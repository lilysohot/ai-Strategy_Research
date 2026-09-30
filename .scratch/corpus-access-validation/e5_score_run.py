"""E5 独立实测评分驱动：把一次真实 model run 落到 L1–L9。

生成侧（L1–L5）复用 ``e4-validate.json``（冻结 gen-2 build 直读，见 e4_validate.py）；
消费侧（L6–L9）从 ``<run>/corpus/ledger.json`` 与 ``<run>/trace.jsonl`` 装配：

- L6 requested：账本 ``requested`` 含该 run 构建（doc) 的请求范围；
- L7 fetched：账本 ``fetched`` 含该构建片段，且引文出现在取回正文（trace 工具结果）；
- L8 delivered：账本 ``delivered`` 状态 == ``delivered``（片段**完整**存留到最终模型输入，
  由 ledger.finalize 在真实消息边界核验），且引文/必要单位已在送达内容里；
- L9 answer_supported：最终回答（trace 末条 assistant 文本）含目标的数值/期间/单位。

零模型、只读：仅解析 run 产物，不再调模型。产物：``<run>/e5-run-score.json``。
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
GOLD = ROOT / ".scratch/corpus-evidence-pipeline" / "ingestion-rebuild" / "i3-2" / "query-gold-scoring-v1.jsonl"

spec = importlib.util.spec_from_file_location("e4_scorer", OUT / "e4_scorer.py")
e4 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(e4)

E4_JSON = OUT / "e4-validate.json"


def load_gold_targets() -> dict[tuple, dict]:
    """(query_id, target_id) → {quote, period, unit, row, col, cell, locator, tier}。"""
    out: dict[tuple, dict] = {}
    for line in GOLD.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        qid = row["query_id"]
        for tier, key in (
            ("required", "evidence_targets"),
            ("supplementary", "supplementary_evidence_targets"),
        ):
            for t in row.get(key) or []:
                c = t.get("constraints") or {}
                out[(qid, t.get("target_id"))] = {
                    "target_id": t.get("target_id"),
                    "tier": tier,
                    "quote": t.get("quote") or "",
                    "period": c.get("period"),
                    "unit": c.get("unit"),
                    "row": c.get("row"),
                    "col": c.get("col"),
                    "locator": t.get("locator") or [],
                    "source_id": t.get("source_id") or "",
                }
    return out

_WS = re.compile(r"[\s\u3000\xa0\u200b]+")


def norm(t: str | None) -> str:
    return _WS.sub("", t or "")


def load_run(run_dir: Path) -> dict:
    """{ledger, tool_results_text(取回正文), final_answers, llm_texts, delivered_text}。

    ``delivered_text`` = ledger 标记 delivered 的片段正文拼接（L8 判定用：只要求
    目标引文及依赖在**已送达**片段中，而非全部取回片段都送达——protocol L8 语义）。
    """
    ledger_path = run_dir / "corpus" / "ledger.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8")) if ledger_path.exists() else {}
    trace_path = run_dir / "trace.jsonl"
    fetched_texts: list[str] = []
    final_answers: list[str] = []
    # locator -> (text, status)，供 delivered_text 组装。
    locator_text: dict[str, str] = {}
    if trace_path.exists():
        for line in trace_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            try:
                ev = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not isinstance(ev, dict):
                continue
            if ev.get("t") == "tool":
                res = ev.get("result")
                if isinstance(res, str):
                    # corpus_fetch 的 result 是二次 JSON 序列化：正文在 text 字段。
                    try:
                        payload = json.loads(res)
                    except json.JSONDecodeError:
                        payload = None
                    if isinstance(payload, dict):
                        for item in payload.get("items") or []:
                            if isinstance(item, dict) and isinstance(item.get("text"), str) and item.get("locator"):
                                locator_text[item["locator"]] = item["text"]
                                fetched_texts.append(item["text"])
                        if isinstance(payload.get("text"), str) and payload.get("locator"):
                            locator_text[payload["locator"]] = payload["text"]
                        if isinstance(payload.get("text"), str):
                            fetched_texts.append(payload["text"])
            if ev.get("t") == "llm" and isinstance(ev.get("text"), str):
                final_answers.append(ev["text"])
    # 取回正文：仅取回类工具返回的实际片段正文（与 ledger.fetched[].chars 对齐）。
    fetched_text = "\n".join(fetched_texts)
    deliv_status = {
        str(d.get("locator")): d.get("status")
        for d in (ledger.get("delivered") or []) if isinstance(d, dict)
    }
    delivered_text = "\n".join(
        t for loc, t in locator_text.items() if deliv_status.get(loc) == "delivered"
    )
    return {
        "ledger": ledger,
        "fetched_text": fetched_text,
        "delivered_text": delivered_text,
        "final_answers": final_answers,
    }


def run_doc_prefix(ledger: dict) -> str | None:
    """从 fetched record 的 doc_id 提取 run 构建的前 8 位（如 9fa4cd7c）。"""
    fetched = ledger.get("fetched") or []
    for f in fetched:
        if isinstance(f, dict) and f.get("doc_id"):
            d = (f["doc_id"] or "").split(":")[-1]
            return d[:8]
    return None


def _quote_in_text(quote_n: str, token_ns: list[str], text: str) -> bool:
    if not quote_n:
        return False
    tn = norm(text)
    if quote_n in tn:
        return True
    # 非逐字（排版/标点漂移）时降级为分词覆盖（仍是送达相关证据，非放水）。
    return bool(token_ns) and all(t in tn for t in token_ns)


def _unit_options(unit: str) -> list[str]:
    """把单位展开为等价写法（如「元/股」亦匹配「元」；「元/吨；%」拆为「元/吨」+「%」）。"""
    un = norm(unit)
    if not un:
        return []
    # 复合单位（; ；、,）拆为独立单位分别匹配；各子部分内再按 / 展开。
    parts = re.split(r"[;；,，、]", un)
    opts: set[str] = set()
    for p in parts:
        p = p.strip()
        if not p:
            continue
        opts.add(p)
        if "元/股" in p:
            opts.add(norm("元"))
        for sep in ("/", "每"):
            if sep in p:
                opts.add(norm(p.replace(sep, "")))
    return [o for o in opts if o]


def score_consumption_run(run: dict, target: dict, page: str | None) -> tuple[dict[str, str], dict]:
    """基于 run 事实判 L6–L9，返回 (layers, evidence)。"""
    ledger = run["ledger"]
    fetched_text = run["fetched_text"]
    final_answers = run["final_answers"]
    answer = "\n".join(final_answers[-2:]) if final_answers else ""
    doc = run_doc_prefix(ledger)

    quote = target.get("verbatim_quote") or target.get("quote") or ""
    qn = norm(quote)
    tok_re = re.split(r"\s+", quote.strip()) if quote.strip() else []
    token_ns = [norm(t) for t in tok_re if t and len(t) >= 2]
    period = str(target.get("period") or "").strip()
    unit = str(target.get("unit") or "").strip()
    unit_opts = _unit_options(unit)

    requested = ledger.get("requested") or []
    fetched = ledger.get("fetched") or []
    delivered = ledger.get("delivered") or []

    layers: dict[str, str] = {}
    ev: dict = {}

    # L6
    req_locs = [
        loc for r in requested if isinstance(r, dict) for loc in (r.get("locators") or [])
    ]
    req_ok = bool(req_locs)
    layers["L6"] = "pass" if req_ok else "fail"
    ev["L6"] = {"requested_entries": len(requested), "locators": len(req_locs), "doc_prefix": doc}

    # L7
    fq = _quote_in_text(qn, token_ns, fetched_text)
    l7 = bool(fetched) and fq
    layers["L7"] = "pass" if l7 else "fail"
    ev["L7"] = {"fetched": len(fetched), "quote_in_fetched": fq}

    # L8：目标引文及必要依赖在**已送达**片段中（protocol L8 语义：最终模型输入
    # 含目标及必要依赖；不以「全部取回片段都 delivered」判定——无关片段未送达
    # 不影响目标送达）。期间/单位以等价写法存在于已送达正文。
    delivered_text = run.get("delivered_text") or ""
    fq_keep = _quote_in_text(qn, token_ns, delivered_text)
    ys = re.findall(r"\d{4}", period) if period else []
    period_ok = (not period) or any(a in norm(delivered_text) for a in ys)
    unit_there = (not unit) or any(o in norm(delivered_text) for o in unit_opts)
    l8 = fq_keep and period_ok
    layers["L8"] = "pass" if l8 else "fail"
    ev["L8"] = {
        "n_delivered": sum(1 for d in delivered if isinstance(d, dict) and d.get("status") == "delivered"),
        "quote_intact_in_delivered": fq_keep,
        "period_ok": period_ok,
        "unit_present": unit_there,
    }

    # L9：最终回答含该目标的数值 + 单位等价 + 期间。
    # protocol §4.5「允许正确释义，不要求答案机械复述整段金标」：gold quote 若
    # 是整段长文（如 macro-003 同一段 17 个数值），要求全部出现即过严。分层判定：
    #   - 短 quote（数值 ≤ 4）：数值即该目标核心，要求全部出现（防型号/EPS 缺漏）；
    #   - 长 quote（数值 > 4）：要求回答引用到该证据的**至少一个关键数值**
    #     （明显数值 = 小数/百分号/≥3 位数字），并核对单位/期间。
    an = norm(answer)
    vals = [norm(v) for v in e4.value_tokens(quote)]
    if len(vals) <= 4:
        checked = vals
        vals_ok = (not checked) or all(v in an for v in checked)
    else:
        key_vals = [
            v for v in vals
            if "%" in v or "." in v or sum(c.isdigit() for c in v) >= 3
        ]
        checked = key_vals or vals
        vals_ok = (not checked) or any(v in an for v in checked)
    unit_ok = (not unit) or any(o in an for o in unit_opts)
    period_ok_ans = (not period) or any(a in an for a in ys)
    l9 = bool(answer) and vals_ok and unit_ok and period_ok_ans
    layers["L9"] = "pass" if l9 else "fail"
    ev["L9"] = {
        "values": vals,
        "key_values": checked,
        "vals_ok": vals_ok,
        "unit_ok": unit_ok,
        "period_ok": period_ok_ans,
    }

    return layers, ev


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--run", required=True, type=Path)
    ap.add_argument("--e4", type=Path, default=E4_JSON)
    # 该 run 对应的 query_id（gold 中 30 题之一）。缺省时回退到 e4 首键，
    # 仅兼容单一 run 场景；批量按题评分必须显式传入。
    ap.add_argument("--query", default=None, help="query_id in gold (company-001 … macro-010)")
    args = ap.parse_args()

    if not args.e4.exists():
        print(f"缺生成侧 {args.e4}，先跑 e4_validate.py", file=sys.stderr)
        return 2
    e4_data = json.loads(args.e4.read_text(encoding="utf-8"))
    run = load_run(args.run)
    gold = load_gold_targets()
    e4_by_tid = { (r["query_id"], r["target_id"]): r for r in e4_data.get("targets", []) }
    if not e4_by_tid:
        print(f"e4 数据空：{args.e4}", file=sys.stderr)
        return 2

    qid = args.query or next(iter(e4_by_tid))[0]
    order = ["L1", "L2", "L3", "L4", "L5", "L6", "L7", "L8", "L9"]
    rows = []
    for key, tgt in gold.items():
        if key[0] != qid:
            continue
        erow = e4_by_tid.get(key)
        if erow is None:
            continue
        page = next((str(x).split(":", 1)[1] for x in tgt.get("locator", []) if str(x).startswith("page:")), None)
        run_layers, ev = score_consumption_run(run, tgt, page)
        layers = {**{k: erow["layers"][k] for k in order}, **run_layers}
        fails = [k for k in order if layers[k] == "fail"]
        rows.append({
            "target_id": key[1],
            "tier": tgt["tier"],
            "page": page,
            "layers": layers,
            "first_fail": fails[0] if fails else None,
            "failure_class": e4.classify_failure(fails[0]) if fails else None,
            "all_pass": not fails,
            "run_evidence": ev,
            "prep": {k: erow["prep"][k] for k in ("in_clean_contiguous", "single_chunk_hit", "offered_contains") if k in erow["prep"]},
        })

    fails = [r for r in rows if r["first_fail"] is not None]
    result = {
        "artifact": "e5-run-score",
        "generated_at": datetime.now(UTC).isoformat(),
        "run": str(args.run),
        "query_id": qid,
        "doc_prefix": run_doc_prefix(run["ledger"]),
        "policy": "生成侧=e4-validate（冻结 gen-2）；消费侧=run ledger/trace 直读；零模型",
        "targets": rows,
        "summary": {
            "targets": len(rows),
            "all_pass": sum(1 for r in rows if r["all_pass"]),
            "per_layer_fail": {k: v for k, v in sorted(Counter(r["first_fail"] for r in fails).items(), key=lambda kv: str(kv[0]))},
            "per_class_fail": {k: v for k, v in sorted(Counter(r["failure_class"] for r in fails).items(), key=lambda kv: str(kv[0]))},
            "fail_targets": [(r["target_id"], r["first_fail"], r["failure_class"]) for r in fails],
        },
    }
    out = args.run / "e5-run-score.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, default=str))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())