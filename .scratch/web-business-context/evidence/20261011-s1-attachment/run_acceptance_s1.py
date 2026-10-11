"""S1 acceptance: one attachment turn followed by a plain turn (issue 01 §10.7).

Registered criteria (signed off 2026-10-11, before the run):

  C1  the uploaded-file note is NOT in the turn's system prompt   (S1-b fix)
  C2  the note IS in the turn's user message                      (same bytes, tail)
  C3  the two turns' system prompts are byte-identical            (prefix constant)
  C4  turn 2 reports ``replay.decision == "used"``                (history reached the model)
  C5  turn 2's dump starts with turn 1's dump, message for message (local, provider-free)
  C6  turn 2 ``cache_read_tokens`` >= 0.8 x turn 1 ``prompt_tokens`` (R4 wording)

Why these: S1-b moved the upload note out of the system prompt so that a turn
carrying an attachment no longer changes the cached prefix (issue 01 §9.20 O4 —
"skipped once, then recovered"). C1-C3 are the fix stated directly; C4-C6 are
the continuation promise it must not break. C5 is the property stated on our side
of the wire, so a provider accounting artefact cannot be mistaken for a defect.

One session, two runs, no tools (both prompts ask for a two-character reply):

  turn 1  long prompt (clears the provider's minimum cacheable prefix) + a real
          attachment staged into the run's ``inputs/`` + the note the API route
          builds for it
  turn 2  the same session, plain follow-up, no attachment

Run into a fresh directory (write-once evidence):

  uv run python .scratch/web-business-context/evidence/20261011-s1-attachment/run_acceptance_s1.py \
      --out .scratch/web-business-context/evidence/20261011-s1-attachment/run-20261011
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
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
TURN2 = "请再确认一次，仍然只回复两个字：收到。不要调用任何工具。"

#: The turn-1 attachment, as a client would send it (name + bytes).
ATTACHMENT_NAME = "brief.md"
ATTACHMENT_BYTES = b"# Brief\nOnly used to make this turn carry an attachment.\n"


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


def upload_note(stored_name: str, inputs_path: str) -> str:
    """The note ``server/routes/runs.py`` builds for a one-file attachment.

    Kept byte-for-byte in step with that route: the point of the arm is that this
    text reaches the model from the *tail*, so it must be the real text.
    """
    return (
        "The user attached 1 input file(s) for this task. "
        f"Read them from these read-only paths:\n  - /inputs/{stored_name}\n"
        f"(native: read directly from {inputs_path})"
    )


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
    """Header + message list of the run's conversation dump, or why it is absent."""
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
        "system_prompt": document.get("system_prompt") or "",
        "raw_messages": messages,
        "trim": document.get("trim"),
        "est_tokens": document.get("messages_est_tokens"),
    }


def _user_texts(messages: list[dict]) -> str:
    return "\n".join(
        str(m.get("content") or "") for m in messages if m.get("role") == "user"
    )


def _first_difference(left: str, right: str) -> dict[str, Any] | None:
    """Where two byte strings first diverge — the §9.15 diagnostic, kept handy."""
    for index, (a, b) in enumerate(zip(left, right, strict=False)):
        if a != b:
            return {"index": index, "left": left[index : index + 60], "right": right[index : index + 60]}
    if len(left) != len(right):
        return {"index": min(len(left), len(right)), "left": "<end>", "right": "<end>"}
    return None


async def run_arm(store: Any, orch: Any, *, out_dir: Path, model: str) -> dict[str, Any]:
    user_id, account_id = await _bound_research_seed(store)
    research_id = await _make_session(
        store, user_id=user_id, account_id=account_id, title="S1 attachment arm"
    )
    record: dict[str, Any] = {
        "label": "attachment-then-plain",
        "research_id": research_id.hex,
        "model": model,
        "runs": [],
    }
    previous_dump: list[dict] | None = None
    note = ""

    for index, prompt in ((1, TURN1), (2, TURN2)):
        run_hex = uuid.uuid4().hex
        run_uuid = uuid.UUID(run_hex)
        run_root = Path(store_run_dir(run_hex))
        addendum = ""
        if index == 1:
            # Stage the attachment for real, then describe it with the route's
            # own wording — the note names this run's inputs dir, which is why it
            # cannot live in the cached prefix.
            inputs_dir = run_root / "inputs"
            inputs_dir.mkdir(parents=True, exist_ok=True)
            (inputs_dir / ATTACHMENT_NAME).write_bytes(ATTACHMENT_BYTES)
            note = upload_note(ATTACHMENT_NAME, str(inputs_dir))
            addendum = note
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
            prompt_addendum=addendum,
            turn_index=index,
            backfill_turn=True,
        )
        row = await _wait_run(store, run_uuid, user_id, timeout=300.0)
        if row is None:
            record["runs"].append({"turn": index, "error": "timeout waiting for terminal status"})
            break

        usage = row.usage_json or {}
        summary_path = run_root / "summary.json"
        summary = (
            json.loads(summary_path.read_text(encoding="utf-8"))
            if summary_path.is_file()
            else {}
        )
        dump = _dump_summary(run_root)
        prefix_ok = None
        if previous_dump is not None and dump.get("exists"):
            current = dump["raw_messages"]
            prefix_ok = current[: len(previous_dump)] == previous_dump
        system_prompt = str(dump.get("system_prompt") or "")
        user_text = _user_texts(dump.get("raw_messages") or [])

        record["runs"].append(
            {
                "turn": index,
                "run_id": run_hex,
                "has_attachment": index == 1,
                "status": row.status,
                "stopped_by": row.stopped_by,
                "prompt_tokens": row.prompt_tokens,
                "cache_read_tokens": row.cache_read_tokens,
                "cache_write_tokens": row.cache_write_tokens,
                "llm_calls": row.llm_calls,
                "usage_status": usage.get("status"),
                "usage_replay": usage.get("replay"),
                "summary_replay": summary.get("replay"),
                "final_answer_head": (row.final_answer or "")[:120],
                "error": row.error,
                "dump": {
                    key: value
                    for key, value in dump.items()
                    if key not in ("raw_messages", "system_prompt")
                },
                "system_prompt_len": len(system_prompt),
                "system_prompt_sha256": hashlib.sha256(
                    system_prompt.encode("utf-8")
                ).hexdigest(),
                "note_in_system_prompt": bool(note) and note in system_prompt,
                "note_in_user_message": bool(note) and note in user_text,
                "prefix_matches_previous_dump": prefix_ok,
                "run_root": str(run_root),
            }
        )
        # Kept for the cross-turn comparison only; never used as a criterion.
        record.setdefault("_system_prompts", []).append(system_prompt)
        previous_dump = dump["raw_messages"] if dump.get("exists") else previous_dump

    # The raw system-prompt texts are only needed for the in-process comparison;
    # the evidence keeps their lengths and digests instead of two 8k-char copies.
    (out_dir / "arm.json").write_text(
        json.dumps(public_view(record), ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return record


def public_view(arm: dict[str, Any]) -> dict[str, Any]:
    """The arm without the in-process system-prompt copies."""
    return {key: value for key, value in arm.items() if key != "_system_prompts"}


def store_run_dir(run_hex: str) -> str:
    from server.config import run_dir_for

    return str(run_dir_for(run_hex))


def verdict_for(arm: dict[str, Any]) -> dict[str, Any]:
    """Judge the registered criteria. Nothing here is chosen after the fact."""
    runs = {int(entry.get("turn") or 0): entry for entry in arm["runs"]}
    first, second = runs.get(1, {}), runs.get(2, {})
    prompts = arm.get("_system_prompts") or []
    turn1_prompt = int(first.get("prompt_tokens") or 0)
    turn2_cache = int(second.get("cache_read_tokens") or 0)
    identical = len(prompts) == 2 and prompts[0] == prompts[1]

    checks = {
        "C1_note_not_in_system_prompt": first.get("note_in_system_prompt") is False,
        "C2_note_in_user_message": first.get("note_in_user_message") is True,
        "C3_system_prompt_identical_across_turns": bool(identical),
        "C4_turn2_replay_used": (second.get("summary_replay") or {}).get("decision") == "used",
        "C5_turn2_prefix_matches_turn1_dump": second.get("prefix_matches_previous_dump") is True,
        "C6_turn2_cache_read_ge_80pct_turn1_prompt": bool(turn1_prompt)
        and turn2_cache >= 0.8 * turn1_prompt,
    }
    detail: dict[str, Any] = {
        "reuse_ratio_turn2": (turn2_cache / turn1_prompt) if turn1_prompt else None,
        "turn1_prompt_tokens": turn1_prompt,
        "turn2_cache_read_tokens": turn2_cache,
        "system_prompt_len": [len(p) for p in prompts],
        "system_prompt_diff": (
            None
            if identical or len(prompts) != 2
            else _first_difference(prompts[0], prompts[1])
        ),
    }
    # S1-a rode along in the same runs: the replay verdict must be on the Run row,
    # not only inside the run directory's summary.json.
    detail["usage_json_carries_replay"] = all(
        isinstance(entry.get("usage_replay"), dict) and entry["usage_replay"].get("decision")
        for entry in arm["runs"]
    )
    return {"checks": checks, "detail": detail, "pass": all(checks.values())}


def write_report(out_dir: Path, arm: dict[str, Any], verdict: dict[str, Any], model: str) -> None:
    lines = [
        "# S1 验收：带附件一轮 + 纯文本一轮（issue 01 §10.7）",
        "",
        f"- 模型：`{model}`；口径：`runs.usage_json`（`server/usage.py`）；同一绑定研究（会话）内两轮。",
        "- 第 1 轮带真实附件（`inputs/brief.md`）并把路由构造的说明文本交给 worker；第 2 轮纯文本。",
        f"- 判定：**{'PASS' if verdict['pass'] else 'FAIL'}**",
        "",
        "| 轮 | 附件 | prompt_tokens | cache_read_tokens | llm_calls | summary.replay | usage_json.replay | dump(messages) | 前缀=上一轮 dump |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for entry in arm["runs"]:
        replay = entry.get("summary_replay") or {}
        usage_replay = entry.get("usage_replay") or {}
        dump = entry.get("dump") or {}
        lines.append(
            f"| {entry.get('turn')} | {entry.get('has_attachment')} | {entry.get('prompt_tokens')} | "
            f"{entry.get('cache_read_tokens')} | {entry.get('llm_calls')} | "
            f"{replay.get('decision')}{': ' + str(replay.get('reason')) if replay.get('reason') else ''} | "
            f"{usage_replay.get('decision')} | {dump.get('messages')} | "
            f"{entry.get('prefix_matches_previous_dump')} |"
        )
    lines += ["", "## 判据", ""]
    for name, ok in verdict["checks"].items():
        lines.append(f"- {'PASS' if ok else 'FAIL'} — `{name}`")
    lines += [
        "",
        "## 判据明细",
        "",
        f"```json\n{json.dumps(verdict['detail'], ensure_ascii=False, indent=2)}\n```",
        "",
    ]
    (out_dir / "report.md").write_text("\n".join(lines), encoding="utf-8")


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", required=True)
    parser.add_argument("--model", default="deepseek-v4-flash-ga-260731")
    args = parser.parse_args()

    out_dir = Path(args.out)
    if out_dir.exists() and any(out_dir.iterdir()):
        raise SystemExit(f"{out_dir} is not empty — write-once evidence, pick a fresh dir")
    out_dir.mkdir(parents=True, exist_ok=True)

    for key in ("OPENAI_API_KEY", "OPENAI_BASE_URL"):
        value = os.environ.get(key) or _dotenv_value(key)
        if not value:
            raise SystemExit(f"{key} missing (env + .env)")
        os.environ[key] = value
    os.environ["OPENAI_MODEL"] = args.model
    os.environ.setdefault("FRONTIER_AGENT_LLM_STICKY_SESSION", "1")

    from server import store
    from server.config import get_config
    from server.orchestrator import Orchestrator

    config = get_config()
    orchestrator = Orchestrator()
    meta = {
        "model_arg": args.model,
        "pipeline_id": config.pipeline_id,
        "sandbox_backend": config.sandbox_backend,
        "runs_root": str(config.runs_root),
    }

    arm = await run_arm(store, orchestrator, out_dir=out_dir, model=args.model)
    verdict = verdict_for(arm)
    payload = {"meta": meta, "arm": public_view(arm), "verdict": verdict}
    (out_dir / "results.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    write_report(out_dir, arm, verdict, args.model)
    print(
        json.dumps(
            {
                "out": str(out_dir),
                "session": arm.get("research_id"),
                "pass": verdict["pass"],
                "checks": verdict["checks"],
                "detail": verdict["detail"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if verdict["pass"] else 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
