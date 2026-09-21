"""band 落产品同口径回测（§10.5 选项 A）：产品 select_band × 当前 active corpus。

S2 判定后改道：S3a/S3b 双否，band 在**选择层**落产品（原票 03 chunk.cover 作废）。
本回测验证产品 `selection.select_band`（BandPolicy gap=1/expand=1/band_cap=8/pool_cap=24）
在当前语料（index-4-zhcfg-2，与 i42 同）上的表现。

口径（与 i42 backtest.py / recall-funnel 一致）：
- 79 目标、perdoc 文档序（band 文档选择与 select 逐字节一致）；
- 查询 = 问题词元 OR 连接；limit=2000 不饱和断言；
- scorer = 工作树空白规约（NOT frozen）；0 model_calls；
- 负例（单变量）：走 OR 检索路径 + base 选择（select 前 8 块），FP 判定只取决于
  是否有文档被检索（与 i41/i42 相同）。

变体对照：
- ``base``：select（score 降序，前 top_k 来源 × 8 块）——当前产品 i42 语义的对照组；
- ``band``：select_band（文档内连续区间取回）。

自检：两变体的 S0_kept / S1_candidates / S2_doc_topk 必须与 i42 基线一致
（候选池与文档选择不受 band 影响）；band 的 S4_matched 须 ≥ 基线 44。

只读 PG + 0 model_calls；产物 write-once 写入本目录。
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

        self_check = {
            "S0_S1_S2_match_i42": (funnel["S0_kept"] == i42_baseline["funnel"]["S0_kept"] == 77
                                   and funnel["S1_candidates"]
                                   == i42_baseline["funnel"]["S1_candidates"] == 66
                                   and funnel["S2_doc_topk"]
                                   == i42_baseline["funnel"]["S2_doc_topk"] == 60),
            "S4_ge_baseline": funnel["S4_matched"] >= i42_baseline["funnel"]["S4_matched"],
            "width_le_provable": max_band_width_measured <= band.provable_width_bound,
            "fp_not_increased": len(report_band.false_positives) <= 6,
        }

        summary = {
            "artifact": "band-product-backtest",
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "kind": "同口径回测（非冻结回归）",
            "corpus": "index-4-zhcfg-2 active (8 builds)",
            "selection": "product select_band (BandPolicy gap=1/expand=1/band_cap=8/pool_cap=24)",
            "scorer": "working-tree whitespace-norm (NOT frozen)",
            "model_calls": 0,
            "band_params": {"gap": band.gap, "expand": band.expand, "band_cap": band.band_cap,
                            "pool_cap": band.pool_cap,
                            "provable_width_bound": band.provable_width_bound,
                            "max_band_width_measured": max_band_width_measured},
            "layers": {"base": layer_summary(report_base), "band": layer_summary(report_band)},
            "funnel": funnel,
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
        write_once("band-summary.json", summary)
        write_once("band-observations.json", [asdict(o) for o in obs_band.values()])
        write_once("band-base-observations.json", [asdict(o) for o in obs_base.values()])
        write_once("band-trace.json", traces)
        write_once("band-score.json", asdict(report_band))
        (HERE / "band-score.md").write_text(format_report(report_band) + "\n")
        write_once("fetch-receipts.json", receipts)
        write_once("band-funnel-targets.json", funnel_targets)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        # ── MD 报告 ──
        i42f = i42_baseline["funnel"]
        lines = [
            "# band 落产品同口径回测（select_band × index-4-zhcfg-2）",
            "",
            f"- 生成：{summary['generated_at']}；类型：同口径回测（参照 i42，非冻结回归）",
            f"- corpus：8 份 active builds（index-4-zhcfg-2，与 i42 同）",
            f"- 选择：产品 `select_band`（G={band.gap}/K={band.expand}/带数={band.band_cap}/"
            f"POOL_CAP={band.pool_cap}；可证带宽上界 {band.provable_width_bound}，"
            f"实测最大带宽 {max_band_width_measured}）",
            "- 口径：79 目标、查询=问题词元 OR、limit=2000 不饱和断言、scorer=工作树空白规约（NOT frozen）、0 model calls",
            "",
            "## 漏斗对比（band vs i42 基线）",
            "",
            "| 层 | i42 基线 | band | Δ |",
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
            f"band **{summary['layers']['band']['evidence_pass_total']}**（i42 基线 12/24）",
            f"- 负例误报：band {len(report_band.false_positives)}（i42 基线 6，不得回升）",
            f"- 桶分布：{json.dumps(dict(buckets), ensure_ascii=False)}",
            f"- 带宽：实测最大 {max_band_width_measured} ≤ 可证上界 {band.provable_width_bound}"
            f"（{'满足' if max_band_width_measured <= band.provable_width_bound else '违反'}）",
        ]
        (HERE / "band-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
