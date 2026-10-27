"""Shared required facts for admission and run-bound input requests."""


def missing_facts(use_case: str, present: set[str]) -> dict[str, str]:
    if use_case not in {"plan_analysis", "holding_cost"}:
        return {}
    required = {
        "account.currency": "请选择账户币种",
        "account.capital_basis": "请说明资金口径（总资金 / 可用资金）",
        "account.as_of": "请选择资金数据时点",
        "plan.symbol": "请填写标的",
        "plan.market": "请选择市场",
        "plan.direction": "请选择方向",
        "plan.allocated_capital": "请先在会话资金中创建规划资金（从主账户可用资金中划出）",
    }
    if use_case == "holding_cost":
        required.update(
            {
                "trade.side": "请说明成交方向",
                "trade.quantity": "请填写成交数量",
                "trade.price": "已买入时请填写实际成交价，不能用现价或计划价替代",
                "trade.traded_at": "请填写成交时间",
            }
        )
    missing = {key: reason for key, reason in required.items() if key not in present}
    if not present & {"account.total_capital", "account.available_capital"}:
        missing["account.total_capital|account.available_capital"] = (
            "请如实填写当前账户总资金或可用资金"
        )
    return missing
