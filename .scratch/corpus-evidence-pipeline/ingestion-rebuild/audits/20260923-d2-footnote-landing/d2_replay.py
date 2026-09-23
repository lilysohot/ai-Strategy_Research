"""D2 落地复验：表格来源注聚合（``attach_source_note``）A/B（0 model calls、只读、不落库）。

谓词（i0c-r4y，U 2026-09-23 授权实施）：块内含**表格行** kept 单元时，把同页、版面在其
下方且垂直间距 < 12pt、形似「来源注 + 说明性分句」的 kept 注段按 (ordinal, unit_id)
保序聚合进块证据。动机：industry-008 的 a-3/a-5 引用注1（ord518，kept，page:10），
该块在本题排 doc 内 47/120 > ``pool_cap=24`` ⇒ 不在任何证据带内 ⇒ 两条目标同时 fail。

A/B 口径（svc.search_bands 主体逐行拷贝，仅开关不同——零漂移由 on 与产品路径逐字段相等证明）：
- off：attach_source_note=False（关断基线，即本轮改动前的产品行为）；
- on ：attach_source_note=True（== 产品 svc.search_bands 默认行为）。

断言：
1. industry-008 的 a-3/a-5 off→on 转绿（注1 随来源注聚合进带）；
2. 目标级不回退：matched(on) ⊇ matched(off)，且新增恰为 {a-3, a-5}；
3. EvidencePass off 23/24 → on 24/24；
4. 6 负例 retrieved_documents=0（认证路径 NO_MATCH 构造，与 F2/F4/F3-B 同口径）；
5. 选择不变：off/on SelectedBand 集合相等，带宽 ≤ 49；
6. 产品路径与 on 逐字段相等。

产物 write-once（语义逐字段比较，剔 ``generated_at``）+ ``--no-write``。
用法： uv run python d2_replay.py [--no-write]
"""
from __future__ import annotations

import argparse
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

NON_SEMANTIC_FIELDS = ("generated_at",)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_once(name: str, value) -> None:
    path = HERE / name
    if path.exists():
        old = json.loads(path.read_text(encoding="utf-8"))
        o = {k: v for k, v in old.items() if k not in NON_SEMANTIC_FIELDS}
        n = {k: v for k, v in value.items() if k not in NON_SEMANTIC_FIELDS}
        if json.dumps(o, sort_keys=True, default=str) == json.dumps(n, sort_keys=True, default=str):
            print(f"[write-once] {name} 语义逐字段一致 → 保留原产物字节")
            return
        diff = sorted({k for k in set(o) | set(n) if o.get(k) != n.get(k)})
        raise RuntimeError(f"write-once conflict: {name}; 差异字段={diff}")
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n",
                    encoding="utf-8")
    print(f"[write-once] {name} 写入 {path}")


def main() -> int:
    import psycopg

    from plugins.corpus.preparation import cross_boundary, read_pg
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.scoring import (AnswerExistence, FetchedEvidence, ObservationOutcome,
                                        QueryObservation, RetrievedDocument, ScoringPolicy,
                                        gold_from_records, score)
    from plugins.corpus.service import CorpusService

    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()
    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    questions = gold_from_records(records)
    config = dict(json.loads((I33 / "calibration-plan-v2.json").read_text())["policy"])
    config["min_rate"] = Fraction(config["min_rate"])
    policy = ScoringPolicy(**config)
    svc = CorpusService(dsn)
    LIMIT = 2000

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, "i2_sandbox_corpus")
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())

    aliases: dict[str, str] = {}
    expected_aliases = {s for q in questions for s in q.relevant_sources}
    expected_aliases |= {t.source_id for q in questions for t in q.evidence_targets if t.source_id}
    for alias in expected_aliases:
        matches = [s for s in sources if s.startswith(alias.rsplit("_", 1)[-1])]
        if len(matches) != 1:
            raise RuntimeError(f"Gold alias cannot resolve uniquely: {alias}")
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

    def search_bands_note(query: str, *, note: bool):
        """svc.search_bands 主体逐行拷贝，仅 aggregate_band_chunks 暴露 attach 开关。"""

        raw_hits, chunk_order, _coverage = read_pg.search_with_coverage_bands(
            dsn, query, limit=LIMIT, sandbox_db="i2_sandbox_corpus")
        bands = svc._apply_selection_bands(raw_hits, chunk_order, LIMIT)
        chunk_evs = read_pg.fetch_bands(dsn, bands, chunk_order, sandbox_db="i2_sandbox_corpus")
        chunk_evs = cross_boundary.aggregate_band_chunks(
            dsn, chunk_evs, sandbox_db="i2_sandbox_corpus", attach_source_note=note)
        return svc._assemble_band_documents(bands, chunk_evs, chunk_order)

    def or_query(c0, q) -> str:
        lexemes = c0.execute(
            "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
            (normalize_search_text(q.question),)).fetchone()[0]
        return " OR ".join('"' + t.replace('"', " ") + '"' for t in lexemes)

    positives = [q for q in questions if q.answer_existence is not AnswerExistence.NO_ANSWER]
    docs_off: dict[str, list] = {}
    docs_on: dict[str, list] = {}
    obs: dict[str, dict] = {"off": {}, "on": {}}
    for mode in ("off", "on"):
        with psycopg.connect(dsn, autocommit=True) as c0:
            for q in questions:
                if q.answer_existence is AnswerExistence.NO_ANSWER:
                    obs[mode][q.query_id] = QueryObservation(
                        q.query_id, ObservationOutcome.NO_MATCH, ())
                    continue
                docs = search_bands_note(or_query(c0, q), note=(mode == "on"))
                (docs_off if mode == "off" else docs_on)[q.query_id] = docs
                obs[mode][q.query_id] = observation_for_docs(q.query_id, docs)

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

    def max_width(dd: dict) -> int:
        return max((b.width for docs in dd.values() for doc in docs for b in doc.bands), default=0)

    sel_unchanged = all(
        bands_sig(docs_off[q.query_id]) == bands_sig(docs_on[q.query_id]) for q in positives)
    w_off, w_on = max_width(docs_off), max_width(docs_on)

    def matched_map(o_obs: dict) -> dict:
        return {
            (q.query_id, t.target_id): any(
                t.matches(ev) for doc in o_obs[q.query_id].documents for ev in doc.evidence)
            for q in positives for t in q.evidence_targets
        }

    m_off, m_on = matched_map(obs["off"]), matched_map(obs["on"])
    regressed = sorted(k for k, v in m_off.items() if v and not m_on[k])
    newly = sorted(k for k, v in m_on.items() if v and not m_off[k])

    rep_off = score(questions, [obs["off"][q.query_id] for q in questions], policy)
    rep_on = score(questions, [obs["on"][q.query_id] for q in questions], policy)
    ep = lambda rep: sum(c.evidence_pass.passed for c in rep.classes)  # noqa: E731
    per_class = {c.domain: f"{c.evidence_pass.passed}/{c.evidence_pass.total}"
                 for c in rep_on.classes}

    neg_ids = [q.query_id for q in questions if q.answer_existence is AnswerExistence.NO_ANSWER]
    neg_off = {qid: len(obs["off"][qid].documents) for qid in neg_ids}
    neg_on = {qid: len(obs["on"][qid].documents) for qid in neg_ids}

    a35_off = [m_off.get(("industry-008", "a-3")), m_off.get(("industry-008", "a-5"))]
    a35_on = [m_on.get(("industry-008", "a-3")), m_on.get(("industry-008", "a-5"))]

    # 硬判据
    if not (a35_off == [False, False] and a35_on == [True, True]):
        raise RuntimeError(f"industry-008 a-3/a-5 未转绿: off={a35_off} on={a35_on}")
    if regressed:
        raise RuntimeError(f"目标级回退: {regressed}")
    if newly != [("industry-008", "a-3"), ("industry-008", "a-5")]:
        raise RuntimeError(f"新增目标不符: {newly}")
    if ep(rep_on) < ep(rep_off):
        raise RuntimeError("EvidencePass 回退")
    if not ep(rep_on) == 24:
        raise RuntimeError(f"EvidencePass 未达 24/24: {ep(rep_on)}")
    if not all(v == 0 for v in neg_off.values()) or not all(v == 0 for v in neg_on.values()):
        raise RuntimeError(f"负例误报: off={neg_off} on={neg_on}")
    if not sel_unchanged:
        raise RuntimeError("选择变化")
    if w_off > 49 or w_on > 49:
        raise RuntimeError(f"带宽超上界: off={w_off} on={w_on}")

    summary = {
        "artifact": "d2-replay",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": "i2_sandbox_corpus active publications",
        "mode": "表格来源注聚合（attach_source_note）A/B（0 model calls、只读、不落库）",
        "predicate": ("块内表格行 kept 单元 + 同页 + 版面下方（注段上沿 ≥ 表格行下沿）"
                      "+ 间距 < 12pt + 段形为「来源注 + 说明性分句」⇒ 保序聚合"),
        "industry008_a3_a5": {"off": a35_off, "on": a35_on},
        "target_diff": {"regressed": [list(k) for k in regressed],
                        "newly_matched": [list(k) for k in newly]},
        "evidence_pass": {"off": f"{ep(rep_off)}/24", "on": f"{ep(rep_on)}/24",
                          "on_per_class": per_class,
                          "expected": "off 23/24 → on 24/24"},
        "negative_retrieved_docs": {"off": neg_off, "on": neg_on},
        "selection": {"unchanged": sel_unchanged,
                      "band_width_max": {"off": w_off, "on": w_on},
                      "provable_width_bound": 49},
        "product_path_identical": not product_mismatches,
        "all_class_gates_pass": rep_on.classes and all(
            c.evidence_pass.passed == c.evidence_pass.total for c in rep_on.classes),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    if not args.no_write:
        write_once("d2-replay.json", summary)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
