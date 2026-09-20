"""I3-3 议题 A 实测：连续块区间取回（band interval retrieval）能否使 11 条 kept_page_not_selected → matched。

诊断性质（非冻结回归）：
- 冻结资产（manifest/query-gold/projection/source-gold/apply-decisions）逐字节核验；
  scorer 用工作树空白规约版（同 i38 reshape），血缘在内存补丁（磁盘 manifest 不动）。
- 只读 PG + 0 model_calls；产物 write-once 写入本目录。

议题 A 语义（topic-a-chunk-evidence-granularity.md §4）：
- **不调 cap**：max_chunks_per_top_document 语义保持 8，但取回单位从"单块 top-N"改为"带区间"
  （I-A3：取回连续块区间）。带数上限 = 8。
- **不得按金标词/页/行列补取**：带完全由 OR 词元命中（池内块）形成，金标引文不参与检索。
- **不做整篇文档取回**：只取回带区间内块。

带规则（本脚本参数，G=1/K=1 为主口径，附敏感性扫描）：
- 池内块（OR 命中）按原文序（min unit ordinal）聚簇：相邻池块间非池块 ≤ G 则同带；
- 每带两端各扩展 K 块；
- 带排名 = 簇内最大 ts_rank；每文档取带数上限 = BAND_CAP；
- 带内块按原文序拼接为单一 FetchedEvidence，locator = 带内覆盖页集合。

对照层：base（前 8 块/文档 × 页级 locator，与 i37 同口径）。
负例：沿用 S4 窄检索（literal AND，无命中→空观测），确保误报不增。
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
I33 = BASE / "audits/20260920-i33-calibration"
I38 = BASE / "audits/20260920-i38-reshape"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

import calibrate  # noqa: E402  reuse group_hits（文档选择保持同一语义）

SANDBOX = "i2_sandbox_corpus"
BASE_PER_DOC = 8  # base 层：每文档前 8 块（与 i37 对齐）
MAX_CHUNKS_PER_SOURCE = 300  # 每来源池块上限；超过即拒绝（cap saturation 纪律）

# 议题 A 主口径参数
BAND_GAP = 1      # 相邻池块间允许的最大非池块数（空隙容忍）
BAND_EXPAND = 1   # 带两端各扩展块数
BAND_CAP = 8      # 每文档选带数上限（cap=8 的带语义）

# 议题 A 的 11 条（topic-a-chunk-evidence-granularity.md §2）
TOPIC_A_TARGETS = [
    ("company-004", "e2"), ("company-004", "a-2"), ("company-004", "a-3"),
    ("company-005", "e2"), ("company-005", "e3"),
    ("company-008", "a-2"), ("company-008", "a-3"), ("company-008", "a-5"),
    ("macro-002", "e4"), ("macro-003", "a-2"), ("macro-003", "a-4"),
]

SENSITIVITY = [(1, 1), (1, 2), (2, 2), (2, 3)]


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(name: str, value) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"write-once conflict: {name}")
    path.write_bytes(raw)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def norm(s: object) -> str:
    return "".join(ch for ch in s if not ch.isspace()) if isinstance(s, str) else ""


def min_ordinal(refs: list) -> int:
    vals = []
    for ref in refs or []:
        try:
            vals.append(int(str(ref).rsplit(":", 1)[-1]))
        except ValueError:
            pass
    return min(vals) if vals else 10**9


def load_build_chunks(conn, build_id: str) -> tuple[list[str], dict[str, dict]]:
    """一次查询取回 build 全量块：原文序 chunk_id 列表 + 每块 {text, pages, min_ord}。

    ``text`` 为块内单元按 ordinal 的 ``"\\n"`` 拼接（与 read_pg.fetch_verbatim 同语义，
    仅用于带覆盖的可行性前缀检索；证据仍走 fetch_verbatim 权威路径）。
    """
    rows = conn.execute(
        "SELECT c.chunk_id, c.unit_refs FROM corpus.corpus_chunks c WHERE c.build_id = %s",
        (build_id,)).fetchall()
    units = conn.execute(
        "SELECT u.unit_id, u.raw_text, u.ordinal, u.location->>'page' "
        "FROM corpus.corpus_units u WHERE u.build_id = %s "
        "ORDER BY u.ordinal NULLS LAST, u.unit_id",
        (build_id,)).fetchall()
    text_by_unit = {}
    page_by_unit = {}
    for unit_id, raw_text, ordinal, page in units:
        text_by_unit[str(unit_id)] = str(raw_text or "")
        page_by_unit[str(unit_id)] = int(page) if page is not None else None
    ordered: list[str] = []
    meta: dict[str, dict] = {}
    for chunk_id, refs in rows:
        cid = str(chunk_id)
        texts = [text_by_unit[r] for r in (refs or ()) if r in text_by_unit]
        if not texts:
            continue
        pages = sorted({page_by_unit[r] for r in (refs or ()) if r in text_by_unit
                        and page_by_unit[r] is not None})
        meta[cid] = {"text": "\n".join(texts), "pages": pages,
                     "min_ord": min_ordinal(refs)}
    for cid in sorted(meta, key=lambda c: meta[c]["min_ord"]):
        ordered.append(cid)
    return ordered, meta


def form_bands(pool_positions: list[int], score_by_pos: dict[int, float], n: int,
               gap: int, expand: int) -> list[dict]:
    """池内位置聚簇 → 带区间（原文序闭区间 [start, end]），带分 = 簇内最大 ts_rank。

    ``pool_positions`` 已按原文序排序。相邻池位置间隔（非池块数）≤ gap 视为同簇；
    每簇两端各扩展 expand 块。返回按位置排序的带，字段 {start, end, score, pool: [...]}。
    """
    clusters: list[list[int]] = []
    for p in pool_positions:
        if clusters and p - clusters[-1][-1] - 1 <= gap:
            clusters[-1].append(p)
        else:
            clusters.append([p])
    bands = []
    for cl in clusters:
        start = max(0, cl[0] - expand)
        end = min(n - 1, cl[-1] + expand)
        bands.append({"start": start, "end": end,
                      "score": max(score_by_pos[p] for p in cl),
                      "pool": list(cl)})
    return bands


def rank_bands(bands: list[dict]) -> dict[int, int]:
    """带分降序排名（并列按带起点）；返回 {带在 bands 中的索引: 排名(1-based)}。"""
    order = sorted(range(len(bands)), key=lambda i: (-bands[i]["score"], bands[i]["start"]))
    return {idx: rank + 1 for rank, idx in enumerate(order)}


def build_observation_band(query_id, doc_hits: dict, bands_by_source: dict,
                           fetch_cid, aliases):
    """按已选带装配观测：每带拼接为单一 FetchedEvidence，locator = 带内页集合。

    ``bands_by_source``: {source_id: [band, ...]}（已按带分降序取前 BAND_CAP 个；
    每带含 ``chunk_ids`` = 原文序带内全部块 id，含扩展的非池块）。
    """
    from plugins.corpus.scoring import (FetchedEvidence, QueryObservation,
                                        RetrievedDocument, ObservationOutcome)

    documents = []
    for source_id, bands in bands_by_source.items():
        evidences: list[FetchedEvidence] = []
        for band in bands:
            texts: list[str] = []
            pages: set[int] = set()
            for cid in band["chunk_ids"]:
                ev = fetch_cid(band["build_id"], cid)
                texts.append(ev.text)
                for unit in ev.units:
                    if unit.page is not None:
                        pages.add(unit.page)
            locator = tuple(f"page:{p}" for p in sorted(pages))
            evidences.append(FetchedEvidence("\n".join(texts), locator, True))
        documents.append(RetrievedDocument(
            aliases.get(source_id, source_id), tuple(evidences),
            doc_hits[source_id][0].build_id))
    return QueryObservation(query_id,
                            ObservationOutcome.OK if documents else ObservationOutcome.NO_MATCH,
                            tuple(documents))


def build_observation_base(query_id, grouped, fetch, aliases):
    """与 i37/i38 同口径：每块按页分组成证据（base 对照层）。"""
    from plugins.corpus.scoring import (FetchedEvidence, QueryObservation,
                                        RetrievedDocument, ObservationOutcome)

    documents = []
    for source_id, hits in grouped.items():
        evidences: list[FetchedEvidence] = []
        for hit in hits:
            chunk = fetch(hit)
            pages: dict[int, list[str]] = {}
            for unit in chunk.units:
                pages.setdefault(unit.page, []).append(unit.raw_text)
            for page, texts in pages.items():
                evidences.append(FetchedEvidence(
                    "\n".join(texts),
                    (f"page:{page}",) if page is not None else (),
                    True))
        documents.append(RetrievedDocument(
            aliases.get(source_id, source_id), tuple(evidences), hits[0].build_id))
    return QueryObservation(query_id,
                            ObservationOutcome.OK if documents else ObservationOutcome.NO_MATCH,
                            tuple(documents))


def main() -> int:
    # ── 1. 冻结资产核验（除工作树 scorer 外与 r39 一致，同 i37/i38 口径）──
    plan = json.loads((I33 / "calibration-plan-v2.json").read_text())
    for rel, sha in plan["binding"].items():
        if rel == "plugins/corpus/scoring.py":
            continue  # 工作树 scorer 是本回测观察对象
        if digest(ROOT / rel) != sha:
            raise RuntimeError(f"Frozen asset drift vs r39 (except scorer): {rel}")
    release = load_module("i31_region_release", BASE / "audits/20260920-i31-region-review/release.py")
    dsn = release.connect()

    loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")
    applier = loader.load_module(BASE / "i3s2_apply_decisions.py", "i33_approved_input")
    scorer_sha = digest(ROOT / "plugins/corpus/scoring.py")
    manifest_dict = json.loads(loader.MANIFEST.read_text(encoding="utf-8"))
    diag_manifest = copy.deepcopy(manifest_dict)
    diag_manifest["lineage"]["scorer"]["sha256"] = scorer_sha
    errors = loader.validate(records, loader.load_jsonl(loader.QUERY_GOLD),
                             json.loads(loader.PROJECTION.read_text()),
                             loader.load_jsonl(loader.SOURCE_GOLD),
                             diag_manifest, applier)
    if errors:
        raise RuntimeError(f"Frozen scoring assets invalid: {errors}")
    write_once("binding.json", {
        "kind": "diagnostic (NOT a frozen regression)",
        "scorer_working_tree_sha256": scorer_sha,
        "frozen_assets_ok": True,
        "manifest_lineage_scorer": "patched in-memory to working-tree hash (disk manifest untouched)",
        "band_semantics": {
            "gap": BAND_GAP, "expand": BAND_EXPAND, "band_cap": BAND_CAP,
            "cap_is_band_count": "max_chunks_per_top_document(8) 语义改为带数；不调 cap 值",
            "selection": "带由 OR 词元命中池形成；不按金标词/页/行列补取",
        },
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    })

    from plugins.corpus.scoring import (AnswerExistence, gold_from_records, ScoringPolicy,
                                        score, format_report)
    from plugins.corpus.preparation.search_pg import search_chunks, _check_target
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.read_pg import (fetch_verbatim, build_handle, chunk_locator)
    from plugins.corpus.preparation.contract import UnitStatus
    from plugins.corpus.preparation.repository_pg import PgStore
    import psycopg

    questions = gold_from_records(records)
    config = dict(plan["policy"])
    config["min_rate"] = Fraction(config["min_rate"])
    policy = ScoringPolicy(**config)

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX)

        def snapshot():
            return dict(conn.execute(
                "SELECT source_id, active_build_id FROM corpus.corpus_publications "
                "WHERE active_build_id IS NOT NULL").fetchall())

        sources = snapshot()
        if len(sources) != 8:
            raise RuntimeError(f"Active corpus has {len(sources)} sources (expected 8)")

        aliases = {}
        expected_aliases = {s for q in questions for s in q.relevant_sources}
        expected_aliases |= {t.source_id for q in questions for t in q.evidence_targets if t.source_id}
        for alias in expected_aliases:
            matches = [source for source in sources if source.startswith(alias.rsplit("_", 1)[-1])]
            if len(matches) != 1:
                raise RuntimeError(f"Gold alias cannot resolve uniquely: {alias}")
            if matches[0] in aliases and aliases[matches[0]] != alias:
                raise RuntimeError("Multiple gold aliases for one source")
            aliases[matches[0]] = alias
        alias_to_source = {alias: src for src, alias in aliases.items()}
        write_once("source-identity-map.json", {"aliases": aliases, "active_builds": sources})

        # kept 单元按 build → page 缓存（与 i35/i37 同口径：仅 KEPT）
        kept_pages: dict[str, dict[int, str]] = {}
        doc_text: dict[str, str] = {}
        with PgStore(dsn, sandbox_db=SANDBOX) as store:
            for src, build_id in sources.items():
                pages: dict[int, list[str]] = {}
                for u in store.get_units(build_id):
                    if u.status is UnitStatus.KEPT and u.location.page is not None:
                        pages.setdefault(u.location.page, []).append(u.raw_text)
                kept_pages[build_id] = {pg: "\n".join(ls) for pg, ls in pages.items()}
        for build_id in sources.values():
            doc_text[build_id] = "\n".join(t for t in kept_pages[build_id].values())

        # build 全量块缓存（原文序 + 每块文本/页，供带形成与覆盖检索）
        build_cache: dict[str, tuple[list[str], dict[str, dict]]] = {}

        def ordered_meta(build_id: str):
            if build_id not in build_cache:
                build_cache[build_id] = load_build_chunks(conn, build_id)
            return build_cache[build_id]

        cache: dict = {}
        receipts: dict = {}

        def fetch(hit):
            key = (hit.build_id, hit.chunk_id)
            if key not in cache:
                cache[key] = fetch_verbatim(dsn, build_handle(hit.build_id),
                                            chunk_locator(hit.chunk_id))
                receipts["/".join(key)] = asdict(cache[key])
            return cache[key]

        def fetch_cid(build_id: str, chunk_id: str):
            key = (build_id, chunk_id)
            if key not in cache:
                cache[key] = fetch_verbatim(dsn, build_handle(build_id),
                                            chunk_locator(chunk_id))
                receipts["/".join(key)] = asdict(cache[key])
            return cache[key]

        def or_query(conn, question: str) -> str:
            lexemes = conn.execute("SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                                   (normalize_search_text(question),)).fetchone()[0]
            if not lexemes:
                raise RuntimeError("Question tokenization produced no terms")
            return " OR ".join('"' + term.replace('"', ' ') + '"' for term in lexemes)

        traces = []
        obs_base: dict[str, object] = {}
        obs_band: dict[str, object] = {}
        band_trace: dict[str, object] = {}
        for question in questions:
            if question.answer_existence is AnswerExistence.NO_ANSWER:
                # S4：负例专用窄检索（literal AND）→ 空观测
                hits = search_chunks(dsn, question.question, limit=2000)
                empty_obs = build_observation_base(
                    question.query_id, {}, fetch, aliases)
                obs_base[question.query_id] = empty_obs
                obs_band[question.query_id] = empty_obs
                traces.append({"query_id": question.query_id, "mode": "s4_literal_and",
                               "executed_query": question.question, "chunk_hits": len(hits)})
                continue
            # 有答案题：OR 词元主检索
            query = or_query(conn, question.question)
            hits = search_chunks(dsn, query, limit=2000)
            if len(hits) >= 2000:
                raise RuntimeError("Candidate cap saturated; cannot certify document top-k")
            grouped_base = calibrate.group_hits(hits, policy.top_k, BASE_PER_DOC)
            # 文档选择保持 group_hits 语义（前 top_k 来源）；对每个选中来源做带选择
            doc_hits: dict[str, list] = {}
            bands_by_source: dict[str, list] = {}
            for source_id in grouped_base:
                all_hits = [h for h in hits if h.source_id == source_id]
                if len(all_hits) > MAX_CHUNKS_PER_SOURCE:
                    raise RuntimeError(f"Saturation: {source_id} has {len(all_hits)} hits")
                doc_hits[source_id] = all_hits
                build_id = all_hits[0].build_id
                ordered, meta = ordered_meta(build_id)
                pos_of = {cid: i for i, cid in enumerate(ordered)}
                pool_positions = sorted(pos_of[h.chunk_id] for h in all_hits)
                score_by_pos = {pos_of[h.chunk_id]: h.score for h in all_hits}
                bands = form_bands(pool_positions, score_by_pos, len(ordered),
                                   BAND_GAP, BAND_EXPAND)
                ranking = rank_bands(bands)
                selected = sorted(
                    (bands[i] for i in ranking if ranking[i] <= BAND_CAP),
                    key=lambda b: (-b["score"], b["start"]))
                for band in selected:
                    band["build_id"] = build_id
                    band["chunk_ids"] = [ordered[p]
                                         for p in range(band["start"], band["end"] + 1)]
                bands_by_source[source_id] = selected
            obs_base[question.query_id] = build_observation_base(
                question.query_id, grouped_base, fetch, aliases)
            obs_band[question.query_id] = build_observation_band(
                question.query_id, doc_hits, bands_by_source, fetch_cid, aliases)
            traces.append({"query_id": question.query_id, "mode": "or_main",
                           "input_question": question.question, "executed_query": query,
                           "chunk_hits": len(hits),
                           "base_selected": {s: len(h) for s, h in grouped_base.items()},
                           "band_selected": {s: [{"start": b["start"], "end": b["end"],
                                                  "score": round(b["score"], 6),
                                                  "chunks": len(b["chunk_ids"])}
                                                 for b in bs]
                                             for s, bs in bands_by_source.items()}})
            band_trace[question.query_id] = traces[-1]
            if snapshot() != sources:
                raise RuntimeError("Active publication changed during re-run")

        if snapshot() != sources:
            raise RuntimeError("Active publication changed during re-run")

        report_base = score(questions, list(obs_base.values()), policy)
        report_band = score(questions, list(obs_band.values()), policy)

        # ── 3. 逐目标分层定位（band 观测为准）+ 桶分类 ──
        def first_matched_layer(q, target, allowed) -> str | None:
            for label, obs in (("base", obs_base), ("band", obs_band)):
                obs_q = obs.get(q.query_id)
                if obs_q is None:
                    continue
                if any(target.matches(ev) and doc.source_id in allowed
                       for doc in obs_q.documents for ev in doc.evidence):
                    return label
            return None

        diagnostics = []
        for q in questions:
            relevant = set(q.relevant_sources)
            obs_q = obs_band.get(q.query_id)
            for target in q.evidence_targets:
                allowed = (target.source_id,) if target.source_id else tuple(relevant)
                row = {"query_id": q.query_id, "target_id": target.target_id,
                       "domain": q.domain, "quote": target.quote, "locator": list(target.locator),
                       "source_id": target.source_id}
                page = None
                for tok in target.locator:
                    if tok.startswith("page:"):
                        page = int(tok.split(":", 1)[1])
                        break
                layer = first_matched_layer(q, target, allowed)
                row["layer"] = layer
                if layer is not None:
                    row["matched"] = True
                    row["bucket"] = "matched"
                    diagnostics.append(row)
                    continue
                row["matched"] = False
                selected_text = "\n".join(
                    ev.text for doc in (obs_q.documents if obs_q else ()) for ev in doc.evidence)
                in_selected = norm(target.quote) in norm(selected_text)
                src = target.source_id or (next(iter(relevant), None))
                live_src = alias_to_source.get(src)
                build_id = sources.get(live_src) if live_src else None
                in_kept_page = in_kept_any = in_doc = False
                if build_id:
                    if page is not None:
                        in_kept_page = norm(target.quote) in norm(kept_pages.get(build_id, {}).get(page, ""))
                    in_kept_any = any(norm(target.quote) in norm(t)
                                      for t in kept_pages.get(build_id, {}).values())
                    in_doc = norm(target.quote) in norm(doc_text.get(build_id, ""))
                row.update({"in_selected_evidence": in_selected,
                            "in_kept_declared_page": in_kept_page,
                            "in_kept_anywhere": in_kept_any,
                            "in_doc_full": in_doc})
                if in_selected:
                    row["bucket"] = "selected_but_match_fail"
                elif in_kept_page:
                    row["bucket"] = "kept_page_not_selected"
                elif in_kept_any:
                    row["bucket"] = "kept_elsewhere_page_mismatch"
                elif in_doc:
                    row["bucket"] = "doc_not_kept_clean_stage_loss"
                else:
                    row["bucket"] = "not_in_doc_unreachable"
                diagnostics.append(row)

        # ── 4. 议题 A：11 条带覆盖可行性（含敏感性扫描）──
        row_lookup = {(d["query_id"], d["target_id"]): d for d in diagnostics}
        feasibility = []
        for qid, tid in TOPIC_A_TARGETS:
            drow = row_lookup[(qid, tid)]
            question = next(q for q in questions if q.query_id == qid)
            target = next(t for t in question.evidence_targets if t.target_id == tid)
            sha = alias_to_source.get(target.source_id or "")
            build_id = sources.get(sha) if sha else None
            entry = {"query_id": qid, "target_id": tid, "matched_band": drow["matched"],
                     "layer": drow["layer"]}
            if not build_id:
                entry["error"] = "no active build"
                feasibility.append(entry)
                continue
            ordered, meta = ordered_meta(build_id)
            chunks = [norm(meta[cid]["text"]) for cid in ordered]
            quote = norm(target.quote)
            pref = [""]
            for c in chunks:
                pref.append(pref[-1] + c)
            pos = pref[-1].find(quote)
            entry["quote_len"] = len(quote)
            if pos < 0:
                entry["cover"] = None
                feasibility.append(entry)
                continue
            end = pos + len(quote) - 1
            a = next(i for i in range(len(chunks)) if len(pref[i + 1]) > pos)
            b = next(i for i in range(len(chunks)) if len(pref[i + 1]) > end)
            entry["cover"] = [a, b]
            # 池内位置（同题 hits）
            query = or_query(conn, question.question)
            hits = search_chunks(dsn, query, limit=2000)
            pool = {h.chunk_id for h in hits if h.source_id == sha}
            pos_of = {cid: i for i, cid in enumerate(ordered)}
            pool_positions = sorted(pos_of[c] for c in pool if c in pos_of)
            score_by_pos = {pos_of[h.chunk_id]: h.score
                            for h in hits if h.source_id == sha and h.chunk_id in pos_of}
            entry["pool"] = len(pool_positions)
            sensitivity = []
            for gap, expand in SENSITIVITY:
                bands = form_bands(pool_positions, score_by_pos, len(ordered), gap, expand)
                ranking = rank_bands(bands)
                cover_band = next((i for i, band in enumerate(bands)
                                   if band["start"] <= a and b <= band["end"]), None)
                if cover_band is None:
                    sensitivity.append({"gap": gap, "expand": expand,
                                        "coverable": False, "rank": None,
                                        "selected_in_band_cap": False})
                    continue
                rank = ranking[cover_band]
                sel = rank <= BAND_CAP
                splice_ok = None
                if sel:
                    band = bands[cover_band]
                    text = "\n".join(meta[ordered[p]]["text"]
                                     for p in range(band["start"], band["end"] + 1))
                    splice_ok = quote in norm(text)
                sensitivity.append({"gap": gap, "expand": expand,
                                    "coverable": True, "rank": rank,
                                    "band_span": [bands[cover_band]["start"],
                                                  bands[cover_band]["end"]],
                                    "selected_in_band_cap": sel,
                                    "splice_contains_quote": splice_ok})
            entry["sensitivity"] = sensitivity
            feasibility.append(entry)

        # ── 5. 负例（no-answer）S4 结果 ──
        neg = []
        for q in questions:
            o = obs_band[q.query_id]
            if q.answer_existence is AnswerExistence.NO_ANSWER:
                docs = [{"source_id": d.source_id,
                         "evidence_preview": [ev.text[:140] for ev in d.evidence][:2]}
                        for d in o.documents] if o else []
                neg.append({"query_id": q.query_id, "question": q.question,
                            "retrieved_documents": len(docs), "docs": docs})

        write_once("i39-trace.json", traces)
        write_once("i39-band-trace.json", band_trace)
        write_once("i39-observations.json", [asdict(o) for o in obs_band.values()])
        write_once("i39-feasibility.json", feasibility)
        write_once("i39-score.json", asdict(report_band))
        (HERE / "i39-score.md").write_text(format_report(report_band) + "\n")
        write_once("fetch-receipts.json", receipts)
        write_once("i39-diagnostics.json", diagnostics)
        write_once("negative-cases.json", {
            "note": "no-answer questions under S4 narrow (literal AND) retrieval",
            "cases": neg})

        buckets = Counter(d["bucket"] for d in diagnostics)
        topic_a_status = {f"{d['query_id']} {d['target_id']}": {
            "matched": d["matched"], "layer": d["layer"]}
            for d in diagnostics if (d["query_id"], d["target_id"]) in TOPIC_A_TARGETS}
        topic_a_matched = sum(1 for d in diagnostics
                              if (d["query_id"], d["target_id"]) in TOPIC_A_TARGETS and d["matched"])

        def layer_summary(report) -> dict:
            return {
                "passed": report.passed,
                "per_class": [{"domain": c.domain, "doc_recall": str(c.doc_recall.rate),
                               "question_pass": f"{c.question_pass.passed}/{c.question_pass.total}",
                               "evidence_pass": f"{c.evidence_pass.passed}/{c.evidence_pass.total}"}
                              for c in report.classes],
                "evidence_pass_total": f"{sum(c.evidence_pass.passed for c in report.classes)}/"
                                       f"{sum(c.evidence_pass.total for c in report.classes)}",
                "false_positives": report.false_positives,
                "fabricated_citations": report.fabricated_citations,
                "critical_failures": report.critical_failures,
            }

        summary = {
            "artifact": "i3-9-topic-a-band",
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "kind": "diagnostic", "corpus": "reader-pdf-5 reingest active (8 builds)",
            "scorer": "working-tree whitespace-norm (NOT frozen)",
            "band_params": {"gap": BAND_GAP, "expand": BAND_EXPAND, "band_cap": BAND_CAP},
            "layers": {
                "base": layer_summary(report_base),
                "band": layer_summary(report_band),
            },
            "negative": {"s4_false_positives": report_band.false_positives},
            "target_buckets_final": dict(buckets),
            "topic_a": {
                "total": len(TOPIC_A_TARGETS),
                "matched": topic_a_matched,
                "per_target": topic_a_status,
                "band_cap_selected": sum(1 for f in feasibility if any(
                    s.get("selected_in_band_cap") for s in f.get("sensitivity", []))),
            },
            "model_calls": 0,
            "questions": len(questions),
        }
        write_once("i39-summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        # ── 6. MD 报告 ──
        lines = [
            "# I3-3 议题 A 实测：连续块区间取回（band interval retrieval）",
            "",
            f"- 生成：{summary['generated_at']}；类型：诊断（**非冻结回归**）",
            f"- scorer：工作树空白规约版 `{scorer_sha[:12]}`（未冻结未采纳）；评分资产冻结字节已核验",
            f"- corpus：8 份 active builds（reader-pdf-5 重摄入）",
            f"- 带参数：G={BAND_GAP}（空隙容忍）/ K={BAND_EXPAND}（两端扩展）/ 带上限={BAND_CAP}",
            "- 语义边界：不调 cap 值（8=带数）；带由 OR 词元命中池形成；不做整篇文档取回；不按金标词/页/行列补取",
            "",
            "## 逐层对比（有答案题 EvidencePass + 负例误报）",
            "",
            "| 层 | company | industry | macro | 合计 | 负例误报 |",
            "|---|---|---|---|---|---|",
        ]
        for label, rep in (("base（前8块·页级）", report_base),
                           ("band（带区间取回·带数8）", report_band)):
            pcs = {c.domain: f"{c.evidence_pass.passed}/{c.evidence_pass.total}"
                   for c in rep.classes}
            total = f"{sum(c.evidence_pass.passed for c in rep.classes)}/" \
                    f"{sum(c.evidence_pass.total for c in rep.classes)}"
            lines.append(f"| {label} | {pcs.get('company', '-')} | {pcs.get('industry', '-')} | "
                         f"{pcs.get('macro', '-')} | {total} | "
                         f"{len(rep.false_positives)} |")
        lines += [
            "",
            "## 议题 A：11 条带覆盖可行性（主口径 G=1/K=1）",
            "",
            "| 目标 | 引文长 | cover | 池内块 | coverable | 带排名 | 进带数8 | 拼接含引文 | band层匹配 |",
            "|---|---|---:|---:|---|---|---|---|---|",
        ]
        for f in feasibility:
            sens = next((s for s in f.get("sensitivity", [])
                         if s["gap"] == BAND_GAP and s["expand"] == BAND_EXPAND), None)
            if sens is None:
                lines.append(f"| {f['query_id']} {f['target_id']} | {f.get('quote_len', '-')} "
                             f"| {f.get('cover')} | {f.get('pool', '-')} | - | - | - | - | "
                             f"{f['matched_band']} |")
                continue
            lines.append(
                f"| {f['query_id']} {f['target_id']} | {f.get('quote_len', '-')} "
                f"| {f.get('cover')} | {f.get('pool', '-')} | {sens['coverable']} "
                f"| {sens['rank']} | {sens['selected_in_band_cap']} "
                f"| {sens['splice_contains_quote']} | {f['matched_band']} |")
        lines += [
            "",
            "## 敏感性扫描（gap, expand）→ 进带数 8 的目标数",
            "",
        ]
        for gap, expand in SENSITIVITY:
            cnt = sum(1 for f in feasibility
                      for s in f.get("sensitivity", [])
                      if s["gap"] == gap and s["expand"] == expand
                      and s.get("selected_in_band_cap"))
            lines.append(f"- (G={gap}, K={expand})：{cnt}/11 进带数 8")
        lines += [
            "",
            "## 负例（S4 窄检索）",
            "",
        ]
        for case in neg:
            lines.append(f"- {case['query_id']}：命中文档 {case['retrieved_documents']}（期望 0）")
        (HERE / "i39-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
