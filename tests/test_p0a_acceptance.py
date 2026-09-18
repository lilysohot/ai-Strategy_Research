"""P0a 验收：把 §7.1 的六条标准变成可重复执行的机械验收。

这个文件存在的理由：P0a 剩下没闭环的两件事——「#2 lint 结论是否真的固化」
与「反例验收：校验是否真有约束力」——都可以**不依赖 LLM** 判定。既然能
确定性判定，就不该留给「跑一次 TUI 看它表现」那种不可复现的方式。

链路是完整的 P0a 设计：:

    stub 研报 → parse_evidence（真实解析，真实定位符）→ 手搓最小 sqlite 入库
        → position_sizing（算术）→ build_strategy_card（组装）
        → strategy_lint（在线校验）→ verify_card（离线三闸裁决）

语料用 ``tests/fixtures/stub_reports`` 而不动 ``data/corpus``：P0a 的设计
前提就是「stub 研报，不碰真实数据」，真实 20 份属于 P0b。测试因此自洽，
换台机器也能跑。
"""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

import pytest

from plugins.corpus.evidence import parse_evidence
from plugins.corpus.fetch import connect, make_source_resolver
from plugins.corpus.strategy_schema import (
    POSITION_SIZING_ID,
    STRATEGY_LINT_ID,
    build_strategy_card,
    dump_strategy_json,
)
from plugins.corpus.verify import verify_card
from plugins.tools.position_sizing import position_sizing
from plugins.tools.strategy_lint import strategy_lint

STUB_DIR = Path(__file__).parent / "fixtures" / "stub_reports"

# 与 run828a 同量级的一组参数，但把止损收紧到 1270，
# 使风险收益比 = (1430-1320)/(1320-1270) = 2.2 >= 1.5 —— 正好同时
# 走到「资金约束」分支（run828a 走的是风险约束分支），两条分支都被覆盖。
CAPITAL_TOTAL = 1_000_000
RISK_BUDGET_PCT = 2.0
ENTRY_LOW, ENTRY_HIGH, STOP_LOSS, TARGET = 1295.0, 1320.0, 1270.0, 1430.0


# 读侧最小 schema：列集按 fetch/verify 的实际 SELECT 反推（I2-7 后写链已退休，
# 测试只负责把解析结果放进读侧认识的形状）。
_STUB_DDL = """
CREATE TABLE documents (
    doc_id      TEXT PRIMARY KEY,
    title       TEXT NOT NULL,
    source_path TEXT NOT NULL,
    mime        TEXT NOT NULL,
    status      TEXT NOT NULL,
    block_count INTEGER NOT NULL,
    char_count  INTEGER NOT NULL
);
CREATE TABLE blocks (
    doc_id  TEXT NOT NULL,
    seq     INTEGER NOT NULL,
    locator TEXT NOT NULL,
    text    TEXT NOT NULL,
    PRIMARY KEY (doc_id, seq)
);
"""


def _stub_body(path: Path) -> str:
    """stub md 的正文：剥掉头部 key: value 元数据区（fixture 的组织方式）。

    parse_evidence 的 md 路径原文透传、不认识元数据区；溯源闸比对的
    「原文」应当只含正文。
    """
    lines = path.read_text(encoding="utf-8").splitlines()
    for i, line in enumerate(lines):
        if line.startswith("# "):
            return "\n".join(lines[i:])
    return "\n".join(lines)


def _load_stub_corpus(conn: sqlite3.Connection) -> None:
    """stub 研报 → 真实解析 → 手搓最小 sqlite 写入。

    I2-7：旧 ingest.parse_document/upsert_document 已随写链整体退休。
    解析仍走生产同源（parse_evidence）：doc_id/title 不是手搓的；md 恒为
    单页（locator="document"），整篇正文自然成为一块。
    """
    conn.executescript(_STUB_DDL)
    for path in sorted(STUB_DIR.glob("*.md")):
        doc = parse_evidence(path)
        page = doc.pages[0]
        conn.execute(
            "INSERT INTO documents (doc_id, title, source_path, mime, status, block_count,"
            " char_count) VALUES (?, ?, ?, 'text/markdown', 'active', 1, ?)",
            (doc.doc_id, doc.title, doc.source_path, len(page.text)),
        )
        conn.execute(
            "INSERT INTO blocks (doc_id, seq, locator, text) VALUES (?, 1, ?, ?)",
            (doc.doc_id, page.locator, _stub_body(path)),
        )
    conn.commit()


@pytest.fixture
def corpus_db(tmp_path: Path):
    """把 stub 研报解析进临时库，返回连接。

    解析走生产同源（parse_evidence）而不是手搓 dict：验收要验的是**这条链路**，
    手搓一份 blocks 文本等于把被测对象换掉了。
    """
    conn = connect(tmp_path / "index.db")
    _load_stub_corpus(conn)
    yield conn
    conn.close()


def _locate(
    conn: sqlite3.Connection,
    doc_id: str,
    keyword: str,
) -> tuple[str, str]:
    """从真实块里取出一条**逐字**引文，返回 ``(locator, quote)``。

    刻意不硬编码中文引文：从库里现取，能保证它一定是原文的连续子串。
    硬编码的话，一旦 stub 文件被改动一个标点，溯源闸就会以「找不到引文」
    的形式失败——那种失败看不出是数据改了还是代码坏了。
    """
    rows = conn.execute(
        "SELECT seq, locator, text FROM blocks WHERE doc_id = ? ORDER BY seq",
        (doc_id,),
    ).fetchall()
    for _seq, locator, text in rows:
        for line in text.splitlines():
            stripped = line.strip()
            if len(stripped) >= 10 and keyword in stripped:
                return locator, stripped
    raise AssertionError(f"stub 语料里找不到含 {keyword!r} 的行：{doc_id}")


def _doc_ids(conn: sqlite3.Connection) -> dict[str, str]:
    """按文件名关键字取 doc_id。"""
    rows = conn.execute("SELECT doc_id, source_path FROM documents").fetchall()
    mapping: dict[str, str] = {}
    for doc_id, source_path in rows:
        name = Path(source_path).name
        for key in ("R01", "R02", "R03", "R04", "R05"):
            if name.startswith(key):
                mapping[key] = doc_id
    return mapping


async def _sizing(stop_loss: float = STOP_LOSS) -> dict[str, Any]:
    payload = await position_sizing.func(  # type: ignore[attr-defined]
        capital_total=CAPITAL_TOTAL,
        risk_budget_pct=RISK_BUDGET_PCT,
        entry_low=ENTRY_LOW,
        entry_high=ENTRY_HIGH,
        stop_loss=stop_loss,
    )
    return json.loads(payload)


def _build_card(
    conn: sqlite3.Connection,
    stop_loss: float = STOP_LOSS,
) -> dict[str, Any]:
    """组装一张合规策略卡（evidence 全部取自真实入库原文）。"""
    ids = _doc_ids(conn)
    fact_locator, fact_quote = _locate(conn, ids["R01"], "营业收入")
    forecast_locator, forecast_quote = _locate(conn, ids["R01"], "目标价")
    opinion_locator, opinion_quote = _locate(conn, ids["R04"], "失效")

    sources = []
    for key in ("R01", "R04"):
        row = conn.execute(
            "SELECT doc_id, title, source_path FROM documents WHERE doc_id = ?",
            (ids[key],),
        ).fetchone()
        sources.append({"id": row[0], "title": row[1], "url": row[2]})

    return build_strategy_card(
        symbol="LHXC.SH",
        thesis="产能爬坡打开第二成长曲线；反方给出可证伪的失效条件。",
        evidence=[
            {"source_ref": ids["R01"], "page": fact_locator, "quote": fact_quote, "kind": "fact"},
            {
                "source_ref": ids["R01"],
                "page": forecast_locator,
                "quote": forecast_quote,
                "kind": "forecast",
            },
            {
                "source_ref": ids["R04"],
                "page": opinion_locator,
                "quote": opinion_quote,
                "kind": "opinion",
            },
        ],
        entry_low=ENTRY_LOW,
        entry_high=ENTRY_HIGH,
        stop_loss=stop_loss,
        target=TARGET,
        invalidation="若季度营收同比转负则逻辑失效",
        horizon="3-6M",
        capital_total=CAPITAL_TOTAL,
        sizing={},  # 占位：调用方随后用 position_sizing 的真实返回覆盖
        sources=sources,
    )


# ── 正向：完整链路产出一张三闸全绿的策略卡 ──────────────────────────────


async def test_full_chain_produces_a_three_gate_clean_card(corpus_db):
    """§7.1 的 #1/#3/#4 与三条硬闸一次性验完。

    这是 P0a 的主验收：走完 position_sizing → 组装 → 在线 lint → 离线
    三闸裁决，最终 passed=True。它替代了「跑一次 TUI 看表现」这种
    不可复现的方式。
    """
    conn = corpus_db
    card = _build_card(conn)
    card["position"]["sizing"] = await _sizing()

    # 硬闸②（#1/#3）：仓位数字确实由工具产出
    assert card["position"]["sizing"]["computed_by"] == POSITION_SIZING_ID
    # 资金约束分支：400000/1320 = 303 股 < 风险允许的 400 股
    assert card["position"]["sizing"]["constrained_by"] == "capital"
    assert card["position"]["sizing"]["shares"] == 300
    assert card["position"]["sizing"]["amount"] == 300 * ENTRY_HIGH

    # 在线校验（#2）
    lint = json.loads(await strategy_lint.func(dump_strategy_json(card)))  # type: ignore[attr-defined]
    assert lint["passed"] is True, lint["errors"]
    assert lint["checked_by"] == STRATEGY_LINT_ID
    assert lint["warnings"] == [], lint["warnings"]

    # 纪律要求：lint 段**原样**落盘（不只是 checked_by）
    card["lint"] = lint

    # 离线三闸裁决
    report = verify_card(card, source_resolver=make_source_resolver(conn))
    assert report["passed"] is True, report["problems"]
    assert report["skipped"] == []
    for gate in ("traceability", "arithmetic", "schema"):
        assert report["gates"][gate]["status"] == "passed", report["gates"][gate]


async def test_traceability_gate_rejects_a_fabricated_quote(corpus_db):
    """硬闸①：把引文改一个字，溯源闸必须抓到。

    这条是「溯源校验真的在比对了」的证明——如果它只会无脑返回 passed，
    改引文前后结果一样，那这条闸就是摆设。
    """
    conn = corpus_db
    card = _build_card(conn)
    card["position"]["sizing"] = await _sizing()
    card["position"]["evidence"][0]["quote"] = "公司2025年营业收入为99.9亿元（编造）"

    report = verify_card(card, source_resolver=make_source_resolver(conn))
    assert report["passed"] is False
    assert report["gates"]["traceability"]["status"] == "failed"
    codes = {item["code"] for item in report["gates"]["traceability"]["problems"]}
    assert "quote_not_found" in codes


# ── 反例验收：校验是否真有约束力（plan §7.1 明确要求「必须也能过」）──────


async def test_bad_stop_loss_is_rejected_by_position_sizing():
    """止损在入场区间之上 → 工具直接拒绝产出仓位，而不是给个离谱的数。"""
    result = await _sizing(stop_loss=1300.0)  # > entry_low 1295
    assert result["ok"] is False
    assert "stop_loss" in result["error"]
    # 错误体里**不含**可用数字，防止 Agent 从失败调用里捡数
    assert result["shares"] == 0


async def test_bad_stop_loss_is_rejected_by_lint(corpus_db):
    """止损在入场区间之上 → strategy_lint 判 ERROR（且是阻断级）。"""
    conn = corpus_db
    card = _build_card(conn, stop_loss=1300.0)
    card["position"]["sizing"] = await _sizing()  # 用合规 sizing，只把止损改坏

    lint = json.loads(await strategy_lint.func(dump_strategy_json(card)))  # type: ignore[attr-defined]
    assert lint["passed"] is False
    codes = {item["code"] for item in lint["errors"]}
    assert "stop_loss_not_below_entry" in codes


async def test_forged_lint_pass_is_caught_by_offline_verification(corpus_db):
    """**关键**：Agent 绕过校验、自己写一句 ``"passed": true`` 也过不了。

    这条是反例验收真正的落点。只测「lint 会报错」是不够的——那只验证了
    工具，没验证「绕过得绕不过去」。Agent 完全可以跳过 lint，直接写一张
    漂亮卡再补个 passed=true；离线重算会让这种自产自销当场现形。
    """
    conn = corpus_db
    card = _build_card(conn, stop_loss=1300.0)  # 故意构造不可行的止损
    card["position"]["sizing"] = await _sizing()

    # 伪造：假装校验通过
    card["lint"] = {
        "checked_by": STRATEGY_LINT_ID,
        "passed": True,
        "errors": [],
        "warnings": [],
    }

    report = verify_card(card, source_resolver=make_source_resolver(conn))
    assert report["passed"] is False
    codes = {item["code"] for item in report["gates"]["schema"]["problems"]}
    # 重算必然失败，且与卡内「0 条错误」的记录不一致
    assert "lint_recheck_failed" in codes
    assert "lint_result_diverged" in codes


async def test_missing_lint_passed_field_is_caught(corpus_db):
    """run828a 的真实缺陷：只存 checked_by、不存 passed。"""
    conn = corpus_db
    card = _build_card(conn)
    card["position"]["sizing"] = await _sizing()
    card["lint"] = {"checked_by": STRATEGY_LINT_ID, "note": "看起来没问题"}

    report = verify_card(card, source_resolver=make_source_resolver(conn))
    assert report["passed"] is False
    codes = {item["code"] for item in report["gates"]["schema"]["problems"]}
    assert "lint_passed_not_recorded" in codes
