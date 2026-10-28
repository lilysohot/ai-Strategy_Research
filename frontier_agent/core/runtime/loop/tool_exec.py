"""Parallel tool execution for the agent loop."""

from __future__ import annotations

import asyncio
import json
import re
import time
from collections.abc import Callable, Coroutine, Mapping
from contextlib import suppress
from dataclasses import replace
from typing import Any, Protocol, runtime_checkable

from frontier_agent.core.loop_types import ToolResult
from frontier_agent.core.tool import Tool, ToolOutcome

__all__ = [
    "PROTECTED_FANIN_TOOLS",
    "TOOL_RESULT_MAX_CHARS",
    "DefaultToolResultPostProcessor",
    "ToolResultPostProcessor",
    "execute_tools",
    "max_tool_wall_time_s",
    "tool_result_text_is_error",
]

TOOL_RESULT_MAX_CHARS = 150_000

_ERROR_PREFIX_RE = re.compile(r"^Error(?:\s*:|\s|$)", re.IGNORECASE)
_BRACKETED_ERROR_RE = re.compile(
    r"^\[[^\]\r\n]*\berror\b[^\]\r\n]*\]",
    re.IGNORECASE,
)
_NEGATED_BRACKETED_ERROR_RE = re.compile(
    r"^\[[^\]\r\n]*\b(?:no|without)\s+error\b[^\]\r\n]*\]",
    re.IGNORECASE,
)
_EXIT_CODE_PREFIX_RE = re.compile(r"^\[Exit code\s+(-?\d+)\]", re.IGNORECASE)
_ERROR_STATUSES = frozenset({"error", "failed", "failure", "timed_out", "timeout"})


def _structured_result_is_error(value: Mapping[object, object]) -> bool:
    """Classify the small set of success fields used by built-in tools."""
    lowered = {str(key).lower(): item for key, item in value.items()}
    ok = lowered.get("ok")
    if isinstance(ok, bool):
        return not ok
    success = lowered.get("success")
    if isinstance(success, bool):
        return not success
    status = lowered.get("status")
    return isinstance(status, str) and status.strip().lower() in _ERROR_STATUSES


def tool_result_text_is_error(text: str) -> bool:
    """Recognise legacy string failures at the tool-result protocol boundary.

    Tool implementations historically returned both ordinary strings and
    bracketed error strings. Keep the compatibility rule prefix-scoped so a
    successful document containing words such as ``Error rate`` is not marked
    failed. New callers should return :class:`~frontier_agent.core.tool.ToolOutcome`
    when they need to classify a result explicitly.
    """
    value = str(text or "").lstrip()
    if _ERROR_PREFIX_RE.match(value):
        return True
    if _BRACKETED_ERROR_RE.match(value) and not _NEGATED_BRACKETED_ERROR_RE.match(value):
        return True
    match = _EXIT_CODE_PREFIX_RE.match(value)
    if match:
        return int(match.group(1)) != 0
    if value.startswith("{"):
        try:
            payload = json.loads(value)
        except (TypeError, ValueError):
            return False
        if isinstance(payload, Mapping):
            return _structured_result_is_error(payload)
    return False


def _tool_return_is_error(raw: Any, rendered: str) -> bool:
    if isinstance(raw, Mapping):
        return _structured_result_is_error(raw)
    return tool_result_text_is_error(rendered)


def _result_cap() -> int:
    """Effective global result cap — :data:`TOOL_RESULT_MAX_CHARS` unless
    ``TOOL_RESULT_MAX_CHARS`` is set in the environment.

    Read per call, not at import: a stress run lowers it to force the truncation
    path on the tools that opt out of a per-tool cap, and a misconfigured value
    must fall back to the default rather than uncapping the context.
    """
    from frontier_agent.infra.config import get_config

    try:
        configured = int(get_config().tool_result_max_chars or 0)
    except Exception:
        return TOOL_RESULT_MAX_CHARS
    return configured if configured > 0 else TOOL_RESULT_MAX_CHARS
_AGGREGATION_TOOLS = frozenset({"collect_reports", "collect_results"})

# Tools that enforce their own wall-clock deadline internally and return a
# STRUCTURED error when it fires. The outer wait must never be shorter than
# that deadline, or the loop cancels the tool mid-flight and the caller gets
# a bare "timed out after Ns" instead of the tool's own diagnosis (partial
# file cleaned up, disk-limit hit, upstream 404, …).
#
# Unlike ``_AGGREGATION_TOOLS`` the deadline is a module constant rather than
# a call argument, so it is declared here as a floor. Keep each entry in sync
# with the owning tool module.
#
# Why this matters now: the agent_team profiles moved ``tool_timeout_s``
# 1800 -> 360 (it doubles as the WallClockGuard reserve floor). That number
# was measured over bash / web_search / web_fetch only — ``download_file``
# was not in the sample and legitimately runs to 660s, so without this floor
# a large download would be cancelled at 360s.
_SELF_TIMING_TOOL_FLOORS: dict[str, int] = {
    # plugins/tools/download_file.py: _TIMEOUT = _TOTAL_TIMEOUT + 60 = 660.
    "download_file": 660,
}

# Tools that read their deadline from the loop instead of owning a constant:
# they call :func:`get_current_tool_budget` and stop at that budget, so the
# outer wait must sit a little ABOVE it. Without the headroom the two
# deadlines are equal and it is a coin flip whether the tool's own error
# ("timed out after 900 seconds" plus a recovery hint) or the loop's bare
# cancel reaches the model.
#
# ``bash`` is the case this exists for: it used to enforce a hardcoded 300s
# regardless of ``tool_timeout_s``, so on the Frontier Challenge every ORCA /
# GROMACS / LAMMPS run died at 5 minutes inside an 1800s budget and the model
# burned turns on chunk-and-restart workarounds. See issue #53.
_BUDGET_AWARE_TOOLS = frozenset({"bash", "web_fetch"})

# Headroom granted to a budget-aware tool between its own deadline and the
# outer wait. Must exceed the sandbox's post-exit output drain
# (``_sandbox._POST_EXIT_DRAIN_S`` = 5s) plus the killed command's teardown,
# output masking, and overflow spill — 30s matches the margin
# ``run_python_code`` already leaves over its inner ``timeout -s KILL``.
_BUDGET_GRACE_S = 30

# Fan-in / orchestration tools whose results carry a sub-agent's actual
# findings. Single source of truth for the set that tiered compaction PROTECTS
# from Tier1 age-based blanking in agent_team (imported by nodes/main_agent.py).
PROTECTED_FANIN_TOOLS = _AGGREGATION_TOOLS | frozenset(
    {"assign_task", "submit_report", "create_subagent", "publish_handoff"}
)


@runtime_checkable
class ToolResultPostProcessor(Protocol):
    """Transforms a :class:`ToolResult` into the string that enters
    the tool-result message in the conversation history.

    Receives the full :class:`ToolResult` (including ``name``, ``args``,
    ``is_error``) so implementations can dispatch per-tool: e.g. a
    ``bash`` processor that keeps stderr + tail of stdout, a
    ``web_fetch`` processor that preserves title + head, a
    ``file_editor`` processor that never truncates.

    Called once per tool result, after the loop's hard 16k safety cap
    from :func:`execute_tools` has already been applied, so the
    processor is working with at most ``TOOL_RESULT_MAX_CHARS`` of
    input. Return value replaces ``tool_result.result`` in the message
    content only — the ``ToolResult`` object itself (observed by
    observers, recorded in evidence) stays unchanged.
    """

    def process(self, tool_result: ToolResult) -> str:
        ...


class DefaultToolResultPostProcessor:
    """Default: apply the configured ``tool_result_max_chars`` cap.

    Mirrors the inline slice that lived in ``agent_loop.py`` before this
    Protocol was extracted. A ``max_chars`` of ``None`` means
    pass-through; otherwise the result is truncated and a tail marker
    is appended so downstream consumers can see that the content was
    cut.
    """

    def __init__(self, max_chars: int | None = None) -> None:
        self._max_chars = max_chars

    def process(self, tool_result: ToolResult) -> str:
        content = tool_result.result
        cap = self._max_chars
        if cap and isinstance(content, str) and len(content) > cap:
            return (
                content[:cap]
                + f"\n\n[... truncated {len(content) - cap} chars past {cap}-char cap]"
            )
        return content if isinstance(content, str) else str(content)


async def execute_tools(
    tool_calls: list[dict],
    tool_map: dict[str, Tool],
    timeout: int,
    turn: int,
    count_offset: int,
    interrupt_waiter: Callable[[dict], Coroutine[Any, Any, bool]] | None = None,
) -> list[ToolResult]:
    """Execute ``tool_calls`` in parallel, returning one ``ToolResult`` each.

    Unknown tools, timeouts, and exceptions all come back as
    ``is_error=True`` results. Long output strings are truncated at
    ``TOOL_RESULT_MAX_CHARS`` with a tail marker so downstream history
    trimming doesn't have to special-case giant tool returns. The cap
    sits at 150K — wide enough that a full academic paper (markdown of a
    Nature/IEEE-length article runs 50-100K chars) and a long Wikipedia
    article fit without truncation. Per-workflow back-stops
    (e.g. swarm's ReasoningStripCompactor at 200K total context) handle
    the multi-fetch case by aging old tool bodies to URL stubs.
    """

    async def _run_one(call: dict, idx: int) -> ToolResult:
        name = call.get("name", "")
        args = call.get("args", {})
        tool_call_id = call.get("id") or f"call_{turn}_{count_offset + idx}"
        tool = tool_map.get(name)
        start = time.monotonic()

        if tool is None:
            available = ", ".join(sorted(tool_map)) or "(none)"
            return ToolResult(
                name=name,
                args=args,
                result=(
                    f"Error: unknown tool '{name}' is not available. "
                    f"Available tools: {available}. Call one of these instead."
                ),
                duration_ms=0,
                tool_call_id=tool_call_id,
                is_error=True,
            )

        effective_timeout = _effective_tool_timeout(name, args, timeout)
        tool_budget = _tool_budget(name, effective_timeout)

        # Count at the shared execution point so every loop contributes to the
        # top-level usage summary. This is a no-op when no meter is bound.
        from frontier_agent.infra.usage_meter import record_tool_call
        record_tool_call(name)

        # Expose this tool's id to nested code via a
        # task-local contextvar so dispatcher tools (delegate_subtask /
        # assign_task) can stamp ``spawn_context.spawned_by_tool_call_id``
        # on the sub-agent they spawn. ``asyncio.gather`` gives each
        # ``_run_one`` task its own context copy so parallel tools don't
        # observe each other's id.
        from frontier_agent.core.execution_context import (
            reset_current_tool_budget,
            reset_current_tool_call_id,
            set_current_tool_budget,
            set_current_tool_call_id,
        )
        _tc_token = set_current_tool_call_id(tool_call_id)
        _budget_token = set_current_tool_budget(tool_budget)
        invoke_task: asyncio.Task | None = None
        interrupt_task: asyncio.Task | None = None
        woke_for_interrupt = False
        try:
            if interrupt_waiter is not None and name in _AGGREGATION_TOOLS:
                invoke_task = asyncio.create_task(asyncio.wait_for(
                    tool.ainvoke(args),
                    timeout=effective_timeout,
                ))
                interrupt_task = asyncio.create_task(interrupt_waiter(call))
                done, _ = await asyncio.wait(
                    {invoke_task, interrupt_task},
                    return_when=asyncio.FIRST_COMPLETED,
                )
                woke_for_interrupt = (
                    interrupt_task in done and bool(interrupt_task.result())
                )
                if woke_for_interrupt and not invoke_task.done():
                    invoke_task.cancel()
                    with suppress(asyncio.CancelledError):
                        await invoke_task
                    elapsed = int((time.monotonic() - start) * 1000)
                    return ToolResult(
                        name=name,
                        args=args,
                        result=(
                            "[interrupted] Waiting for sub-agent reports was "
                            "cancelled because a new user message arrived."
                        ),
                        duration_ms=elapsed,
                        tool_call_id=tool_call_id,
                        is_error=False,
                        interrupted=True,
                    )
                raw = await invoke_task
            else:
                raw = await asyncio.wait_for(
                    tool.ainvoke(args),
                    timeout=effective_timeout,
                )
            explicit_error: bool | None = None
            if isinstance(raw, ToolOutcome):
                explicit_error = raw.is_error
                raw = raw.result
            result_str = str(raw) if raw is not None else ""
            if len(result_str) > _result_cap():
                result_str = _truncate_with_recovery(name, result_str)
            elapsed = int((time.monotonic() - start) * 1000)
            return ToolResult(
                name=name,
                args=args,
                result=result_str,
                duration_ms=elapsed,
                tool_call_id=tool_call_id,
                is_error=(
                    explicit_error
                    if explicit_error is not None
                    else _tool_return_is_error(raw, result_str)
                ),
                # If a report and a user message became ready in the same event
                # loop tick, preserve the real report and still tell the loop
                # to inject the already-claimed user message before its next
                # LLM request.
                interrupted=woke_for_interrupt,
            )
        except TimeoutError:
            elapsed = int((time.monotonic() - start) * 1000)
            return ToolResult(
                name=name,
                args=args,
                result=(
                    f"Error: tool '{name}' timed out after "
                    f"{effective_timeout}s"
                ),
                duration_ms=elapsed,
                tool_call_id=tool_call_id,
                is_error=True,
                interrupted=woke_for_interrupt,
            )
        except Exception as exc:
            elapsed = int((time.monotonic() - start) * 1000)
            return ToolResult(
                name=name,
                args=args,
                result=_invocation_error_text(name, args, tool, exc),
                duration_ms=elapsed,
                tool_call_id=tool_call_id,
                is_error=True,
                interrupted=woke_for_interrupt,
            )
        finally:
            if interrupt_task is not None and not interrupt_task.done():
                interrupt_task.cancel()
                with suppress(asyncio.CancelledError):
                    await interrupt_task
            if invoke_task is not None and not invoke_task.done():
                invoke_task.cancel()
                with suppress(asyncio.CancelledError):
                    await invoke_task
            reset_current_tool_budget(_budget_token)
            reset_current_tool_call_id(_tc_token)

    tasks = [_run_one(call, i) for i, call in enumerate(tool_calls)]
    results = await asyncio.gather(*tasks)
    return _apply_aggregate_budget(list(results))


def _required_argument_names(tool: Tool) -> list[str]:
    """Required argument names from the tool's JSON schema, in declared order."""
    parameters = getattr(tool, "parameters", None) or {}
    required = parameters.get("required") if isinstance(parameters, dict) else None
    if not isinstance(required, list):
        return []
    return [str(field) for field in required]


def _invocation_error_text(
    name: str, args: object, tool: Tool, exc: BaseException,
) -> str:
    """Model-facing text for a tool that failed before doing any work.

    A missing required argument arrives as ``TypeError: web_search() missing 1
    required positional argument: 'q'``. That says nothing about what the model
    should do next, and in a live team run it was the only signal the model got
    for a call it could have trivially corrected. Name the missing fields and
    the full required set instead; the tool never ran, so nothing is ambiguous.
    """
    if isinstance(exc, TypeError) and "required positional argument" in str(exc):
        required = _required_argument_names(tool)
        supplied = args if isinstance(args, dict) else {}
        missing = [field for field in required if field not in supplied]
        if missing:
            return (
                f"Error: tool '{name}' was called without required argument(s): "
                f"{', '.join(missing)}. Pass every required field as a named "
                f"argument (required: {', '.join(required)}); the tool did not run."
            )
    return f"Error: {type(exc).__name__}: {exc}"


def _effective_tool_timeout(name: str, args: dict, default_timeout: int) -> int:
    """Return the outer wait timeout for one tool call.

    Aggregation tools already accept their own ``timeout`` argument and
    use it to bound the internal wait. The outer loop timeout must not
    be shorter than that value, otherwise a profile-level 60s
    ``tool_timeout`` cancels ``collect_reports(timeout=1800)`` before
    the tool's own wait semantics can run.

    Tools in :data:`_SELF_TIMING_TOOL_FLOORS` own a fixed internal deadline
    instead of taking one as an argument; the same rule applies, with the
    floor read from the table.

    Tools in :data:`_BUDGET_AWARE_TOOLS` invert the relationship — they take
    their deadline FROM the loop via ``get_current_tool_budget`` — so the outer
    wait is the configured timeout plus :data:`_BUDGET_GRACE_S`, leaving the
    tool room to report its own timeout first. Their budget comes back from
    :func:`_tool_budget`.
    """
    floor = _SELF_TIMING_TOOL_FLOORS.get(name)
    if floor is not None:
        return max(int(default_timeout), floor)
    if name in _BUDGET_AWARE_TOOLS:
        return int(default_timeout) + _BUDGET_GRACE_S
    if name not in _AGGREGATION_TOOLS:
        return int(default_timeout)
    requested = 0
    if isinstance(args, dict):
        try:
            requested = int(float(args.get("timeout", 0) or 0))
        except (TypeError, ValueError):
            requested = 0
    if requested <= 0:
        return int(default_timeout)
    return max(int(default_timeout), requested + 5)


def _truncate_with_recovery(name: str, result: str) -> str:
    """Cut a result to :data:`TOOL_RESULT_MAX_CHARS`, spilling the middle first.

    This cap is the ONLY one that applies to the tools whose ``ToolMeta`` sets
    ``max_result_chars=0`` — web_fetch / web_search / read_file, where content
    density is judged to reward full bodies. For those, ``maybe_overflow`` is a
    documented no-op, so before this the discarded remainder was simply gone: a
    300K paper lost its second half with nothing on disk and no path to recover
    it, which is the opposite of what every other truncation in the system does
    (``maybe_overflow`` and ``spill_compacted_body`` both persist before cutting).

    Spill is best-effort by design — a backend with no agent-readable filesystem
    returns no path — so the marker degrades to the plain char count rather than
    failing the tool call.
    """
    from plugins.tools._overflow import budgeted_preview, spill_compacted_body

    try:
        ref = spill_compacted_body(name, result)
    except Exception:  # pragma: no cover - diagnostics must not fail a tool call
        ref = None
    return budgeted_preview(result, cap=_result_cap(), ref=ref or "", tool_name=name)


def _apply_aggregate_budget(results: list[ToolResult]) -> list[ToolResult]:
    """Hold one turn's tool results to the per-turn total.

    Every cap above this one is per result, so N parallel calls each landing just
    under their own cap still add up without bound — and the uncapped tools cap
    at 150K EACH, so two fetches in one turn can outweigh the whole rest of the
    context. The budget existed but had no call site; this is it.
    """
    from plugins.tools._overflow import (
        MAX_AGGREGATE_RESULT_CHARS,
        check_aggregate_budget,
    )

    if sum(len(r.result) for r in results) <= MAX_AGGREGATE_RESULT_CHARS:
        return results
    bodies = check_aggregate_budget(
        [r.result for r in results], [r.name for r in results],
    )
    return [
        r if body == r.result else replace(r, result=body)
        for r, body in zip(results, bodies, strict=True)
    ]


def _tool_budget(name: str, effective_timeout: int) -> float | None:
    """Return the deadline to publish to the tool, or ``None`` to leave it alone.

    Only :data:`_BUDGET_AWARE_TOOLS` get a budget; every other tool either has
    no internal deadline or owns a fixed one that
    :func:`_effective_tool_timeout` already floors, and handing those a number
    they would ignore only invites a future reader to wire it up backwards.

    The budget is the outer wait minus :data:`_BUDGET_GRACE_S` — i.e. exactly
    the configured ``tool_timeout`` — so the tool's own deadline fires first.
    """
    if name not in _BUDGET_AWARE_TOOLS:
        return None
    return float(max(effective_timeout - _BUDGET_GRACE_S, 1))


def max_tool_wall_time_s(tool_timeout: float) -> float:
    """Longest a single tool call can occupy the loop, for this configured
    ``tool_timeout``.

    Wall-clock reserves must budget against THIS rather than the configured
    value. A budget-aware tool's outer wait is deliberately ``tool_timeout +
    _BUDGET_GRACE_S`` so the tool reports its own timeout instead of being
    cancelled mid-flight — which means a tool started just before the research
    deadline overruns it by the grace as well, eating into the reserve that
    finalization was promised.

    Note this does NOT fold in :data:`_SELF_TIMING_TOOL_FLOORS`. ``download_file``
    can already outlast a small ``tool_timeout`` (its floor is 660s) and the
    reserves never accounted for that either; correcting it would silently move
    agent_team's research window by several minutes, so it is left as its own
    decision rather than smuggled in here.
    """
    return max(float(tool_timeout), 0.0) + _BUDGET_GRACE_S
