"""A4 固定任务回放（真实模型档）：3 道冻结题冒烟、apodex 子进程、逐题可续跑。

目的：在**真实模型 + 真实工作流**（``frontier-agent --mode react``，glm-5.3-flash）
上跑固定任务集冒烟，与零模型档（replay.py，protocol 层）互补：

- **成本**：session.json 的 usage（input/output/cached token 与消息级 breakdown）、
  trace.jsonl 的 LLM 轮数与工具调用数、墙钟时间；
- **A4 账本**：run 工件 ``corpus/ledger.json`` 的 offered/requested/fetched/delivered
  四集合与范围完整性（观测模式，不阻断）；发布边界工件
  ``corpus/manifest_verification.json``（发布状态与逐结论问题码，评审 §5.3 修正：
  旧脚本误读 ``verification.json`` 导致该字段恒空）；
- **正确性代理（零评分成本）**：冻结金标 ``evidence_targets`` 的逐字引文是否出现在
  (a) 取回的语料内容（trace 工具结果）→ 取回侧覆盖；(b) 最终答案 → 答案侧覆盖。
  引文按空白归一后子串匹配；**不用金标决定取哪些块**（agent 自己搜）。

选题（确定性，冒烟规模 3）：金标 ``evidence_targets`` 用于**分层选题**——三个 domain
各取第一道 answerable 且带 row/cell 约束的题（company-003／industry-001，表格题是
D2 修复的直接受益场景）；macro 无 cell 约束题取第一道 answerable（macro-001，叙述题
对照）。金标同时用于事后评分（引文覆盖）；**金标参与了选题与评分，因此这不是独立
盲测**。检索决策不使用金标：agent 自己搜，不用金标决定取哪些块。

可续跑：每题结果落 ``model_runs/<query_id>/result.json``，已存在则跳过（与
benchmarks 公共 harness 的 resumable 约定同口径）。只读保证：子进程 PGOPTIONS
强制 ``default_transaction_read_only=on``（语料库只读；run 工件走文件系统不受影响）。

用法：``uv run python .scratch/a4-replay-20260928/replay_model.py [--timeout 900]``
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
RUNS_DIR = OUT / "model_runs"
SCORING_INPUT = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"
sys.path.insert(0, str(ROOT))

SMOKE_SCALE = 3
ARTIFACT_ROOT = ROOT / ".apodex/runs"


def now() -> str:
    return datetime.now(UTC).isoformat()


def load_questions() -> list[dict]:
    rows = [
        json.loads(line)
        for line in SCORING_INPUT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return rows


def pick_smoke_questions(rows: list[dict]) -> list[dict]:
    """每个 domain 一道：优先 answerable 且金标带 row/cell 约束（表格题），否则第一道 answerable。"""

    def has_cell_constraint(row: dict) -> bool:
        for target in row.get("evidence_targets") or []:
            constraints = target.get("constraints") or {}
            if constraints.get("row") or constraints.get("cell"):
                return True
        return False

    picked: list[dict] = []
    for domain in ("company", "industry", "macro"):
        candidates = [r for r in rows if r["domain"] == domain and r["query_kind"] == "answerable"]
        table = [r for r in candidates if has_cell_constraint(r)]
        picked.append((table or candidates)[0])
    return picked


def norm(text: str) -> str:
    """引文匹配归一：压缩所有空白（金标引文含换行，agent 侧文本边界的空白形态不定）。"""
    return re.sub(r"\s+", "", text or "")


def find_run_dir(before: set[str]) -> Path | None:
    """子进程结束后新出现的 run 目录（按名字排序取最新）。"""
    if not ARTIFACT_ROOT.exists():
        return None
    fresh = [p for p in ARTIFACT_ROOT.iterdir() if p.is_dir() and p.name not in before]
    return max(fresh, key=lambda p: p.name) if fresh else None


def parse_trace(run_dir: Path) -> dict:
    path = run_dir / "trace.jsonl"
    if not path.exists():
        return {"present": False}
    rows = [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]
    tools: Counter = Counter()
    tool_ms = 0.0
    tool_errors = 0
    corpus_blob = ""
    llm_turns = 0
    for row in rows:
        kind = row.get("t")
        if kind == "llm":
            llm_turns += 1
        elif kind == "tool":
            name = row.get("name") or ""
            tools[name] += 1
            tool_ms += float(row.get("ms") or 0)
            if row.get("is_error"):
                tool_errors += 1
            if name.startswith("corpus_"):
                corpus_blob += json.dumps(row.get("result"), ensure_ascii=False, default=str)
    return {
        "present": True,
        "llm_turns": llm_turns,
        "tool_calls": sum(tools.values()),
        "tool_calls_by_name": dict(tools),
        "tool_ms_total": round(tool_ms),
        "tool_errors": tool_errors,
        "corpus_calls": {k: v for k, v in tools.items() if k.startswith("corpus_")},
    }


def parse_ledger(run_dir: Path) -> dict:
    path = run_dir / "corpus" / "ledger.json"
    if not path.exists():
        return {"present": False, "note": "无 corpus 调用或观察者未落盘"}
    data = json.loads(path.read_text(encoding="utf-8"))
    verification = None
    ver_path = run_dir / "corpus" / "manifest_verification.json"
    if ver_path.exists():
        verification = json.loads(ver_path.read_text(encoding="utf-8"))
    problem_codes = Counter(
        problem.get("code")
        for row in (verification or {}).get("conclusions") or []
        for problem in row.get("problems") or []
        if isinstance(problem, dict)
    )
    return {
        "present": True,
        "offered": len(data.get("offered") or []),
        "requested": len(data.get("requested") or []),
        "fetched": len(data.get("fetched") or []),
        "delivered": len(data.get("delivered") or []),
        "delivered_status": dict(Counter(d.get("status") for d in data.get("delivered") or [])),
        "all_offered_fetched": data.get("all_offered_fetched"),
        "range_completeness": data.get("range_completeness") or [],
        "errors": data.get("errors") or [],
        "skipped": len(data.get("skipped") or []),
        "verification_status": (verification or {}).get("status"),
        "verification_counts": (verification or {}).get("counts"),
        "verification_errors": (verification or {}).get("verification_errors"),
        "verification_problem_codes": dict(problem_codes),
        "verification_path": str(ver_path.relative_to(ROOT)) if verification else None,
    }


def gold_coverage(row: dict, corpus_blob: str, answer_blob: str) -> dict:
    """零成本正确性代理：金标逐字引文的取回侧／答案侧覆盖（空白归一子串匹配）。"""
    targets = row.get("evidence_targets") or []
    per_target = []
    for target in targets:
        quote = norm(target.get("quote") or "")
        if not quote:
            per_target.append({"target_id": target.get("target_id"), "fetched": None, "in_answer": None})
            continue
        per_target.append(
            {
                "target_id": target.get("target_id"),
                "role": target.get("role"),
                "fetched": quote in corpus_blob,
                "in_answer": quote in answer_blob,
            }
        )
    graded = [t for t in per_target if t["fetched"] is not None]
    return {
        "targets": len(targets),
        "fetched_hit": sum(1 for t in graded if t["fetched"]),
        "answer_hit": sum(1 for t in graded if t["in_answer"]),
        "fetched_coverage": round(sum(1 for t in graded if t["fetched"]) / len(graded), 3) if graded else None,
        "answer_coverage": round(sum(1 for t in graded if t["in_answer"]) / len(graded), 3) if graded else None,
        "per_target": per_target,
    }


def answer_blob_from(run_dir: Path | None) -> str:
    """最终答案文本：session 历史最后一条 assistant 消息 + outputs/report.md（若有）。"""
    if run_dir is None or not (run_dir / "session.json").exists():
        return ""
    data = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
    answer = ""
    for message in reversed(data.get("history") or []):
        if message.get("role") == "assistant":
            answer = str(message.get("content") or "")
            break
    report = run_dir / "outputs" / "report.md"
    if report.exists():
        answer += "\n" + report.read_text(encoding="utf-8")
    return answer


def run_question(row: dict, timeout_s: int) -> dict:
    query_id = row["query_id"]
    artifact_dir = RUNS_DIR / query_id
    result_path = artifact_dir / "result.json"
    if result_path.exists():
        old = json.loads(result_path.read_text(encoding="utf-8"))
        run_dir = ROOT / (old.get("session") or {}).get("run_dir", "x")
        if (old.get("session") or {}).get("run_dir") and run_dir.exists():
            # 可续跑：agent 子进程不重跑，仅按当前评分口径重算（评分口径修过时有用）
            old["trace"] = parse_trace(run_dir)
            old["ledger"] = parse_ledger(run_dir)
            answer_blob = answer_blob_from(run_dir)
            old["gold"] = gold_coverage(row, norm(corpus_blob_from(run_dir)), norm(answer_blob))
            result_path.write_text(json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
            return {**old, "skipped": True, "note": "已存在：仅重算评分，未重跑 agent"}
        return {"query_id": query_id, "skipped": True, "note": "result.json 已存在且无 run_dir"}

    artifact_dir.mkdir(parents=True, exist_ok=True)
    before = {p.name for p in ARTIFACT_ROOT.iterdir()} if ARTIFACT_ROOT.exists() else set()
    env = dict(os.environ)
    env["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=120000"

    started = time.monotonic()
    proc = subprocess.run(
        [
            "uv", "run", "frontier-agent",
            "--mode", "react", "--no-tui", "--yes",
            "-p", row["question"],
        ],
        cwd=str(ROOT),
        env=env,
        capture_output=True,
        text=True,
        timeout=timeout_s,
    )
    wall_s = round(time.monotonic() - started, 1)
    (artifact_dir / "stdout tail.txt").write_text(
        (proc.stdout or "")[-4000:] + "\n--- stderr ---\n" + (proc.stderr or "")[-2000:],
        encoding="utf-8",
    )

    run_dir = find_run_dir(before)
    session: dict = {"present": False}
    answer_blob = ""
    if run_dir is not None and (run_dir / "session.json").exists():
        data = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
        usage = data.get("usage") or {}
        session = {
            "present": True,
            "session_id": data.get("session_id"),
            "model": data.get("model"),
            "run_dir": str(run_dir.relative_to(ROOT)),
            "usage": {
                "input": usage.get("input"),
                "output": usage.get("output"),
                "cached": usage.get("cached"),
                "compactions": usage.get("compactions"),
                "last_input": usage.get("last_input"),
            },
            "history_len": len(data.get("history") or []),
        }
        answer_blob = answer_blob_from(run_dir)

    result = {
        "artifact": "a4-replay-model-question",
        "query_id": query_id,
        "domain": row["domain"],
        "question": row["question"],
        "status": "ok" if proc.returncode == 0 else f"exit:{proc.returncode}",
        "wall_s": wall_s,
        "session": session,
        "trace": parse_trace(run_dir) if run_dir else {"present": False},
        "ledger": parse_ledger(run_dir) if run_dir else {"present": False},
        "gold": gold_coverage(row, norm(corpus_blob_from(run_dir)), norm(answer_blob)),
        "generated_at": now(),
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def _flatten_strings(obj: object) -> list[str]:
    """递归展平 JSON 结构里的字符串值（含数字转文本）。

    工具结果在 trace 里是 JSON 文本，直接二次 dumps 会把换行变成字面 ``\\n`` 两字符，
    与金标引文（真实换行）归一后无法对齐——必须先解析再取字符串值。
    """
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for value in obj.values() for s in _flatten_strings(value)]
    if isinstance(obj, (list, tuple)):
        return [s for value in obj for s in _flatten_strings(value)]
    if obj is None or isinstance(obj, bool):
        return []
    return [str(obj)]


def corpus_blob_from(run_dir: Path | None) -> str:
    """从 trace 提取 corpus 工具结果正文（解析后展平，供引文匹配）。"""
    if run_dir is None:
        return ""
    path = run_dir / "trace.jsonl"
    if not path.exists():
        return ""
    parts: list[str] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if row.get("t") != "tool" or not (row.get("name") or "").startswith("corpus_"):
            continue
        result = row.get("result")
        if isinstance(result, str):
            try:
                result = json.loads(result)
            except (TypeError, ValueError):
                pass
        parts.extend(_flatten_strings(result))
    return "\n".join(parts)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--timeout", type=int, default=900, help="每题子进程超时秒数")
    args = parser.parse_args()

    questions = pick_smoke_questions(load_questions())
    print("smoke questions:", [q["query_id"] for q in questions])

    rows = []
    for row in questions:
        print(f"== {row['query_id']} :: {row['question'][:40]}…")
        try:
            result = run_question(row, args.timeout)
        except subprocess.TimeoutExpired:
            result = {
                "artifact": "a4-replay-model-question",
                "query_id": row["query_id"],
                "status": "timeout",
                "timeout_s": args.timeout,
                "generated_at": now(),
            }
            artifact_dir = RUNS_DIR / row["query_id"]
            artifact_dir.mkdir(parents=True, exist_ok=True)
            (artifact_dir / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        print(
            f"   status={result.get('status')} wall={result.get('wall_s')}s "
            f"gold_fetched={result.get('gold', {}).get('fetched_coverage')} "
            f"gold_answer={result.get('gold', {}).get('answer_coverage')}"
        )
        rows.append(result)

    done = [r for r in rows if r.get("status") == "ok"]
    usage_total = {
        "input": sum((r.get("session", {}).get("usage") or {}).get("input") or 0 for r in done),
        "output": sum((r.get("session", {}).get("usage") or {}).get("output") or 0 for r in done),
        "cached": sum((r.get("session", {}).get("usage") or {}).get("cached") or 0 for r in done),
    }
    summary = {
        "artifact": "a4-replay-model",
        "version": 1,
        "generated_at": now(),
        "tier": "real-model smoke (glm-5.3-flash, react, one-shot per question)",
        "scale": {"questions": len(rows), "ok": len(done)},
        "selection_policy": "每 domain 一道 answerable；按金标 row/cell 约束分层优先表格题（D2 受益场景）——金标参与分层选题与事后评分",
        "policy": {
            "command": "uv run frontier-agent --mode react --no-tui --yes -p <question>",
            "pg_read_only": "PGOPTIONS default_transaction_read_only=on",
            "resumable": "model_runs/<query_id>/result.json 存在即跳过",
            "gold_usage": "金标用于分层选题和事后评分（引文覆盖），不进入模型检索决策；因此这不是独立盲测",
        },
        "totals": {
            "wall_s": round(sum(r.get("wall_s") or 0 for r in done), 1),
            "usage_tokens": usage_total,
            "llm_turns": sum((r.get("trace") or {}).get("llm_turns") or 0 for r in done),
            "tool_calls": sum((r.get("trace") or {}).get("tool_calls") or 0 for r in done),
            "ledger_offered": sum((r.get("ledger") or {}).get("offered") or 0 for r in done),
            "ledger_fetched": sum((r.get("ledger") or {}).get("fetched") or 0 for r in done),
            "ledger_delivered": sum((r.get("ledger") or {}).get("delivered") or 0 for r in done),
            "gold_fetched_coverage": [
                {"query_id": r["query_id"], "coverage": (r.get("gold") or {}).get("fetched_coverage")}
                for r in rows
            ],
        },
        "per_question": rows,
    }
    (OUT / "replay_model.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
