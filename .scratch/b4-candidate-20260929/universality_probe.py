"""普遍性探针：跨 6 源量化「gold 引文在源 PDF 文本流中是否连续」的一致率。

目的：决定 reader-pdf-9 的装配目标能否以「源 PDF 文本流序」为保真基线。此前
「gold = 源流序」只在 174b6462 单页 5 条核验过，本探针扩大到金标全部 target。

判定（对每个含 non-empty quote 的 target）：
- ``src_info``：归一化引文是否作为**连续子串**出现在源 PDF 对应页文本流中。
  ``src_contiguous``（连续命中）、``src_present_tokens``（不连续但分词全在，如
  bbox 阅读序与流序不同）、``src_absent``（分词缺失＝真不支持）。
- ``cand_tight``：归一化引文是否作为连续子串出现在候选 build 单块／doc_norm 中
  （``in_concat``、``in_single_chunk_any``）。
- 一致性统计：``gold 连续 ⇔ src 连续`` 在全部 target 中的比例。

只读保证：源 PDF 用 pymupdf 纯读，候选 artifacts 复用 b4_candidate
（零模型 / PG 只读 / 纯内存）。零模型 import 陷阱由 b4_candidate 模块级装载继承。
产物：``universality.json``。
"""

from __future__ import annotations

import importlib.util
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import fitz  # noqa: E402

spec = importlib.util.spec_from_file_location(
    "b4_candidate", ROOT / ".scratch/b4-candidate-20260929/b4_candidate.py"
)
bc = importlib.util.module_from_spec(spec)
spec.loader.exec_module(bc)
b0 = bc.b0

import psycopg  # noqa: E402

from plugins.corpus.service import dsn  # noqa: E402

WS = re.compile(r"[\s\u3000\xa0\u200b]+")


def norm(s: str) -> str:
    return WS.sub("", s or "")


def main() -> None:
    gold = b0.load_gold()
    gold_source_ids = {
        t["source_id"]
        for row in gold
        for t in (row.get("evidence_targets") or []) + (row.get("supplementary_evidence_targets") or [])
    }

    with psycopg.connect(dsn()) as conn:
        conn.execute("SET default_transaction_read_only=on")
        resolved = b0.resolve_sources(conn, gold_source_ids)
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

    # 候选 build 对照所需的 hits（复用 B0 保存），用于 in_single_chunk 判定。
    baseline = json.loads((bc.B0_JSON).read_text(encoding="utf-8"))
    # 归并候选 artifacts 以复用 b0.attr_target 判定单块命中（含 page 提示 + offered）。
    candidate_artifacts: dict[str, dict] = {}
    for gid in gold_source_ids:
        full = resolved[gid]["corpus_source_id"]
        if full is None or full not in sid_to_archive:
            continue
        path = bc.ARCHIVE / sid_to_archive[full]
        candidate_artifacts[full] = bc.build_candidate_artifacts(path, full, resolved[gid]["build_id"])
    queries = baseline["queries"]
    hits = bc.b1.offered_hits_for_new(queries, candidate_artifacts)

    # 源流缓存按分页。
    src_streams: dict[str, dict[str, str]] = {}
    for gid in gold_source_ids:
        full = resolved[gid]["corpus_source_id"]
        if full is None or full not in sid_to_archive:
            continue
        path = bc.ARCHIVE / sid_to_archive[full]
        doc = fitz.open(path)
        src_streams[gid] = {str(i + 1): norm(doc[i].get_text()) for i in range(doc.page_count)}

    rows: list[dict] = []
    for row in gold:
        qid = row["query_id"]
        for tier, key in (
            ("required", "evidence_targets"),
            ("supplementary", "supplementary_evidence_targets"),
        ):
            for t in row.get(key) or []:
                gid = t["source_id"]
                quote = (t.get("quote") or "").strip()
                if not quote:
                    continue
                qn = norm(quote)
                full = resolved.get(gid, {}).get("corpus_source_id")
                page_hint = next(
                    (str(x).split(":", 1)[1] for x in (t.get("locator") or []) if str(x).startswith("page:")),
                    None,
                )
                stream = src_streams.get(gid, {}).get(page_hint, "")
                src_contiguous = bool(qn) and qn in stream if stream else None
                # 分词是否全部散落在该页（区分"不连续但存在"与"真缺失"）。
                toks = [norm(x) for x in re.split(r"\s+", quote) if x]
                tokens_present = bool(toks) and stream and all(x in stream for x in toks)
                if src_contiguous is None or page_hint is None or full is None:
                    src_state = "n/a"
                elif src_contiguous:
                    src_state = "src_contiguous"
                elif tokens_present:
                    src_state = "src_tokens_only"
                else:
                    src_state = "src_absent"
                art = candidate_artifacts.get(full)
                if art is None:
                    cand_in_concat = None
                    cand_in_chunk = None
                else:
                    cand_in_concat = qn in art["doc_norm"] if qn else False
                    rec = b0.attr_target(t, tier == "supplementary", qid, art, hits[qid])
                    cand_in_chunk = rec.get("flags", {}).get("in_single_chunk_any")
                rows.append(
                    {
                        "query_id": qid,
                        "target_id": t.get("target_id"),
                        "tier": tier,
                        "source_id": gid,
                        "quote_head": quote[:40],
                        "src_state": src_state,
                        "cand_in_concat": cand_in_concat,
                        "cand_in_chunk": cand_in_chunk,
                    }
                )

    # 一致性：gold 连续（cand_in_chunk=True）与 src_contiguous 是否对齐。
    align = Counter()
    for r in rows:
        if r["src_state"] not in ("src_contiguous", "src_tokens_only", "src_absent"):
            align["n/a"] += 1
            continue
        gold_cont = bool(r["cand_in_chunk"])
        src_cont = r["src_state"] == "src_contiguous"
        if gold_cont == src_cont and r["src_state"] != "n/a":
            align["aligned"] += 1
        else:
            align["mismatch"] += 1
    src_state_hist = Counter(r["src_state"] for r in rows)
    # 重点：当 gold 宣称"单块命中"（作者认为应可预期命中）但源流不连续的比例——即
    # "gold 顺序 ≠ 源流顺序" 的可疑面。
    gold_no_concat = [r for r in rows if r["cand_in_concat"] is False]
    gold_no_chunk = [r for r in rows if r["cand_in_chunk"] is False]

    result = {
        "artifact": "universality-probe",
        "generated_at": json.dumps(dict(), default=str),
        "n_targets": len(rows),
        "src_state_hist": dict(src_state_hist),
        "alignment": dict(align),
        "gold_continuous_not_in_src": [
            r for r in rows if r["cand_in_chunk"] is True and r["src_state"] == "src_tokens_only"
        ],
        "gold_gap_not_in_concat": [
            {k: r[k] for k in ("query_id", "target_id", "source_id", "src_state", "quote_head")}
            for r in rows
            if r["cand_in_concat"] is False
        ],
        "rows": rows,
    }
    (OUT / "universality.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(dsn(), "<REDACTED>"),
        encoding="utf-8",
    )
    print("N_TARGETS", len(rows))
    print("SRC_STATE", dict(src_state_hist))
    print("ALIGN", dict(align))
    print("GOLD_CHUNK_TRUE_BUT_SRC_TOKENS_ONLY (gold顺序≠源流顺序、断在chunk)", len(result["gold_continuous_not_in_src"]))
    for r in result["gold_continuous_not_in_src"][:20]:
        print("  ", r["query_id"], r["target_id"], r["source_id"], "::", r["quote_head"])
    print("GOLD_NOT_IN_CONCAT", len(result["gold_gap_not_in_concat"]))
    for r in result["gold_gap_not_in_concat"][:20]:
        print("  ", r["query_id"], r["target_id"], r["source_id"], r["src_state"], "::", r["quote_head"])


if __name__ == "__main__":
    main()