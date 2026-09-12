"""D2 P5：语料库三类审计报告（d2-claims-design §4）。

**定位（§4 元层设计）**：``verify.py`` 的三条硬闸裁决的是**策略卡**，本模块裁决的是
**语料库**。两者**并列，不互相替代**——本报告不是硬闸裁决，输出里显式标注。

**只读现有表**（``documents`` / ``blocks`` / ``claims`` / ``claim_block_runs``），
不产 claim、不调 LLM；所有"判定类"逻辑与抽取链路**同口径复用**：

- 候选块判定 = ``claims_v2.triage_block_detail``，输出 numeric/rating/personal_trade/
  qualitative/noise/no_signal 原因码，便于看见评级、个人交易、定性观点召回与噪声过滤；
- 领域分类 = ``doc_kind_override`` 优先，否则 ``classify_doc_kind(title, texts)``
  （与 ``CorpusService.extract_claims`` 完全一致）；
- 文档级标的 = ``document_ticker``，仅 company 文档（同上）；
- 指标归一 = ``normalize_metric``（P3 别名表的直接消费者——别名表没覆盖的同义对
  会在这里以"命名分裂"浮出，这正是 P3 验收记录说的"不确定的对留给审计层"）。

**三档结论，退出码只认冲突**（§4：退出码非 0 表示发现冲突，可做 CI 门禁）：

- ``conflicts``：数据错误（备份漏列 / 跨块数值冲突 / company 文档 claim 无标的 /
  kind↔period 不自洽 / 数字无法溯源 / 死信）→ **退出码 1**；
- ``observations``：需要人工但不拦门禁（指标命名分裂——别名表按"确定同义"纪律
  随实测扩充，分裂清单就是扩充候选）；
- ``gaps``：运营缺口（候选块未抽完 / 失败可重试块）——跑批中间态天然非零，不拦。

**留痕（§11 缺口#6）**：每次审计追加一行 JSONL（默认
``data/corpus/.audit/audit_runs.jsonl``，``CORPUS_AUDIT_JSONL`` 覆盖），趋势
（"溯源率从 100% 退化到 95%"）靠它回答。ingest 只扫目录顶层，隐藏目录不会
被误当成文档。
"""

from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg
from psycopg.rows import dict_row

from plugins.corpus.claims import (
    DOC_KINDS,
    BlockView,
    classify_doc_kind,
    document_ticker,
    is_flat_table,
    normalize_metric,
)
from plugins.corpus.claims_v2 import (
    _value_in_evidence,
    classify_doc_kind_detail,
    triage_block_detail,
)

#: 死信判定：同一块累计失败次数达到该值即不再重试（与 CLI 默认 --max-attempts 一致）
DEAD_LETTER_ATTEMPTS = 3

#: 各类清单最多带多少条明细——审计报告要能整页看，明细超限时只给计数
DETAIL_LIMIT = 20

#: 报告头显式声明（§4：审计不重复实现硬闸逻辑，也不冒充硬闸）
DISCLAIMER = "本报告不是硬闸裁决：verify.py 裁决策略卡，本审计裁决语料库（d2-claims-design §4）。"

#: 留痕 JSONL 默认路径；``CORPUS_AUDIT_JSONL`` 覆盖；传空串禁用留痕
DEFAULT_JSONL = "data/corpus/.audit/audit_runs.jsonl"

_NUM_TOKEN_RE = re.compile(r"\d+(?:\.\d+)?")
_FORECAST_PERIOD_RE = re.compile(r"\d{4}E$")


# ── 数据装载（全部只读） ─────────────────────────────────────────
def _load_documents(
    conn: psycopg.Connection, doc_ids: Sequence[str] | None
) -> list[dict[str, Any]]:
    sql = (
        "SELECT doc_id, title, published, doc_kind_override, status FROM documents"
        + (" WHERE doc_id = ANY(%s)" if doc_ids else "")
        + " ORDER BY doc_id"
    )
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, (list(doc_ids),) if doc_ids else None)
        return [dict(r) for r in cur.fetchall()]


def _load_blocks(conn: psycopg.Connection) -> dict[str, list[BlockView]]:
    by_doc: dict[str, list[BlockView]] = defaultdict(list)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT doc_id, seq, locator, text FROM blocks ORDER BY doc_id, seq")
        for row in cur.fetchall():
            by_doc[str(row["doc_id"])].append(
                BlockView(int(row["seq"]), str(row["locator"]), str(row["text"] or ""))
            )
    return dict(by_doc)


def _load_claims(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT claim_id, doc_id, seq, kind, tickers, metric, value_text, value_num,"
            " period, as_of, claim_text FROM claims ORDER BY doc_id, seq, claim_id"
        )
        return [dict(r) for r in cur.fetchall()]


def _load_runs(conn: psycopg.Connection) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT doc_id, seq, status, claims_n, attempts, duration_ms, prompt_tokens,"
            " completion_tokens, error FROM claim_block_runs"
            " ORDER BY doc_id, seq"
        )
        return [dict(r) for r in cur.fetchall()]


def _table_exists(conn: psycopg.Connection, table: str) -> bool:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT to_regclass(%s) AS name", (table,))
        row = cur.fetchone()
    return bool(row and row["name"])


def _doc_kind(row: dict[str, Any], texts: list[str]) -> str:
    """与 ``CorpusService.extract_claims`` 同口径：覆盖优先，否则零成本规则分类。"""
    override = row.get("doc_kind_override")
    if override in DOC_KINDS:
        return str(override)
    return classify_doc_kind(str(row.get("title") or ""), texts)


# ── 报告一：完整性 ───────────────────────────────────────────────
#: 审计覆盖的表（§4：只读现有表；v2 影子表同样必须被备份/恢复覆盖）
_AUDITED_TABLES = (
    "blocks",
    "claim_block_runs",
    "claim_block_runs_v2",
    "claims",
    "claims_v2",
    "documents",
)


def _backup_coverage(conn: psycopg.Connection) -> tuple[list[dict[str, Any]], list[str]]:
    """实际列 vs ``_BACKUP_COLUMNS`` 逐列枚举：漏列不会报错，只会静默丢字段（附录 A）。

    返回 ``(列偏差清单, 未纳入备份的表)``。前者是冲突，双向查：
    老库迁移加列后忘了同步枚举（§5.1 的 ⚠️ 说的正是它），或枚举里列了库里
    没有的列；生成列（``tsv`` / ``title_tsv``）可随时重算，不算偏差。
    后者防"新表压根没进备份"。
    """
    from plugins.corpus.service import CorpusService  # 延迟导入避免环形依赖

    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            "SELECT table_name, column_name, is_generated FROM information_schema.columns"
            " WHERE table_schema = current_schema() ORDER BY table_name, ordinal_position"
        )
        actual: dict[str, list[str]] = defaultdict(list)
        for r in cur.fetchall():
            if r["is_generated"] == "ALWAYS":  # 生成列由 PG 派生，备份无需覆盖
                continue
            actual[str(r["table_name"])].append(str(r["column_name"]))

    backup = CorpusService._BACKUP_COLUMNS
    drift: list[dict[str, Any]] = [
        {"table": table, "missing_in_db": lost}
        for table, columns in backup.items()
        if (lost := [c for c in columns if c not in actual.get(table, [])])
    ]
    drift += [
        {"table": table, "columns_unlisted": extra}
        for table, cols in sorted(actual.items())
        if table in backup and (extra := [c for c in cols if c not in backup[table]])
    ]
    orphan_tables = [t for t in _AUDITED_TABLES if t not in backup]
    return drift, orphan_tables


def audit_completeness(
    conn: psycopg.Connection,
    documents: list[dict[str, Any]],
    blocks_by_doc: dict[str, list[BlockView]],
    claims: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """候选块 vs 已抽块缺口；0 候选文档；字段缺失率；备份覆盖率（§4 报告一）。

    候选/0 候选只在 **status='ok'** 的文档上算：``empty`` / ``needs_ocr`` 是入库侧
    问题（没解析出内容 / 等 OCR），把它们算进"0 候选文档"只会用不可行动的条目
    稀释缺口信号——它们该走重跑 ingest，而不是 D2 抽取。
    """
    by_status = Counter(str(row.get("status") or "") for row in documents)
    eligible = {str(row["doc_id"]) for row in documents if row.get("status") == "ok"}
    candidates: dict[str, set[int]] = {}
    no_candidate_docs: list[str] = []
    triage_reasons: Counter[str] = Counter()
    block_lengths: list[int] = []
    flat_tables: list[tuple[str, int]] = []
    for row in documents:
        doc_id = str(row["doc_id"])
        if doc_id not in eligible:
            continue
        cand: set[int] = set()
        for block in blocks_by_doc.get(doc_id, []):
            block_lengths.append(len(block.text))
            triage = triage_block_detail(block.text)
            triage_reasons[triage.reason] += 1
            if triage.candidate:
                cand.add(block.seq)
            if is_flat_table(block.text):
                flat_tables.append((doc_id, block.seq))
        candidates[doc_id] = cand
        if not cand:
            no_candidate_docs.append(doc_id)

    kind_details = {
        str(row["doc_id"]): classify_doc_kind_detail(
            str(row.get("title") or ""),
            tuple(b.text for b in blocks_by_doc.get(str(row["doc_id"]), [])),
            str(row["doc_kind_override"]) if row.get("doc_kind_override") else None,
        )
        for row in documents
    }
    kind_reason_counts = Counter(detail.reason for detail in kind_details.values())
    low_confidence_docs = [
        {
            "doc_id": doc_id,
            "kind": detail.kind,
            "reason": detail.reason,
            "confidence": detail.confidence,
        }
        for doc_id, detail in sorted(kind_details.items())
        if detail.confidence < 0.8
    ]

    ok_runs: dict[str, set[int]] = defaultdict(set)
    failed_runs: list[dict[str, Any]] = []
    for r in runs:
        doc_id, seq = str(r["doc_id"]), int(r["seq"])
        if r["status"] == "ok":
            ok_runs[doc_id].add(seq)
        else:
            failed_runs.append({"doc_id": doc_id, "seq": seq, "attempts": r["attempts"]})

    gap = sorted(
        (doc_id, seq)
        for doc_id, seqs in candidates.items()
        for seq in seqs
        if seq not in ok_runs.get(doc_id, set())
    )
    stale = sorted(
        (doc_id, seq)
        for doc_id, seqs in ok_runs.items()
        for seq in seqs - candidates.get(doc_id, set())
    )

    # 字段缺失率（§4 列 period/metric/value；as_of 是 P1 新增一并统计）
    total = len(claims)
    missing_fields = {
        field: sum(1 for c in claims if c.get(field) in (None, ""))
        for field in ("metric", "value_text", "period", "as_of")
    }

    backup_missing, backup_extra_tables = _backup_coverage(conn)

    return {
        "documents": {
            "total": len(documents),
            "eligible": len(eligible),
            "by_status": dict(sorted(by_status.items())),
        },
        "candidates_total": sum(len(s) for s in candidates.values()),
        "extracted_ok_blocks": sum(len(s) for s in ok_runs.values()),
        "extraction_gap": {"count": len(gap), "examples": gap[:DETAIL_LIMIT]},
        "stale_ok_blocks": {"count": len(stale), "examples": stale[:DETAIL_LIMIT]},
        "zero_candidate_docs": {
            "count": len(no_candidate_docs),
            "examples": no_candidate_docs[:DETAIL_LIMIT],
        },
        "failed_runs": {"count": len(failed_runs), "examples": failed_runs[:DETAIL_LIMIT]},
        "triage": {
            "reason_counts": dict(sorted(triage_reasons.items())),
            "flat_table_blocks": {
                "count": len(flat_tables),
                "examples": flat_tables[:DETAIL_LIMIT],
            },
            "block_length": {
                "count": len(block_lengths),
                "min": min(block_lengths) if block_lengths else 0,
                "max": max(block_lengths) if block_lengths else 0,
                "avg": round(sum(block_lengths) / len(block_lengths), 1) if block_lengths else 0,
            },
        },
        "doc_kind_detail": {
            "reason_counts": dict(sorted(kind_reason_counts.items())),
            "low_confidence": {
                "count": len(low_confidence_docs),
                "examples": low_confidence_docs[:DETAIL_LIMIT],
            },
        },
        "field_missing": {
            "claims_total": total,
            **{
                k: {"count": v, "rate": round(v / total, 4) if total else 0.0}
                for k, v in missing_fields.items()
            },
        },
        "backup_coverage": {
            "tables": sorted(_AUDITED_TABLES),
            "drift": backup_missing,
            "tables_not_backed_up": backup_extra_tables,
        },
    }


def audit_v2_shadow(conn: psycopg.Connection) -> dict[str, Any]:
    """v2 影子状态分布；只读，不要求生产切换。"""
    if not _table_exists(conn, "claims_v2") or not _table_exists(conn, "claim_block_runs_v2"):
        return {"available": False}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute("SELECT quality_status, COUNT(*) AS n FROM claims_v2 GROUP BY quality_status")
        quality = {str(r["quality_status"]): int(r["n"]) for r in cur.fetchall()}
        cur.execute("SELECT status, COUNT(*) AS n FROM claim_block_runs_v2 GROUP BY status")
        runs = {str(r["status"]): int(r["n"]) for r in cur.fetchall()}
        cur.execute("SELECT COUNT(*) AS n FROM claims_v2 WHERE quality_status = 'ok'")
        ok_row = cur.fetchone()
    ok = int(ok_row["n"]) if ok_row else 0
    total = sum(quality.values())
    return {
        "available": True,
        "claims": {
            "total": total,
            "quality_status": dict(sorted(quality.items())),
            "normal_query_visible": ok,
        },
        "runs": {"status": dict(sorted(runs.items()))},
    }


# ── 报告二：一致性 ───────────────────────────────────────────────
def audit_consistency(
    documents: list[dict[str, Any]],
    blocks_by_doc: dict[str, list[BlockView]],
    claims: list[dict[str, Any]],
) -> dict[str, Any]:
    """跨块数值冲突；指标命名分裂；ticker 与文档标的冲突；kind↔period 自洽（§4 报告二）。"""
    # 1. 跨块同指标同年份数值冲突：同 (doc, metric, period, kind) 出现多个不同 value_num
    groups: dict[tuple[str, str, str, str], set[object]] = defaultdict(set)
    for c in claims:
        if c.get("value_num") is None:
            continue
        key = (
            str(c["doc_id"]),
            str(c.get("metric") or ""),
            str(c.get("period") or ""),
            str(c.get("kind") or ""),
        )
        groups[key].add(c["value_num"])
    value_conflicts = [
        {"doc_id": k[0], "metric": k[1], "period": k[2], "kind": k[3], "values": sorted(v, key=str)}
        for k, v in sorted(groups.items())
        if len(v) > 1
    ]

    # 2. 指标命名分裂：归一后同键但原文写法 >1 种（别名表的扩充候选，观察项）
    names: dict[tuple[str, str], set[str]] = defaultdict(set)
    for c in claims:
        metric = c.get("metric")
        if not metric:
            continue
        names[(str(c["doc_id"]), normalize_metric(str(metric)) or "")].add(str(metric))
    splits = [
        {"doc_id": k[0], "normalized": k[1], "variants": sorted(v)}
        for k, v in sorted(names.items(), key=lambda kv: (kv[0][0], str(kv[0][1])))
        if len(v) > 1
    ]

    # 3. ticker 与文档标的冲突：company 文档的 claim 必须带标的（抽取链路有兜底回填）
    kinds = {
        str(row["doc_id"]): _doc_kind(
            row, [b.text for b in blocks_by_doc.get(str(row["doc_id"]), [])]
        )
        for row in documents
    }
    tickers_by_doc = {
        str(row["doc_id"]): document_ticker(
            str(row.get("title") or ""), [b.text for b in blocks_by_doc.get(str(row["doc_id"]), [])]
        )
        for row in documents
    }
    unattributed: list[dict[str, Any]] = []
    for c in claims:
        doc_id = str(c["doc_id"])
        if kinds.get(doc_id) != "company" or c.get("tickers"):
            continue
        unattributed.append(
            {
                "doc_id": doc_id,
                "seq": c["seq"],
                "claim_id": c["claim_id"],
                "doc_ticker": tickers_by_doc.get(doc_id),
            }
        )

    # 4. kind↔period 自洽：forecast 必须有 period；fact 不得标预测期（如 2026E）
    kind_period = []
    for c in claims:
        kind, period = c.get("kind"), c.get("period")
        bad = (kind == "forecast" and not period) or (
            kind == "fact" and period and _FORECAST_PERIOD_RE.fullmatch(str(period).strip())
        )
        if bad:
            kind_period.append(
                {"doc_id": c["doc_id"], "seq": c["seq"], "kind": kind, "period": period}
            )

    return {
        "value_conflicts": {
            "count": len(value_conflicts),
            "examples": value_conflicts[:DETAIL_LIMIT],
        },
        "metric_splits": {"count": len(splits), "examples": splits[:DETAIL_LIMIT]},
        "company_claims_without_ticker": {
            "count": len(unattributed),
            "examples": unattributed[:DETAIL_LIMIT],
        },
        "kind_period_violations": {
            "count": len(kind_period),
            "examples": kind_period[:DETAIL_LIMIT],
        },
    }


# ── 报告三：质量评估 ─────────────────────────────────────────────
def _trace_values(
    claims: list[dict[str, Any]], blocks_by_doc: dict[str, list[BlockView]]
) -> list[dict[str, Any]]:
    """数字溯源：value_text 里的数字必须能在其所在块的原文中找到。

    千分位/空格先归一再比对（原文 ``173,340`` 对 ``value_num`` ``173340`` 算可溯源，
    这是解析层的归一行为，不是虚构）。
    """
    text_by_key = {
        (doc_id, b.seq): b.text for doc_id, blocks in blocks_by_doc.items() for b in blocks
    }
    failures: list[dict[str, Any]] = []
    for c in claims:
        raw = c.get("value_text")
        if raw in (None, ""):
            raw = c.get("value_num")
        if raw in (None, ""):
            continue  # 无值的 claim 归完整性报告管，这里不判
        block_text = text_by_key.get((str(c["doc_id"]), int(c["seq"])), "")
        tokens = _NUM_TOKEN_RE.findall(str(raw))
        if tokens and not _value_in_evidence(str(raw), block_text):
            failures.append(
                {
                    "doc_id": c["doc_id"],
                    "seq": c["seq"],
                    "claim_id": c["claim_id"],
                    "claim_text": str(c.get("claim_text") or "")[:80],
                    "value_text": c.get("value_text"),
                }
            )
    return failures


def audit_quality(
    blocks_by_doc: dict[str, list[BlockView]],
    claims: list[dict[str, Any]],
    runs: list[dict[str, Any]],
) -> dict[str, Any]:
    """数字溯源率；JSON 解析失败率 / 死信率；单块耗时/花费分布（§4 报告三）。"""
    untraced = _trace_values(claims, blocks_by_doc)
    traced_n = sum(
        1 for c in claims if c.get("value_text") not in (None, "") or c.get("value_num") is not None
    )

    ok_runs = [r for r in runs if r["status"] == "ok"]
    failed = [r for r in runs if r["status"] != "ok"]
    dead = [r for r in failed if int(r["attempts"] or 0) >= DEAD_LETTER_ATTEMPTS]

    def dist(field: str) -> dict[str, int | None]:
        vals = sorted(int(r[field]) for r in ok_runs if r[field] is not None)
        if not vals:
            return {"p50": None, "p95": None, "max": None, "sum": 0}

        def pick(q: float) -> int:
            return vals[min(len(vals) - 1, round(q * (len(vals) - 1)))]

        return {
            "p50": pick(0.50),
            "p95": pick(0.95),
            "max": vals[-1],
            "sum": sum(vals),
        }

    total_runs = len(runs)
    return {
        "traceability": {
            "claims_with_value": traced_n,
            "untraced": len(untraced),
            "rate": round(1 - len(untraced) / traced_n, 4) if traced_n else 1.0,
            "examples": untraced[:DETAIL_LIMIT],
        },
        "runs": {
            "total": total_runs,
            "ok": len(ok_runs),
            "failed_retryable": len(failed) - len(dead),
            "dead_letters": len(dead),
            "failure_rate": round(len(failed) / total_runs, 4) if total_runs else 0.0,
        },
        "spend_per_ok_block": {
            "duration_ms": dist("duration_ms"),
            "prompt_tokens": dist("prompt_tokens"),
            "completion_tokens": dist("completion_tokens"),
        },
    }


# ── 汇总入口 ─────────────────────────────────────────────────────
def run_audit(
    db: str,
    doc_ids: Sequence[str] | None = None,
    jsonl_path: str | Path | None = None,
) -> tuple[dict[str, Any], int]:
    """跑三类报告并落留痕，返回 ``(报告 JSON, 退出码)``。退出码：0 干净 / 1 有冲突 / 2 没跑起来。"""
    report: dict[str, Any] = {
        "disclaimer": DISCLAIMER,
        "generated_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "scope": list(doc_ids) if doc_ids else "all",
    }
    try:
        with psycopg.connect(db, connect_timeout=5) as conn:
            documents = _load_documents(conn, doc_ids)
            blocks_by_doc = _load_blocks(conn)
            claims = _load_claims(conn)
            runs = _load_runs(conn)

            completeness = audit_completeness(conn, documents, blocks_by_doc, claims, runs)
            consistency = audit_consistency(documents, blocks_by_doc, claims)
            quality = audit_quality(blocks_by_doc, claims, runs)
            v2_shadow = audit_v2_shadow(conn)
    except psycopg.OperationalError as exc:
        return {"ok": False, "error": f"PG 不可用：{exc}"}, 2

    report["completeness"] = completeness
    report["consistency"] = consistency
    report["quality"] = quality
    report["v2_shadow"] = v2_shadow

    # 冲突清单（驱动退出码）；观察项/缺口只报告
    conflicts: list[str] = []
    if completeness["backup_coverage"]["drift"]:  # type: ignore[index]
        conflicts.append("backup_coverage.drift")
    for key in ("value_conflicts", "company_claims_without_ticker", "kind_period_violations"):
        if consistency[key]["count"]:  # type: ignore[index]
            conflicts.append(f"consistency.{key}")
    if quality["traceability"]["untraced"]:  # type: ignore[index]
        conflicts.append("quality.traceability.untraced")
    if quality["runs"]["dead_letters"]:  # type: ignore[index]
        conflicts.append("quality.runs.dead_letters")
    report["conflicts"] = conflicts

    _append_jsonl(jsonl_path, report, len(conflicts))
    return report, (1 if conflicts else 0)


def _append_jsonl(path: str | Path | None, report: dict[str, Any], conflicts_n: int) -> None:
    """留痕（§11 缺口#6）：每次审计追加一行 JSONL；显式传空串禁用。"""
    if path == "":
        return
    target = Path(path) if path else Path(os.environ.get("CORPUS_AUDIT_JSONL") or DEFAULT_JSONL)
    record = {
        "ts": report["generated_at"],
        "scope": report["scope"],
        "exit_code": 1 if conflicts_n else 0,
        "conflicts": conflicts_n,
        "candidates_total": report["completeness"]["candidates_total"],  # type: ignore[index]
        "claims_total": report["completeness"]["field_missing"]["claims_total"],  # type: ignore[index]
        "traceability_rate": report["quality"]["traceability"]["rate"],  # type: ignore[index]
    }
    target.parent.mkdir(parents=True, exist_ok=True)
    with target.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
