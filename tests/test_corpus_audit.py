"""D2 P5 验收：语料库三类审计报告（d2-claims-design §4）。

覆盖：完整性（候选块缺口 / 0 候选文档 / 字段缺失率 / 备份覆盖率）、一致性
（跨块数值冲突 / 指标命名分裂 / ticker 冲突 / kind↔period 自洽）、质量评估
（数字溯源率 / 失败与死信 / 花费分布），以及退出码纪律（0 干净 / 1 冲突 /
2 没跑起来）与 JSONL 留痕（§11 缺口#6）。

隔离方式与 ``test_corpus_claims.py`` 一致：临时 schema，PG 不可用则 skip。
审计全程只读——测试库里的"缺陷"都是故意注入的已知数据。
"""

from __future__ import annotations

import json
from pathlib import Path

import psycopg
import pytest

from plugins.corpus.audit import run_audit
from plugins.corpus.service import CorpusService, dsn

SCRATCH_SCHEMA = "corpus_d5audit"


def _scratch_url(admin: str, schema: str = SCRATCH_SCHEMA) -> str:
    from urllib.parse import quote

    options = quote(f"-c search_path={schema},public")
    sep = "&" if "?" in admin else "?"
    return f"{admin}{sep}options={options}"


@pytest.fixture(scope="module")
def audit_dsn():
    admin = dsn()
    try:
        psycopg.connect(admin, connect_timeout=5).close()
    except psycopg.OperationalError as exc:  # pragma: no cover - 环境相关
        pytest.skip(f"PG 不可用，跳过 D5 审计测试：{exc}")

    with psycopg.connect(admin, autocommit=True) as conn:
        conn.execute(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE')
        conn.execute(f'CREATE SCHEMA "{SCRATCH_SCHEMA}"')
    url = _scratch_url(admin)
    CorpusService(url).init_db()
    _seed(url)
    try:
        yield url
    finally:
        with psycopg.connect(admin, autocommit=True) as conn:
            conn.execute(f'DROP SCHEMA IF EXISTS "{SCRATCH_SCHEMA}" CASCADE')


def _seed(url: str) -> None:
    """注入一小份带**已知缺陷**的语料：每个缺陷对准一个检查项。"""

    # 4 份文档：company（标题带代码）/ industry / macro（override 定死，不依赖分类器）
    # d4 是 status='empty' 的入库残次品 ⇒ 不进候选统计（不可行动，归 ingest 重跑）
    docs = [
        ("d1_company", "贵州茅台（600519.SH）2026 年中报点评", None, "ok"),
        ("d2_industry", "化工行业专题：从分化到收敛", "industry", "ok"),
        ("d3_macro", "某宏观周报（无数字）", "macro", "ok"),
        ("d4_empty", "扫描件（解析失败）", "macro", "empty"),
    ]
    blocks = [
        # d1：seq1 候选（承载全部 claim）；seq2 纯噪音但有一条 ok 台账 ⇒ stale；
        # seq3 候选但没抽过 ⇒ 抽取缺口
        (
            "d1_company",
            1,
            "贵州茅台 2026H1 营业收入 1741 亿元。另一处口径 1700 亿元。"
            "目标价 1888 元。毛利率 90.4%。每股收益 88.5 元。2025 年营收 173,340。",
        ),
        ("d1_company", 2, "免责声明：本报告未经书面许可不得转载。"),
        ("d1_company", 3, "2026E 展望：资本开支 1234 亿元。"),
        ("d2_industry", 1, "基础化工行业周报：纯碱价格 2100 元/吨，环比上升。"),
        ("d3_macro", 1, "免责声明：本报告不构成投资建议。"),
        # d4 有数字块但 status='empty' ⇒ 即便 has_signal 成立也不进候选
        ("d4_empty", 1, "疑似数字 42。"),
    ]
    claims = [
        # (doc, seq, claim_text, kind, tickers, metric, value_text, value_num, period)
        # ①② 同 (doc, metric, period, kind) 不同数值 ⇒ 跨块数值冲突
        (
            "d1_company",
            1,
            "茅台 2026H1 营业收入约 1741 亿元",
            "fact",
            ["600519.SH"],
            "营业收入",
            "1741亿元",
            1741,
            "2026H1",
        ),
        (
            "d1_company",
            1,
            "茅台 2026H1 营业收入约 1700 亿元（另一处口径）",
            "fact",
            ["600519.SH"],
            "营业收入",
            "1700亿元",
            1700,
            "2026H1",
        ),
        # ③④ 归一同键（每股收益）但原文两种写法 ⇒ 指标命名分裂
        (
            "d1_company",
            1,
            "茅台 2026E 每股收益 88.5 元",
            "forecast",
            ["600519.SH"],
            "每股收益",
            "88.5元",
            88.5,
            "2026E",
        ),
        (
            "d1_company",
            1,
            "茅台 2026E EPS 88.5 元",
            "forecast",
            ["600519.SH"],
            "EPS",
            "88.5元",
            88.5,
            "2026E",
        ),
        # ⑤ forecast 无 period（kind↔period 违例）+ company 文档 claim 无标的（双重缺陷）
        (
            "d1_company",
            1,
            "目标价 1888 元（未给期）",
            "forecast",
            [],
            "目标价",
            "1888元",
            1888,
            None,
        ),
        # ⑥ 数字不在块原文 ⇒ 溯源失败
        (
            "d1_company",
            1,
            "毛利率 99999%（原文无此数）",
            "fact",
            ["600519.SH"],
            "毛利率",
            "99999%",
            99999,
            None,
        ),
        # ⑦ 千分位归一：value_text 173340 对原文 173,340 ⇒ 算可溯源
        (
            "d1_company",
            1,
            "2025 年营收 173340（千分位归一）",
            "fact",
            ["600519.SH"],
            "营业收入（千分位）",
            "173340",
            173340,
            "2025",
        ),
        # ⑧ fact 标预测期 ⇒ kind↔period 违例
        (
            "d1_company",
            1,
            "2026E 毛利率 90.4%（fact 标预测期）",
            "fact",
            ["600519.SH"],
            "毛利率 2026E",
            "90.4%",
            90.4,
            "2026E",
        ),
        # ⑨ industry 文档 claim 无标的 ⇒ **不是**冲突（插槽契约本就要求为空）
        (
            "d2_industry",
            1,
            "纯碱价格 2100 元/吨",
            "fact",
            [],
            "纯碱.价格",
            "2100元/吨",
            2100,
            "2026-08",
        ),
    ]
    runs = [
        # d1 seq1 ok；d1 seq2 ok 但该块不是候选 ⇒ stale；d2 seq1 失败（可重试，未达死信）
        ("d1_company", 1, "ok", 9, 1, 1500, 500, 1000),
        ("d1_company", 2, "ok", 0, 1, 100, 80, 1),
        ("d2_industry", 1, "failed", 0, 2, 3000, None, None),
    ]

    with psycopg.connect(url, autocommit=True) as conn:
        for doc_id, title, override, status in docs:
            conn.execute(
                "INSERT INTO documents (doc_id, title, source_path, content_hash, mime,"
                " status, block_count, doc_kind_override, published)"
                " VALUES (%s, %s, %s, %s, 'text/markdown', %s, 0, %s, '2026-09-01')",
                (doc_id, title, f"/tmp/{doc_id}.md", f"hash-{doc_id}", status, override),
            )
        for doc_id, seq, text in blocks:
            conn.execute(
                "INSERT INTO blocks (doc_id, seq, locator, text) VALUES (%s, %s, %s, %s)",
                (doc_id, seq, f"p{seq}", text),
            )
            conn.execute("UPDATE documents SET block_count = %s WHERE doc_id = %s", (seq, doc_id))
        for doc, seq, claim_text, kind, tickers, metric, value_text, value_num, period in claims:
            conn.execute(
                "INSERT INTO claims (doc_id, seq, locator, claim_text, kind, tickers,"
                " metric, value_text, value_num, unit, period, as_of, confidence)"
                " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, '2026-09-01', 0.9)",
                (
                    doc,
                    seq,
                    f"p{seq}",
                    claim_text,
                    kind,
                    tickers,
                    metric,
                    value_text,
                    value_num,
                    "%",
                    period,
                ),
            )
        for doc_id, seq, status, claims_n, attempts, dur, pt, ct in runs:
            conn.execute(
                "INSERT INTO claim_block_runs (doc_id, seq, status, claims_n, attempts,"
                " model, extractor_version, duration_ms, prompt_tokens, completion_tokens)"
                " VALUES (%s, %s, %s, %s, %s, 'fake-model', 'test', %s, %s, %s)",
                (doc_id, seq, status, claims_n, attempts, dur, pt, ct),
            )


# ── 完整性 ───────────────────────────────────────────────────────
def test_completeness_gap_stale_and_zero_candidates(audit_dsn: str) -> None:
    report, _code = run_audit(audit_dsn, jsonl_path="")
    c = report["completeness"]
    # 文档口径：4 份中 eligible（status='ok'）3 份；empty 的 d4 不进候选统计
    assert c["documents"] == {"total": 4, "eligible": 3, "by_status": {"empty": 1, "ok": 3}}
    assert c["candidates_total"] == 3
    # 候选 = d1{1,3} + d2{1}；ok 台账 = d1{1,2}（failed 不算已抽）
    # ⇒ 缺口 = d1 seq3 + d2 seq1，stale = d1 seq2
    assert c["extraction_gap"]["count"] == 2
    assert ("d1_company", 3) in c["extraction_gap"]["examples"]
    assert ("d2_industry", 1) in c["extraction_gap"]["examples"]
    assert c["stale_ok_blocks"]["count"] == 1
    assert ("d1_company", 2) in c["stale_ok_blocks"]["examples"]
    # d3 全是免责声明 ⇒ 0 候选文档
    assert c["zero_candidate_docs"]["count"] == 1
    assert "d3_macro" in c["zero_candidate_docs"]["examples"]
    assert c["failed_runs"]["count"] == 1
    # 字段缺失率：仅 ⑤⑥ 两条缺 period；metric/value_text/as_of 全非空
    fm = c["field_missing"]
    assert fm["claims_total"] == 9
    for field in ("metric", "value_text", "as_of"):
        assert fm[field]["count"] == 0, field
    assert fm["period"]["count"] == 2
    # 备份覆盖率：seed 库由 init_db 完整建表 ⇒ 无偏差
    assert c["backup_coverage"]["drift"] == []


def test_backup_coverage_detects_unlisted_column(
    audit_dsn: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    """枚举漏列 = 静默丢字段（附录 A 事故）：少列一列必须被抓出来。"""
    from plugins.corpus.service import CorpusService

    monkeypatch.setitem(CorpusService._BACKUP_COLUMNS, "claims", ("claim_id", "doc_id"))
    report, code = run_audit(audit_dsn, jsonl_path="")
    drift = report["completeness"]["backup_coverage"]["drift"]
    unlisted = [d for d in drift if d.get("columns_unlisted")]
    assert any(d["table"] == "claims" for d in unlisted)
    assert code == 1  # 与其他注入缺陷共存 ⇒ 冲突退出码


# ── 一致性 ───────────────────────────────────────────────────────
def test_consistency_all_four_checks(audit_dsn: str) -> None:
    report, _ = run_audit(audit_dsn, jsonl_path="")
    co = report["consistency"]
    # 跨块数值冲突：仅 ①② 一组（③④ metric 原文不同，不并组）
    assert co["value_conflicts"]["count"] == 1
    ex = co["value_conflicts"]["examples"][0]
    assert (ex["doc_id"], ex["metric"], ex["period"]) == ("d1_company", "营业收入", "2026H1")
    assert sorted(ex["values"], key=str) == [1700, 1741]
    # 指标命名分裂：每股收益 / EPS 同文档并存
    assert co["metric_splits"]["count"] == 1
    assert co["metric_splits"]["examples"][0]["variants"] == ["EPS", "每股收益"]
    # ticker：company 文档的 ⑤ 无标的算冲突；industry 的 ⑨ 为空是契约不算
    assert co["company_claims_without_ticker"]["count"] == 1
    assert co["company_claims_without_ticker"]["examples"][0]["doc_id"] == "d1_company"
    # kind↔period：⑤ forecast 无 period + ⑧ fact 标 2026E
    assert co["kind_period_violations"]["count"] == 2


# ── 质量评估 ─────────────────────────────────────────────────────
def test_quality_traceability_and_runs(audit_dsn: str) -> None:
    report, _ = run_audit(audit_dsn, jsonl_path="")
    q = report["quality"]
    # 溯源：9 条有值，仅 ⑥ 不可溯源；⑦ 千分位归一不算失败
    assert q["traceability"]["claims_with_value"] == 9
    assert q["traceability"]["untraced"] == 1
    assert q["traceability"]["rate"] == pytest.approx(round(8 / 9, 4))
    assert q["traceability"]["examples"][0]["claim_text"] == "毛利率 99999%（原文无此数）"
    # 台账：total 3 = ok 2 + failed 1；死信 0（attempts=2 < 3）
    assert q["runs"] == {
        "total": 3,
        "ok": 2,
        "failed_retryable": 1,
        "dead_letters": 0,
        "failure_rate": pytest.approx(round(1 / 3, 4)),
    }
    # 花费分布来自 ok 台账（含 stale 的 d1 seq2）
    ct = q["spend_per_ok_block"]["completion_tokens"]
    assert ct["max"] == 1000 and ct["sum"] == 1001


# ── 退出码与留痕 ─────────────────────────────────────────────────
def test_exit_code_reflects_conflicts_and_jsonl_trace(audit_dsn: str, tmp_path: Path) -> None:
    jsonl = tmp_path / "audit_runs.jsonl"
    report, code = run_audit(audit_dsn, jsonl_path=jsonl)
    # seed 库注入了 3 类冲突 ⇒ 退出码 1，且清单与冲突来源对得上
    assert code == 1
    assert set(report["conflicts"]) == {
        "consistency.value_conflicts",
        "consistency.company_claims_without_ticker",
        "consistency.kind_period_violations",
        "quality.traceability.untraced",
    }
    # 留痕（缺口#6）：一行 JSON，趋势字段齐备
    lines = jsonl.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 1
    rec = json.loads(lines[0])
    assert rec["exit_code"] == 1
    assert rec["conflicts"] == 4
    assert rec["claims_total"] == 9
    assert rec["traceability_rate"] == pytest.approx(round(8 / 9, 4))
    # 空串 = 显式禁用留痕
    run_audit(audit_dsn, jsonl_path="")
    assert len(jsonl.read_text(encoding="utf-8").splitlines()) == 1


def test_doc_scope_filters_documents(audit_dsn: str) -> None:
    report, _ = run_audit(audit_dsn, doc_ids=["d2_industry"], jsonl_path="")
    c = report["completeness"]
    assert c["documents"] == {"total": 1, "eligible": 1, "by_status": {"ok": 1}}
    assert c["candidates_total"] == 1


def test_pg_down_returns_exit_2() -> None:
    report, code = run_audit(
        "host=127.0.0.1 port=1 dbname=none user=u connect_timeout=1", jsonl_path=""
    )
    assert code == 2
    assert report["ok"] is False and "PG 不可用" in str(report["error"])
