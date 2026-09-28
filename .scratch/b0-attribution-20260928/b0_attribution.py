"""B0 准备层归因（固定 30 题金标集，零模型、PG 只读）。

目的（`docs/data_clean_dos/02-fragment-chunking.md` §B0）：在**不重建语料**的前提下，
用只读语料库对固定金标集逐题归因，区分：

- ``source_text_missing`` —— 金标 ``quote`` 在权威原文单元（``corpus_units.raw_text``）
  里**逐字找不到**（原文/结构错误，类 2）；
- ``chunking_impact`` —— quote 存在于全文档拼接里，但**不落在任何单个 chunk**（跨块
  边界，类 3 的切块影响）；
- ``structure_error`` —— quote 存在于单一 chunk，但金标声明了表格 ``row/col/cell``
  结构，而该来源活动 build 的单元**没有单元格坐标**（``location.cells`` 为空），
  结构关系无法从权威产物复核（类 2）；
- ``retrieval_not_offered`` —— quote 存在于单一 chunk，但**固定查询**（问题原文）
  的检索命中未提供覆盖它的块（检索未取，类 3）；
- ``ok`` —— 证据在权威原文、落在单块、且固定查询命中覆盖。

**边界（不越界）**：本脚本只归因**准备层/检索层**。模型侧「已 offered+fetched 但未
delivered」属消费侧，不在此判定；这里不调用任何模型，只调真实注册工具
``corpus_search``（问题原文作固定查询）做 offered 判定。

只读保证：``PGOPTIONS`` 强制 ``default_transaction_read_only=on``；零模型保证：import
陷阱拒绝 ``openai``／``anthropic``。产物：``b0_attribution.json``。
"""

from __future__ import annotations

import asyncio
import hashlib
import importlib.abc
import json
import os
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
GOLD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

from dotenv import dotenv_values  # noqa: E402

_cfg = dotenv_values(ROOT / ".env")
for _k, _v in _cfg.items():
    if _k.startswith("CORPUS_") and _v is not None:
        os.environ.setdefault(_k, _v)
os.environ["PGOPTIONS"] = "-c default_transaction_read_only=on -c statement_timeout=30000"
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"


class DenyModels(importlib.abc.MetaPathFinder):
    """零模型档：任何 LLM SDK／语义模型模块都不允许被 import。"""

    _DENIED_ROOTS = {"openai", "anthropic"}
    _DENIED_PREFIXES = ("plugins.corpus.material_semantics", "plugins.corpus._r2_")

    def find_spec(self, fullname, path=None, target=None):  # noqa: ANN001, ANN201
        if fullname.split(".")[0] in self._DENIED_ROOTS or fullname.startswith(
            self._DENIED_PREFIXES
        ):
            raise RuntimeError(f"Model module forbidden during B0 attribution: {fullname}")
        return None


sys.meta_path.insert(0, DenyModels())

import psycopg  # noqa: E402

from plugins.corpus.service import dsn  # noqa: E402
from plugins.tools import get_builtin_tools  # noqa: E402

_WS = re.compile(r"[\s\u3000\xa0\u200b]+")


def norm(text: str) -> str:
    """去全部空白（含换行/全角空格/零宽空格）后比较，抵消排版换行差异。"""
    return _WS.sub("", text or "")


def hash8(gold_source_id: str) -> str:
    return gold_source_id.split("_")[-1]


def load_gold() -> list[dict]:
    return [
        json.loads(line)
        for line in GOLD.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def resolve_sources(conn: psycopg.Connection, gold_ids: set[str]) -> dict[str, dict]:
    """``<date>_<hash8>`` → {corpus_source_id, build_id}；hash8 为 source_id 前缀。"""
    rows = conn.execute(
        "SELECT source_id FROM corpus.corpus_sources"
    ).fetchall()
    by_prefix = {r[0][:8]: r[0] for r in rows}
    out: dict[str, dict] = {}
    for gid in sorted(gold_ids):
        full = by_prefix.get(hash8(gid))
        if full is None:
            out[gid] = {"corpus_source_id": None, "build_id": None}
            continue
        build = conn.execute(
            "SELECT active_build_id FROM corpus.corpus_publications WHERE source_id=%s",
            (full,),
        ).fetchone()
        out[gid] = {
            "corpus_source_id": full,
            "build_id": build[0] if build else None,
        }
    return out


def load_source_artifacts(conn: psycopg.Connection, build_id: str) -> dict:
    """活动 build 的权威单元与 chunk（chunk 文本 = 其 ``unit_refs`` 单元拼接）。"""
    units = conn.execute(
        "SELECT u.ordinal, u.unit_id, u.location->>'page', "
        "jsonb_array_length(COALESCE(u.location->'cells','[]'::jsonb)), "
        "u.location->>'element', u.raw_text "
        "FROM corpus.corpus_units u WHERE u.build_id=%s ORDER BY u.ordinal",
        (build_id,),
    ).fetchall()
    unit_rows = [
        {
            "ordinal": r[0],
            "unit_id": r[1],
            "page": r[2],
            "n_cells": int(r[3]),
            "element": r[4],
            "raw": r[5] or "",
            "norm": norm(r[5] or ""),
        }
        for r in units
    ]
    by_unit = {u["unit_id"]: u for u in unit_rows}
    chunks = conn.execute(
        "SELECT c.chunk_id, c.kind, c.title_text, c.unit_refs, c.section_path "
        "FROM corpus.corpus_chunks c WHERE c.build_id=%s",
        (build_id,),
    ).fetchall()
    chunk_rows = []
    for c in chunks:
        refs = list(c[3] or [])
        text = "\n".join(by_unit[u]["raw"] for u in refs if u in by_unit)
        chunk_rows.append(
            {
                "chunk_id": c[0],
                "kind": c[1],
                "title": c[2],
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
    # 归一拼接与逐单元区间：用于把"仅存在于拼接"的引文定位到跨过的单元。
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
    }


def crossed_units(artifacts: dict, qn: str) -> list[dict]:
    """引文在归一拼接里跨过的单元（含其所属 chunk kind），用于表征切块影响。"""
    i = artifacts["doc_norm"].find(qn)
    if i < 0 or not qn:
        return []
    j = i + len(qn)
    out = []
    for uid, page, a, b in artifacts["unit_spans"]:
        if a < j and b > i:
            out.append({"unit_id": uid, "page": page, "chunk_kinds": artifacts["unit_kinds"].get(uid, [])})
    return out


def attr_target(
    target: dict,
    extra: bool,
    qid: str,
    artifacts: dict,
    hits_by_source: dict[str, dict],
) -> dict:
    quote = target.get("quote") or ""
    qn = norm(quote)
    locator = target.get("locator") or []
    constraints = target.get("constraints") or {}
    is_table = bool(
        constraints.get("cell")
        or constraints.get("row")
        or constraints.get("col")
        or any(str(x).startswith(("row:", "col:", "cell:")) for x in locator)
    )
    src = artifacts.get("_resolved", {})

    # 金标 locator 的 ``page:N`` 是权威定位提示：短引文（如 "67.74"）会在多页重复，
    # 必须按提示页匹配，否则会取到错误页的同名数字。
    page_hint = next(
        (
            str(x).split(":", 1)[1]
            for x in locator
            if str(x).startswith("page:")
        ),
        None,
    )
    page_units = [
        u for u in artifacts["units"] if page_hint is None or u["page"] == page_hint
    ]
    page_chunks = [
        c
        for c in artifacts["chunks"]
        if page_hint is None or page_hint in (c["pages"] or [])
    ]

    unit_hit = next((u for u in page_units if qn and qn in u["norm"]), None)
    chunk_hit = next((c for c in page_chunks if qn and qn in c["norm"]), None)
    unit_hit_any = next((u for u in artifacts["units"] if qn and qn in u["norm"]), None)
    chunk_hit_any = next(
        (c for c in artifacts["chunks"] if qn and qn in c["norm"]), None
    )
    # 存在性按**全文归一拼接**判定（去空白后跨行/跨单元连续即视为存在）；
    # 单单元/单块命中用于区分"落在单块"与"跨块边界"。
    in_concat = bool(qn) and qn in artifacts["doc_norm"]

    hit = hits_by_source.get(src.get("corpus_source_id") or "")
    offered_locators = list(hit["offered_locators"]) if hit else []
    offered_contains = bool(
        hit
        and any(
            qn and qn in artifacts["chunk_by_locator"].get(loc, {}).get("norm", "")
            for loc in offered_locators
        )
    )
    source_in_hits = hit is not None

    # 单元格坐标：只看**提示页**命中的单元（短引文在其它页的同名数字不代表本表结构）。
    cell_unit = unit_hit if unit_hit is not None else unit_hit_any
    # 引文未连续出现时，检查其分词是否都在全文里（区分"原文缺失"与"只是阅读序/栏序不连续"）。
    tokens = [t for t in re.split(r"\s+", quote.strip()) if t and len(t) >= 2]
    tokens_present = bool(tokens) and all(norm(t) in artifacts["doc_norm"] for t in tokens)

    flags = {
        "in_concat": in_concat,
        "in_single_unit_any": unit_hit_any is not None,
        "in_single_unit_tip_page": unit_hit is not None,
        "in_single_chunk_any": chunk_hit_any is not None,
        "in_single_chunk_tip_page": chunk_hit is not None,
        "page_hint": page_hint,
        "source_in_search_hits": source_in_hits,
        "quote_in_offered_chunk": offered_contains,
        "is_table_target": is_table,
        "cell_unit_id": cell_unit["unit_id"] if cell_unit else None,
        "cell_unit_page": cell_unit["page"] if cell_unit else None,
        "table_has_cell_coords": bool(cell_unit and cell_unit["n_cells"] > 0),
        "tokens_present": tokens_present,
        "token_count": len(tokens),
    }
    if unit_hit_any is not None and page_hint is not None and unit_hit is None:
        flags["located_off_tip_page"] = [unit_hit_any["page"]]

    if not in_concat:
        if tokens_present:
            # 分词都在全文，但连续串不在 → 阅读序／栏序不连续（表格或跨栏），归结构错误。
            code = "structure_error"
            flags["structure_reason"] = "read_order_not_contiguous"
        else:
            code = "source_text_missing"
    elif chunk_hit_any is None:
        code = "chunking_impact"
    elif is_table and not flags["table_has_cell_coords"]:
        code = "structure_error"
        flags["structure_reason"] = "table_cell_coords_absent"
    elif not offered_contains:
        code = "retrieval_not_offered"
    else:
        code = "ok"

    rec = {
        "target_id": target.get("target_id"),
        "role": target.get("role"),
        "tier": "supplementary" if extra else "required",
        "source_id": target.get("source_id"),
        "locator": locator,
        "is_table": is_table,
        "quote_chars": len(quote),
        "quote_head": quote[:40].replace("\n", "\\n"),
        "primary_code": code,
        "flags": flags,
        "containing_unit": unit_hit_any["unit_id"] if unit_hit_any else None,
        "containing_unit_page": unit_hit_any["page"] if unit_hit_any else None,
        "containing_chunk": chunk_hit_any["chunk_id"] if chunk_hit_any else None,
        "containing_chunk_kind": chunk_hit_any["kind"] if chunk_hit_any else None,
        "search_source_rank": hit["rank"] if hit else None,
        "offered_locator_count": len(offered_locators),
    }
    if code == "chunking_impact":
        crossed = crossed_units(artifacts, qn)
        rec["crossed_units"] = crossed
        rec["crossed_chunk_kinds"] = sorted(
            {k for c in crossed for k in c["chunk_kinds"]}
        )
        rec["crossed_pages"] = sorted({c["page"] for c in crossed if c["page"]})
    return rec


async def main() -> None:
    gold = load_gold()
    gold_source_ids = {
        t["source_id"]
        for row in gold
        for t in (row.get("evidence_targets") or [])
        + (row.get("supplementary_evidence_targets") or [])
    }
    registry = get_builtin_tools()
    search = registry["corpus_search"]

    with psycopg.connect(dsn()) as conn:
        ro = conn.execute("SHOW transaction_read_only").fetchone()[0]
        db = conn.execute("SELECT current_database()").fetchone()[0]
        assert ro == "on", f"transaction_read_only={ro!r}"
        assert db == "postgres", f"current_database={db!r}"
        resolved = resolve_sources(conn, gold_source_ids)
        artifacts: dict[str, dict] = {}
        for gid, info in resolved.items():
            if info["build_id"]:
                art = load_source_artifacts(conn, info["build_id"])
                art["_resolved"] = info
                artifacts[gid] = art

    # 固定查询：问题原文 → 真实 corpus_search（零模型）
    queries: dict[str, dict] = {}
    for row in gold:
        qid = row["query_id"]
        raw = await search.ainvoke({"query": row["question"], "limit": 10})
        try:
            payload = json.loads(raw)
        except (TypeError, ValueError):
            payload = {}
        hits = payload.get("hits") or []
        hits_by_source: dict[str, dict] = {}
        for rank, h in enumerate(hits):
            sid = str(h.get("source_id") or "")
            locs = [str(x) for x in (h.get("context_locators") or [])]
            if not sid:
                continue
            prev = hits_by_source.get(sid)
            if prev is None:
                hits_by_source[sid] = {
                    "rank": rank,
                    "doc_id": str(h.get("doc_id") or ""),
                    "offered_locators": list(dict.fromkeys(locs)),
                }
            else:
                prev["offered_locators"] = list(
                    dict.fromkeys(prev["offered_locators"] + locs)
                )
        queries[qid] = {
            "question": row["question"],
            "domain": row.get("domain"),
            "answer_existence": row.get("answer_existence"),
            "hits": len(hits),
            "hit_sources": sorted(hits_by_source),
            "hits_by_source": hits_by_source,
        }

    target_rows: list[dict] = []
    for row in gold:
        qid = row["query_id"]
        for tier, key in (
            ("required", "evidence_targets"),
            ("supplementary", "supplementary_evidence_targets"),
        ):
            for t in row.get(key) or []:
                gid = t["source_id"]
                art = artifacts.get(gid)
                if art is None:
                    target_rows.append(
                        {
                            "query_id": qid,
                            "target_id": t.get("target_id"),
                            "tier": tier,
                            "source_id": gid,
                            "primary_code": "source_unresolved",
                            "flags": {},
                        }
                    )
                    continue
                rec = attr_target(
                    t,
                    tier == "supplementary",
                    qid,
                    art,
                    queries[qid]["hits_by_source"],
                )
                rec["query_id"] = qid
                rec["domain"] = row.get("domain")
                rec["answer_existence"] = row.get("answer_existence")
                target_rows.append(rec)

    code_counts = Counter(r["primary_code"] for r in target_rows)
    by_tier = {
        tier: Counter(
            r["primary_code"] for r in target_rows if r.get("tier") == tier
        )
        for tier in ("required", "supplementary")
    }
    by_domain = {
        dom: Counter(
            r["primary_code"] for r in target_rows if r.get("domain") == dom
        )
        for dom in sorted({r.get("domain") for r in target_rows if r.get("domain")})
    }
    structure_reasons = Counter(
        r["flags"].get("structure_reason")
        for r in target_rows
        if r["primary_code"] == "structure_error"
    )
    chunk_span_units = [
        r["flags"].get("token_count")
        for r in target_rows
        if r["primary_code"] == "chunking_impact"
    ]
    chunking_crossed_kinds = Counter(
        k
        for r in target_rows
        if r["primary_code"] == "chunking_impact"
        for k in r.get("crossed_chunk_kinds", [])
    )

    defect_notes = {
        "structure_error": (
            "分两类：(a) ``table_cell_coords_absent``——金标声明表格 row/col/cell 结构，"
            "但来源活动 build 的**提示页单元** location.cells 为空，单元格坐标未保留，"
            "无法按 (页,行,列) 复核；(b) ``read_order_not_contiguous``——引文分词都在全文，"
            "但连续串不在——阅读序／栏序不连续（表格跨栏或续表拼接）。"
        ),
        "retrieval_not_offered": (
            "证据位于单一 chunk，但固定查询（问题原文）的检索命中未提供覆盖它的块。"
            "本次实测为 0：命中文档的 offered 上下文覆盖了该文档全部块，"
            "故凡落在单块且该文档命中者均视为已 offered。"
        ),
        "chunking_impact": (
            "证据存在于全文拼接，但未落在任何单个 chunk——跨块边界，单次取证取不回逐字引文。"
            "实测多为正文段落被拆进相邻 heading/body 块。"
        ),
        "source_text_missing": (
            "证据 quote 在权威原文单元中逐字找不到。本次实测为 0（唯一候选经查"
            "属阅读序不连续，已改判结构错误）。"
        ),
    }

    result = {
        "artifact": "b0-attribution",
        "version": 1,
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").UTC
        ).isoformat(),
        "scope": "preparation/retrieval attribution, zero model, read-only PG",
        "probe": {
            "transaction_read_only": ro,
            "current_database": db,
            "gold_rows": len(gold),
            "gold_targets": len(target_rows),
            "gold_sources": len(gold_source_ids),
        },
        "gold_usage": (
            "金标用于固定样本与逐 target 归因；固定查询=问题原文，不进入模型决策；"
            "这不是独立盲测。"
        ),
        "policy": {
            "gold": str(GOLD.relative_to(ROOT)),
            "gold_sha256": hashlib.sha256(GOLD.read_bytes()).hexdigest()[:16],
            "query": "corpus_search(query=question, limit=10)",
            "normalization": "去除全部空白（含换行/全角/零宽）后比较",
            "precedence": [
                "source_text_missing",
                "chunking_impact",
                "structure_error",
                "retrieval_not_offered",
                "ok",
            ],
        },
        "defect_notes": defect_notes,
        "resolved_sources": {
            gid: {
                "corpus_source_id": info["corpus_source_id"],
                "build_id": info["build_id"],
                "units": len(artifacts[gid]["units"]) if gid in artifacts else 0,
                "chunks": len(artifacts[gid]["chunks"]) if gid in artifacts else 0,
                "units_with_cells": artifacts[gid]["units_with_cells"]
                if gid in artifacts
                else 0,
            }
            for gid, info in resolved.items()
        },
        "summary": {
            "primary_code_counts": dict(code_counts),
            "by_tier": {k: dict(v) for k, v in by_tier.items()},
            "by_domain": {k: dict(v) for k, v in by_domain.items()},
            "structure_reasons": dict(structure_reasons),
            "chunking_span_token_counts": sorted(chunk_span_units),
            "chunking_crossed_chunk_kinds": dict(chunking_crossed_kinds),
            "targets": len(target_rows),
        },
        "queries": queries,
        "targets": target_rows,
    }
    (OUT / "b0_attribution.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2, default=str).replace(
            dsn(), "<REDACTED>"
        ),
        encoding="utf-8",
    )
    print(json.dumps(result["probe"], ensure_ascii=False, indent=2))
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print("models_absent", not any(x in sys.modules for x in ["openai", "anthropic"]))


if __name__ == "__main__":
    asyncio.run(main())