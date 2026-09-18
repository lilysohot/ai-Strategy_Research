"""覆盖度信号：语料库**没有相关研报**时必须给出明确信号与下一步。

背景（此前的行为）：`corpus_search` 查不到时返回 `ok=true / count=0 / hits=[]`，
与「检索成功但为空」长得一样，模型无法区分 ⇒ 反复重试，或去够一篇沾边的
研报凑 evidence。现在空结果返回 §7.3 三轴 ``coverage`` 对象 + 明确的流程指令。

I2-8：``coverage`` 由未定义的 ``"none"`` 字符串升级为结构对象
（``processing`` / ``query_status`` / ``availability`` / ``reason_codes``）——
空命中只表述"该已查询范围无匹配"（``query_status=no_match``），
**不自动转 absent**（``availability`` 仍为 unknown），见架构 §7.3。

注：这里用 **monkeypatch 注入空结果**而不是构造一个"查不到的词"——
中文分词会让看似不可能的查询命中语料（实测「…影子股份XYZ…」因"股份"二字命中），
只有注入才能保证测的是**空结果分支本身**。
"""

from __future__ import annotations

import asyncio
import importlib
import json

import pytest

# `plugins.tools.__init__` 把 corpus_search 绑定成了 Tool，需取真身才能调 .func
corpus_search_module = importlib.import_module("plugins.tools.corpus_search")


class _EmptyService:
    """检索永远返回空 —— 模拟「语料库没有相关研报」。"""

    def search(self, query: str, limit: int = 10) -> list:
        return []


@pytest.fixture()
def empty_corpus(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(corpus_search_module, "get_service", lambda: _EmptyService())


def _search(query: str, limit: int = 3) -> dict:
    raw = asyncio.run(corpus_search_module.corpus_search.func(query, limit))
    return json.loads(raw)


def test_no_coverage_returns_explicit_signal(empty_corpus) -> None:
    payload = _search("贵州茅台 目标价")

    assert payload["count"] == 0
    assert payload["hits"] == []
    coverage = payload["coverage"]
    assert isinstance(coverage, dict), "无覆盖必须显式告知，不能与「检索成功」混同"
    assert coverage["query_status"] == "no_match"
    # §7.3：自由文本 FTS 无命中不足以推断材料不存在 ⇒ 不自动转 absent
    assert coverage["availability"] == "unknown"
    assert coverage["reason_codes"]


def test_no_coverage_tells_model_to_stop_and_switch_path(empty_corpus) -> None:
    """指令要能「及时退出当前流程」：停止检索 + 转向市场数据。"""
    hint = _search("贵州茅台 目标价")["hint"]

    assert "停止" in hint, "必须要求模型停止继续检索研报"
    assert "market_resolve" in hint, "必须给出下一步：消歧"
    assert "market_quote" in hint, "必须给出下一步：实时行情"
    assert "market_history" in hint, "必须给出下一步：技术面分析"


def test_no_coverage_hint_pins_the_no_fabrication_rule(empty_corpus) -> None:
    """转向不等于放松纪律：禁止编造研报、指标数值不得由模型自算。"""
    hint = _search("贵州茅台 目标价")["hint"]

    assert "禁止编造" in hint
    assert "computed_by" in hint, "指标数值须来自确定性工具（硬闸②）"


def test_coverage_signal_is_present_in_the_discipline_prompt() -> None:
    """提示词层也要有同一条规则（模型可能忽略工具返回的 hint）。"""
    from plugins.corpus.research_discipline import RESEARCH_DISCIPLINE_ADDENDUM

    assert 'coverage="none"' in RESEARCH_DISCIPLINE_ADDENDUM
    assert "market_history" in RESEARCH_DISCIPLINE_ADDENDUM
    assert "computed_by" in RESEARCH_DISCIPLINE_ADDENDUM
