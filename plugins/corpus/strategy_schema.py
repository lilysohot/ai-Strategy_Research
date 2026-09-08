"""``strategy.json`` 的权威 schema 常量 + 构建入口。

单一定义的意义：``strategy_lint``（在线校验）、Agent（组装策略卡）、将来的
离线校验脚本（``python -m plugins.corpus.verify``，三条硬闸）都从这里取同一个
常量。三处各写一份字面量，是「改了一处忘了另一处」这类静默失效的标准温床。

P0 范围：去掉了 portfolio 聚合，强化 evidence 溯源。
"""

from __future__ import annotations

import json
from typing import Any

# ── 版本与工具标识 ──────────────────────────────────────────────────────
# 硬闸②：strategy.json 的 sizing.computed_by 必须等于这个值。
# 它是「这个数字由确定性工具算出、不是 LLM 编的」的唯一证据。
POSITION_SIZING_ID = "position_sizing@v1"
# 对称的校验器标识，供离线校验脚本确认 lint 结果确实来自 strategy_lint。
STRATEGY_LINT_ID = "strategy_lint@v1"
STRATEGY_SCHEMA_VERSION = 1

# ── 枚举 ────────────────────────────────────────────────────────────────
# fact 与 forecast 混用在本项目里视为答案错误（精度红线），所以这两个值
# 必须三选一、没有「其他」这个逃生口。
EVIDENCE_KINDS: tuple[str, ...] = ("fact", "forecast", "opinion")
# 「至少一条 fact」：只有观点/预测而没有事实的策略没有事实基础，
# 属于硬闸①要挡住的那类「看起来很专业但其实什么都没证明」。
EVIDENCE_KIND_FACT = "fact"
# 能支撑 target 的前瞻类证据。技术位/用户指定的目标价可能没有对应研报，
# 所以缺它只给 WARN，不阻断落卡。
FORWARD_LOOKING_KINDS: tuple[str, ...] = ("forecast", "opinion")
# 逐字引用的最小长度：短于此值基本可以断定是「概括」而非原文。
MIN_QUOTE_LEN = 8
# page 的占位符（小写后比较）。命中即等于「没有页码」——硬闸①要求
# source_ref + 页码，页码写 ``—`` 会让溯源退化成半条腿。
# 网页/接口类来源没有 PDF 页码，应填 URL 或锚点而不是占位符。
PAGE_PLACEHOLDERS: frozenset[str] = frozenset(
    {
        "",
        "-",
        "--",
        "—",
        "–",
        "n/a",
        "na",
        "none",
        "null",
        "nil",
        "tbd",
        "?",
        "??",
        "未知",
        "无",
        "不详",
        "待补",
        "/",
    }
)
# sources 条目：id 用于被 evidence.source_ref 引用；url / title 至少有一个，
# 否则来源无法定位，溯源链在最后一环断掉。
SOURCE_LOCATOR_KEYS: tuple[str, ...] = ("url", "title")
# 时间窗是封闭枚举：自由文本会让「3-6 个月」「半年」这类写法各写各的，
# 离线脚本就没法做时序对齐。
HORIZONS: tuple[str, ...] = ("1-5D", "1-4W", "1-3M", "3-6M", "6-12M", "12M+")

# ── 风控边界（position_sizing 与 strategy_lint 共用）────────────────────
# 单笔风险预算的合法区间。下限防止「0.01% 风险」这种无意义仓位，
# 上限防止一次失误打穿账户。
RISK_BUDGET_MIN_PCT = 0.1
RISK_BUDGET_MAX_PCT = 5.0
DEFAULT_LOT_SIZE = 100  # A 股一手 100 股
DEFAULT_MAX_WEIGHT_PCT = 40.0  # 单票权重上限
# 反过拟合：策略必须的「结构性旋钮」恰好 6 个（entry.low / entry.high /
# stop_loss / target / risk_budget_pct / max_weight_pct）。超出这个预算的
# 每一个额外旋钮都是作者新加的自由度，会触发 WARN。
TUNABLE_PARAM_BUDGET = 6
MIN_RISK_REWARD = 1.5

DISCLAIMER = "本研究性推演不构成投资建议，不涉及任何交易执行。"

# ── 字段名（供 lint 与离线脚本引用，避免字符串散落）─────────────────────
EVIDENCE_REQUIRED_KEYS: tuple[str, ...] = ("source_ref", "page", "quote", "kind")


def build_strategy_card(
    *,
    symbol: str,
    thesis: str,
    evidence: list[dict[str, Any]],
    entry_low: float,
    entry_high: float,
    stop_loss: float,
    target: float,
    invalidation: str,
    horizon: str,
    capital_total: float,
    sizing: dict[str, Any],
    lint: dict[str, Any] | None = None,
    disclaimer: str = DISCLAIMER,
    sources: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """组装一张策略卡（纯函数，不落盘、不校验）。

    ``sizing`` 必须原样来自 ``position_sizing`` 的返回——禁止手填，也禁止
    「参考工具给的数再修一下」。``strategy_lint`` 会重算与校验它。

    ``sources`` 是 ``evidence`` 的解析表：每条 source 至少给 ``id`` 与
    ``url``/``title`` 之一，``evidence.source_ref`` 必须能在其中找到，
    否则 ``strategy_lint`` 判为悬空引用（ERROR）。

    落盘由调用方负责：Agent 用 ``create_file`` 写到 ``/outputs/strategy.json``。
    """
    return {
        "version": STRATEGY_SCHEMA_VERSION,
        "capital_total": capital_total,
        "position": {
            "symbol": symbol,
            "thesis": thesis,
            "evidence": list(evidence),
            "entry": {"low": entry_low, "high": entry_high},
            "stop_loss": stop_loss,
            "target": target,
            "invalidation": invalidation,
            "horizon": horizon,
            "sizing": dict(sizing),
        },
        "lint": dict(lint or {}),
        "disclaimer": disclaimer,
        # sources 是 evidence 的解析表：strategy_lint 用它校验每条
        # evidence.source_ref 都指向一个真实声明过的来源。缺省为空列表而不是
        # 省略键——「没有来源」是 explicit 的事实，不是键的缺失。
        "sources": [dict(item) for item in sources or []],
    }


def dump_strategy_json(card: dict[str, Any]) -> str:
    """序列化策略卡为 UTF-8 JSON 文本。

    ``ensure_ascii=False``：evidence 的 quote 是中文逐字原文，转义成
    ``\\uXXXX`` 后人工不可读，而这份文件本来就是要给人核的。
    """
    return json.dumps(card, ensure_ascii=False, indent=2)


def position_of(card: dict[str, Any]) -> dict[str, Any]:
    """取 ``position`` 段；缺失或类型不对时返回空 dict（不抛异常）。"""
    raw = card.get("position")
    return raw if isinstance(raw, dict) else {}


def sizing_of(card: dict[str, Any]) -> dict[str, Any]:
    """取 ``position.sizing`` 段；缺失或类型不对时返回空 dict。"""
    raw = position_of(card).get("sizing")
    return raw if isinstance(raw, dict) else {}


__all__ = [
    "DEFAULT_LOT_SIZE",
    "DEFAULT_MAX_WEIGHT_PCT",
    "DISCLAIMER",
    "EVIDENCE_KINDS",
    "EVIDENCE_KIND_FACT",
    "EVIDENCE_REQUIRED_KEYS",
    "FORWARD_LOOKING_KINDS",
    "HORIZONS",
    "MIN_QUOTE_LEN",
    "MIN_RISK_REWARD",
    "PAGE_PLACEHOLDERS",
    "POSITION_SIZING_ID",
    "RISK_BUDGET_MAX_PCT",
    "RISK_BUDGET_MIN_PCT",
    "SOURCE_LOCATOR_KEYS",
    "STRATEGY_LINT_ID",
    "STRATEGY_SCHEMA_VERSION",
    "TUNABLE_PARAM_BUDGET",
    "build_strategy_card",
    "dump_strategy_json",
    "position_of",
    "sizing_of",
]
