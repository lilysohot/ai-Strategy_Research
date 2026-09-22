"""B5/M6 判据现状机读盘点（spec §14.8 B5 收口清单的机读归因）。

对 M6（`docs/plan/corpus-ingestion-rebuild-tasks.md:260`）中**可只读实测**的判据逐条出数：

- 逐类三指标：`score()` 按冻结 policy（`calibration-plan-v2.json`，min_rate=19/20）
  对 24 有答案题出 doc_recall / question_pass / evidence_pass 的**逐类**账 + 判定门；
- 关键题 100%：`critical=True` 题的 question_pass/evidence_pass + `critical_failures`；
- 伪引用负例 0：负例观测 NO_MATCH 下 `false_positives`（诊断）+ 引 B2 产品 abstain 复验
  （`audits/20260922-b2-abstain-reject/`，abstain=on 真 0）；
- 3 道未 pass 题逐目标归因：桶（sbf/not_selected）、quote 是否在带文本（空白规约）、
  locator 缺口、cell 证据有无、金标文档位次；并对照 `RANK_LEXEME_PRUNE=False`
  （anchor 口径）确认非 r4v 排序信号引入的回退。

不在本脚本范围（需授权/另立作业，只在报告记 pending）：I3-5 旧检索/财务基线非回归、
I3-6 最终冻结、I3-7 重验、M6 放行（独立复核 + U 具名签认）。

只读 PG（corpus schema 零写入）、0 model calls、不写库、不 commit；产物 write-once
（b5-inventory.json，语义逐字段比较、剔 generated_at），`--no-write` 只跑不写。
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
            print(f"[write-once] {name}: 语义逐字段一致 → 保留原产物", file=sys.stderr)
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

    from plugins.corpus.preparation import read_pg, search_pg
    from plugins.corpus.preparation.chunk import normalize_search_text
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
    MIN_RATE = Fraction(19, 20)

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

    positives = [q for q in questions if q.answer_existence is not AnswerExistence.NO_ANSWER]
    negatives = [q for q in questions if q.answer_existence is AnswerExistence.NO_ANSWER]
    assert len(positives) == 24 and len(negatives) == 6

    base_qs: dict[str, str] = {}
    with psycopg.connect(dsn, autocommit=True) as c0:
        for q in questions:
            lex = c0.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(q.question),)).fetchone()[0]
            base_qs[q.query_id] = or_str(tuple(str(t) for t in lex))

    prod_docs: dict[str, tuple] = {}
    off_docs: dict[str, tuple] = {}
    for q in positives:
        qid = q.query_id
        prod_docs[qid], _ = svc.search_bands(base_qs[qid], limit=LIMIT)
    saved = search_pg.RANK_LEXEME_PRUNE
    try:
        search_pg.RANK_LEXEME_PRUNE = False
        for q in positives:
            off_docs[q.query_id], _ = svc.search_bands(base_qs[q.query_id], limit=LIMIT)
    finally:
        search_pg.RANK_LEXEME_PRUNE = saved

    obs_p = {q.query_id: observation_for_docs(q.query_id, prod_docs[q.query_id])
             for q in positives}
    obs_off = {q.query_id: observation_for_docs(q.query_id, off_docs[q.query_id])
               for q in positives}
    for q in negatives:
        obs_p[q.query_id] = QueryObservation(q.query_id, ObservationOutcome.NO_MATCH, ())

    report = score(questions, [obs_p[q.query_id] for q in questions], policy)

    # 负例真检索诊断（abstain 关，同 c3w/r4v 口径；B2 已证 abstain=on 产品 0）
    neg_real: dict[str, int] = {}
    for q in negatives:
        docs, _ = svc.search_bands(base_qs[q.query_id], limit=LIMIT)
        neg_real[q.query_id] = len(docs)

    # ── 逐题/逐目标归因 ──────────────────────────────────────────────────
    def no_ws(s: str) -> str:
        return "".join(ch for ch in s if not ch.isspace())

    per_question = []
    for q in positives:
        qid = q.query_id
        ob = obs_p[qid]
        sel = [aliases.get(d.source_id, d.source_id) for d in ob.documents]
        gold_in = [g for g in q.relevant_sources if g in sel]
        qs = report.question(qid)
        fail_targets = []
        for t in q.evidence_targets:
            hit = any(t.matches(ev) for doc in ob.documents for ev in doc.evidence)
            if hit:
                continue
            quote_in_band = False
            loc_missing: list[str] = []
            pages_needed = [tok for tok in t.locator if tok.startswith("page:")]
            rowcol_needed = [tok for tok in t.locator if tok.startswith(("row:", "col:"))]
            cell_locators_available: list[str] = []
            band_pages: list[int] = []
            for doc in ob.documents:
                for ev in doc.evidence:
                    toks = set(ev.locator)
                    if rowcol_needed or any(tk.startswith(("row:", "col:")) for tk in toks):
                        cell_locators_available += [tk for tk in toks
                                                    if tk.startswith(("row:", "col:"))]
                    if any(tk.startswith("page:") for tk in toks):
                        band_pages += [int(tk.split(":", 1)[1]) for tk in toks
                                       if tk.startswith("page:")]
                    if no_ws(t.quote) in no_ws(ev.text):
                        quote_in_band = True
                        loc_missing = [tok for tok in t.locator if tok not in toks]
            src_bound = t.source_id or (gold_in[0] if gold_in else None)
            if t.source_id:
                bucket = ("selected_but_match_fail" if t.source_id in sel
                          else "source_doc_not_selected")
            else:
                bucket = "selected_but_match_fail" if gold_in else "not_selected"
            hit_off = any(
                t.matches(ev)
                for doc in obs_off[qid].documents for ev in doc.evidence)
            fail_targets.append({
                "target_id": t.target_id,
                "source_id": t.source_id,
                "bucket": bucket,
                "quote_in_band_text": quote_in_band,
                "locator_missing": loc_missing,
                "needs_cell_locator": bool(rowcol_needed),
                "cell_locators_in_evidence_sample": sorted(set(cell_locators_available))[:12],
                "pages_needed": pages_needed,
                "pages_in_bands_sample": sorted(set(band_pages))[:12],
                "also_fails_under_switch_off": not hit_off,
            })
        per_question.append({
            "query_id": qid,
            "domain": qs.domain,
            "critical": qs.critical,
            "question_pass": qs.question_pass,
            "evidence_pass": qs.evidence_pass,
            "doc_recall": None if qs.doc_recall is None else str(qs.doc_recall),
            "failures": list(qs.failures),
            "gold_doc_selected": bool(gold_in),
            "gold_doc_position": (sel.index(gold_in[0]) + 1) if gold_in else None,
            "n_targets": len(q.evidence_targets),
            "n_matched": sum(1 for t in q.evidence_targets
                             if any(t.matches(ev) for doc in ob.documents for ev in doc.evidence)),
            "fail_target_detail": fail_targets,
        })

    classes = [{
        "domain": c.domain,
        "answerable_total": c.answerable_total,
        "doc_recall": None if c.doc_recall.rate is None else str(c.doc_recall.rate),
        "question_pass": f"{c.question_pass.passed}/{c.question_pass.total}",
        "evidence_pass": f"{c.evidence_pass.passed}/{c.evidence_pass.total}",
        "gate_doc_recall_ge_19_20": (c.doc_recall.rate is not None
                                     and c.doc_recall.rate >= MIN_RATE),
        "gate_question_pass_ge_19_20": (c.question_pass.rate is not None
                                        and c.question_pass.rate >= MIN_RATE),
        "gate_evidence_pass_ge_19_20": (c.evidence_pass.rate is not None
                                        and c.evidence_pass.rate >= MIN_RATE),
    } for c in report.classes]

    ep_counts = report.overall.evidence_pass_counts
    qp_counts = report.overall.question_pass_counts
    crit_pos = [q for q in positives if q.critical]
    crit_ep_fail = [r["query_id"] for r in per_question if r["critical"] and not r["evidence_pass"]]

    summary = {
        "artifact": "b5-m6-inventory",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": "i2_sandbox_corpus active publications",
        "mode": ("B5/M6 可只读实测判据盘点：产品路径（RANK_LEXEME_PRUNE 默认 on）+ 冻结 policy；"
                 "只读 PG、0 model calls、corpus schema 零写入"),
        "frozen_policy": {
            "min_rate": str(policy.min_rate),
            "top_k": policy.top_k,
            "require_critical_all_pass": policy.require_critical_all_pass,
            "max_false_positives": policy.max_false_positives,
            "max_fabricated_citations": policy.max_fabricated_citations,
        },
        "m6_evidence": {
            "evidence_pass_counts": f"{ep_counts[0]}/{ep_counts[1]}",
            "question_pass_counts": f"{qp_counts[0]}/{qp_counts[1]}",
            "per_class": classes,
            "all_class_gates_pass": all(
                c["gate_doc_recall_ge_19_20"] and c["gate_question_pass_ge_19_20"]
                and c["gate_evidence_pass_ge_19_20"] for c in classes),
            "critical_total_positives": len(crit_pos),
            "critical_evidence_pass_fails": crit_ep_fail,
            "critical_all_pass": not crit_ep_fail,
            "critical_failures_blockers": list(report.critical_failures),
            "false_positives": list(report.false_positives),
            "fabricated_citations": list(report.fabricated_citations),
            "negatives_real_search_diagnostic": neg_real,
            "negatives_product_abstain": {
                "evidence": "audits/20260922-b2-abstain-reject/b2-summary.json",
                "result": "CORPUS_ABSTAIN_NO_ANSWER=on：6/6 hits=0 + abstain=true（I-M6-1 产品侧达成）",
            },
        },
        "failing_questions": [r for r in per_question if not r["evidence_pass"]],
        "per_question": per_question,
        "score_report_passed": report.passed,
        "blockers": list(report.blockers),
        "out_of_scope_pending": {
            "I3-5_nonregression": "旧检索 golden、财务 57/57、公式 7/7、客户表 12/12、正文 3/3、宏观 0/3 另列——未执行，需环境/预算授权",
            "I3-6_final_freeze": "结束校准并冻结最终配置/代码/评分器/预期 + 不可变最终 manifest——未执行（前置 I3-3/4/5）",
            "I3-7_reverify": "用 I3-6 版本重建/重索引并全链重验（E2E 12 项 + gap dispositions + 受影响 M4/M5 门）——未执行（前置 I3-6）",
            "M6_signoff": "M6 放行只能由独立复核 + U 具名签认给出（plan 纪律），不以本脚本放行",
        },
    }

    write_once("b5-inventory.json", summary, dry_run=dry_run)

    print(json.dumps({
        "evidence_pass": summary["m6_evidence"]["evidence_pass_counts"],
        "per_class": [(c["domain"], c["evidence_pass"], c["doc_recall"]) for c in classes],
        "critical_fails": crit_ep_fail,
        "failing_questions": [r["query_id"] for r in summary["failing_questions"]],
        "all_class_gates_pass": summary["m6_evidence"]["all_class_gates_pass"],
        "score_report_passed": report.passed,
        "blockers": summary["blockers"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
