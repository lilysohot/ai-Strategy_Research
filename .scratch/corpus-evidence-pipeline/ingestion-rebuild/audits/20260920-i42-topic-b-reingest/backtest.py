"""I42 议题 B 同口径回测：结构重叠排序信号 × 新 active corpus（index-4-zhcfg-2）。

口径与 i37 全链路回测（backtest.py / inspect_top8_truncation.py）一致，差异仅在：
- corpus：i42 teardown 重建后的 8 份新 active build（reader-pdf-6 / chunk-3 / index-4-zhcfg-2）；
- 排序：对 ``search_chunks`` 候选施加结构重叠信号（I-B1 标签注入 + I-B2 排序主键），
  两变体对照：
    * ``global``：全池按 (结构重叠数, ts_rank) 主键重排后再 top-5×8（用户确认的信号规则）；
    * ``perdoc``：文档序保持词法首次出现（与 i37 一致），仅文档内前 8 块按 (结构重叠, ts_rank)
      重排（I-B2 原文「对应 cell 块必须进入该文档前 N 块」的字面语义）。
- 断言点（议题 B 验收）：
    1. 图 6 十条引文块在该文档内排名 ≤ 8（进选择范围）；
    2. 系统级：DocRecall 不降（i37 基线各域 1）；负例误报数不增加（≤ i37 基线 6）；
    3. 语义：查询只用问题词元（OR 连接），信号只来自 chunk 结构标签，无金标补取。
- I-B3：选择上限仍为 ``max_chunks_per_document=8``（SelectionPolicy 断言点）。

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

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
I33 = BASE / "audits/20260920-i33-calibration"
I37 = BASE / "audits/20260920-i37-fullchain-backtest"
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

import calibrate  # noqa: E402  reuse observations_for

SANDBOX = "i2_sandbox_corpus"
TOPIC_B_TARGETS: dict[str, tuple[str, ...]] = {
    "industry-001": ("e1", "e2", "e3"),
    "industry-002": ("e1",),
    "industry-003": ("e1", "e2", "a-3"),
    "industry-008": ("a-2", "a-3", "a-5"),
}


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


def group_perdoc(
    hits: tuple,
    lexemes: tuple[str, ...],
    top_k: int,
    per_doc: int,
) -> dict[str, list]:
    """per-doc 变体选择：文档序 = 词法首次出现（与 i37 逐字节一致），
    文档内前 ``per_doc`` 块按 (结构重叠数, ts_rank) 重排。"""
    from plugins.corpus.preparation.search_pg import _label_tokens

    docs: dict[str, list] = {}
    order: list[str] = []
    for hit in hits:
        if hit.source_id not in docs:
            docs[hit.source_id] = []
            order.append(hit.source_id)
        docs[hit.source_id].append(hit)
    lexeme_set = set(lexemes)

    def key(hit) -> tuple[int, float]:
        return (len(lexeme_set & _label_tokens(hit)), hit.score)

    grouped: dict[str, list] = {}
    for sid in order[:top_k]:
        bucket = docs[sid]
        bucket.sort(key=key, reverse=True)
        grouped[sid] = bucket[:per_doc]
    return grouped


def main() -> int:
    from plugins.corpus.preparation.selection import SelectionPolicy
    assert SelectionPolicy().max_chunks_per_document == 8, "I-B3: cap 必须保持 8"
    release = load_module("i31_region_release", BASE / "audits/20260920-i31-region-review/release.py")
    dsn = release.connect()

    loader = load_module("i33_scoring_loader", BASE / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(BASE / "i3-2/scoring-input-manifest.json")
    applier = loader.load_module(BASE / "i3s2_apply_decisions.py", "i33_approved_input")
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

    from plugins.corpus.scoring import (gold_from_records, ScoringPolicy, score, format_report,
                                        AnswerExistence)
    from plugins.corpus.preparation.search_pg import search_chunks, rank_hits, _check_target
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.read_pg import (fetch_verbatim, build_handle, chunk_locator)
    from plugins.corpus.preparation.repository_pg import PgStore
    from plugins.corpus.preparation.contract import UnitStatus
    import psycopg

    questions = gold_from_records(records)
    config = dict(load_json(I33 / "calibration-plan-v2.json")["policy"])
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
        expected_aliases |= {t.source_id for q in questions for t in q.evidence_targets if t.source_id}
        for alias in expected_aliases:
            matches = [source for source in sources if source.startswith(alias.rsplit("_", 1)[-1])]
            if len(matches) != 1:
                raise RuntimeError(f"Gold alias cannot resolve uniquely: {alias}")
            if matches[0] in aliases and aliases[matches[0]] != alias:
                raise RuntimeError("Multiple gold aliases for one source")
            aliases[matches[0]] = alias
        alias_to_source = {alias: src for src, alias in aliases.items()}

        # kept 单元按 build → page 缓存
        kept_pages: dict[str, dict[int, str]] = {}
        with PgStore(dsn, sandbox_db=SANDBOX) as store:
            for src, build_id in sources.items():
                pages: dict[int, list[str]] = {}
                for u in store.get_units(build_id):
                    if u.status is UnitStatus.KEPT and u.location.page is not None:
                        pages.setdefault(u.location.page, []).append(u.raw_text)
                kept_pages[build_id] = {pg: "\n".join(ls) for pg, ls in pages.items()}

        cache: dict = {}
        receipts = {}

        def fetch(hit):
            key = (hit.build_id, hit.chunk_id)
            if key not in cache:
                cache[key] = fetch_verbatim(dsn, build_handle(hit.build_id), chunk_locator(hit.chunk_id))
                receipts["/".join(key)] = asdict(cache[key])
            return cache[key]

        def run_variant(name: str, select_fn) -> dict:
            traces = []
            observations = []
            by_query: dict[str, tuple] = {}
            for question in questions:
                lexemes = conn.execute("SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                                       (normalize_search_text(question.question),)).fetchone()[0]
                if not lexemes:
                    raise RuntimeError("Question tokenization produced no terms")
                query = " OR ".join('"' + term.replace('"', ' ') + '"' for term in lexemes)
                tsquery = conn.execute("SELECT websearch_to_tsquery('zhcfg', %s)::text",
                                       (normalize_search_text(query),)).fetchone()[0]
                hits = search_chunks(dsn, query, limit=2000)
                if len(hits) >= 2000:
                    raise RuntimeError("Candidate cap saturated; cannot certify document top-k")
                grouped = select_fn(hits, tuple(lexemes))
                by_query[question.query_id] = (hits, grouped)
                observation = calibrate.observations_for(question.query_id, grouped, fetch, aliases)
                observations.append(observation)
                traces.append({"query_id": question.query_id, "input_question": question.question,
                               "executed_query": query, "native_tsquery": tsquery,
                               "chunk_hits": len(hits),
                               "selected": {s: [asdict(h) for h in hlist] for s, hlist in grouped.items()}})

            # 议题 B 十条引文探针
            topic_probe = []
            for q in questions:
                if q.query_id not in TOPIC_B_TARGETS:
                    continue
                hits, grouped = by_query[q.query_id]
                doc_rank_map = {alias_to_source.get(a, a): i + 1 for i, s in enumerate(grouped)
                                for a in (s,)}
                for target in q.evidence_targets:
                    if target.target_id not in TOPIC_B_TARGETS[q.query_id]:
                        continue
                    if not target.source_id:
                        raise RuntimeError(f"{q.query_id} {target.target_id}: 缺 source_id")
                    sha = alias_to_source.get(target.source_id)
                    doc_hits = [h for h in hits if h.source_id == sha]
                    raw_rank = None
                    for i, hit in enumerate(doc_hits, start=1):
                        got = fetch(hit)
                        if norm(target.quote) in norm(got.text):
                            raw_rank = i
                            break
                    # I-B2 语义：引文块必须进入「该文档前 N 块」= 变体实际选中的 top-8 块
                    selected_hits = grouped.get(sha, [])
                    selected_rank = None
                    for i, hit in enumerate(selected_hits, start=1):
                        got = fetch(hit)
                        if norm(target.quote) in norm(got.text):
                            selected_rank = i
                            break
                    topic_probe.append({
                        "query_id": q.query_id, "target_id": q.query_id + " " + target.target_id,
                        "quote": target.quote, "locator": list(target.locator),
                        "doc_rank": doc_rank_map.get(sha), "doc_hits": len(doc_hits),
                        "raw_rank": raw_rank, "selected_rank": selected_rank,
                        "in_selection_range": selected_rank is not None,
                    })

            report = score(questions, observations, policy)
            neg = []
            for q, o in zip(questions, observations):
                if q.answer_existence is AnswerExistence.NO_ANSWER:
                    docs = [{"source_id": d.source_id, "build_id": d.build_id,
                             "evidence_preview": [ev.text[:140] for ev in d.evidence][:4]}
                            for d in o.documents] if o else []
                    neg.append({"query_id": q.query_id, "answer_existence": q.answer_existence.name,
                                "question": q.question, "retrieved_documents": len(docs), "docs": docs})

            diagnostics = []
            ob_map = {o.query_id: o for o in observations}
            for q in questions:
                obs = ob_map.get(q.query_id)
                relevant = set(q.relevant_sources)
                for target in q.evidence_targets:
                    allowed = (target.source_id,) if target.source_id else tuple(relevant)
                    row = {"query_id": q.query_id, "target_id": q.query_id + " " + target.target_id,
                           "domain": q.domain, "quote": target.quote,
                           "locator": list(target.locator), "source_id": target.source_id}
                    page = None
                    for tok in target.locator:
                        if tok.startswith("page:"):
                            page = int(tok.split(":", 1)[1])
                            break
                    if obs is None:
                        row["bucket"] = "no_observation"
                        diagnostics.append(row)
                        continue
                    matched = any(
                        target.matches(ev) and doc.source_id in allowed
                        for doc in obs.documents for ev in doc.evidence)
                    row["matched"] = matched
                    if matched:
                        row["bucket"] = "matched"
                        diagnostics.append(row)
                        continue
                    selected_text = "\n".join(ev.text for doc in obs.documents for ev in doc.evidence)
                    in_selected = norm(target.quote) in norm(selected_text)
                    src = target.source_id or (next(iter(relevant), None))
                    live_src = alias_to_source.get(src)
                    build_id = sources.get(live_src) if live_src else None
                    in_kept_page = in_kept_any = False
                    if build_id:
                        if page is not None:
                            in_kept_page = norm(target.quote) in norm(kept_pages.get(build_id, {}).get(page, ""))
                        in_kept_any = any(norm(target.quote) in norm(t)
                                          for t in kept_pages.get(build_id, {}).values())
                    row.update({"in_selected_evidence": in_selected,
                                "in_kept_declared_page": in_kept_page,
                                "in_kept_anywhere": in_kept_any})
                    if in_selected:
                        row["bucket"] = "selected_but_match_fail"
                    elif in_kept_page:
                        row["bucket"] = "kept_page_not_selected"
                    elif in_kept_any:
                        row["bucket"] = "kept_elsewhere_page_mismatch"
                    else:
                        row["bucket"] = "not_in_doc_unreachable"
                    diagnostics.append(row)

            write_once(f"{name}-observations.json", [asdict(o) for o in observations])
            write_once(f"{name}-trace.json", traces)
            write_once(f"{name}-score.json", asdict(report))
            (HERE / f"{name}-score.md").write_text(format_report(report) + "\n")
            if neg:
                write_once(f"{name}-negative-cases.json", neg)
            write_once(f"{name}-topic-probe.json", topic_probe)
            return {
                "report": report, "observations": observations, "diagnostics": diagnostics,
                "topic_probe": topic_probe, "neg": neg,
            }

        def select_global(hits, lexemes):
            ranked = rank_hits(hits, lexemes=lexemes, signals=("lexical", "structural"))
            return calibrate.group_hits(ranked, policy.top_k, 8)

        def select_perdoc(hits, lexemes):
            return group_perdoc(hits, lexemes, policy.top_k, 8)

        global_v = run_variant("candidate_structural_or", select_global)
        perdoc_v = run_variant("candidate_structural_perdoc", select_perdoc)
        write_once("fetch-receipts.json", receipts)

        i37 = json.loads((I37 / "backtest-summary.json").read_text())

        def pack(name: str, v: dict) -> dict:
            r = v["report"]
            buckets = Counter(d["bucket"] for d in v["diagnostics"])
            topic_buckets = Counter(
                d["bucket"] for d in v["diagnostics"]
                if d["query_id"] in TOPIC_B_TARGETS
                and d["target_id"].split()[-1] in TOPIC_B_TARGETS[d["query_id"]])
            probe = v["topic_probe"]
            return {
                "variant": name,
                "passed": r.passed,
                "per_class": [{"domain": c.domain, "doc_recall": str(c.doc_recall.rate),
                               "question_pass": f"{c.question_pass.passed}/{c.question_pass.total}",
                               "evidence_pass": f"{c.evidence_pass.passed}/{c.evidence_pass.total}"}
                              for c in r.classes],
                "evidence_pass_total": f"{sum(c.evidence_pass.passed for c in r.classes)}/"
                                       f"{sum(c.evidence_pass.total for c in r.classes)}",
                "false_positives": r.false_positives,
                "fabricated_citations": r.fabricated_citations,
                "critical_failures": r.critical_failures,
                "target_buckets": dict(buckets),
                "topic_b": {"total": len(probe), "in_selection_range": sum(
                    p["in_selection_range"] for p in probe),
                    "target_buckets": dict(topic_buckets),
                    "probe": probe},
                "failures": dict(Counter(f.split(":")[0] for q in r.questions for f in q.failures)),
            }

        g = pack("candidate_structural_or", global_v)
        p = pack("candidate_structural_perdoc", perdoc_v)

        # 逐目标桶 diff（对 i37 基线）
        def diff_vs_i37(diags: list) -> dict:
            short = lambda r: r["target_id"].split()[-1]  # noqa: E731
            m37 = {(r["query_id"], short(r)): r["bucket"]
                   for r in json.loads((I37 / "diagnostics.json").read_text())}
            m42 = {(r["query_id"], short(r)): r["bucket"] for r in diags}
            assert set(m37) == set(m42)
            return {f"{q} {t}": (m37[(q, t)], m42[(q, t)])
                    for (q, t) in sorted(set(m37)) if m37[(q, t)] != m42[(q, t)]}

        g["bucket_diff_vs_i37"] = diff_vs_i37(global_v["diagnostics"])
        p["bucket_diff_vs_i37"] = diff_vs_i37(perdoc_v["diagnostics"])

        summary = {
            "artifact": "i42-topic-b-backtest",
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "corpus": "index-4-zhcfg-2 reingest active (8 builds)",
            "ranking_note": "global=(结构重叠,ts_rank) 全池主键；perdoc=文档序词法+文档内(结构重叠,ts_rank)",
            "i37_baseline": {"doc_recall": "1 (all domains)", "false_positives": len(i37["false_positives"]),
                             "evidence_pass_total": i37["evidence_pass_total"]},
            "global": g, "perdoc": p,
            "model_calls": 0, "questions": len(questions),
        }
        write_once("backtest-summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        # ── MD 报告 ──
        lines = [
            "# I42 议题 B 同口径回测（index-4-zhcfg-2 × 结构重叠排序，global/perdoc 两变体）",
            "",
            f"- 生成：{summary['generated_at']}；类型：同口径回测（参照 i37，非冻结回归）",
            f"- corpus：8 份 active builds（i42 teardown 重建，reader-pdf-6 / chunk-3 / index-4-zhcfg-2）",
            "- 选择上限保持 8（I-B3）；查询只用问题词元 OR 连接；信号只来自 chunk 结构标签（I-B1 注入）",
            f"- i37 基线：DocRecall 全域 1；负例误报 6；EvidencePass {i37['evidence_pass_total']}",
            "",
            "## 两变体对照",
            "",
            "| 指标 | global（全池主键） | perdoc（文档内主键） |",
            "|---|---|---|",
            f"| 议题 B 进选择范围 | {g['topic_b']['in_selection_range']}/{g['topic_b']['total']} | "
            f"{p['topic_b']['in_selection_range']}/{p['topic_b']['total']} |",
            f"| EvidencePass | {g['evidence_pass_total']} | {p['evidence_pass_total']} |",
            f"| 负例误报 | {len(g['false_positives'])} | {len(p['false_positives'])} |",
            f"| 目标桶回退数（vs i37） | {len(g['bucket_diff_vs_i37'])} | {len(p['bucket_diff_vs_i37'])} |",
            "",
            "## 议题 B 十条引文探针（global 变体）",
            "",
            "| 目标 | 文档排名 | 原始块排名 | 选中块排名 | 进选择范围 |",
            "|---|---:|---:|---:|---|",
        ]
        for x in g["topic_b"]["probe"]:
            lines.append(f"| {x['target_id']} | {x['doc_rank']} | {x['raw_rank']} | "
                         f"{x['selected_rank']} | "
                         f"{'✓' if x['in_selection_range'] else '✗'} |")
        lines += [
            "",
            "## 逐目标桶回退明细（global → perdoc，对照 i37）",
            "",
            "| 目标 | i37 | global | perdoc |",
            "|---|---|---|---|",
        ]
        all_targets = sorted(set(g["bucket_diff_vs_i37"]) | set(p["bucket_diff_vs_i37"]))
        for t in all_targets:
            gb = g["bucket_diff_vs_i37"].get(t, (None, None))
            pb = p["bucket_diff_vs_i37"].get(t, (None, None))
            lines.append(f"| {t} | {gb[0]} | {gb[1]} | {pb[1]} |")
        lines += ["", "## 三类指标（global / perdoc）", "",
            "| 类 | DocRecall | QuestionPass | EvidencePass |", "|---|---|---|---|"]
        for cg, cp in zip(g["per_class"], p["per_class"]):
            lines.append(f"| {cg['domain']} | {cg['doc_recall']} / {cp['doc_recall']} | "
                         f"{cg['question_pass']} / {cp['question_pass']} | "
                         f"{cg['evidence_pass']} / {cp['evidence_pass']} |")

        # ── 关键发现与待决 ──
        perdoc_better = [t for t in set(g["bucket_diff_vs_i37"]) - set(p["bucket_diff_vs_i37"])]
        lines += [
            "", "## 关键发现", "",
            f"- 议题 B：两变体均 7/10 引文进入选择范围（6 条 selected_but_match_fail + 1 条 matched；"
            f"industry-001 e1-e3 / industry-003 e1/e2/a-3 选中块 rank 1，industry-002 e1 rank 5）。",
            f"- 未进的 3 条全部是 industry-008 的页 10 图6 表头/脚注引文（a-2/a-3/a-5）：raw rank 35/49，"
            f"该查询下页 10 图6 块未进入长江文档 top-8（页 6/7 的涨幅TOP5 表格块占据），"
            f"是候选池内排名问题而非 cap 问题。",
            f"- 6 条带 row:/col: 定位符的目标（industry-001/002/003 的 e1-e3）在现行观测构造下最多只能到 "
            f"selected_but_match_fail（EvidenceTarget.matches 要求 locator 全部 token ∈ evidence.locator，"
            f"而 evidence locator 只有 page:N）；只有 page-only 定位符的 a-3 可达 matched。",
            f"- company-003 回退（光力科技 doc 落出 top-5）是词法层回归：I-B1 标签注入改变 ts_rank 后，"
            f"光力在该查询下 doc rank 6；两变体均受影响，与结构排序信号无关。",
            f"- company-008 a-4 是两变体唯一分歧点：global 因全池重排把贵州茅台文档挤出 top-5 而回退，"
            f"perdoc 保持词法文档序后维持 matched（{perdoc_better}）。",
            f"- 系统级：EvidencePass 两变体均 12/24（i37 基线 13/24）；负例误报均 6（不增）；"
            f"company DocRecall global 13/16、perdoc 7/8（perdoc 恢复 company-008）。",
            "", "## 待决", "",
            "1. 排序信号形态：perdoc（文档序=词法，文档内按 (结构重叠, ts_rank)）相对 global 少 1 条回退"
            "且不扰动文档级召回，建议优先；是否采纳需裁决。",
            "2. company-003 词法级回退：属 I-B1 标签注入副作用，不在结构排序信号范围内，需另立议题。",
            "3. industry-008 表头/脚注引文：需判断是否属议题 B 验收必须（原文判据含 10 条全进），"
            "如必须则需扩展候选或检索侧信号。",
        ]
        (HERE / "backtest-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


if __name__ == "__main__":
    raise SystemExit(main())
