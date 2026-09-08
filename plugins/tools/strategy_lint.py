"""strategy_lint — 确定性策略卡校验。

LLM 可以提出策略，**能不能落卡由本工具说了算**。设计上刻意做成纯函数：
不读文件、不调 LLM、无副作用——否则「校验」本身就成了另一个需要被校验的
东西，硬闸③就失去意义。

入参是 JSON 字符串（LLM 更容易传对），解析失败返回明确错误而不是抛异常：
一次格式错误不该让整个 ReAct 循环崩掉。
"""

from __future__ import annotations

import json
import math
from typing import Any

from frontier_agent.core.tool import tool
from plugins.corpus.strategy_schema import (
    DEFAULT_LOT_SIZE,
    DEFAULT_MAX_WEIGHT_PCT,
    EVIDENCE_KIND_FACT,
    EVIDENCE_KINDS,
    EVIDENCE_REQUIRED_KEYS,
    FORWARD_LOOKING_KINDS,
    HORIZONS,
    MIN_QUOTE_LEN,
    MIN_RISK_REWARD,
    PAGE_PLACEHOLDERS,
    POSITION_SIZING_ID,
    RISK_BUDGET_MAX_PCT,
    RISK_BUDGET_MIN_PCT,
    SOURCE_LOCATOR_KEYS,
    STRATEGY_LINT_ID,
    TUNABLE_PARAM_BUDGET,
)

# ``position`` 段里属于 schema 的键。出现在此集合之外的键会被计为
# 「作者新增的自由度」，计入反过拟合预算。
_KNOWN_POSITION_KEYS = frozenset(
    {
        "symbol",
        "thesis",
        "evidence",
        "entry",
        "stop_loss",
        "target",
        "invalidation",
        "horizon",
        "sizing",
        "parameters",
    }
)
# 注意：``sizing`` 段**不参与**额外旋钮统计。它是 position_sizing 原样搬过来的
# 机器产物，多一个回显字段不是作者新加的自由度；把它们算进反过拟合预算，
# 只会让每次工具加字段都误报 WARN，把真正的信号淹掉。


def _number(value: object) -> float | None:
    """转成有限 float，失败返回 ``None``（``bool`` 同样拒绝）。"""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) else None


def _err(code: str, message: str) -> dict[str, str]:
    return {"code": code, "level": "error", "message": message}


def _warn(code: str, message: str) -> dict[str, str]:
    return {"code": code, "level": "warn", "message": message}


def _result(
    errors: list[dict[str, str]],
    warnings: list[dict[str, str]],
) -> dict[str, Any]:
    """统一出口。``checked_by`` 让离线校验脚本能确认这份 lint 结果确实
    出自 strategy_lint，而不是 Agent 自己写的一句 ``"passed": true``。"""
    return {
        "passed": not errors,
        "errors": errors,
        "warnings": warnings,
        "checked_by": STRATEGY_LINT_ID,
    }


def _count_extra_knobs(position: dict[str, Any]) -> tuple[int, list[str]]:
    """统计超出「六个结构性旋钮」的额外可调参数。

    六个结构性旋钮是：entry.low、entry.high、stop_loss、target、
    risk_budget_pct、max_weight_pct——任何策略都必须选这六个数，它们不算
    过拟合。在此之上多出来的每一个键，都是作者新引入的自由度。
    """
    extras: list[str] = []
    for key in position:
        if key not in _KNOWN_POSITION_KEYS:
            extras.append(key)

    parameters = position.get("parameters")
    if isinstance(parameters, dict):
        extras.extend(f"parameters.{name}" for name in parameters)
    elif isinstance(parameters, list):
        extras.extend(f"parameters[{index}]" for index in range(len(parameters)))

    return len(extras), extras


def _is_blank(value: object) -> bool:
    """空值判定：``None`` 或空白字符串。

    数字 ``0`` **不算空**——页码 / 数量的 0 是合法取值，把它判空会让
    「第 0 页」这种边缘但合法的输入被误杀。
    """
    if value is None:
        return True
    if isinstance(value, str):
        return not value.strip()
    return False


def _is_placeholder_page(value: object) -> bool:
    """页码是否只是占位符（而非可定位的真实页码）。

    数字视为真实页码；字符串去空白后命中 ``PAGE_PLACEHOLDERS``（``—`` /
    ``N/A`` / ``未知`` 等）即判为占位符；其余类型（dict / list / bool）
    无法定位，同样拒绝。

    「写了个 ``—``」和「没写」在溯源上等价，都断开了硬闸①的最后一环。
    """
    if isinstance(value, bool):
        return True
    if isinstance(value, (int, float)):
        return False
    if not isinstance(value, str):
        return True
    return value.strip().lower() in PAGE_PLACEHOLDERS


def _declared_source_ids(card: dict[str, Any]) -> set[str] | None:
    """取 ``sources`` 段声明的 id 集合。

    ``sources`` 缺失 / 为空 / 非列表时返回 ``None``，让调用方能区分
    「声明了 0 个来源」（空集合，此时任何引用都是悬空）与
    「压根没声明」（``None``，报 ``missing_sources``）。
    """
    raw = card.get("sources")
    if not isinstance(raw, list) or not raw:
        return None
    ids: set[str] = set()
    for entry in raw:
        if isinstance(entry, dict):
            sid = entry.get("id")
            if isinstance(sid, str) and sid.strip():
                ids.add(sid.strip())
    return ids


def lint_strategy(card: dict[str, Any]) -> dict[str, Any]:
    """校验一张策略卡。纯函数：同样的输入永远给同样的输出。

    规则，与 ``docs/p0-implementation-spec.md`` §3.2 一致：

    ERROR —— 价格关系 / 风险预算区间 / 单票权重 / 失效条件非空 /
             时间窗枚举 / 止损存在 / 最小交易单位 / ``sizing.computed_by`` /
             evidence 存在性与结构 / 来源可解析 / 至少一条 fact
    WARN  —— 可调参数 <= 6 / 风险收益比 >= 1.5 / quote 过短 /
             目标价无前瞻证据支撑 / 证据重复 / 来源不可定位

    evidence 一组规则是**硬闸①的在线形态**：规格把「引用是否真能在原文里
    逐字找到」留给离线脚本，但空的、没页码的、引用了不存在来源的证据
    必须**当场**被挡住，否则「数字可溯源」就只是一句写在文档里的口号。

    ``passed`` 只由 ERROR 决定，warning 不阻断落卡。
    """
    errors: list[dict[str, str]] = []
    warnings: list[dict[str, str]] = []

    if not isinstance(card, dict):
        return _result(
            [_err("not_an_object", f"策略卡必须是 JSON 对象，实际 {type(card).__name__}")],
            warnings,
        )

    position = card.get("position")
    if not isinstance(position, dict):
        return _result([_err("missing_position", "策略卡缺少 position 段")], warnings)

    entry = position.get("entry")
    entry = entry if isinstance(entry, dict) else {}
    entry_low = _number(entry.get("low"))
    entry_high = _number(entry.get("high"))
    stop_loss = _number(position.get("stop_loss"))
    target = _number(position.get("target"))

    sizing = position.get("sizing")
    sizing = sizing if isinstance(sizing, dict) else {}
    shares = _number(sizing.get("shares"))
    amount = _number(sizing.get("amount"))
    weight_pct = _number(sizing.get("weight_pct"))
    risk_budget_pct = _number(sizing.get("risk_budget_pct"))
    lot_size = _number(sizing.get("lot_size"))
    max_weight_pct = _number(sizing.get("max_weight_pct"))
    if lot_size is None or lot_size < 1:
        lot_size = float(DEFAULT_LOT_SIZE)
    if max_weight_pct is None or max_weight_pct <= 0:
        max_weight_pct = float(DEFAULT_MAX_WEIGHT_PCT)

    # ── ERROR 1..3：价格关系 ──────────────────────────────────────────
    if stop_loss is None:
        errors.append(_err("missing_stop_loss", "stop_loss 必填且必须为数字"))
    elif entry_low is None:
        errors.append(_err("missing_entry_low", "entry.low 必填且必须为数字"))
    elif stop_loss >= entry_low:
        errors.append(
            _err(
                "stop_loss_not_below_entry",
                f"价格关系要求 stop_loss < entry.low，实际 {stop_loss} >= {entry_low}",
            )
        )

    if entry_low is not None and entry_high is not None and entry_low >= entry_high:
        errors.append(
            _err(
                "entry_range_inverted",
                f"价格关系要求 entry.low < entry.high，实际 {entry_low} >= {entry_high}",
            )
        )

    if entry_high is not None and target is not None and target <= entry_high:
        errors.append(
            _err(
                "target_not_above_entry",
                f"价格关系要求 entry.high < target，实际 {entry_high} >= {target}",
            )
        )

    # ── ERROR：风险预算区间 ────────────────────────────────────────────
    if risk_budget_pct is None:
        errors.append(
            _err(
                "missing_risk_budget_pct",
                "sizing.risk_budget_pct 必填且必须为数字",
            )
        )
    elif not RISK_BUDGET_MIN_PCT <= risk_budget_pct <= RISK_BUDGET_MAX_PCT:
        errors.append(
            _err(
                "risk_budget_out_of_range",
                f"risk_budget_pct 应在 [{RISK_BUDGET_MIN_PCT}, {RISK_BUDGET_MAX_PCT}]，"
                f"实际 {risk_budget_pct}",
            )
        )

    # ── ERROR：单票权重上限 ────────────────────────────────────────────
    if weight_pct is None:
        errors.append(_err("missing_weight_pct", "sizing.weight_pct 必填且必须为数字"))
    elif weight_pct > max_weight_pct:
        errors.append(
            _err(
                "weight_over_limit",
                f"weight_pct 应 <= max_weight_pct ({max_weight_pct})，实际 {weight_pct}",
            )
        )

    # ── ERROR：失效条件（无失效条件的策略不允许落卡）────────────────────
    invalidation = str(position.get("invalidation") or "").strip()
    if not invalidation:
        errors.append(
            _err(
                "missing_invalidation",
                "invalidation 必填：没有可证伪失效条件的策略不允许落卡",
            )
        )

    # ── ERROR：时间窗非空且为预设枚举 ──────────────────────────────────
    horizon = str(position.get("horizon") or "").strip()
    if not horizon:
        errors.append(_err("missing_horizon", f"horizon 必填，取值为 {list(HORIZONS)} 之一"))
    elif horizon not in HORIZONS:
        errors.append(
            _err(
                "horizon_not_in_enum",
                f"horizon 应取 {list(HORIZONS)} 之一，实际 {horizon!r}",
            )
        )

    # ── ERROR：最小交易单位 ────────────────────────────────────────────
    if shares is None:
        errors.append(_err("missing_shares", "sizing.shares 必填且必须为数字"))
    elif shares < lot_size:
        errors.append(
            _err(
                "shares_below_one_lot",
                f"shares 应 >= lot_size ({lot_size:g})，实际 {shares:g}——"
                "风险预算不足以买入一手时不应落卡，请报告不可行",
            )
        )
    elif shares % lot_size != 0:
        errors.append(
            _err(
                "shares_not_multiple_of_lot",
                f"shares 必须是 lot_size ({lot_size:g}) 的整数倍，实际 {shares:g}",
            )
        )

    # ── ERROR：算术出工具（硬闸②）──────────────────────────────────────
    # 这条是整个 P0a 的支点：任何绕过 position_sizing 自行编造仓位的策略
    # 都无法通过校验。删掉 computed_by 必须 ERROR——见
    # tests/test_strategy_lint.py::test_missing_computed_by_is_error。
    computed_by = str(sizing.get("computed_by") or "").strip()
    if not computed_by:
        errors.append(
            _err(
                "missing_computed_by",
                f"sizing.computed_by 必填，且只能来自 position_sizing 的返回值"
                f"（期望 {POSITION_SIZING_ID}）——禁止手填仓位",
            )
        )
    elif computed_by != POSITION_SIZING_ID:
        errors.append(
            _err(
                "unknown_computed_by",
                f"sizing.computed_by 应为 {POSITION_SIZING_ID}，实际 {computed_by!r}",
            )
        )

    # ── ERROR：sizing 内部自洽（硬闸②的在线形态）──────────────────────
    # 规格把「重算一遍、不信任字段」留给离线校验脚本；这里再做一次是为了让
    # 手改过数字的策略**当场**被挡住，而不是等跑完写进文件才发现。
    # 容差 0.01（金额到分、权重到 1bp）：足够宽，能容忍 position_sizing 的
    # 四舍五入与 JSON 序列化；又足够窄，改一手股就必定被抓到。
    capital_total = _number(card.get("capital_total"))
    if (
        shares is not None
        and entry_high is not None
        and amount is not None
        and abs(shares * entry_high - amount) > 0.01
    ):
        errors.append(
            _err(
                "amount_mismatch",
                f"sizing.amount 应等于 shares × entry.high = {shares:g} × {entry_high:g} "
                f"= {shares * entry_high:.2f}，实际 {amount:g}——sizing 必须原样来自 "
                "position_sizing，不得手改",
            )
        )
    if (
        amount is not None
        and weight_pct is not None
        and capital_total is not None
        and capital_total > 0
        and abs(amount / capital_total * 100 - weight_pct) > 0.01
    ):
        errors.append(
            _err(
                "weight_mismatch",
                f"sizing.weight_pct 应等于 amount / capital_total × 100 = "
                f"{amount / capital_total * 100:.4f}，实际 {weight_pct:g}",
            )
        )

    # ── ERROR：evidence 可溯源（硬闸①的在线形态）──────────────────────
    # 「引用是否真能在原文里逐字找到」留给离线脚本；这里挡的是结构性问题：
    # 没有证据 / 证据没有页码 / 引用了没声明过的来源 / 全是观点没有事实。
    # 这些一旦放过，硬闸①就退化成文档里的一句口号。
    evidence = position.get("evidence")
    source_ids = _declared_source_ids(card)
    kinds: set[str] = set()
    if not isinstance(evidence, list):
        errors.append(
            _err(
                "missing_evidence",
                f"position.evidence 必填且必须为列表（实际 "
                f"{type(evidence).__name__}）——没有证据的策略不允许落卡",
            )
        )
        evidence = []
    elif not evidence:
        errors.append(
            _err(
                "evidence_empty",
                "position.evidence 不能为空：没有任何证据支撑的策略不允许落卡",
            )
        )
    else:
        if source_ids is None:
            errors.append(
                _err(
                    "missing_sources",
                    "策略卡缺少 sources 段（或 sources 为空），无法验证 evidence "
                    "的来源——请声明 sources，每条至少含 id 与 url/title 之一",
                )
            )
        seen: set[tuple[str, str]] = set()
        for index, item in enumerate(evidence):
            label = f"evidence[{index}]"
            if not isinstance(item, dict):
                errors.append(
                    _err(
                        "evidence_not_object",
                        f"{label} 必须是对象，实际 {type(item).__name__}",
                    )
                )
                continue
            # 必填四键：缺一个，溯源链就断一环
            for key in EVIDENCE_REQUIRED_KEYS:
                if _is_blank(item.get(key)):
                    errors.append(
                        _err(
                            "evidence_missing_field",
                            f"{label} 的必填字段 {key!r} 缺失或为空"
                            f"（必填：{list(EVIDENCE_REQUIRED_KEYS)}）",
                        )
                    )
            kind = str(item.get("kind") or "").strip()
            if kind and kind not in EVIDENCE_KINDS:
                errors.append(
                    _err(
                        "evidence_bad_kind",
                        f"{label} 的 kind 应取 {list(EVIDENCE_KINDS)} 之一，实际 {kind!r}",
                    )
                )
            elif kind:
                kinds.add(kind)
            # page 写成占位符等于没有页码——网页/接口来源应填 URL 或锚点
            if "page" in item and _is_placeholder_page(item.get("page")):
                errors.append(
                    _err(
                        "evidence_page_placeholder",
                        f"{label} 的 page 是占位符 {item.get('page')!r}，无法定位到"
                        "原文——PDF 请填页码，网页/接口来源请填 URL 或锚点",
                    )
                )
            quote = str(item.get("quote") or "").strip()
            if quote and len(quote) < MIN_QUOTE_LEN:
                warnings.append(
                    _warn(
                        "evidence_quote_too_short",
                        f"{label} 的 quote 仅 {len(quote)} 字 < {MIN_QUOTE_LEN}："
                        "逐字原文通常更长，疑似概括而非引用",
                    )
                )
            ref = str(item.get("source_ref") or "").strip()
            if ref:
                if source_ids is not None and ref not in source_ids:
                    errors.append(
                        _err(
                            "evidence_unknown_source_ref",
                            f"{label} 的 source_ref {ref!r} 未在 sources 中声明"
                            f"（已声明：{sorted(source_ids)}）——source_ref 必须指向"
                            "一个真实存在的来源",
                        )
                    )
                fingerprint = (ref, quote)
                if fingerprint in seen:
                    warnings.append(
                        _warn(
                            "evidence_duplicate",
                            f"{label} 与前面的条目重复（source_ref={ref!r} 且 quote 相同）",
                        )
                    )
                seen.add(fingerprint)
        # 一致性：全是预测/观点、没有一条事实 = 无事实基础的推测
        if EVIDENCE_KIND_FACT not in kinds:
            errors.append(
                _err(
                    "evidence_no_fact",
                    f"evidence 中没有任何 kind={EVIDENCE_KIND_FACT!r} 的证据"
                    f"（实际出现的 kind：{sorted(kinds) or '无'}）——只有预测/观点"
                    "而没有事实支撑的策略不允许落卡",
                )
            )

    # ── ERROR / WARN：sources 条目自身 ─────────────────────────────────
    # 来源表本身也要能站得住：没有 id 就无法被引用，没有 url/title 就无法定位。
    declared_sources = card.get("sources")
    if isinstance(declared_sources, list):
        for index, entry in enumerate(declared_sources):
            label = f"sources[{index}]"
            if not isinstance(entry, dict):
                errors.append(
                    _err(
                        "source_not_object",
                        f"{label} 必须是对象，实际 {type(entry).__name__}",
                    )
                )
                continue
            sid = str(entry.get("id") or "").strip()
            if not sid:
                errors.append(
                    _err(
                        "source_missing_id",
                        f"{label} 缺少 id：没有 id 的来源无法被 evidence.source_ref 引用",
                    )
                )
                continue
            if not any(str(entry.get(key) or "").strip() for key in SOURCE_LOCATOR_KEYS):
                warnings.append(
                    _warn(
                        "source_missing_locator",
                        f"{label}（id={sid!r}）既无 url 也无 title，来源无法定位，"
                        "溯源在最后一环断掉",
                    )
                )

    # ── WARN：可调参数数量（反过拟合）──────────────────────────────────
    extra_count, extras = _count_extra_knobs(position)
    tunable = TUNABLE_PARAM_BUDGET + extra_count
    if tunable > TUNABLE_PARAM_BUDGET:
        warnings.append(
            _warn(
                "too_many_tunable_params",
                f"可调参数 {tunable} 个 > {TUNABLE_PARAM_BUDGET}（结构性旋钮之外的额外项："
                f"{', '.join(extras)}）——参数越多越可能是拟合出来的",
            )
        )

    # ── WARN：风险收益比 ───────────────────────────────────────────────
    if stop_loss is not None and entry_high is not None and target is not None:
        risk = entry_high - stop_loss
        if risk > 0:
            ratio = (target - entry_high) / risk
            if ratio < MIN_RISK_REWARD:
                warnings.append(
                    _warn(
                        "low_risk_reward",
                        f"风险收益比 {ratio:.2f} < {MIN_RISK_REWARD}"
                        f"（(target {target:g} - entry.high {entry_high:g}) / "
                        f"(entry.high {entry_high:g} - stop_loss {stop_loss:g})）",
                    )
                )

    # ── WARN：目标价与证据的一致性 ─────────────────────────────────────
    # target 是一个「关于未来的数」，正常情况下应由预测/观点类证据支撑。
    # 缺了不一定是错（可能是技术位或用户指定），所以只提醒不阻断。
    if target is not None and not kinds & set(FORWARD_LOOKING_KINDS):
        warnings.append(
            _warn(
                "target_without_forecast",
                f"target 有值（{target:g}）但 evidence 中没有 "
                f"{list(FORWARD_LOOKING_KINDS)} 类证据——目标价通常应来自预测或评级，"
                "请确认其依据",
            )
        )

    return _result(errors, warnings)


@tool
async def strategy_lint(strategy_json: str) -> str:
    """校验策略卡：价格关系、风险上限、必填字段、参数数量。返回 errors/warnings。

    落卡前**必须**调用本工具。返回 ``passed=false`` 时：修正后重新校验，
    **不得绕过**——直接把未通过校验的策略写进 /outputs/strategy.json 视为
    违反硬闸③。warning 不阻断，但必须在报告里向用户说明。

    错误信息刻意写成「期望 X 实际 Y」，让 Agent 知道该改哪个字段、改成什么，
    而不是只能盲目重试。

    Args:
        strategy_json: 策略卡的 JSON 字符串（即拟写入 /outputs/strategy.json
            的完整内容）。

    Returns:
        JSON 字符串：``{"passed": bool, "errors": [...], "warnings": [...]}``。
        errors / warnings 的每一项形如 ``{"code", "level", "message"}``。
        入参非法 JSON 时返回 ``passed=false`` 且 errors 含 ``invalid_json``，
        不抛异常。
    """
    try:
        card = json.loads(strategy_json)
    except (TypeError, ValueError) as exc:
        result = _result(
            [_err("invalid_json", f"strategy_json 不是合法 JSON：{exc}")],
            [],
        )
        return json.dumps(result, ensure_ascii=False)

    return json.dumps(lint_strategy(card), ensure_ascii=False)
