"""只读反事实：把"证据单位"从「每文档 top-8 块」换成「该文档全部 kept 页」。

- 法律性：**不使用任何金标事实**。仍然只用问题词元做 OR 检索、同样 top-5 文档归并；
  只是在已召回的文档内，把证据粒度从块改为页（页级文本来自权威 kept 单元）。
- 目的：证明 (1) 页级证据能覆盖多少； (2) 剩余卡点是"文本"还是"locator"；
  (3) 负例（无答案题）是否被放大。
- 不写库、不改任何冻结资产；仅在本目录产出诊断 JSON。

对照基线（i37，块级证据）：EvidencePass 13/24，kept_page_not_selected 21。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from dataclasses import asdict
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
I33 = BASE / "audits/20260920-i33-calibration"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

import calibrate  # noqa: E402


def load_module(name: str, path: Path):  # noqa: ANN201
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def norm(s: object) -> str:
    return "".join(ch for ch in s if not ch.isspace()) if isinstance(s, str) else ""


def main() -> None:
    release = load_module("i31_region_release", BASE / "audits/20260920-i31-region-review/release.py")
    dsn = release.connect()
    loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")
    plan = json.loads((I33 / "calibration-plan-v2.json").read_text())

    from plugins.corpus.preparation.chunk import normalize_search_text  # noqa: PLC0415
    from plugins.corpus.preparation.contract import UnitStatus  # noqa: PLC0415
    from plugins.corpus.preparation.repository_pg import PgStore  # noqa: PLC0415
    from plugins.corpus.preparation.search_pg import search_chunks  # noqa: PLC0415
    from plugins.corpus.scoring import (  # noqa: PLC0415
        AnswerExistence,
        FetchedEvidence,
        QueryObservation,
        RetrievedDocument,
        ScoringPolicy,
        format_report,
        gold_from_records,
        score,
    )
    import psycopg  # noqa: PLC0415

    questions = gold_from_records(records)
    ident = json.loads((HERE / "source-identity-map.json").read_text())
    active_builds = {sha: bid for sha, bid in ident["active_builds"].items()}
    alias_of = {sha: alias for sha, alias in ident["aliases"].items()}

    policy_config = dict(plan["policy"])
    policy_config["min_rate"] = Fraction(policy_config["min_rate"])
    policy = ScoringPolicy(**policy_config)

    # 每份 active build 的 kept 页文本（权威 kept 单元，与诊断同口径）
    page_text: dict[str, dict[int, str]] = {}
    with PgStore(dsn) as store:
        for sha, build_id in active_builds.items():
            pages: dict[int, list[str]] = {}
            for unit in store.get_units(build_id):
                if unit.status is UnitStatus.KEPT and unit.location.page is not None:
                    pages.setdefault(unit.location.page, []).append(unit.raw_text)
            page_text[build_id] = {pg: "\n".join(ls) for pg, ls in pages.items()}

    observations = []
    traces = []
    with psycopg.connect(dsn, autocommit=True) as conn:
        for question in questions:
            lexemes = conn.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(question.question),),
            ).fetchone()[0]
            query = " OR ".join('"' + term.replace('"', " ") + '"' for term in lexemes)
            hits = search_chunks(dsn, query, limit=plan["max_chunk_candidates"])
            grouped = calibrate.group_hits(hits, policy.top_k, plan["max_chunks_per_top_document"])
            documents = []
            for source_id, chunk_hits in grouped.items():
                build_id = chunk_hits[0].build_id
                pages = page_text.get(build_id, {})
                evidences = tuple(
                    FetchedEvidence(pages[pg], locator=(f"page:{pg}",), verified=True)
                    for pg in sorted(pages)
                )
                documents.append(
                    RetrievedDocument(alias_of.get(source_id, source_id), evidences, build_id)
                )
            observations.append(
                QueryObservation(question.query_id, documents=tuple(documents))
            )
            traces.append({
                "query_id": question.query_id,
                "chunk_hits": len(hits),
                "documents": [d.source_id for d in documents],
                "pages": {d.source_id: len(d.evidence) for d in documents},
            })

    report = score(questions, observations, policy)
    print(format_report(report))

    # 逐目标：页级证据下，究竟卡在"文本"还是"locator"
    obs_map = {o.query_id: o for o in observations}
    rows = []
    for question in questions:
        observation = obs_map[question.query_id]
        relevant = set(question.relevant_sources)
        for target in question.evidence_targets:
            allowed = (target.source_id,) if target.source_id else tuple(relevant)
            matched = any(
                target.matches(ev) and doc.source_id in allowed
                for doc in observation.documents
                for ev in doc.evidence
            )
            text_hit = False
            locator_ok = False
            for doc in observation.documents:
                if doc.source_id not in allowed:
                    continue
                for ev in doc.evidence:
                    if norm(target.quote) in norm(ev.text):
                        text_hit = True
                        if all(token in ev.locator for token in target.locator):
                            locator_ok = True
            rows.append({
                "query_id": question.query_id,
                "target_id": target.target_id,
                "domain": question.domain,
                "matched": matched,
                "text_in_page": text_hit,
                "locator_satisfied": locator_ok,
                "locator": list(target.locator),
                "quote_len": len(norm(target.quote)),
                "verdict": (
                    "matched"
                    if matched
                    else ("text present but locator missing" if text_hit else "text absent in pages")
                ),
            })

    old = {(r["query_id"], r["target_id"]): r for r in json.loads((HERE / "diagnostics.json").read_text())}
    was21 = {k for k, v in old.items() if v["bucket"] == "kept_page_not_selected"}
    print("=" * 92)
    print("原 21 条 kept_page_not_selected 在页级证据下的判读：")
    fixed = [f"{r['query_id']} {r['target_id']}" for r in rows
             if (r["query_id"], r["target_id"]) in was21 and r["matched"]]
    locator_only = [f"{r['query_id']} {r['target_id']}" for r in rows
                    if (r["query_id"], r["target_id"]) in was21 and not r["matched"]
                    and r["verdict"] == "text present but locator missing"]
    still_absent = [f"{r['query_id']} {r['target_id']}" for r in rows
                    if (r["query_id"], r["target_id"]) in was21 and not r["matched"]
                    and r["verdict"] == "text absent in pages"]
    print(f"  转 matched            : {len(fixed)}  {fixed}")
    print(f"  文本在、只缺 locator  : {len(locator_only)}  {locator_only}")
    print(f"  页文本里也没有        : {len(still_absent)}  {still_absent}")

    negatives = [
        {"query_id": q.query_id, "docs": len(obs_map[q.query_id].documents)}
        for q in questions
        if q.answer_existence is AnswerExistence.NO_ANSWER
    ]
    print(f"负例（无答案题）检索命中文档数：{[n['docs'] for n in negatives]}（块级证据时同为命中，未放大）")

    (HERE / "page-level-evidence-probe.json").write_text(
        json.dumps({
            "kind": "diagnostic counterfactual (NOT a frozen metric)",
            "change": "evidence unit: per-document top-8 chunks -> all kept pages of retrieved docs",
            "legality": "no gold facts used; same OR question-lexeme query; same top-5 document grouping",
            "classes": [asdict(c) for c in report.classes],
            "passed": report.passed,
            "blockers": list(report.blockers),
            "questions": [asdict(q) for q in report.questions],
            "targets": rows,
            "was_kept_page_not_selected": sorted(f"{a} {b}" for a, b in was21),
            "fixed": fixed,
            "locator_only": locator_only,
            "still_absent": still_absent,
            "traces": traces,
        }, ensure_ascii=False, indent=2, default=str) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
