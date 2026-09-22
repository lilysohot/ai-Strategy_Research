"""r4v 落地复验：产品（search_pg 双 tsquery 排序信号）== c3w 评估 prune_fn_punct 臂。

权威期望值来源 = `audits/20260922-c3-lexical-weight/c3w-eval.json`（write-once 评估产物，
获胜档 prune_fn_punct）。硬门（任一失败 RuntimeError 非零退出）：

- G1 机制等价：显式 `rank_query=臂排序串`（or_str(pruned 题面词元)）经产品
  `search_chunks_on → _apply_selection_bands → fetch_bands → aggregate → assemble`
  与臂独立重算（c3w run_weighted 同构）在 24 有答案题上**逐字段相等**——证明产品
  SQL 接线/选择/装配机制与评估臂完全一致；
- G2 端到端==记录值（=plan M4 门）：默认产品路径（`svc.search_bands`，排序词元取自
  收到的查询串）EvidencePass 21/24、82 目标 matched=75（sbf=4、not_selected=0）、
  newly_matched 恰为 company-003×6 + company-008/a-2 + industry-008/a-2、regressed=[]、
  selection_changed=24、带宽 33≤49、company-003 6/6 且金标 pos1；
- G3 开关回滚：`RANK_LEXEME_PRUNE=False` 下产品 == 独立重算的 anchor 臂（**逐字段**），
  且端到端 == c3w-eval.json anchor 记录值（19/24、matched=67、带宽 33）——逐字节回 base；
- G4 负例：6 题真检索召回 == 记录值（各 5）且不高于 anchor 臂（红线不回升）。

**词元来源口径（已记录的非门诊断）**：评估臂的排序词元取自**题面** zhcfg 词元；产品
默认路径按 rollout-plan §3.2 从**收到的查询串**提取（harness 传入的是题面词元的 OR 串，
再分词含 'or' 操作符词元/再切分差异）。两口径在 82 目标漏斗上**逐值等值**（G2 全绿），
但 band 划分可不同（诊断项 `default_vs_arm_doc_mismatch` 记录）；需要与臂逐字段一致时
用 `build_search_params(rank_query=…)` 显式指定（G1 即此路径）。

只读 PG（corpus schema 零写入）、0 model calls、不写库、不 commit；产物 write-once
（r4v-replay.json），`--no-write` 只跑不写。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import replace as dc_replace
from fractions import Fraction
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
I33 = AUDITS / "20260920-i33-calibration"
C3W = AUDITS / "20260922-c3-lexical-weight"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

NON_SEMANTIC_FIELDS = ("generated_at",)


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in NON_SEMANTIC_FIELDS}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def write_once(name: str, value, *, dry_run: bool = False) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if semantic(existing) == semantic(value):
            print(f"[write-once] {name}: 语义逐字段一致（仅 generated_at 不同）→ 保留原产物",
                  file=sys.stderr)
            return
        keys = sorted((set(existing) | set(value)) - set(NON_SEMANTIC_FIELDS))
        diffs = [k for k in keys if semantic(existing.get(k)) != semantic(value.get(k))]
        raise RuntimeError(f"write-once conflict: {name} (语义差异字段: {diffs})")
    if dry_run:
        print(f"[write-once] --no-write: 跳过写出 {name}", file=sys.stderr)
        return
    path.write_bytes(raw)


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def main() -> int:
    import psycopg

    from plugins.corpus.preparation import cross_boundary, read_pg, search_pg
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.negative_query import _FUNCTION_WORDS, is_punct_lexeme
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.scoring import (AnswerExistence, FetchedEvidence, ObservationOutcome,
                                        QueryObservation, RetrievedDocument, ScoringPolicy,
                                        gold_from_records, score)
    from plugins.corpus.service import CorpusService

    dry_run = "--no-write" in sys.argv
    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()
    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    questions = gold_from_records(records)
    config = dict(json.loads((I33 / "calibration-plan-v2.json").read_text())["policy"])
    config["min_rate"] = Fraction(config["min_rate"])
    policy = ScoringPolicy(**config)
    LIMIT = 2000
    expected = json.loads((C3W / "c3w-eval.json").read_text())

    svc = CorpusService(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, "i2_sandbox_corpus")
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())

    aliases: dict[str, str] = {}
    expected_sources = {s for q in questions for s in q.relevant_sources}
    expected_sources |= {t.source_id for q in questions for t in q.evidence_targets if t.source_id}
    for alias in expected_sources:
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

    def or_str(lexemes) -> str:
        return " OR ".join('"' + t.replace('"', " ") + '"' for t in lexemes)

    def rerank(base_query: str, content, function, w_f: float):
        """c3w 评估臂的独立重算（不改产品字节）：raw 池 → 自行 SQL 重打分 → 产品选择/装配。"""
        raw_hits, chunk_order, _cov = read_pg.search_with_coverage_bands(
            dsn, base_query, limit=LIMIT, sandbox_db="i2_sandbox_corpus")
        if not raw_hits:
            return (), chunk_order, ()
        ids = [h.chunk_id for h in raw_hits]
        with psycopg.connect(dsn, autocommit=True) as c0:
            rows = c0.execute(
                "SELECT chunk_id, "
                "  ts_rank(search_tsv, websearch_to_tsquery('zhcfg', %s)), "
                "  ts_rank(search_tsv, websearch_to_tsquery('zhcfg', %s)) "
                "FROM corpus.corpus_chunks WHERE chunk_id = ANY(%s)",
                (or_str(content), or_str(function), ids)).fetchall()
        rank = {r[0]: (float(r[1] or 0.0), float(r[2] or 0.0)) for r in rows}
        new_hits = []
        for h in raw_hits:
            rc, rf = rank.get(h.chunk_id, (0.0, 0.0))
            new_hits.append(dc_replace(h, score=rc + w_f * rf))
        new_hits.sort(key=lambda h: (-h.score, h.build_id, h.chunk_id))
        bands = svc._apply_selection_bands(tuple(new_hits), chunk_order, LIMIT)
        chunk_evs = read_pg.fetch_bands(dsn, bands, chunk_order, sandbox_db="i2_sandbox_corpus")
        chunk_evs = cross_boundary.aggregate_band_chunks(
            dsn, chunk_evs, sandbox_db="i2_sandbox_corpus", stitch_continuation=True)
        docs = svc._assemble_band_documents(bands, chunk_evs, chunk_order)
        sel_aliases = [aliases.get(d.source_id, d.source_id) for d in docs]
        return docs, chunk_order, tuple(sel_aliases)

    positives = [q for q in questions if q.answer_existence is not AnswerExistence.NO_ANSWER]
    negatives = [q for q in questions if q.answer_existence is AnswerExistence.NO_ANSWER]
    assert len(positives) == 24 and len(negatives) == 6

    # 每题：题面 → zhcfg 词元 → base 池查询串（全词元 OR）+ 臂词元集合（与 c3w_eval 同构）
    q_lex: dict[str, tuple[str, ...]] = {}
    base_qs: dict[str, str] = {}
    with psycopg.connect(dsn, autocommit=True) as c0:
        for q in questions:
            lex = c0.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(q.question),)).fetchone()[0]
            q_lex[q.query_id] = tuple(str(t) for t in lex)
            base_qs[q.query_id] = or_str(q_lex[q.query_id])

    def arm_sets(lexemes: tuple[str, ...], *, prune: bool):
        """prune=True ⇒ prune_fn_punct（去功能词+标点）；False ⇒ anchor（全词元）。"""
        if not prune:
            return tuple(lexemes), ()
        keep_fn = tuple(t for t in lexemes if t not in _FUNCTION_WORDS)
        return tuple(t for t in keep_fn if not is_punct_lexeme(t)), \
            tuple(t for t in lexemes if t in _FUNCTION_WORDS or is_punct_lexeme(t))

    # ── 产品（落地后字节）与两档臂独立重算 ────────────────────────────────
    prod_docs: dict[str, tuple] = {}
    arm_docs: dict[str, tuple] = {}
    arm_chunk_order: dict[str, dict] = {}
    off_docs: dict[str, tuple] = {}
    off_arm_docs: dict[str, tuple] = {}
    for q in positives:
        qid = q.query_id
        prod_docs[qid], _ = svc.search_bands(base_qs[qid], limit=LIMIT)
        content, function = arm_sets(q_lex[qid], prune=True)
        arm_docs[qid], arm_chunk_order[qid], _ = rerank(base_qs[qid], content, function, 0.0)
        content_a, function_a = arm_sets(q_lex[qid], prune=False)
        off_arm_docs[qid], _, _ = rerank(base_qs[qid], content_a, function_a, 0.0)

    # G1 机制等价：显式 rank_query=臂排序串 ⇒ 产品装配 == 臂重算（逐字段）
    explicit_docs: dict[str, tuple] = {}
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, "i2_sandbox_corpus")
        with conn.cursor() as cur:
            for q in positives:
                qid = q.query_id
                content, _fn = arm_sets(q_lex[qid], prune=True)
                params = search_pg.build_search_params(
                    base_qs[qid], limit=LIMIT, rank_query=or_str(content))
                hits = search_pg.search_chunks_on(cur, params)
                bands = svc._apply_selection_bands(hits, arm_chunk_order[qid], LIMIT)
                cev = read_pg.fetch_bands(
                    dsn, bands, arm_chunk_order[qid], sandbox_db="i2_sandbox_corpus")
                cev = cross_boundary.aggregate_band_chunks(
                    dsn, cev, sandbox_db="i2_sandbox_corpus", stitch_continuation=True)
                explicit_docs[qid] = svc._assemble_band_documents(
                    bands, cev, arm_chunk_order[qid])

    # G3 开关回滚：RANK_LEXEME_PRUNE=False 下产品路径须 == anchor 臂重算
    saved = search_pg.RANK_LEXEME_PRUNE
    try:
        search_pg.RANK_LEXEME_PRUNE = False
        for q in positives:
            qid = q.query_id
            off_docs[qid], _ = svc.search_bands(base_qs[qid], limit=LIMIT)
    finally:
        search_pg.RANK_LEXEME_PRUNE = saved

    # ── G1 机制等价（显式 rank_query）；G3a 回滚==anchor 臂；口径诊断 ─────
    g1_mismatch = [q.query_id for q in positives
                   if explicit_docs[q.query_id] != arm_docs[q.query_id]]
    g3_mismatch = [q.query_id for q in positives if off_docs[q.query_id] != off_arm_docs[q.query_id]]
    # 非门诊断：默认路径（排序词元取自收到的查询串）vs 臂（词元取自题面）的 band 差异。
    default_vs_arm_doc_mismatch = [q.query_id for q in positives
                                   if prod_docs[q.query_id] != arm_docs[q.query_id]]

    # ── 端到端漏斗 ────────────────────────────────────────────────────────
    def matched_map(o: dict) -> dict[tuple[str, str], bool]:
        m: dict[tuple[str, str], bool] = {}
        for q in positives:
            ob = o[q.query_id]
            for t in q.evidence_targets:
                m[(q.query_id, t.target_id)] = any(
                    t.matches(ev) for doc in ob.documents for ev in doc.evidence)
        return m

    def buckets(o: dict) -> dict[str, int]:
        b = {"matched": 0, "selected_but_match_fail": 0, "not_selected": 0}
        for q in positives:
            ob = o[q.query_id]
            sel = {aliases.get(d.source_id, d.source_id) for d in ob.documents}
            gold_in = bool(sel & set(q.relevant_sources))
            for t in q.evidence_targets:
                if any(t.matches(ev) for doc in ob.documents for ev in doc.evidence):
                    b["matched"] += 1
                elif gold_in:
                    b["selected_but_match_fail"] += 1
                else:
                    b["not_selected"] += 1
        return b

    def bands_sig(docs) -> tuple:
        return tuple(tuple(doc.bands) for doc in docs)

    def max_width(d: dict) -> int:
        return max((b.width for docs in d.values() for doc in docs for b in doc.bands), default=0)

    obs_p = {q.query_id: observation_for_docs(q.query_id, prod_docs[q.query_id])
             for q in positives}
    obs_o = {q.query_id: observation_for_docs(q.query_id, off_docs[q.query_id])
             for q in positives}
    for q in negatives:
        obs_p[q.query_id] = QueryObservation(q.query_id, ObservationOutcome.NO_MATCH, ())
        obs_o[q.query_id] = QueryObservation(q.query_id, ObservationOutcome.NO_MATCH, ())

    mats_p, mats_o = matched_map(obs_p), matched_map(obs_o)
    bks_p, bks_o = buckets(obs_p), buckets(obs_o)
    ep_p = sum(c.evidence_pass.passed for c in
               score(questions, [obs_p[q.query_id] for q in questions], policy).classes)
    ep_o = sum(c.evidence_pass.passed for c in
               score(questions, [obs_o[q.query_id] for q in questions], policy).classes)
    width_p = max_width(prod_docs)
    width_o = max_width(off_docs)
    newly = sorted(f"{k[0]}/{k[1]}" for k in mats_p
                   if mats_p[k] and not mats_o[k])
    regressed = sorted(f"{k[0]}/{k[1]}" for k in mats_o
                       if mats_o[k] and not mats_p[k])
    sel_changed = [q.query_id for q in positives
                   if bands_sig(off_docs[q.query_id]) != bands_sig(prod_docs[q.query_id])]

    # 负例真检索（产品路径，关拒检同 c3w 口径）
    neg_real_p: dict[str, int] = {}
    for q in negatives:
        docs, _ = svc.search_bands(base_qs[q.query_id], limit=LIMIT)
        neg_real_p[q.query_id] = len(docs)

    # company-003
    q003 = next(q for q in questions if q.query_id == "company-003")
    g003 = next(iter(q003.relevant_sources))
    sel003 = [aliases.get(d.source_id, d.source_id) for d in prod_docs["company-003"]]
    c3 = {
        "gold_selected": g003 in sel003,
        "gold_position": (sel003.index(g003) + 1) if g003 in sel003 else None,
        "targets_matched": sum(
            1 for t in q003.evidence_targets
            if any(t.matches(ev) for doc in obs_p["company-003"].documents
                   for ev in doc.evidence)),
    }

    # ── 硬门判定 ──────────────────────────────────────────────────────────
    exp_pfp = expected["per_arm"]["prune_fn_punct"]
    exp_anchor = expected["per_arm"]["anchor"]
    gates: dict[str, bool] = {
        "G1_machinery_explicit_rank_query_equals_arm": not g1_mismatch,
        "G2_evidence_pass_21_24": f"{ep_p}/24" == exp_pfp["evidence_pass"],
        "G2_matched_75": bks_p == exp_pfp["buckets_82_targets"],
        "G2_newly_matched_exact": newly == exp_pfp["diff_vs_anchor"]["newly_matched"],
        "G2_zero_regression": regressed == exp_pfp["diff_vs_anchor"]["regressed"] == [],
        "G2_selection_changed_24": len(sel_changed) == exp_pfp["selection_changed_vs_anchor"],
        "G2_width_33_le_49": width_p == exp_pfp["band_width_max"] <= 49,
        "G2_company003_6_6_pos1": (
            c3["gold_selected"] is True and c3["gold_position"] == 1
            and c3["targets_matched"] == expected["company003"]["prune_fn_punct"]["targets_matched"]),
        "G3_switch_off_equals_anchor_arm": not g3_mismatch,
        "G3_switch_off_metrics_equal_anchor_record": (
            f"{ep_o}/24" == exp_anchor["evidence_pass"]
            and bks_o == exp_anchor["buckets_82_targets"]
            and width_o == exp_anchor["band_width_max"]),
        "G4_negatives_equal_record_and_no_raise": (
            neg_real_p == expected["negatives"]["real_search_diagnostic"]["prune_fn_punct"]
            and all(neg_real_p[k] <= expected["negatives"]["real_search_diagnostic"]["anchor"][k]
                    for k in neg_real_p)),
    }
    failed = [k for k, v in gates.items() if not v]
    if failed:
        raise RuntimeError(f"r4v 落地复验硬门失败: {failed}; "
                           f"g1={g1_mismatch[:3]} g3={g3_mismatch[:3]} "
                           f"ep_p={ep_p}/24 bks_p={bks_p} newly={newly} "
                           f"ep_o={ep_o}/24 bks_o={bks_o} neg={neg_real_p}")

    summary = {
        "artifact": "r4v-replay",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": "i2_sandbox_corpus active publications",
        "mode": ("c′ prune_fn_punct 产品落地复验（i0c-r4v）：产品路径 vs 独立重算臂 vs "
                 "c3w-eval.json 记录值；只读 PG、0 model calls、corpus schema 零写入"),
        "product_path": "svc.search_bands（search_pg 双 tsquery：WHERE 全词元 / score 实词）",
        "gates": gates,
        "product_funnel": {
            "evidence_pass": f"{ep_p}/24",
            "buckets_82_targets": bks_p,
            "newly_matched_vs_switch_off": newly,
            "regressed_vs_switch_off": regressed,
            "selection_changed_vs_switch_off": len(sel_changed),
            "band_width_max": width_p,
            "company003": c3,
        },
        "diagnostics": {
            "lexeme_source_note": (
                "评估臂排序词元取自题面；产品默认路径取自收到的查询串（rollout-plan §3.2）。"
                "两口径在 82 目标漏斗上逐值等值（G2 全绿），band 划分可不同。"),
            "default_vs_arm_doc_mismatch": default_vs_arm_doc_mismatch,
        },
        "switch_off_funnel": {
            "evidence_pass": f"{ep_o}/24",
            "buckets_82_targets": bks_o,
            "band_width_max": width_o,
        },
        "negatives_real_search": neg_real_p,
        "expected_source": str(C3W / "c3w-eval.json"),
    }
    write_once("r4v-replay.json", summary, dry_run=dry_run)
    print(json.dumps({"gates": gates, "product_funnel": summary["product_funnel"],
                      "switch_off_funnel": summary["switch_off_funnel"],
                      "negatives": neg_real_p}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
