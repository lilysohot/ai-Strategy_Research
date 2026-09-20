"""I3-3 全链路回测：reader-pdf-5 重摄入 active corpus × 当前工作树 scorer。

诊断性质（非冻结回归）：
- 评分输入 manifest / query-gold / projection / source-gold 等**冻结资产**逐字节核验；
- scorer 用**工作树现字节**（当前为空白规约版 f61573d7，未冻结、未采纳）——本回测
  只回答「当前代码在全链路上把卡点留在哪一层」，不宣称通过、不改金标/评分器/检索。
- 对每条 gold 证据目标做逐层定位：
    matched                        —— 评分命中
    selected_but_match_fail        —— 引文在选中证据里但匹配失败（locator/verified 等）
    kept_page_not_selected         —— 引文在 kept 声明页内但未进 top-k 选中块（检索/切块丢失）
    kept_elsewhere_page_mismatch   —— 引文在 kept 但不在声明页（跨页/定位差异）
    doc_not_kept_clean_stage_loss  —— 引文只在非 kept 单元（清洗剔除/NOISE）
    not_in_doc_unreachable         —— 全文任意处不逐字出现（金标改写/重建，检索层不可达）
- 负例（no-answer）逐条列出检索命中的文档与证据预览，定位 OR 过宽的误报来源。
- 只读 PG + 0 model_calls；产物 write-once 写入本目录。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import os
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
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

import calibrate  # noqa: E402  reuse group_hits / observations_for

SANDBOX = "i2_sandbox_corpus"
VARIANT = "candidate_question_lexemes_or"


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


def main() -> int:
    # ── 1. 冻结资产核验：除工作树 scorer 外，其余绑定与 r39 计划一致（与 rerun_or 同口径）──
    plan = json.loads((I33 / "calibration-plan-v2.json").read_text())
    for rel, sha in plan["binding"].items():
        if rel == "plugins/corpus/scoring.py":
            continue  # 工作树 scorer 是本回测的观察对象，不参与冻结比对
        if digest(ROOT / rel) != sha:
            raise RuntimeError(f"Frozen asset drift vs r39 (except scorer): {rel}")
    release = load_module("i31_region_release", BASE / "audits/20260920-i31-region-review/release.py")
    dsn = release.connect()

    loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")
    applier = loader.load_module(BASE / "i3s2_apply_decisions.py", "i33_approved_input")
    scorer_sha = digest(ROOT / "plugins/corpus/scoring.py")
    # manifest 血缘记录的 scorer 是冻结严格版（bf9c8b80）；工作树为空白规约版（f61573d7）。
    # validate() 对 scorer 血缘 fail-closed 拒绝——这正是当前卡点之一。本诊断在**内存**中把
    # lineage.scorer.sha256 补丁为工作树现哈希（磁盘冻结 manifest 不动），以测工作树 scorer 语义。
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
    write_once("binding.json", {
        "kind": "diagnostic (NOT a frozen regression)",
        "scorer_working_tree_sha256": scorer_sha,
        "frozen_assets_ok": True,
        "manifest_lineage_scorer": "patched in-memory to working-tree hash (disk manifest untouched)",
        "note": "scorer 为工作树空白规约版（f61573d7），未冻结未采纳；本回测仅定位卡点",
        "checked_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    })

    from plugins.corpus.scoring import (gold_from_records, ScoringPolicy, score, format_report,
                                        AnswerExistence)
    from plugins.corpus.preparation.search_pg import search_chunks, _check_target
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.read_pg import (fetch_verbatim, build_handle, chunk_locator,
                                                    fetch_document)
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
        write_once("source-identity-map.json", {"aliases": aliases, "active_builds": sources})
        alias_to_source = {alias: src for src, alias in aliases.items()}

        # kept 单元按 build → page 缓存（与 i35 取证同口径：仅 UnitStatus.KEPT）
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
            doc_text[build_id] = fetch_document(dsn, build_handle(build_id)).text

        cache: dict = {}
        receipts = {}

        def fetch(hit):
            key = (hit.build_id, hit.chunk_id)
            if key not in cache:
                cache[key] = fetch_verbatim(dsn, build_handle(hit.build_id), chunk_locator(hit.chunk_id))
                receipts["/".join(key)] = asdict(cache[key])
            return cache[key]

        traces = []
        observations = []
        for question in questions:
            query = question.question
            lexemes = conn.execute("SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                                   (normalize_search_text(query),)).fetchone()[0]
            if not lexemes:
                raise RuntimeError("Question tokenization produced no terms")
            query = " OR ".join('"' + term.replace('"', ' ') + '"' for term in lexemes)
            tsquery = conn.execute("SELECT websearch_to_tsquery('zhcfg', %s)::text",
                                   (normalize_search_text(query),)).fetchone()[0]
            hits = search_chunks(dsn, query, limit=2000)
            if len(hits) >= 2000:
                raise RuntimeError("Candidate cap saturated; cannot certify document top-k")
            grouped = calibrate.group_hits(hits, policy.top_k, 8)
            observation = calibrate.observations_for(question.query_id, grouped, fetch, aliases)
            observations.append(observation)
            traces.append({"query_id": question.query_id, "input_question": question.question,
                           "executed_query": query, "native_tsquery": tsquery, "chunk_hits": len(hits),
                           "selected": {s: [asdict(h) for h in hlist] for s, hlist in grouped.items()}})
            if snapshot() != sources:
                raise RuntimeError("Active publication changed during re-run")

        if snapshot() != sources:
            raise RuntimeError("Active publication changed during re-run")

        report = score(questions, observations, policy)

        # ── 3. 逐目标分层定位 ──
        ob_map = {o.query_id: o for o in observations}
        diagnostics = []
        for q in questions:
            obs = ob_map.get(q.query_id)
            relevant = set(q.relevant_sources)
            for target in q.evidence_targets:
                allowed = (target.source_id,) if target.source_id else tuple(relevant)
                row = {"query_id": q.query_id, "target_id": target.target_id,
                       "domain": q.domain, "quote": target.quote, "locator": list(target.locator),
                       "source_id": target.source_id}
                # 声明页
                page = None
                for tok in target.locator:
                    if tok.startswith("page:"):
                        page = int(tok.split(":", 1)[1])
                        break
                if obs is None:
                    row["bucket"] = "no_observation"
                    diagnostics.append(row)
                    continue
                # 与 score() 同口径的匹配
                matched = any(
                    target.matches(ev) and doc.source_id in allowed
                    for doc in obs.documents for ev in doc.evidence)
                row["matched"] = matched
                if matched:
                    row["bucket"] = "matched"
                    diagnostics.append(row)
                    continue
                # 引文在选中证据全文（含全部 top-k 文档、无关来源也算作证据文本在链上）
                selected_text = "\n".join(
                    ev.text for doc in obs.documents for ev in doc.evidence)
                in_selected = norm(target.quote) in norm(selected_text)
                src = target.source_id or (next(iter(relevant), None))
                live_src = alias_to_source.get(src)
                build_id = sources.get(live_src) if live_src else None
                in_kept_page = False
                in_kept_any = False
                in_doc = False
                if build_id:
                    if page is not None:
                        in_kept_page = norm(target.quote) in norm(kept_pages.get(build_id, {}).get(page, ""))
                    in_kept_any = any(norm(target.quote) in norm(t)
                                      for t in kept_pages.get(build_id, {}).values())
                    in_doc = norm(target.quote) in norm(doc_text.get(build_id, ""))
                row.update({
                    "in_selected_evidence": in_selected,
                    "in_kept_declared_page": in_kept_page,
                    "in_kept_anywhere": in_kept_any,
                    "in_doc_full": in_doc,
                })
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

        # ── 4. 负例（no-answer）检索定位 ──
        neg = []
        for q, o in zip(questions, observations):
            if q.answer_existence is AnswerExistence.NO_ANSWER:
                docs = [{"source_id": d.source_id, "build_id": d.build_id,
                         "evidence_preview": [ev.text[:140] for ev in d.evidence][:4]}
                        for d in o.documents] if o else []
                neg.append({"query_id": q.query_id, "answer_existence": q.answer_existence.name,
                            "question": q.question, "retrieved_documents": len(docs), "docs": docs})
        if neg:
            write_once("negative-cases.json", {"note": "no-answer questions' retrieved evidence (OR-too-broad localization)",
                                               "cases": neg})

        write_once("candidate_question_lexemes_or-observations.json", [asdict(o) for o in observations])
        write_once("candidate_question_lexemes_or-trace.json", traces)
        write_once("candidate_question_lexemes_or-score.json", asdict(report))
        (HERE / "candidate_question_lexemes_or-score.md").write_text(format_report(report) + "\n")
        write_once("fetch-receipts.json", receipts)
        write_once("diagnostics.json", diagnostics)

        buckets = Counter(d["bucket"] for d in diagnostics)
        summary = {
            "artifact": "i3-7-fullchain-backtest",
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "kind": "diagnostic", "corpus": "reader-pdf-5 reingest active (8 builds)",
            "scorer": "working-tree whitespace-norm (NOT frozen)",
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
            "target_buckets": dict(buckets),
            "failures": dict(Counter(f.split(":")[0] for q in report.questions for f in q.failures)),
            "model_calls": 0,
            "questions": len(questions),
        }
        write_once("backtest-summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        # ── 5. MD 报告 ──
        lines = [
            "# I3-7 全链路回测（reader-pdf-5 × 工作树 scorer，诊断性质）",
            "",
            f"- 生成：{summary['generated_at']}；类型：诊断（**非冻结回归**）",
            f"- scorer：工作树空白规约版 `{scorer_sha[:12]}`（未冻结未采纳）；评分资产冻结字节已核验",
            f"- corpus：8 份 active builds（reader-pdf-5 重摄入，含 4 份人工 gap-review 重签）",
            f"- 结论：passed={report.passed}；EvidencePass {summary['evidence_pass_total']}；"
            f"负例误报 {report.false_positives}、伪造引用 {report.fabricated_citations}",
            "",
            "## 三类指标",
            "",
            "| 类 | DocRecall | QuestionPass | EvidencePass |",
            "|---|---|---|---|",
        ]
        for c in summary["per_class"]:
            lines.append(f"| {c['domain']} | {c['doc_recall']} | {c['question_pass']} | {c['evidence_pass']} |")
        lines += [
            "",
            "## 逐目标分层定位（evidence targets 全部）",
            "",
            "| 桶 | 数量 | 含义 |",
            "|---|---|---|",
            "| matched | " + str(buckets.get("matched", 0)) + " | 评分命中 |",
            "| selected_but_match_fail | " + str(buckets.get("selected_but_match_fail", 0)) + " | 引文在选中证据里但匹配失败（locator/verified） |",
            "| kept_page_not_selected | " + str(buckets.get("kept_page_not_selected", 0)) + " | 引文在 kept 声明页内但未进 top-k 选中块（检索/切块丢失） |",
            "| kept_elsewhere_page_mismatch | " + str(buckets.get("kept_elsewhere_page_mismatch", 0)) + " | 引文在 kept 但不在声明页（跨页/定位差异） |",
            "| doc_not_kept_clean_stage_loss | " + str(buckets.get("doc_not_kept_clean_stage_loss", 0)) + " | 引文只在非 kept 单元（清洗剔除/NOISE） |",
            "| not_in_doc_unreachable | " + str(buckets.get("not_in_doc_unreachable", 0)) + " | 全文任意处不逐字出现（金标改写/重建，检索层不可达） |",
            "| no_observation | " + str(buckets.get("no_observation", 0)) + " | 无观测 |",
            "",
            "## 负例误报定位",
            "",
            "| 题 | 检索命中文档数 | 命中证据预览 |",
            "|---|---|---|",
        ]
        for case in neg:
            preview = " / ".join(e for d in case["docs"][:2] for e in d["evidence_preview"][:1])
            lines.append(f"| {case['query_id']} | {case['retrieved_documents']} | {preview} |")
        (HERE / "backtest-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
