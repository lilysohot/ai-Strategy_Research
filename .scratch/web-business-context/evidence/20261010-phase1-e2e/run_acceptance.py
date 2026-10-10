"""Phase-1 acceptance for issue 01 (cross-turn context inheritance).

Registered criteria (issue 01 §9.9 + §9.14 R1-R3):

  treatment  3 runs in ONE bound research (business session, so the request
             prefix carries the business policy + business tools), turn 1's
             prompt padded to ~3-4k tokens so the shared prefix clears the
             provider's minimum cacheable length.
  control    same shape, but each run's ``run/conversation.json`` is moved aside
             after it finishes, so the next run finds nothing to replay.

  pass       treatment: turn 2 ``cache_read_tokens`` >= turn 1 ``prompt_tokens``
             AND turn 3 >= half of turns 1+2 ``prompt_tokens``
             AND all three runs report ``replay.decision == "used"``.
             control: turns 2-3 ``cache_read_tokens`` stay below half of turn 1's
             ``prompt_tokens`` and report ``replay.decision == "skipped"``.

  local      independent of the provider: turn N's dump must *start with* turn
             N-1's dump, message for message (canonical JSON). That is the
             byte-stable-prefix property stated on our side of the wire.

Run into a fresh directory (write-once evidence; the script never overwrites):

  uv run python .scratch/web-business-context/evidence/20261010-phase1-e2e/run_acceptance.py \
      --out .scratch/web-business-context/evidence/20261010-phase1-e2e/run-<stamp> \
      --model deepseek-v4-flash-ga-260731
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
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


async def _bound_research_seed(store: Any) -> tuple[uuid.UUID, uuid.UUID]:
    """Reuse a real (user, account) pair so the new research is genuinely bound."""
    from sqlalchemy import select

    async with store.get_sessionmaker()() as session:
        row = (
            await session.execute(
                select(store.ResearchInvestmentLink).where(
                    store.ResearchInvestmentLink.account_id.is_not(None)
                ).limit(1)
            )
        ).scalar_one_or_none()
    if row is None:
        raise SystemExit("no bound research in this database — cannot build the arm")
    return row.user_id, row.account_id


async def _make_session(store: Any, *, user_id: uuid.UUID, account_id: uuid.UUID, title: str):
    from server import store as store_mod

    research_id = uuid.uuid4()
    await store_mod.ensure_session(session_id=research_id, user_id=user_id, title=title)
    async with store_mod.get_sessionmaker()() as session:
        session.add(
            store_mod.ResearchInvestmentLink(
                research_id=research_id, user_id=user_id, account_id=account_id,
                primary_plan_id=None,
            )
        )
        await session.commit()
    bound = await store_mod.session_has_research_binding(research_id=research_id)
    if not bound:
        raise SystemExit("research binding was not visible to session_has_research_binding")
    return research_id


async def _wait_run(store: Any, run_uuid: uuid.UUID, user_id: uuid.UUID, *, timeout: float):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        row = await store.get_run(run_id=run_uuid, user_id=user_id)
        if row is not None and row.status not in store.ACTIVE_RUN_STATUSES:
            # usage is metered in _spawn's finally, just after the terminal status
            for _ in range(120):
                if row.usage_json is not None:
                    break
                await asyncio.sleep(0.5)
                row = await store.get_run(run_id=run_uuid, user_id=user_id)
            return row
        await asyncio.sleep(1.0)
    return None


def _dump_summary(run_root: Path) -> dict[str, Any]:
    dump = run_root / "run" / "conversation.json"
    if not dump.is_file():
        return {"exists": False}
    try:
        document = json.loads(dump.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {"exists": True, "readable": False}
    messages = document.get("messages") or []
    return {
        "exists": True,
        "readable": True,
        "messages": len(messages),
        "user_turns": sum(1 for m in messages if m.get("role") == "user"),
        "trim": document.get("trim"),
        "system_prompt_len": len(document.get("system_prompt") or ""),
        "tool_names": document.get("tool_names") or [],
        "raw": document,
    }


async def _run_arm(store: Any, orch: Any, *, label: str, out_dir: Path, model: str,
                   turns: int, drop_dump_after: bool) -> dict[str, Any]:
    user_id, account_id = await _bound_research_seed(store)
    research_id = await _make_session(
        store, user_id=user_id, account_id=account_id, title=f"phase1-e2e {label}",
    )
    record: dict[str, Any] = {
        "label": label, "research_id": research_id.hex, "model": model, "runs": [],
    }
    previous_dump: list[dict] | None = None

    for index in range(1, turns + 1):
        run_hex = uuid.uuid4().hex
        run_uuid = uuid.UUID(run_hex)
        prompt = TURN1 if index == 1 else FOLLOW_UP
        run_root = Path(store_run_dir(run_hex))
        await store.create_run(
            run_id=run_uuid,
            session_id=research_id,
            user_id=user_id,
            prompt=prompt,
            pipeline_id="stateful-react-agent",
            run_dir=str(run_root),
            status="queued",
        )
        await orch.submit(
            run_id=run_hex,
            session_id=str(research_id),
            prompt=prompt,
            user_id=None,  # keep the server's own .env credentials
            turn_index=index,
            backfill_turn=True,
        )
        row = await _wait_run(store, run_uuid, user_id, timeout=300.0)
        if row is None:
            record["runs"].append({"turn": index, "error": "timeout waiting for terminal status"})
            break

        usage = row.usage_json or {}
        summary_path = run_root / "summary.json"
        summary = json.loads(summary_path.read_text(encoding="utf-8")) if summary_path.is_file() else {}
        dump = _dump_summary(run_root)
        prefix_ok = None
        if previous_dump is not None and dump.get("exists"):
            current = dump["raw"]["messages"]
            prefix_ok = current[: len(previous_dump)] == previous_dump

        record["runs"].append({
            "turn": index,
            "run_id": run_hex,
            "status": row.status,
            "stopped_by": row.stopped_by,
            "prompt_tokens": row.prompt_tokens,
            "cache_read_tokens": row.cache_read_tokens,
            "llm_calls": row.llm_calls,
            "usage": {k: usage.get(k) for k in ("prompt_tokens", "cache_read_tokens", "cache_write_tokens")},
            "usage_status": usage.get("status"),
            "replay": summary.get("replay"),
            "final_answer_head": (row.final_answer or "")[:120],
            "error": row.error,
            "dump": {k: v for k, v in dump.items() if k != "raw"},
            "prefix_matches_previous_dump": prefix_ok,
            "run_root": str(run_root),
        })
        previous_dump = dump["raw"]["messages"] if dump.get("exists") else previous_dump

        if drop_dump_after and dump.get("exists"):
            dump_path = run_root / "run" / "conversation.json"
            moved = dump_path.with_name("conversation.moved-by-control.json")
            shutil.move(str(dump_path), str(moved))
            record["runs"][-1]["dump_moved_to"] = str(moved)

    (out_dir / f"{label}.json").write_text(
        json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    return record


def store_run_dir(run_hex: str) -> str:
    from server.config import run_dir_for

    return str(run_dir_for(run_hex))


def _verdict(treatment: dict[str, Any], control: dict[str, Any]) -> dict[str, Any]:
    def turn(arm: dict[str, Any], index: int) -> dict[str, Any]:
        for entry in arm["runs"]:
            if entry.get("turn") == index:
                return entry
        return {}

    def num(entry: dict[str, Any], key: str) -> int:
        value = entry.get(key)
        return int(value) if isinstance(value, int) else 0

    t1, t2, t3 = turn(treatment, 1), turn(treatment, 2), turn(treatment, 3)
    c1, c2, c3 = turn(control, 1), turn(control, 2), turn(control, 3)
    checks = {
        "t2_covers_t1_prompt": num(t2, "cache_read_tokens") >= num(t1, "prompt_tokens") > 0,
        "t3_covers_most_of_t1_t2": num(t3, "cache_read_tokens")
        >= 0.5 * (num(t1, "prompt_tokens") + num(t2, "prompt_tokens")),
        "treatment_replayed_all_turns": all(
            (turn(treatment, i).get("replay") or {}).get("decision") == "used" for i in (1, 2, 3)
        ),
        "control_did_not_replay": all(
            (turn(control, i).get("replay") or {}).get("decision") == "skipped" for i in (2, 3)
        ),
        "control_cache_cold": num(c2, "cache_read_tokens") < 0.5 * num(c1, "prompt_tokens")
        and num(c3, "cache_read_tokens") < 0.5 * num(c1, "prompt_tokens"),
        "treatment_prefix_matches_previous_dump": t2.get("prefix_matches_previous_dump") is True
        and t3.get("prefix_matches_previous_dump") is True,
    }
    return {
        "checks": checks,
        "thresholds": {
            "t2_needs": num(t1, "prompt_tokens"),
            "t3_needs_half_of": 0.5 * (num(t1, "prompt_tokens") + num(t2, "prompt_tokens")),
            "control_must_stay_below": 0.5 * num(c1, "prompt_tokens"),
        },
        "pass": all(checks.values()),
    }


def _write_report(out_dir: Path, treatment: dict[str, Any], control: dict[str, Any],
                  verdict: dict[str, Any], model: str) -> None:
    lines = [
        "# 阶段 1 端到端验收（issue 01 §9.9.4）",
        "",
        f"- 模型：`{model}`；口径：`runs.usage_json`（`server/usage.py`）；两臂各 3 轮，同一绑定研究内。",
        f"- 判定：**{'PASS' if verdict['pass'] else 'FAIL'}**",
        "",
        "| 臂 | 轮 | prompt_tokens | cache_read_tokens | llm_calls | replay.decision | dump(messages) | 前缀=上一轮 dump |",
        "|---|---|---|---|---|---|---|---|",
    ]
    for arm in (treatment, control):
        for entry in arm["runs"]:
            replay = entry.get("replay") or {}
            dump = entry.get("dump") or {}
            lines.append(
                f"| {arm['label']} | {entry.get('turn')} | {entry.get('prompt_tokens')} | "
                f"{entry.get('cache_read_tokens')} | {entry.get('llm_calls')} | "
                f"{replay.get('decision')}{': ' + str(replay.get('reason')) if replay.get('reason') else ''} | "
                f"{dump.get('messages')} | {entry.get('prefix_matches_previous_dump')} |"
            )
    lines += ["", "## 判据", ""]
    for name, ok in verdict["checks"].items():
        lines.append(f"- {'PASS' if ok else 'FAIL'} — `{name}`")
    lines += ["", "## 阈值", "", f"```json\n{json.dumps(verdict['thresholds'], indent=2)}\n```", ""]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="deepseek-v4-flash-ga-260731")
    parser.add_argument("--turns", type=int, default=3)
    parser.add_argument("--only", choices=("treatment", "control"), default=None)
    parser.add_argument(
        "--backend", default=None,
        help="SANDBOX_BACKEND for the arm (native = this box's default; container = the "
             "production model, whose system prompt renders the logical /workspace paths)",
    )
    args = parser.parse_args()

    out_dir = Path(args.out)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"{out_dir} is not empty — write-once evidence, pick a fresh dir")
    out_dir.mkdir(parents=True, exist_ok=True)

    # Credentials: the server's own .env, with the model swapped for the run.
    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        value = os.environ.get(key) or _dotenv_value(key)
        if not value:
            raise SystemExit(f"{key} missing (env + .env)")
        os.environ[key] = value
    os.environ["OPENAI_MODEL"] = args.model
    os.environ.setdefault("FRONTIER_AGENT_LLM_STICKY_SESSION", "1")
    if args.backend:
        # Before ``get_config()`` so the orchestrator hands this backend to the
        # worker (which passes it to ``apply_env`` as SANDBOX_BACKEND).
        os.environ["SANDBOX_BACKEND"] = args.backend

    from server import store
    from server.config import get_config
    from server.orchestrator import Orchestrator

    config = get_config()
    orchestrator = Orchestrator()
    meta = {
        "model_arg": args.model,
        "pipeline_id": config.pipeline_id,
        "sandbox_backend": config.sandbox_backend,
        "wall_timeout_s": config.wall_timeout_s,
        "runs_root": str(config.runs_root),
    }

    treatment: dict[str, Any] = {"label": "treatment", "runs": []}
    control: dict[str, Any] = {"label": "control", "runs": []}
    if args.only in (None, "treatment"):
        treatment = await _run_arm(
            store, orchestrator, label="treatment", out_dir=out_dir, model=args.model,
            turns=args.turns, drop_dump_after=False,
        )
    if args.only in (None, "control"):
        control = await _run_arm(
            store, orchestrator, label="control", out_dir=out_dir, model=args.model,
            turns=args.turns, drop_dump_after=True,
        )
    if args.only is not None:
        # Pre-flight / single-arm diagnostic: no verdict, just the raw record.
        payload = {"meta": meta, args.only: treatment if args.only == "treatment" else control}
        (out_dir / "results.json").write_text(
            json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(json.dumps(payload, ensure_ascii=False, indent=2)[:4000])
        return 0
    verdict = _verdict(treatment, control)
    payload = {"meta": meta, "treatment": treatment, "control": control, "verdict": verdict}
    (out_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8",
    )
    _write_report(out_dir, treatment, control, verdict, args.model)
    print(json.dumps({"out": str(out_dir), "pass": verdict["pass"], "checks": verdict["checks"]},
                     ensure_ascii=False, indent=2))
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
