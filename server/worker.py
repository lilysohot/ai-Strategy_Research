#!/usr/bin/env python3
"""Worker subprocess entry point for one run.

Spawned by the orchestrator with ``start_new_session=True`` so the orchestrator
can drain and kill the whole process group on shutdown. Responsibilities:

  1. chdir to the **repo root** — pipeline discovery is CWD-relative
     (``Path("workflows")`` in kernel_adapter._discover_pipeline_specs).
  2. Install per-run filesystem roots and LLM env BEFORE importing
     ``infra.config`` (it caches on first read).
  3. Assert the three OPENAI_* vars are all present or all absent (no silent
     fallback to api.openai.com with a user's key — tech-stack.md §5.3).
  4. Inject the server's ``profile_overrides`` (file + market tools, fs_mode).
  5. Cooperatively stop via ``metadata["pause_check"]`` + a stdin JSONL channel.
  6. Redirect all logging to run_dir/run/engine.log; stdout carries only JSONL
     control/heartbeat frames for the orchestrator.

The worker NEVER writes the trajectory — the runtime's TrajectoryFileObserver
does that into ``<_trial_dir>/agent/trajectories``. Realtime events (token
deltas, tool lifecycle) are captured by the in-worker ``BridgeObserver`` and
pumped to stdout as ``event`` frames by ``_bridge_pump``, since the observer's
asyncio queue cannot cross the process boundary. Lifecycle frames still carry
run_started / run_finished / stop_ack for state tracking and stop signals.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import logging
import os
import sys
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]


def _setup_logging(engine_log: Path) -> None:
    """Route all logging to engine.log; keep stdout clean for JSONL frames."""
    engine_log.parent.mkdir(parents=True, exist_ok=True)
    handler = logging.FileHandler(engine_log, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    root = logging.getLogger()
    root.handlers[:] = [handler]
    root.setLevel(logging.INFO)


def _frame(type_: str, **data: Any) -> None:
    """Emit one JSONL control frame on stdout (the orchestrator reads these)."""
    sys.stdout.write(json.dumps({"type": type_, **data}, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def persist_summary(run_root: Path, summary: dict[str, Any]) -> None:
    """Durably persist ``summary.json`` (F06-RUN-3 + F06 power durability).

    The rename is atomic against concurrent *readers*, but against a power cut
    the page cache can lose the tmp file's content while keeping the (empty)
    renamed entry — so the file is fsynced before the replace and the directory
    entry after it. The trajectory is fsynced once here too (terminal state):
    a crash then loses at most the last unflushed deltas, never the whole file.
    Every fsync is best-effort — a platform without fsync must still write its
    summary, and an OSError from the write itself is logged, never raised (it
    must not mask the run outcome).
    """
    from server.trajectory_status import fsync_directory

    traj = run_root / "run" / "agent" / "trajectories" / "react_agent.jsonl"
    try:
        if traj.exists():
            fd = os.open(str(traj), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
    except OSError:
        pass
    try:
        summary_tmp = run_root / "summary.json.tmp"
        summary_tmp.write_text(json.dumps(summary, ensure_ascii=False), encoding="utf-8")
        try:
            fd = os.open(str(summary_tmp), os.O_RDONLY)
            try:
                os.fsync(fd)
            finally:
                os.close(fd)
        except OSError:
            pass
        os.replace(summary_tmp, run_root / "summary.json")
        fsync_directory(run_root)
    except OSError:
        logging.getLogger("worker").warning("summary write failed", exc_info=True)


def _export_cross_mode_context(
    run_root: Path,
    *,
    inherited_context: str | None = None,
    published_answer: str = "",
    answer_status: str = "",
) -> Path | None:
    """Export this Run's validated native dump for a future mode change.

    The converter lives with the workflows; this worker-side seam only moves
    bytes between the workflow-owned native and portable contracts. A missing
    native dump is valid for a Run that ended before its loop snapshot existed.
    """

    from frontier_agent.components.observers.conversation_snapshot import canonical_json
    from server.history import CONVERSATION_DUMP_RELPATH, CROSS_MODE_CONTEXT_RELPATH
    from workflows._shared.cross_mode_context import (
        export_conversation_context,
        with_published_answer,
    )

    native_path = run_root.joinpath(*CONVERSATION_DUMP_RELPATH)
    if not native_path.is_file():
        return None
    portable_max_tokens = int(
        os.environ.get("REPLAY_MAX_TOKENS")
        or max(1, int(os.environ.get("OPENAI_CONTEXT_WINDOW", "262144")) // 2)
    )
    context = export_conversation_context(
        native_path.read_text(encoding="utf-8"),
        inherited_context=inherited_context,
        max_tokens=portable_max_tokens,
    )
    context = with_published_answer(
        context,
        content=published_answer,
        answer_status=answer_status,
        max_tokens=portable_max_tokens,
    )
    output_path = run_root.joinpath(*CROSS_MODE_CONTEXT_RELPATH)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = output_path.with_suffix(output_path.suffix + ".tmp")
    tmp.write_text(canonical_json(context), encoding="utf-8")
    try:
        fd = os.open(str(tmp), os.O_RDONLY)
        try:
            os.fsync(fd)
        finally:
            os.close(fd)
    except OSError:
        pass
    os.replace(tmp, output_path)
    return output_path


def _load_continuity_inputs(
    run_root: Path,
    *,
    target_pipeline_id: str,
    prior_pipeline_id: str = "",
) -> tuple[str, str]:
    """Return ``(native replay, portable context)`` for one target workflow."""

    replay_payload = ""
    replay_path = run_root / "prior_conversation.json"
    if replay_path.exists():
        replay_payload = replay_path.read_text(encoding="utf-8")

    cross_mode_context = ""
    use_cross_mode_context = target_pipeline_id == "agent_team" or (
        bool(prior_pipeline_id) and prior_pipeline_id != target_pipeline_id
    )
    if use_cross_mode_context:
        portable_path = run_root / "prior_cross_mode_context.json"
        if portable_path.exists():
            cross_mode_context = portable_path.read_text(encoding="utf-8")
        elif replay_payload:
            # Legacy heads predate the portable archive. Convert their validated
            # native bytes at the workflow boundary instead of starting team (or
            # a switched single Run) with empty history.
            from frontier_agent.components.observers.conversation_snapshot import (
                canonical_json,
            )
            from workflows._shared.cross_mode_context import export_conversation_context

            cross_mode_context = canonical_json(export_conversation_context(replay_payload))
    return replay_payload, cross_mode_context


def _load_research_history_contexts(run_root: Path) -> list[str]:
    """Load and remove the parent's owner-only portable-history staging file."""

    from server.history import RESEARCH_HISTORY_STAGE

    path = run_root / RESEARCH_HISTORY_STAGE
    if not path.is_file():
        return []
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(value, dict) or value.get("schema") != "research-history-stage/1":
            raise RuntimeError("research history stage schema mismatch")
        contexts = value.get("contexts")
        if not isinstance(contexts, list) or any(not isinstance(item, str) for item in contexts):
            raise RuntimeError("research history stage contexts is not a string list")
        return list(contexts)
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("research history stage is unreadable") from exc
    finally:
        path.unlink(missing_ok=True)


def _compose_run_instruction(
    prompt: str,
    *,
    prompt_addendum: str = "",
    investment_context: dict[str, Any] | None = None,
) -> tuple[str, str]:
    """Return ``(coordinator instruction, safe delegation question)``.

    The delegation form is frozen before authenticated business data is added.
    Agent Team may prepend it to sub-agent assignments; the full form is for
    the user-facing coordinator only.
    """

    delegation_question = prompt
    if prompt_addendum:
        delegation_question = f"{delegation_question}\n\n{prompt_addendum}"
    instruction = delegation_question
    if investment_context is not None:
        from server.investment_context import render_context_data

        instruction = f"{instruction}\n\n{render_context_data(investment_context)}"
    return instruction, delegation_question


def _assert_llm_env(model: str, base_url: str, api_key: str) -> None:
    """Reject partial LLM injection (tech-stack.md §5.3).

    All three must be present or all absent. A missing base_url would otherwise
    silently route a user's key to api.openai.com.
    """
    present = [bool(model), bool(base_url), bool(api_key)]
    if any(present) and not all(present):
        missing = [
            name
            for name, ok in (
                ("OPENAI_MODEL", model),
                ("OPENAI_BASE_URL", base_url),
                ("OPENAI_API_KEY", api_key),
            )
            if not ok
        ]
        raise SystemExit(f"partial LLM injection rejected; missing: {missing}")


def _load_investment_context(run_root: Path, run_id: str) -> dict[str, Any] | None:
    """Load the parent-materialized context and reject cross-Run substitution."""
    path = run_root / "investment-context.json"
    if not path.exists():
        return None
    try:
        context = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError("investment context is unreadable") from exc
    try:
        expected_run_id = uuid.UUID(run_id).hex
    except ValueError as exc:
        raise RuntimeError("worker Run id is invalid") from exc
    if not isinstance(context, dict) or context.get("run_id") != expected_run_id:
        raise RuntimeError("investment context does not belong to this Run")
    return context


def _finalize_investment_context(run_root: Path, context_tokens: tuple[Any, ...] | None) -> None:
    """Persist best-effort tool metrics and always release the Run binding."""
    if context_tokens is None:
        return
    from plugins.tools.investment_context import (
        investment_context_metrics,
        reset_investment_context,
    )
    from server.strategy_delivery import persist_strategy_verification

    try:
        persist_strategy_verification(run_root)
        (run_root / "investment-context-tools.json").write_text(
            json.dumps(investment_context_metrics(), sort_keys=True), encoding="utf-8"
        )
    except OSError:
        logging.getLogger("worker").warning(
            "investment context metrics persist failed", exc_info=True
        )
    finally:
        reset_investment_context(context_tokens)


def _finalize_input_intent(run_root: Path, token: Any | None) -> None:
    """Persist the model-declared input intent for the API to materialize (方案 A).

    worker 不写库、不指定 owner 与字段：只留下用途与原因，字段由 API 按用途裁决。
    """
    if token is None:
        return
    from plugins.tools.investment_input_request import pending_input_intent, reset_input_intent

    try:
        intent = pending_input_intent()
        if intent:
            payload = {
                "schema_version": "input-request/1",
                "use_case": intent.get("use_case"),
                "reason": intent.get("reason"),
            }
            tmp = run_root / "input-request.json.tmp"
            tmp.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            os.replace(tmp, run_root / "input-request.json")
    except OSError:
        logging.getLogger("worker").warning("input intent persist failed", exc_info=True)
    finally:
        reset_input_intent(token)


def apply_env(
    paths: dict[str, Path],
    *,
    backend: str,
    wall_time_s: int,
    max_turns: int,
    model: str,
    base_url: str,
    api_key: str,
    require_role_isolation: bool = False,
    canonical_mounts: bool = False,
) -> None:
    """Install per-run environment before any ``infra.config`` import."""
    os.environ.update(
        {
            "SANDBOX_BACKEND": backend,
            "FRONTIER_AGENT_WORKSPACE_DIR": "/workspace"
            if canonical_mounts
            else str(paths["workspace"]),
            "FRONTIER_AGENT_OUTPUTS_DIR": "/outputs" if canonical_mounts else str(paths["outputs"]),
            "FRONTIER_AGENT_INPUTS_DIR": "/inputs" if canonical_mounts else str(paths["inputs"]),
            "CODING_WORKSPACE_ROOT": str(paths["workspace"]),
            "APODEX_SPILL_DIR": str(paths["spill"]),
            # Corpus consumption ledgers and A4 manifests are run artifacts too.
            # Without this, Web workers verify only in process memory and leave
            # no durable semantic audit trail after exit.
            "APODEX_RUN_DIR": str(paths["run"]),
            "FRONTIER_AGENT_TASK_WALL_TIME_S": str(wall_time_s),
            "FRONTIER_AGENT_MAX_TURNS": str(max_turns),
            "BASH_ALLOWLIST_MODE": "enforce",
        }
    )
    if require_role_isolation:
        # CurrentSandbox is a working-directory facade, not a chroot.  Team
        # role isolation therefore requires a distinct OS identity so a
        # sub-agent's shell cannot traverse into owner-only coordinator/run
        # artifacts.  tool_identity() fails closed when the image is missing
        # the account or the worker cannot drop privileges.
        os.environ.pop("FRONTIER_AGENT_TOOL_USER", None)
        os.environ["FRONTIER_AGENT_REQUIRE_TOOL_USER"] = "1"
    else:
        os.environ["FRONTIER_AGENT_TOOL_USER"] = "off"
        os.environ.pop("FRONTIER_AGENT_REQUIRE_TOOL_USER", None)
    if model:
        os.environ["OPENAI_MODEL"] = model
    if base_url:
        os.environ["OPENAI_BASE_URL"] = base_url
    if api_key:
        os.environ["OPENAI_API_KEY"] = api_key


async def _bridge_pump(queue: asyncio.Queue[dict[str, Any] | None]) -> None:
    """Forward live bridge events to stdout as JSONL ``event`` frames.

    The worker is a *subprocess*, so the observer's asyncio queue lives in this
    process and the parent cannot read it. stdout is the only channel across
    that boundary, so every realtime event (token deltas, tool lifecycle) is
    re-emitted here as a frame and rehydrated by the orchestrator.

    ``None`` is the shutdown sentinel: it drains what is left and returns.
    """
    while True:
        event = await queue.get()
        if event is None:
            return
        # ``type`` is the frame discriminator; the SSE payload's own ``type``
        # field rides inside, so namespace the frame to avoid a collision.
        _frame("event", payload=event)


class _StopFlag:
    """Cooperative stop signal fed into ``metadata['pause_check']``."""

    def __init__(self) -> None:
        self.requested = False
        # Mirrors AgentLoopResult.stopped_by semantics (tech-stack.md §5.2): the
        # worker's own stop paths set this so the runs table can record why.
        self.stopped_by = ""

    async def check(self) -> bool:
        return self.requested


async def _stdin_watch(stop: _StopFlag, steer_inbox: Any, gate: Any = None) -> None:
    """Read the orchestrator's control frames from stdin (stop / steer / approve).

    The orchestrator spawns the worker with ``stdin=PIPE`` and writes JSON
    control lines (``{"action":"stop"}``, ``{"action":"steer","message":...}``,
    ``{"action":"approve","approval_id":...,"decision":...}``) to it. A thread
    does the blocking read so we are not at the mercy of ``connect_read_pipe``'s
    handling of the inherited pipe on every platform; on stop we set the
    cooperative stop flag, on steer we feed the run's
    :class:`~server.steer.SteerInbox` for the observer to drain at the next
    turn boundary, and on approve we resolve the pending
    :class:`~server.approval.ApprovalGate` future from this thread (the gate
    marshals the wakeup onto the loop).
    """
    import threading

    def _reader() -> None:
        try:
            for raw in sys.stdin:
                line = raw.strip()
                if not line:
                    continue
                try:
                    msg = json.loads(line)
                except json.JSONDecodeError:
                    continue
                action = msg.get("action")
                if action == "stop":
                    stop.requested = True
                    stop.stopped_by = "user_stop"
                    _frame("stop_ack")
                    logging.getLogger("worker").info("stop requested via stdin")
                    # Keep reading: an approval may already be pending, and the
                    # gate must not outlive the stop — fail it closed now (P3.2)
                    # so the loop reaches the turn boundary instead of sitting on
                    # the 300s gate timeout. Late approve frames are harmless:
                    # resolve() refuses spent/unknown ids.
                    if gate is not None:
                        gate.reject_pending()
                if action == "steer" and steer_inbox is not None:
                    # F21: the control id rides along so the adoption report can
                    # name the record the parent persisted for this line.
                    control_id = msg.get("control_id")
                    steer_inbox.enqueue(
                        str(msg.get("message") or ""),
                        control_id=str(control_id) if control_id else None,
                    )
                if action == "approve" and gate is not None:
                    from server.approval import ApprovalDecision

                    gate.resolve(
                        str(msg.get("approval_id") or ""),
                        ApprovalDecision(
                            decision=str(msg.get("decision") or ""),
                            replacement_command=msg.get("replacement_command"),
                        ),
                    )
        except (OSError, ValueError):
            return

    t = threading.Thread(target=_reader, daemon=True, name="stdin-watch")
    t.start()
    # Keep the coroutine alive until the worker is otherwise done; the event loop
    # awaits this task in run_once's ``finally`` via stdin_task.cancel().
    try:
        while not stop.requested:
            await asyncio.sleep(0.2)
    finally:
        # The thread is daemon; nothing to join. The flag is already set if a stop
        # arrived, and the loop's pause_check will observe it at the next boundary.
        pass


async def _drain_bridge(
    queue: asyncio.Queue[dict[str, Any] | None],
    pump_task: asyncio.Task[None],
) -> None:
    """Stop the bridge pump once it has flushed every queued event.

    The sentinel is queued last, so the pump exits only after the events already
    ahead of it have been written. Best-effort: never let a wedged pump keep the
    worker alive past its wall clock.
    """
    await queue.put(None)
    with contextlib.suppress(Exception):
        await asyncio.wait_for(pump_task, timeout=10)
    if not pump_task.done():
        pump_task.cancel()


async def run_once(args: argparse.Namespace) -> int:
    """Execute one run end-to-end and persist its artifacts.

    Loads the LLM credentials from the environment (never argv), wires the
    bridge observer + stdin stop watcher, drives the workflow via
    ``BenchmarkSession``, then writes diff.json / usage.json / summary.json
    under the run directory. Returns 0 on success, 1 when the run errored.
    """
    from server.bridge import BridgeObserver
    from server.config import build_run_paths, run_dir_for
    from server.diff import DiffRecorder
    from server.profile import (
        BUSINESS_CONTEXT_POLICY,
        CONTEXT_INTEGRITY_POLICY,
        INPUT_REQUEST_POLICY,
        PROFILE_NAME,
        RESEARCH_HISTORY_POLICY,
        TEAM_BUSINESS_OWNERSHIP_POLICY,
        TEAM_SUBAGENT_POLICY,
        build_profile_overrides,
    )

    paths = build_run_paths(args.run_id)
    run_root = run_dir_for(args.run_id)
    engine_log = paths["run"] / "engine.log"
    _setup_logging(engine_log)

    # LLM credentials arrive ONLY through the environment, injected by the
    # orchestrator (or the server's .env when the user has no config). They are
    # never passed as argv (which is visible in `ps`), so we read them here and
    # nowhere else. The argparse --model/--base-url/--api-key flags are retained
    # only for out-of-band manual debugging and are not set by the orchestrator.
    model = os.environ.get("OPENAI_MODEL", "") or args.model
    base_url = os.environ.get("OPENAI_BASE_URL", "") or args.base_url
    api_key = os.environ.get("OPENAI_API_KEY", "") or args.api_key

    _assert_llm_env(model, base_url, api_key)
    apply_env(
        paths,
        backend=args.backend,
        wall_time_s=args.wall_time,
        max_turns=args.max_turns,
        model=model,
        base_url=base_url,
        api_key=api_key,
        require_role_isolation=(
            args.pipeline_id == "agent_team" and args.backend in {"native", "container"}
        ),
        # Bwrap tools execute in a separate mount namespace for either workflow.
        # Keep aliases canonical; physical per-Run directories are supplied
        # through metadata below.
        canonical_mounts=args.backend in {"bwrap", "auto"},
    )

    # ``.env`` at repo root is loaded at import with override=False, so the
    # injected OPENAI_* above are not clobbered (tech-stack.md §5.3).
    from dotenv import load_dotenv

    load_dotenv(REPO_ROOT / ".env", override=False)

    from benchmarks.public.core.kernel_adapter import BenchmarkSession

    stop = _StopFlag()
    # P3.1 live steering: the stdin watcher feeds user lines into the inbox and
    # the observer injects them at the next safe turn boundary (§6.2).
    from server.steer import SteerInbox, SteerObserver

    steer_inbox = SteerInbox()

    def _report_steer_adopted(control_ids: list[str]) -> None:
        """Tell the parent which steer records actually reached the loop (F21).

        Only the worker can know this: a steer still sitting in the inbox when
        the run ends was never injected, so the parent must not infer adoption
        from the fact that the line was accepted and written to stdin.
        """
        for control_id in control_ids:
            _frame("control_applied", kind="steer", control_id=control_id)

    steer_observer = SteerObserver(steer_inbox, on_adopted=_report_steer_adopted)
    # P3.2 (§6.1): confirm-level tool calls emit approval_requested into
    # live_events and suspend on the gate until stdin delivers the decision.
    from server.approval import ApprovalGate, ApprovalObserver

    gate = ApprovalGate()
    # Unbounded: the agent loop must never block on the UI. Deltas are tiny and
    # the pump drains continuously; a bounded queue would stall generation on a
    # slow reader.
    live_events: asyncio.Queue[dict[str, Any] | None] = asyncio.Queue()
    team_source_meta = (
        {"agent_id": "coordinator", "agent_kind": "coordinator"}
        if args.pipeline_id == "agent_team"
        else {}
    )
    approval_observer = ApprovalObserver(
        gate,
        live_events.put_nowait,
        cwd=str(paths["workspace"]),
        source_meta=team_source_meta,
    )
    stdin_task = asyncio.create_task(_stdin_watch(stop, steer_inbox, gate))

    # T2.8: capture ``stopped_by`` and the partial answer from the loop's
    # ``AgentLoopResult`` (not the pipeline state, which never carries them —
    # tech-stack.md §5.2). The observer is injected via ``sdk_extra_observers``
    # so the workflow node appends it to the in-loop observer stack and its
    # ``on_loop_end`` fires with the authoritative result.
    # Unbounded: the agent loop must never block on the UI. Deltas are tiny and
    # the pump drains continuously; a bounded queue would stall generation on a
    # slow reader.
    bridge = BridgeObserver(
        queue=live_events,
        # Status-bar facts (§5.6) stamped on the live run_started event.
        run_meta={
            "pipeline_id": args.pipeline_id,
            "model_name": model,
            "max_turns": args.max_turns,
        },
        source_meta=team_source_meta,
    )
    pump_task = asyncio.create_task(_bridge_pump(live_events))

    # P2.5: snapshot the (usually empty) outputs dir before the run so any
    # post-run change is attributable; per-file baselines are first-touch.
    # The working directory is scanned too — the §2.2 第二类 bash-scan sweep.
    recorder = DiffRecorder(
        run_root=run_root,
        outputs_root=paths["outputs"],
        workspace_root=paths["workspace"],
    )
    recorder.snapshot_outputs_baseline()

    investment_context = _load_investment_context(run_root, args.run_id)
    context_tokens = None
    # 方案 A：缺料意图对**所有**研究 Run 启用（2026-10-08）——它不依赖业务快照，
    # 只把“要给结论但缺用户真实资料”的意图交给服务端裁决。
    from plugins.tools.investment_input_request import bind_input_intent

    intent_token = bind_input_intent()
    if investment_context is not None:
        from plugins.tools.investment_context import bind_investment_context

        context_tokens = bind_investment_context(investment_context)

    # The request *prefix* configuration — business policy text and tool set — is
    # keyed on the SESSION's business binding rather than on whether this run
    # resolved a snapshot (issue 01 §9.6). Both are part of the LLM request
    # prefix, so letting them flip between turns of one conversation would
    # invalidate the provider's prefix cache. Run-specific business *data* still
    # lands in the instruction tail (below), where it cannot break the prefix.
    business_prefix = getattr(args, "business_prefix", None)
    if business_prefix is None:
        # Callers that do not send the flag (spike runs, manual worker
        # invocations) keep the previous per-run behaviour.
        business_prefix = investment_context is not None
    business_prefix = bool(business_prefix)

    overrides = build_profile_overrides(
        has_investment_context=business_prefix,
        pipeline_id=args.pipeline_id,
        enable_research_history=bool(getattr(args, "mixed_mode_history", False)),
    )
    # Parse any extra agent_tools the orchestrator appends (e.g. market tools
    # once registered in T4.2).
    if args.agent_tools:
        extra = [t.strip() for t in args.agent_tools.split(",") if t.strip()]
        if business_prefix:
            # Raw position_sizing accepts model-supplied capital. A business Run
            # may only expose the snapshot-bound wrapper.
            extra = [name for name in extra if name not in {"position_sizing", "strategy_lint"}]
        target_key = "main_agent_tools" if args.pipeline_id == "agent_team" else "agent_tools"
        overrides["agent"][target_key] = [*overrides["agent"][target_key], *extra]

    metadata: dict[str, Any] = {
        "profile": PROFILE_NAME,
        "profile_overrides": overrides,
        "fs_mode": True,
        "_trial_dir": str(paths["run"]),
        "coding_workspace_root": str(paths["workspace"]),
        "session_id": args.session_id,
        "turn_index": args.turn_index,
        "pause_check": stop.check,
        # DiffRecorder hooks on_tool_call (pre-execution) for file-tool baselines;
        # it never intervenes (always returns None) and swallows its own errors.
        # ApprovalObserver also hooks on_tool_call but DOES intervene: confirm-
        # level calls suspend on the approval gate (§6.1).
        "sdk_extra_observers": [
            bridge,
            recorder,
            steer_observer,
            approval_observer,
        ],
        "_sys_prompt_addendum": (
            # Constant for every run, so it belongs to the request *prefix*.
            # Per-run guidance (the uploaded-file note, the business data) is
            # appended to the instruction tail below instead — see issue 01 §10.2
            # S1-b and `_per_run_tail`.
            "Input files are mounted read-only at /inputs. Write the final deliverable to /outputs."
            "\n" + CONTEXT_INTEGRITY_POLICY
        ),
    }
    # Web storage and bwrap must name the same per-Run directories. Both the
    # stateful and team workflows consume these fields when constructing their
    # private mount namespaces; container/native modes keep using apply_env's
    # physical paths directly.
    metadata["_sandbox_workspace_root"] = str(paths["workspace"])
    metadata["_sandbox_outputs_dir"] = str(paths["outputs"])
    metadata["_sandbox_mounts"] = [
        {"src": str(paths["inputs"]), "dst": "/inputs", "mode": "ro"},
    ]
    if business_prefix:
        metadata["_sys_prompt_addendum"] += "\n" + BUSINESS_CONTEXT_POLICY
    # 缺料表达对**所有**研究 Run 生效（2026-10-08 实测补充）：只有工具描述不够，
    # 必须有 prompt 级指令，否则模型会把“缺资料”写成一段说明而不调用工具。
    metadata["_sys_prompt_addendum"] += "\n" + INPUT_REQUEST_POLICY
    if getattr(args, "mixed_mode_history", False):
        metadata["_sys_prompt_addendum"] += "\n" + RESEARCH_HISTORY_POLICY
    if args.pipeline_id == "agent_team":
        metadata["_sys_prompt_addendum"] += "\n" + TEAM_BUSINESS_OWNERSHIP_POLICY
        metadata["_subagent_prompt_addendum"] = TEAM_SUBAGENT_POLICY

    started = time.time()
    _frame("run_started", run_dir=str(run_root))
    final_answer = ""
    error = ""
    # Cross-turn replay outcome, surfaced in summary.json so the acceptance run
    # can show "used"/"skipped + reason" per turn without reading engine.log.
    replay_decision: dict[str, Any] = {}
    # The write-time summary call's own tokens (issue 01 §12.11 待办 2). Defaulted
    # here for the same reason as the decision above: the pipeline call below can
    # fail before ever producing a state.
    summary_usage: dict[str, Any] = {}
    workflow_stop_reason = ""
    answer_outcome: dict[str, str] = {}

    # Cross-turn continuity (issue 01 §9.4): the orchestrator stages the session's
    # stored conversation dump in this run root. The worker never parses it —
    # it is handed to the workflow as an opaque payload, and the workflow
    # validates it before replaying anything.
    replay_payload, cross_mode_context = _load_continuity_inputs(
        run_root,
        target_pipeline_id=args.pipeline_id,
        prior_pipeline_id=str(getattr(args, "prior_pipeline_id", "") or ""),
    )
    history_token = None
    if getattr(args, "mixed_mode_history", False):
        from plugins.tools.research_history import bind_research_history

        history_token = bind_research_history(_load_research_history_contexts(run_root))

    # The request *tail*: everything that differs between turns of ONE
    # conversation. The uploaded-file note names this run's inputs and the
    # business data is this run's snapshot, so neither may sit in the system
    # prompt — one per-run byte in the prefix resets the provider's cache for the
    # whole conversation (issue 01 §9.15). The model sees the same bytes as
    # before; they are simply appended after the user's prompt instead of before
    # it. The workflow adds this run's own directory notes to the same tail.
    instruction, subagent_original_question = _compose_run_instruction(
        args.prompt,
        prompt_addendum=args.prompt_addendum,
        investment_context=investment_context,
    )
    # Agent Team's assign_task prepends this value to every delegated prompt.
    # Keep the useful user scope and input-file note, but freeze it before the
    # authenticated investment block is appended below.  The complete
    # instruction remains available to the coordinator only.
    if args.pipeline_id == "agent_team":
        metadata["_subagent_original_question"] = subagent_original_question

    continuity_mode = (getattr(args, "continuity", "on") or "on").strip().lower()
    try:
        async with BenchmarkSession() as session:
            state = await asyncio.wait_for(
                session.run(
                    instruction,
                    meta=metadata,
                    pipeline_id=args.pipeline_id,
                    extra_input={
                        # Watch mode is read-only (issue 01 §13): it can replay
                        # the chat carrier but cannot write its raw trace back.
                        "continuity_read_enabled": continuity_mode != "off",
                        "continuity_write_enabled": continuity_mode == "on",
                        **({"replay_payload": replay_payload} if replay_payload else {}),
                        **(
                            {"cross_mode_context": cross_mode_context} if cross_mode_context else {}
                        ),
                    },
                ),
                timeout=args.wall_time + 30,
            )
        replay_decision = state.get("replay_decision") or {}
        summary_usage = state.get("summary_usage") or {}
        workflow_stop_reason = str(state.get("stopped_by") or "")
        answer_outcome = {
            key: str(state.get(key) or "")
            for key in (
                "answer_status",
                "final_answer_source",
                "llm_error_reason",
                "llm_retry_blocked_by",
            )
        }
        for key in ("final_answer", "final_content", "report", "answer", "output"):
            value = state.get(key)
            if isinstance(value, dict):
                value = value.get("content")
            if isinstance(value, str) and value.strip():
                final_answer = value.strip()
                break
        # T2.8 partial fallback: when the loop ended early (stop/user deadline)
        # the pipeline state may be empty, but the observer captured the partial
        # text from ``AgentLoopResult.final_content``. Prefer the state answer,
        # fall back to the observer's partial so the user still sees progress.
        if not final_answer and bridge.final_content.strip():
            final_answer = bridge.final_content.strip()
        try:
            _export_cross_mode_context(
                run_root,
                inherited_context=cross_mode_context or None,
                published_answer=final_answer,
                answer_status=str(state.get("answer_status") or ""),
            )
        except Exception:
            logging.getLogger("worker").warning("cross-mode context export failed", exc_info=True)
        # Merge stopped_by: the worker's own stop paths (user_stop / deadline)
        # take precedence; otherwise use the loop result's own reason (e.g.
        # "max_turns", "context_limit", "paused"). The workflow may also
        # downgrade a natural completion at its business publication boundary.
        stopped_by = stop.stopped_by or workflow_stop_reason or bridge.stopped_by or ""
        _frame(
            "run_finished",
            ok=True,
            duration_s=round(time.time() - started, 2),
            answer_len=len(final_answer),
            stopped_by=stopped_by,
            final_answer=final_answer[:50_000],
            **answer_outcome,
        )
    except TimeoutError:
        error = "wall timeout exceeded"
        # The worker-side deadline fired: the loop was cancelled before
        # on_loop_end, so stopped_by is recorded here (not from the observer).
        _frame(
            "run_finished",
            ok=False,
            error=error,
            stopped_by="deadline",
            duration_s=round(time.time() - started, 2),
        )
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        logging.getLogger("worker").exception("run failed")
        _frame("run_finished", ok=False, error=error, duration_s=round(time.time() - started, 2))
    finally:
        stdin_task.cancel()
        # Flush the realtime tail before the process exits: deltas emitted after
        # the last flush would otherwise be lost to the parent.
        await _drain_bridge(live_events, pump_task)
        # P2.5: produce the run diff after the loop is fully done (the final
        # file state is what gets diffed). Never mask the run outcome.
        try:
            recorder.write_diff()
        except Exception:
            logging.getLogger("worker").warning("diff generation failed", exc_info=True)
        _finalize_investment_context(run_root, context_tokens)
        _finalize_input_intent(run_root, intent_token)
        if history_token is not None:
            from plugins.tools.research_history import reset_research_history

            reset_research_history(history_token)

    # Persist a small summary the orchestrator/relay can read for the runs table.
    # stopped_by precedence mirrors the run_finished frame above. ``bridge`` is
    # unconditionally bound above, so no fallback is needed here.
    _stopped_by = stop.stopped_by or workflow_stop_reason or bridge.stopped_by
    summary = {
        "run_id": args.run_id,
        # Survives ingestion, which deletes run/conversation.json. Directory
        # statistics must not need the continuity carrier to identify a run.
        "session_id": args.session_id,
        "final_answer": final_answer[:50_000],
        "error": error,
        "stopped_by": _stopped_by,
        **answer_outcome,
        "duration_s": round(time.time() - started, 2),
        # Cross-turn replay outcome (issue 01 §9.8): "used" / "skipped" + reason.
        "replay": replay_decision,
        # The write-time summary call's own tokens (issue 01 §12.11 待办 2). Its own
        # key rather than folded into the run's counters: this call happens in an
        # observer the trajectory never sees, so it was previously unmetered.
        "summary_usage": summary_usage,
    }
    # F22 / F06-RUN-3 + F06 power durability: atomic + fsynced persist (see
    # persist_summary). A write failure is logged but must never mask the outcome.
    persist_summary(run_root, summary)
    return 0 if not error else 1


def main() -> int:
    """CLI entry point: parse argv, pin cwd/sys.path, then run one run_once."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--session-id", default="")
    parser.add_argument("--turn-index", type=int, default=1)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--prompt-addendum", default="")
    parser.add_argument("--pipeline-id", default="stateful-react-agent")
    parser.add_argument("--prior-pipeline-id", default="")
    parser.add_argument("--backend", default="native")
    parser.add_argument("--wall-time", type=int, default=900)
    parser.add_argument("--max-turns", type=int, default=60)
    parser.add_argument("--model", default="")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--agent-tools", default="")
    parser.add_argument("--mixed-mode-history", action="store_true")
    parser.add_argument(
        "--require-semantic-store",
        action="store_true",
        help="fail before the first model call unless CORPUS_STRUCTURED_ROOT is a read-only mount",
    )
    # Session-level business flag (issue 01 §9.6): ``1``/``0`` pins the request
    # prefix config; omitted (``None``) keeps the legacy per-run behaviour for
    # callers that do not send it.
    parser.add_argument("--business-prefix", type=int, default=None, choices=(0, 1))
    # Cross-turn continuity carrier (issue 01 §13): watch-triggered runs pass
    # ``read`` so they replay the chat conversation without leaving a dump.
    parser.add_argument("--continuity", default="on", choices=("on", "read", "off"))
    args = parser.parse_args()

    # CWD = repo root is mandatory for workflow discovery.
    os.chdir(REPO_ROOT)
    if str(REPO_ROOT) not in sys.path:
        sys.path.insert(0, str(REPO_ROOT))

    try:
        if args.require_semantic_store:
            from apodex.semantic_access import require_readonly_semantic_store

            require_readonly_semantic_store(required=True)
        return asyncio.run(run_once(args))
    except SystemExit:
        raise
    except Exception as exc:
        _frame("run_finished", ok=False, error=f"{type(exc).__name__}: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
