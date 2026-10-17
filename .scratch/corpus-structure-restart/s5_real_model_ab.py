"""S5 frozen real-model A/B for the v14 corpus structure restart.

The execution agent receives only the natural-language question.  Gold evidence
is loaded by this parent scorer after the isolated child process exits.
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
RUNS_ROOT = ROOT / ".s5runs_v14"
GOLD = ROOT / ".scratch/corpus-access-validation/e2_holdout_targets.json"
MANIFEST_R1 = ROOT / "docs/data_clean_dos/v14-s5-real-model-manifest.json"
MANIFEST = ROOT / "docs/data_clean_dos/v14-s5-real-model-manifest-r3.json"
REPORT = ROOT / "docs/data_clean_dos/v14-s5-real-model-ab-report.json"
CONTROL_ROOT = Path("/home/administrator/.cache/frontieragent-s5-control-669b7d4a")
VERIFICATION_FILES = {
    "control": ROOT / ".scratch/corpus-structure-restart/v14-control-verification.json",
    "candidate": ROOT / ".scratch/corpus-structure-restart/s4-candidate-verification.json",
}

PILOT_TARGETS = (
    "f86c6d2c-cxotable",  # S1: complex table structure
    "5e305376-fedrate",  # S2/S3: split evidence and paged fetch
    "f7f65d7e-risk",  # S4: source-level recall
)
ARMS = {
    "control": {
        "code_root": CONTROL_ROOT,
        "commit": "669b7d4a8540c38d47cf642dc0de4d879eb28c4f",
        "database": "e6_holdout_corpus",
    },
    "candidate": {
        "code_root": ROOT,
        "commit": "288711846b2af754b891120f0d58a7e2f7feab37",
        "database": "v14_s2_quote_corpus",
    },
}
FROZEN_ENV = {
    "MAIN_MAX_TURNS": "40",
    "RESEARCH_WALL_TIME": "1800",
    "REPORT_WALL_TIME": "600",
    "OPENAI_MAX_INPUT_TOKENS": "2000000",
    "OPENAI_MAX_TOKENS": "100000",
    "SANDBOX_BACKEND": "bwrap",
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


def load_configured_model() -> dict[str, str]:
    # Importing config loads ROOT/.env without printing any secret.
    from frontier_agent.infra.config import get_config

    cfg = get_config()
    api_key = os.environ.get("OPENAI_API_KEY", "")
    base_url = os.environ.get("OPENAI_BASE_URL", "")
    model = os.environ.get("OPENAI_MODEL", "") or str(cfg.openai_model)
    if not api_key or not base_url or not model:
        raise RuntimeError("configured OPENAI_API_KEY/OPENAI_BASE_URL/OPENAI_MODEL is incomplete")
    os.environ["JUDGE_API_KEY"] = api_key
    os.environ["JUDGE_BASE_URL"] = base_url
    os.environ["JUDGE_MODEL"] = model
    return {"model": model, "endpoint_host": re.sub(r"^https?://", "", base_url).split("/")[0]}


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


def write_manifest(
    model: dict[str, str], target_ids: Sequence[str], repeats: int
) -> dict[str, Any]:
    assets = [
        GOLD,
        Path(__file__),
        MANIFEST_R1,
        ROOT / ".scratch/corpus-access-validation/e4_scorer.py",
        ROOT / ".scratch/corpus-structure-restart/v14-control-verification.json",
        ROOT / ".scratch/corpus-structure-restart/s4-candidate-verification.json",
        ROOT / "plugins/corpus/preparation/search_pg.py",
        ROOT / "plugins/tools/corpus_fetch.py",
    ]
    dirty = [
        line for line in git_output("status", "--porcelain").splitlines()
        if line and ".codebuddy/memory/MEMORY.md" not in line
    ]
    manifest: dict[str, Any] = {
        "schema": "corpus-v14-s5-real-model-ab-v1",
        "frozen_at": now(),
        "status": "frozen_before_execution",
        "extends_manifest": {
            "path": str(MANIFEST_R1.relative_to(ROOT)),
            "sha256": sha256(MANIFEST_R1),
            "completed_repeats": [1],
            "new_repeats": list(range(2, repeats + 1)),
        },
        "arms": {
            name: {"commit": arm["commit"], "database": arm["database"]}
            for name, arm in ARMS.items()
        },
        "execution": {
            "workflow": "react/stateful-react-agent",
            "one_question_per_process": True,
            "gold_hidden_from_agent": True,
            "concurrency": 1,
            "repeats": repeats,
            "target_ids": target_ids,
            "budgets": FROZEN_ENV,
            "arm_order": "counterbalanced by target index and repeat",
        },
        "model": model,
        "judge": {
            **model,
            "credential_source": "configured OPENAI_* copied to JUDGE_* at runtime",
            "independence": "same-provider same-model judge (user-authorized; not independent)",
        },
        "assets": {str(path.relative_to(ROOT)): sha256(path) for path in assets},
        "non_user_dirty_paths_at_freeze": dirty,
    }
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    return manifest


def latest_run_dir(work_dir: Path) -> Path | None:
    root = work_dir / ".apodex" / "runs"
    if not root.exists():
        return None
    candidates = [path for path in root.iterdir() if path.is_dir()]
    return max(candidates, key=lambda path: path.stat().st_mtime) if candidates else None


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
    result = {
        "artifact": "v14-s5-real-model-run",
        "generated_at": now(),
        "arm": arm_name,
        "repeat": repeat,
        "target_id": target["target_id"],
        "sample_id": target["sample_id"],
        "domain": target["domain"],
        "role": target["evidence_role"],
        "question": target["question"],
        "status": status,
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
                    max_completion_tokens=4000,
                    temperature=0,
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


def write_report(results: list[dict[str, Any]], manifest: dict[str, Any], *, full: bool) -> None:
    excluded = excluded_preflight_attempts()
    summary = aggregate(results)
    control = summary.get("control") or {}
    candidate = summary.get("candidate") or {}

    def delta_percent(metric: str) -> float | None:
        before = float(control.get(metric) or 0)
        after = float(candidate.get(metric) or 0)
        return round((after - before) / before * 100, 1) if before else None

    control_tokens = control.get("tokens") or {}
    candidate_tokens = candidate.get("tokens") or {}
    control_tool_names = control.get("tool_calls_by_name") or {}
    candidate_tool_names = candidate.get("tool_calls_by_name") or {}
    repeat_count = len({row["repeat"] for row in results})

    def token_delta_percent(metric: str) -> float | None:
        before = float(control_tokens.get(metric) or 0)
        after = float(candidate_tokens.get(metric) or 0)
        return round((after - before) / before * 100, 1) if before else None

    def named_tool_delta_percent(name: str) -> float | None:
        before = float(control_tool_names.get(name) or 0)
        after = float(candidate_tool_names.get(name) or 0)
        return round((after - before) / before * 100, 1) if before else None

    candidate_runs = int(candidate.get("runs") or 0)
    pilot_pass = repeat_count >= 3 and candidate_runs > 0 and all(
        int(candidate.get(metric) or 0) == candidate_runs
        for metric in ("judge_pass", "source_offered", "quote_fetched", "quote_delivered")
    )

    report = {
        "artifact": "v14-s5-real-model-ab",
        "generated_at": now(),
        "status": (
            "full_matrix_complete"
            if full
            else ("pilot_repeats_complete" if repeat_count >= 3 else "pilot_complete")
        ),
        "manifest_sha256": sha256(MANIFEST),
        "judge_independence": manifest["judge"]["independence"],
        "scope": {
            "questions": len({row["target_id"] for row in results}),
            "repeats": len({row["repeat"] for row in results}),
            "runs": len(results),
        },
        "summary": summary,
        "comparison": {
            "judge_pass_delta": int(candidate.get("judge_pass") or 0)
            - int(control.get("judge_pass") or 0),
            "source_offered_delta": int(candidate.get("source_offered") or 0)
            - int(control.get("source_offered") or 0),
            "quote_fetched_delta": int(candidate.get("quote_fetched") or 0)
            - int(control.get("quote_fetched") or 0),
            "quote_delivered_delta": int(candidate.get("quote_delivered") or 0)
            - int(control.get("quote_delivered") or 0),
            "wall_s_delta_percent": delta_percent("wall_s"),
            "tool_calls_delta_percent": delta_percent("tool_calls"),
            "corpus_search_calls_delta_percent": named_tool_delta_percent("corpus_search"),
            "corpus_fetch_calls_delta_percent": named_tool_delta_percent("corpus_fetch"),
            "tool_errors_delta": int(candidate.get("tool_errors") or 0)
            - int(control.get("tool_errors") or 0),
            "input_tokens_delta_percent": token_delta_percent("input"),
            "output_tokens_delta_percent": token_delta_percent("output"),
            "cached_tokens_delta_percent": token_delta_percent("cached"),
        },
        "variance": variance_summary(results),
        "decision": {
            "status": (
                "pilot_repeats_pass_expand_51_matrix"
                if pilot_pass
                else "pilot_repeats_complete_needs_review"
                if repeat_count >= 3
                else "pilot_quality_passed_cost_inconclusive"
            ),
            "release_ready": False,
            "reasons": [
                f"Control judged-answer pass: {control.get('judge_pass', 0)}/{control.get('runs', 0)}; "
                f"candidate: {candidate.get('judge_pass', 0)}/{candidate.get('runs', 0)}.",
                f"Candidate wall time delta: {delta_percent('wall_s')}%; tool-call delta: "
                f"{delta_percent('tool_calls')}%; input-token delta: "
                f"{token_delta_percent('input')}%.",
                "The configured judge is the same provider and model as the answering agent, so it is not independent.",
            ] + (
                []
                if repeat_count >= 3
                else [
                    "Only one repeat per question was run; the frozen protocol requires three candidate repeats."
                ]
            ),
            "next_gate": (
                "run the frozen 51-target real-model matrix; use an independent judge before a release claim"
                if pilot_pass
                else "review the failed or missing pilot criteria before expanding the 51-target matrix"
                if repeat_count >= 3
                else "complete repeats 2 and 3 for the frozen three-question pilot before expanding the 51-target matrix"
            ),
        },
        "limitations": [
            "Judge-call token usage was not persisted for repeat 1; repeats 2 and 3 persist it. Answer-agent usage is complete for all repeats.",
            "The pre-execution manifest did not hash the untracked runner source; the report records the post-processing runner hash.",
        ],
        "excluded_preflight_attempts": excluded,
        "postprocess_runner_sha256": sha256(Path(__file__)),
        "per_run": results,
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")


def rescore_existing() -> int:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    results = []
    for path in sorted(RUNS_ROOT.glob("*/*/run-*/result.json")):
        result = json.loads(path.read_text(encoding="utf-8"))
        refresh_source_offered(result)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        results.append(result)
    write_report(results, manifest, full=len({row["target_id"] for row in results}) == 51)
    print(json.dumps(aggregate(results), ensure_ascii=False, indent=2), flush=True)
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--all", action="store_true", help="run all 51 target questions")
    parser.add_argument("--repeats", type=int, default=1)
    parser.add_argument("--timeout", type=int, default=1800)
    parser.add_argument("--rescore-only", action="store_true")
    args = parser.parse_args()
    if args.rescore_only:
        return rescore_existing()
    if args.repeats < 1:
        raise SystemExit("--repeats must be >= 1")
    model = load_configured_model()
    targets = load_targets()
    target_ids = list(targets) if args.all else list(PILOT_TARGETS)
    missing = [target_id for target_id in target_ids if target_id not in targets]
    if missing:
        raise SystemExit(f"missing targets: {missing}")
    for name, arm in ARMS.items():
        actual = git_output("rev-parse", "HEAD", cwd=Path(arm["code_root"]))
        if actual != arm["commit"]:
            raise SystemExit(f"{name} code root is {actual}, expected {arm['commit']}")
        db_check = verify_arm_database(str(arm["database"]))
        print(f"[preflight] {name} database={db_check}", flush=True)
    manifest = write_manifest(model, target_ids, args.repeats)
    print(f"[freeze] {MANIFEST} ({len(target_ids)} questions x {args.repeats} repeats x 2 arms)", flush=True)

    results: list[dict[str, Any]] = []
    for repeat in range(1, args.repeats + 1):
        for index, target_id in enumerate(target_ids):
            order = ("control", "candidate") if (index + repeat) % 2 else ("candidate", "control")
            for arm_name in order:
                print(f"[run] r{repeat} {target_id} {arm_name}", flush=True)
                result_path = RUNS_ROOT / arm_name / target_id / f"run-{repeat:02d}" / "result.json"
                existed = result_path.exists()
                result = run_one(arm_name, targets[target_id], repeat, args.timeout)
                if not existed or (result.get("judge") or {}).get("verdict") not in {"pass", "fail"}:
                    result["judge"] = asyncio.run(judge_one(result, targets[target_id]))
                result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
                results.append(result)
                print(
                    f"[done] {result['status']} judge={result['judge'].get('verdict')} "
                    f"offered={(result.get('deterministic') or {}).get('source_offered')} "
                    f"fetched={(result.get('deterministic') or {}).get('quote_fetched')} "
                    f"wall={result.get('wall_s')}s",
                    flush=True,
                )

    write_report(results, manifest, full=args.all)
    print(json.dumps(aggregate(results), ensure_ascii=False, indent=2), flush=True)
    print(f"[report] {REPORT}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
