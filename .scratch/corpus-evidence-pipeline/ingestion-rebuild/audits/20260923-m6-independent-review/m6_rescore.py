"""M6 独立复核 · 独立重评分探针（**不 import i37_score.py**，全新最小 harness）。

独立性设计（对齐 20260918-i30-review 先例：不重用被复核脚本的组装，只复用冻结库代码）：

- fail-closed 前置：导入任何插件模块前，先对账 i3-final-freeze-manifest.json 中
  scoring.py / calibration-plan-v2.json / guards/i3-e2e.json 的冻结哈希（不符即退出 1）；
- DSN 自 .env 独立解析 + fail-closed（host=127.0.0.1、port=543、db=i2_sandbox_corpus），
  再装守卫 guards/i3-e2e.json（零模型 / 网络仅 543 / forbidden_roots 留出零读取）；
- 三指标重算：冻结 gold（scoring-input-manifest 经 loader 自校验装载）× 冻结评分器
  ``plugins.corpus.scoring.score``（冻结字节）× 冻结 policy（calibration-plan-v2），
  产品检索走 ``CorpusService.search_bands``（冻结默认 RANK_LEXEME_PRUNE on），另跑
  off 对照（锚定 r4v 口径）；
- **逐字段对账**：per_question 30 行（question_pass/evidence_pass/doc_recall/failures）、
  overall 计数、逐类三指标（**由本探针自行从 per-question 聚合，不复用被复核账本**）、
  FP/fabricated 空集、critical 22 题、b5 基线对照、prune on/off 对照——全部 vs
  i37-score-results.json 独立重比；
- 负例双口径复验：abstain=on 下 6 负例拒答 + 24 正例拒检诊断（pending 项独立复证）；
- authority 取证回环：探针自选样本（不复用 i37 的 company-001 探针）+ 未知句柄拒绝。

零模型、沙箱只读（corpus schema 零写入）、生产库 5432 零触碰。产物 write-once：
m6-rescore.json。用法（仓库根）::

    env -u PYTHONPATH uv run python \\
      .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/m6_rescore.py
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import sys
from datetime import UTC, datetime
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
FINAL_MANIFEST = BASE / "i3-final-freeze-manifest.json"
I37_SCORE_RESULTS = BASE / "audits/20260923-i37-final-reverify/i37-score-results.json"
GUARD = BASE / "guards/i3-e2e.json"
CALIB = BASE / "audits/20260920-i33-calibration"
SANDBOX_DB = "i2_sandbox_corpus"
LIMIT = 2000
MIN_RATE = Fraction(19, 20)
sys.path.insert(0, str(ROOT))

NON_SEMANTIC = ("generated_at",)


def _semantic(value):
    if isinstance(value, dict):
        return {k: _semantic(v) for k, v in value.items() if k not in NON_SEMANTIC}
    if isinstance(value, list):
        return [_semantic(v) for v in value]
    return value


def write_once(name: str, value) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists():
        if _semantic(json.loads(path.read_text(encoding="utf-8"))) != _semantic(value):
            raise RuntimeError(f"write-once conflict: {name}")
        print(f"[write-once] {name}: 语义一致 → 保留", file=sys.stderr)
        return
    path.write_bytes(raw)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def fail(msg: str) -> None:
    print(json.dumps({"fatal": msg}, ensure_ascii=False), file=sys.stderr)
    raise SystemExit(1)


def main() -> int:
    # 0) 冻结哈希 fail-closed（先于任何插件导入）
    fm = json.loads(FINAL_MANIFEST.read_text(encoding="utf-8"))
    frozen = fm["frozen_assets"]
    expect_scorer = frozen["implementation"]["plugins/corpus/scoring.py"]
    expect_calib = frozen["expectations_and_policy"][
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/"
        "calibration-plan-v2.json"]
    expect_guard = frozen["guards"][".scratch/corpus-evidence-pipeline/ingestion-rebuild/"
                                   "guards/i3-e2e.json"]
    scorer_path = ROOT / "plugins/corpus/scoring.py"
    if digest(scorer_path) != expect_scorer:
        fail("plugins/corpus/scoring.py 字节与冻结清单不符——拒绝继续")
    if digest(CALIB / "calibration-plan-v2.json") != expect_calib:
        fail("calibration-plan-v2.json 与冻结清单不符")
    if digest(GUARD) != expect_guard:
        fail("guards/i3-e2e.json 与冻结清单不符")
    scoring_manifest_path = BASE / "i3-2/scoring-input-manifest.json"
    scoring_manifest_sha = digest(scoring_manifest_path)

    # 1) DSN 独立解析 + fail-closed（守卫会投毒环境变量，故只读 .env 文件）
    env: dict[str, str] = {}
    for line in (ROOT / ".env").read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            env[line.split("=", 1)[0]] = line.split("=", 1)[1]
    raw_dsn = env.get("CORPUS_DSN", "")
    cred_part = raw_dsn.split("://", 1)[-1].rsplit("@", 1)[0]
    from urllib.parse import urlsplit

    parts = urlsplit(f"postgresql://{cred_part}@127.0.0.1:543/{SANDBOX_DB}")
    if parts.hostname != "127.0.0.1" or parts.port != 543 or parts.path != f"/{SANDBOX_DB}":
        fail(f"DSN fail-closed 校验失败：{parts.hostname}:{parts.port}{parts.path}")
    sandbox_dsn = f"postgresql://{cred_part}@127.0.0.1:543/{SANDBOX_DB}"

    # 2) 装守卫（先于其余插件导入）
    from plugins.corpus.preparation import guard as guard_module

    guard_module.install(GUARD)

    import psycopg

    from plugins.corpus.preparation import read_pg, search_pg
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.scoring import (AnswerExistence, FetchedEvidence, ObservationOutcome,
                                        QueryObservation, RetrievedDocument, ScoringPolicy,
                                        gold_from_records, score)
    from plugins.corpus.service import CorpusService

    loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(scoring_manifest_path)
    questions = gold_from_records(records)
    policy_cfg = dict(json.loads((CALIB / "calibration-plan-v2.json").read_text())["policy"])
    policy_cfg["min_rate"] = Fraction(policy_cfg["min_rate"])
    policy = ScoringPolicy(**policy_cfg)
    fp_cfg = fm["runtime_configuration"]["frozen_policy"]
    policy_ok = (str(policy.min_rate) == fp_cfg["min_rate"] and policy.top_k == fp_cfg["top_k"]
                 and policy.require_critical_all_pass == fp_cfg["require_critical_all_pass"]
                 and policy.max_false_positives == fp_cfg["max_false_positives"]
                 and policy.max_fabricated_citations == fp_cfg["max_fabricated_citations"])
    if not policy_ok:
        fail("评分 policy 与冻结口径不符")

    positives = [q for q in questions if q.answer_existence is not AnswerExistence.NO_ANSWER]
    negatives = [q for q in questions if q.answer_existence is AnswerExistence.NO_ANSWER]
    if len(positives) != 24 or len(negatives) != 6:
        fail(f"gold 形态漂移：正例 {len(positives)} / 负例 {len(negatives)}")

    svc = CorpusService(sandbox_dsn)
    read_chain = svc.read_chain()
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX_DB)
        sources = {r[0] for r in conn.execute(
            "SELECT source_id FROM corpus.corpus_publications WHERE active_build_id IS NOT NULL"
        ).fetchall()}
    if read_chain != "new" or len(sources) != 8:
        fail(f"read_chain={read_chain} active={len(sources)}（需 new/8）")

    expected_aliases = sorted({s for q in questions for s in q.relevant_sources}
                              | {t.source_id for q in questions
                                 for t in q.evidence_targets if t.source_id})
    aliases: dict[str, str] = {}
    for alias in expected_aliases:
        short = alias.rsplit("_", 1)[-1]
        matches = [s for s in sources if s.startswith(short)]
        if len(matches) != 1:
            fail(f"gold alias 解析不唯一：{alias} → {len(matches)}")
        aliases[matches[0]] = alias

    def observation_for(query_id: str, docs) -> QueryObservation:
        documents = []
        for doc in docs:
            evidences: list[FetchedEvidence] = []
            for band_items in doc.chunks_by_band:
                texts = [it.text for it in band_items]
                pages = sorted({p for it in band_items for p in it.pages})
                if texts:
                    evidences.append(FetchedEvidence(
                        "\n".join(texts), tuple(f"page:{p}" for p in pages), True))
            for cell in doc.cells:
                loc = ([f"page:{cell.page}"] if cell.page is not None else []) + \
                      ["row:" + cell.row, "col:" + cell.col]
                evidences.append(FetchedEvidence(cell.text, tuple(loc), True))
            documents.append(RetrievedDocument(
                aliases.get(doc.source_id, doc.source_id), tuple(evidences), doc.build_id))
        return QueryObservation(
            query_id, ObservationOutcome.OK if documents else ObservationOutcome.NO_MATCH,
            tuple(documents))

    base_qs: dict[str, str] = {}
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn:
        for q in questions:
            lex = conn.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(q.question),)).fetchone()[0]
            base_qs[q.query_id] = " OR ".join(
                '"' + str(t).replace('"', " ") + '"' for t in lex)

    # 3) 产品检索双跑（on=冻结默认 / off=锚定对照）+ 冻结评分器
    docs_on: dict[str, tuple] = {}
    docs_off: dict[str, tuple] = {}
    for q in positives:
        docs_on[q.query_id], _ = svc.search_bands(base_qs[q.query_id], limit=LIMIT)
    saved = search_pg.RANK_LEXEME_PRUNE
    try:
        search_pg.RANK_LEXEME_PRUNE = False
        for q in positives:
            docs_off[q.query_id], _ = svc.search_bands(base_qs[q.query_id], limit=LIMIT)
    finally:
        search_pg.RANK_LEXEME_PRUNE = saved

    obs_on = {q.query_id: observation_for(q.query_id, docs_on[q.query_id]) for q in positives}
    obs_off = {q.query_id: observation_for(q.query_id, docs_off[q.query_id]) for q in positives}
    for q in negatives:
        obs_on[q.query_id] = QueryObservation(q.query_id, ObservationOutcome.NO_MATCH, ())
        obs_off[q.query_id] = QueryObservation(q.query_id, ObservationOutcome.NO_MATCH, ())

    report = score(questions, [obs_on[q.query_id] for q in questions], policy)
    report_off = score(questions, [obs_off[q.query_id] for q in questions], policy)

    per_question = [{
        "query_id": qs.query_id, "domain": qs.domain, "critical": qs.critical,
        "negative": qs.answer_existence is AnswerExistence.NO_ANSWER,
        "question_pass": qs.question_pass, "evidence_pass": qs.evidence_pass,
        "doc_recall": None if qs.doc_recall is None else str(qs.doc_recall),
        "failures": list(qs.failures),
    } for qs in report.questions]

    # 4) 逐类聚合：本探针自行从 per-question 汇总（不读被复核账本的类行）
    classes_recomputed: dict[str, dict] = {}
    for row in per_question:
        if row["negative"]:
            continue
        c = classes_recomputed.setdefault(row["domain"], {
            "answerable_total": 0, "qp": 0, "ep": 0, "doc_recall_sum": Fraction(0)})
        c["answerable_total"] += 1
        c["qp"] += int(row["question_pass"] is True)
        c["ep"] += int(row["evidence_pass"] is True)
        if row["doc_recall"] is not None:
            c["doc_recall_sum"] += Fraction(row["doc_recall"])
    class_rows = []
    for domain in sorted(classes_recomputed):
        c = classes_recomputed[domain]
        qp_rate = Fraction(c["qp"], c["answerable_total"])
        ep_rate = Fraction(c["ep"], c["answerable_total"])
        # 类级 doc_recall 用均值（与冻结评分器 DocRecall.rate 同口径：逐题 recall 之和 / 题数）
        recall_mean = c["doc_recall_sum"] / c["answerable_total"]
        class_rows.append({
            "domain": domain,
            "answerable_total": c["answerable_total"],
            "doc_recall": str(recall_mean),
            "question_pass": f"{c['qp']}/{c['answerable_total']}",
            "evidence_pass": f"{c['ep']}/{c['answerable_total']}",
            "gate_doc_recall_ge_19_20": recall_mean >= MIN_RATE,
            "gate_question_pass_ge_19_20": qp_rate >= MIN_RATE,
            "gate_evidence_pass_ge_19_20": ep_rate >= MIN_RATE,
        })

    crit_pos = [q for q in positives if q.critical]
    crit_fails = sorted(row["query_id"] for row in per_question
                        if row["critical"] and row["evidence_pass"] is False)

    # 5) b5 基线对照（独立读取基线文件）
    b5 = json.loads((BASE / "audits/20260923-b5-final/b5-inventory.json").read_text(
        encoding="utf-8"))
    b5_classes = {c["domain"]: c for c in b5["m6_evidence"]["per_class"]}
    baseline_regressions = []
    for row in class_rows:
        base = b5_classes.get(row["domain"])
        if base is None:
            baseline_regressions.append({"domain": row["domain"], "reason": "b5 缺该类"})
            continue
        for name, cur, old in (("doc_recall", Fraction(row["doc_recall"]),
                                Fraction(base["doc_recall"])),
                               ("question_pass", Fraction(row["question_pass"]),
                                Fraction(base["question_pass"])),
                               ("evidence_pass", Fraction(row["evidence_pass"]),
                                Fraction(base["evidence_pass"]))):
            if cur < old:
                baseline_regressions.append({"domain": row["domain"], "metric": name,
                                             "current": str(cur), "b5": str(old)})

    # 6) prune on/off 对照（独立口径重算）
    pass_on = {qs.query_id: qs.question_pass for qs in report.questions}
    pass_off = {qs.query_id: qs.question_pass for qs in report_off.questions}
    prune_regressions = sorted(qid for qid, on in pass_on.items()
                               if on is False and pass_off.get(qid))
    prune_improvements = sorted(qid for qid, on in pass_on.items()
                                if on and pass_off.get(qid) is False)

    # 7) abstain=on 双口径复验（raw 题干）
    saved_abstain = os.environ.get("CORPUS_ABSTAIN_NO_ANSWER")
    os.environ["CORPUS_ABSTAIN_NO_ANSWER"] = "on"
    try:
        neg_rows, pos_rows = [], []
        for q in questions:
            hits, cov = svc.search_with_coverage(q.question, limit=10)
            row = {"query_id": q.query_id, "n_hits": len(hits),
                   "abstain": bool(cov.get("abstain")), "query_status": cov.get("query_status")}
            (neg_rows if q.answer_existence is AnswerExistence.NO_ANSWER
             else pos_rows).append(row)
    finally:
        if saved_abstain is None:
            os.environ.pop("CORPUS_ABSTAIN_NO_ANSWER", None)
        else:
            os.environ["CORPUS_ABSTAIN_NO_ANSWER"] = saved_abstain
    abstain_neg_ok = len(neg_rows) == 6 and all(r["n_hits"] == 0 and r["abstain"]
                                                for r in neg_rows)
    pos_rejected = sorted(r["query_id"] for r in pos_rows
                          if r["n_hits"] == 0 or r["abstain"])

    # 8) authority 回环：探针自选样本（最后一条正例的最后一份文档）
    probe_q = positives[-1]
    probe_doc = docs_on[probe_q.query_id][-1]
    probe_item = probe_doc.chunks_by_band[0][0]
    authority = {
        "probe_query": probe_q.query_id,
        "probe_source_alias": aliases.get(probe_doc.source_id, probe_doc.source_id),
        "doc_handle": probe_doc.doc_handle,
        "handle_format_ok": probe_doc.doc_handle.startswith("cv2:"),
        "locator": read_pg.chunk_locator(probe_item.chunk_id),
    }
    authority_ok = False
    try:
        ev = svc.fetch_verbatim(probe_doc.doc_handle, authority["locator"])
        authority["roundtrip"] = {
            "build_id_match": ev.build_id == probe_doc.build_id,
            "chunk_id_match": ev.chunk_id == probe_item.chunk_id,
            "n_units": len(ev.units),
            "text_nonempty": bool(ev.text.strip()),
        }
        try:
            svc.fetch_verbatim("cv2:" + "f" * 64, authority["locator"])
            authority["unknown_handle_rejected"] = False
        except read_pg.UnknownHandleError:
            authority["unknown_handle_rejected"] = True
        rt = authority["roundtrip"]
        authority_ok = (rt["build_id_match"] and rt["chunk_id_match"] and rt["n_units"] > 0
                        and rt["text_nonempty"] and authority["unknown_handle_rejected"])
    except read_pg.ReadError as exc:
        authority["roundtrip_error"] = f"{type(exc).__name__}: {exc}"

    # 9) 与 i37-score-results.json 逐字段对账
    i37 = json.loads(I37_SCORE_RESULTS.read_text(encoding="utf-8"))
    i37_by_qid = {row["query_id"]: row for row in i37["per_question"]}
    field_diffs: list[dict] = []
    for row in per_question:
        ref = i37_by_qid.get(row["query_id"])
        if ref is None:
            field_diffs.append({"query_id": row["query_id"], "field": "*", "reason": "i37 缺行"})
            continue
        for key in ("question_pass", "evidence_pass", "doc_recall", "failures",
                    "critical", "negative", "domain"):
            if row[key] != ref.get(key):
                field_diffs.append({"query_id": row["query_id"], "field": key,
                                    "m6": row[key], "i37": ref.get(key)})
    overall_qp = f"{sum(int(r['question_pass'] is True) for r in per_question if not r['negative'])}/24"
    overall_ep = f"{sum(int(r['evidence_pass'] is True) for r in per_question if not r['negative'])}/24"
    i37_cls = {c["domain"]: c for c in i37["scoring"]["per_class"]}
    class_diffs = []
    for row in class_rows:
        ref = i37_cls.get(row["domain"])
        if ref is None:
            class_diffs.append({"domain": row["domain"], "reason": "i37 缺类行"})
            continue
        for key in ("answerable_total", "doc_recall", "question_pass", "evidence_pass",
                    "gate_doc_recall_ge_19_20", "gate_question_pass_ge_19_20",
                    "gate_evidence_pass_ge_19_20"):
            if row[key] != ref.get(key):
                class_diffs.append({"domain": row["domain"], "field": key,
                                    "m6": row[key], "i37": ref.get(key)})
    reconcile = {
        "overall_question_pass": {"m6": overall_qp, "i37": i37["scoring"]["question_pass_counts"],
                                  "match": overall_qp == i37["scoring"]["question_pass_counts"]},
        "overall_evidence_pass": {"m6": overall_ep, "i37": i37["scoring"]["evidence_pass_counts"],
                                  "match": overall_ep == i37["scoring"]["evidence_pass_counts"]},
        "false_positives_empty": not report.false_positives,
        "fabricated_citations_empty": not report.fabricated_citations,
        "critical_total_positives": {"m6": len(crit_pos),
                                     "i37": i37["scoring"]["critical_total_positives"],
                                     "match": len(crit_pos)
                                     == i37["scoring"]["critical_total_positives"]},
        "critical_fails": {"m6": crit_fails,
                           "i37": i37["scoring"]["critical_evidence_pass_fails"],
                           "match": crit_fails == i37["scoring"]["critical_evidence_pass_fails"]},
        "per_question_field_diffs": field_diffs,
        "per_class_field_diffs": class_diffs,
        "baseline_regressions": {"m6": baseline_regressions,
                                 "i37": i37["baseline_comparison"]["regressions"],
                                 "match": baseline_regressions
                                 == i37["baseline_comparison"]["regressions"]},
        "prune": {"m6_improvements": prune_improvements,
                  "m6_regressions": prune_regressions,
                  "i37_improvements": i37["rank_lexeme_prune_comparison"]
                  ["improvements_on_better_than_off"],
                  "i37_regressions": i37["rank_lexeme_prune_comparison"]
                  ["regressions_on_worse_than_off"]},
        "abstain_negatives_6_of_6": {"m6": abstain_neg_ok,
                                     "i37": i37["negatives"]["product_abstain_on"]
                                     ["negatives_rejected_6_of_6"]},
        "abstain_positives_rejected": {"m6": len(pos_rejected),
                                       "m6_query_ids": pos_rejected,
                                       "i37_count": i37["negatives"]["product_abstain_on"]
                                       ["positives_diagnostic"]["n_positives_rejected"]},
    }
    reconcile_ok = (reconcile["overall_question_pass"]["match"]
                    and reconcile["overall_evidence_pass"]["match"]
                    and reconcile["false_positives_empty"]
                    and reconcile["fabricated_citations_empty"]
                    and reconcile["critical_total_positives"]["match"]
                    and reconcile["critical_fails"]["match"]
                    and not field_diffs and not class_diffs
                    and reconcile["baseline_regressions"]["match"]
                    and not prune_regressions
                    and prune_improvements == i37["rank_lexeme_prune_comparison"]
                    ["improvements_on_better_than_off"]
                    and abstain_neg_ok
                    and len(pos_rejected) == i37["negatives"]["product_abstain_on"]
                    ["positives_diagnostic"]["n_positives_rejected"]
                    and authority_ok and policy_ok)

    results = {
        "artifact": "m6-independent-rescore",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "independence": {
            "imports_i37_score": False,
            "imports_i37_rebuild": False,
            "frozen_scorer": "plugins/corpus/scoring.py",
            "frozen_scorer_sha256": expect_scorer,
            "scorer_bytes_match_freeze": True,
            "calibration_sha256": expect_calib,
            "guard_sha256": expect_guard,
            "scoring_input_manifest_sha256_recorded": scoring_manifest_sha,
            "probe_authority_sample": f"{authority['probe_query']}（与 i37 的 company-001 不同）",
        },
        "dsn_fail_closed": {"host": "127.0.0.1", "port": 543, "db": SANDBOX_DB},
        "read_chain": read_chain,
        "active_sources": len(sources),
        "policy_matches_freeze": policy_ok,
        "overall": {"question_pass": overall_qp, "evidence_pass": overall_ep,
                    "doc_recall_all_classes": {r["domain"]: r["doc_recall"]
                                               for r in class_rows}},
        "per_class_recomputed": class_rows,
        "per_question": per_question,
        "critical": {"total_positives": len(crit_pos), "fails": crit_fails},
        "false_positives": list(report.false_positives),
        "fabricated_citations": list(report.fabricated_citations),
        "baseline_regressions": baseline_regressions,
        "prune_comparison": {"improvements_on": prune_improvements,
                             "regressions_on": prune_regressions},
        "abstain_on": {"negatives": neg_rows, "negatives_rejected_6_of_6": abstain_neg_ok,
                       "positives_rejected": pos_rejected},
        "authority": authority,
        "authority_ok": authority_ok,
        "reconciliation_vs_i37": reconcile,
        "all_match": reconcile_ok,
        "discipline": {
            "model_calls": 0,
            "guard": "guards/i3-e2e.json 已装载（零模型 / 网络仅 127.0.0.1:543 / "
                     "forbidden_roots 留出零读取）",
            "pg": "只读（SELECT 与检索/fetch；corpus schema 零写入）；生产 5432 零触碰",
        },
    }
    write_once("m6-rescore.json", results)
    print(json.dumps({"all_match": reconcile_ok,
                      "question_pass": overall_qp,
                      "evidence_pass": overall_ep,
                      "per_class": [(r["domain"], r["evidence_pass"], r["doc_recall"])
                                    for r in class_rows],
                      "field_diffs": field_diffs,
                      "class_diffs": class_diffs,
                      "prune_improvements": prune_improvements,
                      "abstain_neg_6_of_6": abstain_neg_ok,
                      "abstain_pos_rejected": len(pos_rejected),
                      "authority_ok": authority_ok}, ensure_ascii=False, indent=2))
    return 0 if reconcile_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
