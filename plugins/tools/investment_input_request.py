"""Run-bound tool: the model declares that it lacks required user facts.

方案 A（2026-10-08 裁决）：worker 只表达**最小意图**（用途 + 原因），不写库、不指定字段与
owner。Run 结束时 worker 把意图落到自己目录的 ``input-request.json``，由持库凭据的 API 进程
按该用途对冻结快照裁决缺失字段后创建补数请求（``server.input_requests``）。

可变 dict 与 ``_METRICS`` 同一模式：ContextVar 持有的对象在子任务里修改对父流程可见。
"""

from __future__ import annotations

import contextvars
from typing import Any

from frontier_agent.core.tool import tool
from plugins.investment_requirements import missing_facts

_INTENT: contextvars.ContextVar[dict[str, Any] | None] = contextvars.ContextVar(
    "investment_input_intent", default=None
)

_ALLOWED_USE_CASES = frozenset({"plan_analysis", "holding_cost"})


def bind_input_intent() -> contextvars.Token[dict[str, Any] | None]:
    """Bind one mutable intent slot for this Run (worker calls before the loop)."""
    return _INTENT.set({"requested": None})


def pending_input_intent() -> dict[str, Any] | None:
    """Return the declared intent, if the model asked for missing facts."""
    state = _INTENT.get()
    if not state:
        return None
    requested = state.get("requested")
    return dict(requested) if isinstance(requested, dict) else None


def reset_input_intent(token: contextvars.Token[dict[str, Any] | None]) -> None:
    _INTENT.reset(token)


@tool
async def request_investment_input(use_case: str, reason: str) -> str:
    """当你要给出价位或仓位结论、但缺少用户自己的真实资料时，调用本工具请求补充。

    何时调用：用户在研究/询问某只股票，你准备给出买入卖出价、仓位或成本收益结论，而缺少
    用户自己的必要事实时调用一次并说明业务原因。字段由服务端按用途和冻结快照裁决，工具
    调用后不要自行列举、猜测或承诺弹窗字段，只说明结构化窗口会展示服务端裁决结果。
    何时不要调用：纯材料阅读、看研报、一般问答；也不要为了“顺便问一下”而调用。
    不要把缺失的值编出来，也不要用假设值、现价或建议价替代用户的真实资料。

    Args:
        use_case: 打算给出的结论类型，只支持 plan_analysis（价位/仓位）或 holding_cost（成本收益）。
        reason: 一句话说明为什么该业务结论依赖补数；不要自行列举待补字段。

    Returns:
        确认文本：已记录本次诉求，系统会向用户索取资料；本 Run 不应给出依赖缺失资料的结论。
    """
    if use_case not in _ALLOWED_USE_CASES:
        return (
            "无法记录：use_case 只支持 plan_analysis 或 holding_cost；"
            "其他结论请按材料阅读回答，不要请求资金/成交资料。"
        )
    text = (reason or "").strip()
    if not text:
        return "无法记录：请说明缺少哪类资料与用途。"
    state = _INTENT.get()
    if state is None:
        # 非业务 Run（未绑定意图槽）不产生请求，避免普通 Run 被误拦。
        return "本 Run 未启用业务资料补数，请按现有资料回答或说明资料不足。"
    from plugins.tools.investment_context import _context, _entry_value

    context = _context()
    if context is not None:
        present = {name for name in context.get("values", {}) if _entry_value(context, name) is not None}
        if not missing_facts(use_case, present):
            state["requested"] = None
            return (
                "当前冻结资料已满足该用途，无需创建补数请求。不要声称已创建弹窗或待办。"
                "入场价是分析情景，不是待补用户事实；未填写风险约束时仅可给出资金上限，不能声称已验证风险仓位。"
            )
    state["requested"] = {"use_case": use_case, "reason": text[:500]}
    return (
        "已记录补数意图，尚未创建待办：运行结束后服务端按冻结快照裁决是否创建结构化窗口；"
        "不要在回答中自行列举字段，也不要输出依赖缺失资料的个性化结论。"
    )
