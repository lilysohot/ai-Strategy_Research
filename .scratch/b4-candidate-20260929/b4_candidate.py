"""E3 候选 build 分项对照（B4 门槛）：候选栈 reader-pdf-8 → clean-4 → chunk-5
相对基线（B0）与上一组合档（B4 ``b1b3`` = reader-pdf-7 → clean-3 → chunk-4）的
target 级归因对比。

目的（`e3-defect-register.md` §5.5 实施顺序「重建候选语料 → B4 分项对照」）：

- **chunking_impact 20 条恢复且 0 回归**：17 条 chunk 规则恢复（b1b3 已证）+ e1/e2
  （clean-1 句子游程）+ a-1（clean-1 首现豁免，单块命中受 R2-a 守卫约束，另行裁决）；
- **NOISE 0 残留**：三条 gold 引文（company-007 e1/e2、company-008 a-1）不再位于
  NOISE 单元——逐条核对引文跨过的单元在候选 clean 台账中的状态；
- **S1–S4 结构缺陷修复**：reader-pdf-8 后 structure_error → ok（cells 坐标恢复 +
  续表行序恢复），且 company-003（dddc7cd0）page 20 对照不回归；
- **无新错误**：ok → 非 ok 为 0、相对基线 0 字符丢失、旧单元仍为新文档连续子串。

**隔离保证（B4.3 同款）**：零模型（沿用 B0 import 陷阱）、只读 PG（旧 artifacts 只
SELECT，不写任何行）、候选 artifacts 纯 Python 内存重建（不改归档、不建索引、不发布）。
offered 判定复用 B0 保存的检索命中（``hits_by_source``）：命中来源 offered 覆盖其
全部新块（B0 结构结论，与 B1/B4 相同的受控假设）。

产物：``b4-candidate-comparison.json``（对照明细 + a-1 裁决证据）。
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
B4_JSON = ROOT / ".scratch/b4-combined-20260929/b4-combined-comparison.json"
# 6 来源的归档副本（i3-1 e2e 审计固定归档；生产 data/corpus-archive 无此批次）。
ARCHIVE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/archive"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# 复用 B1 脚本（其模块级代码装载 B0 的零模型 import 陷阱、.env、PGOPTIONS 只读；
# 并把 clean/chunk/readers 模块装进 sys.modules）。b1.build_new_artifacts 断言
# reader-pdf-7，候选档须断言 reader-pdf-8，故不调用，仅复用其 offered 映射。
spec = importlib.util.spec_from_file_location(
    "b1_comparison", ROOT / ".scratch/b1-comparison-20260929/b1_comparison.py"
)
b1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1)
b0 = b1.b0

import psycopg  # noqa: E402

from plugins.corpus.preparation.chunk import CHUNK_REV, chunk_clean_result  # noqa: E402
from plugins.corpus.preparation.clean import CLEAN_REV, clean_reader_result  # noqa: E402
from plugins.corpus.preparation.readers import read_document  # noqa: E402
from plugins.corpus.service import dsn  # noqa: E402

LOCATOR_PREFIX = "b4cand-0000000000000000"

# NOISE 残留三条（e3-defect-register.md §2）：引文必须不再位于 NOISE 单元。
NOISE_RESIDUAL = {("company-007", "e1"), ("company-007", "e2"), ("company-008", "a-1")}
# a-1 裁决证据目标（R2-a 张力：标题+评级左右栏并排）。
ADJUDICATE = {("company-008", "a-1")}


def norm(text: str) -> str:
    return b0.norm(text)


def build_candidate_artifacts(path: Path, source_id: str, active_build_id: str) -> dict:
    """归档副本 → reader-pdf-8 → clean-4 → chunk-5 → B0 形状 artifacts（纯内存）。

    与 b1.build_new_artifacts 同形，另断言候选栈 identity 并捕获每单元 clean
    状态（NOISE 残留核对需要台账，而 B0 形状不携带 status）。
    """
    reader_result = read_document(path)
    assert "reader-pdf-9" in reader_result.extractor_rev, reader_result.extractor_rev
    clean = clean_reader_result(reader_result)
    assert clean.clean_rev == CLEAN_REV, (clean.clean_rev, CLEAN_REV)
    chunk_result = chunk_clean_result(reader_result, clean)
    assert chunk_result.chunk_rev == CHUNK_REV, (chunk_result.chunk_rev, CHUNK_REV)

    status_by_ordinal = {
        r.ordinal: r.status.value for r in clean.regions if r.ordinal is not None
    }
    unit_rows: list[dict] = []
    for u in sorted(reader_result.units, key=lambda u: u.ordinal):
        unit_rows.append(
            {
                "ordinal": u.ordinal,
                "unit_id": f"unit:{u.ordinal:04d}",
                "page": str(u.location.page) if u.location.page is not None else None,
                "n_cells": len(u.location.cells or ()),
                "element": u.location.element,
                "bbox": list(u.location.bbox) if u.location.bbox else None,
                "status": status_by_ordinal.get(u.ordinal),
                "raw": u.raw_text,
                "norm": norm(u.raw_text),
            }
        )
    by_unit = {u["unit_id"]: u for u in unit_rows}
    unit_id_by_ordinal = {u["ordinal"]: u["unit_id"] for u in unit_rows}

    chunk_rows: list[dict] = []
    for candidate in chunk_result.chunks:
        refs = [unit_id_by_ordinal[o] for o in candidate.unit_ordinals if o in unit_id_by_ordinal]
        refs = list(
            dict.fromkeys(
                [
                    *refs,
                    *[unit_id_by_ordinal[o] for o in candidate.context_refs if o in unit_id_by_ordinal],
                ]
            )
        )
        text = "\n".join(by_unit[u]["raw"] for u in refs if u in by_unit)
        chunk_rows.append(
            {
                "chunk_id": f"{LOCATOR_PREFIX}:{candidate.key}",
                "kind": candidate.kind,
                "title": candidate.title_text,
                "unit_refs": refs,
                "pages": sorted(
                    {by_unit[u]["page"] for u in refs if u in by_unit and by_unit[u]["page"]}
                ),
                "text": text,
                "norm": norm(text),
            }
        )
    unit_kinds: dict[str, list[str]] = {}
    for c in chunk_rows:
        for uid in c["unit_refs"]:
            unit_kinds.setdefault(uid, []).append(c["kind"])
    concat_parts: list[str] = []
    spans: list[tuple[str, str, int, int]] = []
    offset = 0
    for u in unit_rows:
        spans.append((u["unit_id"], u["page"], offset, offset + len(u["norm"])))
        offset += len(u["norm"])
        concat_parts.append(u["norm"])
    return {
        "units": unit_rows,
        "chunks": chunk_rows,
        "chunk_by_locator": {f"chunk:{c['chunk_id']}": c for c in chunk_rows},
        "doc_norm": "".join(concat_parts),
        "unit_spans": spans,
        "unit_kinds": unit_kinds,
        "units_with_cells": sum(1 for u in unit_rows if u["n_cells"] > 0),
        "_resolved": {"corpus_source_id": source_id, "build_id": active_build_id},
    }


def doc_row_for(new: dict, old: dict, source_id: str, gold_source_id: str) -> dict:
    """文档级对照（相对基线，镜像 b4_combined.doc_row_for）。"""
    old_norm = old["doc_norm"]
    new_norm = new["doc_norm"]
    old_missing = Counter(ch for ch in old_norm if old_norm.count(ch) > new_norm.count(ch))
    new_missing = Counter(ch for ch in new_norm if new_norm.count(ch) > old_norm.count(ch))
    old_unit_substr_missing = [
        u["unit_id"] for u in old["units"] if u["norm"] and u["norm"] not in new_norm
    ]
    old_chunk_broken = [
        c["chunk_id"] for c in old["chunks"] if c["norm"] and c["norm"] not in new_norm
    ]
    kind_hist = Counter(c["kind"] for c in new["chunks"])
    return {
        "source_id": source_id,
        "gold_source_id": gold_source_id,
        "old_units": len(old["units"]),
        "new_units": len(new["units"]),
        "old_chunks": len(old["chunks"]),
        "new_chunks": len(new["chunks"]),
        "kind_hist": {k: v for k, v in sorted(kind_hist.items())},
        "old_doc_norm_chars": len(old_norm),
        "new_doc_norm_chars": len(new_norm),
        "chars_lost_vs_old": sum(old_missing.values()),
        "chars_gained_vs_old": sum(new_missing.values()),
        "old_unit_not_contiguous_in_new": old_unit_substr_missing,
        "old_chunk_not_contiguous_in_new": old_chunk_broken,
    }


def noise_residual_check(
    target: dict, art: dict, quote_norm: str
) -> dict:
    """NOISE 残留核对：引文跨过的单元在候选 clean 台账中的状态必须全部 kept。"""
    crossed = b0.crossed_units(art, quote_norm)
    unit_by_id = {u["unit_id"]: u for u in art["units"]}
    details = []
    for c in crossed:
        u = unit_by_id.get(c["unit_id"], {})
        details.append(
            {
                "unit_id": c["unit_id"],
                "page": c["page"],
                "status": u.get("status"),
                "n_cells": u.get("n_cells"),
                "bbox": u.get("bbox"),
                "chunk_kinds": c["chunk_kinds"],
                "raw_head": (u.get("raw") or "")[:40],
            }
        )
    return {
        "in_concat": bool(quote_norm) and quote_norm in art["doc_norm"],
        "crossed_units": details,
        "all_crossed_kept": bool(details) and all(d["status"] == "kept" for d in details),
        "noise_crossed": [d["unit_id"] for d in details if d["status"] == "noise"],
    }


def main() -> None:
    baseline = json.loads(B0_JSON.read_text(encoding="utf-8"))
    b4_result = json.loads(B4_JSON.read_text(encoding="utf-8"))
    gold = b0.load_gold()
    base_by_target = {
        (t.get("query_id"), t.get("target_id")): t for t in baseline["targets"]
    }
    b4_by_target = {
        (t.get("query_id"), t.get("target_id")): t for t in b4_result["targets"]
    }
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
        resolved = b0.resolve_sources(conn, gold_source_ids)
        old_artifacts: dict[str, dict] = {}
        for gid, info in resolved.items():
            if info["build_id"]:
                art = b0.load_source_artifacts(conn, info["build_id"])
                art["_resolved"] = info
                old_artifacts[gid] = art
        sid_to_archive: dict[str, str] = {}
        for gid in gold_source_ids:
            full = resolved[gid]["corpus_source_id"]
            if full is None:
                continue
            row = conn.execute(
                "SELECT archive_path, format FROM corpus.corpus_sources WHERE source_id=%s",
                (full,),
            ).fetchone()
            if row is not None:
                sid_to_archive[full] = row[0]

    # ── 候选 artifacts（连接外构建：纯内存，不占 PG 会话） ──
    candidate_artifacts: dict[str, dict] = {}
    for gid, info in resolved.items():
        full = info["corpus_source_id"]
        if full is None or full not in sid_to_archive:
            continue
        path = ARCHIVE / sid_to_archive[full]
        if not path.exists():
            raise FileNotFoundError(f"归档副本缺失: {path}")
        candidate_artifacts[full] = build_candidate_artifacts(path, full, info["build_id"])

    hits = b1.offered_hits_for_new(queries, candidate_artifacts)

    # ── target 级归因（候选 vs base vs b1b3） ──
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
                b4row = b4_by_target.get((qid, t.get("target_id")))
                base_code = base["primary_code"] if base else None
                b1b3_code = b4row.get("b1b3_code") if b4row else base_code
                art = candidate_artifacts.get(full) if full else None
                if art is None:
                    cand_code, flags = "source_unresolved", {}
                else:
                    rec = b0.attr_target(t, tier == "supplementary", qid, art, hits[qid])
                    cand_code = rec["primary_code"]
                    flags = rec.get("flags", {})
                row_out = {
                    "query_id": qid,
                    "target_id": t.get("target_id"),
                    "tier": tier,
                    "source_id": gid,
                    "base_code": base_code,
                    "b1b3_code": b1b3_code,
                    "candidate_code": cand_code,
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
                        )
                    },
                }
                # NOISE 残留三条 + a-1 裁决：附单元台账核对
                if (qid, t.get("target_id")) in (NOISE_RESIDUAL | ADJUDICATE) and art is not None:
                    quote_norm = norm(t.get("quote") or "")
                    row_out["noise_residual_check"] = noise_residual_check(t, art, quote_norm)
                target_rows.append(row_out)

    transitions = {
        pair: Counter((r["base_code"], r[pair]) for r in target_rows)
        for pair in ("b1b3_code", "candidate_code")
    }
    transitions["candidate_vs_b1b3"] = Counter(
        (r["b1b3_code"], r["candidate_code"]) for r in target_rows
    )

    # ── 文档级对照（相对基线） ──
    doc_rows: list[dict] = []
    for gid, info in resolved.items():
        full = info["corpus_source_id"]
        old = old_artifacts.get(gid)
        if full is None or old is None or full not in candidate_artifacts:
            continue
        doc_rows.append(doc_row_for(candidate_artifacts[full], old, full, gid))

    result = {
        "artifact": "b4-candidate-comparison",
        "version": 1,
        "generated_at": datetime.now(UTC).isoformat(),
        "scope": "E3 candidate build comparison: reader-pdf-8 + clean-4 + chunk-5 vs base/B4-b1b3, zero model, read-only PG, no publish",
        "policy": {
            "gold": str(GOLD.relative_to(ROOT)),
            "variants": {
                "base": "B0 活动 build（reader-pdf-6 时代，chunk-3），b0_attribution.json",
                "b1b3": "B4 组合档：reader-pdf-7 → clean-3 → chunk-4（b4-combined-comparison.json）",
                "candidate": "候选栈：reader-pdf-8 → clean-4 → chunk-5（当前代码，归档副本重读，纯内存）",
            },
            "offered_rule": "复用 B0 检索命中；命中文档 offered 覆盖其全部新块（B0 结构结论）",
            "noise_residual_rule": "gold 引文跨过的单元在候选 clean 台账中必须全部 kept",
            "limitations": [
                "offered_locators 为 B0 保存值映射（来源命中→新块全量），非对新 build 索引重新检索",
                "候选 artifacts 为纯内存重建，未建 PG 候选 build（冻结进 E5 另行执行）",
            ],
        },
        "doc_level": doc_rows,
        "targets": target_rows,
        "summary": {
            "targets": len(target_rows),
            "transitions_vs_base": {
                pair: {f"{a}->{b}": n for (a, b), n in sorted(cnt.items())}
                for pair, cnt in transitions.items()
                if pair != "candidate_vs_b1b3"
            },
            "transitions_candidate_vs_b1b3": {
                f"{a}->{b}": n for (a, b), n in sorted(transitions["candidate_vs_b1b3"].items())
            },
            "improved_vs_base": {
                "chunking_impact_recovered": sum(
                    1
                    for r in target_rows
                    if r["base_code"] == "chunking_impact"
                    and r["candidate_code"] != "chunking_impact"
                ),
                "structure_error_recovered": sum(
                    1
                    for r in target_rows
                    if r["base_code"] == "structure_error"
                    and r["candidate_code"] != "structure_error"
                ),
            },
            "regressed_vs_base": sum(
                1 for r in target_rows if r["base_code"] == "ok" and r["candidate_code"] != "ok"
            ),
            "still_chunking_candidate": [
                (r["query_id"], r["target_id"], r["source_id"], r["flags"])
                for r in target_rows
                if r["candidate_code"] == "chunking_impact"
            ],
            "noise_residual": [
                {
                    "query_id": r["query_id"],
                    "target_id": r["target_id"],
                    "all_crossed_kept": r.get("noise_residual_check", {}).get("all_crossed_kept"),
                    "noise_crossed": r.get("noise_residual_check", {}).get("noise_crossed"),
                }
                for r in target_rows
                if (r["query_id"], r["target_id"]) in NOISE_RESIDUAL
            ],
            "doc_chars_lost": sum(d["chars_lost_vs_old"] for d in doc_rows),
            "doc_old_units_not_contiguous": sum(
                len(d["old_unit_not_contiguous_in_new"]) for d in doc_rows
            ),
            "doc_old_chunks_broken": sum(
                len(d["old_chunk_not_contiguous_in_new"]) for d in doc_rows
            ),
            "doc_chunks_delta": sum(d["new_chunks"] - d["old_chunks"] for d in doc_rows),
        },
    }
    (OUT / "b4-candidate-comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(
            dsn(), "<REDACTED>"
        ),
        encoding="utf-8",
    )

    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print("DOC_LEVEL", json.dumps(
        [
            {k: d[k] for k in ("gold_source_id", "old_units", "new_units", "old_chunks", "new_chunks", "chars_lost_vs_old", "chars_gained_vs_old", "old_unit_not_contiguous_in_new")}
            for d in doc_rows
        ],
        ensure_ascii=False,
    ))
    print("MODELS_ABSENT", not any(x in sys.modules for x in ["openai", "anthropic"]))
    print("RO", ro)
    print("STACK reader-pdf-8", CLEAN_REV, CHUNK_REV)


if __name__ == "__main__":
    main()
