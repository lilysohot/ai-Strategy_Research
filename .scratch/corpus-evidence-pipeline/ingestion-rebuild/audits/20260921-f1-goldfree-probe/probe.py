"""B2 金标无关拒检探针（只读，0 model calls）。

问题
----
F1 的 6→0（`negative_query.tighten_no_answer_query` + `is_relevant_candidate`）**只在回测脚本里**成立，
且 `f1_backtest.py:98/147` 是按金标 `answer_existence is NO_ANSWER` **分支**才启用（与 spec §11
「评测量尺不得来自金标」冲突）⇒ 产品侧负例仍是 6（`service.py` 无 abstain 通道，`negative_query`
零产品调用点）。本探针把问题从"合不合规"变成"能不能用**金标无关**的谓词无条件达成 6→0"。

方法
----
对**全部 30 题一律**走同一条产品读取路径（OR 查询 → `read_pg.search_with_coverage_bands` →
`selection.select_band` → `read_pg.fetch_bands` → `CorpusService._assemble_band_documents`，含 cell 投影），
**不按 answer_existence 分支**，然后对四种形态各打分：

| 变体 | 拒检谓词（只吃：查询内容词元 + 候选文本） | 粒度 |
|---|---|---|
| `off` | 无（基线复现：负例应回升 6、band_s2 = 18/24、S1=66/S2=60/S4=50） | — |
| `a1_unit` | 该文档案内**任一被选单元**同时含全部内容词元 | 最紧（≈ F1 的 `is_relevant_candidate`） |
| `a2_item` | 该文档任一**带内块文本**同时含全部内容词元 | 中 |
| `a3_doc` | 该文档**全部已选证据文本合集**含全部内容词元 | 最松 |

判定口径（spec §13.4 纪律：只看端到端，不用单层指标下结论）
- **I-M6-1**：6 条 no-answer 题 `retrieved_documents == 0`（金标无关路径）
- **I-M6-2**：有答案题 `S1_candidates=66` / `S2_doc_topk=60` / `S4_matched=50` 逐字节不回退，
  band_s2 EvidencePass **18/24** 不回退
- **I-M6-3**：谓词输入只含查询词元与候选文本（静态断言 `negative_query` 源码不含金标字段；
  运行时断言 30/30 题一律施加同一门）
- 附加读数：逐题被丢弃文档清单（召回损失的**点名证据**）

只读 PG `i2_sandbox_corpus`；产物 write-once 写本目录；`--no-write` 干跑不落盘。
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from dataclasses import asdict
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
I33 = AUDITS / "20260920-i33-calibration"
I42 = AUDITS / "20260920-i42-topic-b-reingest"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))

SANDBOX = "i2_sandbox_corpus"
VARIANTS = ("off", "a1_unit", "a2_item", "a3_doc")
BASE_BAND_S2_EVIDENCE_PASS = 18
BASE_FUNNEL = {"S1_candidates": 66, "S2_doc_topk": 60, "S4_matched": 50}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def norm(s: object) -> str:
    return "".join(ch for ch in s if not ch.isspace()) if isinstance(s, str) else ""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true", help="干跑：不落盘产物")
    args = parser.parse_args()

    from plugins.corpus.preparation import read_pg
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.contract import UnitStatus
    from plugins.corpus.preparation.negative_query import content_lexemes
    from plugins.corpus.preparation.repository_pg import PgStore
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.preparation.selection import BandPolicy, SelectionPolicy, select_band
    from plugins.corpus.scoring import (AnswerExistence, FetchedEvidence, ObservationOutcome,
                                        QueryObservation, RetrievedDocument, ScoringPolicy,
                                        format_report, gold_from_records, score)
    from plugins.corpus.service import CorpusService
    import psycopg

    # ── I-M6-3 静态：拒检谓词不得接触金标 ──
    neg_src = (ROOT / "plugins/corpus/preparation/negative_query.py").read_text(encoding="utf-8")
    gate_source_clean = ("answer_existence" not in neg_src and "gold" not in neg_src.lower())

    band_policy = BandPolicy()
    assert SelectionPolicy().max_chunks_per_document == 8, "I-B3: cap 必须保持 8"

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()

    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    applier = loader.load_module(INGEST / "i3s2_apply_decisions.py", "i33_approved_input")
    manifest_dict = json.loads(loader.MANIFEST.read_text(encoding="utf-8"))
    diag_manifest = json.loads(json.dumps(manifest_dict))
    diag_manifest["lineage"]["scorer"]["sha256"] = digest(ROOT / "plugins/corpus/scoring.py")
    errors = loader.validate(records, loader.load_jsonl(loader.QUERY_GOLD),
                             json.loads(loader.PROJECTION.read_text()),
                             loader.load_jsonl(loader.SOURCE_GOLD),
                             diag_manifest, applier)
    if errors:
        raise RuntimeError(f"Frozen scoring assets invalid: {errors}")

    questions = gold_from_records(records)
    config = dict(json.loads((I33 / "calibration-plan-v2.json").read_text())["policy"])
    config["min_rate"] = Fraction(config["min_rate"])
    policy = ScoringPolicy(**config)

    svc = CorpusService(dsn)

    def build_document(doc) -> RetrievedDocument:
        evidences: list[FetchedEvidence] = []
        for band_items in doc.chunks_by_band:
            texts = [it.text for it in band_items]
            pages = sorted({p for it in band_items for p in it.pages})
            evidences.append(FetchedEvidence("\n".join(texts),
                                             tuple(f"page:{p}" for p in pages), True))
        for c in doc.cells:
            loc = [f"page:{c.page}"] if c.page is not None else []
            loc += [f"row:{c.row}", f"col:{c.col}"]
            evidences.append(FetchedEvidence(c.text, tuple(loc), True))
        return RetrievedDocument(doc.source_id, tuple(evidences), doc.build_id)

    def observation(query_id, docs, keep_by_source) -> QueryObservation:
        kept = [d for d in docs if keep_by_source.get(d.source_id, True)]
        documents = tuple(build_document(d) for d in kept)
        outcome = ObservationOutcome.OK if documents else ObservationOutcome.NO_MATCH
        return QueryObservation(query_id, outcome, documents)

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, SANDBOX)
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())
        if len(sources) != 8:
            raise RuntimeError(f"Active corpus has {len(sources)} sources (expected 8)")

        aliases = {}
        expected_aliases = {s for q in questions for s in q.relevant_sources}
        expected_aliases |= {t.source_id for q in questions for t in q.evidence_targets
                             if t.source_id}
        for alias in expected_aliases:
            matches = [s for s in sources if s.startswith(alias.rsplit("_", 1)[-1])]
            if len(matches) != 1:
                raise RuntimeError(f"Gold alias cannot resolve uniquely: {alias}")
            aliases[matches[0]] = alias
        alias_to_source = {alias: src for src, alias in aliases.items()}

        kept_pages: dict[str, dict[int, str]] = {}
        with PgStore(dsn, sandbox_db=SANDBOX) as store:
            for src, build_id in sources.items():
                pages: dict[int, list[str]] = {}
                for u in store.get_units(build_id):
                    if u.status is UnitStatus.KEPT and u.location.page is not None:
                        pages.setdefault(u.location.page, []).append(u.raw_text)
                kept_pages[build_id] = {pg: "\n".join(ls) for pg, ls in pages.items()}

        lexemes_by_qid = {
            q.query_id: tuple(conn.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(q.question),)).fetchone()[0] or ())
            for q in questions
        }

        def or_query(qid: str) -> str:
            lexemes = lexemes_by_qid[qid]
            if not lexemes:
                raise RuntimeError(f"{qid}: question tokenization produced no terms")
            return " OR ".join('"' + t.replace('"', " ") + '"' for t in lexemes)

        obs: dict[str, dict[str, QueryObservation]] = {v: {} for v in VARIANTS}
        keep_flags: dict[str, dict[str, dict[str, bool]]] = {v: {} for v in VARIANTS}
        dropped: list[dict] = []
        per_query: dict[str, dict] = {}
        gate_applied = 0
        traces = []

        for question in questions:
            qid = question.query_id
            query = or_query(qid)
            hits, chunk_order, _coverage = read_pg.search_with_coverage_bands(
                dsn, query, limit=2000, sandbox_db=SANDBOX)
            if len(hits) >= 2000:
                raise RuntimeError(f"{qid}: candidate cap saturated")
            bands = select_band(hits, SelectionPolicy(), band_policy,
                                chunk_order_by_source=chunk_order)
            chunk_evs = read_pg.fetch_bands(dsn, bands, chunk_order, sandbox_db=SANDBOX)
            docs = svc._assemble_band_documents(tuple(bands), tuple(chunk_evs), chunk_order)

            # 该来源被选中块的「单元级 / 块级」文本（与 fetch_bands 返回顺序一一对应）
            flat: list[tuple[str, str, str]] = []
            for band in bands:
                ordered = chunk_order[band.source_id]
                for pos in range(band.start, band.end + 1):
                    flat.append((band.source_id, band.build_id, ordered[pos]))
            if len(flat) != len(chunk_evs):
                raise RuntimeError(f"{qid}: band/chunk evidence 长度不一致")
            unit_texts: dict[str, list[str]] = {}
            item_texts: dict[str, list[str]] = {}
            for (sid, _bid, _cid), ev in zip(flat, chunk_evs):
                item_texts.setdefault(sid, []).append(ev.text)
                unit_texts.setdefault(sid, []).extend(u.raw_text for u in ev.units)

            content = content_lexemes(lexemes_by_qid[qid])
            by_source_doc = {d.source_id: d for d in docs}

            flags: dict[str, dict[str, bool]] = {}
            for variant in VARIANTS:
                flags[variant] = {}
                for doc in docs:
                    if variant == "off":
                        flags[variant][doc.source_id] = True
                        continue
                    if not content:
                        flags[variant][doc.source_id] = False
                        continue
                    if variant == "a1_unit":
                        joined = "\n".join(unit_texts.get(doc.source_id, ()))
                    elif variant == "a2_item":
                        joined = "\n".join(item_texts.get(doc.source_id, ()))
                    else:
                        joined = "\n".join(ev.text for ev in build_document(doc).evidence)
                    flags[variant][doc.source_id] = all(
                        norm(t) in norm(joined) for t in content)
                keep_flags[variant][qid] = flags[variant]
                obs[variant][qid] = observation(qid, docs, flags[variant])

            gate_applied += 1
            for variant in ("a1_unit", "a2_item", "a3_doc"):
                for sid, keep in flags[variant].items():
                    if not keep:
                        dropped.append({"query_id": qid, "variant": variant,
                                        "source_id": aliases.get(sid, sid),
                                        "answer_existence": question.answer_existence.value})
            per_query[qid] = {"hits": hits, "groups": {d.source_id: d for d in docs}}
            traces.append({
                "query_id": qid,
                "answer_existence": question.answer_existence.value,
                "content_lexemes": list(content),
                "chunk_hits": len(hits),
                "selected_docs": [aliases.get(d.source_id, d.source_id) for d in docs],
                "kept_docs": {v: [aliases.get(s, s) for s, k in flags[v].items() if k]
                              for v in ("a1_unit", "a2_item", "a3_doc")},
            })

        # 候选块逐字文本（同游标批量；S1 层判据用，禁 N+1）
        chunk_text_cache: dict[str, dict[tuple[str, str], str]] = {}

        def cand_texts(qid: str) -> dict[tuple[str, str], str]:
            if qid not in chunk_text_cache:
                hits = per_query[qid]["hits"]
                unit_refs: dict[str, set[str]] = {}
                for hit in hits:
                    for uid in hit.unit_refs:
                        unit_refs.setdefault(hit.build_id, set()).add(uid)
                raw_by_key: dict[tuple[str, str], str] = {}
                if unit_refs:
                    bs, us = [], []
                    for bid, uids in unit_refs.items():
                        for uid in uids:
                            bs.append(bid)
                            us.append(uid)
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT build_id, unit_id, raw_text, content_hash FROM corpus.corpus_units "
                            "WHERE (build_id, unit_id) IN "
                            "(SELECT b, u FROM unnest(%(bs)s::text[], %(us)s::text[]) AS x(b, u))",
                            {"bs": bs, "us": us})
                        for bid, uid, raw, chash in cur.fetchall():
                            text = str(raw or "")
                            if hashlib.sha256(text.encode()).hexdigest() != str(chash or ""):
                                raise RuntimeError(f"权威单元内容哈希不符: {uid}")
                            raw_by_key[(str(bid), str(uid))] = text
                chunk_text_cache[qid] = {
                    (hit.build_id, hit.chunk_id):
                        "\n".join(raw_by_key[(hit.build_id, uid)] for uid in hit.unit_refs)
                    for hit in hits}
            return chunk_text_cache[qid]

        reports = {v: score(questions, [obs[v][q.query_id] for q in questions], policy)
                   for v in VARIANTS}

        def epic(report) -> int:
            return sum(c.evidence_pass.passed for c in report.classes)

        def layer_summary(report) -> dict:
            return {
                "evidence_pass_total": f"{epic(report)}/{sum(c.evidence_pass.total for c in report.classes)}",
                "per_class": [{"domain": c.domain, "evidence_pass": f"{c.evidence_pass.passed}/{c.evidence_pass.total}"}
                              for c in report.classes],
                "false_positives": len(report.false_positives),
                "critical_failures": report.critical_failures,
            }

        # ── 逐目标漏斗（按变体重算：gate 丢弃的文档其 S2/S3/S4 一律判失）──
        funnels: dict[str, dict] = {}
        buckets: dict[str, dict] = {}
        for variant in VARIANTS:
            funnel_targets = []
            for q in questions:
                o = obs[variant][q.query_id]
                pinfo = per_query[q.query_id]
                flags = keep_flags[variant][q.query_id]
                relevant = set(q.relevant_sources)
                texts_by_chunk = cand_texts(q.query_id)
                cand_texts_by_src: dict[str, list[str]] = {}
                for hit in pinfo["hits"]:
                    cand_texts_by_src.setdefault(hit.source_id, []).append(
                        texts_by_chunk[(hit.build_id, hit.chunk_id)])
                for target in q.evidence_targets:
                    allowed = (target.source_id,) if target.source_id else tuple(relevant)
                    page = None
                    for tok in target.locator:
                        if tok.startswith("page:"):
                            page = int(tok.split(":", 1)[1])
                            break
                    matched = bool(o) and any(
                        target.matches(ev) and doc.source_id in allowed
                        for doc in o.documents for ev in doc.evidence)
                    src = target.source_id or (next(iter(relevant), None))
                    live_src = alias_to_source.get(src)
                    build_id = sources.get(live_src) if live_src else None
                    quote = norm(target.quote)

                    in_kept_any = bool(build_id) and any(
                        quote in norm(t) for t in kept_pages.get(build_id, {}).values())
                    in_kept_page = (page is not None and bool(build_id)
                                    and quote in norm(kept_pages.get(build_id, {}).get(page, "")))
                    s1 = any(quote in norm(t) for t in cand_texts_by_src.get(live_src or "", ()))
                    s2 = (s1 and live_src in pinfo["groups"]
                          and flags.get(live_src, True))
                    band_text = ""
                    if o and live_src is not None:
                        want = aliases.get(live_src, live_src)
                        for doc in o.documents:
                            if doc.source_id == want:
                                band_text = "\n".join(ev.text for ev in doc.evidence)
                                break
                    s3 = s2 and quote in norm(band_text)
                    s4 = s3 and matched
                    all_evs = [ev for doc in (o.documents if o else ()) for ev in doc.evidence]
                    in_selected = quote in norm("\n".join(ev.text for ev in all_evs))
                    bucket = ("matched" if matched else
                              "selected_but_match_fail" if in_selected else
                              "kept_page_not_selected" if in_kept_page else
                              "kept_elsewhere_page_mismatch" if in_kept_any else
                              "not_in_doc_unreachable")
                    funnel_targets.append({"query_id": q.query_id,
                                           "target_id": f"{q.query_id} {target.target_id}",
                                           "S0_kept": in_kept_any, "S1_candidates": s1,
                                           "S2_doc_topk": s2, "S3_band_cover": s3,
                                           "S4_matched": s4, "matched": matched,
                                           "bucket": bucket})
            funnels[variant] = {
                key: sum(1 for r in funnel_targets if r[key])
                for key in ("S0_kept", "S1_candidates", "S2_doc_topk", "S3_band_cover", "S4_matched")}
            buckets[variant] = dict(Counter(r["bucket"] for r in funnel_targets))

        negatives = {
            v: [{"query_id": q.query_id, "retrieved_documents": len(obs[v][q.query_id].documents)}
                for q in questions if q.answer_existence is AnswerExistence.NO_ANSWER]
            for v in VARIANTS}

        dropped_answerable = [d for d in dropped if d["answer_existence"] != AnswerExistence.NO_ANSWER.value]
        verdict = {
            "I-M6-1_negatives_zero": {v: all(n["retrieved_documents"] == 0 for n in negatives[v])
                                      for v in VARIANTS},
            "I-M6-2_no_answerable_regression": {},
            "I-M6-3_gate_is_gold_free_source": gate_source_clean,
            "I-M6-3_gate_applied_to_all_questions": gate_applied == len(questions),
        }
        for v in VARIANTS:
            f = funnels[v]
            verdict["I-M6-2_no_answerable_regression"][v] = {
                "S1_candidates": f["S1_candidates"],
                "S2_doc_topk": f["S2_doc_topk"],
                "S4_matched": f["S4_matched"],
                "evidence_pass": epic(reports[v]),
                "ok": (f["S1_candidates"] == BASE_FUNNEL["S1_candidates"]
                       and f["S2_doc_topk"] == BASE_FUNNEL["S2_doc_topk"]
                       and f["S4_matched"] == BASE_FUNNEL["S4_matched"]
                       and epic(reports[v]) >= BASE_BAND_S2_EVIDENCE_PASS),
            }

        summary = {
            "artifact": "f1-goldfree-probe",
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "kind": "金标无关拒检探针（只读；非冻结回归）",
            "corpus": "index-4-zhcfg-2 active (8 builds)",
            "pipeline": "product band_s2 path (search_with_coverage_bands → select_band → fetch_bands → "
                        "_assemble_band_documents)；30 题一律同路径，不按 answer_existence 分支",
            "gold_independence": {
                "gate_inputs": "查询内容词元（zhcfg 词元去功能词）+ 候选文本",
                "static_check": gate_source_clean,
                "all_questions_gated": gate_applied == len(questions),
            },
            "baseline_f2": {"evidence_pass_band_s2": BASE_BAND_S2_EVIDENCE_PASS, "funnel": BASE_FUNNEL,
                            "negatives": 6},
            "variants": {v: {"evidence_pass": epic(reports[v]), "funnel": funnels[v],
                             "buckets": buckets[v], "negatives_zero": verdict["I-M6-1_negatives_zero"][v],
                             "dropped_docs_total": sum(1 for d in dropped if d["variant"] == v),
                             "dropped_docs_answerable": sum(1 for d in dropped_answerable
                                                            if d["variant"] == v)}
                         for v in VARIANTS},
            "verdict": verdict,
            "layers": {v: layer_summary(reports[v]) for v in VARIANTS},
            "dropped_docs_answerable": dropped_answerable,
            "questions": len(questions),
        }

        if not args.no_write:
            def write_once(name: str, value) -> None:
                path = HERE / name
                raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
                if path.exists() and path.read_bytes() != raw:
                    raise RuntimeError(f"write-once conflict: {name}")
                path.write_bytes(raw)

            write_once("probe-summary.json", summary)
            write_once("probe-trace.json", traces)
            write_once("probe-dropped-docs.json", dropped)
            write_once("probe-funnel-targets.json", funnels)
            lines = [
                "# B2 金标无关拒检探针（只读）",
                "",
                f"- 生成：{summary['generated_at']}；0 model calls；只读 `i2_sandbox_corpus`",
                f"- 路径：{summary['pipeline']}",
                "- 门输入：查询内容词元 + 候选文本（静态检查通过：" f"{gate_source_clean}）",
                "",
                "## 变体对照（30 题一律施门，含 6 条 no-answer）",
                "",
                "| 变体 | EvidencePass | S2_doc_topk | S4_matched | 负例全 0 | 丢弃文档（有答案题） |",
                "|---|---|---:|---:|---|---:|",
            ]
            for v in VARIANTS:
                item = summary["variants"][v]
                lines.append(f"| `{v}` | {item['evidence_pass']}/24 | {item['funnel']['S2_doc_topk']} | "
                             f"{item['funnel']['S4_matched']} | {item['negatives_zero']} | "
                             f"{item['dropped_docs_answerable']} |")
            lines += ["", "## 有答案题被丢弃的文档（召回损失点名）", ""]
            if dropped_answerable:
                for d in dropped_answerable:
                    lines.append(f"- `{d['variant']}` {d['query_id']} → {d['source_id']}")
            else:
                lines.append("- 无")
            (HERE / "probe-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
            (HERE / "probe-score-off.md").write_text(format_report(reports["off"]) + "\n")
            for v in ("a1_unit", "a2_item", "a3_doc"):
                (HERE / f"probe-score-{v}.md").write_text(format_report(reports[v]) + "\n")

        print(json.dumps({"verdict": verdict, "variants": summary["variants"]},
                         ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
