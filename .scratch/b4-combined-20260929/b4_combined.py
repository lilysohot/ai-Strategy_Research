"""B4 组合对照：B3-only 与 B1+B3 相对基线（B0）与 B1-only 的分项归因对比。

目的（`docs/data_clean_dos/02-fragment-chunking.md` §B4.1 的「通过项的组合」行）：
实现 B3 候选切块规则（chunk-4，R1 单格表行并入正文 / R2 连续标题合并）后，在同一
基线上跑两个变体，回答两个问题：

- B3 是否有必要实施：B1-only 后残留的 9 条 ``chunking_impact`` 里，单格表行误判
  （5 条 macro）与标题拆块（1 条 company-008 a-2）是否被 B3 恢复为 ``ok``；
- 组合是否引入新错误、综合成本是否值得：B1+B3 相对基线/B1-only 是否有回归，
  chunk 数与 kind 分布成本变化是否在可接受范围。

变体矩阵：

- ``base`` —— B0 活动 build（reader-pdf-6/clean-3/chunk-3 时代）归因
  （``b0_attribution.json`` 的 ``primary_code``）；
- ``b1`` —— B1-only：reader-pdf-7 + chunk-3（``b1_comparison.json`` 的 ``new_code``，
  上一步生成时 CHUNK_REV 尚未升至 chunk-4，故其 chunk 侧为 chunk-3）；
- ``b3`` —— B3-only：旧 PG 单元反投影 + chunk-4（不换 reader，只换切块规则）；
- ``b1b3`` —— B1+B3：归档副本重读 reader-pdf-7 → clean → chunk-4。

**隔离保证（B4.3）**：零模型（沿用 B0/B1 的 import 陷阱）、只读 PG（旧 artifacts
只 SELECT，不写任何行）、新 artifacts 纯 Python 内存重建（不改归档、不建索引、不发布）。

offered 判定复用 B0 保存的检索命中（``hits_by_source``）；B0 已证实 offered 上下文
覆盖命中文档**全部块**，故新变体的 offered_contains 按「来源命中 且 引文落在该变体
单块」等价重现（与 B1 相同的受控假设）。

产物：``b4-combined-comparison.json``（对照明细）。
"""

from __future__ import annotations

import importlib.util
import json
import os
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
GOLD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"
B0_JSON = ROOT / ".scratch/b0-attribution-20260928/b0_attribution.json"
B1_JSON = ROOT / ".scratch/b1-comparison-20260929/b1_comparison.json"
# 6 来源的归档副本（i3-1 e2e 审计固定归档；生产 data/corpus-archive 无此批次）。
ARCHIVE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/archive"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# 复用 B1 脚本（其模块级代码装载 B0 的零模型 import 陷阱、.env、PGOPTIONS 只读；
# 并把 clean/chunk/readers 模块装进 sys.modules）。
spec = importlib.util.spec_from_file_location(
    "b1_comparison", ROOT / ".scratch/b1-comparison-20260929/b1_comparison.py"
)
b1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1)
b0 = b1.b0

import psycopg  # noqa: E402

from plugins.corpus.preparation.chunk import chunk_clean_result  # noqa: E402
from plugins.corpus.preparation.clean import CleanRegion, CleanResult  # noqa: E402
from plugins.corpus.preparation.contract import (  # noqa: E402
    DocumentFormat,
    UnitLocation,
    UnitStatus,
)
from plugins.corpus.preparation.readers.base import (  # noqa: E402
    CandidateUnit,
    ReaderResult,
)
from plugins.corpus.service import dsn  # noqa: E402

LOCATOR_PREFIX = "b4cmp-0000000000000000"


def norm(text: str) -> str:
    return b0.norm(text)


def _artifacts_from_rows(
    unit_rows: list[dict], chunk_result, source_id: str, active_build_id: str
) -> dict:
    """B0 形状 artifacts 装配（镜像 b1.build_new_artifacts 的 chunk 部分）。"""
    by_unit = {u["unit_id"]: u for u in unit_rows}
    unit_id_by_ordinal = {u["ordinal"]: u["unit_id"] for u in unit_rows}
    chunk_rows: list[dict] = []
    for candidate in chunk_result.chunks:
        refs = [
            unit_id_by_ordinal[o] for o in candidate.unit_ordinals if o in unit_id_by_ordinal
        ]
        refs = list(
            dict.fromkeys(
                [
                    *refs,
                    *[
                        unit_id_by_ordinal[o]
                        for o in candidate.context_refs
                        if o in unit_id_by_ordinal
                    ],
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
                    {
                        by_unit[u]["page"]
                        for u in refs
                        if u in by_unit and by_unit[u]["page"]
                    }
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


def _page_int(value: str | None) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except ValueError:
        return None


def build_b3only_artifacts(conn: psycopg.Connection, build_id: str, source_id: str) -> dict:
    """旧 PG 单元（kind/status/clean_view/reasons/cells）反投影 → chunk-4（B3-only）。"""
    rows = conn.execute(
        "SELECT u.ordinal, u.unit_id, u.kind, u.raw_text, "
        "u.location->>'page', u.location->>'element', "
        "jsonb_array_length(COALESCE(u.location->'cells','[]'::jsonb)), "
        "COALESCE(u.location->'label_path','[]'::jsonb), "
        "u.clean_view, u.status, u.reasons "
        "FROM corpus.corpus_units u WHERE u.build_id=%s ORDER BY u.ordinal",
        (build_id,),
    ).fetchall()
    units: list[CandidateUnit] = []
    unit_rows: list[dict] = []
    region_rows: list[tuple[int, str, UnitStatus, tuple[str, ...], str | None]] = []
    for r in rows:
        ordinal, unit_id, kind, raw_text = r[0], r[1], r[2], r[3]
        page_str, element = r[4], r[5]
        n_cells = int(r[6])
        label_path = list(r[7] or [])
        clean_view = r[8]
        status = UnitStatus(r[9])
        reasons = tuple(r[10] or [])
        location = UnitLocation(
            page=_page_int(page_str),
            element=element,
            cells=tuple((i, 0) for i in range(n_cells)),
            label_path=tuple(label_path),
        )
        units.append(
            CandidateUnit(
                ordinal=ordinal,
                kind=kind,
                status=status,
                reasons=reasons,
                raw_text=raw_text or "",
                location=location,
            )
        )
        unit_rows.append(
            {
                "ordinal": ordinal,
                "unit_id": unit_id,
                "page": str(location.page) if location.page is not None else None,
                "n_cells": n_cells,
                "element": element,
                "raw": raw_text or "",
                "norm": norm(raw_text or ""),
            }
        )
        region_rows.append((ordinal, kind, status, reasons, clean_view))
    regions = [
        CleanRegion(
            key=f"r{ordinal:04d}",
            ordinal=ordinal,
            kind=kind,
            status=status,
            reasons=reasons,
            clean_view=clean_view,
            mapping=(),
        )
        for ordinal, kind, status, reasons, clean_view in region_rows
    ]
    reader_result = ReaderResult(
        format=DocumentFormat.PDF,
        extractor_rev="pg-projection",
        source_path="pg",
        page_count=None,
        units=tuple(units),
        issues=(),
    )
    clean = CleanResult(clean_rev="clean-3 (反投影)", regions=tuple(regions))
    chunk_result = chunk_clean_result(reader_result, clean)
    return _artifacts_from_rows(unit_rows, chunk_result, source_id, build_id)


def doc_row_for(variant: dict, old: dict, source_id: str, gold_source_id: str) -> dict:
    old_norm = old["doc_norm"]
    new_norm = variant["doc_norm"]
    old_missing = Counter(
        ch for ch in old_norm if old_norm.count(ch) > new_norm.count(ch)
    )
    new_missing = Counter(
        ch for ch in new_norm if new_norm.count(ch) > old_norm.count(ch)
    )
    old_unit_substr_missing = [
        u["unit_id"] for u in old["units"] if u["norm"] and u["norm"] not in new_norm
    ]
    old_chunk_broken = [
        c["chunk_id"] for c in old["chunks"] if c["norm"] and c["norm"] not in new_norm
    ]
    kind_hist = Counter(c["kind"] for c in variant["chunks"])
    return {
        "source_id": source_id,
        "gold_source_id": gold_source_id,
        "old_units": len(old["units"]),
        "new_units": len(variant["units"]),
        "old_chunks": len(old["chunks"]),
        "new_chunks": len(variant["chunks"]),
        "kind_hist": {k: v for k, v in sorted(kind_hist.items())},
        "old_doc_norm_chars": len(old_norm),
        "new_doc_norm_chars": len(new_norm),
        "chars_lost_vs_old": sum(old_missing.values()),
        "chars_gained_vs_old": sum(new_missing.values()),
        "old_unit_not_contiguous_in_new": old_unit_substr_missing,
        "old_chunk_not_contiguous_in_new": old_chunk_broken,
    }


def main() -> None:
    baseline = json.loads(B0_JSON.read_text(encoding="utf-8"))
    b1_result = json.loads(B1_JSON.read_text(encoding="utf-8"))
    gold = b0.load_gold()
    base_by_target = {
        (t.get("query_id"), t.get("target_id")): t for t in baseline["targets"]
    }
    b1_by_target = {
        (t.get("query_id"), t.get("target_id")): t for t in b1_result["targets"]
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

        # ── 变体 artifacts（连接存活期内构建） ──
        b3_artifacts: dict[str, dict] = {}
        b1b3_artifacts: dict[str, dict] = {}
        for gid, info in resolved.items():
            full = info["corpus_source_id"]
            if full is None:
                continue
            if info["build_id"]:
                b3_artifacts[full] = build_b3only_artifacts(
                    conn, info["build_id"], full
                )
            if full in sid_to_archive:
                path = ARCHIVE / sid_to_archive[full]
                if not path.exists():
                    raise FileNotFoundError(f"归档副本缺失: {path}")
                b1b3_artifacts[full] = b1.build_new_artifacts(path, full, info["build_id"])

    hits_b3 = b1.offered_hits_for_new(queries, b3_artifacts)
    hits_b1b3 = b1.offered_hits_for_new(queries, b1b3_artifacts)

    # ── target 级四变体归因 ──
    target_rows: list[dict] = []
    for row in gold:
        qid = row["query_id"]
        for tier, key in (
            ("required", "evidence_targets"),
            ("supplementary", "supplementary_evidence_targets"),
        ):
            for t in row.get(key) or []:
                gid = t["source_id"]
                full = resolved[gid]["corpus_source_id"] if resolved.get(gid, {}) else None
                base = base_by_target.get((qid, t.get("target_id")))
                b1row = b1_by_target.get((qid, t.get("target_id")))
                base_code = base["primary_code"] if base else None
                b1_code = b1row["new_code"] if b1row else base_code

                def run(code_variant: str, artifacts: dict, hits) -> tuple[str, dict]:
                    art = artifacts.get(full) if full else None
                    if art is None:
                        return "source_unresolved", {}
                    rec = b0.attr_target(t, tier == "supplementary", qid, art, hits[qid])
                    return rec["primary_code"], rec.get("flags", {})

                b3_code, b3_flags = run("b3", b3_artifacts, hits_b3)
                b1b3_code, b1b3_flags = run("b1b3", b1b3_artifacts, hits_b1b3)
                target_rows.append(
                    {
                        "query_id": qid,
                        "target_id": t.get("target_id"),
                        "tier": tier,
                        "source_id": gid,
                        "base_code": base_code,
                        "b1_code": b1_code,
                        "b3_code": b3_code,
                        "b1b3_code": b1b3_code,
                        "b1b3_flags": {k: v for k, v in b1b3_flags.items() if k in ("in_concat", "in_single_chunk_any")},
                    }
                )

    transitions = {
        pair: Counter((r["base_code"], r[pair]) for r in target_rows)
        for pair in ("b1_code", "b3_code", "b1b3_code")
    }
    transitions["b1b3_vs_b1"] = Counter(
        (r["b1_code"], r["b1b3_code"]) for r in target_rows
    )

    # ── 文档级对照（相对基线） ──
    doc_b3: list[dict] = []
    doc_b1b3: list[dict] = []
    for gid, info in resolved.items():
        full = info["corpus_source_id"]
        old = old_artifacts.get(gid)
        if full is None or old is None:
            continue
        if full in b3_artifacts:
            doc_b3.append(doc_row_for(b3_artifacts[full], old, full, gid))
        if full in b1b3_artifacts:
            doc_b1b3.append(doc_row_for(b1b3_artifacts[full], old, full, gid))

    b1_doc = {d["source_id"]: d for d in b1_result["doc_level"]}

    result = {
        "artifact": "b4-combined-comparison",
        "version": 1,
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").UTC
        ).isoformat(),
        "scope": "B4 combined comparison: B3-only + B1+B3 vs base/B1-only, zero model, read-only PG, no publish",
        "policy": {
            "gold": str(GOLD.relative_to(ROOT)),
            "variants": {
                "base": "B0 活动 build（reader-pdf-6 时代，chunk-3），b0_attribution.json",
                "b1": "B1-only：reader-pdf-7 + chunk-3（b1_comparison.json 保存值）",
                "b3": "B3-only：旧 PG 单元反投影 + chunk-4（R1 单格表行并入正文 / R2 连续标题合并）",
                "b1b3": "B1+B3：归档副本重读 reader-pdf-7 → clean → chunk-4",
            },
            "b3_rules": [
                "R1：table_row 且 len(location.cells)==1 时按正文 run 装配（==1 而非 <=1，cells=() 的 MD/docx 行不误伤）",
                "R2：连续 heading 单元合并为单一 heading 块（文本 \\n 拼接），单行标题维持既有行为",
            ],
            "chunk_rev": "chunk-4（b4 变体共用）",
            "offered_rule": "复用 B0 检索命中；命中文档 offered 覆盖其全部新块（B0 结构结论）",
            "limitations": [
                "b1 变体为 b1_comparison.json 保存值（其生成时 CHUNK_REV=chunk-3，故恰为 B1-only）",
                "B3-only 用占位 cells（(i,0) 序列）保证 len 语义，不复制真实网格坐标——单格/多格判定等价，但 label 前缀依赖真实 label_path",
                "offered_locators 为 B0 保存值映射（来源命中→新块全量），非对新 build 索引重新检索",
            ],
        },
        "doc_level": {"b3": doc_b3, "b1b3": doc_b1b3, "b1_reference": list(b1_doc.values())},
        "targets": target_rows,
        "summary": {
            "targets": len(target_rows),
            "transitions_vs_base": {
                pair: {f"{a}->{b}": n for (a, b), n in sorted(cnt.items())}
                for pair, cnt in transitions.items()
                if pair != "b1b3_vs_b1"
            },
            "transitions_b1b3_vs_b1": {
                f"{a}->{b}": n for (a, b), n in sorted(transitions["b1b3_vs_b1"].items())
            },
            "improved_vs_base": {
                pair: sum(
                    1
                    for r in target_rows
                    if r["base_code"] == "chunking_impact" and r[pair] != "chunking_impact"
                )
                for pair in ("b1_code", "b3_code", "b1b3_code")
            },
            "regressed_vs_base": {
                pair: sum(
                    1 for r in target_rows if r["base_code"] == "ok" and r[pair] != "ok"
                )
                for pair in ("b1_code", "b3_code", "b1b3_code")
            },
            "still_chunking_b1b3": [
                (r["query_id"], r["target_id"], r["source_id"])
                for r in target_rows
                if r["b1b3_code"] == "chunking_impact"
            ],
            "doc_b3_chars_lost": sum(d["chars_lost_vs_old"] for d in doc_b3),
            "doc_b3_chunks_delta": sum(
                d["new_chunks"] - d["old_chunks"] for d in doc_b3
            ),
            "doc_b1b3_chars_lost": sum(d["chars_lost_vs_old"] for d in doc_b1b3),
            "doc_b1b3_chunks_delta": sum(
                d["new_chunks"] - d["old_chunks"] for d in doc_b1b3
            ),
        },
    }
    (OUT / "b4-combined-comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(
            dsn(), "<REDACTED>"
        ),
        encoding="utf-8",
    )

    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print("MODELS_ABSENT", not any(x in sys.modules for x in ["openai", "anthropic"]))
    print("RO", ro)


if __name__ == "__main__":
    main()
