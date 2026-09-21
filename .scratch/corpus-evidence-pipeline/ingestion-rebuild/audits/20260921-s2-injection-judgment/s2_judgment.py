"""S2 判定实验：标签注入对召回（S1_candidates）与 EvidencePass 的贡献。

问题（spec §10.2 / §6.1 S2）：chunk._table_row_label_prefix 把结构标签前缀
无条件拼进 search_text → GENERATED 列 search_tsv → 同时影响 GIN 召回与 ts_rank。
S2 判定「临时关掉标签注入」后 S1_candidates 与 EvidencePass 是否变化，据此选择
S3a（保留注入、进独立 label_tsv）还是 S3b（删除注入）。

方法（读侧虚拟重建，**不重摄入**，0 model calls）：
- 标签只注入 search_text，从不进入 unit.raw_text。因此每个候选 chunk 的
  「无注入索引文本」= 其引用单元 raw_text 的确定性 "\\n" 拼接（fetch_verbatim
  同语义），再经 chunk.normalize_search_text 归一化（与写侧同一 R5 规则）。
- 用 ``to_tsvector('zhcfg', no_label_text) @@ tsq`` 判定无注入召回；
  用 ``ts_rank(to_tsvector('zhcfg', no_label_text), tsq)`` 得无注入排名。
- 两变体同口径回测（口径与 i42 backtest.py 逐项一致：79 目标、perdoc 选择、
  工作树空白规约 scorer、query = 问题词元 OR 连接、limit=2000 不饱和断言）：
    * with_injection：现状（搜索仍走带注入索引）；
    * no_injection：候选集 = 无注入命中子集，按无注入 ts_rank 重排后再选择。

自检：with_injection 变体应复现 i42 的漏斗 66/60/51/44 与 EvidencePass 12/24。
若复现失败，先修脚本再读结论。

判定输出：
1. S1_candidates 随注入去除的掉失（逐目标 + 逐 chunk：哪个查询词元只来自标签）；
2. EvidencePass（链尾）随注入去除的变化（含 S2/S3 排名位移解释）；
3. 负例误报不得从 i42 的 6 回升。
"""
from __future__ import annotations

import copy
import hashlib
import importlib.util
import json
import sys
from collections import Counter
from dataclasses import asdict, replace
from datetime import datetime, timezone
from fractions import Fraction
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
I33 = AUDITS / "20260920-i33-calibration"
I37 = AUDITS / "20260920-i37-fullchain-backtest"
I42 = AUDITS / "20260920-i42-topic-b-reingest"
I31 = AUDITS / "20260920-i31-region-review"
HERE = Path(__file__).resolve().parent

sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))
sys.path.insert(0, str(I31))

import calibrate  # noqa: E402  reuse observations_for

SANDBOX = "i2_sandbox_corpus"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_once(name: str, value) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"write-once conflict: {name}")
    path.write_bytes(raw)


def load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def norm(s: object) -> str:
    return "".join(ch for ch in s if not ch.isspace()) if isinstance(s, str) else ""


def group_perdoc(hits, lexemes, top_k: int, per_doc: int) -> dict[str, list]:
    """per-doc 变体选择：文档序 = 词法首次出现，文档内前 per_doc 块按
    (结构重叠数, ts_rank) 重排（i42 backtest.py 原样搬移）。"""
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

    release = load_module("i31_region_release", I31 / "release.py")
    dsn = release.connect()

    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    applier = loader.load_module(INGEST / "i3s2_apply_decisions.py", "i33_approved_input")
    scorer_sha = digest(ROOT / "plugins/corpus/scoring.py")
    manifest_dict = json.loads(loader.MANIFEST.read_text(encoding="utf-8"))
    diag_manifest = copy.deepcopy(manifest_dict)
    diag_manifest["lineage"]["scorer"]["sha256"] = scorer_sha
    errors = loader.validate(records, loader.load_jsonl(loader.QUERY_GOLD),
                             json.loads(loader.PROJECTION.read_text()),
                             loader.load_jsonl(loader.SOURCE_GOLD),
                             diag_manifest, applier)
    if errors:
        raise RuntimeError(f"Frozen scoring assets invalid: {errors}")

    from plugins.corpus.scoring import (gold_from_records, ScoringPolicy, score,
                                        format_report, AnswerExistence)
    from plugins.corpus.preparation.search_pg import search_chunks, _check_target
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.read_pg import fetch_verbatim, build_handle, chunk_locator
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

        aliases: dict[str, str] = {}
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

        # kept 单元按 build → page 缓存（与 i42 同口径）
        kept_pages: dict[str, dict[int, str]] = {}
        with PgStore(dsn, sandbox_db=SANDBOX) as store:
            for src, build_id in sources.items():
                pages: dict[int, list[str]] = {}
                for u in store.get_units(build_id):
                    if u.status is UnitStatus.KEPT and u.location.page is not None:
                        pages.setdefault(u.location.page, []).append(u.raw_text)
                kept_pages[build_id] = {pg: "\n".join(ls) for pg, ls in pages.items()}

        cache: dict = {}
        receipts: dict = {}

        def fetch(hit):
            key = (hit.build_id, hit.chunk_id)
            if key not in cache:
                cache[key] = fetch_verbatim(dsn, build_handle(hit.build_id), chunk_locator(hit.chunk_id))
                receipts["/".join(key)] = asdict(cache[key])
            return cache[key]

        # ── 逐查询：候选 + 无注入重建（读侧，不写库） ──────────────────────
        per_query: dict[str, dict] = {}
        for question in questions:
            lexemes = conn.execute("SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                                   (normalize_search_text(question.question),)).fetchone()[0]
            if not lexemes:
                raise RuntimeError("Question tokenization produced no terms")
            query = " OR ".join('"' + term.replace('"', ' ') + '"' for term in lexemes)
            tsquery_text = conn.execute("SELECT websearch_to_tsquery('zhcfg', %s)::text",
                                        (normalize_search_text(query),)).fetchone()[0]
            hits = search_chunks(dsn, query, limit=2000)
            if len(hits) >= 2000:
                raise RuntimeError("Candidate cap saturated; cannot certify document top-k")

            # 批量取候选 chunk 的引用单元 raw_text（无注入文本的来源）
            unit_refs: dict[str, set[str]] = {}
            for hit in hits:
                for uid in hit.unit_refs:
                    unit_refs.setdefault(hit.build_id, set()).add(uid)
            raw_by_key: dict[tuple[str, str], str] = {}
            if unit_refs:
                build_ids: list[str] = []
                unit_ids: list[str] = []
                for bid, uids in unit_refs.items():
                    for uid in uids:
                        build_ids.append(bid)
                        unit_ids.append(uid)
                with conn.cursor() as cur:
                    cur.execute(
                        "SELECT build_id, unit_id, raw_text, content_hash FROM corpus.corpus_units "
                        "WHERE (build_id, unit_id) IN "
                        "(SELECT b, u FROM unnest(%(bs)s::text[], %(us)s::text[]) AS x(b, u))",
                        {"bs": build_ids, "us": unit_ids})
                    for bid, uid, raw, chash in cur.fetchall():
                        text = str(raw or "")
                        if hashlib.sha256(text.encode()).hexdigest() != str(chash or ""):
                            raise RuntimeError(f"权威单元内容哈希不符: {uid} @ {str(bid)[:12]}")
                        raw_by_key[(str(bid), str(uid))] = text
            text_by_chunk: dict[tuple[str, str], str] = {}
            for hit in hits:
                parts = [raw_by_key[(hit.build_id, uid)] for uid in hit.unit_refs]
                if len(parts) != len(hit.unit_refs):
                    raise RuntimeError(f"候选 chunk 单元悬空: {hit.build_id[:12]}/{hit.chunk_id}")
                text_by_chunk[(hit.build_id, hit.chunk_id)] = "\n".join(parts)

            # 无注入匹配 + 排名（批量，一次 SQL/查询）
            noinj_texts = [normalize_search_text(text_by_chunk[(h.build_id, h.chunk_id)]) for h in hits]
            noinj: dict[int, tuple[bool, float]] = {}
            with conn.cursor() as cur:
                cur.execute(
                    "WITH q AS (SELECT %(tsq)s::tsquery AS tsq) "
                    "SELECT i, (to_tsvector('zhcfg', t) @@ q.tsq) AS m, "
                    "       ts_rank(to_tsvector('zhcfg', t), q.tsq) AS r "
                    "FROM unnest(%(texts)s::text[]) WITH ORDINALITY AS x(t, i), q",
                    {"tsq": tsquery_text, "texts": noinj_texts})
                for i, m, r in cur.fetchall():
                    noinj[i - 1] = (bool(m), float(r))

            per_query[question.query_id] = {
                "question": question, "lexemes": tuple(lexemes),
                "hits": hits, "text_by_chunk": text_by_chunk, "noinj": noinj,
            }

        # ── 两变体的选择与观测 ────────────────────────────────────────────
        variants: dict[str, dict[str, tuple]] = {}   # vname -> qid -> (hits, grouped)
        for vname, mode in (("with_injection", "injection"), ("no_injection", "noinjection")):
            selected: dict[str, tuple] = {}
            for qid, info in per_query.items():
                hits = info["hits"]
                lexemes = info["lexemes"]
                if mode == "injection":
                    sel_hits = hits
                else:
                    picked = [replace(h, score=r) for i, h in enumerate(hits)
                              if info["noinj"][i][0]]
                    picked.sort(key=lambda h: (-h.score, h.build_id, h.chunk_id))
                    sel_hits = tuple(picked)
                grouped = group_perdoc(sel_hits, lexemes, policy.top_k, 8)
                selected[qid] = (sel_hits, grouped)
            variants[vname] = selected

        # ── 评分 + 漏斗 + 归因（两变体） ──────────────────────────────────
        def run_variant(vname: str) -> dict:
            selected = variants[vname]
            observations = []
            for question in questions:
                sel_hits, grouped = selected[question.query_id]
                observations.append(
                    calibrate.observations_for(question.query_id, grouped, fetch, aliases))
            report = score(questions, observations, policy)

            neg = []
            for q, o in zip(questions, observations):
                if q.answer_existence is AnswerExistence.NO_ANSWER:
                    docs = [{"source_id": d.source_id, "build_id": d.build_id,
                             "evidence_preview": [ev.text[:140] for ev in d.evidence][:4]}
                            for d in o.documents] if o else []
                    neg.append({"query_id": q.query_id, "answer_existence": q.answer_existence.name,
                                "question": q.question, "retrieved_documents": len(docs), "docs": docs})

            ob_map = {o.query_id: o for o in observations}
            rows = []
            for q in questions:
                obs = ob_map.get(q.query_id)
                relevant = set(q.relevant_sources)
                sel_hits, grouped = selected[q.query_id]
                info = per_query[q.query_id]
                src = None
                for target in q.evidence_targets:
                    allowed = (target.source_id,) if target.source_id else tuple(relevant)
                    src = target.source_id or (next(iter(relevant), None))
                    live_src = alias_to_source.get(src)
                    build_id = sources.get(live_src) if live_src else None
                    page = None
                    for tok in target.locator:
                        if tok.startswith("page:"):
                            page = int(tok.split(":", 1)[1])
                            break

                    row = {"query_id": q.query_id, "target_id": q.query_id + " " + target.target_id,
                           "domain": q.domain, "quote": target.quote,
                           "locator": list(target.locator), "source_id": target.source_id}
                    matched = False
                    if obs is not None:
                        matched = any(target.matches(ev) and doc.source_id in allowed
                                      for doc in obs.documents for ev in doc.evidence)
                    row["matched"] = matched

                    # S0：引文在 kept 单元内
                    in_kept_any = False
                    if build_id:
                        in_kept_any = any(norm(target.quote) in norm(t)
                                          for t in kept_pages.get(build_id, {}).values())
                    row["S0_kept"] = in_kept_any

                    # S1：引文在候选块内（该变体的候选集）
                    cand_texts = [info["text_by_chunk"][(h.build_id, h.chunk_id)]
                                  for h in sel_hits if h.build_id == build_id]
                    s1 = any(norm(target.quote) in norm(t) for t in cand_texts)
                    row["S1_candidates"] = s1

                    # S2：源文档进 top-5 选择
                    doc_in_topk = any(hit.source_id == live_src
                                      for hlist in grouped.values() for hit in hlist)
                    row["S2_doc_topk"] = s1 and doc_in_topk

                    # S3：引文块进该文档选中 top-8
                    sel_doc = [h for h in grouped.get(live_src, [])]
                    s3 = any(norm(target.quote)
                             in norm(info["text_by_chunk"][(h.build_id, h.chunk_id)])
                             for h in sel_doc)
                    row["S3_chunk_top8"] = row["S2_doc_topk"] and s3
                    row["S4_matched"] = row["S3_chunk_top8"] and matched

                    # 桶（i42 口径）
                    selected_text = "\n".join(ev.text for doc in obs.documents for ev in doc.evidence) if obs else ""
                    in_selected = norm(target.quote) in norm(selected_text)
                    in_kept_page = False
                    if build_id and page is not None:
                        in_kept_page = norm(target.quote) in norm(kept_pages.get(build_id, {}).get(page, ""))
                    if matched:
                        row["bucket"] = "matched"
                    elif in_selected:
                        row["bucket"] = "selected_but_match_fail"
                    elif in_kept_page:
                        row["bucket"] = "kept_page_not_selected"
                    elif in_kept_any:
                        row["bucket"] = "kept_elsewhere_page_mismatch"
                    else:
                        row["bucket"] = "not_in_doc_unreachable"
                    rows.append(row)
            return {"report": report, "observations": observations, "rows": rows, "neg": neg}

        v_inj = run_variant("with_injection")
        v_noinj = run_variant("no_injection")

        # ── 注入召回贡献归因 ──────────────────────────────────────────────
        contrib = []
        row_by_id = {r["target_id"]: r for r in v_inj["rows"]}
        noinj_by_id = {r["target_id"]: r for r in v_noinj["rows"]}
        for q in questions:
            relevant = set(q.relevant_sources)
            for target in q.evidence_targets:
                tid = f"{q.query_id} {target.target_id}"
                row = row_by_id.get(tid)
                if row is None or not row["S1_candidates"]:
                    continue
                if noinj_by_id[tid]["S1_candidates"]:
                    continue
                # 该目标：带注入可召回、无注入不可召回 → 注入贡献待查
                src = target.source_id or (next(iter(relevant), None))
                live_src = alias_to_source.get(src)
                build_id = sources.get(live_src)
                info = per_query[q.query_id]
                lexeme_set = set(info["lexemes"])
                chunks = []
                for i, h in enumerate(info["hits"]):
                    if h.build_id != build_id:
                        continue
                    text = info["text_by_chunk"][(h.build_id, h.chunk_id)]
                    if norm(target.quote) not in norm(text):
                        continue
                    m, r = info["noinj"][i]
                    label_tokens = set()
                    for label in h.label_path:
                        label_tokens.update(label.split())
                    label_hits = sorted(lexeme_set & label_tokens)
                    chunks.append({
                        "chunk_id": h.chunk_id, "kind": h.kind,
                        "no_label_match": m, "no_label_rank": r,
                        "label_lexemes_hit": label_hits,
                        "quote_in_chunk": True,
                    })
                contrib.append({
                    "target_id": tid, "quote": target.quote,
                    "source_alias": src, "chunks": chunks,
                })

        # ── 汇总 ──────────────────────────────────────────────────────────
        def pack(v: dict) -> dict:
            r = v["report"]
            buckets = Counter(x["bucket"] for x in v["rows"])
            funnel = {k: sum(1 for x in v["rows"] if x[k]) for k in
                      ("S0_kept", "S1_candidates", "S2_doc_topk", "S3_chunk_top8", "S4_matched")}
            return {
                "funnel": funnel,
                "evidence_pass_total": f"{sum(c.evidence_pass.passed for c in r.classes)}/"
                                       f"{sum(c.evidence_pass.total for c in r.classes)}",
                "per_class": [{"domain": c.domain, "doc_recall": str(c.doc_recall.rate),
                               "question_pass": f"{c.question_pass.passed}/{c.question_pass.total}",
                               "evidence_pass": f"{c.evidence_pass.passed}/{c.evidence_pass.total}"}
                              for c in r.classes],
                "false_positives": len(r.false_positives),
                "fabricated_citations": len(r.fabricated_citations),
                "critical_failures": len(r.critical_failures),
                "buckets": dict(buckets),
                "negatives": v["neg"],
            }

        p_inj = pack(v_inj)
        p_noinj = pack(v_noinj)

        # 自检：with_injection 应复现 i42
        i42_funnel = load_json(I42 / "recall-funnel.json")["funnel"]
        reproduce = (p_inj["funnel"]["S1_candidates"] == i42_funnel["S1_candidates"] == 66
                     and p_inj["funnel"]["S4_matched"] == i42_funnel["S4_matched"] == 44
                     and p_inj["evidence_pass_total"] == "12/24")

        summary = {
            "artifact": "s2-injection-judgment",
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "corpus": "index-4-zhcfg-2 active (8 builds)",
            "method": "read-side virtual no-injection reconstruction (no re-ingest); "
                      "no-label text = unit raw_text join + normalize_search_text (R5)",
            "scorer": "working-tree whitespace-norm (NOT frozen)",
            "model_calls": 0,
            "i42_baseline": {"funnel": i42_funnel,
                             "evidence_pass_total": "12/24", "false_positives": 6},
            "with_injection": p_inj,
            "no_injection": p_noinj,
            "self_check_reproduces_i42": reproduce,
            "injection_recall_contribution": {
                "targets_with_injection_recall": len(contrib),
                "targets": contrib,
            },
        }
        write_once("s2-summary.json", summary)
        print(json.dumps(summary, ensure_ascii=False, indent=2))

        # ── MD 报告 ──
        lines = [
            "# S2 判定实验：标签注入对召回与 EvidencePass 的贡献（读侧虚拟重建）",
            "",
            f"- 生成：{summary['generated_at']}；类型：判定实验（spec §6.1 S2 / §10.2）",
            f"- corpus：8 份 active builds（index-4-zhcfg-2，与 i42 同）",
            f"- 方法：不重摄入。无注入索引文本 = 候选 chunk 引用单元 raw_text 逐字拼接"
            f" + normalize_search_text（R5），重算 to_tsvector('zhcfg', …) @@ tsq 与 ts_rank。",
            f"- 口径：79 目标、perdoc 选择、工作树空白规约 scorer、query=问题词元 OR、"
            f"limit=2000 不饱和断言（与 i42 backtest.py 一致）。",
            f"- 自检（with_injection 复现 i42）：**{'通过' if reproduce else '未通过'}**",
            "",
            "## 漏斗对比（嵌套累计）",
            "",
            "| 层 | i42 基线 | with_injection | no_injection | Δ(no_inj − i42) |",
            "|---|---|---:|---:|---:|",
        ]
        for k in ("S0_kept", "S1_candidates", "S2_doc_topk", "S3_chunk_top8", "S4_matched"):
            base = i42_funnel[k]
            wi = p_inj["funnel"][k]
            ni = p_noinj["funnel"][k]
            lines.append(f"| {k} | {base} | {wi} | {ni} | **{ni - base:+d}** |")
        lines += [
            "",
            "## 三类指标（with_injection / no_injection）",
            "",
            "| 类 | DocRecall | QuestionPass | EvidencePass |",
            "|---|---|---|---|",
        ]
        for ci, cn in zip(p_inj["per_class"], p_noinj["per_class"]):
            lines.append(f"| {ci['domain']} | {ci['doc_recall']} / {cn['doc_recall']} | "
                         f"{ci['question_pass']} / {cn['question_pass']} | "
                         f"{ci['evidence_pass']} / {cn['evidence_pass']} |")
        lines += [
            "",
            f"- EvidencePass：with_injection {p_inj['evidence_pass_total']}；"
            f"no_injection {p_noinj['evidence_pass_total']}（i42 基线 12/24）",
            f"- 负例误报：with_injection {p_inj['false_positives']}；"
            f"no_injection {p_noinj['false_positives']}（i42 基线 6，不得回升）",
            "",
            "## 注入的召回贡献（S1_candidates 掉失目标）",
            "",
            f"**带注入可召回、无注入不可召回的目标数 = {len(contrib)}**（0 即注入对召回零贡献）",
            "",
        ]
        if contrib:
            lines.append("| 目标 | 源 | 涉及 chunk | 无注入匹配 | 标签词元命中 |")
            lines.append("|---|---|---:|---|---|")
            for c in contrib:
                first = c["chunks"][0] if c["chunks"] else {}
                lines.append(f"| {c['target_id']} | {c['source_alias']} | "
                             f"{len(c['chunks'])} | "
                             f"{'Y' if first.get('no_label_match') else 'N'} | "
                             f"{','.join(first.get('label_lexemes_hit', []))} |")
        lines += [
            "",
            "## 逐目标对比（with_injection → no_injection）",
            "",
            "| 目标 | S1(wi→ni) | S2 | S3 | S4 | 桶(wi) → 桶(ni) |",
            "|---|---|---|---|---|---|",
        ]
        by_id = {r["target_id"]: r for r in v_noinj["rows"]}
        for r in sorted(v_inj["rows"], key=lambda x: x["target_id"]):
            nr = by_id[r["target_id"]]
            arrow = lambda v, k: f"{'✓' if v[k] else '✗'}→{'✓' if nr[k] else '✗'}"  # noqa: E731
            lines.append(f"| {r['target_id']} | {arrow(r, 'S1_candidates')} | "
                         f"{arrow(r, 'S2_doc_topk')} | {arrow(r, 'S3_chunk_top8')} | "
                         f"{arrow(r, 'S4_matched')} | {r['bucket']} → {nr['bucket']} |")
        lines += ["", "## 判定", "",
            f"- **S1_candidates 掉失：{len(contrib)} 条**。"
            f"{'（0 掉失）→ 注入对召回零贡献，支持 S3b 删除注入。' if not contrib else '见上方逐目标归因。'}",
            f"- EvidencePass 变化：{p_inj['evidence_pass_total']} → {p_noinj['evidence_pass_total']}。",
            f"- 负例误报：{p_inj['false_positives']} → {p_noinj['false_positives']}"
            f"（{'符合' if p_noinj['false_positives'] <= 6 else '超出'}不回升约束）。",
        ]
        (HERE / "s2-report.md").write_text("\n".join(lines) + "\n", encoding="utf-8")

        # 逐目标表落盘
        write_once("s2-targets.json", {
            "with_injection": v_inj["rows"],
            "no_injection": v_noinj["rows"],
        })
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
