"""c′ 第二半：实词加权 / 虚词-标点降权的只读离线评估（0 model calls，只读 PG，不落库、不改产品字节）。

C 方案原文：「查询侧剔除虚词/标点词元，**或**给实词（年度列、公司名、指标名）加权」。
前一半（剔除）已在 `audits/20260922-c3-lexical-signal/` 评估（minus_function 有效、去单字有害）。
本脚本评估后一半：**不删词，只给内容词/功能词/标点不同权重**。

为什么不能直接用 PG 的权重语法：写侧 `to_tsvector('zhcfg', search_text)` **未 setweight**
⇒ 所有词元同权重类，`ts_rank(weights, …)` 与 `tsquery` 的 `:A/:B` 标记均无区分效果。
因此在**排序调用侧**用"双 tsquery 线性加权和"实现（不改索引、不改产品字节）：

    score = w_c * ts_rank(search_tsv, tsq_content) + w_f * ts_rank(search_tsv, tsq_function)

单变量 = (content 词元集合, function 词元集合, w_f)。候选池固定为产品 base 池
（全词元 OR、`limit=2000`），只重排 hits 的 score ⇒ 与产品唯一差异就是排序信号；
`chunk_order` 是"来源全量原文序"（与命中顺序无关），故不受重排影响、无需重建。

arms（w_c 恒为 1.0）：
- anchor          : content=全词元、function=∅ ⇒ 退化成 base（**锚定**：须等于产品 svc.search_bands）
- prune_fn        : content=去 `_FUNCTION_WORDS`（保留单字与标点），w_f=0（= 前一半 minus_function）
- prune_fn_punct  : content=再去**标点**词元（结构判定：词元内无字母/数字/汉字），w_f=0
- w0.2 / w0.5     : content=去功能词，function=功能词命中，w_f=0.2 / 0.5（不删词，只降权）
- prune_content   : `content_lexemes`（再剔单字），w_f=0 —— 对照档，预期回退（已知）

判据（S2 教训：只认端到端）：82 目标三桶 + EvidencePass(24) + 负例主口径/真检索诊断 + 带宽。
产物 write-once（c3w-eval.json）；`--no-write` 只跑不写。
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


def is_punct(token: str) -> bool:
    """标点词元的结构判定（非金标）：词元内不含任何字母/数字/汉字。"""
    return not any(ch.isalnum() for ch in token)


def main() -> int:
    import psycopg

    from plugins.corpus.preparation import cross_boundary, read_pg
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.negative_query import _FUNCTION_WORDS, content_lexemes
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

    svc = CorpusService(dsn)
    with psycopg.connect(dsn, autocommit=True) as conn:
        _check_target(conn, "i2_sandbox_corpus")
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())

    aliases: dict[str, str] = {}
    expected = {s for q in questions for s in q.relevant_sources}
    expected |= {t.source_id for q in questions for t in q.evidence_targets if t.source_id}
    for alias in expected:
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

    def arms(lexemes: list[str]) -> dict[str, tuple[tuple[str, ...], tuple[str, ...], float]]:
        fn = tuple(t for t in lexemes if t in _FUNCTION_WORDS)
        pu = tuple(t for t in lexemes if is_punct(t))
        keep_fn = tuple(t for t in lexemes if t not in _FUNCTION_WORDS)
        keep_fn_pu = tuple(t for t in keep_fn if not is_punct(t))
        cont = tuple(content_lexemes(lexemes))
        return {
            # name: (content_lexemes, function_lexemes, w_f)
            "anchor": (tuple(lexemes), (), 0.0),
            "prune_fn": (keep_fn, fn, 0.0),
            "prune_fn_punct": (keep_fn_pu, fn + pu, 0.0),
            "w0.2": (keep_fn, fn, 0.2),
            "w0.5": (keep_fn, fn, 0.5),
            "prune_content": (cont, tuple(t for t in lexemes if t not in cont), 0.0),
        }

    def run_weighted(base_query: str, content, function, w_f: float):
        """候选池 = 产品 base 池；只替换 score 后重排，再走产品选择/装配。"""
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
    ARM_ORDER = ("anchor", "prune_fn", "prune_fn_punct", "w0.2", "w0.5", "prune_content")

    # 每题：题面 → 词元 → 各 arm 的 (content, function, w_f)
    q_arms: dict[str, dict] = {}
    base_qs: dict[str, str] = {}
    with psycopg.connect(dsn, autocommit=True) as c0:
        for q in questions:
            lex = c0.execute(
                "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(q.question),)).fetchone()[0]
            q_arms[q.query_id] = arms(lex)
            base_qs[q.query_id] = or_str(lex)

    obs: dict[str, dict] = {a: {} for a in ARM_ORDER}
    docs_by_arm: dict[str, dict] = {a: {} for a in ARM_ORDER}
    for arm in ARM_ORDER:
        for q in positives:
            content, function, w_f = q_arms[q.query_id][arm]
            docs, _co, _sel = run_weighted(base_qs[q.query_id], content, function, w_f)
            docs_by_arm[arm][q.query_id] = docs
            obs[arm][q.query_id] = observation_for_docs(q.query_id, docs)
        for q in negatives:
            obs[arm][q.query_id] = QueryObservation(
                q.query_id, ObservationOutcome.NO_MATCH, ())

    # ── 锚定：anchor 臂必须等于产品 svc.search_bands（排序信号零改动 ⇒ 应逐字段相等）──
    mismatches: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as c0:
        for q in positives:
            prod, _cov = svc.search_bands(base_qs[q.query_id], limit=LIMIT)
            if prod != docs_by_arm["anchor"][q.query_id]:
                mismatches.append(q.query_id)

    # ── 负例真检索诊断（关闭拒检，量降权后是否把负例召回得更多）────────────
    neg_real: dict[str, dict[str, int]] = {}
    for arm in ARM_ORDER:
        neg_real[arm] = {}
        for q in negatives:
            content, function, w_f = q_arms[q.query_id][arm]
            docs, _co, _sel = run_weighted(base_qs[q.query_id], content, function, w_f)
            neg_real[arm][q.query_id] = len(docs)

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

    mats = {a: matched_map(obs[a]) for a in ARM_ORDER}
    bks = {a: buckets(obs[a]) for a in ARM_ORDER}
    reps = {a: score(questions, [obs[a][q.query_id] for q in questions], policy)
            for a in ARM_ORDER}
    ep = {a: sum(c.evidence_pass.passed for c in reps[a].classes) for a in ARM_ORDER}
    widths = {a: max_width(docs_by_arm[a]) for a in ARM_ORDER}
    sel_changed = {a: [q.query_id for q in positives
                       if bands_sig(docs_by_arm["anchor"][q.query_id]) !=
                       bands_sig(docs_by_arm[a][q.query_id])] for a in ARM_ORDER}
    diff = {a: {
        "regressed": sorted(f"{k[0]}/{k[1]}" for k in mats["anchor"]
                            if mats["anchor"][k] and not mats[a][k]),
        "newly_matched": sorted(f"{k[0]}/{k[1]}" for k in mats[a]
                                if mats[a][k] and not mats["anchor"][k]),
    } for a in ARM_ORDER}

    q003 = next(q for q in questions if q.query_id == "company-003")
    g003 = next(iter(q003.relevant_sources))
    c3 = {}
    for a in ARM_ORDER:
        o = obs[a]["company-003"]
        sel = [aliases.get(d.source_id, d.source_id) for d in o.documents]
        content, function, w_f = q_arms["company-003"][a]
        c3[a] = {"content_n": len(content), "function_n": len(function), "w_f": w_f,
                 "gold_selected": g003 in sel,
                 "gold_position": (sel.index(g003) + 1) if g003 in sel else None,
                 "targets_matched": sum(
                     1 for t in q003.evidence_targets
                     if any(t.matches(ev) for doc in o.documents for ev in doc.evidence))}

    # ── 硬判据（红-可捕获）──────────────────────────────────────────────
    if mismatches:
        raise RuntimeError(f"anchor 臂与产品路径不一致（基线漂移）: {mismatches}")
    for a in ARM_ORDER:
        worse = {k: v for k, v in neg_real[a].items() if v > neg_real["anchor"].get(k, 0)}
        if worse:
            raise RuntimeError(f"负例真检索召回回升（红线）: arm={a} {worse}")
        if widths[a] > 49:
            raise RuntimeError(f"带宽超上界: arm={a} width={widths[a]}")

    summary = {
        "artifact": "c3w-eval",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": "i2_sandbox_corpus active publications",
        "mode": ("c′ 第二半：实词加权 / 虚词标点降权 只读离线评估（0 model calls、只读 PG、"
                 "corpus schema 零写入、不改产品字节）"),
        "scoring_formula": "score = 1.0*ts_rank(tsv, tsq_content) + w_f*ts_rank(tsv, tsq_function)",
        "why_not_pg_weights": ("写侧 to_tsvector 未 setweight ⇒ 词元同权重类，ts_rank(weights,…) "
                               "与 tsquery 的 :A/:B 标记无区分效果，故在排序调用侧用双 tsquery 加权和"),
        "single_variable": "(content 词元集合, function 词元集合, w_f)；候选池固定为产品 base 池",
        "anchor_equals_product": not mismatches,
        "arms": {
            "anchor": "content=全词元、function=∅（退化成 base，锚定档）",
            "prune_fn": "content=去 _FUNCTION_WORDS（保留单字与标点）、w_f=0",
            "prune_fn_punct": "content=再去标点词元（结构判定）、w_f=0",
            "w0.2": "content=去功能词、function=功能词、w_f=0.2（不删词只降权）",
            "w0.5": "同上 w_f=0.5",
            "prune_content": "content_lexemes（再剔单字）、w_f=0（对照档，预期回退）",
        },
        "per_arm": {a: {
            "evidence_pass": f"{ep[a]}/24",
            "buckets_82_targets": bks[a],
            "targets_matched": sum(1 for v in mats[a].values() if v),
            "diff_vs_anchor": diff[a],
            "selection_changed_vs_anchor": len(sel_changed[a]),
            "band_width_max": widths[a],
        } for a in ARM_ORDER},
        "delta_vs_anchor": {a: {
            "evidence_pass": ep[a] - ep["anchor"],
            "matched": bks[a]["matched"] - bks["anchor"]["matched"],
            "not_selected": bks[a]["not_selected"] - bks["anchor"]["not_selected"],
        } for a in ARM_ORDER},
        "negatives": {"real_search_diagnostic": neg_real,
                      "main_path_retrieved": {a: {q.query_id: len(obs[a][q.query_id].documents)
                                                  for q in negatives} for a in ARM_ORDER}},
        "company003": c3,
        "s2_lesson": "单层 rank/top5 变化不得单独下结论；本评估以 82 目标三桶 + EvidencePass 为准",
    }
    write_once("c3w-eval.json", summary, dry_run=dry_run)
    print(json.dumps({k: summary[k] for k in
                      ("anchor_equals_product", "per_arm", "delta_vs_anchor",
                       "company003", "negatives")}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
