"""B7：离线校验接上 corpus 解析器后，溯源命中率 = 100%（未溯源数字数 = 0）。

依赖 PG 语料库（CORPUS_DSN，默认本机 PostgreSQL）；不可用或无数据时跳过。

关键判据（plan §7.2）：
- 逐字 evidence → 命中率 100%、整卡通过
- 编造 quote（原文里不存在）→ 命中率 < 100%、整卡不通过

这意味着「数字可溯源」不再依赖 Agent 自觉，而是被磁盘上的原文逐字比对兜死。
"""

from __future__ import annotations

import asyncio
import json

import pytest

from plugins.corpus.service import get_service
from plugins.corpus.strategy_schema import build_strategy_card, dump_strategy_json
from plugins.corpus.verify import verify_card
from plugins.tools.position_sizing import position_sizing
from plugins.tools.strategy_lint import strategy_lint


def _pg_ready() -> bool:
    try:
        return get_service().stats()["documents"] > 0
    except Exception:
        return False


pytestmark = pytest.mark.skipif(
    not _pg_ready(),
    reason="PG 语料库不可用或无数据（默认 postgresql://postgres:postgres@localhost:5432/postgres）",
)


@pytest.fixture
def svc():
    return get_service()


def _sample(svc) -> tuple[str, str, str]:
    """取一份真实文档的第一块（doc_id, locator, 逐字文本）。"""
    hits = svc.search("贵州茅台 目标价", limit=1) or svc.search("市场", limit=1)
    assert hits, "语料库里居然搜不到任何块"
    hit = hits[0]
    block = svc.fetch(hit.doc_id, hit.locator)
    assert block is not None
    return hit.doc_id, hit.locator, block.text


def _build_card(quote: str, *, doc_id: str, locator: str) -> dict:
    """用真实语料拼一张合法策略卡（sizing/lint 都过），evidence.quote 由参数控制。"""
    sizing = json.loads(
        asyncio.run(
            position_sizing.func(
                capital_total=1_000_000,
                risk_budget_pct=2.0,
                entry_low=100.0,
                entry_high=110.0,
                stop_loss=95.0,
            )
        )
    )
    card = build_strategy_card(
        symbol="X.SH",
        thesis="测试用论点",
        evidence=[{"source_ref": doc_id, "page": locator, "quote": quote, "kind": "fact"}],
        entry_low=100.0,
        entry_high=110.0,
        stop_loss=95.0,
        target=120.0,
        invalidation="跌破关键位",
        horizon="1-3M",
        capital_total=1_000_000,
        sizing=sizing,
        sources=[{"id": doc_id, "title": "测试来源", "url": ""}],
    )
    lint = json.loads(asyncio.run(strategy_lint.func(dump_strategy_json(card))))
    card["lint"] = lint
    return card


def test_verbatim_quote_gives_full_traceability(svc) -> None:
    doc_id, locator, text = _sample(svc)
    quote = text.strip().split("\n")[0][:40]
    card = _build_card(quote, doc_id=doc_id, locator=locator)

    report = verify_card(card, source_resolver=svc.source_resolver())

    assert report["passed"] is True
    assert report["traceability"]["total"] == 1
    assert report["traceability"]["traced"] == 1
    assert report["traceability"]["rate"] == 1.0


def test_fabricated_quote_lowers_traceability_rate(svc) -> None:
    doc_id, locator, _ = _sample(svc)
    quote = "这段原文里绝对不存在的编造数字 12345.67 亿元"
    card = _build_card(quote, doc_id=doc_id, locator=locator)

    report = verify_card(card, source_resolver=svc.source_resolver())

    # 编造被逐字比对抓出：整卡不通过，且命中率 < 100%
    assert report["passed"] is False
    assert report["traceability"]["rate"] < 1.0


def test_no_resolver_marks_traceability_skipped_strict_fails(svc) -> None:
    doc_id, locator, text = _sample(svc)
    quote = text.strip().split("\n")[0][:40]
    card = _build_card(quote, doc_id=doc_id, locator=locator)

    # 不给 resolver：溯源闸 skipped；strict 模式整卡判不通过
    report = verify_card(card)  # 默认 strict=True
    assert report["traceability"]["skipped"] is True
    assert report["passed"] is False
