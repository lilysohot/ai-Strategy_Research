"""S3 acceptance: the replay window keeps its cache across 45 real turns (issue 01 §12.5/§12.8).

Pre-registered criteria (signed off 2026-10-12, BEFORE the run; §12.5 as revised):

  C1  completeness — both arms ran 45 turns, every run terminal, no ``error``,
      ``llm_calls >= 1``
  C2  carrier regression (S2) — after every turn the run's dump file is gone and
      the session row holds the conversation
  C3  size — every turn's ``prompt_tokens <= replay_max_tokens`` (114,688)
  C4  a cut flaps once, not forever (treatment) — for every run N whose replay
      carried a trim (the miss turn), the next TWO turns reuse >= 80% of the
      preceding turn's prompt
  C5  the memory is written once per cut (treatment) — the summary block's digest
      changes at most ``cuts`` times
  C6  arms differ (headline) — treatment mean reuse >= 80%, control <= 60%, gap
      >= 20pp
  C7  plateau (treatment) — max prompt over the last 10 turns <= 1.5x the max over
      turns 15..25

Arms are the *same code* with one knob: ``REPLAY_MAX_TURN_STEP`` (the profile reads
it as ``${REPLAY_MAX_TURN_STEP:-5}``), treatment = 5 (new default), control = 0
(pre-hysteresis). One driver process, but every turn is its own worker subprocess,
so the window crosses a fresh process each time — the carrier is the database.

  uv run python .../run_acceptance_s3.py --out DIR --arm treatment
  uv run python .../run_acceptance_s3.py --out DIR --arm control
  uv run python .../run_acceptance_s3.py --out DIR --verdict

Resumable: each turn is appended to ``<arm>-turns.json``, so a restart continues
where it stopped instead of paying for the turns again.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import itertools
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]

TURNS = 45
TURN_TOKENS = 1_000
#: The replay token budget the web profile resolves to (``max_input_tokens // 2``).
REPLAY_MAX_TOKENS = 114_688
ARMS = {"treatment": 5, "control": 0}

SENTENCE = (
    "以下背景资料与本轮问题无关，仅用于把上下文撑到与真实业务会话相当的长度，请忽略其具体内容。"
)


def _dotenv_value(key: str) -> str:
    env_path = REPO_ROOT / ".env"
    if not env_path.exists():
        return ""
    for line in env_path.read_text(encoding="utf-8").splitlines():
        name, _, value = line.partition("=")
        if name.strip() == key:
            return value.strip().strip('"').strip("'")
    return ""


def _env_or_dotenv(key: str) -> str:
    return os.environ.get(key) or _dotenv_value(key)


def prompt_for(turn: int) -> str:
    """One turn of roughly ``TURN_TOKENS`` tokens, unique per turn.

    Sized deliberately: a turn has to be big enough that the window the next turn
    replays is comparable with the system prompt, or the reuse *ratio* would be
    dominated by the constant system prompt in both arms and the arms would look
    alike while their absolute re-prefill differs several-fold.
    """
    from frontier_agent.core.runtime.loop.context_budget import estimate_tokens

    unit = f"第 {turn} 轮背景资料：{SENTENCE}"
    repeats = max(1, round(TURN_TOKENS / max(1, estimate_tokens(unit))))
    return f"{unit * repeats}\n\n以上全部是背景噪音。请只回复两个字：收到。不要调用任何工具。"


def summary_digest(messages: list[dict[str, Any]]) -> str | None:
    """Digest of the memory block, or None when the window carries none."""
    from frontier_agent.components.observers.conversation_snapshot import SUMMARY_TAG

    if len(messages) > 1 and SUMMARY_TAG in str(messages[1].get("content") or ""):
        body = str(messages[1].get("content") or "")
        return hashlib.sha256(body.encode("utf-8")).hexdigest()[:12]
    return None


async def _bound_research_seed(store: Any) -> tuple[uuid.UUID, uuid.UUID]:
    from sqlalchemy import select

    async with store.get_sessionmaker()() as session:
        row = (
            await session.execute(
                select(store.ResearchInvestmentLink)
                .where(store.ResearchInvestmentLink.account_id.is_not(None))
                .limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        raise SystemExit("no bound research in this database — cannot build the arm")
    return row.user_id, row.account_id


async def _make_session(
    store: Any, *, user_id: uuid.UUID, account_id: uuid.UUID, title: str
) -> uuid.UUID:
    from server import store as store_mod

    session_uuid = uuid.uuid4()
    await store_mod.ensure_session(session_id=session_uuid, user_id=user_id, title=title)
    async with store_mod.get_sessionmaker()() as session:
        session.add(
            store_mod.ResearchInvestmentLink(
                research_id=session_uuid,
                user_id=user_id,
                account_id=account_id,
                primary_plan_id=None,
            )
        )
        await session.commit()
    return session_uuid


async def _wait_run(store: Any, run_uuid: uuid.UUID, user_id: uuid.UUID, *, timeout: float) -> Any:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = await store.get_run(run_id=run_uuid, user_id=user_id)
        if row is not None and row.status not in store.ACTIVE_RUN_STATUSES:
            for _ in range(120):
                if row.usage_json is not None:
                    break
                await asyncio.sleep(0.5)
                row = await store.get_run(run_id=run_uuid, user_id=user_id)
            return row
        await asyncio.sleep(1.0)
    return None


async def _auto_approve(
    orchestrator: Any, run_id: str, decision: str, seen: list[dict[str, Any]]
) -> None:
    """Answer every ``approval_requested`` — a confirm-level tool call parks the
    loop until a human decides, or the gate's 300s fail-closed timeout expires."""
    queue = orchestrator.subscribe(run_id)
    try:
        while True:
            frame = await queue.get()
            if frame is None:
                return
            if frame.get("type") != "approval_requested":
                continue
            approval_id = str(frame.get("approval_id") or "")
            delivered = await orchestrator.approve(run_id, approval_id, decision)
            seen.append(
                {"approval_id": approval_id, "tool": frame.get("tool_name"), "ok": delivered}
            )
    finally:
        orchestrator.unsubscribe(run_id, queue)


def _load_state(path: Path, *, arm: str, step: int) -> dict[str, Any]:
    if not path.is_file():
        return {"arm": arm, "step": step, "turns": {}}
    state = json.loads(path.read_text(encoding="utf-8"))
    if state.get("step") != step:
        raise SystemExit(f"{path} was written with step={state.get('step')}, not {step}")
    return state


def _save_state(path: Path, state: dict[str, Any]) -> None:
    path.write_text(json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8")


async def run_arm(args: argparse.Namespace) -> int:
    from server import store
    from server.config import run_dir_for
    from server.orchestrator import Orchestrator
    from server.store import read_session_conversation

    arm = args.arm
    step = ARMS[arm]
    model = args.model or _env_or_dotenv("OPENAI_MODEL")
    if not model:
        raise SystemExit("no model: pass --model or set OPENAI_MODEL")
    os.environ["OPENAI_MODEL"] = model
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        value = _env_or_dotenv(key)
        if not value:
            raise SystemExit(f"{key} missing (env + .env)")
        os.environ[key] = value

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    state_path = out_dir / f"{arm}-turns.json"
    state = _load_state(state_path, arm=arm, step=step)

    if not state["turns"]:
        seed_user, account_id = await _bound_research_seed(store)
        state["user_id"] = seed_user.hex
        state["session_id"] = (
            await _make_session(
                store, user_id=seed_user, account_id=account_id, title=f"S3 {arm} step={step}"
            )
        ).hex
        state["model"] = model
        state["created_at"] = time.strftime("%Y-%m-%d %H:%M:%S")
        _save_state(state_path, state)
    user_id = uuid.UUID(state["user_id"])
    session_uuid = uuid.UUID(state["session_id"])

    # The worker inherits this process's environment, and the profile interpolates
    # it — one knob is the only difference between the arms.
    os.environ["REPLAY_MAX_TURN_STEP"] = str(step)
    os.environ["REPLAY_MAX_TURNS"] = "10"

    orchestrator = Orchestrator()
    for turn in range(1, args.turns + 1):
        key = str(turn)
        if key in state["turns"]:
            continue
        prompt = prompt_for(turn)
        run_hex = uuid.uuid4().hex
        run_uuid = uuid.UUID(run_hex)
        run_root = Path(run_dir_for(run_hex))
        await store.create_run(
            run_id=run_uuid,
            session_id=session_uuid,
            user_id=user_id,
            prompt=prompt,
            pipeline_id="stateful-react-agent",
            run_dir=str(run_root),
            status="queued",
        )
        approvals: list[dict[str, Any]] = []
        watcher = asyncio.create_task(
            _auto_approve(orchestrator, run_hex, "session_all", approvals)
        )
        try:
            await orchestrator.submit(
                run_id=run_hex,
                session_id=str(session_uuid),
                prompt=prompt,
                user_id=None,  # the server's own .env credentials
                turn_index=turn,
                backfill_turn=True,
            )
            row = await _wait_run(store, run_uuid, user_id, timeout=args.wait)
        finally:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
        if row is None:
            print(f"[{arm}] turn {turn}: TIMEOUT after {args.wait}s", flush=True)
            _save_state(state_path, state)
            return 1
        # The parent deletes the dump when its ingest commits, which can land a
        # moment after the run row goes terminal. Sample twice, so a race is not
        # reported as "the carrier did not move" (it was, once, and the artifact
        # was gone by the time anyone looked).
        await asyncio.sleep(args.grace)

        usage = row.usage_json or {}
        payload = await read_session_conversation(session_id=session_uuid)
        messages: list[dict[str, Any]] = []
        if payload:
            messages = json.loads(payload).get("messages") or []
        record = {
            "turn": turn,
            "run_id": run_hex,
            "status": row.status,
            "stopped_by": row.stopped_by,
            "error": row.error,
            "prompt_tokens": row.prompt_tokens,
            "cache_read_tokens": row.cache_read_tokens,
            "llm_calls": row.llm_calls,
            "usage_status": usage.get("status"),
            "replay": usage.get("replay"),
            "answer_head": (row.final_answer or "")[:60],
            "dump_present_after_run": (run_root / "run" / "conversation.json").is_file(),
            "dump_gone_later": not (run_root / "run" / "conversation.json").is_file(),
            "stored_after_run": payload is not None,
            "window_messages": len(messages),
            "window_turns": sum(1 for m in messages if m.get("role") == "user"),
            "summary_digest": summary_digest(messages),
            "approvals": approvals,
        }
        state["turns"][key] = record
        _save_state(state_path, state)

        replay = record["replay"] or {}
        trim = replay.get("trim") or {}
        print(
            f"[{arm}] turn {turn:>2}  prompt {record['prompt_tokens'] or 0:>6}  "
            f"cache {record['cache_read_tokens'] or 0:>6}  "
            f"replay {replay.get('decision')}  "
            f"trim {'YES' if trim else '-'}  "
            f"win {record['window_turns']}t/{record['window_messages']}m  "
            f"{record['stopped_by']}",
            flush=True,
        )
    print(f"[{arm}] done: {len(state['turns'])} turns recorded in {state_path}", flush=True)
    return 0


def _rows(arm: dict[str, Any], turns: int = TURNS) -> list[dict[str, Any]]:
    return [arm["turns"][str(t)] for t in range(1, turns + 1) if str(t) in arm["turns"]]


def _reuse(rows: list[dict[str, Any]]) -> dict[int, float]:
    """``reuse[turn]`` = this turn's cache reads / the previous turn's prompt (R4)."""
    out: dict[int, float] = {}
    for previous, current in itertools.pairwise(rows):
        if previous["prompt_tokens"]:
            out[current["turn"]] = (current["cache_read_tokens"] or 0) / previous["prompt_tokens"]
    return out


def carrier_audit(out_dir: Path) -> dict[str, Any]:
    """Re-check *now* that no arm's run directory still holds a dump file.

    The live per-turn check can race the parent's ingest commit (it did, once). The
    audit is a separate timestamped artifact rather than an edit to the run
    records, so a disagreement between the two stays visible instead of being
    quietly reconciled.
    """
    from server.config import run_dir_for

    audit: dict[str, Any] = {"checked_at": time.strftime("%Y-%m-%d %H:%M:%S"), "arms": {}}
    for arm in ARMS:
        path = out_dir / f"{arm}-turns.json"
        if not path.is_file():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))["turns"]
        left = [
            turn
            for turn, record in rows.items()
            if (Path(run_dir_for(record["run_id"])) / "run" / "conversation.json").is_file()
        ]
        audit["arms"][arm] = {"turns": len(rows), "dumps_left": sorted(left, key=int)}
    (out_dir / "carrier-audit.json").write_text(
        json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return audit


def _error_sample(arm: dict[str, Any], out_dir: Path) -> str:
    """The first worker-side error line of an arm that could not reach the model.

    Kept in the evidence because "the run stopped" is not a diagnosis: without the
    line, a quota wall and a broken chain look identical in the counters.
    """
    del out_dir
    from server.config import run_dir_for

    for turn in sorted(arm["turns"], key=int):
        record = arm["turns"][turn]
        log = Path(run_dir_for(record["run_id"])) / "run" / "engine.log"
        if not log.is_file():
            continue
        for line in log.read_text(encoding="utf-8", errors="replace").splitlines():
            if "Non-transient LLM error" in line or "ERROR" in line:
                return line.strip()[:300]
    return ""


def verdict(out_dir: Path) -> dict[str, Any]:
    treatment = json.loads((out_dir / "treatment-turns.json").read_text(encoding="utf-8"))
    control = json.loads((out_dir / "control-turns.json").read_text(encoding="utf-8"))
    treat_rows, control_rows = _rows(treatment), _rows(control)
    treat_reuse, control_reuse = _reuse(treat_rows), _reuse(control_rows)

    def complete(rows: list[dict[str, Any]]) -> bool:
        return (
            len(rows) == TURNS
            and all(r["status"] not in {"queued", "running"} and not r["error"] for r in rows)
            and all((r["llm_calls"] or 0) >= 1 for r in rows)
        )

    audit_path = out_dir / "carrier-audit.json"
    audit = json.loads(audit_path.read_text(encoding="utf-8")) if audit_path.is_file() else None

    def carrier(rows: list[dict[str, Any]], arm: str) -> bool:
        if audit and arm in audit["arms"]:
            return not audit["arms"][arm]["dumps_left"]
        return all(
            (r.get("dump_gone_later", not r["dump_present_after_run"])) and r["stored_after_run"]
            for r in rows
        )

    def sized(rows: list[dict[str, Any]]) -> bool:
        return all((r["prompt_tokens"] or 0) <= REPLAY_MAX_TOKENS for r in rows)

    # A run whose *replay* carried a trim had its prefix broken (that turn is the
    # miss). Recovery is the two turns after it.
    miss_turns = [r["turn"] for r in treat_rows if (r["replay"] or {}).get("trim")]
    recoveries = {
        miss: [
            round(treat_reuse.get(miss + 1, 0.0), 4),
            round(treat_reuse.get(miss + 2, 0.0), 4),
        ]
        for miss in miss_turns
        if miss + 1 <= TURNS
    }
    flapped_once = all(all(value >= 0.8 for value in values) for values in recoveries.values())

    digests = [r["summary_digest"] for r in treat_rows]
    # The block *appearing* is not a rewrite — count only transitions between two
    # existing blocks, or the first cut would be counted twice (created + cut).
    changes = sum(
        1
        for before, after in itertools.pairwise(digests)
        if before is not None and after is not None and before != after
    )

    treat_mean = sum(treat_reuse.values()) / len(treat_reuse) if treat_reuse else 0.0
    control_mean = sum(control_reuse.values()) / len(control_reuse) if control_reuse else 0.0

    # Two different reasons a turn can miss, and the raw ratio cannot tell them
    # apart. A cut rewrites message[1] (the memory block), so that turn's prefix
    # breaks *by construction* on our side. Every other transition is a pure
    # append, so a miss there is the provider not retaining a prefix we did keep.
    preserved = {turn: value for turn, value in treat_reuse.items() if turn not in miss_turns}
    endpoint_misses = sorted(turn for turn, value in preserved.items() if value < 0.8)
    preserved_hits = sorted(turn for turn, value in preserved.items() if value >= 0.8)

    def plateau(rows: list[dict[str, Any]]) -> bool:
        early = [r["prompt_tokens"] or 0 for r in rows if 15 <= r["turn"] <= 25]
        late = [r["prompt_tokens"] or 0 for r in rows if r["turn"] > TURNS - 10]
        if not early or not late:
            return False
        return max(late) <= 1.5 * max(early)

    checks = {
        "C1_complete_both_arms": complete(treat_rows) and complete(control_rows),
        "C2_carrier_moved_every_turn": carrier(treat_rows, "treatment")
        and carrier(control_rows, "control"),
        "C3_prompt_within_budget": sized(treat_rows),
        "C4_cut_flaps_once": flapped_once,
        "C5_memory_written_once_per_cut": changes <= max(1, len(miss_turns)),
        "C6_arms_differ": treat_mean >= 0.8
        and control_mean <= 0.6
        and treat_mean - control_mean >= 0.2,
        "C7_prompt_plateaus": plateau(treat_rows),
    }
    # A control arm that could not talk to the model cannot judge anything: those
    # turns have no counters at all, so C1/C6 are *blocked*, not refuted.
    control_blocked = [r["turn"] for r in control_rows if (r["llm_calls"] or 0) < 1]
    detail = {
        "turns": {"treatment": len(treat_rows), "control": len(control_rows)},
        "mean_reuse": {"treatment": round(treat_mean, 4), "control": round(control_mean, 4)},
        "miss_turns_treatment": miss_turns,
        "recovery_after_each_miss": recoveries,
        "prefix_preserving_turns": {
            "mean_reuse": round(sum(preserved.values()) / len(preserved) if preserved else 0.0, 4),
            "hit_turns": preserved_hits,
            "endpoint_side_misses": endpoint_misses,
        },
        "control_blocked_turns": control_blocked,
        "control_error_sample": _error_sample(control, out_dir),
        "carrier_live_check": {
            "treatment_dump_left": [r["turn"] for r in treat_rows if r["dump_present_after_run"]],
            "control_dump_left": [r["turn"] for r in control_rows if r["dump_present_after_run"]],
        },
        "carrier_audit": audit,
        "summary_digest_changes": changes,
        "prompt_tokens": {
            "treatment": [r["prompt_tokens"] for r in treat_rows],
            "control": [r["prompt_tokens"] for r in control_rows],
        },
        "cache_read_tokens": {
            "treatment": [r["cache_read_tokens"] for r in treat_rows],
            "control": [r["cache_read_tokens"] for r in control_rows],
        },
        "stopped_by": {
            "treatment": sorted({str(r["stopped_by"]) for r in treat_rows}),
            "control": sorted({str(r["stopped_by"]) for r in control_rows}),
        },
    }
    blocked = [
        name
        for name in ("C1_complete_both_arms", "C6_arms_differ")
        if not checks[name] and control_blocked
    ]
    return {
        "checks": checks,
        "blocked": blocked,
        "detail": detail,
        "pass": all(checks.values()),
    }


def write_report(out_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# S3 验收：跨轮窗口的前缀性质（issue 01 §12.5 / §12.8）",
        "",
        "两臂同一份代码，唯一差别是 `REPLAY_MAX_TURN_STEP`（treatment 5 = 新默认，control 0 = 迟滞前）。",
        f"每臂 {TURNS} 轮、每轮一个独立 worker 子进程；载体是数据库（S2）。",
        "",
        f"- **通过：{result['pass']}**",
        "",
        "| 判据 | 结果 |",
        "|---|---|",
    ]
    lines += [
        f"| {name} | {'BLOCKED' if name in result['blocked'] else ('PASS' if ok else 'FAIL')} |"
        for name, ok in result["checks"].items()
    ]
    detail = result["detail"]
    preserved = detail["prefix_preserving_turns"]
    lines += [
        "",
        "| 口径 | 值 |",
        "|---|---|",
        f"| 平均复用率 treatment（全 44 次转换） | {detail['mean_reuse']['treatment'] * 100:.1f}% |",
        f"| ├ 前缀保持轮（{len(preserved['hit_turns']) + len(preserved['endpoint_side_misses'])} 次） | {preserved['mean_reuse'] * 100:.1f}% |",
        f"| │ ├ ≥80% 的轮 | {preserved['hit_turns']} |",
        f"| │ └ 端点侧 miss（我方前缀连续却未命中） | {preserved['endpoint_side_misses']} |",
        f"| └ 裁剪轮（构造性 miss，system+tools only） | {detail['miss_turns_treatment']} |",
        f"| 每个裁剪轮之后的复用（两轮） | {json.dumps(detail['recovery_after_each_miss'], ensure_ascii=False)} |",
        f"| 摘要块变化次数（裁剪 {len(detail['miss_turns_treatment'])} 次） | {detail['summary_digest_changes']} |",
        f"| stopped_by | {json.dumps(detail['stopped_by'], ensure_ascii=False)} |",
    ]
    if detail["control_blocked_turns"]:
        lines += [
            "",
            "## 未能判定：control 臂有轮次无计量",
            "",
            f"- control 无计量的轮：{detail['control_blocked_turns']}",
            f"- worker 侧错误样本：`{detail['control_error_sample']}`",
        ]
    lines += [
        "",
        "逐轮 prompt / cache_read 见 `results.json` 的 `detail`。",
    ]
    (out_dir / "report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    (out_dir / "results.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--arm", choices=tuple(ARMS))
    parser.add_argument("--turns", type=int, default=TURNS)
    parser.add_argument("--model", default="")
    parser.add_argument("--wait", type=float, default=300.0)
    # Seconds to wait before re-checking that the run's dump file is gone: the
    # parent deletes it when its ingest commits, which trails the terminal status.
    parser.add_argument("--grace", type=float, default=3.0)
    parser.add_argument("--verdict", action="store_true")
    parser.add_argument("--carrier-audit", action="store_true")
    args = parser.parse_args(argv)

    os.chdir(REPO_ROOT)
    out_dir = Path(args.out)
    if args.carrier_audit:
        print(json.dumps(carrier_audit(out_dir), ensure_ascii=False, indent=2))
        return 0
    if args.verdict:
        result = verdict(out_dir)
        write_report(out_dir, result)
        print(
            json.dumps(
                {"pass": result["pass"], "checks": result["checks"]}, ensure_ascii=False, indent=2
            )
        )
        return 0 if result["pass"] else 1
    if not args.arm:
        raise SystemExit("pass --arm, or --verdict")
    return asyncio.run(run_arm(args))


if __name__ == "__main__":
    raise SystemExit(main())
