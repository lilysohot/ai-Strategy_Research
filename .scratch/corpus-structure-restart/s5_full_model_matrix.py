"""S5 frozen 51-target real-model matrix for the v14 corpus structure restart.

The execution agent receives only the natural-language question.  Gold evidence
is loaded by this parent scorer after the isolated child process exits.  The
minimum protocol runs control once and candidate three times (204 sessions).
The default invocation only freezes or validates assets; model execution
requires the explicit ``--execute`` flag.
"""

from __future__ import annotations

import argparse
import asyncio
import contextlib
import hashlib
import json
import os
import re
import statistics
import subprocess
import sys
import time
from collections import Counter
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from openai import AsyncOpenAI
from psycopg.conninfo import conninfo_to_dict, make_conninfo

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUNS_ROOT = ROOT / ".s5runs_v14_full"
GOLD = ROOT / ".scratch/corpus-access-validation/e2_holdout_targets.json"
PROFILE = OUT / "s5_full_corpus_only.yaml"
MANIFEST = ROOT / "docs/data_clean_dos/v14-s5-full-matrix-manifest.json"
REPORT = ROOT / "docs/data_clean_dos/v14-s5-full-matrix-report.json"
CONTROL_ROOT = Path("/home/administrator/.cache/frontieragent-s5-control-669b7d4a")
CANDIDATE_ROOT = Path("/home/administrator/.cache/frontieragent-s5-candidate-28871184")
VERIFICATION_FILES = {
    "control": ROOT / ".scratch/corpus-structure-restart/v14-control-verification.json",
    "candidate": ROOT / ".scratch/corpus-structure-restart/s4-candidate-verification.json",
}

ARMS = {
    "control": {
        "code_root": CONTROL_ROOT,
        "commit": "669b7d4a8540c38d47cf642dc0de4d879eb28c4f",
        "database": "e6_holdout_corpus",
    },
    "candidate": {
        "code_root": CANDIDATE_ROOT,
        "commit": "288711846b2af754b891120f0d58a7e2f7feab37",
        "database": "v14_s2_quote_corpus",
    },
}
REPEATS_BY_ARM = {"control": 1, "candidate": 3}
PROFILE_TOOL_NAMES = (
    "add_task",
    "update_task",
    "corpus_search",
    "corpus_fetch",
    "corpus_inventory",
)
EFFECTIVE_TOOL_NAMES = (*PROFILE_TOOL_NAMES, "corpus_submit_manifest")
FORBIDDEN_TOOL_NAMES = {
    "data_coverage",
    "web_search",
    "web_fetch",
    "web_download",
}
FORBIDDEN_TOOL_PREFIXES = ("market_", "stock_", "ths_", "investment_")
FROZEN_ENV = {
    "MAIN_MAX_TURNS": "40",
    "RESEARCH_WALL_TIME": "1800",
    "REPORT_WALL_TIME": "600",
    "OPENAI_MAX_INPUT_TOKENS": "2000000",
    "OPENAI_MAX_TOKENS": "100000",
    "SANDBOX_BACKEND": "bwrap",
    "REACT_NO_WEB": "1",
}
_WS = re.compile(r"[\s\u3000\xa0\u200b]+")


def now() -> str:
    return datetime.now(UTC).isoformat()


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def normalize(text: str | None) -> str:
    return _WS.sub("", text or "")


def load_targets() -> dict[str, dict[str, Any]]:
    docs = json.loads(GOLD.read_text(encoding="utf-8"))
    result: dict[str, dict[str, Any]] = {}
    for doc in docs:
        for target in doc.get("targets") or []:
            result[target["target_id"]] = {
                **target,
                "sample_id": doc["sample_id"],
                "domain": doc["domain"],
                "doc_identity": doc["doc_identity"],
            }
    return result


def load_configured_models() -> tuple[dict[str, str], dict[str, str]]:
    """Load answering and judge identities without returning credentials."""
    from frontier_agent.infra.config import get_config

    cfg = get_config()
    answer_key = os.environ.get("OPENAI_API_KEY", "")
    answer_url = os.environ.get("OPENAI_BASE_URL", "")
    answer_model = os.environ.get("OPENAI_MODEL", "") or str(cfg.openai_model)
    judge_key = os.environ.get("JUDGE_API_KEY", "")
    judge_url = os.environ.get("JUDGE_BASE_URL", "")
    judge_model = os.environ.get("JUDGE_MODEL", "")
    if not answer_key or not answer_url or not answer_model:
        raise RuntimeError("configured OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL is incomplete")
    if not judge_key or not judge_url or not judge_model:
        raise RuntimeError("configured JUDGE_API_KEY/JUDGE_BASE_URL/JUDGE_MODEL is incomplete")
    if (answer_url.rstrip("/"), answer_model) == (judge_url.rstrip("/"), judge_model):
        raise RuntimeError("judge must use a different endpoint or model identity")

    def identity(model: str, base_url: str) -> dict[str, str]:
        return {
            "model": model,
            "endpoint_host": re.sub(r"^https?://", "", base_url).split("/")[0],
        }

    return identity(answer_model, answer_url), identity(judge_model, judge_url)


def git_output(*args: str, cwd: Path = ROOT) -> str:
    return subprocess.check_output(["git", *args], cwd=cwd, text=True).strip()


def arm_dsn(database: str) -> str:
    return make_conninfo(
        **{**conninfo_to_dict(os.environ["CORPUS_DSN"]), "dbname": database}
    )


def verify_arm_database(database: str) -> dict[str, Any]:
    with (
        psycopg.connect(
            arm_dsn(database), options="-c default_transaction_read_only=on"
        ) as conn,
        conn.cursor() as cur,
    ):
        cur.execute("SELECT current_database()")
        current_row = cur.fetchone()
        cur.execute(
            "SELECT count(*) FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL"
        )
        active_row = cur.fetchone()
    if current_row is None or active_row is None:
        raise RuntimeError(f"database preflight returned no row for {database}")
    current = current_row[0]
    active = int(active_row[0])
    if current != database or active != 12:
        raise RuntimeError(f"database preflight failed: current={current}, active={active}")
    return {"current_database": current, "active_publications": active}


def build_schedule(target_ids: Sequence[str]) -> list[dict[str, Any]]:
    """Return the frozen 204-session minimum-protocol order."""
    schedule: list[dict[str, Any]] = []
    for index, target_id in enumerate(target_ids):
        order = ("control", "candidate") if index % 2 == 0 else ("candidate", "control")
        schedule.extend(
            {"arm": arm_name, "target_id": target_id, "repeat": 1}
            for arm_name in order
        )
    for repeat in (2, 3):
        ordered_targets = list(target_ids) if repeat == 2 else list(reversed(target_ids))
        schedule.extend(
            {"arm": "candidate", "target_id": target_id, "repeat": repeat}
            for target_id in ordered_targets
        )
    return schedule


def verify_tool_profile(code_root: Path) -> dict[str, Any]:
    """Resolve the shared external profile through one arm's actual loader."""
    env = {**os.environ, **FROZEN_ENV}
    env["PYTHONPATH"] = str(code_root)
    env["S5_PROFILE_STEM"] = str(PROFILE.with_suffix(""))
    script = (
        "import json,os; "
        "from frontier_agent.core.runtime.resources.manager import ResourceManager; "
        "from plugins.tools import get_builtin_tools; "
        "from workflows.stateful_react_agent.nodes.main_agent import _tools_for_stateful_react; "
        "from workflows.stateful_react_agent.profile import load_react_profile; "
        "p=load_react_profile(os.environ['S5_PROFILE_STEM']); "
        "a=p.get('agent') or {}; "
        "rm=ResourceManager(None,dict(get_builtin_tools())); "
        "effective=[t.name for t in _tools_for_stateful_react(rm,a)]; "
        "print(json.dumps({'profile_tools':a.get('agent_tools') or [],"
        "'effective_tools':effective}))"
    )
    output = subprocess.check_output(
        [sys.executable, "-c", script],
        cwd=code_root,
        env=env,
        text=True,
    ).strip()
    loaded = json.loads(output.splitlines()[-1])
    if loaded.get("profile_tools") != list(PROFILE_TOOL_NAMES):
        raise RuntimeError(
            f"tool profile mismatch for {code_root}: loaded={loaded}, "
            f"expected={list(PROFILE_TOOL_NAMES)}"
        )
    if loaded.get("effective_tools") != list(EFFECTIVE_TOOL_NAMES):
        raise RuntimeError(
            f"effective tool mismatch for {code_root}: loaded={loaded}, "
            f"expected={list(EFFECTIVE_TOOL_NAMES)}"
        )
    return loaded


def write_manifest(
    answer_model: dict[str, str],
    judge_model: dict[str, str],
    target_ids: Sequence[str],
    profile_checks: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    if MANIFEST.exists():
        raise RuntimeError(f"refusing to overwrite frozen manifest: {MANIFEST}")
    assets = [
        GOLD,
        Path(__file__),
        PROFILE,
        ROOT / "docs/data_clean_dos/v14-s4-ab-report.json",
        ROOT / "docs/data_clean_dos/v14-s5-real-model-ab-report.json",
        ROOT / ".scratch/corpus-access-validation/e4_scorer.py",
        ROOT / ".scratch/corpus-structure-restart/v14-control-verification.json",
        ROOT / ".scratch/corpus-structure-restart/s4-candidate-verification.json",
        ROOT / "plugins/corpus/preparation/search_pg.py",
        ROOT / "plugins/tools/corpus_fetch.py",
        ROOT / "plugins/corpus/research_discipline.py",
    ]
    schedule = build_schedule(target_ids)
    schedule_sha = hashlib.sha256(
        json.dumps(schedule, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    dirty = [
        line for line in git_output("status", "--porcelain").splitlines()
        if line and ".codebuddy/memory/MEMORY.md" not in line
    ]
    manifest: dict[str, Any] = {
        "schema": "corpus-v14-s5-full-matrix-v1",
        "frozen_at": now(),
        "status": "frozen_before_execution_awaiting_explicit_launch",
        "arms": {
            name: {"commit": arm["commit"], "database": arm["database"]}
            for name, arm in ARMS.items()
        },
        "execution": {
            "workflow": "react/stateful-react-agent",
            "workflow_profile": str(PROFILE.relative_to(ROOT)),
            "one_question_per_process": True,
            "gold_hidden_from_agent": True,
            "concurrency": 1,
            "protocol": "minimum-204",
            "repeats_by_arm": REPEATS_BY_ARM,
            "questions": len(target_ids),
            "expected_sessions": len(schedule),
            "target_ids": list(target_ids),
            "budgets": FROZEN_ENV,
            "schedule": {
                "sha256": schedule_sha,
                "rule": (
                    "repeat 1 counterbalances control/candidate by target index; "
                    "candidate repeat 2 is forward and repeat 3 reverse target order"
                ),
            },
        },
        "answer_model": answer_model,
        "judge": {
            **judge_model,
            "credential_source": "configured JUDGE_*",
            "different_model_identity": judge_model["model"] != answer_model["model"],
            "different_endpoint_host": (
                judge_model["endpoint_host"] != answer_model["endpoint_host"]
            ),
            "independence": (
                "different-model judge on a different endpoint"
                if judge_model["endpoint_host"] != answer_model["endpoint_host"]
                else "different-model judge on the same configured endpoint/provider"
            ),
        },
        "tools": {
            "policy": "hard profile allowlist plus automatic manifest companion",
            "profile_allowlist": list(PROFILE_TOOL_NAMES),
            "effective_expected": list(EFFECTIVE_TOOL_NAMES),
            "closed_categories": [
                "web/search/download",
                "market/同花顺",
                "shell/filesystem/repository search",
                "investment calculation",
                "semantic structured store",
                "transcript recovery",
            ],
            "profile_resolution_preflight": profile_checks,
        },
        "assets": {str(path.relative_to(ROOT)): sha256(path) for path in assets},
        "non_user_dirty_paths_at_freeze": dirty,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def validate_manifest(
    manifest: dict[str, Any],
    *,
    answer_model: dict[str, str],
    judge_model: dict[str, str],
    target_ids: Sequence[str],
    profile_checks: dict[str, dict[str, Any]],
) -> None:
    """Fail closed if any frozen execution input drifted after freezing."""
    if manifest.get("schema") != "corpus-v14-s5-full-matrix-v1":
        raise RuntimeError("unexpected full-matrix manifest schema")
    execution = manifest.get("execution") or {}
    if execution.get("protocol") != "minimum-204":
        raise RuntimeError("manifest protocol is not minimum-204")
    if execution.get("repeats_by_arm") != REPEATS_BY_ARM:
        raise RuntimeError("manifest repeats_by_arm drifted")
    if execution.get("target_ids") != list(target_ids):
        raise RuntimeError("manifest target ordering drifted")
    schedule = build_schedule(target_ids)
    schedule_sha = hashlib.sha256(
        json.dumps(schedule, ensure_ascii=False, separators=(",", ":")).encode()
    ).hexdigest()
    if (execution.get("schedule") or {}).get("sha256") != schedule_sha:
        raise RuntimeError("manifest schedule hash drifted")
    if execution.get("expected_sessions") != len(schedule) or len(schedule) != 204:
        raise RuntimeError("full-matrix schedule must contain exactly 204 sessions")
    if manifest.get("answer_model") != answer_model:
        raise RuntimeError("answer model identity drifted after freeze")
    frozen_judge = manifest.get("judge") or {}
    for key, value in judge_model.items():
        if frozen_judge.get(key) != value:
            raise RuntimeError(f"judge identity field drifted: {key}")
    tools = manifest.get("tools") or {}
    if tools.get("profile_allowlist") != list(PROFILE_TOOL_NAMES):
        raise RuntimeError("frozen tool profile allowlist drifted")
    if tools.get("effective_expected") != list(EFFECTIVE_TOOL_NAMES):
        raise RuntimeError("frozen effective tool list drifted")
    if tools.get("profile_resolution_preflight") != profile_checks:
        raise RuntimeError("tool profile resolution drifted after freeze")
    for relative, expected in (manifest.get("assets") or {}).items():
        path = ROOT / str(relative)
        if not path.exists() or sha256(path) != expected:
            raise RuntimeError(f"frozen asset drifted: {relative}")


def latest_run_dir(work_dir: Path) -> Path | None:
    root = work_dir / ".apodex" / "runs"
    if not root.exists():
        return None
    candidates = [path for path in root.iterdir() if path.is_dir()]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


def protocol_violations(work_dir: Path, parsed: dict[str, Any]) -> list[str]:
    """Return evidence that a supposedly corpus-only run crossed a closed boundary."""
    violations: list[str] = []
    tool_counts = ((parsed.get("trace") or {}).get("tool_calls_by_name") or {})
    for name, count in sorted(tool_counts.items()):
        if name in FORBIDDEN_TOOL_NAMES or name.startswith(FORBIDDEN_TOOL_PREFIXES):
            violations.append(f"forbidden tool call: {name} x{count}")
    for path in sorted((work_dir / ".apodex").glob("**/market_trace.jsonl")):
        if path.exists() and path.stat().st_size:
            violations.append(
                f"non-empty market trace: {path.relative_to(work_dir)} ({path.stat().st_size} bytes)"
            )
    return violations


def flatten_strings(value: object) -> list[str]:
    if isinstance(value, str):
        return [value]
    if isinstance(value, dict):
        return [item for child in value.values() for item in flatten_strings(child)]
    if isinstance(value, (list, tuple)):
        return [item for child in value for item in flatten_strings(child)]
    if value is None or isinstance(value, bool):
        return []
    return [str(value)]


def parse_run(run_dir: Path | None, target: dict[str, Any]) -> dict[str, Any]:
    if run_dir is None:
        return {"run_present": False}
    trace_path = run_dir / "trace.jsonl"
    ledger_path = run_dir / "corpus" / "ledger.json"
    session_path = run_dir / "session.json"
    events: list[dict[str, Any]] = []
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            try:
                value = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(value, dict):
                events.append(value)
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    session = json.loads(session_path.read_text(encoding="utf-8")) if session_path.exists() else {}

    answer = ""
    for message in reversed(session.get("history") or []):
        if message.get("role") == "assistant" and message.get("content"):
            answer = str(message["content"])
            break
    if not answer:
        texts = [str(e.get("text")) for e in events if e.get("t") == "llm" and e.get("text")]
        answer = texts[-1] if texts else ""

    tool_counts: Counter[str] = Counter()
    corpus_parts: list[str] = []
    locator_text: dict[str, str] = {}
    tool_errors = 0
    for event in events:
        if event.get("t") != "tool":
            continue
        name = str(event.get("name") or "")
        tool_counts[name] += 1
        tool_errors += int(bool(event.get("is_error")))
        if not name.startswith("corpus_"):
            continue
        payload: object = event.get("result")
        if isinstance(payload, str):
            with contextlib.suppress(json.JSONDecodeError):
                payload = json.loads(payload)
        corpus_parts.extend(flatten_strings(payload))
        if isinstance(payload, dict):
            items = list(payload.get("items") or [])
            if payload.get("locator") and payload.get("text"):
                items.append(payload)
            for item in items:
                if isinstance(item, dict) and item.get("locator") and isinstance(item.get("text"), str):
                    locator_text[str(item["locator"])] = item["text"]

    delivered_status = {
        str(item.get("locator")): item.get("status")
        for item in ledger.get("delivered") or [] if isinstance(item, dict)
    }
    delivered_blob = "\n".join(
        text for locator, text in locator_text.items() if delivered_status.get(locator) == "delivered"
    )
    quote = normalize(str(target.get("verbatim_quote") or ""))
    corpus_blob = normalize("\n".join(corpus_parts))
    doc_prefix = str(target["doc_identity"])[:16]
    offered_blob = normalize(json.dumps(ledger.get("offered") or [], ensure_ascii=False))
    usage = session.get("usage") or {}
    return {
        "run_present": True,
        "run_dir": str(run_dir.relative_to(ROOT)) if run_dir.is_relative_to(ROOT) else str(run_dir),
        "answer": answer,
        "trace": {
            "llm_turns": sum(1 for e in events if e.get("t") == "llm"),
            "tool_calls": sum(tool_counts.values()),
            "tool_calls_by_name": dict(tool_counts),
            "tool_errors": tool_errors,
        },
        "usage": {
            "input": usage.get("input"),
            "output": usage.get("output"),
            "cached": usage.get("cached"),
            "compactions": usage.get("compactions"),
        },
        "ledger": {
            "present": ledger_path.exists(),
            "offered": len(ledger.get("offered") or []),
            "requested": len(ledger.get("requested") or []),
            "fetched": len(ledger.get("fetched") or []),
            "delivered": len(ledger.get("delivered") or []),
            "errors": ledger.get("errors") or [],
        },
        "deterministic": {
            "source_offered": doc_prefix in offered_blob,
            "quote_fetched": bool(quote and quote in corpus_blob),
            "quote_delivered": bool(quote and quote in normalize(delivered_blob)),
        },
    }


def run_one(arm_name: str, target: dict[str, Any], repeat: int, timeout_s: int) -> dict[str, Any]:
    result_path = RUNS_ROOT / arm_name / target["target_id"] / f"run-{repeat:02d}" / "result.json"
    if result_path.exists():
        return json.loads(result_path.read_text(encoding="utf-8"))
    work_dir = result_path.parent / "workspace"
    work_dir.mkdir(parents=True, exist_ok=True)
    arm = ARMS[arm_name]
    env = {**os.environ, **FROZEN_ENV}
    env["CORPUS_TARGET_DB"] = str(arm["database"])
    env["CORPUS_DSN"] = arm_dsn(str(arm["database"]))
    env["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=120000"
    env["REACT_WORKFLOW_PROFILE"] = str(PROFILE.with_suffix(""))
    env["REACT_NO_WEB"] = "1"
    old_pythonpath = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = str(arm["code_root"]) + (os.pathsep + old_pythonpath if old_pythonpath else "")
    cmd = [
        sys.executable,
        "-m",
        "apodex.cli",
        "--mode",
        "react",
        "-p",
        str(target["question"]),
        "--cwd",
        str(work_dir),
        "--no-tui",
        "--yes",
    ]
    started = time.monotonic()
    try:
        process = subprocess.run(
            cmd,
            cwd=str(work_dir),
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout_s,
        )
        status = "ok" if process.returncode == 0 else f"exit:{process.returncode}"
        stdout = process.stdout or ""
        stderr = process.stderr or ""
    except subprocess.TimeoutExpired as exc:
        status = "timeout"
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
    (result_path.parent / "process-tail.txt").write_text(
        stdout[-5000:] + "\n--- stderr ---\n" + stderr[-3000:], encoding="utf-8"
    )
    parsed = parse_run(latest_run_dir(work_dir), target)
    violations = protocol_violations(work_dir, parsed)
    if violations:
        status = "protocol_violation"
    result = {
        "artifact": "v14-s5-full-matrix-run",
        "generated_at": now(),
        "arm": arm_name,
        "repeat": repeat,
        "target_id": target["target_id"],
        "sample_id": target["sample_id"],
        "domain": target["domain"],
        "role": target["evidence_role"],
        "question": target["question"],
        "status": status,
        "protocol_violations": violations,
        "wall_s": round(time.monotonic() - started, 1),
        **parsed,
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def parse_json_object(text: str) -> dict[str, Any]:
    stripped = text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    try:
        value = json.loads(stripped)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", stripped, re.DOTALL)
        value = json.loads(match.group(0)) if match else {}
    return value if isinstance(value, dict) else {}


async def judge_one(result: dict[str, Any], target: dict[str, Any]) -> dict[str, Any]:
    if result.get("status") != "ok" or not result.get("answer"):
        return {"verdict": "not_attempted", "score": 0.0, "reason": "run did not produce an answer"}
    prompt = f"""你是语料问答验收评分器。只根据参考证据判断回答，不补充外部知识。
输出严格 JSON：{{"verdict":"pass|fail","score":0到1,"supported":true或false,"complete":true或false,"reason":"一句话"}}。
通过要求：回答中的核心事实受到参考证据支持，并满足问题要求；允许释义、数字格式差异和只引用可接受证据声明允许的核心数字。若编造、答错主体/期间/单位或漏掉问题要求的关键项，判失败。

问题：{target['question']}
参考证据：{target['verbatim_quote']}
可接受证据规则：{target.get('acceptable_evidence') or ''}
模型回答：{result['answer']}
"""
    last_error = "empty response"
    async with AsyncOpenAI(
        api_key=os.environ["JUDGE_API_KEY"],
        base_url=os.environ["JUDGE_BASE_URL"].rstrip("/").removesuffix("/chat/completions"),
    ) as client:
        for _attempt in range(2):
            try:
                response = await client.chat.completions.create(
                    model=os.environ["JUDGE_MODEL"],
                    messages=[{"role": "user", "content": prompt}],
                    max_completion_tokens=1000,
                    temperature=0,
                    response_format={"type": "json_object"},
                    extra_body={"thinking": {"type": "disabled"}},
                )
                raw = (response.choices[0].message.content or "").strip()
                judged = parse_json_object(raw)
                if judged.get("verdict") in {"pass", "fail"}:
                    usage = response.usage
                    return {
                        **judged,
                        "raw": raw,
                        "model": os.environ["JUDGE_MODEL"],
                        "usage": {
                            "input": usage.prompt_tokens if usage else None,
                            "output": usage.completion_tokens if usage else None,
                            "total": usage.total_tokens if usage else None,
                        },
                    }
                last_error = "judge returned no parseable verdict"
            except Exception as exc:
                last_error = f"{type(exc).__name__}: {exc}"
            await asyncio.sleep(1)
    return {"verdict": "judge_error", "score": 0.0, "reason": last_error}


async def verify_judge_access() -> None:
    """Fail before the first answer session when Judge auth/model routing is unusable."""
    async with AsyncOpenAI(
        api_key=os.environ["JUDGE_API_KEY"],
        base_url=os.environ["JUDGE_BASE_URL"].rstrip("/").removesuffix("/chat/completions"),
    ) as client:
        response = await client.chat.completions.create(
            model=os.environ["JUDGE_MODEL"],
            messages=[{"role": "user", "content": "只输出 json：键 ok 的值为 true"}],
            max_completion_tokens=128,
            temperature=0,
            response_format={"type": "json_object"},
            extra_body={"thinking": {"type": "disabled"}},
        )
    if not response.choices or not (response.choices[0].message.content or "").strip():
        raise RuntimeError("Judge preflight returned an empty response")


def aggregate(results: list[dict[str, Any]]) -> dict[str, Any]:
    arms: dict[str, Any] = {}
    for arm_name in ARMS:
        rows = [row for row in results if row["arm"] == arm_name]
        tool_names = sorted(
            {
                name
                for row in rows
                for name in ((row.get("trace") or {}).get("tool_calls_by_name") or {})
            }
        )
        arms[arm_name] = {
            "runs": len(rows),
            "ok": sum(row.get("status") == "ok" for row in rows),
            "judge_pass": sum((row.get("judge") or {}).get("verdict") == "pass" for row in rows),
            "source_offered": sum(bool((row.get("deterministic") or {}).get("source_offered")) for row in rows),
            "quote_fetched": sum(bool((row.get("deterministic") or {}).get("quote_fetched")) for row in rows),
            "quote_delivered": sum(bool((row.get("deterministic") or {}).get("quote_delivered")) for row in rows),
            "wall_s": round(sum(float(row.get("wall_s") or 0) for row in rows), 1),
            "tool_calls": sum(int((row.get("trace") or {}).get("tool_calls") or 0) for row in rows),
            "tool_errors": sum(int((row.get("trace") or {}).get("tool_errors") or 0) for row in rows),
            "tool_calls_by_name": {
                name: sum(
                    int((((row.get("trace") or {}).get("tool_calls_by_name") or {}).get(name)) or 0)
                    for row in rows
                )
                for name in tool_names
            },
            "tokens": {
                key: sum(int((row.get("usage") or {}).get(key) or 0) for row in rows)
                for key in ("input", "output", "cached")
            },
            "judge_tokens": {
                "recorded_runs": sum(bool((row.get("judge") or {}).get("usage")) for row in rows),
                "input": sum(
                    int((((row.get("judge") or {}).get("usage") or {}).get("input")) or 0)
                    for row in rows
                ),
                "output": sum(
                    int((((row.get("judge") or {}).get("usage") or {}).get("output")) or 0)
                    for row in rows
                ),
            },
        }
    return arms


def variance_summary(results: list[dict[str, Any]]) -> dict[str, Any]:
    summary: dict[str, Any] = {}
    for target_id in sorted({str(row["target_id"]) for row in results}):
        summary[target_id] = {}
        for arm_name in ARMS:
            rows = [
                row for row in results
                if row["target_id"] == target_id and row["arm"] == arm_name
            ]
            walls = [float(row.get("wall_s") or 0) for row in rows]
            inputs = [float((row.get("usage") or {}).get("input") or 0) for row in rows]
            tools = [float((row.get("trace") or {}).get("tool_calls") or 0) for row in rows]
            searches = [
                float(
                    (((row.get("trace") or {}).get("tool_calls_by_name") or {}).get("corpus_search"))
                    or 0
                )
                for row in rows
            ]
            fetches = [
                float(
                    (((row.get("trace") or {}).get("tool_calls_by_name") or {}).get("corpus_fetch"))
                    or 0
                )
                for row in rows
            ]
            errors = [float((row.get("trace") or {}).get("tool_errors") or 0) for row in rows]

            def stats(values: list[float]) -> dict[str, float]:
                avg = statistics.mean(values) if values else 0.0
                stdev = statistics.pstdev(values) if len(values) > 1 else 0.0
                return {
                    "mean": round(avg, 1),
                    "min": round(min(values), 1) if values else 0.0,
                    "max": round(max(values), 1) if values else 0.0,
                    "pstdev": round(stdev, 1),
                    "cv": round(stdev / avg, 3) if avg else 0.0,
                }

            summary[target_id][arm_name] = {
                "runs": len(rows),
                "judge_pass": sum((row.get("judge") or {}).get("verdict") == "pass" for row in rows),
                "source_offered": sum(
                    bool((row.get("deterministic") or {}).get("source_offered")) for row in rows
                ),
                "quote_fetched": sum(
                    bool((row.get("deterministic") or {}).get("quote_fetched")) for row in rows
                ),
                "quote_delivered": sum(
                    bool((row.get("deterministic") or {}).get("quote_delivered")) for row in rows
                ),
                "wall_s": stats(walls),
                "input_tokens": stats(inputs),
                "tool_calls": stats(tools),
                "corpus_search_calls": stats(searches),
                "corpus_fetch_calls": stats(fetches),
                "tool_errors": stats(errors),
            }
    return summary


def expected_build_id(arm_name: str, sample_id: str) -> str:
    data = json.loads(VERIFICATION_FILES[arm_name].read_text(encoding="utf-8"))
    for publication in data.get("publications") or []:
        if publication.get("sample_id") == sample_id:
            return str(publication["expected_build_id"])
    raise KeyError(f"no expected build for {arm_name}/{sample_id}")


def refresh_source_offered(result: dict[str, Any]) -> None:
    run_dir_value = result.get("run_dir")
    if not run_dir_value:
        return
    run_dir = Path(str(run_dir_value))
    if not run_dir.is_absolute():
        run_dir = ROOT / run_dir
    ledger_path = run_dir / "corpus" / "ledger.json"
    if not ledger_path.exists():
        return
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    expected = expected_build_id(str(result["arm"]), str(result["sample_id"]))
    offered = any(
        isinstance(item, dict) and item.get("build_id") == expected
        for item in ledger.get("offered") or []
    )
    result.setdefault("deterministic", {})["source_offered"] = offered
    result["deterministic"]["expected_build_id"] = expected


def excluded_preflight_attempts() -> list[dict[str, Any]]:
    path = (
        OUT / "s5-invalid-preflight/db-target-mismatch-r1/control/"
        "f86c6d2c-cxotable/run-01/result.json"
    )
    if not path.exists():
        return []
    row = json.loads(path.read_text(encoding="utf-8"))
    return [
        {
            "reason": "CORPUS_TARGET_DB was set but CORPUS_DSN still connected to postgres",
            "disposition": "excluded before formal A/B; preserved as harness preflight failure",
            "arm": row.get("arm"),
            "target_id": row.get("target_id"),
            "status": row.get("status"),
            "wall_s": row.get("wall_s"),
            "usage": row.get("usage"),
            "tool_calls": (row.get("trace") or {}).get("tool_calls"),
        }
    ]


def write_report(results: list[dict[str, Any]], manifest: dict[str, Any]) -> None:
    summary = aggregate(results)
    control = summary.get("control") or {}
    candidate = summary.get("candidate") or {}
    expected_sessions = int((manifest.get("execution") or {}).get("expected_sessions") or 204)
    unique_runs = {
        (str(row.get("arm")), str(row.get("target_id")), int(row.get("repeat") or 0))
        for row in results
    }
    complete = len(results) == expected_sessions and len(unique_runs) == expected_sessions

    def mean_metric(arm: dict[str, Any], metric: str) -> float:
        runs = int(arm.get("runs") or 0)
        return float(arm.get(metric) or 0) / runs if runs else 0.0

    def mean_delta_percent(metric: str) -> float | None:
        before = mean_metric(control, metric)
        after = mean_metric(candidate, metric)
        return round((after - before) / before * 100, 1) if before else None

    control_tokens = control.get("tokens") or {}
    candidate_tokens = candidate.get("tokens") or {}
    control_tool_names = control.get("tool_calls_by_name") or {}
    candidate_tool_names = candidate.get("tool_calls_by_name") or {}

    def mean_token_delta_percent(metric: str) -> float | None:
        before_runs = int(control.get("runs") or 0)
        after_runs = int(candidate.get("runs") or 0)
        before = float(control_tokens.get(metric) or 0) / before_runs if before_runs else 0.0
        after = float(candidate_tokens.get(metric) or 0) / after_runs if after_runs else 0.0
        return round((after - before) / before * 100, 1) if before else None

    def mean_named_tool_delta_percent(name: str) -> float | None:
        before_runs = int(control.get("runs") or 0)
        after_runs = int(candidate.get("runs") or 0)
        before = float(control_tool_names.get(name) or 0) / before_runs if before_runs else 0.0
        after = float(candidate_tool_names.get(name) or 0) / after_runs if after_runs else 0.0
        return round((after - before) / before * 100, 1) if before else None

    def rate(arm: dict[str, Any], metric: str) -> float:
        runs = int(arm.get("runs") or 0)
        return float(arm.get(metric) or 0) / runs if runs else 0.0

    def by_role(arm_name: str) -> dict[str, Any]:
        arm_rows = [row for row in results if row.get("arm") == arm_name]
        return {
            role: {
                "runs": len(role_rows),
                "judge_pass": sum(
                    (row.get("judge") or {}).get("verdict") == "pass" for row in role_rows
                ),
                "source_offered": sum(
                    bool((row.get("deterministic") or {}).get("source_offered"))
                    for row in role_rows
                ),
                "quote_fetched": sum(
                    bool((row.get("deterministic") or {}).get("quote_fetched"))
                    for row in role_rows
                ),
                "quote_delivered": sum(
                    bool((row.get("deterministic") or {}).get("quote_delivered"))
                    for row in role_rows
                ),
            }
            for role in sorted({str(row.get("role")) for row in arm_rows})
            if (role_rows := [row for row in arm_rows if str(row.get("role")) == role])
        }

    candidate_runs = int(candidate.get("runs") or 0)
    candidate_pass = complete and candidate_runs == 153 and all(
        int(candidate.get(metric) or 0) == candidate_runs
        for metric in ("judge_pass", "source_offered", "quote_fetched", "quote_delivered")
    )

    report = {
        "artifact": "v14-s5-full-model-matrix",
        "generated_at": now(),
        "status": "full_matrix_complete" if complete else "full_matrix_partial",
        "manifest_sha256": sha256(MANIFEST),
        "judge_independence": manifest["judge"]["independence"],
        "scope": {
            "questions": len({row["target_id"] for row in results}),
            "runs": len(results),
            "expected_runs": expected_sessions,
            "repeats_by_arm": REPEATS_BY_ARM,
        },
        "summary": summary,
        "summary_by_evidence_role": {arm: by_role(arm) for arm in ARMS},
        "comparison": {
            "basis": "per-run means because the minimum protocol has asymmetric repeats",
            "judge_pass_rate_delta_percentage_points": round(
                (rate(candidate, "judge_pass") - rate(control, "judge_pass")) * 100, 1
            ),
            "source_offered_rate_delta_percentage_points": round(
                (rate(candidate, "source_offered") - rate(control, "source_offered")) * 100,
                1,
            ),
            "quote_fetched_rate_delta_percentage_points": round(
                (rate(candidate, "quote_fetched") - rate(control, "quote_fetched")) * 100,
                1,
            ),
            "quote_delivered_rate_delta_percentage_points": round(
                (rate(candidate, "quote_delivered") - rate(control, "quote_delivered")) * 100,
                1,
            ),
            "mean_wall_s_delta_percent": mean_delta_percent("wall_s"),
            "mean_tool_calls_delta_percent": mean_delta_percent("tool_calls"),
            "mean_corpus_search_calls_delta_percent": mean_named_tool_delta_percent(
                "corpus_search"
            ),
            "mean_corpus_fetch_calls_delta_percent": mean_named_tool_delta_percent(
                "corpus_fetch"
            ),
            "mean_input_tokens_delta_percent": mean_token_delta_percent("input"),
            "mean_output_tokens_delta_percent": mean_token_delta_percent("output"),
            "mean_cached_tokens_delta_percent": mean_token_delta_percent("cached"),
        },
        "variance": variance_summary(results),
        "decision": {
            "status": (
                "full_matrix_quality_passed_pending_release_review"
                if candidate_pass
                else "full_matrix_quality_failed"
                if complete
                else "execution_incomplete"
            ),
            "release_ready": False,
            "reasons": [
                f"Control judged-answer pass: {control.get('judge_pass', 0)}/{control.get('runs', 0)}; "
                f"candidate: {candidate.get('judge_pass', 0)}/{candidate.get('runs', 0)}.",
                f"Completed {len(results)}/{expected_sessions} frozen sessions.",
                f"Judge relation: {manifest['judge']['independence']}.",
            ],
            "next_gate": (
                "perform release review, version-binding verification, and rollback rehearsal"
                if candidate_pass
                else "classify every full-matrix failure without changing the frozen holdout"
                if complete
                else "resume the frozen schedule without rerunning completed sessions"
            ),
        },
        "limitations": [
            "The minimum protocol gives control one run per target and candidate three; control run-to-run variance is not estimated in this full matrix.",
            "The judge has a different model identity but shares the configured endpoint/provider with the answering model. Provider-level independence is not established.",
        ],
        "postprocess_runner_sha256": sha256(Path(__file__)),
        "per_run": results,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def rescore_existing(targets: dict[str, dict[str, Any]]) -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results = []
    for path in sorted(RUNS_ROOT.glob("*/*/run-*/result.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        target_id = str(result["target_id"])
        result["judge"] = asyncio.run(judge_one(result, targets[target_id]))
        if (result.get("judge") or {}).get("verdict") == "judge_error":
            path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            raise RuntimeError(f"Judge failed while rescoring {path}: {result['judge']['reason']}")
        refresh_source_offered(result)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
    write_report(results, manifest)
    print(json.dumps(aggregate(results), ensure_ascii=False, indent=2), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--freeze-only", action="store_true")
    mode.add_argument("--execute", action="store_true")
    mode.add_argument("--rescore-only", action="store_true")
    parser.add_argument("--timeout", type=int, default=1800)
    args = parser.parse_args()
    answer_model, judge_model = load_configured_models()
    targets = load_targets()
    target_ids = list(targets)
    if len(target_ids) != 51:
        raise SystemExit(f"expected 51 frozen targets, found {len(target_ids)}")
    profile_checks: dict[str, dict[str, Any]] = {}
    for name, arm in ARMS.items():
        actual = git_output("rev-parse", "HEAD", cwd=Path(arm["code_root"]))
        if actual != arm["commit"]:
            raise SystemExit(f"{name} code root is {actual}, expected {arm['commit']}")
        db_check = verify_arm_database(str(arm["database"]))
        print(f"[preflight] {name} database={db_check}", flush=True)
        profile_checks[name] = verify_tool_profile(Path(arm["code_root"]))
        print(f"[preflight] {name} tools={profile_checks[name]}", flush=True)

    if args.freeze_only:
        manifest = write_manifest(answer_model, judge_model, target_ids, profile_checks)
        print(
            f"[freeze] {MANIFEST} "
            f"({len(target_ids)} questions, {len(build_schedule(target_ids))} sessions; no model run)",
            flush=True,
        )
        print(json.dumps(manifest["tools"], ensure_ascii=False, indent=2), flush=True)
        return 0

    if not MANIFEST.exists():
        raise SystemExit(f"frozen manifest does not exist: {MANIFEST}")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    validate_manifest(
        manifest,
        answer_model=answer_model,
        judge_model=judge_model,
        target_ids=target_ids,
        profile_checks=profile_checks,
    )
    print(f"[freeze-check] validated {MANIFEST}", flush=True)
    asyncio.run(verify_judge_access())
    print("[preflight] Judge authentication and model routing succeeded", flush=True)
    if args.rescore_only:
        return rescore_existing(targets)

    results: list[dict[str, Any]] = []
    schedule = build_schedule(target_ids)
    for position, item in enumerate(schedule, start=1):
        repeat = int(item["repeat"])
        target_id = str(item["target_id"])
        arm_name = str(item["arm"])
        print(
            f"[run {position}/{len(schedule)}] r{repeat} {target_id} {arm_name}",
            flush=True,
        )
        result_path = RUNS_ROOT / arm_name / target_id / f"run-{repeat:02d}" / "result.json"
        existed = result_path.exists()
        result = run_one(arm_name, targets[target_id], repeat, args.timeout)
        if result.get("status") == "protocol_violation":
            raise RuntimeError(
                "closed-tool protocol violation; matrix halted: "
                + "; ".join(result.get("protocol_violations") or [])
            )
        if not existed or (result.get("judge") or {}).get("verdict") not in {"pass", "fail"}:
            result["judge"] = asyncio.run(judge_one(result, targets[target_id]))
        if (result.get("judge") or {}).get("verdict") == "judge_error":
            result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
            raise RuntimeError(
                f"Judge failed for {arm_name}/{target_id}/run-{repeat:02d}: "
                f"{result['judge']['reason']}"
            )
        refresh_source_offered(result)
        result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
        write_report(results, manifest)
        print(
            f"[done] {result['status']} judge={result['judge'].get('verdict')} "
            f"offered={(result.get('deterministic') or {}).get('source_offered')} "
            f"fetched={(result.get('deterministic') or {}).get('quote_fetched')} "
            f"wall={result.get('wall_s')}s",
            flush=True,
        )

    write_report(results, manifest)
    print(json.dumps(aggregate(results), ensure_ascii=False, indent=2), flush=True)
    print(f"[report] {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
