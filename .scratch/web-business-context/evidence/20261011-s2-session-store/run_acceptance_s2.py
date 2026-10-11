"""S2 acceptance: cross-turn continuity through the session store (issue 01 §11.7).

Registered criteria (signed off 2026-10-11, before the run):

  P1  treatment turns 2 and 3 report ``replay.decision == "used"``
  P2  after every treatment turn the dump file is gone and the session row is
      there (the carrier really moved)
  P3  control turns 2 and 3 report ``skipped`` — its session row is deleted
      after each turn, so "no carrier" is the only difference between the arms
  P4  treatment turn 3 reuses >= 80% of turn 2's prompt (R4 wording, §9.17)
  P5  turn N's stored messages start with turn N-1's, message for message (the
      byte-stable-prefix property, stated on our side of the wire)
  P6  the three turns ran in three different processes (a run's OS pid is
      recorded per turn) — this is what makes "survives a restart" a fact rather
      than a claim about one process

Why per-turn invocations: the whole point of S2 is that continuity lives in the
database instead of in a process or a directory, so the strongest available test
is to run each turn in its own process. One process that keeps objects alive
would pass even if the carrier were still in memory.

  # turn 1 of each arm creates the session; turns 2-3 read it back from the
  # arm's ``<arm>-turn1.json`` in the same --out directory.
  uv run python .../run_acceptance_s2.py --out DIR --arm treatment --turn 1
  uv run python .../run_acceptance_s2.py --out DIR --arm treatment --turn 2
  uv run python .../run_acceptance_s2.py --out DIR --arm treatment --turn 3
  uv run python .../run_acceptance_s2.py --out DIR --arm control  --turn 1
  uv run python .../run_acceptance_s2.py --out DIR --arm control  --turn 2
  uv run python .../run_acceptance_s2.py --out DIR --arm control  --turn 3
  uv run python .../run_acceptance_s2.py --out DIR --verdict

The model comes from ``--model`` or the server's own ``OPENAI_MODEL`` (the
deployment's choice). Before running, a probe must show that model reporting a
cache-hit field — ``prompt_tokens_details.cached_tokens`` is what
``frontier_agent/infra/openai_client.py`` reads.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import json
import os
import time
import uuid
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[4]

FILLER_SENTENCE = "以下内容是无关背景资料，仅用于把上下文撑到可缓存的长度，请忽略其具体内容。" * 8
TURN1 = (
    f"{FILLER_SENTENCE * 20}\n\n"
    "以上全部是背景噪音。请只回复两个字：收到。不要调用任何工具。"
)
FOLLOW_UP = "请再确认一次，仍然只回复两个字：收到。不要调用任何工具。"
PROMPTS = {1: TURN1, 2: FOLLOW_UP, 3: FOLLOW_UP}


def _dotenv_value(key: str) -> str:
    """Read one key from the repo ``.env`` without echoing anything else."""
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


async def _bound_research_seed(store: Any) -> tuple[uuid.UUID, uuid.UUID]:
    """Reuse a real (user, account) pair so the new research is genuinely bound."""
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

    research_id = uuid.uuid4()
    await store_mod.ensure_session(session_id=research_id, user_id=user_id, title=title)
    async with store_mod.get_sessionmaker()() as session:
        session.add(
            store_mod.ResearchInvestmentLink(
                research_id=research_id,
                user_id=user_id,
                account_id=account_id,
                primary_plan_id=None,
            )
        )
        await session.commit()
    if not await store_mod.session_has_research_binding(research_id=research_id):
        raise SystemExit("research binding was not visible to session_has_research_binding")
    return research_id


async def _wait_run(
    store: Any, run_uuid: uuid.UUID, user_id: uuid.UUID, *, timeout: float
) -> Any:
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
    """Emulate the browser's verdict for every confirm-level tool call.

    Without this, an unattended run parks on the approval gate for the gate's full
    fail-closed timeout (``server/approval.py: DEFAULT_TIMEOUT_S``) *per gated
    call* — correct product behaviour, but it costs five minutes per ``bash`` and
    looks like a hang. This sends the same stdin frame the
    ``POST /runs/{run_id}/approve`` route sends; ``session_all`` approves the rest
    of the run so later gated calls do not park again.
    """
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
                {
                    "approval_id": approval_id,
                    "tool_name": frame.get("tool_name"),
                    "target": frame.get("target"),
                    "decision": decision,
                    "delivered": bool(delivered),
                }
            )
            print(
                f"[auto-approve] {frame.get('tool_name')} {approval_id} -> {decision} "
                f"delivered={delivered}",
                flush=True,
            )
    finally:
        orchestrator.unsubscribe(run_id, queue)


async def _delete_carrier(session_uuid: uuid.UUID) -> int:
    """Drop the session's stored conversation (the control arm's only difference)."""
    from sqlalchemy import text

    from server.store import get_sessionmaker

    async with get_sessionmaker()() as session:
        result = await session.execute(
            text("delete from session_conversations where session_id = :sid"),
            {"sid": session_uuid},
        )
        await session.commit()
        return result.rowcount or 0


async def run_turn(args: argparse.Namespace) -> int:
    from server import store
    from server.orchestrator import Orchestrator
    from server.store import read_session_conversation

    out_dir = Path(args.out)
    out_dir.mkdir(parents=True, exist_ok=True)
    turn_file = out_dir / f"{args.arm}-turn{args.turn}.json"
    if turn_file.exists():
        raise SystemExit(f"{turn_file} exists — write-once evidence")

    model = args.model or _env_or_dotenv("OPENAI_MODEL")
    if not model:
        raise SystemExit("no model: pass --model or set OPENAI_MODEL")
    os.environ["OPENAI_MODEL"] = model
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        value = _env_or_dotenv(key)
        if not value:
            raise SystemExit(f"{key} missing (env + .env)")
        os.environ[key] = value

    user_id: uuid.UUID
    session_uuid: uuid.UUID
    if args.turn == 1:
        seed_user, account_id = await _bound_research_seed(store)
        session_uuid = await _make_session(
            store, user_id=seed_user, account_id=account_id, title=f"S2 acceptance {args.arm}"
        )
        user_id = seed_user
    else:
        first = json.loads((out_dir / f"{args.arm}-turn1.json").read_text(encoding="utf-8"))
        session_uuid = uuid.UUID(first["session_id"])
        user_id = uuid.UUID(first["user_id"])

    prompt = PROMPTS[args.turn]
    run_hex = uuid.uuid4().hex
    run_uuid = uuid.UUID(run_hex)
    from server.config import run_dir_for

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
    orchestrator = Orchestrator()
    await orchestrator.submit(
        run_id=run_hex,
        session_id=str(session_uuid),
        prompt=prompt,
        user_id=None,  # keep the server's own .env credentials
        turn_index=args.turn,
        backfill_turn=True,
    )
    approvals: list[dict[str, Any]] = []
    watcher: asyncio.Task[None] | None = None
    if args.auto_approve != "off":
        watcher = asyncio.create_task(
            _auto_approve(orchestrator, run_hex, args.auto_approve, approvals)
        )
    try:
        row = await _wait_run(store, run_uuid, user_id, timeout=args.wait)
    finally:
        if watcher is not None:
            watcher.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await watcher
    if row is None:
        raise SystemExit(f"timeout after {args.wait}s waiting for a terminal status")

    usage = row.usage_json or {}
    payload = await read_session_conversation(session_id=session_uuid)
    messages: list[dict] = []
    revision = None
    if payload:
        document = json.loads(payload)
        messages = document.get("messages") or []
        revision = document.get("turns_used")
    rows_deleted = 0
    if args.arm == "control":
        rows_deleted = await _delete_carrier(session_uuid)

    record = {
        "arm": args.arm,
        "turn": args.turn,
        "pid": os.getpid(),
        "model": model,
        "session_id": session_uuid.hex,
        "user_id": user_id.hex,
        "run_id": run_hex,
        "status": row.status,
        "stopped_by": row.stopped_by,
        "prompt_tokens": row.prompt_tokens,
        "cache_read_tokens": row.cache_read_tokens,
        "llm_calls": row.llm_calls,
        "usage_status": usage.get("status"),
        "replay": usage.get("replay"),
        "final_answer_head": (row.final_answer or "")[:120],
        "error": row.error,
        # The carrier moved: the dump must be gone once the run finished.
        "dump_present_after_run": (run_root / "run" / "conversation.json").is_file(),
        "staging_present": (run_root / "prior_conversation.json").is_file(),
        "stored_after_run": payload is not None,
        "stored_messages": messages,
        "stored_turns_used": revision,
        "control_rows_deleted": rows_deleted,
        "run_root": str(run_root),
        "auto_approve": args.auto_approve,
        "approvals": approvals,
    }
    turn_file.write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
    print(
        json.dumps(
            {
                "arm": args.arm,
                "turn": args.turn,
                "session": session_uuid.hex,
                "prompt": record["prompt_tokens"],
                "cache_read": record["cache_read_tokens"],
                "replay": (record["replay"] or {}).get("decision"),
                "dump_present_after_run": record["dump_present_after_run"],
                "stored_after_run": record["stored_after_run"],
            },
            ensure_ascii=False,
        )
    )
    return 0


def _load(out_dir: Path, arm: str, turn: int) -> dict[str, Any]:
    path = out_dir / f"{arm}-turn{turn}.json"
    if not path.is_file():
        raise SystemExit(f"missing {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def verdict(out_dir: Path) -> dict[str, Any]:
    treatment = {turn: _load(out_dir, "treatment", turn) for turn in (1, 2, 3)}
    control = {turn: _load(out_dir, "control", turn) for turn in (1, 2, 3)}

    def decision(arm: dict[int, dict[str, Any]], turn: int) -> str:
        return str((arm[turn].get("replay") or {}).get("decision") or "")

    def num(arm: dict[int, dict[str, Any]], turn: int, key: str) -> int:
        return int(arm[turn].get(key) or 0)

    def prefix_holds() -> bool:
        for turn in (2, 3):
            previous = treatment[turn - 1]["stored_messages"]
            current = treatment[turn]["stored_messages"]
            if not previous or current[: len(previous)] != previous:
                return False
        return True

    turn2_prompt = num(treatment, 2, "prompt_tokens")
    turn3_cache = num(treatment, 3, "cache_read_tokens")
    checks = {
        "P1_treatment_replays_from_turn_2": all(
            decision(treatment, turn) == "used" for turn in (2, 3)
        ),
        "P2_dump_gone_and_row_stored_every_turn": all(
            treatment[turn]["dump_present_after_run"] is False
            and treatment[turn]["stored_after_run"] is True
            for turn in (1, 2, 3)
        ),
        "P3_control_has_no_carrier": all(
            decision(control, turn) == "skipped" for turn in (2, 3)
        ),
        "P4_turn3_reuses_80pct_of_turn2_prompt": bool(turn2_prompt)
        and turn3_cache >= 0.8 * turn2_prompt,
        "P5_stored_prefix_matches_previous_turn": prefix_holds(),
        "P6_three_separate_processes": len({treatment[t]["pid"] for t in (1, 2, 3)}) == 3,
    }
    detail = {
        "treatment": {
            turn: {
                "prompt_tokens": num(treatment, turn, "prompt_tokens"),
                "cache_read_tokens": num(treatment, turn, "cache_read_tokens"),
                "replay": decision(treatment, turn),
                "stored_messages": len(treatment[turn]["stored_messages"]),
            }
            for turn in (1, 2, 3)
        },
        "control": {
            turn: {
                "prompt_tokens": num(control, turn, "prompt_tokens"),
                "cache_read_tokens": num(control, turn, "cache_read_tokens"),
                "replay": decision(control, turn),
                "reason": (control[turn].get("replay") or {}).get("reason"),
            }
            for turn in (1, 2, 3)
        },
        "turn3_reuse_of_turn2": (turn3_cache / turn2_prompt) if turn2_prompt else None,
        "pids": [treatment[t]["pid"] for t in (1, 2, 3)],
    }
    return {"checks": checks, "detail": detail, "pass": all(checks.values())}


def write_report(out_dir: Path, result: dict[str, Any]) -> None:
    lines = [
        "# S2 验收：会话状态归位（issue 01 §11.7）",
        "",
        "- 两臂各 3 轮，**每轮一个独立进程**（`--turn N` 分次调用）；treatment 正常，control 每轮后删掉库中会话行。",
        "- 模型与端点取自服务器 `.env`（跑前探针确认其上报 `prompt_tokens_details.cached_tokens`）。",
        f"- 判定：**{'PASS' if result['pass'] else 'FAIL'}**",
        "",
        "## 判据",
        "",
    ]
    for name, ok in result["checks"].items():
        lines.append(f"- {'PASS' if ok else 'FAIL'} — `{name}`")
    lines += ["", "## 判据明细", "", f"```json\n{json.dumps(result['detail'], ensure_ascii=False, indent=2)}\n```", ""]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=(__doc__ or "").splitlines()[0])
    parser.add_argument("--out", required=True)
    parser.add_argument("--arm", choices=("treatment", "control"))
    parser.add_argument("--turn", type=int, choices=(1, 2, 3))
    parser.add_argument("--model", default="")
    parser.add_argument("--verdict", action="store_true")
    # A confirm-level tool call parks the loop on the approval gate until a human
    # decides (or the gate's 300s fail-closed timeout expires), so an unattended
    # run needs either a longer wait or a verdict. ``session_all`` is the browser's
    # "approve the rest of this run" button.
    parser.add_argument("--wait", type=float, default=300.0)
    parser.add_argument(
        "--auto-approve",
        choices=("off", "once", "session_bash", "session_all"),
        default="off",
    )
    args = parser.parse_args(argv)

    os.chdir(REPO_ROOT)
    if args.verdict:
        result = verdict(Path(args.out))
        (Path(args.out) / "results.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        write_report(Path(args.out), result)
        print(json.dumps({"pass": result["pass"], "checks": result["checks"]}, ensure_ascii=False, indent=2))
        return 0 if result["pass"] else 1
    if not args.arm or not args.turn:
        raise SystemExit("pass --arm and --turn, or --verdict")
    return asyncio.run(run_turn(args))


if __name__ == "__main__":
    raise SystemExit(main())
