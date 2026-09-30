"""E5 金标评分（#1 收尾）：对已冻结的 gen-2 活跃 build 重跑金标检索命中验证。

区别 b4_candidate.py：不内存重读归档重算，而是直接读生产 PG 的**冻结 build**
（``corpus_publications.active_build_id``，E5 冻结后 = gen-2 reader-pdf-9 栈）的
权威单元/chunk，经 B0/B1 的 attr_target 判定链路计算每条引文 primary_code。

零模型（B0 import 陷阱）、只读 PG（仅 SELECT）。offered 判定复用 B0 检索命中映射
（与 B4/B1 同款受控假设）。

产物：e5-gold-score.json（target 级判定 + 与 base/B0 的转移 + NOISE 残留 + 关键面）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
GOLD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"
B0_JSON = ROOT / ".scratch/b0-attribution-20260928/b0_attribution.json"
FROZEN_JSON = OUT / "e5-freeze-result.json"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

spec = importlib.util.spec_from_file_location(
    "b1_comparison", ROOT / ".scratch/b1-comparison-20260929/b1_comparison.py"
)
b1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1)
b0 = b1.b0

import psycopg  # noqa: E402

from plugins.corpus.service import dsn  # noqa: E402

# NOISE 残留三条：引文跨过的单元在冻结 build 的 clean 台账必须全部 kept（B0 形状不携带
# status，这里仅复核 in_concat + 跨单元；kept 判定由 §5.6 单元台账独立闭环）。
NOISE_RESIDUAL = {("company-007", "e1"), ("company-007", "e2"), ("company-008", "a-1")}


def main() -> None:
    baseline = json.loads(B0_JSON.read_text(encoding="utf-8"))
    frozen = json.loads(FROZEN_JSON.read_text(encoding="utf-8"))
    gold = b0.load_gold()
    base_by_target = {
        (t.get("query_id"), t.get("target_id")): t for t in baseline["targets"]
    }
    queries = baseline["queries"]
    # 冻结执行记录：corpus_source_id -> frozen build_id（证明所评即所冻结）。
    frozen_build_by_src = {
        s["source_id"]: s["build_id"] for s in frozen["sources"]
    }

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
        resolved = b0.resolve_sources(conn, gold_source_ids)

    # 冻结 artifacts：production 活跃 build（应为 gen-2）。
    artifacts: dict[str, dict] = {}
    build_match: dict[str, bool] = {}
    for gid, info in resolved.items():
        full = info["corpus_source_id"]
        if full is None:
            continue
        build_match[gid] = info["build_id"] == frozen_build_by_src.get(full)
        with psycopg.connect(dsn()) as conn:
            conn.execute("SET default_transaction_read_only=on")
            art = b0.load_source_artifacts(conn, info["build_id"])
        art["_resolved"] = info
        artifacts[full] = art

    hits = b1.offered_hits_for_new(queries, artifacts)

    target_rows: list[dict] = []
    for row in gold:
        qid = row["query_id"]
        for tier, key in (
            ("required", "evidence_targets"),
            ("supplementary", "supplementary_evidence_targets"),
        ):
            for t in row.get(key) or []:
                gid = t["source_id"]
                full = resolved.get(gid, {}).get("corpus_source_id")
                base = base_by_target.get((qid, t.get("target_id")))
                base_code = base["primary_code"] if base else None
                art = artifacts.get(full) if full else None
                if art is None:
                    code, flags = "source_unresolved", {}
                else:
                    rec = b0.attr_target(t, tier == "supplementary", qid, art, hits[qid])
                    code = rec["primary_code"]
                    flags = rec.get("flags", {})
                row_out = {
                    "query_id": qid,
                    "target_id": t.get("target_id"),
                    "tier": tier,
                    "source_id": gid,
                    "base_code": base_code,
                    "frozen_code": code,
                    "flags": {
                        k: v
                        for k, v in flags.items()
                        if k
                        in (
                            "in_concat",
                            "in_single_chunk_any",
                            "table_has_cell_coords",
                            "structure_reason",
                            "page_hint",
                            "tokens_present",
                        )
                    },
                }
                target_rows.append(row_out)

    recovered_vs_base = [
        (r["query_id"], r["target_id"])
        for r in target_rows
        if r["base_code"] == "chunking_impact" and r["frozen_code"] == "ok"
    ]
    still_not_ok = [
        (r["query_id"], r["target_id"], r["source_id"], r["frozen_code"], r["flags"])
        for r in target_rows
        if r["frozen_code"] != "ok"
    ]
    all_ok = all(r["frozen_code"] == "ok" for r in target_rows)

    result = {
        "artifact": "e5-gold-score",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "E5 frozen gen-2 build gold retrieval re-check (zero model, read-only PG)",
        "policy": {
            "gold": str(GOLD.relative_to(ROOT)),
            "scored_on": "corpus_publications.active_build_id（gen-2 reader-pdf-9→clean-4→chunk-5）",
            "artifact_source": "b0.load_source_artifacts 直读生产 PG 权威单元/chunk（非内存重算）",
            "offered_rule": "复用 B0 检索命中；命中文档 offered 覆盖其全部新块（B0 结构结论）",
        },
        "build_match": build_match,
        "targets": target_rows,
        "summary": {
            "targets": len(target_rows),
            "all_ok": all_ok,
            "base_codes": {
                k: v for k, v in Counter(r["base_code"] for r in target_rows).items()
            },
            "frozen_codes": {
                k: v for k, v in Counter(r["frozen_code"] for r in target_rows).items()
            },
            "chunking_impact_recovered_to_ok": recovered_vs_base,
            "frozen_not_ok": still_not_ok,
            "noise_residual_in_concat": [
                {
                    "target": f"{r['query_id']}:{r['target_id']}",
                    "in_concat": r["flags"].get("in_concat"),
                    "in_single_chunk_any": r["flags"].get("in_single_chunk_any"),
                }
                for r in target_rows
                if (r["query_id"], r["target_id"]) in NOISE_RESIDUAL
                and r["flags"].get("in_concat") is not None
            ],
        },
    }
    (OUT / "e5-gold-score.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(
            dsn(), "<REDACTED>"
        ),
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print("BUILD_MATCH", build_match)
    print("RO", ro, "MODELS_ABSENT", not any(x in sys.modules for x in ("openai", "anthropic")))


if __name__ == "__main__":
    main()