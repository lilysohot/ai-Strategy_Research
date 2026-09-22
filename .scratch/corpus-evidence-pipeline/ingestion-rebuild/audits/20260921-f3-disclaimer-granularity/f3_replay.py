"""B3 / F3 只读复验：重摄入后 F3（免责节句粒度）是否把 company-007/e1 打到绿。

背景（spec §14.5 F3 / §14.6 B3）：F3 语义（``clean.py`` 免责节含可复核数字事实句
→ 整单元降 KEPT）自 ``i0c-r4p`` 起已在链上冻结，但当时语料未重摄入 ⇒ 目标级
``company-007 e1`` 仍停在 ``not_in_doc_unreachable``（F2 回测口径，2026-09-21 15:40
产物，早于本次重摄入）。2026-09-22 语料按当前字节全量重建（8 active builds，
clean_rev 统一为含 F3 的版本）后，需以**同口径**复验：

1. ``company-007 e1`` 的引文所在单元（贵州茅台 doc ord=717, page 7）现在是否为 KEPT；
2. S0_kept → S1_candidates → S2_doc_topk → S3_band_cover → S4_matched 逐层是否转绿；
3. 分层不退化：S1=66 / S2=60 与 i42 基线一致；S0 预期 77→**78**（F3 仅翻转一个单元）；
4. 负例误报（产品默认开关 off 的 OR 路径）不回升：仍 6（= i42 基线）；
5. 用**产品路径** ``CorpusService.search_bands``（r4n band + r4q 跨边界 + cell 投影）
   复核 company-007 的 e1 同样命中（口径与 F4 replay 的 ``on`` 一致）。

口径（与 i42 / band-product 回测一致，便于逐层相减）：
- 79 目标、perdoc 文档序（band 文档选择与 select 逐字节一致）；
- 查询 = 问题词元 OR 连接；limit=2000 不饱和断言；
- scorer = 工作树空白规约（NOT frozen）；0 model_calls；
- 负例（单变量）：OR 检索路径 + base 选择，FP 判定只看是否有文档被检索（与 F2 同）。

只读 PG（不重摄入、不 publish、不写库）+ 0 model_calls；产物 write-once 写入本目录。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
I33 = AUDITS / "20260920-i33-calibration"
I42 = AUDITS / "20260920-i42-topic-b-reingest"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

import calibrate  # noqa: E402  reuse observations_for（base 对照层）

SANDBOX = "i2_sandbox_corpus"
BASE_PER_DOC = 8
MAX_CHUNKS_PER_SOURCE = 300


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


def load_build_chunk_order(conn, build_id: str) -> tuple[str, ...]:
    """一次查询取回 build 全量块 id（原文序：按块内最小单元 ordinal）。

    仅用于把命中块投影到原文位置（select_band 的 chunk_order_by_source 输入）；
    证据文本仍走 fetch_verbatim 权威路径。
    """
    rows = conn.execute(
        "SELECT c.chunk_id, c.unit_refs FROM corpus.corpus_chunks c WHERE c.build_id = %s",
        (build_id,)).fetchall()
    meta: dict[str, int] = {}
    for chunk_id, refs in rows:
        meta[str(chunk_id)] = min_ordinal(refs)
    return tuple(sorted(meta, key=lambda c: meta[c]))


def chunk_texts(conn, hits: tuple) -> dict[tuple[str, str], str]:
    """批量取 hit chunk 的引用单元 raw_text → ``text_by_chunk``。

    S1_candidates 的候选池文本（与 i42/s2 同口径：引文在**任一 search 命中块**
    内即计入候选）；一次性 SQL 取全部引用单元，含内容哈希自证。
    """
    unit_refs: dict[str, set[str]] = {}
    for hit in hits:
        for uid in hit.unit_refs:
            unit_refs.setdefault(hit.build_id, set()).add(uid)
    raw_by_key: dict[tuple[str, str], str] = {}
    if unit_refs:
        build_ids: list[str] = []
        unit_ids: list[str] = []
        for bid, uids in unit_refs.items():
            for uid in uids:
                build_ids.append(bid)
                unit_ids.append(uid)
        with conn.cursor() as cur:
            cur.execute(
                "SELECT build_id, unit_id, raw_text, content_hash FROM corpus.corpus_units "
                "WHERE (build_id, unit_id) IN "
                "(SELECT b, u FROM unnest(%(bs)s::text[], %(us)s::text[]) AS x(b, u))",
                {"bs": build_ids, "us": unit_ids})
            for bid, uid, raw, chash in cur.fetchall():
                text = str(raw or "")
                if hashlib.sha256(text.encode()).hexdigest() != str(chash or ""):
                    raise RuntimeError(f"权威单元内容哈希不符: {uid} @ {str(bid)[:12]}")
                raw_by_key[(str(bid), str(uid))] = text
    text_by_chunk: dict[tuple[str, str], str] = {}
    for hit in hits:
        parts = [raw_by_key[(hit.build_id, uid)] for uid in hit.unit_refs]
        if len(parts) != len(hit.unit_refs):
            raise RuntimeError(f"候选 chunk 单元悬空: {hit.build_id[:12]}/{hit.chunk_id}")
        text_by_chunk[(hit.build_id, hit.chunk_id)] = "\n".join(parts)
    return text_by_chunk


def main() -> int:
    from plugins.corpus.preparation.selection import (BandPolicy, SelectionPolicy,
                                                      select, select_band)
    from plugins.corpus.scoring import (AnswerExistence, FetchedEvidence, QueryObservation,
                                        RetrievedDocument, ObservationOutcome, gold_from_records,
                                        ScoringPolicy, score, format_report)
    from plugins.corpus.preparation.search_pg import search_chunks, _check_target
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.read_pg import (fetch_verbatim, build_handle, chunk_locator)
    from plugins.corpus.preparation.contract import UnitStatus
    from plugins.corpus.preparation.repository_pg import PgStore
    import psycopg

    assert SelectionPolicy().max_chunks_per_document == 8, "I-B3: cap 必须保持 8"
    band = BandPolicy()
    assert band.band_cap == 8, "I-B3(band): 带数上限必须保持 8"

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()

    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    applier = loader.load_module(INGEST / "i3s2_apply_decisions.py", "i33_approved_input")
    scorer_sha = digest(ROOT / "plugins/corpus/scoring.py")
    import copy
    manifest_dict = json.loads(loader.MANIFEST.read_text(encoding="utf-8"))
    diag_manifest = copy.deepcopy(manifest_dict)
    diag_manifest["lineage"]["scorer"]["sha256"] = scorer_sha
    errors = loader.validate(records, loader.load_jsonl(loader.QUERY_GOLD),
                             json.loads(loader.PROJECTION.read_text()),
                             loader.load_jsonl(loader.SOURCE_GOLD),
                             diag_manifest, applier)
    if errors:
        raise RuntimeError(f"Frozen scoring assets invalid: {errors}")

    questions = gold_from_records(records)
    config = dict(json.loads((I33 / "calibration-plan-v2.json").read_text())["policy"])
    config["min_rate"] = Fraction(config["min_rate"])
    policy = ScoringPolicy(**config)

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX)
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())
        if len(sources) != 8:
            raise RuntimeError(f"Active corpus has {len(sources)} sources (expected 8)")

        aliases = {}
        expected_aliases = {s for q in questions for s in q.relevant_sources}
        expected_aliases |= {t.source_id for q in questions for t in q.evidence_targets
                             if t.source_id}
        for alias in expected_aliases:
            matches = [source for source in sources if source.startswith(alias.rsplit("_", 1)[-1])]
            if len(matches) != 1:
                raise RuntimeError(f"Gold alias cannot resolve uniquely: {alias}")
            if matches[0] in aliases and aliases[matches[0]] != alias:
                raise RuntimeError("Multiple gold aliases for one source")
            aliases[matches[0]] = alias
        alias_to_source = {alias: src for src, alias in aliases.items()}

        kept_pages: dict[str, dict[int, str]] = {}
        with PgStore(dsn, sandbox_db=SANDBOX) as store:
            for src, build_id in sources.items():
                pages: dict[int, list[str]] = {}
                for u in store.get_units(build_id):
                    if u.status is UnitStatus.KEPT and u.location.page is not None:
                        pages.setdefault(u.location.page, []).append(u.raw_text)
                kept_pages[build_id] = {pg: "\n".join(ls) for pg, ls in pages.items()}

        chunk_order_cache: dict[str, tuple[str, ...]] = {}
        for build_id in sources.values():
            chunk_order_cache[build_id] = load_build_chunk_order(conn, build_id)
        # select_band 输入：{source_id: 原文序块 id}
        chunk_order_by_source = {src: chunk_order_cache[build_id]
                                 for src, build_id in sources.items()}

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

        def build_observation_base(query_id, grouped):
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

        def build_observation_band(query_id, bands_by_source):
            """每带拼接为单一 FetchedEvidence（带内全部块原文 + page locator）。"""
            documents = []
            for source_id, bands in bands_by_source.items():
                evidences: list[FetchedEvidence] = []
                for b in bands:
                    texts: list[str] = []
                    pages: set[int] = set()
                    for cid in b["chunk_ids"]:
                        ev = fetch_cid(b["build_id"], cid)
                        texts.append(ev.text)
                        for unit in ev.units:
                            if unit.page is not None:
                                pages.add(unit.page)
                    locator = tuple(f"page:{p}" for p in sorted(pages))
                    evidences.append(FetchedEvidence("\n".join(texts), locator, True))
                documents.append(RetrievedDocument(
                    aliases.get(source_id, source_id), tuple(evidences),
                    bands[0]["build_id"]))
            return QueryObservation(query_id,
                                    ObservationOutcome.OK if documents else ObservationOutcome.NO_MATCH,
                                    tuple(documents))

        traces = []
        obs_base: dict[str, object] = {}
        obs_band: dict[str, object] = {}
        per_query: dict[str, dict] = {}
        max_band_width_measured = 0
        for question in questions:
            query = or_query(conn, question.question)
            hits = search_chunks(dsn, query, limit=2000)
            if question.answer_existence is AnswerExistence.NO_ANSWER:
                # 负例（单变量）：与有答案题同一 OR 检索；FP 判定只取决于是否检索到文档。
                grouped = calibrate.group_hits(hits, policy.top_k, BASE_PER_DOC)
                obs = build_observation_base(question.query_id, grouped)
                obs_base[question.query_id] = obs
                obs_band[question.query_id] = obs
                per_query[question.query_id] = {"hits": hits, "text_by_chunk": {},
                                                "groups": {}}
                traces.append({"query_id": question.query_id,
                               "answer_existence": question.answer_existence.value,
                               "mode": "or_negative",
                               "chunk_hits": len(hits),
                               "hits_saturated": len(hits) >= 2000,
                               "retrieved_documents": len(grouped)})
                continue
            if len(hits) >= 2000:
                raise RuntimeError("Candidate cap saturated; cannot certify document top-k")
            text_by_chunk = chunk_texts(conn, hits)
            grouped_base = calibrate.group_hits(hits, policy.top_k, BASE_PER_DOC)
            obs_base[question.query_id] = build_observation_base(question.query_id, grouped_base)

            # band 变体：文档选择同 select（first occurrence top_k），文档内连续区间取回
            bands_by_source: dict[str, list] = {}
            selected_bands = select_band(hits, SelectionPolicy(), band,
                                         chunk_order_by_source=chunk_order_by_source)
            for sb in selected_bands:
                build_id = sb.build_id
                ordered = chunk_order_cache[build_id]
                chunk_ids = [ordered[p] for p in range(sb.start, sb.end + 1)]
                max_band_width_measured = max(max_band_width_measured, sb.width)
                bands_by_source.setdefault(sb.source_id, []).append({
                    "start": sb.start, "end": sb.end, "score": sb.score,
                    "pool": list(sb.pool), "build_id": build_id,
                    "chunk_ids": chunk_ids,
                })
            assert set(bands_by_source) == set(grouped_base), \
                "band 文档选择须与 base（select）逐文档一致"
            per_query[question.query_id] = {"hits": hits, "text_by_chunk": text_by_chunk,
                                            "groups": bands_by_source}
            obs_band[question.query_id] = build_observation_band(question.query_id, bands_by_source)
            traces.append({"query_id": question.query_id,
                           "answer_existence": question.answer_existence.value,
                           "mode": "or_main",
                           "chunk_hits": len(hits),
                           "base_selected": {s: len(h) for s, h in grouped_base.items()},
                           "band_selected": {s: [{"start": b["start"], "end": b["end"],
                                                  "score": round(b["score"], 6),
                                                  "chunks": len(b["chunk_ids"]),
                                                  "pool": len(b["pool"])}
                                                 for b in bs]
                                             for s, bs in bands_by_source.items()}})

        report_base = score(questions, list(obs_base.values()), policy)
        report_band = score(questions, list(obs_band.values()), policy)

        # ── 逐目标漏斗（band 口径；层级语义与 i42/s2 完全一致）──
        # S0_kept → S1_candidates（引文在 search 召回池任一命中块内）→
        # S2_doc_topk（引文所在文档进 band 选择，= select 逐字节一致）→
        # S3_band_cover（引文在选中带文本内）→ S4_matched。
        funnel_targets = []
        for q in questions:
            obs = obs_band.get(q.query_id)
            pinfo = per_query.get(q.query_id)
            relevant = set(q.relevant_sources)
            for target in q.evidence_targets:
                allowed = (target.source_id,) if target.source_id else tuple(relevant)
                page = None
                for tok in target.locator:
                    if tok.startswith("page:"):
                        page = int(tok.split(":", 1)[1])
                        break
                matched = bool(obs) and any(
                    target.matches(ev) and doc.source_id in allowed
                    for doc in obs.documents for ev in doc.evidence)
                src = target.source_id or (next(iter(relevant), None))
                live_src = alias_to_source.get(src)
                build_id = sources.get(live_src) if live_src else None
                quote = norm(target.quote)

                in_kept_page = in_kept_any = False
                if build_id:
                    if page is not None:
                        in_kept_page = quote in norm(kept_pages.get(build_id, {}).get(page, ""))
                    in_kept_any = any(quote in norm(t)
                                      for t in kept_pages.get(build_id, {}).values())

                # S1：引文在候选块内（search 召回池；与 i42/s2 同口径）
                cand_texts = ([pinfo["text_by_chunk"][(h.build_id, h.chunk_id)]
                               for h in pinfo["hits"] if h.build_id == build_id]
                              if pinfo else [])
                s1 = any(quote in norm(t) for t in cand_texts)

                # S2：引文所在文档进 band 选择（band 文档选择与 select 逐字节一致）
                doc_in_topk = bool(pinfo) and live_src in pinfo["groups"]
                s2 = s1 and doc_in_topk

                # S3：引文在选中带文本内（该文档的 band 观测证据文本）
                band_text = ""
                if obs and live_src is not None:
                    want_alias = aliases.get(live_src, live_src)
                    for doc in obs.documents:
                        if doc.source_id == want_alias:
                            band_text = "\n".join(ev.text for ev in doc.evidence)
                            break
                s3 = s2 and quote in norm(band_text)

                s4 = s3 and matched

                # 桶（i42/s2 口径：in_selected 看全部选中证据）
                all_evs = [ev for doc in (obs.documents if obs else ()) for ev in doc.evidence]
                in_selected = quote in norm("\n".join(ev.text for ev in all_evs))
                if matched:
                    bucket = "matched"
                elif in_selected:
                    bucket = "selected_but_match_fail"
                elif in_kept_page:
                    bucket = "kept_page_not_selected"
                elif in_kept_any:
                    bucket = "kept_elsewhere_page_mismatch"
                else:
                    bucket = "not_in_doc_unreachable"

                funnel_targets.append({"query_id": q.query_id,
                                       "target_id": f"{q.query_id} {target.target_id}",
                                       "S0_kept": in_kept_any, "S1_candidates": s1,
                                       "S2_doc_topk": s2, "S3_band_cover": s3,
                                       "S4_matched": s4, "matched": matched,
                                       "bucket": bucket})

        def layer_count(pred) -> int:
            return sum(1 for r in funnel_targets if pred(r))

        funnel = {
            "S0_kept": layer_count(lambda r: r["S0_kept"]),
            "S1_candidates": layer_count(lambda r: r["S1_candidates"]),
            "S2_doc_topk": layer_count(lambda r: r["S2_doc_topk"]),
            "S3_band_cover": layer_count(lambda r: r["S3_band_cover"]),
            "S4_matched": layer_count(lambda r: r["S4_matched"]),
        }
        buckets = Counter(r["bucket"] for r in funnel_targets)

        neg = []
        for q, o in zip(questions, obs_band.values()):
            if q.answer_existence is AnswerExistence.NO_ANSWER:
                docs = [{"source_id": d.source_id,
                         "evidence_preview": [ev.text[:140] for ev in d.evidence][:2]}
                        for d in o.documents] if o else []
                neg.append({"query_id": q.query_id, "question": q.question,
                            "retrieved_documents": len(docs), "docs": docs})

        i42_baseline = json.loads((I42 / "recall-funnel.json").read_text())

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

        # ── F3 焦点：company-007/e1 逐层状态 + 单元级机读归因 ──
        q007 = next(q for q in questions if q.query_id == "company-007")
        e1 = next(t for t in q007.evidence_targets if t.target_id == "e1")
        e1_row = next(r for r in funnel_targets if r["target_id"] == "company-007 e1")
        e1_src = alias_to_source[e1.source_id]
        e1_build = sources[e1_src]
        quote_norm = norm(e1.quote)
        with psycopg.connect(dsn, autocommit=True) as c2:
            unit_rows = c2.execute(
                "SELECT ordinal, status, reasons, location->>'page', raw_text, location->'bbox' "
                "FROM corpus.corpus_units WHERE build_id = %s AND ordinal BETWEEN 716 AND 720 "
                "ORDER BY ordinal",
                (e1_build,)).fetchall()
            chunk_rows = c2.execute(
                "SELECT chunk_id, kind, unit_refs FROM corpus.corpus_chunks WHERE build_id = %s "
                "AND (unit_refs::text LIKE %s OR unit_refs::text LIKE %s)",
                (e1_build, "%unit:0717%", "%unit:0718%")).fetchall()
            tail718 = next((raw for ordinal, status, reasons, page, raw, bbox in unit_rows
                            if int(ordinal) == 718), "")
        e1_units = [{"ordinal": int(ordinal), "status": str(status),
                     "reasons": list(reasons or []), "page": page, "chars": len(raw or ""),
                     "tail": (raw or "")[-14:], "bbox": bbox,
                     "quote_verbatim": quote_norm in norm(raw or "")}
                    for ordinal, status, reasons, page, raw, bbox in unit_rows]
        e1_chunks = [{"chunk_id": str(cid)[:12], "kind": kind, "refs": list(refs),
                      "has_tail_fragment": any(str(r).endswith(":0718") for r in refs)}
                     for cid, kind, refs in chunk_rows]
        # 续接片段假设的可行性：把与该句同单元的 NOISE 尾片段接回块文本后，引文是否逐字可承载
        stitch_ok = None
        with psycopg.connect(dsn, autocommit=True) as c3:
            holder = c3.execute(
                "SELECT chunk_id FROM corpus.corpus_chunks WHERE build_id = %s "
                "AND unit_refs::text LIKE %s LIMIT 1", (e1_build, "%unit:0717%")).fetchone()
        holder_recalled = None
        doc_in_topk = None
        if holder:
            held = fetch_verbatim(dsn, build_handle(e1_build),
                                  chunk_locator(str(holder[0]))).text
            stitch_ok = quote_norm in norm(held + tail718)
            pinfo007 = per_query.get(q007.query_id) or {}
            holder_recalled = any(str(h.chunk_id) == str(holder[0])
                                  for h in pinfo007.get("hits", ()))
            doc_in_topk = e1_src in (pinfo007.get("groups") or {})

        # 产品路径复核（口径与 F4 replay 的 ``on`` 一致）：band + 跨边界 + cell 投影
        from plugins.corpus.service import CorpusService

        svc = CorpusService(dsn)
        prod_docs, _prod_cov = svc.search_bands(or_query(conn, q007.question), limit=2000)
        prod_e1 = False
        for d in prod_docs:
            if aliases.get(d.source_id, d.source_id) != e1.source_id:
                continue
            evs: list = []
            for band_items in d.chunks_by_band:
                texts = [it.text for it in band_items]
                pages = sorted({p for it in band_items for p in it.pages})
                if texts:
                    evs.append(FetchedEvidence("\n".join(texts),
                                               tuple(f"page:{p}" for p in pages), True))
            for c in d.cells:
                loc = ([f"page:{c.page}"] if c.page is not None else []) + \
                      ["row:" + c.row, "col:" + c.col]
                evs.append(FetchedEvidence(c.text, tuple(loc), True))
            if any(e1.matches(ev) for ev in evs):
                prod_e1 = True
                break

        self_check = {
            "S1_S2_not_regressed": (funnel["S1_candidates"] == 66
                                    and funnel["S2_doc_topk"] == 60),
            "S0_kept_plus_f3": funnel["S0_kept"] == 78,
            "e1_S0_kept_green": bool(e1_row["S0_kept"]),
            "e1_S4_matched_green": bool(e1_row["S4_matched"]),
            "e1_product_path_matched": bool(prod_e1),
            "width_le_provable": max_band_width_measured <= band.provable_width_bound,
            "fp_not_increased": len(report_band.false_positives) <= 6,
        }

        summary = {
            "artifact": "f3-reingest-replay",
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "kind": "B3/F3 重摄入后同口径复验（非冻结回归）",
            "corpus": "index-4-zhcfg-2 active (8 builds, rebuilt 2026-09-22 with F3 clean)",
            "selection": "product select_band (BandPolicy gap=1/expand=1/band_cap=8/pool_cap=24)",
            "scorer": "working-tree whitespace-norm (NOT frozen)",
            "model_calls": 0,
            "band_params": {"gap": band.gap, "expand": band.expand, "band_cap": band.band_cap,
                            "pool_cap": band.pool_cap,
                            "provable_width_bound": band.provable_width_bound,
                            "max_band_width_measured": max_band_width_measured},
            "layers": {"base": layer_summary(report_base), "band": layer_summary(report_band)},
            "funnel": funnel,
            "f3_focus": {
                "target": "company-007 e1",
                "source_id": e1.source_id,
                "build_id": e1_build,
                "layers": {k: e1_row[k] for k in
                           ("S0_kept", "S1_candidates", "S2_doc_topk", "S3_band_cover",
                            "S4_matched", "matched", "bucket")},
                "product_path_matched": bool(prod_e1),
                "baseline_before_reingest": {"S0_kept": False, "bucket": "not_in_doc_unreachable",
                                             "artifact": "f2-funnel-targets.json (2026-09-21 15:40)"},
            },
            "f3_diagnosis": {
                "finding": ("F3 单元级判定已生效（ord=717 由 NOISE 转 KEPT）但不足以让 e1 转绿："
                            "事实句被版面切成 ord=717（kept，止于『4.06%的股』）与 ord=718"
                            "（NOISE/disclaimer_section，仅『份。』），块装配按 kept 取单元 ⇒ "
                            "块文本在句中断开，引文『…4.06%的股份。』逐字不可承载。"),
                "units_716_720": e1_units,
                "chunks_717_718": e1_chunks,
                "recall": {"chunk_with_717_recalled": holder_recalled,
                           "doc_in_topk": doc_in_topk,
                           "quote_in_recalled_chunk": e1_row["S1_candidates"],
                           "note": "块与文档均可召回/入选；失败点仅在引文逐字包含"},
                "stitch_tail_fragment_restores_quote": stitch_ok,
                "corpus_wide_pattern": "见 f3-fragment-scan.json（同构样本数）",
                "requires_decision": ["clean 侧句跨单元粒度（改 clean ⇒ 重摄入 + 新冻结修订 + 粒度签认）",
                                      "读取侧续接片段聚合（免重摄入，需新冻结修订）"],
            },
            "i42_baseline": {
                "funnel": i42_baseline["funnel"],
                "evidence_pass_total": "12/24",
                "false_positives": 6,
            },
            "self_check": self_check,
            "target_buckets": dict(buckets),
            "negative": {"or_false_positives": report_band.false_positives, "cases": neg},
            "questions": len(questions),
        }
        write_once("f3-summary.json", summary)
        write_once("f3-observations.json", [asdict(o) for o in obs_band.values()])
        write_once("f3-base-observations.json", [asdict(o) for o in obs_base.values()])
        write_once("f3-trace.json", traces)
        write_once("f3-score.json", asdict(report_band))
        (HERE / "f3-score.md").write_text(format_report(report_band) + "\n")
        write_once("fetch-receipts.json", receipts)
        write_once("f3-funnel-targets.json", funnel_targets)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        # ── MD 报告 ──
        i42f = i42_baseline["funnel"]
        lines = [
            "# B3 / F3 重摄入后复验（company-007/e1 × index-4-zhcfg-2）",
            "",
            f"- 生成：{summary['generated_at']}；类型：同口径复验（参照 i42 / F2，非冻结回归）",
            "- corpus：8 份 active builds（index-4-zhcfg-2，2026-09-22 按当前字节全量重建，clean 含 F3）",
            f"- 选择：产品 `select_band`（G={band.gap}/K={band.expand}/带数={band.band_cap}/"
            f"POOL_CAP={band.pool_cap}；可证带宽上界 {band.provable_width_bound}，"
            f"实测最大带宽 {max_band_width_measured}）",
            "- 口径：79 目标、查询=问题词元 OR、limit=2000 不饱和断言、scorer=工作树空白规约（NOT frozen）、0 model calls",
            "",
            "## F3 焦点：company-007/e1",
            "",
            f"- 引文所在 build `{e1_build[:12]}` 的 ord 716–720 单元：",
            "",
            "| ord | status | reasons | page | 字符数 | 尾部 | 含完整引文 |",
            "|---|---|---|---|---:|---|---|",
        ]
        for u in e1_units:
            lines.append(f"| {u['ordinal']} | {u['status']} | {u['reasons']} | {u['page']} | "
                         f"{u['chars']} | `{u['tail']}` | {u['quote_verbatim']} |")
        lines += [
            "",
            f"- 该句相关块：{json.dumps(e1_chunks, ensure_ascii=False)}"
            f"（`has_tail_fragment=true` 表示 ord718 的『份。』进块）",
            f"- 逐层：{json.dumps({k: e1_row[k] for k in ('S0_kept', 'S1_candidates', 'S2_doc_topk', 'S3_band_cover', 'S4_matched')}, ensure_ascii=False)}",
            f"- 召回：块被召回 = {holder_recalled}；文档进 top-5 = {doc_in_topk}；"
            f"引文在该块文本内 = {e1_row['S1_candidates']}",
            f"- 桶：`{e1_row['bucket']}`（重摄入前 = `not_in_doc_unreachable`，`f2-funnel-targets.json` 2026-09-21 15:40）",
            f"- 产品路径（`CorpusService.search_bands` = band + 跨边界 + cell）：e1 命中 "
            f"**{prod_e1}**",
            f"- 结节点：把 NOISE 尾片段（ord718『份。』）接回块文本后，引文逐字可承载 = "
            f"**{stitch_ok}**",
            "",
            "> 结论：F3 单元级判定已生效（ord717 NOISE→KEPT），但**不足以**让 e1 转绿——"
            "事实句被版面切成 kept 前半 + NOISE 尾片段（『份。』），块装配只收 kept 单元 ⇒ "
            "引文在句中断开。转绿需二选一：clean 侧句跨单元粒度（⇒ 重摄入 + 新修订 + 粒度签认）"
            "或读取侧续接片段聚合（免重摄入，需新修订）。**均属需 U 裁决的粒度/机制变更，未擅自实施。**",
            "",
            "",
            "## 漏斗对比（band vs i42 基线）",
            "",
            "| 层 | i42 基线 | band（F3 后） | Δ |",
            "|---|---|---:|---:|",
        ]
        labels = [("S0_kept", i42f["S0_kept"]), ("S1_candidates", i42f["S1_candidates"]),
                  ("S2_doc_topk", i42f["S2_doc_topk"]), ("S4_matched", i42f["S4_matched"])]
        for name, base_val in labels:
            got = funnel[name]
            lines.append(f"| {name} | {base_val} | {got} | {got - base_val:+d} |")
        lines.append(f"| S3（band 覆盖 / i42 chunk_top8） | {i42f['S3_chunk_top8']} | "
                     f"{funnel['S3_band_cover']} | {funnel['S3_band_cover'] - i42f['S3_chunk_top8']:+d} |")
        lines += [
            "",
            "## 三类指标（base / band）",
            "",
            "| 类 | DocRecall | QuestionPass | EvidencePass |",
            "|---|---|---|---|",
        ]
        for cb, cbn in zip(report_base.classes, report_band.classes):
            lines.append(f"| {cb.domain} | {cb.doc_recall.rate} / {cbn.doc_recall.rate} | "
                         f"{cb.question_pass.passed}/{cb.question_pass.total} / "
                         f"{cbn.question_pass.passed}/{cbn.question_pass.total} | "
                         f"{cb.evidence_pass.passed}/{cb.evidence_pass.total} / "
                         f"{cbn.evidence_pass.passed}/{cbn.evidence_pass.total} |")
        lines += [
            "",
            f"- EvidencePass：base {summary['layers']['base']['evidence_pass_total']}；"
            f"band **{summary['layers']['band']['evidence_pass_total']}**（i42 基线 12/24、"
            f"F2 band+cell 18/24）",
            f"- 负例误报：band {len(report_band.false_positives)}（i42 基线 6，不得回升）",
            f"- 桶分布：{json.dumps(dict(buckets), ensure_ascii=False)}",
            f"- 带宽：实测最大 {max_band_width_measured} ≤ 可证上界 {band.provable_width_bound}"
            f"（{'满足' if max_band_width_measured <= band.provable_width_bound else '违反'}）",
            "",
            "## 自检",
            "",
        ]
        for key, val in self_check.items():
            lines.append(f"- `{key}` = {val}")
        (HERE / "f3-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
