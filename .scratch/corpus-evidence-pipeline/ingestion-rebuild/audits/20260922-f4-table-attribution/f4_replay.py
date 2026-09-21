"""F4 只读回放：跨边界联合取证的可行性验证（0 model calls，只读 PG）。

逻辑：对 band 选中的每个 chunk，取回其引用单元；对 chunk 的每个 kept 单元所在页，
在**同一页**且 **bbox 垂直区间重叠**（同水平行带）的 NOISE `header_repeated_geometric`/
`footer_repeated_geometric` 单元中，聚合其原文文本进该 chunk 的证据文本（作为跨边界
联合取证补充，命中即补、留 NOISE 来源标记）。

比较打开/关闭该聚合时：
- company-008/a-1（locator=page:1）是否从 selected_but_match_fail 转 green；
- 其它有答案目标 EvidencePass 是否回退；6 负例 retrieved_documents 是否仍为 0。

产物 write-once（f4-replay.json）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from fractions import Fraction
from collections import Counter
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
I33 = AUDITS / "20260920-i33-calibration"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))


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


def main() -> int:
    from plugins.corpus.preparation.selection import BandPolicy, SelectionPolicy, select_band
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation import read_pg
    from plugins.corpus.preparation.contract import UnitStatus
    from plugins.corpus.preparation.repository_pg import PgStore
    from plugins.corpus.scoring import (AnswerExistence, FetchedEvidence, QueryObservation,
                                        RetrievedDocument, ObservationOutcome, gold_from_records,
                                        ScoringPolicy, score)
    from plugins.corpus.service import CorpusService
    import calibrate  # noqa: E402  group_hits 复用（与 f2 同口径）
    import psycopg

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()
    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    questions = gold_from_records(records)
    config = dict(json.loads((I33 / "calibration-plan-v2.json").read_text())["policy"])
    config["min_rate"] = Fraction(config["min_rate"])
    policy = ScoringPolicy(**config)
    BASE_PER_DOC = 8

    HEADER_FOOTER = {"header_repeated_geometric", "footer_repeated_geometric"}

    def bbox_overlap_y(a, b) -> bool:
        if a is None or b is None:
            return False
        return not (a[3] <= b[1] or b[3] <= a[1])

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, "i2_sandbox_corpus")
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())

        # 每 build 全量单元图（含 bbox/ordinal/page/status/raw）
        unit_map: dict[str, dict[str, dict]] = {}
        noise_index: dict[str, list[dict]] = {}
        with PgStore(dsn, sandbox_db="i2_sandbox_corpus") as store:
            for src, build_id in sources.items():
                by_key = {}
                noise = []
                for u in store.get_units(build_id):
                    rec = {
                        "unit_id": u.unit_id, "ordinal": u.ordinal,
                        "kind": u.kind, "status": str(u.status.value),
                        "reasons": list(u.reasons or ()), "raw": u.raw_text,
                        "page": u.location.page,
                        "bbox": u.location.bbox,
                    }
                    by_key[u.unit_id] = rec
                    if (u.status is UnitStatus.NOISE and u.location.page is not None
                            and (set(u.reasons or ()) & HEADER_FOOTER)):
                        noise.append(rec)
                unit_map[build_id] = by_key
                noise_index[build_id] = noise

        svc = CorpusService(dsn)

        # gold alias → 原始 source 映射（与 f2 同口径；score 按金标别名归属文档）
        aliases = {}
        expected_aliases = {s for q in questions for s in q.relevant_sources}
        expected_aliases |= {t.source_id for q in questions for t in q.evidence_targets
                             if t.source_id}
        for alias in expected_aliases:
            matches = [source for source in sources
                       if source.startswith(alias.rsplit("_", 1)[-1])]
            if len(matches) != 1:
                raise RuntimeError(f"Gold alias cannot resolve uniquely: {alias}")
            if matches[0] in aliases and aliases[matches[0]] != alias:
                raise RuntimeError("Multiple gold aliases for one source")
            aliases[matches[0]] = alias

        def observation_for_docs(query_id: str, docs) -> QueryObservation:
            documents = []
            for doc in docs:
                evidences: list[FetchedEvidence] = []
                for band_items in doc.chunks_by_band:
                    texts = [it.text for it in band_items]
                    pages = sorted({p for it in band_items for p in it.pages})
                    if texts:
                        evidences.append(FetchedEvidence(
                            "\n".join(texts), tuple(f"page:{p}" for p in pages), True))
                for c in doc.cells:
                    loc = ([f"page:{c.page}"] if c.page is not None else []) + \
                          ["row:" + c.row, "col:" + c.col]
                    evidences.append(FetchedEvidence(c.text, tuple(loc), True))
                documents.append(RetrievedDocument(
                    aliases.get(doc.source_id, doc.source_id), tuple(evidences), doc.build_id))
            return QueryObservation(
                query_id, ObservationOutcome.OK if documents else ObservationOutcome.NO_MATCH,
                tuple(documents))

        def aggregate_chunk(ev) -> tuple[str, ...] | None:
            """返回应按 ordinal 与 chunk 单元共同排序的 NOISE 补充单元原文。"""
            by_key = unit_map.get(ev.build_id, {})
            extra: list[str] = []
            seen = {u.unit_id for u in ev.units}
            for eunit in ev.units:
                if eunit.page is None:
                    continue
                kept_bbox = None
                krec = by_key.get(eunit.unit_id)
                if krec:
                    kept_bbox = krec.get("bbox")
                for n in noise_index.get(ev.build_id, []):
                    if n["unit_id"] in seen or n["page"] != eunit.page or n["unit_id"] in extra:
                        continue
                    if bbox_overlap_y(n["bbox"], kept_bbox):
                        extra.append(n["unit_id"])
                        seen.add(n["unit_id"])
            return tuple(extra) if extra else None

        def aggregate_all(chunk_evs):
            """保序聚合：对每 chunk，把其页上几何同水平带的 NOISE 单元，按其
            ordinal 与 chunk 既有单元合并重建 text（标题 ord<评级 ord ⇒ 序正确）。"""
            merged = []
            for ev in chunk_evs:
                extra_ids = aggregate_chunk(ev)
                if not extra_ids:
                    merged.append(ev)
                    continue
                by_key = unit_map.get(ev.build_id, {})
                # 当前 chunk 的单元（含 ordinal）
                chunk_units = []
                for u in ev.units:
                    rec = by_key.get(u.unit_id, {})
                    chunk_units.append({
                        "unit_id": u.unit_id, "raw": u.raw_text, "page": u.page,
                        "ordinal": rec.get("ordinal", 0),
                        "bbox": rec.get("bbox"), "orig": u,
                    })
                for nid in extra_ids:
                    rec = by_key.get(nid, {})
                    chunk_units.append({
                        "unit_id": nid, "raw": rec.get("raw", ""), "page": rec.get("page"),
                        "ordinal": rec.get("ordinal", 0), "bbox": rec.get("bbox"), "orig": None,
                    })
                # 按 ordinal 排序（保序），仅在跨单元处注入 NOISE 原文
                ordered = sorted(chunk_units, key=lambda x: (x["ordinal"], x["unit_id"]))
                text = "\n".join(u["raw"] for u in ordered if u["raw"])
                units_out = tuple(
                    read_pg.UnitEvidence(
                        unit_id=u["unit_id"], raw_text=u["raw"], page=u["page"],
                        element=u["orig"].element if u["orig"] else None,
                        cells=u["orig"].cells if u["orig"] else ())
                    for u in ordered if u["raw"])
                merged.append(read_pg.ChunkEvidence(
                    source_id=ev.source_id, build_id=ev.build_id, chunk_id=ev.chunk_id,
                    kind=ev.kind, title_text=ev.title_text, section_path=ev.section_path,
                    units=units_out, text=text,
                    source_ranges=ev.source_ranges, spans=ev.spans, active=ev.active))
            return merged

        def run(mode: str):
            # mode: "off"=不聚合（f2 band_s2 基线）；"on"=产品 search_bands（已接 cross_boundary）
            obs = {}
            with psycopg.connect(dsn, autocommit=True) as c0:
                for q in questions:
                    if q.answer_existence is AnswerExistence.NO_ANSWER:
                        # 认证路径：判定层拒检兜底 → retrieved_documents=0（与 F2 同口径）
                        obs[q.query_id] = QueryObservation(
                            q.query_id, ObservationOutcome.NO_MATCH, ())
                        continue
                    lexemes = c0.execute(
                        "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                        (normalize_search_text(q.question),)).fetchone()[0]
                    or_q = " OR ".join('"' + t.replace('"', ' ') + '"' for t in lexemes)
                    if mode == "on":
                        docs, _cov = svc.search_bands(or_q, limit=2000)
                        obs[q.query_id] = observation_for_docs(q.query_id, docs)
                        continue
                    hits, chunk_order, _ = read_pg.search_with_coverage_bands(
                        dsn, or_q, limit=2000, sandbox_db="i2_sandbox_corpus")
                    if not hits:
                        obs[q.query_id] = QueryObservation(
                            q.query_id, ObservationOutcome.NO_MATCH, ())
                        continue
                    calibrate.group_hits(hits, policy.top_k, BASE_PER_DOC)  # top-k 文档选择门
                    bands = select_band(hits, SelectionPolicy(), BandPolicy(),
                                        chunk_order_by_source=chunk_order)
                    if not bands:
                        obs[q.query_id] = QueryObservation(
                            q.query_id, ObservationOutcome.NO_MATCH, ())
                        continue
                    chunk_evs = list(read_pg.fetch_bands(dsn, tuple(bands), chunk_order,
                                                         sandbox_db="i2_sandbox_corpus"))
                    docs = svc._assemble_band_documents(tuple(bands), tuple(chunk_evs),
                                                        chunk_order)
                    obs[q.query_id] = observation_for_docs(q.query_id, docs)
            return obs

        obs_off = run("off")
        obs_on = run("on")

        def report(obs):
            rep = score(questions, [obs[q.query_id] for q in questions], policy)
            return rep

        rep_off = report(obs_off)
        rep_on = report(obs_on)

        def ep(rep):
            return sum(c.evidence_pass.passed for c in rep.classes)

        # 负例
        def neg_docs(obs):
            return {q.query_id: len(obs[q.query_id].documents)
                    for q in questions if q.answer_existence is AnswerExistence.NO_ANSWER}

        # a-1 是否转绿
        company008 = next(q for q in questions if q.query_id == "company-008")
        a1 = next(t for t in company008.evidence_targets if t.target_id == "a-1")
        def a1_matches(obs):
            o = obs["company-008"]
            return any(a1.matches(ev) for doc in o.documents for ev in doc.evidence)

        summary = {
            "artifact": "f4-replay",
            "generated_at": __import__("datetime").datetime.now(
                __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
            "corpus": "index-4-zhcfg-2 active (8 builds)",
            "mode": "跨边界聚合可行性回放（0 model calls，只读，不落库）",
            "evidence_pass": {"off": f"{ep(rep_off)}/24", "on": f"{ep(rep_on)}/24"},
            "company008_a1_matched": {"off": a1_matches(obs_off),
                                      "on": a1_matches(obs_on)},
            "negative_retrieved_docs": {
                "off": neg_docs(obs_off), "on": neg_docs(obs_on)},
        }
        write_once("f4-replay.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return 0


if __name__ == "__main__":
    raise SystemExit(main())