"""company-003（光力科技）文档级召回机读归因（0 model calls，只读 PG，write-once）。

议题（issues/10）：金标文档（国信 doc）在 company-003 查询词法排名落第 6、被 doc
top-5 截断（S2_doc_topk=false），6 条证据目标全 fail。历史归因（i42:72 / spec §10.2）
指向 I-B1 标签注入副作用，本轮以机读证据复核。

方法（全部读取侧，不触产品字节、不写库；唯一临时对象为会话级 TEMP TABLE，
断连即消散，corpus schema 零写入）：
1. 词法排名复现：production 同构 or_query（zhcfg 词元 OR）→
   read_pg.search_with_coverage_bands(limit=2000) → distinct-source 首现序
   （= selection 文档序）→ 金标 doc 的 rank 与 top-5 竞品；
2. 产品选择交叉验证：svc._apply_selection_bands 的选中来源集不含金标（复现 f2 桶）；
3. 词元命中分解（机制定位）：对 top-6 来源的 best chunk，
   search_tsv 命中词元 = body 命中（unit.raw_text）+ 注入标签命中（unit.location.label_path
   按产品注入串 " ".join(dedup) 重建）+ 残差；并给出 body-only ts_rank 对照；
4. 反事实（假设检验）：body-only（去标签）重排 company-003 候选池——金标 doc 是否回
   top-5（假设为真的预测；若不成立则如实上报，假设被证伪）；
5. 扰动面（S2 判定教训：判定必须看端到端/截断面，不得单层下结论）：同一 body-only
   反事实下 24 个有答案题的 doc top-5 集合变化数。

断言（红-可捕获）：目标恰 6 条、金标 doc 词法命中但 rank>5、产品选择不含金标、
6 目标 S1 复现（引文在金标命中块文本内）。
"""
from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
INGEST = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDITS = INGEST / "audits"
I33 = AUDITS / "20260920-i33-calibration"
HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(I33))


# generated_at 是唯一非语义字段（墙钟，每次重跑必然不同）。write-once 判定按语义字段
# 逐字段比较：全部一致 ⇒ 视为复现成功，保留原产物字节不重写；任一语义字段不同 ⇒ 冲突。
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
            print(f"[write-once] {name}: 语义逐字段一致（仅 {NON_SEMANTIC_FIELDS[0]} 不同）"
                  f"→ 保留原产物字节，未重写", file=sys.stderr)
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


def norm_ws(text: str) -> str:
    """scoring 同口径空白规约：剥离全部空白后包含判定。"""
    return "".join(text.split())


def main() -> int:
    dry_run = "--no-write" in sys.argv
    import psycopg

    from plugins.corpus.preparation import read_pg
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.search_pg import _check_target
    from plugins.corpus.scoring import AnswerExistence, gold_from_records
    from plugins.corpus.service import CorpusService

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()
    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    questions = gold_from_records(records)
    LIMIT = 2000
    svc = CorpusService(dsn)

    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, "i2_sandbox_corpus")
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())

    # gold 别名 → 活动 source（与 f3b_replay 同口径）
    aliases: dict[str, str] = {}
    expected = {s for q in questions for s in q.relevant_sources}
    expected |= {t.source_id for q in questions for t in q.evidence_targets if t.source_id}
    for alias in expected:
        matches = [s for s in sources if s.startswith(alias.rsplit("_", 1)[-1])]
        if len(matches) != 1:
            raise RuntimeError(f"Gold alias cannot resolve uniquely: {alias}")
        aliases[matches[0]] = alias
    build_to_src = {b: s for s, b in sources.items()}

    def or_query(cur, q) -> str:
        lexemes = cur.execute(
            "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
            (normalize_search_text(q.question),)).fetchone()[0]
        return " OR ".join('"' + t.replace('"', ' ') + '"' for t in lexemes)

    def doc_order(rows) -> list[str]:
        """distinct-source 首现序（= selection 文档序：首个命中即确定来源排名）。"""
        seen: list[str] = []
        for r in rows:
            sid = r.source_id if hasattr(r, "source_id") else r[0]
            if sid not in seen:
                seen.append(sid)
        return seen

    q003 = next(q for q in questions if q.query_id == "company-003")
    gold_alias = next(iter(q003.relevant_sources))
    gold_src = next(s for s, a in aliases.items() if a == gold_alias)
    gold_build = sources[gold_src]

    # ── 1. 词法排名复现 ────────────────────────────────────────────────
    with psycopg.connect(dsn, autocommit=True) as c0:
        orq = or_query(c0, q003)
        q_lexemes = c0.execute(
            "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
            (normalize_search_text(q003.question),)).fetchone()[0]
    raw_hits, chunk_order, _cov = read_pg.search_with_coverage_bands(
        dsn, orq, limit=LIMIT, sandbox_db="i2_sandbox_corpus")
    order = doc_order(raw_hits)
    best_score: dict[str, float] = {}
    n_hits: dict[str, int] = {}
    for h in raw_hits:
        best_score[h.source_id] = max(best_score.get(h.source_id, 0.0), h.score)
        n_hits[h.source_id] = n_hits.get(h.source_id, 0) + 1
    rank_table = [{"rank": i + 1, "source_id": s, "alias": aliases.get(s, s),
                   "best_score": best_score[s], "hits": n_hits[s],
                   "gold": s == gold_src} for i, s in enumerate(order)]
    gold_rank = order.index(gold_src) + 1 if gold_src in order else None

    # ── 2. 产品选择交叉验证 ────────────────────────────────────────────
    bands = svc._apply_selection_bands(raw_hits, chunk_order, LIMIT)
    sel_sources: list[str] = []
    for b in bands:
        if b.source_id not in sel_sources:
            sel_sources.append(b.source_id)
    gold_excluded = gold_src not in sel_sources

    # ── 3. 词元命中分解（top-6 + 金标 best chunks）────────────────────
    with psycopg.connect(dsn, autocommit=True) as c0:
        chunk_rows = c0.execute(
            "SELECT c.build_id, c.chunk_id, c.kind, c.search_text, "
            "tsvector_to_array(c.search_tsv), c.unit_refs "
            "FROM corpus.corpus_chunks c WHERE c.build_id = ANY(%(bs)s::text[])",
            {"bs": list(sources.values())}).fetchall()
        unit_rows = c0.execute(
            "SELECT build_id, unit_id, raw_text, location->'label_path' "
            "FROM corpus.corpus_units WHERE build_id = ANY(%(bs)s::text[])",
            {"bs": list(sources.values())}).fetchall()
    unit_text = {(r[0], r[1]): (r[2] or "") for r in unit_rows}
    unit_labels = {(r[0], r[1]): (r[3] or []) for r in unit_rows}

    def unit_prefix(label_path) -> str:
        parts: list[str] = []
        seen: set[str] = set()
        for label in label_path:
            if label and label not in seen:
                seen.add(label)
                parts.append(label)
        return " ".join(parts)

    hits_by_source: dict[str, list] = {}
    for h in raw_hits:
        hits_by_source.setdefault(h.source_id, []).append(h)
        hits_by_source[h.source_id].sort(key=lambda x: x.score, reverse=True)
    decomp_sources = list(dict.fromkeys(order[:6] + [gold_src]))

    per_source = []
    residual_chunks = 0
    for sid in decomp_sources:
        top_hits = hits_by_source.get(sid, [])[:20]
        best_full = hits_by_source.get(sid, [None])[0]
        entry = {"source_id": sid, "alias": aliases.get(sid, sid),
                 "gold": sid == gold_src, "n_hits": n_hits.get(sid, 0),
                 "best_full_score": best_full.score if best_full else None}
        if best_full is not None:
            row = next(r for r in chunk_rows
                       if r[0] == best_full.build_id and r[1] == best_full.chunk_id)
            build_id, chunk_id, kind, _stext, full_arr, unit_refs = row
            full_set = set(full_arr)
            body_text = "\n".join(unit_text.get((build_id, u), "") for u in unit_refs)
            prefix_text = "\n".join(
                unit_prefix(unit_labels.get((build_id, u), [])) for u in unit_refs)
            with psycopg.connect(dsn, autocommit=True) as c0:
                body_arr = c0.execute(
                    "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                    (body_text,)).fetchone()[0]
                label_arr = c0.execute(
                    "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                    (prefix_text,)).fetchone()[0]
                body_rank = c0.execute(
                    "SELECT ts_rank(to_tsvector('zhcfg', %s), "
                    "(SELECT websearch_to_tsquery('zhcfg', %s)))",
                    (body_text, orq)).fetchone()[0]
            qset = set(q_lexemes)
            full_m = sorted(full_set & qset)
            body_m = sorted(set(body_arr) & qset & full_set)
            label_only = sorted((set(label_arr) & qset & full_set) - set(body_arr))
            residual = sorted((full_set & qset) - set(body_arr) - set(label_arr))
            if residual:
                residual_chunks += 1
            entry["best_chunk"] = {
                "chunk_id": chunk_id, "kind": kind,
                "full_score": best_full.score, "body_only_score": body_rank,
                "matched_lexemes": full_m,
                "matched_body_lexemes": body_m,
                "matched_label_only_lexemes": label_only,
                "unattributed_lexemes": residual}
        per_source.append(entry)

    # ── 4. 反事实：body-only 重排（company-003 候选池）────────────────
    with psycopg.connect(dsn) as conn:  # 单事务承载 TEMP TABLE（会话级，断连消散）
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TEMP TABLE tmp_body (build_id text, chunk_id text, "
                "source_id text, body text, body_tsv tsvector) ON COMMIT DROP")
            batch: list[tuple] = []
            for build_id, chunk_id, kind, _stext, _full, unit_refs in chunk_rows:
                body_text = "\n".join(unit_text.get((build_id, u), "") for u in unit_refs)
                batch.append((build_id, chunk_id, build_to_src[build_id],
                              body_text, body_text))
                if len(batch) >= 200:
                    cur.executemany(
                        "INSERT INTO tmp_body VALUES (%s,%s,%s,%s,to_tsvector('zhcfg',%s))",
                        batch)
                    batch = []
            if batch:
                cur.executemany(
                    "INSERT INTO tmp_body VALUES (%s,%s,%s,%s,to_tsvector('zhcfg',%s))",
                    batch)
            cur.execute(
                "SELECT source_id, ts_rank(body_tsv, q.tsq) AS score "
                "FROM tmp_body, (SELECT websearch_to_tsquery('zhcfg', %s) AS tsq) q "
                "WHERE body_tsv @@ q.tsq ORDER BY score DESC, build_id, chunk_id",
                (orq,))
            body_rows = cur.fetchall()
    body_order = doc_order(body_rows)
    gold_rank_body = body_order.index(gold_src) + 1 if gold_src in body_order else None
    hypothesis_supported = bool(gold_rank_body and gold_rank_body <= 5)

    # ── 5. 扰动面：24 有答案题 doc top-5（full vs body-only）──────────
    positives = [q for q in questions if q.answer_existence is not AnswerExistence.NO_ANSWER]
    per_question = []
    with psycopg.connect(dsn) as conn:
        with conn.cursor() as cur:
            cur.execute(
                "CREATE TEMP TABLE tmp_body (build_id text, chunk_id text, "
                "source_id text, body text, body_tsv tsvector) ON COMMIT DROP")
            batch = []
            for build_id, chunk_id, kind, _stext, _full, unit_refs in chunk_rows:
                body_text = "\n".join(unit_text.get((build_id, u), "") for u in unit_refs)
                batch.append((build_id, chunk_id, build_to_src[build_id],
                              body_text, body_text))
                if len(batch) >= 200:
                    cur.executemany(
                        "INSERT INTO tmp_body VALUES (%s,%s,%s,%s,to_tsvector('zhcfg',%s))",
                        batch)
                    batch = []
            if batch:
                cur.executemany(
                    "INSERT INTO tmp_body VALUES (%s,%s,%s,%s,to_tsvector('zhcfg',%s))",
                    batch)
            for q in positives:
                orq_q = or_query(cur, q)
                hits_q, _co, _cv = read_pg.search_with_coverage_bands(
                    dsn, orq_q, limit=LIMIT, sandbox_db="i2_sandbox_corpus")
                top5_full = [aliases.get(s, s) for s in doc_order(hits_q)[:5]]
                cur.execute(
                    "SELECT source_id, ts_rank(body_tsv, q.tsq) AS score "
                    "FROM tmp_body, (SELECT websearch_to_tsquery('zhcfg', %s) AS tsq) q "
                    "WHERE body_tsv @@ q.tsq ORDER BY score DESC, build_id, chunk_id",
                    (orq_q,))
                top5_body = [aliases.get(s, s) for s in doc_order(cur.fetchall())[:5]]
                per_question.append({
                    "query_id": q.query_id,
                    "top5_full": top5_full,
                    "top5_body": top5_body,
                    "changed": set(top5_full) != set(top5_body)})

    # S1 复现：6 目标引文在金标命中块文本内（f2 桶前提）
    gold_hit_texts = [next(r[3] for r in chunk_rows
                           if r[0] == h.build_id and r[1] == h.chunk_id)
                      for h in hits_by_source.get(gold_src, [])[:20]]
    s1_flags = {}
    for t in q003.evidence_targets:
        quote = norm_ws(t.quote)
        s1_flags[t.target_id] = any(quote in norm_ws(txt) for txt in gold_hit_texts)

    targets = [{"target_id": t.target_id, "locator": list(t.locator),
                "source_id": t.source_id, "quote_head": t.quote[:40],
                "s1_reproduced": s1_flags[t.target_id]}
               for t in q003.evidence_targets]

    # ── 断言（红-可捕获）───────────────────────────────────────────────
    assert len(q003.evidence_targets) == 6, "company-003 目标数漂移"
    assert gold_rank is not None and gold_rank > 5, \
        f"金标 doc 词法 rank={gold_rank}（预期 >5，掉出 top-5）"
    assert gold_excluded, "产品选择含金标 doc（与 f2 桶矛盾）"
    assert all(s1_flags.values()), f"S1 复现失败: {s1_flags}"

    changed_n = sum(1 for r in per_question if r["changed"])
    summary = {
        "artifact": "c3-attribution",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": "i2_sandbox_corpus active publications",
        "mode": "只读机读归因（0 model calls；SELECT + 会话级 TEMP TABLE，corpus schema 零写入）",
        "issue": ".scratch/corpus-retrieval-decoupling/issues/10-company003-doc-recall.md",
        "query": {"query_id": "company-003", "question": q003.question,
                  "or_query": orq, "lexemes": list(q_lexemes)},
        "gold": {"alias": gold_alias, "source_id": gold_src, "build_id": gold_build},
        "targets": targets,
        "lexical_ranking": rank_table,
        "gold_lexical_rank": gold_rank,
        "production_selection": {"selected_sources": [aliases.get(s, s) for s in sel_sources],
                                 "gold_excluded": gold_excluded},
        "decomposition": {"per_source": per_source,
                          "unattributed_chunks": residual_chunks,
                          "note": ("label_only = search_tsv 命中 − raw_text body 命中；"
                                   "注入串按产品 _table_row_label_prefix 重建")},
        "counterfactual_body_only": {
            "company003_doc_order": [aliases.get(s, s) for s in body_order],
            "gold_rank_body": gold_rank_body,
            "gold_in_top5_body": hypothesis_supported,
            "hypothesis_supported": hypothesis_supported},
        "perturbation_surface": {
            "positives": len(positives),
            "top5_changed": changed_n,
            "per_question": per_question,
            "negatives_note": "6 负例产品路径走判定层拒检（NO_MATCH），不受排序反事实影响",
            "s2_lesson": "单层 top5 扰动不得单独下结论，须以端到端 EvidencePass 复验"},
        "self_check": {
            "no_model_calls": True,
            "read_only": True,
            "targets_is_6": len(q003.evidence_targets) == 6,
            "s1_all_reproduced": all(s1_flags.values()),
            "production_excludes_gold": gold_excluded,
            "gold_lexical_rank": gold_rank,
            "gold_rank_body": gold_rank_body,
            "hypothesis_supported": hypothesis_supported,
            "unattributed_chunks": residual_chunks},
    }
    write_once("c3-attribution.json", summary, dry_run=dry_run)
    print(json.dumps({k: summary[k] for k in
                      ("gold_lexical_rank", "counterfactual_body_only",
                       "perturbation_surface", "self_check")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
