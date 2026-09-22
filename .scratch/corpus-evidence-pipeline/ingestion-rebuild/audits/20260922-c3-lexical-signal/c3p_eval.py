"""c′ 排序信号侧（查询词元口径）只读离线评估（0 model calls，只读 PG，不落库、不改产品字节）。

议题：company-003 金标文档词法 rank 6 掉出 top-5。机制根因（2026-09-22 查证）：
文档名次由**最高分块**决定，而 ts_rank（norm=0）主要计"命中词元个数"；题面 24 词元里
8 个是虚词/标点 ⇒ 无关正文块（命中多、含虚词）压过真正答题的财务预测表块（命中少、
全实词）。据此提出候选路径 c′：**查询侧收紧词元口径**（去功能词 / 去单字 / 去疑问词）。

本脚本只做**离线 A/B/C/D 对照**，不修改任何产品字节：唯一变量是送给产品读链的
or_query 词元集合，其余（检索、选择、band 聚合、评分）逐行复用 f3b 回放主体。

arms（词元口径由粗到紧，判据全部来自产品既有非金标词表）：
- base          : 全 zhcfg 词元 OR（= 现生产/回测口径，基线）
- minus_function: 去 `_FUNCTION_WORDS`（保留单字）
- content       : `content_lexemes`（去功能词 + 去单字）—— c′ 主变体
- abstain       : `abstain_content_lexemes`（再剔 `_QUESTION_WORDS`）—— 诊断档
                  （预期会伤：24 有答案题中 23 条含疑问词）

端到端判据（S2 教训：不得用单层指标下结论）：
1. 82 目标三桶：matched / selected_but_match_fail / not_selected（逐层 Δ 相对 base）；
2. EvidencePass（24 有答案题，i33 calibration-plan-v2 政策）；
3. 负例：主口径（判定层拒检 NO_MATCH，与 F2/F4/f3b 同）+ **真检索诊断**（关闭拒检，
   只看词元收紧后是否把负例文档召回得更多 —— 不得比 base 差，红线）；
4. 选择集 SelectedBand 是否变化、带宽上界 ≤ 49；
5. company-003 专项：金标文档词法 rank / 是否进 top-5 / 6 目标 matched 数。

锚定：base arm 的文档必须与产品 `svc.search_bands` 逐字段相等（证明基线零漂移，
Δ 才可归因于词元口径）。

用法：`python c3p_eval.py [--no-write]`。产物 write-once（`c3p-eval.json`）。
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

# generated_at 是唯一非语义字段；write-once 按语义字段逐字段比较（同 c3_attribution.py）
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


def main() -> int:
    import psycopg

    from plugins.corpus.preparation import cross_boundary, read_pg
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.negative_query import (
        _FUNCTION_WORDS,
        abstain_content_lexemes,
        content_lexemes,
    )
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

    # gold 别名 → 活动 source（与 f2/f3b/c3 同口径）
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

    def doc_order(rows) -> list[str]:
        """distinct-source 首现序（= selection 文档序）。"""
        seen: list[str] = []
        for r in rows:
            if r.source_id not in seen:
                seen.append(r.source_id)
        return seen

    def run_bands(query: str):
        """svc.search_bands 主体逐行拷贝（产物 stitch_continuation=True = 产品默认），
        附带返回 raw_hits 以计算词法文档序（c3 同口径）。"""
        raw_hits, chunk_order, _coverage = read_pg.search_with_coverage_bands(
            dsn, query, limit=LIMIT, sandbox_db="i2_sandbox_corpus")
        bands = svc._apply_selection_bands(raw_hits, chunk_order, LIMIT)
        chunk_evs = read_pg.fetch_bands(dsn, bands, chunk_order, sandbox_db="i2_sandbox_corpus")
        chunk_evs = cross_boundary.aggregate_band_chunks(
            dsn, chunk_evs, sandbox_db="i2_sandbox_corpus", stitch_continuation=True)
        docs = svc._assemble_band_documents(bands, chunk_evs, chunk_order)
        return docs, doc_order(raw_hits)

    def arms_for(lexemes: list[str]) -> dict[str, tuple[str, ...]]:
        return {
            "base": tuple(lexemes),
            "minus_function": tuple(t for t in lexemes if t not in _FUNCTION_WORDS),
            "content": tuple(content_lexemes(lexemes)),
            "abstain": tuple(abstain_content_lexemes(lexemes)),
        }

    def or_query(cur, q) -> tuple[str, list[str], dict[str, tuple[str, ...]]]:
        lexemes = cur.execute(
            "SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
            (normalize_search_text(q.question),)).fetchone()[0]
        arms = arms_for(lexemes)
        full = " OR ".join('"' + t.replace('"', " ") + '"' for t in lexemes)
        return full, lexemes, arms

    positives = [q for q in questions if q.answer_existence is not AnswerExistence.NO_ANSWER]
    negatives = [q for q in questions if q.answer_existence is AnswerExistence.NO_ANSWER]
    ARM_ORDER = ("base", "minus_function", "content", "abstain")
    obs: dict[str, dict[str, QueryObservation]] = {a: {} for a in ARM_ORDER}
    docs_by_arm: dict[str, dict[str, list]] = {a: {} for a in ARM_ORDER}
    empty_arms: dict[str, list[str]] = {a: [] for a in ARM_ORDER}
    rank_by_arm: dict[str, dict[str, int | None]] = {a: {} for a in ARM_ORDER}

    with psycopg.connect(dsn, autocommit=True) as c0:
        q_arms: dict[str, dict[str, tuple[str, ...]]] = {}
        for q in positives:
            _full, _lex, arms = or_query(c0, q)
            q_arms[q.query_id] = arms

    for arm in ARM_ORDER:
        with psycopg.connect(dsn, autocommit=True) as c0:
            for q in positives:
                lexemes = q_arms[q.query_id][arm]
                if not lexemes:
                    empty_arms[arm].append(q.query_id)
                    obs[arm][q.query_id] = QueryObservation(
                        q.query_id, ObservationOutcome.NO_MATCH, ())
                    docs_by_arm[arm][q.query_id] = []
                    rank_by_arm[arm][q.query_id] = None
                    continue
                qs = " OR ".join('"' + t.replace('"', " ") + '"' for t in lexemes)
                docs, order = run_bands(qs)
                docs_by_arm[arm][q.query_id] = docs
                obs[arm][q.query_id] = observation_for_docs(q.query_id, docs)
                sel_aliases = [aliases.get(d.source_id, d.source_id) for d in docs]
                golds = [a for a in sorted(q.relevant_sources) if a in sel_aliases]
                rank_by_arm[arm][q.query_id] = (
                    sel_aliases.index(golds[0]) + 1) if golds else None
            # 负例：主口径构造 NO_MATCH（判定层拒检，与 F2/F4/f3b 同）
            for q in negatives:
                obs[arm][q.query_id] = QueryObservation(
                    q.query_id, ObservationOutcome.NO_MATCH, ())

    # ── 锚定：base arm 必须等于产品 svc.search_bands（证明基线零漂移）──────────
    product_mismatches: list[str] = []
    with psycopg.connect(dsn, autocommit=True) as c0:
        for q in positives:
            _full, _lex, arms = or_query(c0, q)
            prod_docs, _cov = svc.search_bands(
                " OR ".join('"' + t.replace('"', " ") + '"' for t in arms["base"]), limit=LIMIT)
            if prod_docs != docs_by_arm["base"][q.query_id]:
                product_mismatches.append(q.query_id)

    # ── 负例真检索诊断（关闭拒检，只看词元收紧后召回是否变多）───────────────
    neg_real: dict[str, dict[str, int]] = {}
    for arm in ARM_ORDER:
        neg_real[arm] = {}
        with psycopg.connect(dsn, autocommit=True) as c0:
            for q in negatives:
                _full, _lex, arms = or_query(c0, q)
                lexemes = arms[arm]
                if not lexemes:
                    neg_real[arm][q.query_id] = 0
                    continue
                qs = " OR ".join('"' + t.replace('"', " ") + '"' for t in lexemes)
                docs, _order = run_bands(qs)
                neg_real[arm][q.query_id] = len(docs)

    def matched_map(arm_obs: dict) -> dict[tuple[str, str], bool]:
        m: dict[tuple[str, str], bool] = {}
        for q in positives:
            o = arm_obs[q.query_id]
            for t in q.evidence_targets:
                m[(q.query_id, t.target_id)] = any(
                    t.matches(ev) for doc in o.documents for ev in doc.evidence)
        return m

    def buckets(arm_obs: dict) -> dict[str, int]:
        """82 目标三桶：matched / selected_but_match_fail / not_selected（S2 未进）。"""
        b = {"matched": 0, "selected_but_match_fail": 0, "not_selected": 0}
        for q in positives:
            o = arm_obs[q.query_id]
            sel = {aliases.get(d.source_id, d.source_id) for d in o.documents}
            gold_in = bool(sel & set(q.relevant_sources))
            for t in q.evidence_targets:
                hit = any(t.matches(ev) for doc in o.documents for ev in doc.evidence)
                if hit:
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
    sel_changed = {a: [q.query_id for q in positives
                       if bands_sig(docs_by_arm["base"][q.query_id]) !=
                       bands_sig(docs_by_arm[a][q.query_id])] for a in ARM_ORDER}
    widths = {a: max_width(docs_by_arm[a]) for a in ARM_ORDER}

    diff = {
        a: {
            "regressed": sorted(f"{k[0]}/{k[1]}" for k in mats["base"]
                                if mats["base"][k] and not mats[a][k]),
            "newly_matched": sorted(f"{k[0]}/{k[1]}" for k in mats[a]
                                    if mats[a][k] and not mats["base"][k]),
        } for a in ARM_ORDER}

    # company-003 专项
    q003 = next(q for q in questions if q.query_id == "company-003")
    gold_alias003 = next(iter(q003.relevant_sources))
    c3 = {}
    for a in ARM_ORDER:
        o = obs[a]["company-003"]
        sel = [aliases.get(d.source_id, d.source_id) for d in o.documents]
        c3[a] = {
            "gold_selected": gold_alias003 in sel,
            "gold_position_in_selection": (sel.index(gold_alias003) + 1)
            if gold_alias003 in sel else None,
            "selected_aliases": sel,
            "targets_matched": sum(
                1 for t in q003.evidence_targets
                if any(t.matches(ev) for doc in o.documents for ev in doc.evidence)),
            "targets_total": len(q003.evidence_targets),
            "lexemes_n": len(q_arms["company-003"][a]),
        }

    # ── 硬判据（红-可捕获）────────────────────────────────────────────────
    if product_mismatches:
        raise RuntimeError(f"base 臂与产品路径不一致（基线漂移，Δ 不可信）: {product_mismatches}")
    for a in ARM_ORDER:
        if a == "base":
            continue
        worse = {k: v for k, v in neg_real[a].items()
                 if v > neg_real["base"].get(k, 0)}
        if worse:
            raise RuntimeError(f"负例真检索召回回升（红线）: arm={a} {worse}")
    for a in ARM_ORDER:
        if widths[a] > 49:
            raise RuntimeError(f"带宽超上界: arm={a} width={widths[a]}")

    summary = {
        "artifact": "c3p-eval",
        "generated_at": __import__("datetime").datetime.now(
            __import__("datetime").timezone.utc).astimezone().isoformat(timespec="seconds"),
        "corpus": "i2_sandbox_corpus active publications",
        "mode": ("c′ 查询词元口径 A/B/C/D 离线评估（0 model calls；只读 PG，corpus schema "
                 "零写入；不改任何产品字节）"),
        "single_variable": "送给产品读链的 or_query 词元集合（其余逐行复用 f3b 回放主体）",
        "arms": {
            "base": "全 zhcfg 词元 OR（现生产/回测口径，基线）",
            "minus_function": "去 _FUNCTION_WORDS（保留单字）",
            "content": "content_lexemes：去功能词 + 去单字（c′ 主变体）",
            "abstain": "abstain_content_lexemes：再剔 _QUESTION_WORDS（诊断档）",
        },
        "lexeme_source": ("判据全部取自产品既有非金标词表 "
                          "plugins/corpus/preparation/negative_query.py"),
        "anchor_base_equals_product": not product_mismatches,
        "per_arm": {
            a: {
                "evidence_pass": f"{ep[a]}/24",
                "buckets_82_targets": bks[a],
                "targets_matched": sum(1 for v in mats[a].values() if v),
                "diff_vs_base": diff[a],
                "selection_changed_vs_base": sel_changed[a],
                "band_width_max": widths[a],
                "empty_query_questions": empty_arms[a],
            } for a in ARM_ORDER},
        "delta_vs_base": {
            a: {
                "evidence_pass": ep[a] - ep["base"],
                "matched": bks[a]["matched"] - bks["base"]["matched"],
                "selected_but_match_fail": (bks[a]["selected_but_match_fail"]
                                            - bks["base"]["selected_but_match_fail"]),
                "not_selected": bks[a]["not_selected"] - bks["base"]["not_selected"],
            } for a in ARM_ORDER},
        "negatives": {
            "main_path_retrieved": {a: {q.query_id: len(obs[a][q.query_id].documents)
                                        for q in negatives} for a in ARM_ORDER},
            "real_search_diagnostic": neg_real,
            "note": ("main_path = 判定层拒检 NO_MATCH（与 F2/F4/f3b 同口径）；"
                     "real_search = 关闭拒检真跑，仅用于量词元收紧的误报风险（不得高于 base）"),
        },
        "company003": c3,
        "s2_lesson": "单层 rank/top5 变化不得单独下结论；本评估以 82 目标三桶 + EvidencePass 为准",
    }
    write_once("c3p-eval.json", summary, dry_run=dry_run)
    print(json.dumps({k: summary[k] for k in
                      ("anchor_base_equals_product", "per_arm", "delta_vs_base",
                       "company003", "negatives")},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
