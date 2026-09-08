# 03 · `position_sizing` 工具实现

Type: task
Status: closed
Blocked by: (none)

**Goal**: 实现确定性仓位计算工具。**Agent 不得自行计算任何仓位数字**——这是本项目的可信度地基。

**Work**
新建 `plugins/tools/position_sizing.py`：

```python
@tool
async def position_sizing(
    capital_total: float,        # 总资金
    risk_budget_pct: float,      # 单笔风险预算（占总资金 %），必填，无默认
    entry_low: float,
    entry_high: float,
    stop_loss: float,            # 必填
    lot_size: int = 100,         # A股一手 100 股
    max_weight_pct: float = 40.0,
) -> str:
    """计算单笔仓位：风险预算与资金上限取小，向下取整到最小交易单位。

    采用保守口径：风险与资金占用均按入场区间上沿（最差成交价）计算。
    """
```

计算逻辑（纯算术，可单测）：

```
risk_per_share    = entry_high - stop_loss
risk_amount       = capital_total * risk_budget_pct / 100
shares_by_risk    = floor(risk_amount / risk_per_share)
shares_by_capital = floor(capital_total * max_weight_pct / 100 / entry_high)
shares            = min(shares_by_risk, shares_by_capital)
shares            = floor(shares / lot_size) * lot_size
amount            = shares * entry_high
weight_pct        = amount / capital_total * 100
```

返回 JSON：

```json
{"shares": 300, "amount": 435000, "weight_pct": 43.5,
 "risk_per_share": 140.0, "risk_amount": 42000,
 "constrained_by": "risk", "computed_by": "position_sizing@v1"}
```

**边界（必须在工具内处理，不让 LLM 猜）**
- `stop_loss >= entry_low` → 直接返回错误，不计算
- `shares < lot_size` → 返回 `shares=0` 且 `constrained_by="lot"`，并说明「风险预算不足以买入一手」
- `risk_budget_pct` 不在 [0.1, 5.0] → 返回错误（同时由 `strategy_lint` 兜底）
- 所有入参为正数校验

**注意**
- 注解不可放 `TYPE_CHECKING`（`@tool` 运行时 `get_type_hints` 生成 schema）
- 用 Google 风格 docstring，`Args:` 段会被解析成参数描述

**Acceptance**
- 手算 3 组已知用例，工具输出与手算一致
- 每个边界输入都返回明确错误信息，不抛未捕获异常
- 返回体恒含 `computed_by`（硬闸②依赖它）

## Answer

`plugins/tools/position_sizing.py`。

返回体：`ok / shares / amount / weight_pct / risk_per_share / risk_amount /
capital_budget / constrained_by / computed_by`，外加**入参回显**
`risk_budget_pct / entry_high / stop_loss / lot_size / max_weight_pct`。

- 入参回显不是装饰，是**必需**：`strategy_lint` 只读 `strategy.json`，
  不回显的话 Agent 就得手抄风险预算，而「数字经手一次就可能出错」
  正是本项目要挡的事。第一版漏了 `risk_budget_pct`，
  `tests/test_p0a_chain.py` 立刻以 `missing_risk_budget_pct` 变红。
- `constrained_by` 在两口径相等时取 `"risk"`，已写进 docstring。
- `shares < lot_size` → `shares=0` + `constrained_by="lot"` + `reason`。
  这是**合法结论**而非错误：Agent 应报告「该风险预算下无法建仓」，
  而不是自己把预算调大绕过去。
- 错误体也带 `computed_by`（契约是「返回体恒带」），但**不含任何可用数字**，
  所以从一次失败调用里捡不出东西。
- `bool` 被显式拒绝（它是 `int` 的子类，`stop_loss=True` 否则会静默变 1.0）；
  NaN / inf 同样拒绝——NaN 会让所有比较返回 False，把真正的价格错误吞掉。
- 已处理边界：`risk_budget_pct ∉ [0.1, 5.0]`、`stop_loss >= entry_low`、
  `entry_low > entry_high`、`max_weight_pct > 100`、非正数、非数字、`lot_size < 1`。
- 金额保留 2 位、比例 4 位，既避免浮点噪声，也让离线脚本能逐位比对。

## Comments
