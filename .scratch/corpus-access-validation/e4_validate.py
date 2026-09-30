"""E4 开发集集成验证驱动：对冻结 gen-2 活跃 build 落 L1–L9 分层矩阵。

零模型（B0 import 陷阱）、只读 PG（仅 SELECT）。复用 B0/B1 归因器承载
L1–L4 的一部分（reader 提取、单块、offered），另直读 ``corpus_units.clean_view``
得到 **clean 视图**，从而把 L2（reader 提取）与 L3（clean 保留）真正分开
（B0 只读 reader 原文，无法判别误清洗，这是 E4 相对它的关键增量）。

产物：``e4-validate.json`` —— 99 target 的 L1–L9 矩阵、逐类缺陷命中示例
（真实 a-1 → L5 边界 + 确定性自检五类合成命中）、综合结论。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
GOLD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"
B0_JSON = ROOT / ".scratch/b0-attribution-20260928/b0_attribution.json"
FROZEN_JSON = ROOT / ".scratch/b4-candidate-20260929/e5-freeze-result.json"

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# 复用 B1 模块（其 b0 属性装载了零模型 import 陷阱与环境）。
spec = importlib.util.spec_from_file_location(
    "b1_comparison", ROOT / ".scratch/b1-comparison-20260929/b1_comparison.py"
)
b1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1)
b0 = b1.b0

# 纯评分核心（无 DB 依赖），以模块方式装载避免污染顶层 import 排序。
spec_e4 = importlib.util.spec_from_file_location("e4_scorer", OUT / "e4_scorer.py")
e4 = importlib.util.module_from_spec(spec_e4)
spec_e4.loader.exec_module(e4)

import psycopg  # noqa: E402

from plugins.corpus.service import dsn  # noqa: E402

# a-1 为已裁决的已知边界：引文跨 unit 5/6（左右栏 bbox 不相交），chunk-5 R2-a
# 守卫按设计拒绝合并约束。它在生成侧命中 L4/L5（单块/offered）fail，属已知边界
# 而非回归，登记表并单独标注，不进入"未处理缺陷"。
KNOWN_BOUNDARY = {("company-008", "a-1")}


def e4_views(conn: psycopg.Connection, build_id: str) -> tuple[str, str]:
    """读该 build 的 reader 视图拼接与 clean 视图拼接。

    ``corpus_units.raw_text`` = reader（清洗前）；``clean_view`` = clean 后文本
    （``None`` 视为被清除，不计入 clean 拼接）。
    """
    rows = conn.execute(
        "SELECT raw_text, clean_view FROM corpus.corpus_units WHERE build_id=%s ORDER BY ordinal",
        (build_id,),
    ).fetchall()
    reader_parts: list[str] = []
    clean_parts: list[str] = []
    for raw, cv in rows:
        if raw:
            reader_parts.append(b0.norm(raw))
        if cv:
            clean_parts.append(b0.norm(cv))
    return "".join(reader_parts), "".join(clean_parts)


def _tokens(quote: str) -> list[str]:
    return [b0.norm(t) for t in re.split(r"\s+", quote.strip()) if t and len(t) >= 2]


def main() -> None:
    baseline = json.loads(B0_JSON.read_text(encoding="utf-8"))
    gold = b0.load_gold()
    queries = baseline["queries"]

    gold_source_ids = {
        t["source_id"]
        for row in gold
        for t in (row.get("evidence_targets") or [])
        + (row.get("supplementary_evidence_targets") or [])
    }

    with psycopg.connect(dsn()) as conn:
        conn.execute("SET default_transaction_read_only=on")
        ro = conn.execute("SHOW transaction_read_only").fetchone()[0]
        assert ro == "on", f"transaction_read_only={ro!r}"
        db = conn.execute("SELECT current_database()").fetchone()[0]
        resolved = b0.resolve_sources(conn, gold_source_ids)

    artifacts: dict[str, dict] = {}
    clean_norms: dict[str, str] = {}
    for _gid, info in resolved.items():
        full = info["corpus_source_id"]
        if full is None:
            continue
        with psycopg.connect(dsn()) as conn:
            conn.execute("SET default_transaction_read_only=on")
            art = b0.load_source_artifacts(conn, info["build_id"])
            _, clean_norm = e4_views(conn, info["build_id"])
        art["_resolved"] = info
        artifacts[full] = art
        clean_norms[full] = clean_norm

    hits = b1.offered_hits_for_new(queries, artifacts)

    score_rows: list[dict] = []
    for row in gold:
        qid = row["query_id"]
        for tier, key in (
            ("required", "evidence_targets"),
            ("supplementary", "supplementary_evidence_targets"),
        ):
            for t in row.get(key) or []:
                gid = t["source_id"]
                full = resolved.get(gid, {}).get("corpus_source_id")
                art = artifacts.get(full)
                quote = t.get("quote") or ""
                qn = b0.norm(quote)
                toks = _tokens(quote)
                if art is None:
                    prep = {
                        "source_present": True,
                        "in_reader_contiguous": False,
                        "reader_tokens_present": False,
                        "in_clean_contiguous": False,
                        "clean_tokens_present": False,
                        "single_chunk_hit": False,
                        "offered_contains": False,
                    }
                    attr_code = "source_unresolved"
                else:
                    rec = b0.attr_target(t, tier == "supplementary", qid, art, hits[qid])
                    attr_code = rec["primary_code"]
                    flags = rec.get("flags", {})
                    reader_norm = art["doc_norm"]
                    clean_norm = clean_norms[full]
                    prep = {
                        "source_present": True,
                        "in_reader_contiguous": bool(qn and qn in reader_norm),
                        "reader_tokens_present": bool(toks)
                        and all(tk in reader_norm for tk in toks),
                        "has_reader_tokens": bool(toks),
                        "in_clean_contiguous": bool(qn and qn in clean_norm),
                        "clean_tokens_present": bool(toks) and all(tk in clean_norm for tk in toks),
                        "single_chunk_hit": bool(flags.get("in_single_chunk_any")),
                        "offered_contains": bool(flags.get("quote_in_offered_chunk")),
                    }
                target_spec = {
                    "target_id": t.get("target_id"),
                    "verbatim_quote": quote,
                    "quote": quote,
                    "period": (t.get("constraints") or {}).get("period"),
                    "unit": (t.get("constraints") or {}).get("unit"),
                    "row": (t.get("constraints") or {}).get("row"),
                    "col": (t.get("constraints") or {}).get("col"),
                }
                verdict = e4.score_target(target_spec, prep, None)  # 无 run 记录 → 消费层 n/a
                score_rows.append(
                    {
                        "query_id": qid,
                        "target_id": t.get("target_id"),
                        "tier": tier,
                        "source_id": gid,
                        "frozen_code": attr_code,
                        "known_boundary": (qid, t.get("target_id")) in KNOWN_BOUNDARY,
                        "prep": prep,
                        **verdict,
                    }
                )

    layer_fails = Counter(ln for r in score_rows for ln in (r["first_fail"],) if ln is not None)
    class_fails = Counter(r["failure_class"] for r in score_rows if r["failure_class"])
    real_unhandled = [
        {
            k: r[k]
            for k in ("query_id", "target_id", "first_fail", "failure_class", "known_boundary")
        }
        for r in score_rows
        if r["first_fail"] is not None and not r["known_boundary"]
    ]
    # 已知边界（生成侧）单独成组，不解释为回归。
    boundaries = [
        {k: r[k] for k in ("query_id", "target_id", "frozen_code", "first_fail", "failure_class")}
        for r in score_rows
        if r["known_boundary"] and r["first_fail"] is not None
    ]

    autocheck = e4.self_check()
    ok_self = all(c["ok"] for c in autocheck)

    result = {
        "artifact": "e4-validate",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "E4 分层评分器开发集集成验证：冻结 gen-2 build L1–L9 矩阵",
        "policy": {
            "gold": str(GOLD.relative_to(ROOT)),
            "consumption": "消费层（L6–L9）本次无 run 记录 → n/a；由 self_check 与单测证明可判",
            "clean_view_source": "corpus_units.clean_view 直读（区分 L2 reader / L3 clean）",
            "offered_rule": "复用 B0 检索命中映射（B4/B1 同款受控假设）",
            "isolation": "评分侧证据（verbatim_quote/period/unit）只作输入；执行侧不可读本目录",
        },
        "summary": {
            "targets": len(score_rows),
            "all_pass": sum(1 for r in score_rows if r["all_pass"]),
            "first_fail_dist": {k: v for k, v in sorted(layer_fails.items())},
            "class_dist": {k: v for k, v in sorted(class_fails.items())},
            "real_unhandled_generation_side": real_unhandled,
            "known_boundary": boundaries,
            "self_check_pass": ok_self,
            "self_check": autocheck,
        },
        "targets": score_rows,
    }
    (OUT / "e4-validate.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(dsn(), "<REDACTED>"),
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2, default=str))
    print(
        "RO",
        ro,
        "DB",
        db,
        "MODELS_ABSENT",
        not any(x in sys.modules for x in ("openai", "anthropic")),
    )


if __name__ == "__main__":
    main()
