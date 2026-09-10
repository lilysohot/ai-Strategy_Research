"""离线策略卡校验：三条硬闸的最终裁决。

为什么在线之外还要再跑一遍：``strategy_lint`` 是 Agent **自己调用**的，
我们只能从 trajectory 里相信它调过；而最终落盘的 json 也是 Agent **自己写**的。
这两件事之间没有必然联系——Agent 完全可以绕过校验，直接写一张挑不出毛病的
策略卡，再在 ``lint`` 段补一句 ``"passed": true``。

所以本模块**不信任任何落盘字段**，一律重算；它认的是**磁盘上那个文件**，
而不是 Agent 声称它做过什么。

与 ``strategy_lint`` 的分工：

- ``strategy_lint`` —— 在线、给 Agent 看：错误信息要指导它改哪个字段、
  改成什么，warning 允许放过。
- 本模块 —— 离线、给验收看：要么过要么不过，没有 WARN 的余地；
  也不提供「怎么改」的提示，因为它的读者是人不是模型。

三条硬闸对应 ``docs/plan/p0-research-kernel.md`` §2：

1. **数字可溯源**：每条 evidence 的 quote 能在 source_ref 指向的原文里逐字找到
2. **算术不出 LLM**：sizing 带 ``computed_by`` 且金额 / 权重可重算复核
3. **schema 完备**：止损 / 失效条件 / 时间窗必填 + lint 契约成立

用法::

    python -m plugins.corpus.verify path/to/strategy.json

溯源校验需要一个「source_ref -> 原文」的解析器（P0b 的 corpus 会提供）。
没给解析器时该闸标记为 **skipped 而非 passed**——校验不了就是没验过，
不能算通过。默认 ``strict=True``：有任一闸 skipped，整卡判不通过。
"""

from __future__ import annotations

import json
import math
import re
import sys
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from plugins.corpus.service import get_service
from plugins.corpus.strategy_schema import (
    HORIZONS,
    POSITION_SIZING_ID,
    STRATEGY_LINT_ID,
    position_of,
    sizing_of,
)
from plugins.tools.strategy_lint import lint_strategy

# source_ref -> 原文全文；返回 None 表示该来源无法解析。
SourceResolver = Callable[[str], str | None]

GATE_TRACEABILITY = "traceability"
GATE_ARITHMETIC = "arithmetic"
GATE_SCHEMA = "schema"
# 市场数据溯源闸（M6）：`ths:` 引用走**响应留痕**比对，与语料库溯源分开计，
# 避免"真的市场数字因 corpus 里没有该 doc 而被判无法解析"。
GATE_MARKET = "market"
# 展示顺序 = 硬闸编号顺序，便于人对着验收表逐条勾
GATE_ORDER: tuple[str, ...] = (GATE_TRACEABILITY, GATE_MARKET, GATE_ARITHMETIC, GATE_SCHEMA)

# ── 市场数据常量（M6）────────────────────────────────────────────────────
#: 市场数据来源前缀：`ths:<thscode>:<request_id>`
MARKET_PREFIX = "ths:"
#: 合法形态：必须带 thscode 与 request_id（缺 request_id 即悬空引用）
MARKET_REF_RE = re.compile(r"^ths:(\d{6}\.(?:SH|SZ|BJ|OF|HK)):([A-Za-z0-9_-]+)$")
#: 快照新鲜度阈值（自然日）：超过则 WARN（无日历表，按自然日粗判）
DEFAULT_STALE_DAYS = 5

# 金额到分、权重到 1bp：足够容忍 position_sizing 的取整与 JSON 序列化，
# 又足够窄到「改一手股」必定被抓到。与 strategy_lint 内重算同一容差。
RECOMPUTE_TOLERANCE = 0.01

_PASSED = "passed"
_FAILED = "failed"
_SKIPPED = "skipped"

_GATE_TITLES = {
    GATE_TRACEABILITY: "硬闸① 数字可溯源（语料库）",
    GATE_MARKET: "硬闸①扩 市场数据可溯源（留痕比对）",
    GATE_ARITHMETIC: "硬闸② 算术不出 LLM",
    GATE_SCHEMA: "硬闸③ schema 完备 + lint 契约",
}


def _number(value: object) -> float | None:
    """转有限 float，失败返回 ``None``（``bool`` 同样拒绝）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _problem(gate: str, code: str, message: str) -> dict[str, str]:
    return {"gate": gate, "code": code, "message": message}


def _gate_traceability(
    card: dict[str, Any],
    resolver: SourceResolver | None,
) -> tuple[str, list[dict[str, str]], int, int]:
    """硬闸①：每条 evidence 的 quote 必须能在原文里**逐字**找到。

    返回 ``(status, problems, total, traced)``：``total``/``traced`` 用于算
    「溯源命中率」——plan §7.2 要求命中率 100%（未溯源数字数 = 0）。

    这是 plan §9 记的「宽松版」：只要 quote 出现在被引用的那份原文中即算溯源。
    它抓不出「张冠李戴」（引了 A 的话安在 B 头上），但能 100% 抓出「完全编造」。

    resolver 为 ``None`` 时返回 ``skipped``——**不是** ``passed``。
    """
    evidence = position_of(card).get("evidence")
    if not isinstance(evidence, list) or not evidence:
        return _FAILED, [
            _problem(
                GATE_TRACEABILITY,
                "no_evidence",
                "没有 evidence 可溯源：无法验证任何数字的来源",
            )
        ], 0, 0

    # 市场数据引用（`ths:` 前缀）交给**市场溯源闸**（M6）处理，本闸只管语料库来源——
    # 否则 corpus 里根本没有该 doc，会被一律判成「无法解析到原文」，
    # 结果是「真的市场数字也进不了卡」（M6 要修的正是这个）。
    corpus_items = [
        item
        for item in evidence
        if isinstance(item, dict)
        and not str(item.get("source_ref") or "").strip().startswith(MARKET_PREFIX)
    ]
    total = len(corpus_items)
    if resolver is None:
        return _SKIPPED, [], total, 0

    problems: list[dict[str, str]] = []
    traced = 0

    for index, item in enumerate(corpus_items):
        label = f"evidence[{index}]"
        quote = str(item.get("quote") or "").strip()
        ref = str(item.get("source_ref") or "").strip()
        if not quote or not ref:
            problems.append(
                _problem(
                    GATE_TRACEABILITY,
                    "incomplete_evidence",
                    label + " 缺少 source_ref 或 quote，溯源链断开",
                )
            )
            continue
        source_text = resolver(ref)
        if source_text is None:
            problems.append(
                _problem(
                    GATE_TRACEABILITY,
                    "source_unresolvable",
                    label + " 的 source_ref " + repr(ref) + " 无法解析到原文",
                )
            )
            continue
        if quote not in source_text:
            problems.append(
                _problem(
                    GATE_TRACEABILITY,
                    "quote_not_found",
                    label + " 的 quote 未在 " + repr(ref) + " 中逐字出现：" + repr(quote[:60]),
                )
            )
            continue
        # 走到这里说明 quote 已在原文里逐字找到：成功溯源一条
        traced += 1
    return (_FAILED if problems else _PASSED), problems, total, traced


def _market_evidence(card: dict[str, Any]) -> list[tuple[int, dict[str, Any]]]:
    """取所有 `ths:` 市场引用（含原始下标，便于报错定位）。"""
    evidence = position_of(card).get("evidence")
    if not isinstance(evidence, list):
        return []
    return [
        (index, item)
        for index, item in enumerate(evidence)
        if isinstance(item, dict)
        and str(item.get("source_ref") or "").strip().startswith(MARKET_PREFIX)
    ]


def _market_as_of_ms(item: dict[str, Any]) -> int | None:
    """解析引用时点：`quote` 里的 `as_of=<毫秒>` 优先，其次 `page`（ISO 时间）。"""
    match = re.search(r"as_of=(\d{10,13})", str(item.get("quote") or ""))
    if match:
        return int(match.group(1))
    page = str(item.get("page") or "").strip()
    try:
        return int(datetime.fromisoformat(page).timestamp() * 1000)
    except ValueError:
        return None


def _gate_market_traceability(
    card: dict[str, Any],
    market_resolver: SourceResolver | None,
) -> tuple[str, list[dict[str, str]], int, int]:
    """市场溯源闸（M6）：`ths:` 引用必须在**响应留痕**里逐字命中。

    与语料库溯源同一套 `quote in text` 判定，但文本来源是 run 目录的响应留痕
    （§5.5 方案 A）。`market_resolver is None`（没给 `--market-trace`）⇒ `skipped`：
    按 §5.5 方案 B 语义，**验不了就是没验过**，strict 下整卡不通过。
    """
    items = _market_evidence(card)
    if not items:
        return _PASSED, [], 0, 0
    if market_resolver is None:
        return _SKIPPED, [], len(items), 0

    problems: list[dict[str, str]] = []
    traced = 0
    for index, item in items:
        label = f"evidence[{index}]"
        ref = str(item.get("source_ref") or "").strip()
        quote = str(item.get("quote") or "").strip()

        if not MARKET_REF_RE.match(ref):
            problems.append(
                _problem(
                    GATE_MARKET,
                    "market_ref_malformed",
                    label + " 的 ths 引用不合法（应为 ths:<thscode>:<request_id>）：" + repr(ref),
                )
            )
            continue
        if not quote:
            problems.append(_problem(GATE_MARKET, "incomplete_evidence", label + " 缺少 quote"))
            continue

        text = market_resolver(ref)
        if text is None:
            problems.append(
                _problem(
                    GATE_MARKET,
                    "source_unresolvable",
                    label + " 在留痕中找不到该次调用：" + repr(ref),
                )
            )
            continue
        if quote not in text:
            problems.append(
                _problem(
                    GATE_MARKET,
                    "quote_not_found",
                    label + " 的 quote 未在那次真实响应中出现（疑似编造）：" + repr(quote[:60]),
                )
            )
            continue
        traced += 1
    return (_FAILED if problems else _PASSED), problems, len(items), traced


def check_market_consistency(
    card: dict[str, Any],
    *,
    now_ms: int | None = None,
    stale_days: int = DEFAULT_STALE_DAYS,
    band_pct: float = 20.0,
) -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    """市场一致性检查（M6）。返回 ``(errors, warnings)``。

    - ERROR（阻断）：`adjust_mismatch`（口径混用必错）、`financial_lookahead`（前视偏差）；
    - WARN（不阻断，提示复核）：`market_quote_stale`（快照太旧 / 缺时点）、
      `price_out_of_band`（现价偏离建仓区间）。

    边界：这些检查抓的是「**引用方式**不合适」，抓不了「数字本身错」——那是溯源闸的职责。
    """
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []
    items = _market_evidence(card)
    if not items:
        return errors, warnings

    now = now_ms or int(datetime.now().timestamp() * 1000)
    max_age_ms = stale_days * 24 * 60 * 60 * 1000
    adjusts: set[str] = set()
    entry = position_of(card).get("entry") or {}
    low = _number(entry.get("low"))
    high = _number(entry.get("high"))

    for index, item in items:
        label = f"evidence[{index}]"
        quote = str(item.get("quote") or "")

        as_of = _market_as_of_ms(item)
        if as_of is None:
            warnings.append(
                _problem(
                    GATE_MARKET,
                    "market_quote_stale",
                    label + " 引用市场数字但没有可解析的 as_of 时点（实时价格必须带时点）",
                )
            )
        elif now - as_of > max_age_ms:
            days = (now - as_of) // (24 * 60 * 60 * 1000)
            warnings.append(
                _problem(
                    GATE_MARKET,
                    "market_quote_stale",
                    f"{label} 的 as_of 距今约 {days} 天（阈值 {stale_days}）⇒ 价格可能已过时，请复核",
                )
            )

        price = re.search(r"last_price=([\d.]+)", quote)
        if price and low is not None and high is not None:
            value = float(price.group(1))
            if value < low * (1 - band_pct / 100) or value > high * (1 + band_pct / 100):
                warnings.append(
                    _problem(
                        GATE_MARKET,
                        "price_out_of_band",
                        f"{label} 现价 {value} 明显偏离建仓区间 [{low}, {high}]（阈值 ±{band_pct}%）⇒ 请复核",
                    )
                )

        adjust = re.search(r"adjust=([a-z]+)", quote)
        if adjust:
            adjusts.add(adjust.group(1))

        # 前视偏差：evidence 显式带 report_date_ms 时才校验（可选字段，不带不误报）
        report_ms = item.get("report_date_ms")
        if (
            isinstance(report_ms, (int, float))
            and not isinstance(report_ms, bool)
            and int(report_ms) > now
        ):
                errors.append(
                    _problem(
                        GATE_MARKET,
                        "financial_lookahead",
                        f"{label} 引用的财报 report_date_ms 晚于当前时点 ⇒ 用未来数据解释过去（§9 坑 2）",
                    )
                )

    if len(adjusts) > 1:
        errors.append(
            _problem(
                GATE_MARKET,
                "adjust_mismatch",
                "同一张卡混用了不同复权口径（" + "、".join(sorted(adjusts)) + "）⇒ 数值不可比",
            )
        )
    return errors, warnings


def _gate_arithmetic(card: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """硬闸②：sizing 必须来自 position_sizing，且金额 / 权重可重算复核。

    不比对某个期望值，而是**重新推一遍**：``shares × entry.high`` 必须等于
    ``amount``，``amount / capital_total`` 必须等于 ``weight_pct``。
    LLM 自己算的数很难在三处同时自洽。
    """
    problems: list[dict[str, str]] = []
    position = position_of(card)
    sizing = sizing_of(card)

    computed_by = str(sizing.get("computed_by") or "").strip()
    if computed_by != POSITION_SIZING_ID:
        problems.append(
            _problem(
                GATE_ARITHMETIC,
                "computed_by_mismatch",
                "sizing.computed_by 应为 "
                + repr(POSITION_SIZING_ID)
                + "，实际 "
                + repr(computed_by)
                + "——仓位不是 position_sizing 算出来的",
            )
        )

    entry = position.get("entry")
    entry = entry if isinstance(entry, dict) else {}
    shares = _number(sizing.get("shares"))
    amount = _number(sizing.get("amount"))
    weight_pct = _number(sizing.get("weight_pct"))
    entry_high = _number(entry.get("high"))
    capital_total = _number(card.get("capital_total"))

    # 显式 ``is not None`` 而不是 ``None not in (...)``：后者人读起来更短，
    # 但不会让类型检查器收窄，下面的算术运算会全体报类型错误。
    if shares is not None and entry_high is not None and amount is not None:
        expected = shares * entry_high
        if abs(expected - amount) > RECOMPUTE_TOLERANCE:
            problems.append(
                _problem(
                    GATE_ARITHMETIC,
                    "amount_mismatch",
                    f"amount 应为 shares × entry.high = {shares:g} × {entry_high:g} = {expected:.2f}，实际 {amount:g}",
                )
            )
    if (
        amount is not None
        and weight_pct is not None
        and capital_total is not None
        and capital_total > 0
    ):
        expected = amount / capital_total * 100
        if abs(expected - weight_pct) > RECOMPUTE_TOLERANCE:
            problems.append(
                _problem(
                    GATE_ARITHMETIC,
                    "weight_mismatch",
                    f"weight_pct 应为 amount / capital_total × 100 = {expected:.4f}，实际 {weight_pct:g}",
                )
            )
    return (_FAILED if problems else _PASSED), problems


def _gate_schema(card: dict[str, Any]) -> tuple[str, list[dict[str, str]]]:
    """硬闸③：必填字段完备 + lint 契约成立。

    lint 契约是三重的，缺一不可：

    1. ``lint`` 段存在且被 ``strategy_lint`` 盖过章（``checked_by``）
    2. 卡里记录的 ``passed`` 为真
    3. **把这张卡重新喂给 ``strategy_lint``，结果仍为真，且错误条数与卡内
       记录的一致**

    第 3 条是关键：它挡住「先写一张漂亮的卡，再自己补一句 passed=true」。
    只看前两条的话，Agent 完全可以自产自销。
    """
    problems: list[dict[str, str]] = []
    position = position_of(card)

    # 必填三项严格对齐 plan §2 硬闸③「止损 / 失效条件 / 时间窗」。
    # 刻意**不**把 target 算进来：strategy_lint 也不强制它。若这里加码，
    # 会出现「过得了在线校验、却过不了离线校验」的困惑，而这两处本该同源。
    for key in ("stop_loss", "invalidation", "horizon"):
        if key not in position or position.get(key) in (None, ""):
            problems.append(
                _problem(
                    GATE_SCHEMA,
                    "missing_required_field",
                    "position." + key + " 必填，缺失或为空",
                )
            )
    horizon = str(position.get("horizon") or "").strip()
    if horizon and horizon not in HORIZONS:
        problems.append(
            _problem(
                GATE_SCHEMA,
                "horizon_not_in_enum",
                "position.horizon 应取 " + repr(list(HORIZONS)) + " 之一，实际 " + repr(horizon),
            )
        )

    # ── lint 契约 1 & 2 ────────────────────────────────────────────────
    lint = card.get("lint")
    if not isinstance(lint, dict):
        problems.append(
            _problem(
                GATE_SCHEMA,
                "lint_section_missing",
                "策略卡缺少 lint 段：无法证明它被 strategy_lint 校验过",
            )
        )
    else:
        checked_by = str(lint.get("checked_by") or "").strip()
        if checked_by != STRATEGY_LINT_ID:
            problems.append(
                _problem(
                    GATE_SCHEMA,
                    "lint_not_stamped",
                    "lint.checked_by 应为 " + repr(STRATEGY_LINT_ID) + "，实际 " + repr(checked_by),
                )
            )
        stored_passed = lint.get("passed")
        if not isinstance(stored_passed, bool):
            problems.append(
                _problem(
                    GATE_SCHEMA,
                    "lint_passed_not_recorded",
                    "lint.passed 缺失或不是布尔值——校验结果的**结论**没有被固化，"
                    "离线无法确认这张卡真的通过了校验",
                )
            )
        elif stored_passed is not True:
            problems.append(
                _problem(
                    GATE_SCHEMA,
                    "lint_recorded_failure",
                    "卡内记录的 lint.passed 不是 true：未通过校验的卡不该落盘",
                )
            )

    # ── lint 契约 3：重算，不信任落盘结论 ──────────────────────────────
    fresh = lint_strategy(card)
    if not fresh["passed"]:
        codes = ", ".join(item["code"] for item in fresh["errors"])
        problems.append(
            _problem(
                GATE_SCHEMA,
                "lint_recheck_failed",
                "重跑 strategy_lint 未通过（" + codes + "）——卡内容与「已通过校验」的结论不符",
            )
        )
    if isinstance(lint, dict):
        stored_errors = lint.get("errors")
        stored_count = len(stored_errors) if isinstance(stored_errors, list) else -1
        fresh_count = len(fresh["errors"])
        if stored_count != fresh_count:
            problems.append(
                _problem(
                    GATE_SCHEMA,
                    "lint_result_diverged",
                    f"卡内记录的 errors 条数（{stored_count}）与重算结果"
                    f"（{fresh_count}）不一致——卡里的 lint 段不是本次校验的产物",
                )
            )
    return (_FAILED if problems else _PASSED), problems


def verify_card(
    card: dict[str, Any],
    *,
    source_resolver: SourceResolver | None = None,
    market_resolver: SourceResolver | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """校验一张策略卡，返回裁决报告。

    Args:
        card: 已解析的策略卡 dict。
        source_resolver: ``source_ref -> 原文`` 的解析器；为 ``None`` 时
            溯源闸标记 skipped。P0b 的 corpus 接进来后由它提供。
        strict: 为 ``True`` 时，任一闸 skipped 则整卡判不通过。
            默认 True——**校验不了就是没验过**，不能默认放行。

    Returns:
        ``{"passed": bool, "gates": {...}, "traceability": {...},
        "problems": [...], "skipped": [...]}``。
        ``gates`` 每项形如 ``{"status": passed|failed|skipped, "problems": [...]}``。
        ``traceability`` 形如 ``{"total": int, "traced": int, "rate": float,
        "skipped": bool}``——plan §7.2 要求命中率 100%。
    """
    statuses: dict[str, str] = {}
    problems: list[dict[str, str]] = []

    traceability_status, traceability_problems, trace_total, trace_traced = _gate_traceability(
        card,
        source_resolver,
    )
    market_status, market_problems, market_total, market_traced = _gate_market_traceability(
        card, market_resolver
    )
    market_errors, market_warnings = check_market_consistency(card)
    arithmetic_status, arithmetic_problems = _gate_arithmetic(card)
    schema_status, schema_problems = _gate_schema(card)

    statuses[GATE_TRACEABILITY] = traceability_status
    statuses[GATE_MARKET] = market_status
    statuses[GATE_ARITHMETIC] = arithmetic_status
    statuses[GATE_SCHEMA] = schema_status
    problems.extend(traceability_problems)
    problems.extend(market_problems)
    problems.extend(market_errors)
    problems.extend(arithmetic_problems)
    problems.extend(schema_problems)

    skipped = [gate for gate in GATE_ORDER if statuses[gate] == _SKIPPED]
    passed = not problems and not (strict and skipped)

    return {
        "passed": passed,
        "gates": {
            gate: {
                "status": statuses[gate],
                "problems": [item for item in problems if item["gate"] == gate],
            }
            for gate in GATE_ORDER
        },
        # 溯源命中率：未溯源数字数 = 0 即 rate == 1.0。skipped 时 rate 无意义，记 0。
        "traceability": {
            "total": trace_total,
            "traced": trace_traced,
            "rate": (trace_traced / trace_total) if trace_total else 0.0,
            "skipped": traceability_status == _SKIPPED,
        },
        "problems": problems,
        # 市场一致性 WARN（不阻断，提示复核）：价格太旧 / 缺时点 / 偏离建仓区间
        "warnings": market_warnings,
        "market_traceability": {
            "total": market_total,
            "traced": market_traced,
            "skipped": market_status == _SKIPPED,
        },
        "skipped": skipped,
    }


def verify_file(
    path: str | Path,
    *,
    source_resolver: SourceResolver | None = None,
    market_resolver: SourceResolver | None = None,
    strict: bool = True,
) -> dict[str, Any]:
    """读磁盘上的 strategy.json 并校验。

    入口刻意走文件而不是走 dict：要验的就是**落盘的那份**，
    用已经解析好的对象会掩盖「写文件时被改过」这类问题。
    """
    card = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(card, dict):
        return {
            "passed": False,
            "gates": {gate: {"status": _FAILED, "problems": []} for gate in GATE_ORDER},
            "problems": [
                _problem(
                    GATE_SCHEMA,
                    "not_an_object",
                    "strategy.json 顶层必须是对象，实际 " + type(card).__name__,
                )
            ],
            "skipped": [],
        }
    return verify_card(card, source_resolver=source_resolver, strict=strict)


def format_report(report: dict[str, Any]) -> str:
    """把裁决报告渲染成人能逐条勾选的文本。"""
    marks = {_PASSED: "[PASS]", _FAILED: "[FAIL]", _SKIPPED: "[SKIP]"}
    verdict = "通过" if report["passed"] else "不通过"
    lines = ["策略卡校验：" + verdict, ""]
    for gate in GATE_ORDER:
        info = report["gates"][gate]
        lines.append("{} {}".format(marks.get(info["status"], "[????]"), _GATE_TITLES[gate]))
        for item in info["problems"]:
            lines.append("      - " + item["code"] + "：" + item["message"])
    tr = report.get("traceability")
    if tr and not tr.get("skipped"):
        lines.append("")
        lines.append(
            f"数字溯源命中率：{tr['traced']}/{tr['total']} ({tr['rate'] * 100:.1f}%)"
        )
    if report["skipped"]:
        lines.append("")
        lines.append(
            "注：以下闸未能校验（缺少 source_resolver），strict 模式计为不通过："
            + "、".join(report["skipped"])
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：``python -m plugins.corpus.verify <strategy.json> [--corpus <dsn>]``。

    溯源闸（`source_resolver`）由 PG 的 ``CorpusService`` 提供：默认连 ``CORPUS_DSN``
    环境变量（缺省本机 ``postgresql://postgres:postgres@localhost:5432/postgres``），
    也可用 ``--corpus <dsn>`` 覆盖。不给 ``--corpus`` 也会连默认 PG，确保硬闸①始终
    能真正比对原文（而不是标记 skipped）。

    退出码刻意区分「不通过」(1) 与「跑不起来」(2)：CI 里这两种要分开处理，
    前者是策略的问题，后者是校验本身的问题，混在一起会掩盖后者。
    """
    args = list(sys.argv[1:] if argv is None else argv)
    corpus_dsn: str | None = None
    market_trace_dir: str | None = None
    paths: list[str] = []
    rest = list(args)
    while rest:
        token = rest.pop(0)
        if token == "--corpus":
            corpus_dsn = rest.pop(0) if rest else None
        elif token == "--market-trace":
            market_trace_dir = rest.pop(0) if rest else None
        else:
            paths.append(token)
    if not paths:
        print(__doc__)
        return 2

    resolver: SourceResolver | None = None
    try:
        svc = get_service(corpus_dsn)
        resolver = svc.source_resolver()
    except Exception as exc:
        print("无法连接语料库（PG）：" + str(exc))
        return 2

    # 市场溯源闸（M6）：`ths:` 引用走 run 目录留痕。延迟 import —— verify 核心
    # 不依赖 market 实现（§5.7 纪律：resolver 由调用方注入），只有 CLI 用到才加载。
    market_resolver: SourceResolver | None = None
    if market_trace_dir:
        from plugins.market.trace_store import resolve_market_source

        def market_resolver(ref: str) -> str | None:
            return resolve_market_source(ref, market_trace_dir)

    try:
        report = verify_file(
            paths[0], source_resolver=resolver, market_resolver=market_resolver
        )
    except (OSError, ValueError) as exc:
        print("无法读取策略卡：" + str(exc))
        return 2
    print(format_report(report))
    return 0 if report["passed"] else 1


__all__ = [
    "GATE_ARITHMETIC",
    "GATE_ORDER",
    "GATE_SCHEMA",
    "GATE_TRACEABILITY",
    "format_report",
    "verify_card",
    "verify_file",
]


if __name__ == "__main__":
    raise SystemExit(main())
