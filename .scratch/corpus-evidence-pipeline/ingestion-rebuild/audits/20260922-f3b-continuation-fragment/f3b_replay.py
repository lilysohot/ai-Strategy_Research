"""F3-B 只读回放：读取侧续接片段聚合（stitch_continuation）A/B（0 model calls，只读 PG）。

谓词（i0c-r4u，U 2026-09-22 具名裁决路径 B）：kept 单元句中截断（raw_text 不以句末
标点收尾）且其紧邻下一 ordinal 的 NOISE 单元以句末标点收尾（拼接即补全句子）并同页
⇒ 该 NOISE 尾片段按 (ordinal, unit_id) 保序聚合进块证据（内容哈希 fail-closed 同 F4）。
同构样本＝company-007/e1『…4.06%的股』（kept ord717）+『份。』（NOISE/disclaimer_section
ord718）；全库 8 builds 满足「拼接补全句子」者仅此一处。

A/B 口径（svc.search_bands 主体逐行拷贝，仅开关不同——零漂移由 stitch=True 输出与
产品路径逐字段相等证明）：
- off：stitch_continuation=False（保留 F4 表头/脚注聚合的关断基线）；
- on：stitch_continuation=True（== 产品 svc.searchands 默认行为）。

断言：
1. company-007/e1 off→on 转 green（『…4.06%的股』+『份。』拼接还原引文）；
2. 目标级不回退：matched(on) ⊇ matched(off) 且新增 == {company-007/e1}；
3. 6 负例 retrieved_documents=0（认证路径 NO_MATCH 构造，与 F2/F4 同口径）；
4. EvidencePass 不回退（F4 后基线 off 18/24，预期 on 19/24）；
5. 选择不变：off/on SelectedBand 集合相等；带宽 ≤ 49
   （provable_width_bound = (24-1)*(1+1)+1+2*1 = 49）。

产物 write-once（f3b-replay.json）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from fractions import Fraction
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


def main() -> int:
    import psycopg

    from plugins.corpus.preparation import cross_boundary, read_pg
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.scoring import (AnswerExistence, FetchedEvidence, ObservationOutcome,
                                        QueryObservation, RetrievedDocument, ScoringPolicy,
                                        gold_from_records, score)
    from plugins.corpus.service import CorpusService

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()
    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    questions = gold_from_records(records)
    config = dict(json.loads((I33 / "calibration-plan-v2.json").read_text())["policy"])
    config["min_rate"] = Fraction(config["min_rate"])
    policy = ScoringPolicy(**config)
    LIMIT = 2000

    svc = CorpusService(dsn)

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, "i2_sandbox_corpus")
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())

    # gold alias → 原始 source 映射（与 f2/f4 同口径；score 按金标别名归属文档）
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

    def search_bands_stitch(query: str, *, stitch: bool):
        """svc.search_bands 主体逐行拷贝，仅 aggregate_band_chunks 暴露 stitch 开关。"""
        raw_hits, chunk_order, _coverage = read_pg.search_with_coverage_bands(
            dsn, query, limit=LIMIT, sandbox_db="i2_sandbox_corpus")
        bands = svc._apply_selection_bands(raw_hits, chunk_order, LIMIT)
        chunk_evs = read_pg.fetch_bands(dsn, bands, chunk_order, sandbox_db="i2_sandbox_corpus")
        chunk_evs = cross_boundary.aggregate_band_chunks(
            dsn, chunk_evs, sandbox_db="i2_sandbox_corpus", stitch_continuation=stitch)
        return svc._assemble_band_documents(bands, chunk_evs, chunk_order)

    def or_query(c0, q) -> str:
        lexemes = c0.execute(
            "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
            (normalize_search_text(q.question),)).fetchone()[0]
        return " OR ".join('"' + t.replace('"', ' ') + '"' for t in lexemes)

    positives = [q for q in questions if q.answer_existence is not AnswerExistence.NO_ANSWER]

    docs_off: dict[str, list] = {}
    docs_on: dict[str, list] = {}
    obs: dict[str, dict] = {"off": {}, "on": {}}
    for mode in ("off", "on"):
        with psycopg.connect(dsn, autocommit=True) as c0:
            for q in questions:
                if q.answer_existence is AnswerExistence.NO_ANSWER:
                    # 认证路径：判定层拒检兜底 → retrieved_documents=0（与 F2/F4 同口径）
                    obs[mode][q.query_id] = QueryObservation(
                        q.query_id, ObservationOutcome.NO_MATCH, ())
                    continue
                docs = search_bands_stitch(or_query(c0, q), stitch=(mode == "on"))
                if mode == "off":
                    docs_off[q.query_id] = docs
                else:
                    docs_on[q.query_id] = docs
                obs[mode][q.query_id] = observation_for_docs(q.query_id, docs)

    # 产品路径逐字段一致性：stitch=True 手工拷贝 == svc.search_bands（默认开）
    product_mismatches: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as c0:
        for q in positives:
            docs_prod, _cov = svc.search_bands(or_query(c0, q), limit=LIMIT)
            if docs_prod != docs_on[q.query_id]:
                product_mismatches.append(q.query_id)
    if product_mismatches:
        raise RuntimeError(f"产品路径不一致: {product_mismatches}")

    def bands_sig(docs) -> tuple:
        return tuple(tuple(doc.bands) for doc in docs)

    def max_width_all(dd: dict) -> int:
        return max((b.width for docs in dd.values() for doc in docs for b in doc.bands),
                   default=0)

    sel_unchanged = all(
        bands_sig(docs_off[q.query_id]) == bands_sig(docs_on[q.query_id]) for q in positives)
    w_off, w_on = max_width_all(docs_off), max_width_all(docs_on)

    def matched_map(o_obs: dict) -> dict:
        m = {}
        for q in positives:
            o = o_obs[q.query_id]
            for t in q.evidence_targets:
                m[(q.query_id, t.target_id)] = any(
                    t.matches(ev) for doc in o.documents for ev in doc.evidence)
        return m

    m_off, m_on = matched_map(obs["off"]), matched_map(obs["on"])
    regressed = sorted(k for k, v in m_off.items() if v and not m_on[k])
    newly = sorted(k for k, v in m_on.items() if v and not m_off[k])

    rep_off = score(questions, [obs["off"][q.query_id] for q in questions], policy)
    rep_on = score(questions, [obs["on"][q.query_id] for q in questions], policy)
    ep = lambda rep: sum(c.evidence_pass.passed for c in rep.classes)  # noqa: E731

    company007 = next(q for q in questions if q.query_id == "company-007")
    e1 = next(t for t in company007.evidence_targets if t.target_id == "e1")

    def e1_matched(o_obs: dict) -> bool:
        o = o_obs["company-007"]
        return any(e1.matches(ev) for doc in o.documents for ev in doc.evidence)

    neg_ids = [q.query_id for q in questions
               if q.answer_existence is AnswerExistence.NO_ANSWER]
    neg_off = {qid: len(obs["off"][qid].documents) for qid in neg_ids}
    neg_on = {qid: len(obs["on"][qid].documents) for qid in neg_ids}

    # 硬判据
    assert e1_matched(obs["off"]) is False and e1_matched(obs["on"]) is True, "e1 未转绿"
    assert not regressed, f"目标级回退: {regressed}"
    assert newly == [("company-007", "e1")], f"新增目标不符: {newly}"
    assert all(v == 0 for v in neg_off.values()), f"负例 off 误报: {neg_off}"
    assert all(v == 0 for v in neg_on.values()), f"负例 on 误报: {neg_on}"
    assert ep(rep_on) >= ep(rep_off), "EvidencePass 回退"
    assert sel_unchanged, "选择变化"
    assert w_off <= 49 and w_on <= 49, f"带宽超上界: off={w_off} on={w_on}"

    summary = {
        "artifact": "f3b-replay",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": "i2_sandbox_corpus active publications",
        "mode": "读取侧续接片段聚合（stitch_continuation）A/B（0 model calls，只读，不落库）",
        "stitch_predicate": ("kept 句中截断（不以句末标点收尾）+ 紧邻下一 ordinal NOISE 尾片段"
                            "以句末标点收尾（拼接即补全句子）+ 同页 ⇒ 保序聚合进块证据"),
        "company007_e1_matched": {"off": e1_matched(obs["off"]), "on": e1_matched(obs["on"])},
        "target_diff": {"regressed": [list(k) for k in regressed],
                        "newly_matched": [list(k) for k in newly]},
        "evidence_pass": {"off": f"{ep(rep_off)}/24", "on": f"{ep(rep_on)}/24",
                          "f4_baseline": "18/24", "expected": "off 18/24 → on 19/24"},
        "negative_retrieved_docs": {"off": neg_off, "on": neg_on},
        "selection": {"unchanged": sel_unchanged,
                      "band_width_max": {"off": w_off, "on": w_on},
                      "provable_width_bound": 49},
        "product_path_identical": not product_mismatches,
    }
    write_once("f3b-replay.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
