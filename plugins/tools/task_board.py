"""task_board — a per-run task board for the coordinator (main agent)."""

from __future__ import annotations

import ast
import json
import logging
import re
from collections.abc import Iterable
from contextlib import suppress
from copy import deepcopy
from typing import Any

from pydantic import ValidationError

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.components.observers.task_board import TaskBoardObserver
from frontier_agent.components.task_board_types import (
    BOARD_TOOLS,
    RESOLUTION_MARKS,
    VALID_RESOLUTION,
    BoardCounts,
    count_resolutions,
)
from frontier_agent.core.execution_context import get_current_execution_scope
from frontier_agent.core.runtime import registry
from frontier_agent.core.tool import tool
from plugins.tools._bus_scope import SWARM_SCOPE_KEY, resolve_bus_task_id
from plugins.tools._coerce import coerce_json_list, coerce_json_object
from plugins.tools._task_board_contract import BoardAdd, BoardUpdate

logger = logging.getLogger(__name__)

_VERIFICATION_TASK = re.compile(
    r"^\s*(?:核验|验证|复核|交叉核验|交叉验证|终审)"
    r"|(?:最终|终审|独立|交叉|全面|全部|所有).{0,12}(?:核验|验证|复核)"
    r"|^\s*(?:verify|validate|audit|cross[- ]?check)\b",
    re.IGNORECASE,
)

# task_id -> {"seq": int, "tasks": {id: {description, resolution, owners, group}}}
_BOARDS: dict[str, dict[str, Any]] = {}

# task_id -> list of pending board write-ops the stream observer has not yet
# drained. Each op is ``{"op": "add"|"update"|"finish_planning", "ids": [...],
# "phase": "planning"|"execution"}``. The board tools append here on every write;
# A task-board stream observer drains them and emits one
# ``response.swarm.task_board`` frame per op. Recording is unconditional + cheap (the
# eval / HTTP paths simply never drain), and ``clear_board`` empties it at run end
# so it can never leak across trials.
_PENDING_OPS: dict[str, list[dict[str, Any]]] = {}


def _record_op(task_id: str, op: str, ids: list[str] | None = None) -> None:
    """Append a board write-op for the stream observer to drain.

    The op stamps the phase AT WRITE TIME. In the agent-team two-loop profile the
    stream observer is not attached to the planning loop, so ops written there are
    drained late (once the execution loop runs) — by then the phase has flipped to
    ``execution``. Freezing the write-time phase keeps a planning-loop ``add_task``
    rendered as ``phase=planning`` rather than the phase current at drain time.
    """
    _PENDING_OPS.setdefault(task_id, []).append(
        {"op": op, "ids": list(ids or []), "phase": current_phase(task_id)}
    )


# ── State helpers (also used by the observer + finalize_answer gate) ────────

def _board(task_id: str) -> dict[str, Any]:
    return _BOARDS.setdefault(task_id, {"seq": 0, "tasks": {}})


def _verification_required(item: dict[str, Any], description: str) -> bool:
    """Recognize explicit verification gates; ordinary research stays unchanged."""
    return (
        item.get("verification_required") is True
        or bool(coerce_json_list(item.get("verification_requirements")))
        or bool(_VERIFICATION_TASK.search(description))
    )


_CHECK_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,80}$")


def _verification_requirements(
    item: dict[str, Any],
    *,
    task_id: str,
    description: str,
    required: bool,
) -> list[dict[str, str]]:
    """Give every planned verification gate stable, externally visible checks."""
    if not required:
        return []
    out: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in coerce_json_list(item.get("verification_requirements")) or []:
        requirement = coerce_json_object(raw)
        if requirement is None:
            continue
        check_id = str(requirement.get("check_id") or "").strip()
        criterion = str(requirement.get("criterion") or "").strip()
        if not _CHECK_ID.fullmatch(check_id) or not criterion or check_id in seen:
            continue
        seen.add(check_id)
        out.append({"check_id": check_id, "criterion": criterion[:2000]})
    # Auto-recognized verification tasks still become durable plan entries.
    # If the model never dispatches this identity, finalization reports it as a
    # missing check instead of forgetting the intent entirely.
    return out or [{"check_id": f"{task_id}.required", "criterion": description[:2000]}]


def _team_verification_gate_enabled(scope: Any) -> bool:
    """Identify team coordinator runs, including planning_mode=false profiles."""
    metadata = getattr(scope, "metadata", None) or {}
    return SWARM_SCOPE_KEY in metadata or planning_enabled(scope.task_id)


def _planned_check_update(
    scope: Any, tid: str, task: dict[str, Any], item: dict[str, Any],
    *, tasks: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Validate one authoritative definition before changing any task fields."""
    if not _verification_required(item, str(task.get("description") or "")):
        return {}
    proposed = _verification_requirements(
        item, task_id=tid, description=task["description"], required=True,
    ) if item.get("verification_requirements") is not None else (
        task.get("verification_requirements") or _verification_requirements(
            {}, task_id=tid, description=task["description"], required=True,
        )
    )
    if proposed != task.get("verification_requirements"):
        bus = registry.get_optional(AgentBus)
        if bus and any(
            check.get("work_item_id") == tid
            for entry in bus.list_task_jobs(resolve_bus_task_id(scope))
            for check in entry.item.metadata.get("verification_checks", [])
        ):
            raise ValueError("dispatched verification requirements are immutable; recheck the same IDs")
    occupied = {
        check["check_id"] for other_id, other in (
            tasks if tasks is not None else _board(scope.task_id)["tasks"]
        ).items()
        if other_id != tid and not other.get("archived")
        for check in other.get("verification_requirements", [])
    }
    if occupied.intersection(check["check_id"] for check in proposed):
        raise ValueError("planned check_id already belongs to another task")
    return {"verification_required": True, "verification_requirements": proposed}


def board_size(task_id: str) -> int:
    """Number of tasks on this task's board (0 if no board)."""
    b = _BOARDS.get(task_id)
    return sum(not t.get("archived") for t in b["tasks"].values()) if b else 0


def _progress_fields(item: dict[str, Any]) -> dict[str, Any]:
    """Retain model-declared progress separately from tool verification verdicts."""
    fields: dict[str, Any] = {}
    for key in ("done_when", "notes", "gap"):
        if key in item and isinstance(item[key], str):
            fields[key] = item[key].strip()[:2000]
    if item.get("kind") in ("research", "verification", "delivery"):
        fields["kind"] = item["kind"]
    if isinstance(item.get("evidence_refs"), list):
        fields["evidence_refs"] = list(dict.fromkeys(
            ref[:1000] for ref in item["evidence_refs"] if isinstance(ref, str) and ref.strip()
        ))[:20]
    return fields


def record_verification(name: str, *, passed: bool, detail: str) -> None:
    """Record a tool verdict separately from the model's completion judgment."""
    scope = get_current_execution_scope()
    if scope is None:
        return
    board = _board(scope.task_id)
    tid = f"verification:{name}"
    op = "update" if tid in board["tasks"] else "add"
    board["tasks"][tid] = {
        "description": detail, "resolution": "resolved" if passed else "open",
        "owners": [], "group": "工具校验", "verification_ok": passed,
    }
    _record_op(scope.task_id, op, [tid])


def build_task_board_observer(*, cooldown_turns: int = 5) -> TaskBoardObserver:
    """Bind the shared observer to this plugin's task-board state."""
    return TaskBoardObserver(
        board_size=board_size,
        render_board=lambda task_id, bus_task_id: render_board(
            task_id, bus_task_id=bus_task_id,
        ),
        resolve_bus_task_id=resolve_bus_task_id,
        cooldown_turns=cooldown_turns,
    )


def clear_board(task_id: str) -> None:
    """Drop a task's board + phase — called at the end of the main-agent run."""
    _BOARDS.pop(task_id, None)
    _PHASE.pop(task_id, None)
    _PENDING_OPS.pop(task_id, None)


def restore_board_from_messages(
    task_id: str, messages: Iterable[Any], *, archive: bool = False,
) -> int:
    """Rebuild a continued Run's task board from replayed tool calls.

    Conversation replay preserves the model-visible add_task and update_task
    calls, but the in-memory board is intentionally cleared when each Run ends.
    Replaying only the messages therefore leaves the next Run with a convincing
    board transcript and no matching state. Rebuild that state before the loop so
    the first resumed update_task addresses the same ids the model can see.

    Call arguments carry task data. The short update receipt identifies accepted
    ids so a rejected update cannot become successful on replay. Legacy receipts
    without structured id lists remain readable. Malformed calls are ignored.
    """
    clear_board(task_id)
    board = _board(task_id)
    messages = list(messages)
    receipts = {
        str(message.get("tool_call_id")): message.get("content")
        for message in messages
        if isinstance(message, dict) and message.get("role") == "tool"
    }

    def arguments(call: Any) -> tuple[str, dict[str, Any] | None]:
        if not isinstance(call, dict):
            return "", None
        function = call.get("function")
        if not isinstance(function, dict):
            return "", None
        name = str(function.get("name") or "")
        raw = function.get("arguments")
        if isinstance(raw, dict):
            return name, raw
        if not isinstance(raw, str):
            return name, None
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return name, None
        return name, parsed if isinstance(parsed, dict) else None

    for message in messages:
        if not isinstance(message, dict) or message.get("role") != "assistant":
            continue
        for call in message.get("tool_calls") or []:
            name, args = arguments(call)
            if args is None:
                continue
            if name == "add_task":
                receipt = receipts.get(str(call.get("id")))
                if isinstance(receipt, str) and receipt.startswith("Error:"):
                    continue
                items = coerce_json_list(args.get("tasks")) or []
                existing = {
                    task["description"].strip(): tid
                    for tid, task in board["tasks"].items()
                }
                for raw in items:
                    item = coerce_json_object(raw)
                    if item is None:
                        continue
                    description = str(item.get("description") or "").strip()
                    if not description:
                        continue
                    if description in existing:
                        tid = existing[description]
                        board["tasks"][tid].update(_progress_fields(item))
                        required = _verification_required(item, description)
                        if required:
                            board["tasks"][tid]["verification_required"] = True
                            if item.get("verification_requirements") is not None:
                                board["tasks"][tid]["verification_requirements"] = (
                                    _verification_requirements(
                                        item,
                                        task_id=tid,
                                        description=description,
                                        required=True,
                                    )
                                )
                        continue
                    board["seq"] += 1
                    tid = f"t{board['seq']}"
                    required = _verification_required(item, description)
                    board["tasks"][tid] = {
                        **_progress_fields(item),
                        "description": description,
                        "resolution": "open",
                        "owners": _as_owner_list(item.get("owner") or item.get("owners")),
                        "group": str(item.get("group") or "").strip(),
                        "verification_required": required,
                        "verification_requirements": _verification_requirements(
                            item,
                            task_id=tid,
                            description=description,
                            required=required,
                        ),
                    }
                    existing[description] = tid
            elif name == "update_task":
                receipt = receipts.get(str(call.get("id")))
                accepted: set[str] | None = None
                progress_ids: set[str] = set()
                actual_resolutions: dict[str, str] = {}
                if isinstance(receipt, str):
                    actual_resolutions = dict(re.findall(
                        r"^\s*[○▶✓⊘!]\s+(t\d+)\s+(open|in_progress|resolved|cancelled|blocked)\s",
                        receipt, re.MULTILINE,
                    ))
                    progress_match = re.search(r"Progress recorded (\[[^\n]*\]);", receipt)
                    if progress_match:
                        with suppress(ValueError, SyntaxError, TypeError):
                            progress_ids = set(ast.literal_eval(progress_match[1]))
                    match = re.search(r"^Updated (\[[^\n]*\])\.", receipt, re.MULTILINE)
                    if match:
                        try:
                            accepted = set(ast.literal_eval(match[1]))
                        except (ValueError, SyntaxError, TypeError):
                            accepted = set()
                    elif receipt.startswith("Error:"):
                        accepted = set()
                for raw in coerce_json_list(args.get("updates")) or []:
                    update = coerce_json_object(raw)
                    if update is None:
                        continue
                    tid = str(update.get("id") or "")
                    if accepted is not None and tid not in accepted and tid not in progress_ids:
                        continue
                    task = board["tasks"].get(tid)
                    if task is None:
                        continue
                    if update.get("verification_requirements") is not None:
                        task["verification_required"] = True
                        task["verification_requirements"] = _verification_requirements(
                            update, task_id=tid, description=task["description"], required=True,
                        )
                    if tid in progress_ids and (accepted is None or tid not in accepted):
                        task.update(_progress_fields(update))
                        continue
                    resolution = actual_resolutions.get(tid, str(update.get("resolution") or "").strip())
                    if resolution in VALID_RESOLUTION:
                        task["resolution"] = resolution
                    task.update(_progress_fields(update))
                    owners = _as_owner_list(update.get("owner") or update.get("owners"))
                    if owners:
                        if update.get("replace_owners"):
                            task["owners"] = owners
                        else:
                            for owner in owners:
                                if owner not in task["owners"]:
                                    task["owners"].append(owner)

    if not board["tasks"]:
        _BOARDS.pop(task_id, None)
        return 0
    # Make the restored snapshot visible to the stream/UI on the resumed Run.
    if archive:
        # Preserve identities for explicit continuation, outside this round's progress.
        for task in board["tasks"].values():
            task["archived"] = True
    else:
        _record_op(task_id, "add", list(board["tasks"]))
    return len(board["tasks"])


# ── Task-board stream projection — pure read helpers ─────────────────────────
# Consumed by the protocol layer's task-board stream observer
# to build the ``task_board.*`` wire frames. Kept here (next to the state they
# read) and side-effect-free so the observer stays a thin emitter.

def current_phase(task_id: str) -> str:
    """The board's coordinator phase — ``planning`` or ``execution``.

    Defaults to ``execution`` when the run never entered Planning Mode
    (``planning_mode:false`` profiles — apodex production — never call
    ``start_planning``, so ``_PHASE`` has no entry and the board is live in
    execution from the first ``add_task``)."""
    return _PHASE.get(task_id, "execution")


def serialize_tasks(task_id: str, ids: list[str]) -> list[dict[str, Any]]:
    """Render the given task ids to the wire shape, reading CURRENT board state.

    Reading the live ``resolution`` (rather than assuming ``open``) matters: an
    ``add_task`` that de-dups onto an already-``resolved`` id must carry that
    real resolution, or the frontend's whole-row replace would roll the task
    back to ``open`` and regress progress. Ids no longer on the
    board (raced clear) are skipped rather than emitted as ghosts."""
    b = _BOARDS.get(task_id)
    if not b:
        return []
    out: list[dict[str, Any]] = []
    for tid in ids:
        t = b["tasks"].get(tid)
        if t is None or t.get("archived"):
            continue
        serialized = {
            **_progress_fields(t),
            "id": tid,
            "description": t.get("description", ""),
            "resolution": t.get("resolution", "open"),
            "owners": list(t.get("owners") or []),
            "group": t.get("group", ""),
        }
        if t.get("verification_required"):
            serialized["verification_required"] = True
            serialized["verification_requirements"] = [
                dict(item) for item in t.get("verification_requirements") or []
            ]
            bus = registry.get_optional(AgentBus)
            scope = get_current_execution_scope()
            bus_task_id = resolve_bus_task_id(scope) if scope and scope.task_id == task_id else task_id
            if bus is not None:
                from plugins.tools._verification import work_item_verification_progress

                serialized.update(work_item_verification_progress(
                    bus, bus_task_id, tid,
                    [item["check_id"] for item in serialized["verification_requirements"]],
                ))
        out.append(serialized)
    return out


def snapshot_tasks(task_id: str) -> list[dict[str, Any]]:
    """Return the complete board in display order for UI projections.

    Unlike :func:`render_board`, this keeps task data structured so a client
    can render a real board instead of scraping the human-readable tool result.
    """
    b = _BOARDS.get(task_id)
    if not b:
        return []
    return serialize_tasks(task_id, list(b["tasks"]))


def drain_board_ops(task_id: str) -> list[dict[str, Any]]:
    """Pop and return all pending board write-ops for this task (FIFO)."""
    return _PENDING_OPS.pop(task_id, [])


# ── Planning Mode (two-phase state machine) ─────────────────────────────────
# task_id -> "planning" | "execution". Default (no entry) = execution, so ONLY
# the agent-team main agent (which calls start_planning) is ever gated; every
# other caller / workflow is unaffected.
_PHASE: dict[str, str] = {}
# In Planning Mode the agent is a PLANNER, not a solver: it may use only
# READ-ONLY tools (to understand the problem / look up a basic term) plus the
# board tools. EVERYTHING ELSE — team building, dispatch, code/file writes,
# finalize — is blocked until it calls finish_planning. This is an ALLOWLIST
# (the complement is blocked) so a newly-added write tool is denied by default.
_PLANNING_ALLOWED = (
    # read-only inspection / understanding
    "grep_search", "glob_search", "read_file", "read_text", "view_image",
    "web_search", "web_fetch",
    # board tools
    "add_task", "update_task", "finish_planning",
)


def start_planning(task_id: str) -> None:
    _PHASE[task_id] = "planning"


def force_finish_planning(task_id: str) -> None:
    """Flip a task out of Planning Mode WITHOUT the empty-board guard the
    ``finish_planning`` tool enforces. Used by the planning-turn-cap path
    (auto-finish at ``planning_max_turns``) and by the two-loop driver after a
    planning loop that ended on max_turns rather than an explicit finish."""
    if task_id in _PHASE:
        _PHASE[task_id] = "execution"


def is_planning_allowed(tool_name: str) -> bool:
    """True if ``tool_name`` may run during Planning Mode (read-only / board)."""
    return tool_name in _PLANNING_ALLOWED


def in_planning(task_id: str) -> bool:
    return _PHASE.get(task_id) == "planning"


def planning_enabled(task_id: str) -> bool:
    """True if this run enabled Planning Mode (start_planning was called) —
    stays True after finish_planning, so the no-solo / verify finalize gates
    keep applying through execution. ``False`` for non-planning runs."""
    return task_id in _PHASE


def planning_block_message(task_id: str, tool_name: str) -> str | None:
    """Error string to return when ``tool_name`` is called during Planning Mode;
    ``None`` when the call is allowed. No-op unless start_planning() was called
    for this task (i.e. only the agent-team main agent)."""
    if in_planning(task_id) and not is_planning_allowed(tool_name):
        return (
            f"Blocked: `{tool_name}` is unavailable in PLANNING MODE. You are a "
            "PLANNER here — use only READ-ONLY tools (grep_search / glob_search "
            "/ web_search to understand the problem) and the board tools "
            "(add_task / update_task). List EVERY sub-question via add_task, "
            "then call finish_planning() to unlock the team."
        )
    return None


def unresolved_task_ids(task_id: str) -> list[str]:
    """Ids still requiring work — open or in_progress. ``[]`` if no board.

    Cancelled tasks are retracted work (dropped on purpose / created in error),
    while blocked tasks retain gaps for partial publication. Neither prevents
    ending execution; blocked tasks still downgrade the final report."""
    b = _BOARDS.get(task_id)
    if not b:
        return []
    return [
        tid for tid, t in b["tasks"].items()
        if not t.get("archived") and t.get("resolution") not in ("resolved", "cancelled", "blocked")
    ]


def complete_delivery_tasks(task_id: str) -> None:
    """Only an accepted final answer, not a board claim, completes delivery."""
    board = _BOARDS.get(task_id)
    if not board:
        return
    changed = []
    for tid, task in board["tasks"].items():
        if (not task.get("archived") and task.get("kind") == "delivery"
                and not task.get("verification_required")
                and task.get("resolution") in {"open", "in_progress"}):
            task["resolution"] = "resolved"
            changed.append(tid)
    if changed:
        _record_op(task_id, "update", changed)


def _exec_status_by_owner(task_id: str) -> dict[str, str]:
    """Map owner sub-agent name -> coarse execution status, derived from the bus.

    This is the system-owned half of the board: the model never writes it, so
    the model's ``resolution`` verdict can never clobber the live run state.
    """
    bus = registry.get_optional(AgentBus)
    if bus is None:
        return {}
    out: dict[str, str] = {}
    try:
        sessions = bus.list_sessions_for_task(task_id)
    except Exception:
        return {}
    for s in sessions:
        if getattr(s, "current_job_id", None) is not None:
            st = "running"
        elif getattr(s, "pending_tasks", None):
            st = "queued"
        elif getattr(s, "total_task_count", 0) == 0:
            st = "created"
        else:
            st = "reported"
        out[s.name] = st
    return out


def render_board(task_id: str, *, bus_task_id: str | None = None) -> str:
    """Render the board, joining model fields with live bus exec-status."""
    b = _BOARDS.get(task_id)
    if not b or not b["tasks"]:
        return "[task board] empty — call add_task to register sub-questions."
    tasks = {tid: t for tid, t in b["tasks"].items() if not t.get("archived")}
    c = count_resolutions(t["resolution"] for t in tasks.values())
    lines = [
        f"[task board] resolved {c.resolved}/{c.active} · "
        f"in-progress {c.in_progress} · "
        f"open {c.open} · cancelled {c.cancelled} · blocked {c.blocked}"
    ]
    # The owners/exec column only makes sense when there IS a team: in a solo
    # run (e.g. react) no task is ever assigned, so showing "agents=[unassigned]"
    # on every row is pure noise. Drop the whole column unless at least one task
    # has an owner — then skip the bus query too (nothing to join against).
    show_owners = any(t.get("owners") for t in tasks.values())
    exec_by_owner = _exec_status_by_owner(bus_task_id or task_id) if show_owners else {}
    for tid, t in tasks.items():
        row = (
            f"  {RESOLUTION_MARKS.get(t['resolution'], '○')} {tid} "
            f"{t['resolution']:<11} "
        )
        if show_owners:
            owners = t.get("owners") or []
            # one "name:exec_status" per owning agent, so the coordinator sees
            # exactly who is on this task and how far each has got.
            agents = (
                " · ".join(f"{o}:{exec_by_owner.get(o, '?')}" for o in owners)
                if owners else "unassigned"
            )
            row += f"agents=[{agents}]  "
        lines.append(f"{row}{t['description'][:80]}")
        for key in ("done_when", "notes", "gap"):
            if t.get(key):
                lines.append(f"    {key}: {t[key]}")
        if t.get("verification_required"):
            lines.append("    verification_requirements: " + json.dumps(
                t.get("verification_requirements", []), ensure_ascii=False,
            ))
            projected = serialize_tasks(task_id, [tid])[0]
            if "verification_status" in projected:
                lines.append(
                    f"    verification_execution_status: {projected['verification_execution_status']}; "
                    f"verification_status: {projected['verification_status']}"
                )
    return "\n".join(lines)


# ── Tools ───────────────────────────────────────────────────────────────────

def _as_owner_list(val: Any) -> list[str]:
    """Normalise an ``owner`` field (a name, a comma-string, or a list of names)
    into a clean list of agent names. One task can have MANY owners — several
    agents attacking the SAME sub-question from different angles for
    corroboration are all owners of that one task (not separate tasks)."""
    if val is None:
        return []
    items = val if isinstance(val, list) else str(val).split(",")
    out: list[str] = []
    for x in items:
        name = str(x).strip()
        if name and name not in out:
            out.append(name)
    return out


@tool
async def add_task(tasks: list[BoardAdd]) -> str:
    """Register the work items / sub-questions for this run on the task board.

    This is your plan and external memory. Call it up front — before doing any
    real work (fetching, running code, gathering evidence) — once you've broken
    the question into the concrete steps you'll work through, and again whenever
    a new sub-question emerges. (Reasoning, and a few clarifying searches to
    understand the problem, may come first.) Duplicate descriptions are
    de-duplicated (you get the existing id).

    Args:
        tasks: a list, each item ``{"description": str}``:
            - description (required): ONE concrete, checkable work item, e.g.
              "Verify the Markov condition Δω ≫ system rate holds" — not a vague
              area like "look into the math".
            - notes: completion basis or reason for cancelling; required in Web research.
            - gap: the specific remaining question; empty once answered.
            - evidence_refs: source URLs or evidence handles supporting the progress claim.
              These are model-declared pointers, not proof of successful verification.
            - kind: research | verification | delivery. Keep delivery separate from research.
            - done_when: finite acceptance criterion tied to the user's question.
            - owner (OPTIONAL, multi-agent runs only): if a teammate sub-agent is
              already assigned to this item, name it here (a name, comma-string,
              or list — a task may have many). In a solo run, just OMIT it.
            - verification_required (OPTIONAL): set true when completion means an
              independent, version-bound check. Tasks explicitly beginning with
              Verify/核验/验证/复核 are treated this way automatically. Such an item
              cannot resolve until its required verification_checks pass.
            - verification_requirements (OPTIONAL): stable planned checks as
              ``[{"check_id": "amount", "criterion": "Recompute total"}]``.
              Dispatch verification_checks with the same ids. An auto-recognized
              verification task gets ``<task-id>.required`` when this is omitted.

    Returns:
        The assigned ids plus the rendered board.
    """
    items = coerce_json_list(tasks) or []
    scope = get_current_execution_scope()
    if scope is None:
        return "Error: add_task can only be called inside an active run."
    if not items:
        return "Error: add_task requires at least one {description} item."
    # A rejected batch must not leave unreceipted rows or half-written definitions.
    b = deepcopy(_board(scope.task_id))
    existing = {t["description"].strip(): tid for tid, t in b["tasks"].items()}
    new_ids: list[str] = []
    reused_ids: list[str] = []
    skipped = 0  # items that weren't usable {description} objects
    for raw in items:
        it = raw.model_dump(exclude_unset=True) if isinstance(raw, BoardAdd) else coerce_json_object(raw)
        if it is None:
            skipped += 1
            continue
        try:
            it = BoardAdd.model_validate(it).model_dump(exclude_unset=True, exclude_none=True)
        except ValidationError as exc:
            return f"Error: invalid add_task item: {exc}"
        desc = str(it.get("description", "")).strip()
        if not desc:
            skipped += 1
            continue
        if desc in existing:  # dedup re-decomposition
            tid = existing[desc]
            task = b["tasks"][tid]
            try:
                planned = _planned_check_update(scope, tid, task, it, tasks=b["tasks"])
            except ValueError as exc:
                return f"Error: {tid}: {exc}"
            task.pop("archived", None)
            task.update(_progress_fields(it))
            task.update(planned)
            new_ids.append(tid)
            reused_ids.append(tid)
            continue
        tid = f"t{b['seq'] + 1}"
        try:
            _planned_check_update(scope, tid, {"description": desc}, it, tasks=b["tasks"])
        except ValueError as exc:
            return f"Error: {tid}: {exc}"
        b["seq"] += 1
        required = _verification_required(it, desc)
        b["tasks"][tid] = {
            **_progress_fields(it),
            "description": desc,
            "resolution": "open",
            "owners": _as_owner_list(it.get("owner") or it.get("owners")),
            "group": str(it.get("group", "")).strip(),
            "verification_required": required,
            "verification_requirements": _verification_requirements(
                it,
                task_id=tid,
                description=desc,
                required=required,
            ),
        }
        existing[desc] = tid
        new_ids.append(tid)
    logger.info(
        "add_task(task=%s): +%d skipped=%d (ids=%s)",
        scope.task_id, len(new_ids), skipped, new_ids,
    )
    # Nothing landed but items were passed → the shape was wrong. Return a
    # corrective error (not a silent "Added []") so the model re-sends the right
    # shape instead of burning turns repeating the mistake.
    if not new_ids:
        return (
            'Error: add_task expects a list of objects like '
            '[{"description": "..."}]; none of the items were usable, so nothing '
            'was added. Re-call with each task as its own '
            '{"description": "<one concrete work item>"}.'
        )
    _BOARDS[scope.task_id] = b
    _record_op(scope.task_id, "add", new_ids)
    msg = f"Added {new_ids}.\n{render_board(scope.task_id, bus_task_id=resolve_bus_task_id(scope))}"
    if reused_ids:
        msg += f"\nReused existing IDs {reused_ids}; no duplicate tasks created for these items."
    if skipped:
        msg += (
            f'\nNote: {skipped} item(s) were skipped (not a {{"description": ...}} '
            "object). Re-add them with that shape if still needed."
        )
    return msg


@tool
async def update_task(updates: list[BoardUpdate]) -> str:
    """Mark progress on the board — call this the MOMENT a task finishes.

    Updating a historical task explicitly resumes it in the current round.
    Update each task as soon as it is done, before starting the next one; don't
    let finished tasks pile up. The arg is a LIST only to cover the case where
    two tasks finished in the SAME turn (resolve both at once) — it is NOT a
    reason to batch resolutions across turns. Returns the full updated board.

    Args:
        updates: a list of ``{"id", "resolution"?}`` items:
            - id (required): task id from add_task, e.g. "t3".
            - resolution: "in_progress" (set this the MOMENT you start working a
              task — it marks the one you are on now) | "resolved" (the work item
              is answered AND corroborated — your judgment, not merely "I glanced
              at it") | "cancelled" (retract a task you no longer need or created
              in error — it stops counting toward unresolved work; the id stays
              on the board for the trail) | "open" (the default; not started).
            - notes: completion basis or cancellation reason; required to close Web tasks.
            - gap: exact remaining question; empty once answered.
            - evidence_refs: model-declared source URLs or evidence handles (not validation).
            - kind: research | verification | delivery.
            - done_when: finite completion criterion for this user question.
            - verification_requirements: planned check IDs and criteria. May be
              updated before dispatch; dispatched definitions are immutable.
            - resolution='blocked': stop work with an explicit notes and gap.
              Allows partial delivery, never marks missing checks as passed.
            - Team delivery items become resolved only when the final answer is
              accepted. Marking them resolved here stages them as in_progress.
            - owner (OPTIONAL, multi-agent runs only): teammate sub-agent
              name(s) now working it — ADDED to the task's owner list (a name,
              comma-string, or list). Set "replace_owners": true to overwrite
              instead of add. Omit entirely in a solo run.

    Returns:
        The full updated task board (+ any per-item errors).
    """
    items = coerce_json_list(updates) or []
    scope = get_current_execution_scope()
    if scope is None:
        return "Error: update_task can only be called inside an active run."
    b = _BOARDS.get(scope.task_id)
    if not b:
        return "Error: no task board yet — call add_task first."
    changed: list[str] = []
    progress_only: list[str] = []
    errors: list[str] = []
    for raw in items:
        u = raw.model_dump(exclude_unset=True) if isinstance(raw, BoardUpdate) else coerce_json_object(raw)
        if u is None:
            continue
        try:
            u = BoardUpdate.model_validate(u).model_dump(exclude_unset=True, exclude_none=True)
        except ValidationError as exc:
            errors.append(f"invalid update_task item: {exc}")
            continue
        tid = str(u.get("id", ""))
        if tid not in b["tasks"]:
            errors.append(f"{tid or '?'}: no such task")
            continue
        res = str(u.get("resolution", "")).strip()
        if res and res not in VALID_RESOLUTION:
            errors.append(f"{tid}: bad resolution {res!r} (use {VALID_RESOLUTION})")
            continue
        t = b["tasks"][tid]
        progress = _progress_fields(u)
        try:
            planned = _planned_check_update(scope, tid, t, u)
        except ValueError as exc:
            errors.append(f"{tid}: {exc}")
            continue
        if res == "blocked" and not (
            (progress.get("notes") or t.get("notes"))
            and (progress.get("gap") or t.get("gap"))
        ):
            errors.append(f"{tid}: blocked requires notes and gap explaining the remaining limitation")
            continue
        if res == "cancelled" and not progress.get("notes") and u.get("reason"):
            progress["notes"] = str(u["reason"]).strip()[:2000]
        if (scope.metadata.get("research_convergence") and res in ("resolved", "cancelled")
                and not (progress.get("notes") or t.get("notes") or u.get("reason"))):
            errors.append(f"{tid}: provide notes with the completion basis or cancellation reason")
            continue
        if (
            res == "resolved"
            and (planned.get("verification_required") or t.get("verification_required"))
            and _team_verification_gate_enabled(scope)
        ):
            bus = registry.get_optional(AgentBus)
            if bus is None:
                verification_status = "not_registered"
            else:
                from plugins.tools._verification import work_item_verification_status

                try:
                    verification_status = work_item_verification_status(
                        bus,
                        resolve_bus_task_id(scope),
                        tid,
                        required_check_ids=[
                            str(item.get("check_id") or "")
                            for item in planned.get("verification_requirements",
                                                    t.get("verification_requirements")) or []
                            if isinstance(item, dict) and item.get("check_id")
                        ],
                    )
                except Exception:
                    logger.exception("could not project verification state for %s", tid)
                    verification_status = "unavailable"
            if verification_status != "passed":
                detail = {
                    "not_registered": "尚未登记版本绑定检查",
                    "unchecked": "检查尚未提交结论",
                    "partial": "仅部分检查通过",
                    "failed": "至少一项检查未通过",
                    "unavailable": "检查状态暂不可用",
                }.get(verification_status, verification_status)
                errors.append(
                    f"{tid}: {detail}；取得 pass 后才可 resolved；若无法继续，"
                    "请设 resolution='blocked' 并填写 notes、gap，交付带限制的部分结果"
                )
                # Reject the success claim, not truthful observations or the
                # explicitly registered plan. Keep the receipt distinct so a
                # client cannot project the rejected resolution as successful.
                t.update(planned)
                t.update(progress)
                if planned or progress:
                    progress_only.append(tid)
                continue
        if t.get("verification_ok") is False:
            if res == "resolved":
                errors.append(f"{tid}: 工具校验未通过，须重试成功后才可完成")
                continue
            if res == "cancelled":
                reason = str(u.get("reason") or "").strip()
                if not reason:
                    errors.append(f"{tid}: 取消未通过的校验须提供 reason，并在报告披露限制")
                    continue
                t["description"] += f"；未完成原因：{reason}"
        t.setdefault("owners", [])
        if t.pop("archived", False):
            _record_op(scope.task_id, "add", [tid])
        t.update(progress)
        t.update(planned)
        if res:
            t["resolution"] = (
                "in_progress" if res == "resolved" and t.get("kind") == "delivery"
                and not t.get("verification_required")
                and _team_verification_gate_enabled(scope) else res
            )
        # owners ACCUMULATE — assigning another agent to the same task adds it,
        # it does not replace the existing owner(s). ``replace_owners: true``
        # overwrites (e.g. to drop an agent that was reassigned elsewhere).
        new_owners = _as_owner_list(u.get("owner") or u.get("owners"))
        if new_owners:
            if u.get("replace_owners"):
                t["owners"] = new_owners
            else:
                for o in new_owners:
                    if o not in t["owners"]:
                        t["owners"].append(o)
        changed.append(tid)
    if not changed and not errors:
        return ("Error: update_task needs a list of "
                "{id, resolution?, owner?} items.")
    # Emit ONLY the actually-changed ids — rejected ids (bad id /
    # bad resolution) stay off the wire so the frontend never builds ghost rows.
    if changed:
        _record_op(scope.task_id, "update", changed)
    if progress_only:
        _record_op(scope.task_id, "update", progress_only)
    msg = f"Updated {changed}.\n{render_board(scope.task_id, bus_task_id=resolve_bus_task_id(scope))}"
    if progress_only:
        msg += f"\nProgress recorded {progress_only}; requested resolution rejected."
    if errors:
        if not changed:
            return "Error: no task was updated; " + "; ".join(errors) + "\n" + msg
        msg += "\nerrors: " + "; ".join(errors)
    return msg


@tool
async def finish_planning() -> str:
    """Leave Planning Mode and start building the team.

    While planning, only add_task / update_task are available. Call this once
    your task board lists EVERY sub-question; afterwards create_subagent /
    assign_task / collect_reports become available (you can still add_task /
    update_task to refine the plan as the investigation unfolds).
    """
    scope = get_current_execution_scope()
    if scope is None:
        return "Error: finish_planning can only be called inside an active run."
    if board_size(scope.task_id) == 0:
        return (
            "Error: the task board is empty — call add_task to list the "
            "sub-questions before finishing planning."
        )
    _PHASE[scope.task_id] = "execution"
    _record_op(scope.task_id, "finish_planning")
    return (
        "Planning complete — now in EXECUTION mode. You may create_subagent / "
        "assign_task to build and dispatch the team.\n"
        + render_board(scope.task_id, bus_task_id=resolve_bus_task_id(scope))
    )


# Later tools may depend on the board's updated phase/progress. Their guards
# must inspect completed mutations, not merely a proposed update in the batch.
for _board_mutation in (add_task, update_task, finish_planning):
    _board_mutation.metadata["execution_barrier"] = True


__all__ = [
    "BOARD_TOOLS",
    "RESOLUTION_MARKS",
    "VALID_RESOLUTION",
    "BoardCounts",
    "add_task",
    "board_size",
    "build_task_board_observer",
    "clear_board",
    "count_resolutions",
    "current_phase",
    "drain_board_ops",
    "finish_planning",
    "force_finish_planning",
    "in_planning",
    "is_planning_allowed",
    "planning_block_message",
    "planning_enabled",
    "render_board",
    "restore_board_from_messages",
    "serialize_tasks",
    "snapshot_tasks",
    "start_planning",
    "unresolved_task_ids",
    "update_task",
]
