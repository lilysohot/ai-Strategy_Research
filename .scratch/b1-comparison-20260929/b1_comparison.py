"""B1-only 分项对照（B4 门槛）：reader-pdf-7 相对基线 reader-pdf-6 的准备层归因对比。

目的（`docs/data_clean_dos/02-fragment-chunking.md` §B4.1 的 B1-only 行）：仅 reader
候选逻辑变化（`_is_heading` 的 `uniform_multiline_block` 规则），clean/chunk 不变，
回答两个问题：

- 分组是否改善：``chunking_impact``（正文被拆进相邻 heading/body 块）是否回落；
- 是否出现字符或阅读序损伤：逐字字符覆盖与旧连续串在新文档中的连续性。

**隔离保证（B4.3）**：零模型（沿用 B0 的 import 陷阱）、只读 PG（旧 artifacts 只
SELECT，不写任何行）、新 artifacts 纯 Python 内存重建（不改归档、不建索引、不发布）。

offered 判定复用 B0 保存的检索命中（``hits_by_source``）；B0 已证实 offered 上下文
覆盖命中文档**全部块**（``retrieval_not_offered=0`` 结构性成立），故新 build 的
offered_contains 按「来源命中 且 引文落在新 build 单块」等价重现——这是本档的受控
假设，见报告 §限制。

产物：``b1_comparison.json``（对照明细）。
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
# 6 来源的归档副本（i3-1 e2e 审计固定归档；生产 data/corpus-archive 无此批次）。
ARCHIVE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/archive"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# 复用 B0 脚本的零模型 import 陷阱与环境装载（其模块级代码完成 .env CORPUS_* 与
# PGOPTIONS 只读、DenyModels 注入）。
spec = importlib.util.spec_from_file_location(
    "b0_attribution", ROOT / ".scratch/b0-attribution-20260928/b0_attribution.py"
)
b0 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b0)

import psycopg  # noqa: E402

from plugins.corpus.preparation.clean import clean_reader_result  # noqa: E402
from plugins.corpus.preparation.chunk import chunk_clean_result  # noqa: E402
from plugins.corpus.preparation.readers import read_document  # noqa: E402
from plugins.corpus.service import dsn  # noqa: E402

# 同 build_id 的 16 位前缀，保持 locator 形状与权威链一致（仅内部一致性需要）。
LOCATOR_PREFIX = "b1cmp-0000000000000000"


def norm(text: str) -> str:
    return b0.norm(text)


def build_new_artifacts(path: Path, source_id: str, active_build_id: str) -> dict:
    """归档副本 → reader-pdf-7 → clean → chunk → B0 形状的 artifacts（纯内存）。"""
    reader_result = read_document(path)
    assert "reader-pdf-7" in reader_result.extractor_rev, reader_result.extractor_rev
    clean = clean_reader_result(reader_result)
    chunk_result = chunk_clean_result(reader_result, clean)

    unit_rows: list[dict] = []
    for u in sorted(reader_result.units, key=lambda u: u.ordinal):
        unit_rows.append(
            {
                "ordinal": u.ordinal,
                "unit_id": f"unit:{u.ordinal:04d}",
                "page": str(u.location.page) if u.location.page is not None else None,
                "n_cells": len(u.location.cells or ()),
                "element": u.location.element,
                "raw": u.raw_text,
                "norm": norm(u.raw_text),
            }
        )
    by_unit = {u["unit_id"]: u for u in unit_rows}
    unit_id_by_ordinal = {u["ordinal"]: u["unit_id"] for u in unit_rows}

    chunk_rows: list[dict] = []
    for candidate in chunk_result.chunks:
        refs = [unit_id_by_ordinal[o] for o in candidate.unit_ordinals if o in unit_id_by_ordinal]
        refs = list(dict.fromkeys([*refs, *[unit_id_by_ordinal[o] for o in candidate.context_refs if o in unit_id_by_ordinal]]))
        text = "\n".join(by_unit[u]["raw"] for u in refs if u in by_unit)
        chunk_rows.append(
            {
                "chunk_id": f"{LOCATOR_PREFIX}:{candidate.key}",
                "kind": candidate.kind,
                "title": candidate.title_text,
                "unit_refs": refs,
                "pages": sorted({by_unit[u]["page"] for u in refs if u in by_unit and by_unit[u]["page"]}),
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


def offered_hits_for_new(queries: dict, new_artifacts: dict[str, dict]) -> dict[str, dict]:
    """把 B0 的检索命中映射到新 build：命中来源的 offered 覆盖其全部新块（B0 结构结论）。"""
    out: dict[str, dict] = {}
    for qid, q in queries.items():
        per_source: dict[str, dict] = {}
        for sid, hit in q["hits_by_source"].items():
            art = new_artifacts.get(sid)
            if art is None:
                continue
            per_source[sid] = {
                "rank": hit["rank"],
                "doc_id": hit["doc_id"],
                "offered_locators": [f"chunk:{c['chunk_id']}" for c in art["chunks"]],
            }
        out[qid] = per_source
    return out


def main() -> None:
    gold = b0.load_gold()
    baseline = json.loads(B0_JSON.read_text(encoding="utf-8"))
    base_by_target = {
        (t.get("query_id"), t.get("target_id")): t
        for t in baseline["targets"]
    }
    queries = baseline["queries"]

    gold_source_ids = {
        t["source_id"]
        for row in gold
        for t in (row.get("evidence_targets") or []) + (row.get("supplementary_evidence_targets") or [])
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
        # 归档路径（只读 SELECT）
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

    # 新 artifacts：重读归档副本
    new_artifacts: dict[str, dict] = {}
    for gid, info in resolved.items():
        full = info["corpus_source_id"]
        if full is None or full not in sid_to_archive:
            continue
        path = ARCHIVE / sid_to_archive[full]
        if not path.exists():
            raise FileNotFoundError(f"归档副本缺失: {path}")
        new_artifacts[full] = build_new_artifacts(path, full, info["build_id"])

    hits_new = offered_hits_for_new(queries, new_artifacts)

    # ── 文档级 B1.3 对照：字符覆盖 + 阅读序连续性 ──
    doc_rows: list[dict] = []
    for gid, info in resolved.items():
        full = info["corpus_source_id"]
        old = old_artifacts.get(gid)
        new = new_artifacts.get(full)
        if full is None or old is None or new is None:
            continue
        old_norm = old["doc_norm"]
        new_norm = new["doc_norm"]
        old_missing = Counter(ch for ch in old_norm if old_norm.count(ch) > new_norm.count(ch))
        new_missing = Counter(ch for ch in new_norm if new_norm.count(ch) > old_norm.count(ch))
        # 旧单元逐字（去空白）是否仍是新文档的连续子串 —— 检测行级丢失/重排。
        old_unit_substr_missing = [
            u["unit_id"] for u in old["units"] if u["norm"] and u["norm"] not in new_norm
        ]
        # 旧 chunk 连续串是否仍连续 —— 检测阅读序损伤。
        old_chunk_broken = [
            c["chunk_id"] for c in old["chunks"] if c["norm"] and c["norm"] not in new_norm
        ]
        old_heading_units = sum(1 for u in old["units"] if u["element"] == "heading")
        new_heading_units = sum(1 for u in new["units"] if u["element"] == "heading")
        doc_rows.append(
            {
                "source_id": full,
                "gold_source_id": gid,
                "old_units": len(old["units"]),
                "new_units": len(new["units"]),
                "old_chunks": len(old["chunks"]),
                "new_chunks": len(new["chunks"]),
                "old_heading_units": old_heading_units,
                "new_heading_units": new_heading_units,
                "old_doc_norm_chars": len(old_norm),
                "new_doc_norm_chars": len(new_norm),
                "chars_lost_vs_old": sum(old_missing.values()),
                "chars_gained_vs_old": sum(new_missing.values()),
                "old_unit_not_contiguous_in_new": old_unit_substr_missing,
                "old_chunk_not_contiguous_in_new": old_chunk_broken,
            }
        )

    # ── target 级归因对比 ──
    target_rows: list[dict] = []
    for row in gold:
        qid = row["query_id"]
        for tier, key in (
            ("required", "evidence_targets"),
            ("supplementary", "supplementary_evidence_targets"),
        ):
            for t in row.get(key) or []:
                gid = t["source_id"]
                base = base_by_target.get((qid, t.get("target_id")))
                art = new_artifacts.get(resolved[gid]["corpus_source_id"]) if resolved.get(gid, {}).get("corpus_source_id") else None
                if art is None:
                    new_code = "source_unresolved"
                    flags: dict = {}
                else:
                    rec = b0.attr_target(t, tier == "supplementary", qid, art, hits_new[qid])
                    new_code = rec["primary_code"]
                    flags = rec.get("flags", {})
                base_code = base["primary_code"] if base else None
                target_rows.append(
                    {
                        "query_id": qid,
                        "target_id": t.get("target_id"),
                        "tier": tier,
                        "source_id": gid,
                        "base_code": base_code,
                        "new_code": new_code,
                        "changed": base_code != new_code,
                        "flags": flags,
                    }
                )

    transitions: Counter = Counter()
    for r in target_rows:
        transitions[(r["base_code"], r["new_code"])] += 1

    result = {
        "artifact": "b1-comparison",
        "version": 1,
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").UTC).isoformat(),
        "scope": "B4 B1-only comparison: reader-pdf-7 vs reader-pdf-6, zero model, read-only PG, no publish",
        "policy": {
            "gold": str(GOLD.relative_to(ROOT)),
            "reader_new": "reader-pdf-7",
            "reader_old": "reader-pdf-6 (基线 build 的 recorded parse_rev)",
            "clean_rev": "clean-3 (不变)",
            "chunk_rev": "chunk-3 (不变)",
            "offered_rule": "复用 B0 检索命中；命中文档 offered 覆盖其全部新块（B0 结构结论）",
            "limitations": [
                "offered_locators 为 B0 保存值映射（来源命中→新块全量），非对新 build 索引重新检索",
                "目标比较的 base_code 取自 b0_attribution.json（活动 build，reader-pdf-6 时代）",
            ],
        },
        "doc_level": doc_rows,
        "targets": target_rows,
        "summary": {
            "targets": len(target_rows),
            "transitions": {f"{a}->{b}": n for (a, b), n in sorted(transitions.items())},
            "improved": sum(1 for r in target_rows if r["base_code"] == "chunking_impact" and r["new_code"] != "chunking_impact"),
            "regressed": sum(1 for r in target_rows if r["base_code"] == "ok" and r["new_code"] != "ok"),
            "chars_lost_any_source": sum(d["chars_lost_vs_old"] for d in doc_rows),
            "old_units_not_contiguous_any": sum(len(d["old_unit_not_contiguous_in_new"]) for d in doc_rows),
            "old_chunks_broken_any": sum(len(d["old_chunk_not_contiguous_in_new"]) for d in doc_rows),
        },
    }
    (OUT / "b1_comparison.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(dsn(), "<REDACTED>"),
        encoding="utf-8",
    )
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(json.dumps([{k: d[k] for k in ("gold_source_id", "old_units", "new_units", "old_chunks", "new_chunks", "old_heading_units", "new_heading_units", "chars_lost_vs_old", "chars_gained_vs_old", "old_unit_not_contiguous_in_new", "old_chunk_not_contiguous_in_new")} for d in doc_rows], ensure_ascii=False, indent=2))
    regressed = [r for r in target_rows if r["base_code"] == "ok" and r["new_code"] != "ok"]
    improved = [r for r in target_rows if r["base_code"] == "chunking_impact" and r["new_code"] != "chunking_impact"]
    print("REGRESSED:")
    for r in regressed:
        print(json.dumps({k: r[k] for k in ("query_id", "target_id", "tier", "source_id", "new_code", "flags")}, ensure_ascii=False, default=str))
    print("IMPROVED_COUNT", len(improved))
    print("STILL_CHUNKING", [(r["query_id"], r["target_id"], r["source_id"]) for r in target_rows if r["new_code"] == "chunking_impact"])
    print("models_absent", not any(x in sys.modules for x in ["openai", "anthropic"]))


if __name__ == "__main__":
    main()
