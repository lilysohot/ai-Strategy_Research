"""E5 正式集批量驱动（apodex CLI + bwrap 隔离）。

30 题 = gold ``query-gold-scoring-v1.jsonl`` 的 30 个 query_id（company/industry/macro ×10）。
每独立会话在 ``<ROOT>/.e5runs_e5/<qid>/`` 下跑 ``--mode react -p "<question>"``，
强制 ``SANDBOX_BACKEND=bwrap``（OS 级读边界藏 ``.scratch``）＋冻结预算 env，并发 1，可续跑。

对 24 个含 target 的题调 ``e5_score_run.py`` 落 L1–L9；对 6 个 no_answer 题落负向（幻觉）检查。
产物：每题 ``<qid>/e5-run-score.json``（或 no-answer 版）＋ 根级 ``e5-batch-summary.json``。

用法：uv run python e5_run_batch.py [--run-qids c-001,...] [--all] [--score-only]
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
GOLD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"
RUNS_ROOT = ROOT / ".e5runs_e5"
SCORER = OUT / "e5_score_run.py"

FROZEN_ENV = {
    "MAIN_MAX_TURNS": "40",
    "RESEARCH_WALL_TIME": "1800",
    "REPORT_WALL_TIME": "600",
    "OPENAI_MAX_INPUT_TOKENS": "2000000",
    "OPENAI_MAX_TOKENS": "100000",
}
# no_answer 键（在这些题中模型应正确报告“缺失”，不得编造；不进 L1–L9 矩阵）
NO_ANSWER_QUERIES = {
    "company-009", "company-010", "industry-009", "industry-010",
    "macro-009", "macro-010",
}
_NEG_MARKERS = (
    "未披露", "未给出", "未提供", "无法给出", "无法提供", "没有", "不存在",
    "未包含", "不含", "找不到", "未找到", "没有披露", "没有给出",
)


def load_gold() -> dict:
    rows = {}
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        r = json.loads(line)
        rows[r["query_id"]] = r
    return rows


def latest_run_dir(qid: str) -> Path | None:
    """该题最近一次带落盘账本的 run 目录。"""
    base = RUNS_ROOT / qid / ".apodex" / "runs"
    if not base.exists():
        return None
    cands = []
    for d in base.iterdir():
        if d.is_dir() and (d / "corpus" / "ledger.json").exists():
            cands.append(d)
    if not cands:
        return None
    return max(cands, key=lambda d: d.stat().st_mtime)


def qid_is_done(qid: str) -> bool:
    if qid in NO_ANSWER_QUERIES:
        return (RUNS_ROOT / qid / "e5-noanswer-score.json").exists()
    rd = latest_run_dir(qid)
    return rd is not None and (rd / "e5-run-score.json").exists()


def run_one(qid: str, question: str) -> None:
    cwd = RUNS_ROOT / qid
    cwd.mkdir(parents=True, exist_ok=True)
    env = {**os.environ, "SANDBOX_BACKEND": "bwrap", **FROZEN_ENV}
    cmd = [
        sys.executable, "-m", "apodex.cli", "--mode", "react",
        "-p", question, "--cwd", str(cwd), "--no-tui", "--yes",
    ]
    # apodex 入口假定用 `uv run frontier-agent`；此处走模块等价（runner 已由 uv 启动）。
    proc = subprocess.run(cmd, cwd=cwd, env=env, capture_output=True, text=True)
    if proc.returncode != 0:
        # 记录但仍继续（评分器会依据是否产 ledger 判定无答案失败）。
        (cwd / "run.err.log").write_text(proc.stderr[-4000:], encoding="utf-8")


def score_one(qid: str, gold: dict) -> dict:
    rd = latest_run_dir(qid)
    if qid in NO_ANSWER_QUERIES:
        return score_noanswer(qid, gold[qid], rd)
    if rd is None:
        return {"query_id": qid, "error": "no_run_dir", "targets": [], "all_pass": 0}
    r = subprocess.run(
        [sys.executable, str(SCORER), "--run", str(rd), "--query", qid],
        capture_output=True, text=True,
    )
    if r.returncode != 0:
        return {"query_id": qid, "error": f"scorer_rc{r.returncode}: {r.stderr[-500:]}",
                "targets": [], "all_pass": 0}
    return json.loads(r.stdout) if r.stdout.strip().startswith("{") else \
        json.loads((rd / "e5-run-score.json").read_text(encoding="utf-8"))


def score_noanswer(qid: str, row: dict, rd: Path | None) -> dict:
    """负向：最终回答应明确表示“缺失/无法给出”，不得编造数值。"""
    result = {"query_id": qid, "answer_existence": "no_answer",
              "run_dir": str(rd) if rd else None, "checks": []}
    if rd is None:
        result["verdict"] = "no_run_ledger"
        (RUNS_ROOT / qid / "e5-noanswer-score.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    trace = rd / "trace.jsonl"
    texts = []
    if trace.exists():
        for line in trace.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(ev, dict) and ev.get("t") == "llm" and isinstance(ev.get("text"), str):
                texts.append(ev["text"])
    answer = "\n".join(texts[-2:]) if texts else ""
    neg = any(m in answer for m in _NEG_MARKERS)
    # 编造探测：出现具体财务数值（年份+数字）即视为可能编造；仅定性否定词算安全。
    import re
    fabricated = bool(re.search(r"(?:20\d{2}[年:：]?|EPS|归母|净利|均价|采购|利率)[^0-9]{0,6}\d[0-9,.%]*", answer))
    verdict = "ok" if (neg and not fabricated) else ("weak_negative" if neg else "hallucination_risk")
    result.update({
        "has_negative_marker": neg, "fabrication_risk": fabricated,
        "answer_preview": answer[:300], "verdict": verdict,
    })
    (RUNS_ROOT / qid / "e5-noanswer-score.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    return result


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--all", action="store_true", help="run + score pending questions")
    ap.add_argument("--score-only", action="store_true")
    ap.add_argument("--run-qids", default="", help="限定 query_id 白名单（逗号分隔）或 all")
    args = ap.parse_args()

    gold = load_gold()
    qids = list(gold.keys())
    if args.run_qids and args.run_qids != "all":
        qids = [q.strip() for q in args.run_qids.split(",") if q.strip()]

    if args.all:
        for qid in qids:
            question = gold[qid]["question"]
            if qid_is_done(qid):
                print(f"[skip] {qid} 已完成", flush=True)
                continue
            print(f"[run ] {qid} (source={gold[qid].get('relevant_sources')})", flush=True)
            run_one(qid, question)
            score_one(qid, gold)
            print(f"[done] {qid} → {qid_is_done(qid)}", flush=True)

    score_only = args.score_only or (not args.all)
    if score_only:
        for qid in qids:
            score = score_one(qid, gold)
            if qid in NO_ANSWER_QUERIES:
                print(f"[score] {qid} noanswer verdict={score.get('verdict')}", flush=True)
            else:
                print(f"[score] {qid} all_pass={score.get('all_pass')}/"
                      f"{sum(1 for t in score.get('targets', []) if t is not None)} "
                      f"fails={score.get('summary', {}).get('fail_targets', [])}", flush=True)

    # 汇总
    summary = {"generated_at": _dt.datetime.now(_dt.UTC).isoformat(),
               "policy": "SANDBOX_BACKEND=bwrap + 冻结预算(40轮/30min/2M in/100k out/60 tools)；生成侧=e4-validate；消费侧=ledger+trace；零模型",
               "queries": {}}
    for qid in gold:
        if qid in NO_ANSWER_QUERIES:
            p = RUNS_ROOT / qid / "e5-noanswer-score.json"
        else:
            rd = latest_run_dir(qid)
            p = (rd / "e5-run-score.json") if rd else None
        if p is not None and p.exists():
            summary["queries"][qid] = json.loads(p.read_text(encoding="utf-8"))
    (OUT / "e5-batch-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(f"[summary] {len(summary['queries'])} scored → {OUT / 'e5-batch-summary.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())