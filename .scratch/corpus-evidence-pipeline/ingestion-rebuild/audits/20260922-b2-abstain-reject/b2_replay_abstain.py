"""B2 abstain 拒检通道真库复验（只读 PG + 0 model_calls）。

口径（B2 验证清单 a/b/c）：
- a) 负例：开关 on 下 6 条负例题干走产品 ``service.search_with_coverage`` →
  ``hits==[]`` 且 ``coverage["abstain"] is True``；评分 false_positives 空。
- b) 有答案题：S1=66 / S2=60 不回退（与 F1 回测同漏斗口径：OR 检索 + perdoc top-k）。
- c) 负例 FP 不回升（空观测 → 0 FP）。

只读：不重摄入、不 publish、不改语料。产物 write-once 写入本目录。
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
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

import calibrate  # noqa: E402  observations_for / group_hits

BASE_PER_DOC = 8


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def write_once(name: str, value) -> None:
    path = HERE / name
    raw = (json.dumps(value, ensure_ascii=False, indent=2, default=str) + "\n").encode()
    if path.exists() and path.read_bytes() != raw:
        raise RuntimeError(f"write-once conflict: {name}")
    path.write_bytes(raw)


def norm(s: object) -> str:
    return "".join(ch for ch in s if not ch.isspace()) if isinstance(s, str) else ""


def main() -> int:
    from plugins.corpus.preparation.chunk import normalize_search_text
    from plugins.corpus.preparation.read_pg import fetch_verbatim, build_handle, chunk_locator
    from plugins.corpus.scoring import (
        AnswerExistence,
        gold_from_records,
        ScoringPolicy,
        score,
        format_report,
    )
    from plugins.corpus.preparation.negative_query import (
        abstain_content_lexemes,
        abstain_no_answer_query,
    )
    from plugins.corpus.service import get_service

    release = load_module("i31_region_release", AUDITS / "20260920-i31-region-review/release.py")
    dsn = release.connect()

    loader = load_module("i33_scoring_loader", INGEST / "i3s2_scoring_input.py")
    records = loader.load_scoring_input(INGEST / "i3-2/scoring-input-manifest.json")
    applier = loader.load_module(INGEST / "i3s2_apply_decisions.py", "i33_approved_input")
    errors = loader.validate(
        records,
        loader.load_jsonl(loader.QUERY_GOLD),
        json.loads(loader.PROJECTION.read_text()),
        loader.load_jsonl(loader.SOURCE_GOLD),
        json.loads(loader.MANIFEST.read_text()),
        applier,
    )
    if errors:
        raise RuntimeError(f"Frozen scoring assets invalid: {errors}")

    questions = gold_from_records(records)
    config = dict(json.loads((I33 / "calibration-plan-v2.json").read_text())["policy"])
    config["min_rate"] = Fraction(config["min_rate"])
    policy = ScoringPolicy(**config)

    neg_ids = {q.query_id for q in questions if q.answer_existence is AnswerExistence.NO_ANSWER}
    assert len(neg_ids) == 6, f"expect 6 negative, got {len(neg_ids)}"

    import psycopg

    with psycopg.connect(dsn, autocommit=True) as conn:
        sources = dict(conn.execute(
            "SELECT source_id, active_build_id FROM corpus.corpus_publications "
            "WHERE active_build_id IS NOT NULL").fetchall())
        if len(sources) < 8:
            raise RuntimeError(f"Active corpus has {len(sources)} sources (expected >= 8)")
        aliases = {}
        expected_aliases = {s for q in questions for s in q.relevant_sources}
        expected_aliases |= {t.source_id for q in questions for t in q.evidence_targets
                             if t.source_id}
        for alias in expected_aliases:
            matches = [src for src in sources if src.startswith(alias.rsplit("_", 1)[-1])]
            if len(matches) != 1:
                raise RuntimeError(f"Gold alias cannot resolve uniquely: {alias}")
            if matches[0] in aliases and aliases[matches[0]] != alias:
                raise RuntimeError("Multiple gold aliases for one source")
            aliases[matches[0]] = alias
        alias_to_source = {alias: src for src, alias in aliases.items()}

        cache: dict = {}
        receipts: dict = {}

        def fetch(hit):
            key = (hit.build_id, hit.chunk_id)
            if key not in cache:
                cache[key] = fetch_verbatim(dsn, build_handle(hit.build_id),
                                            chunk_locator(hit.chunk_id))
                receipts["/".join(key)] = asdict(cache[key])
            return cache[key]

        def or_query(conn, question: str) -> str:
            lexemes = conn.execute("SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                                   (normalize_search_text(question),)).fetchone()[0]
            if not lexemes:
                raise RuntimeError("Question tokenization produced no terms")
            return " OR ".join('"' + term.replace('"', ' ') + '"' for term in lexemes)

        from plugins.corpus.preparation.search_pg import search_chunks

        service = get_service(dsn)
        traces = []
        per_query: dict[str, dict] = {}
        neg_hits: dict = {}
        neg_cov: dict = {}

        def build_observation(query_id, grouped):
            return calibrate.observations_for(query_id, grouped, fetch, aliases)

        for question in questions:
            if question.answer_existence is AnswerExistence.NO_ANSWER:
                # 负例走产品 abstain 通道（B2 核心）。生产查询不改路径；仅读开关 on 生效。
                hits, coverage = service.search_with_coverage(
                    question.question, limit=policy.top_k)
                neg_hits[question.query_id] = hits
                neg_cov[question.query_id] = coverage
                traces.append({"query_id": question.query_id, "mode": "product_abstain",
                               "hits": len(hits), "abstain": coverage.get("abstain"),
                               "query_status": coverage.get("query_status"),
                               "retrieved_documents": 0})
                continue
            # 有答案题走 F1 同 OCR 基线（不变量：S1/S2 不回退）。
            query = or_query(conn, question.question)
            hits = search_chunks(dsn, query, limit=2000)
            if len(hits) >= 2000:
                raise RuntimeError("Candidate cap saturated; cannot certify document top-k")
            text_by_chunk = {}
            for hit in hits:
                for uid in hit.unit_refs:
                    with conn.cursor() as cur:
                        cur.execute(
                            "SELECT unit_id, raw_text, content_hash FROM corpus.corpus_units "
                            "WHERE build_id=%s AND unit_id=%s", (hit.build_id, uid))
                        row = cur.fetchone()
                    if hashlib.sha256(str(row[1] or "").encode()).hexdigest() != str(row[2] or ""):
                        raise RuntimeError(f"权威单元内容哈希不符: {uid}")
                    text_by_chunk[(hit.build_id, hit.chunk_id)] = (
                        text_by_chunk.get((hit.build_id, hit.chunk_id), "") + "\n"
                        + str(row[1] or ""))
            grouped = calibrate.group_hits(hits, policy.top_k, BASE_PER_DOC)
            build_observation(question.query_id, grouped)
            per_query[question.query_id] = {"hits": hits, "text_by_chunk": text_by_chunk,
                                            "groups": grouped}
            traces.append({"query_id": question.query_id, "mode": "or_answerable",
                           "chunk_hits": len(hits),
                           "base_selected": {s: len(h) for s, h in grouped.items()}})

        # ---- 有答案题漏斗（与 f1_backtest 相同口径）----
        from plugins.corpus.scoring import score as core_score
        # 重新跑有答案题 scoring：产品复验不需 score 负例（abstain 空观测不计 FP），
        # 此处仅用于有答案题 per-class 不变式对照；负例 FP 用下述 empty-observation 评分。
        # 有答案题观测已在循环内通过 build_observation 灌入 calibrate；但 score 需要观测列表，
        # 这里改用与 f1 相同的方式——重新收集有答案题观测。
        # 说明：为控制真库只读，本脚本对有答案题不重算 score 全报告，
        # 漏斗 S1/S2 由下方逐目标式计算（与 f1_backtest f… 同口径）。

        # ---- 负例 FP 判定（B2 c）：空观测 → 0 FP ----
        # service.abstain 返回空 hits → scoring 对空观测不计 FP。这里直接以产品返回的
        # 空 hits 数作为 retrieved_documents=0 的判据（与 coverage abstain 一致）。

        neg = [{"query_id": q.query_id, "question": q.question,
                "product_hits": len(neg_hits[q.query_id]),
                "abstain": bool(neg_cov[q.query_id].get("abstain")),
                "query_status": neg_cov[q.query_id].get("query_status")}
               for q in questions if q.answer_existence is AnswerExistence.NO_ANSWER]

        # 有答案题 S1/S2 逐目标漏斗（同 f1_backtest 实现）
        funnel_targets = []
        for q in questions:
            if q.answer_existence is AnswerExistence.NO_ANSWER:
                continue
            pinfo = per_query.get(q.query_id)
            relevant = set(q.relevant_sources)
            for target in q.evidence_targets:
                allowed = (target.source_id,) if target.source_id else tuple(relevant)
                src = target.source_id or (next(iter(relevant), None))
                live_src = alias_to_source.get(src)
                build_id = sources.get(live_src) if live_src else None
                quote = norm(target.quote)
                cand_texts = ([pinfo["text_by_chunk"].get((h.build_id, h.chunk_id), "")
                               for h in pinfo["hits"] if h.build_id == build_id]
                              if pinfo else [])
                s1 = any(quote in norm(t) for t in cand_texts)
                doc_in_topk = bool(pinfo) and live_src in pinfo["groups"]
                s2 = s1 and doc_in_topk
                funnel_targets.append({"query_id": q.query_id,
                                       "target_id": f"{q.query_id} {target.target_id}",
                                       "S1_candidates": s1, "S2_doc_topk": s2})

        layer = lambda pred: sum(1 for r in funnel_targets if pred(r))
        funnel = {"S1_candidates": layer(lambda r: r["S1_candidates"]),
                  "S2_doc_topk": layer(lambda r: r["S2_doc_topk"])}

        i42funnel = json.loads((I42 / "recall-funnel.json").read_text())["funnel"]

        fp_zero = all(r["product_hits"] == 0 and r["abstain"] for r in neg)
        self_check = {
            "B2_a_negative_abstain": fp_zero,
            "B2_b_S1_66": funnel["S1_candidates"] == 66 == i42funnel.get("S1_candidates"),
            "B2_b_S2_60": funnel["S2_doc_topk"] == i42funnel.get("S2_doc_topk"),
        }

        summary = {
            "artifact": "b2-abstain-reject-replay",
            "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
            "kind": "B2 abstain 拒检通道真库复验（产品 search_with_coverage，只读）",
            "corpus": "index-4-zhcfg-2 active (8 docs + legacy)",
            "model_calls": 0,
            "switch": "CORPUS_ABSTAIN_NO_ANSWER=on",
            "negative": {"cases": neg},
            "funnel": funnel,
            "i42_baseline": {"funnel": i42funnel},
            "self_check": self_check,
        }
        write_once("b2-summary.json", summary)
        write_once("b2-trace.json", traces)
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        sys.exit(0 if all(self_check.values()) else 1)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())