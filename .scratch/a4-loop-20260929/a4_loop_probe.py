"""A4 环内修正闭环的真实模型验证探针（补取 → 改表述 → 重新提交）。

背景：``docs/data_clean_dos/01-table-recovery.md`` §A4.5「已知未实现」第 1 条——
清单生产者（``corpus_submit_manifest``）的即时回验与环内修正闭环**从未在真实模型
运行中验证**（既有 3 题冒烟早于该工具存在，验证状态恒为 ``draft``）。

本探针跑真实工作流（``frontier-agent --mode react --no-tui --yes``，tui profile，
含 corpus_search/fetch/inventory + 伴随绑定的 ``corpus_submit_manifest``），逐题：

1. 子进程运行（PGOPTIONS 强制语料库只读；run 工件走文件系统不受影响）；
2. 解析 ``trace.jsonl`` 的 ``corpus_submit_manifest`` 调用序列——每次提交的参数
   （结论数）、返回值（publish_status／counts／逐条 status 与 problems 码）；
3. 解析同一 run 的 ``corpus/manifests/manifest-NNN.json``（每次提交独立落盘）与
   ``corpus/manifest_verification.json``（发布边界重算结果）；
4. 判定**闭环是否发生并收敛**：
   - ``had_feedback``：某次提交有结论带问题码（pending_delivery／not_delivered／
     quote_not_found／missing_dependencies／…）；
   - ``resolved``：更晚的一次提交里，先前有问题的同一结论 id 变为 ``supported``
     （或最终提交 counts 的 partial+unsupported 归零）；
   - 并记录两次提交之间是否出现补取（``corpus_fetch``）与提交次数。

只读保证：子进程 ``PGOPTIONS=default_transaction_read_only=on``；本脚本不写语料库，
只写本目录（``model_runs/<query_id>/result.json``，可续跑）。

用法：
  uv run python .scratch/a4-loop-20260929/a4_loop_probe.py --query-ids company-003
  uv run python .scratch/a4-loop-20260929/a4_loop_probe.py --query-ids company-003 \
      --guided            # 追加「必须登记清单并按反馈重提」的显式要求
"""

from __future__ import annotations

import argparse
import contextlib
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
ARTIFACT_ROOT = ROOT / ".apodex/runs"
SCORING_INPUT = (
    ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"
)
sys.path.insert(0, str(ROOT))

MANIFEST_TOOL = "corpus_submit_manifest"
PROBLEM_CODES = (
    "pending_delivery", "not_delivered", "quote_not_found", "incomplete_evidence",
    "missing_dependencies", "no_evidence", "invalid_evidence", "invalid_conclusion",
    "source_unresolvable", "not_in_report", "verification_error",
)

#: 显式引导档（--guided）追加的要求：把清单义务与**迭代修正闭环**写成硬要求。
GUIDED_ADDENDUM = (
    "\n\n【交付要求（A4 清单）】请用中文给出一份**证据化的简短分析**，并遵守：\n"
    "1. 在整理出初步结论后，**先调用一次 `corpus_submit_manifest` 提交清单**："
    "每条结论给 `id`、`report_quote`（该结论在你最终回答中的**逐字**锚点）、"
    "逐字 `quote` 证据（含 `doc_id`／`locator`／`quote`）及必要的 `required_dependencies`"
    "（value/period/unit/header/footnote）。\n"
    "2. 读取工具返回的**逐条问题**并按其修正：缺原文就去 `corpus_fetch` 补取、"
    "表述不实就修改、无支持就移除；把 `report_quote` 改成最终回答里**逐字出现**的句子。\n"
    "3. 修正后**重新提交完整清单**；若返回 `pending`（新取片段待下一轮边界核验），"
    "在下一轮再次提交确认。如此迭代，直到工具返回全部结论 `supported`。\n"
    "    4. 最终回答不得主张清单标记为 `unsupported` 的结论。\n"
)

#: 早提交档（--early）：刻意在取证完成前先提交，逼出 not_delivered/pending → 补取。
EARLY_ADDENDUM = (
    "\n\n【流程要求（请严格按步骤）】\n"
    "1. 先做**一次** `corpus_search`，不要急着取回全部原文；\n"
    "2. 立即用初步结论调用一次 `corpus_submit_manifest` 提交清单（每条结论给 "
    "`id`、`report_quote`、逐字 `quote` 证据、`required_dependencies`）。此时多数引用"
    "可能被判 `not_delivered`/`pending`（正文尚未取回或尚未过边界核验），这是预期的；\n"
    "3. 逐条读取工具返回的问题：对被判 `not_delivered`/`pending` 的 `locator`，"
    "调用 `corpus_fetch` **补取原文**；对 `missing_dependencies`，补齐对应 purpose 的证据；\n"
    "4. 修正后**重新提交完整清单**，直到工具返回全部结论 `supported`；\n"
    "5. 最后用中文给出简短证据化回答，`report_quote` 必须是回答里逐字出现的句子。\n"
)


def now() -> str:
    return datetime.now(UTC).isoformat()


def load_questions() -> dict[str, dict]:
    rows = [
        json.loads(line)
        for line in SCORING_INPUT.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return {row["query_id"]: row for row in rows}


def norm(text: str) -> str:
    return re.sub(r"\s+", "", text or "")


def _rel(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(ROOT))
    except ValueError:
        return str(path)


def find_run_dir(before: set[str]) -> Path | None:
    if not ARTIFACT_ROOT.exists():
        return None
    fresh = [p for p in ARTIFACT_ROOT.iterdir() if p.is_dir() and p.name not in before]
    return max(fresh, key=lambda p: p.name) if fresh else None


def _flatten_strings(obj: object) -> list[str]:
    if isinstance(obj, str):
        return [obj]
    if isinstance(obj, dict):
        return [s for value in obj.values() for s in _flatten_strings(value)]
    if isinstance(obj, (list, tuple)):
        return [s for value in obj for s in _flatten_strings(value)]
    if obj is None or isinstance(obj, bool):
        return []
    return [str(obj)]


def _result_json(raw: object) -> dict | None:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, str):
        try:
            parsed = json.loads(raw)
        except (TypeError, ValueError):
            return None
        return parsed if isinstance(parsed, dict) else None
    return None


def parse_trace(run_dir: Path) -> dict:
    """抽取 corpus_* 工具时间线 + 每次 corpus_submit_manifest 的反馈。"""
    path = run_dir / "trace.jsonl"
    if not path.exists():
        return {"present": False}
    rows = [
        json.loads(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    timeline: list[dict] = []
    submits: list[dict] = []
    tool_counts: Counter = Counter()
    llm_turns = 0
    for row in rows:
        kind = row.get("t")
        if kind == "llm":
            llm_turns += 1
            continue
        if kind != "tool":
            continue
        name = str(row.get("name") or "")
        tool_counts[name] += 1
        if not name.startswith("corpus_"):
            continue
        entry = {
            "turn": row.get("turn"),
            "name": name,
            "is_error": bool(row.get("is_error")),
        }
        if name == "corpus_fetch":
            args = row.get("args") or {}
            if isinstance(args, dict):
                locs = args.get("locators")
                if isinstance(locs, list):
                    entry["mode"] = "batch"
                    entry["locators"] = [str(x) for x in locs]
                elif args.get("cursor") is not None:
                    entry["mode"] = "cursor"
                else:
                    entry["mode"] = "single"
                    entry["locators"] = [str(args.get("locator") or "")] if args.get("locator") else []
        if name == MANIFEST_TOOL:
            args = row.get("args") or {}
            n_concl = None
            if isinstance(args, dict) and isinstance(args.get("conclusions"), list):
                n_concl = len(args["conclusions"])
            payload = _result_json(row.get("result"))
            entry["seq"] = len(submits)
            entry["n_conclusions"] = n_concl
            if payload is None:
                entry["parseable"] = False
            else:
                concl = payload.get("conclusions") or []
                per = []
                for c in concl:
                    if not isinstance(c, dict):
                        continue
                    codes = sorted({
                        str(p.get("code"))
                        for p in (c.get("problems") or [])
                        if isinstance(p, dict)
                    })
                    per.append({
                        "id": c.get("id"),
                        "status": c.get("status"),
                        "delivery": c.get("delivery"),
                        "codes": codes,
                    })
                entry.update({
                    "parseable": True,
                    "ok": payload.get("ok"),
                    "publish_status": payload.get("publish_status"),
                    "counts": payload.get("counts"),
                    "errors": payload.get("errors"),
                    "conclusions": per,
                    "problem_codes": dict(Counter(
                        code for c in per for code in c["codes"]
                    )),
                })
            submits.append(entry)
        timeline.append(entry)
    return {
        "present": True,
        "llm_turns": llm_turns,
        "tool_counts": dict(tool_counts),
        "corpus_timeline": timeline,
        "manifest_submits": submits,
    }


def parse_manifests(run_dir: Path) -> dict:
    sub = run_dir / "corpus" / "manifests"
    files = sorted(sub.glob("*.json")) if sub.is_dir() else []
    return {
        "count": len(files),
        "files": [_rel(p) for p in files],
    }


def parse_verification(run_dir: Path) -> dict:
    path = run_dir / "corpus" / "manifest_verification.json"
    if not path.exists():
        return {"present": False}
    data = json.loads(path.read_text(encoding="utf-8"))
    codes = Counter(
        p.get("code")
        for row in (data.get("conclusions") or [])
        for p in (row.get("problems") or [])
        if isinstance(p, dict)
    )
    return {
        "present": True,
        "status": data.get("status"),
        "counts": data.get("counts"),
        "verification_errors": data.get("verification_errors"),
        "problem_codes": dict(codes),
        "boundary_action": data.get("boundary_action"),
        "manifest_files": data.get("manifest_files"),
        "path": _rel(path),
    }


def analyse_loop(submits: list[dict], timeline: list[dict]) -> dict:
    """判定「提交→反馈→修正→重新提交→收敛」是否发生。"""
    feedback_submits = [
        s for s in submits
        if s.get("parseable") and (s.get("problem_codes") or s.get("errors"))
    ]
    had_feedback = bool(feedback_submits)
    # 逐结论 id 的「先前有问题 → 后来 supported」转移。
    resolved: list[dict] = []
    seen_problem: dict[str, int] = {}
    for s in submits:
        if not s.get("parseable"):
            continue
        seq = s.get("seq")
        for c in s.get("conclusions") or []:
            cid = str(c.get("id"))
            if c.get("codes"):
                seen_problem.setdefault(cid, seq)
            elif cid in seen_problem and c.get("status") == "supported":
                resolved.append({
                    "id": cid,
                    "problem_at_submit": seen_problem[cid],
                    "resolved_at_submit": seq,
                })
    # 最终提交汇总。
    final = next((s for s in reversed(submits) if s.get("parseable")), None)
    final_counts = (final or {}).get("counts") or {}
    final_clean = bool(final) and not (
        (final_counts.get("partial") or 0) + (final_counts.get("unsupported") or 0)
    )
    # 提交之间是否有补取。
    fetches = [e for e in timeline if e.get("name") == "corpus_fetch"]
    return {
        "manifest_tool_calls": len(submits),
        "had_feedback": had_feedback,
        "feedback_submit_seqs": [s.get("seq") for s in feedback_submits],
        "feedback_codes": dict(Counter(
            code for s in feedback_submits for code in (s.get("problem_codes") or {})
        )),
        "resolved_conclusions": resolved,
        "resolved": bool(resolved) or (had_feedback and final_clean),
        "final_publish_status": (final or {}).get("publish_status"),
        "final_counts": final_counts,
        "corpus_fetch_calls": len(fetches),
        "corpus_fetch_locators": sum(len(e.get("locators") or []) for e in fetches),
    }


def answer_and_corpus_blob(run_dir: Path) -> tuple[str, str]:
    answer = ""
    if (run_dir / "session.json").exists():
        data = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
        for message in reversed(data.get("history") or []):
            if message.get("role") == "assistant":
                answer = str(message.get("content") or "")
                break
    report = run_dir / "outputs" / "report.md"
    if report.exists():
        answer += "\n" + report.read_text(encoding="utf-8")
    corpus_parts: list[str] = []
    trace = run_dir / "trace.jsonl"
    if trace.exists():
        for line in trace.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            if row.get("t") != "tool" or not str(row.get("name") or "").startswith("corpus_"):
                continue
            result = row.get("result")
            if isinstance(result, str):
                with contextlib.suppress(TypeError, ValueError):
                    result = json.loads(result)
            corpus_parts.extend(_flatten_strings(result))
    return answer, "\n".join(corpus_parts)


def gold_coverage(row: dict, corpus_blob: str, answer_blob: str) -> dict:
    targets = row.get("evidence_targets") or []
    per = []
    for target in targets:
        quote = norm(target.get("quote") or "")
        if not quote:
            continue
        per.append({
            "target_id": target.get("target_id"),
            "fetched": quote in corpus_blob,
            "in_answer": quote in answer_blob,
        })
    return {
        "targets": len(per),
        "fetched_hit": sum(1 for t in per if t["fetched"]),
        "answer_hit": sum(1 for t in per if t["in_answer"]),
    }


def run_question(
    row: dict, timeout_s: int, guided: bool, out_root: Path | None = None,
    early: bool = False,
) -> dict:
    query_id = row["query_id"]
    artifact_dir = (out_root or RUNS_DIR) / query_id
    result_path = artifact_dir / "result.json"
    if result_path.exists():
        old = json.loads(result_path.read_text(encoding="utf-8"))
        rd = (old.get("session") or {}).get("run_dir")
        if rd and (ROOT / rd).exists():
            return {**old, "skipped": True, "note": "result.json 已存在：未重跑（删目录可重跑）"}
        return {"query_id": query_id, "skipped": True, "note": "result.json 已存在且无 run_dir"}

    artifact_dir.mkdir(parents=True, exist_ok=True)
    addendum = EARLY_ADDENDUM if early else (GUIDED_ADDENDUM if guided else "")
    question = row["question"] + addendum
    before = {p.name for p in ARTIFACT_ROOT.iterdir()} if ARTIFACT_ROOT.exists() else set()
    env = dict(os.environ)
    env["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=120000"

    started = time.monotonic()
    proc = subprocess.run(
        ["uv", "run", "frontier-agent", "--mode", "react", "--no-tui", "--yes", "-p", question],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=timeout_s,
    )
    wall_s = round(time.monotonic() - started, 1)
    (artifact_dir / "stdout tail.txt").write_text(
        (proc.stdout or "")[-4000:] + "\n--- stderr ---\n" + (proc.stderr or "")[-3000:],
        encoding="utf-8",
    )

    run_dir = find_run_dir(before)
    session: dict = {"present": False}
    gold = {"targets": 0, "fetched_hit": 0, "answer_hit": 0}
    trace = {"present": False}
    manifests = {"count": 0, "files": []}
    verification = {"present": False}
    loop = {"manifest_tool_calls": 0, "had_feedback": False, "resolved": False}
    if run_dir is not None:
        if (run_dir / "session.json").exists():
            data = json.loads((run_dir / "session.json").read_text(encoding="utf-8"))
            usage = data.get("usage") or {}
            session = {
                "present": True,
                "session_id": data.get("session_id"),
                "model": data.get("model"),
                "run_dir": _rel(run_dir),
                "usage": {
                    "input": usage.get("input"), "output": usage.get("output"),
                    "cached": usage.get("cached"),
                },
            }
        trace = parse_trace(run_dir)
        manifests = parse_manifests(run_dir)
        verification = parse_verification(run_dir)
        loop = analyse_loop(trace.get("manifest_submits") or [], trace.get("corpus_timeline") or [])
        answer, corpus_blob = answer_and_corpus_blob(run_dir)
        gold = gold_coverage(row, norm(corpus_blob), norm(answer))

    result = {
        "artifact": "a4-loop-probe-question",
        "query_id": query_id,
        "domain": row["domain"],
        "question": row["question"],
        "guided": guided,
        "status": "ok" if proc.returncode == 0 else f"exit:{proc.returncode}",
        "wall_s": wall_s,
        "session": session,
        "trace": trace,
        "manifests": manifests,
        "verification": verification,
        "loop": loop,
        "gold": gold,
        "generated_at": now(),
    }
    result_path.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--query-ids", default="company-003",
                        help="逗号分隔的 query_id（默认 company-003）")
    parser.add_argument("--timeout", type=int, default=1800, help="每题子进程超时秒数")
    parser.add_argument("--guided", action="store_true", help="追加显式「必须登记并重提」要求")
    parser.add_argument("--early", action="store_true", help="早提交档：取证前先提交以逼出补取闭环")
    parser.add_argument("--tag", default="", help="产物子目录/摘要后缀（区分自然档与引导档）")
    args = parser.parse_args()

    out_root = RUNS_DIR / args.tag if args.tag else RUNS_DIR
    catalogue = load_questions()
    ids = [x.strip() for x in args.query_ids.split(",") if x.strip()]
    rows = []
    for qid in ids:
        if qid not in catalogue:
            print(f"!! unknown query_id: {qid}")
            continue
        row = catalogue[qid]
        print(f"== {qid} :: {row['question'][:50]}…")
        try:
            result = run_question(row, args.timeout, args.guided, out_root, args.early)
        except subprocess.TimeoutExpired:
            result = {"query_id": qid, "status": "timeout", "timeout_s": args.timeout,
                      "generated_at": now()}
            (out_root / qid).mkdir(parents=True, exist_ok=True)
            (out_root / qid / "result.json").write_text(
                json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        lp = result.get("loop") or {}
        print(
            f"   status={result.get('status')} wall={result.get('wall_s')}s "
            f"submits={lp.get('manifest_tool_calls')} feedback={lp.get('had_feedback')} "
            f"resolved={lp.get('resolved')} final={lp.get('final_publish_status')}"
        )
        rows.append(result)

    done = [r for r in rows if r.get("status") == "ok"]
    usage_total = {
        "input": sum((r.get("session", {}).get("usage") or {}).get("input") or 0 for r in done),
        "output": sum((r.get("session", {}).get("usage") or {}).get("output") or 0 for r in done),
    }
    summary = {
        "artifact": "a4-loop-probe",
        "version": 1,
        "generated_at": now(),
        "tier": "real-model A4 in-loop correction probe (react/tui profile)",
        "policy": {
            "command": "uv run frontier-agent --mode react --no-tui --yes -p <question>",
            "guided": args.guided,
            "early": args.early,
            "pg_read_only": "PGOPTIONS default_transaction_read_only=on",
            "resumable": "model_runs/<query_id>/result.json 存在即跳过",
        },
        "scale": {"questions": len(rows), "ok": len(done)},
        "totals": usage_total,
        "per_question": rows,
    }
    (OUT / f"a4_loop_probe{('.' + args.tag) if args.tag else ''}.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "questions": [{
            "query_id": r.get("query_id"),
            "status": r.get("status"),
            "loop": r.get("loop"),
        } for r in rows],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
