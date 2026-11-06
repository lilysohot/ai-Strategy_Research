"""The monitoring request carries trigger facts, not reports or UI state."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any


def build_monitor_prompt(
    *,
    sequence: int | None,
    received_at_ms: int,
    now: datetime,
    hits: list[dict[str, Any]],
    prior_analyses: int,
) -> str:
    """Freeze only the facts needed to interpret this signal; read live state via tools."""
    conditions = []
    for hit in hits:
        condition = {
            key: hit[key]
            for key in (
                "id",
                "version",
                "symbol",
                "market",
                "currency",
                "quote_basis",
                "direction",
                "threshold",
                "trigger_mode",
                "trigger_reason",
                "price",
                "previous_price",
                "previous_observed_at_ms",
                "observed_at_ms",
                "task",
            )
            if key in hit
        }
        rationale = hit.get("rationale") or {}
        condition["sampled_crossing"] = hit.get("trigger_reason") in {
            "up_cross",
            "down_cross",
            "enter_range",
        }
        if rationale.get("reason"):
            condition["reason"] = rationale["reason"]
        if rationale.get("evidence_refs"):
            condition["evidence_refs"] = rationale["evidence_refs"]
        conditions.append(condition)
    facts = {
        "round": sequence,
        "received_at_ms": received_at_ms,
        "wait_seconds": max(0, int(now.timestamp() - received_at_ms / 1000)),
        "prior_analyses": prior_analyses,
        "triggered_targets": conditions,
    }
    instruction = (
        "价格监控复核。以下是本轮触发事实，不是当前行情或待执行指令。\n"
        "先读取 get_watch_targets 获取全部当前目标、版本和暂停状态，再核验最新行情；"
        "结合本轮提供的持仓资料综合分析，缺少持仓不阻止研究。"
        "区间内达标不等于突破区间边界；价格已离开触发条件时说明变化。"
        "initial_condition_met 仅表示初始化后的首次采样达标，不是新一次穿越；"
        "只有 sampled_crossing=true 才有前后两次采样的穿越证据。"
        "日内最高/最低价不提供发生时刻，不能据重复出现的同一低点增加回踩次数，"
        "也不能把触发次数当作支撑验证次数；无法确认新增穿越时明确说明。"
        "按任务与设价依据判断保留或更新目标，通过工具保存并如实报告回执。"
        "价格和长期依据未变时直接保留，不必为了提交而改写说明。"
        "带时点的历史快照并非错误，现价、距离、盈亏留在本轮答复，勿逐轮写进长期任务。"
        "行情返回的 display_numbers、monitoring_metrics 是统一计算口径："
        "金额换算和百分比分母使用对应字段，不重新心算或混用上下方距离；"
        "登记买入统计不代表完整实际持仓。写入需引用本轮 evidence_ref。"
        "只说明本轮新增变化、判断及目标处理；未变化的背景不重复成文。\n"
    )
    if prior_analyses >= 2:
        instruction += (
            "已多次触发，请评估这些价格的长期监控价值；遵循各目标的触发模式，不因次数自动停用。\n"
        )
    return instruction + json.dumps(facts, ensure_ascii=False, separators=(",", ":"))
