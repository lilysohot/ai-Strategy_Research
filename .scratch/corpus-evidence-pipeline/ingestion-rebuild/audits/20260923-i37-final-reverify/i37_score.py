"""I3-7 重验之评分/取证/负例电池：对 I3-7 重建后的沙箱按 I3-6 冻结口径出全账。

- 三类评分：i3-2 冻结 gold（24 正例 + 6 负例）× 冻结 policy（``calibration-plan-v2.json``：
  min_rate=19/20、top_k=5、require_critical_all_pass、FP=0、fabricated=0），对重建后活动
  build 逐类出 doc_recall / question_pass / evidence_pass 三指标 + 判定门（§3.6 I3-7：
  「逐类三指标达冻结目标（候选 ≥95%）」）；
- 冻结一致性：REV 常量**代码级**对照 ``i3-final-freeze-manifest.json``（READER_PDF/DOCX/MD、
  CLEAN、CHUNK、INDEX、INGEST、PROBE）+ **库级指纹重算**（parse_rev=canonical_fingerprint(
  [PARSE_RULE_REV, source_id, reader._extractor_rev()])——pdf/docx 带库版本后缀，与写入
  侧唯一组装公式一致；clean/chunk/index 同法现算）；
- 不回退对照：与 b5 盘点基线（``audits/20260923-b5-final/b5-inventory.json``，冻结前
  收口 24/24）逐类比较，任何一类任何指标低于基线即失败；
- 排序开关对照：RANK_LEXEME_PRUNE on（冻结默认）/ off 双跑，on 劣于 off 的题即失败
  （on 改善记录在案，r4v 锚定口径）；
- 产品层负例（``CORPUS_ABSTAIN_NO_ANSWER=on``，b2/I-M6-1 同款 **raw 题干**）：6/6 拒检
  hits=[] + ``coverage["abstain"] is True``；正例表现**仅作诊断记录**（发现：abstain=on
  下 24/24 正例被拒检——AND 预检要求单单元全实质词元在真实语料归零；S1「正例不误拒」
  设计宣称未获正例证据。b2/I-M6-1 冻结口径只断言负例 6/6。非 I3-7 门，登记 pending
  待 U 裁决，不擅改冻结代码）；
- 取证 round-trip：search 命中句柄 ``cv2:…`` / ``chunk:…`` → fetch_verbatim 逐字取回
  （units 非空、build_id/chunk_id round-trip）+ 未知句柄 ``UnknownHandleError`` 拒绝。

守卫：``guards/i3-e2e.json``（装载后零模型、网络仅 127.0.0.1:543、forbidden_roots 留出
零读取）；DSN 自 .env 直读（不经被守卫投毒的进程环境）；生产库 5432 零触碰；
corpus schema 零写入；0 model calls。产物 write-once（i37-score-results.json，语义
逐字段比较、剔 generated_at），``--no-write`` 只跑不写。
用法（仓库根）： uv run python .scratch/.../audits/20260923-i37-final-reverify/i37_score.py
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
GUARD = BASE / "guards/i3-e2e.json"
FINAL_MANIFEST = BASE / "i3-final-freeze-manifest.json"
REBUILD_REPORT = HERE / "rebuild-report.json"
B5_INVENTORY = BASE / "audits/20260923-b5-final/b5-inventory.json"
CALIB = BASE / "audits/20260920-i33-calibration"
SANDBOX_DB = "i2_sandbox_corpus"
LIMIT = 2000
MIN_RATE = Fraction(19, 20)
sys.path.insert(0, str(ROOT))

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


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def main() -> int:
    import psycopg

    from plugins.corpus.preparation import read_pg, search_pg
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.search_pg import _check_target, search_chunks
    from plugins.corpus.scoring import (AnswerExistence, FetchedEvidence, ObservationOutcome,
                                        QueryObservation, RetrievedDocument, ScoringPolicy,
                                        gold_from_records, score)
    from plugins.corpus.service import _ABSTAIN_PRE_CHECK_LIMIT, CorpusService

    # 0) 输入 + 守卫 + DSN（.env 直读；守卫先装，之后再触碰插件内部）
    fm = json.loads(FINAL_MANIFEST.read_text(encoding="utf-8"))
    rebuild = json.loads(REBUILD_REPORT.read_text(encoding="utf-8"))
    b5 = json.loads(B5_INVENTORY.read_text(encoding="utf-8"))
    rebuild_summary = rebuild["summary"]
    if not rebuild_summary["all_new_build_active"]:
        print(json.dumps({"error": "重建报告显示并非全部新 build active——先收口重建步"},
                         ensure_ascii=False))
        return 1

    from plugins.corpus.preparation import guard as guard_module  # noqa: PLC0415

    guard_module.install(GUARD)

    rebuild_mod = load_module("i37_rebuild_mod", HERE / "i37_rebuild.py")
    _, sandbox_dsn = rebuild_mod._build_dsn(rebuild_mod._load_env(ROOT))

    loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")
    questions = gold_from_records(records)
    config = dict(json.loads((CALIB / "calibration-plan-v2.json").read_text())["policy"])
    config["min_rate"] = Fraction(config["min_rate"])
    policy = ScoringPolicy(**config)

    fp = fm["runtime_configuration"]["frozen_policy"]
    frozen_policy_ok = (
        str(policy.min_rate) == fp["min_rate"]
        and policy.top_k == fp["top_k"]
        and policy.require_critical_all_pass == fp["require_critical_all_pass"]
        and policy.max_false_positives == fp["max_false_positives"]
        and policy.max_fabricated_citations == fp["max_fabricated_citations"]
    )
    revs = fm["runtime_configuration"]["revs"]
    from plugins.corpus.preparation.admission import PROBE_REV  # noqa: PLC0415
    from plugins.corpus.preparation.chunk import CHUNK_REV  # noqa: PLC0415
    from plugins.corpus.preparation.clean import CLEAN_REV  # noqa: PLC0415
    from plugins.corpus.preparation.contract import (  # noqa: PLC0415
        DocumentFormat,
        canonical_fingerprint,
        sha256_of_bytes,
    )
    from plugins.corpus.preparation.engine import INDEX_REV_V3, PARSE_RULE_REV  # noqa: PLC0415
    from plugins.corpus.preparation.readers import (  # noqa: PLC0415
        docx_reader,
        pdf_reader,
    )
    from plugins.corpus.preparation.readers.md_reader import READER_MD_REV  # noqa: PLC0415
    from plugins.corpus.preparation.readers.pdf_reader import READER_PDF_REV  # noqa: PLC0415
    from plugins.corpus.preparation.source import INGEST_REV  # noqa: PLC0415

    # 写入侧 parse_rev 用的是 reader 自带 _extractor_rev()（pdf/docx 带库版本后缀，
    # md 为裸标签）——审计不自行拼公式，直接复用 reader 的组装函数。
    stamped_extractor_rev = {
        DocumentFormat.PDF: pdf_reader._extractor_rev(),
        DocumentFormat.DOCX: docx_reader._extractor_rev(),
        DocumentFormat.MARKDOWN: READER_MD_REV,
    }
    code_revs = {
        "reader_pdf": READER_PDF_REV,
        "reader_docx": docx_reader.READER_DOCX_REV,
        "reader_md": READER_MD_REV,
        "clean": CLEAN_REV,
        "chunk": CHUNK_REV,
        "index": INDEX_REV_V3,
        "ingest": INGEST_REV,
        "admission_probe": PROBE_REV,
    }
    code_revs_match = code_revs == dict(revs)

    # 1) 目标核验 + 活动发布指针
    svc = CorpusService(sandbox_dsn)
    read_chain = svc.read_chain()
    with psycopg.connect(sandbox_dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX_DB)
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())
        active_builds = conn.execute(
            "SELECT b.build_id, b.source_id, b.parse_rev, b.clean_rev, b.chunk_rev, "
            "b.index_rev FROM corpus.corpus_builds b WHERE b.build_id IN "
            "(SELECT active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL)").fetchall()
    sources_active_ok = len(sources) == rebuild_summary["published"]

    # 库级指纹重算：活动 build 的 revs 必须等于冻结常量按唯一组装公式的现算值
    fmt_by_sid: dict[str, str] = {}
    for entry in json.loads((BASE / "audits/20260920-i31-dev-lane/dev-scope-manifest.json")
                            .read_text(encoding="utf-8"))["sources"]:
        sid = sha256_of_bytes((ROOT / str(entry["path"])).read_bytes())
        fmt_by_sid[sid] = Path(str(entry["path"])).suffix.lower()
    fmt_enum = {".pdf": DocumentFormat.PDF, ".docx": DocumentFormat.DOCX,
                ".md": DocumentFormat.MARKDOWN}
    db_revs_ok = len(active_builds) == len(fmt_by_sid) and all(
        row[2] == canonical_fingerprint(
            [PARSE_RULE_REV, row[1], stamped_extractor_rev[fmt_enum[fmt_by_sid[row[1]]]]])
        and row[3] == canonical_fingerprint([CLEAN_REV])
        and row[4] == canonical_fingerprint([CHUNK_REV])
        and row[5] == INDEX_REV_V3
        for row in active_builds)
    rebuild_revs_ok = code_revs_match and db_revs_ok

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
    assert len(positives) == 24 and len(negatives) == 6, (
        f"冻结 gold 形态漂移：正例 {len(positives)} / 负例 {len(negatives)}（应为 24/6）")

    base_qs: dict[str, str] = {}
    with psycopg.connect(sandbox_dsn, autocommit=True) as c0:
        for q in questions:
            lex = c0.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(q.question),)).fetchone()[0]
            base_qs[q.query_id] = or_str(tuple(str(t) for t in lex))

    # 2) 产品检索：冻结默认（RANK_LEXEME_PRUNE on）+ 开关 off 对照
    prod_docs: dict[str, tuple] = {}
    off_docs: dict[str, tuple] = {}
    for q in positives:
        prod_docs[q.query_id], _ = svc.search_bands(base_qs[q.query_id], limit=LIMIT)
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
        obs_off[q.query_id] = QueryObservation(q.query_id, ObservationOutcome.NO_MATCH, ())

    report = score(questions, [obs_p[q.query_id] for q in questions], policy)
    report_off = score(questions, [obs_off[q.query_id] for q in questions], policy)

    # 3) 逐类账 + 判定门（冻结目标 min_rate=19/20）
    classes_rows = [{
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
    all_class_gates = all(
        c["gate_doc_recall_ge_19_20"] and c["gate_question_pass_ge_19_20"]
        and c["gate_evidence_pass_ge_19_20"] for c in classes_rows)

    qp_counts = report.overall.question_pass_counts
    ep_counts = report.overall.evidence_pass_counts
    crit_pos = [q for q in positives if q.critical]
    crit_ep_fail = [qs.query_id for qs in report.questions
                    if qs.critical and qs.evidence_pass is False]

    per_question = []
    for qs in report.questions:
        per_question.append({
            "query_id": qs.query_id,
            "domain": qs.domain,
            "critical": qs.critical,
            "negative": qs.answer_existence is AnswerExistence.NO_ANSWER,
            "question_pass": qs.question_pass,
            "evidence_pass": qs.evidence_pass,
            "doc_recall": None if qs.doc_recall is None else str(qs.doc_recall),
            "failures": list(qs.failures),
        })

    # 4) 不回退对照：b5 基线（冻结前收口）逐类比较
    b5_classes = {c["domain"]: c for c in b5["m6_evidence"]["per_class"]}
    baseline_regressions = []
    for c in report.classes:
        base = b5_classes.get(c.domain)
        if base is None:
            baseline_regressions.append({"domain": c.domain, "reason": "b5 基线缺该类"})
            continue
        for name, cur, old in (
            ("doc_recall", c.doc_recall.rate, Fraction(base["doc_recall"])),
            ("question_pass", c.question_pass.rate, Fraction(base["question_pass"])),
            ("evidence_pass", c.evidence_pass.rate, Fraction(base["evidence_pass"])),
        ):
            if cur is None or cur < old:
                baseline_regressions.append({"domain": c.domain, "metric": name,
                                             "current": str(cur), "b5": str(old)})
    b5_crit = b5["m6_evidence"].get("critical_all_pass")
    if b5_crit and crit_ep_fail:
        baseline_regressions.append({"domain": "*", "metric": "critical_all_pass",
                                     "current": False, "b5": b5_crit})

    # 5) 排序开关对照：on 不得劣于 off（on 劣化 = 回退；on 改善 = 记录在案）
    pass_on = {qs.query_id: qs.question_pass for qs in report.questions}
    pass_off = {qs.query_id: qs.question_pass for qs in report_off.questions}
    prune_regressions = sorted(qid for qid, on in pass_on.items()
                               if on is False and pass_off.get(qid))
    prune_improvements = sorted(qid for qid, on in pass_on.items()
                                if on and pass_off.get(qid) is False)

    # 6) 产品层负例：abstain=on 以产品形态（raw 题干，b2/I-M6-1 同款）复验 6 负例拒检；
    #    正例表现仅作诊断记录（I-M6-1 冻结口径不设正例门；发现登记 pending）
    saved_abstain = os.environ.get("CORPUS_ABSTAIN_NO_ANSWER")
    os.environ["CORPUS_ABSTAIN_NO_ANSWER"] = "on"
    try:
        neg_rows: list[dict] = []
        pos_rows: list[dict] = []
        for q in questions:
            hits, cov = svc.search_with_coverage(q.question, limit=10)
            row = {"query_id": q.query_id, "n_hits": len(hits),
                   "abstain": bool(cov.get("abstain")),
                   "query_status": cov.get("query_status")}
            (neg_rows if q.answer_existence is AnswerExistence.NO_ANSWER
             else pos_rows).append(row)
    finally:
        if saved_abstain is None:
            os.environ.pop("CORPUS_ABSTAIN_NO_ANSWER", None)
        else:
            os.environ["CORPUS_ABSTAIN_NO_ANSWER"] = saved_abstain
    abstain_neg_ok = len(neg_rows) == 6 and all(
        r["n_hits"] == 0 and r["abstain"] for r in neg_rows)
    pos_rejected = [r["query_id"] for r in pos_rows if r["n_hits"] == 0 or r["abstain"]]

    abstain_pos_diagnostic: dict = {}
    if pos_rejected:
        from plugins.corpus.preparation.negative_query import (  # noqa: PLC0415
            abstain_content_lexemes,
            abstain_no_answer_query,
        )
        from plugins.corpus.preparation.search_pg import query_lexemes  # noqa: PLC0415

        rep = next(q for q in positives if q.query_id in set(pos_rejected))
        lex = query_lexemes(sandbox_dsn, rep.question, sandbox_db=SANDBOX_DB)
        content = abstain_content_lexemes(lex)
        pre = search_chunks(sandbox_dsn, abstain_no_answer_query(content),
                            limit=_ABSTAIN_PRE_CHECK_LIMIT, sandbox_db=SANDBOX_DB)
        abstain_pos_diagnostic = {
            "representative": rep.query_id,
            "n_content_lexemes": len(content),
            "and_precheck_hits": len(pre),
            "finding": "abstain=on 下 24/24 正例被拒检：AND 预检要求单个单元同时含全部"
                       "实质词元，真实语料归零（band 检索靠 OR+带聚合仍可命中）。"
                       "b2/I-M6-1 冻结口径只断言负例 6/6（达成）；『正例不误拒』（S1）"
                       "设计宣称未获正例证据——非 I3-7 门，登记 pending 待 U 裁决，"
                       "不擅改冻结代码。",
        }

    # 7) 取证 round-trip：评分漏斗命中的带句柄逐字取回 + 未知句柄拒绝
    probe_doc = next(d for q in positives for d in prod_docs[q.query_id])
    probe_item = probe_doc.chunks_by_band[0][0]
    authority: dict = {
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
        authority_ok = (
            rt["build_id_match"] and rt["chunk_id_match"] and rt["n_units"] > 0
            and rt["text_nonempty"] and authority["unknown_handle_rejected"])
    except read_pg.ReadError as exc:  # 取证链路异常本身即失败
        authority["roundtrip_error"] = f"{type(exc).__name__}: {exc}"

    # 8) 汇总门
    gates = {
        "rebuild_all_new_build_active": bool(rebuild_summary["all_new_build_active"]),
        "frozen_policy_match": frozen_policy_ok,
        "frozen_revs_match": rebuild_revs_ok,
        "sources_active_match_rebuild": sources_active_ok,
        "read_chain_new": read_chain == "new",
        "all_class_gates_ge_19_20": all_class_gates,
        "critical_all_pass": not crit_ep_fail,
        "no_false_positives": not report.false_positives,
        "no_fabricated_citations": not report.fabricated_citations,
        "score_report_passed": report.passed,
        "baseline_non_regression": not baseline_regressions,
        "prune_on_not_worse_than_off": not prune_regressions,
        "abstain_negatives_6_of_6": abstain_neg_ok,
        "authority_roundtrip_ok": authority_ok,
    }
    passed = all(gates.values())

    summary = {
        "artifact": "i37-final-reverify-score",
        "generated_at": datetime.now(UTC).astimezone().isoformat(timespec="seconds"),
        "corpus": "i2_sandbox_corpus active publications（I3-7 重建步产物）",
        "frozen_version": {
            "final_manifest": rel(FINAL_MANIFEST),
            "final_manifest_sha256": digest(FINAL_MANIFEST),
            "chain_head_declared": "i0c-r4z",
            "chain_binding_revision": "i0c-r5a",
        },
        "inputs": {
            "scoring_manifest": rel(BASE / "i3-2/scoring-input-manifest.json"),
            "rebuild_report": rel(REBUILD_REPORT),
            "rebuild_report_sha256": digest(REBUILD_REPORT),
            "b5_baseline": rel(B5_INVENTORY),
            "b5_baseline_sha256": digest(B5_INVENTORY),
            "guard": rel(GUARD),
            "guard_sha256": digest(GUARD),
        },
        "frozen_policy": {
            "min_rate": str(policy.min_rate),
            "top_k": policy.top_k,
            "require_critical_all_pass": policy.require_critical_all_pass,
            "max_false_positives": policy.max_false_positives,
            "max_fabricated_citations": policy.max_fabricated_citations,
        },
        "policy_matches_freeze": frozen_policy_ok,
        "rebuild": {
            "published": rebuild_summary["published"],
            "active": rebuild_summary["active"],
            "sources_in_db": len(sources),
            "code_revs_match_freeze": code_revs_match,
            "db_revs_recomputed_match": db_revs_ok,
            "revs_match_freeze": rebuild_revs_ok,
        },
        "read_chain": read_chain,
        "scoring": {
            "question_pass_counts": f"{qp_counts[0]}/{qp_counts[1]}",
            "evidence_pass_counts": f"{ep_counts[0]}/{ep_counts[1]}",
            "per_class": classes_rows,
            "critical_total_positives": len(crit_pos),
            "critical_evidence_pass_fails": crit_ep_fail,
            "critical_failures_blockers": list(report.critical_failures),
            "false_positives": list(report.false_positives),
            "fabricated_citations": list(report.fabricated_citations),
            "blockers": list(report.blockers),
            "report_passed": report.passed,
        },
        "per_question": per_question,
        "rank_lexeme_prune_comparison": {
            "mode": "冻结默认 on（产品）vs off（锚定对照）；on 劣化 = 回退门",
            "improvements_on_better_than_off": prune_improvements,
            "regressions_on_worse_than_off": prune_regressions,
        },
        "baseline_comparison": {
            "b5_inventory": rel(B5_INVENTORY),
            "regressions": baseline_regressions,
            "non_regression": not baseline_regressions,
        },
        "negatives": {
            "product_abstain_on": {
                "mode": "CORPUS_ABSTAIN_NO_ANSWER=on，产品形态 raw 题干（b2/I-M6-1 同款）",
                "negatives": neg_rows,
                "negatives_rejected_6_of_6": abstain_neg_ok,
                "positives_diagnostic": {
                    "n_positives_rejected": len(pos_rejected),
                    "rejected_query_ids": pos_rejected,
                    "representative_attribution": abstain_pos_diagnostic,
                    "gate": "非 I3-7 门（冻结口径只断言负例 6/6）；发现登记 pending 待 U 裁决",
                },
            },
            "scoring_layer_false_positives": list(report.false_positives),
        },
        "authority": authority,
        "gates": gates,
        "passed": passed,
        "discipline": {
            "model_calls": 0,
            "pg": "只读（corpus schema 零写入）；沙箱 127.0.0.1:543/i2_sandbox_corpus；"
                  "生产库 5432 零触碰；_check_target fail-closed",
            "guard": "guards/i3-e2e.json 装载（零模型/网络仅 543/forbidden_roots 留出零读取）",
            "dsn": f"postgresql://***@127.0.0.1:543/{SANDBOX_DB}",
            "write_once": "i37-score-results.json（语义逐字段比较、剔 generated_at）",
        },
        "out_of_scope_pending": {
            "abstain_positives_finding": "abstain=on 下 24/24 正例被拒检（AND 预检单单元全实质"
                                         "词元在真实语料归零；S1『正例不误拒』未获证）——"
                                         "非 I3-7 门，pending 待 U 裁决",
            "legacy_nonregression": "旧检索/财务/公式/客户表等旧基线复验另列（i37_legacy.py）",
            "e2e_gates": "fullchain 12 项 + gap dispositions + 守卫 env 测试电池另列（b3）",
            "M6_signoff": "M6 放行只能由独立复核 + U 具名签认给出（plan 纪律），不以本脚本放行",
        },
    }

    write_once("i37-score-results.json", summary,
               dry_run="--no-write" in sys.argv)

    print(json.dumps({
        "question_pass": summary["scoring"]["question_pass_counts"],
        "evidence_pass": summary["scoring"]["evidence_pass_counts"],
        "per_class": [(c["domain"], c["evidence_pass"], c["doc_recall"],
                       c["gate_evidence_pass_ge_19_20"]) for c in classes_rows],
        "critical_fails": crit_ep_fail,
        "false_positives": list(report.false_positives),
        "fabricated_citations": list(report.fabricated_citations),
        "baseline_regressions": baseline_regressions,
        "prune_regressions": prune_regressions,
        "prune_improvements": prune_improvements,
        "abstain_neg_6_of_6": abstain_neg_ok,
        "abstain_pos_rejected": len(pos_rejected),
        "authority_ok": authority_ok,
        "gates": gates,
        "passed": passed,
    }, ensure_ascii=False, indent=2))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
