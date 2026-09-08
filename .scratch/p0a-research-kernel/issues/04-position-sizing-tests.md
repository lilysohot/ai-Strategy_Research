# 04 · `position_sizing` 单测

Type: task
Status: closed
Blocked by: 03

**Goal**: 锁死 03 的算术与边界行为，防止后续改动静默破坏仓位计算。

**Work**
新建 `tests/test_position_sizing.py`（pytest，`asyncio_mode="auto"`）。
必测用例：

| 类别 | 用例 |
|---|---|
| 基准 | 常规入参 → shares/amount/weight_pct 与手算一致 |
| 风险约束 | `shares_by_risk < shares_by_capital` → `constrained_by == "risk"` |
| 资金约束 | `shares_by_capital < shares_by_risk` → `constrained_by == "capital"` |
| 取整 | 非整手结果向下取整到 `lot_size` 倍数 |
| 边界 | `shares < lot_size` → `shares == 0` 且 `constrained_by == "lot"` |
| 边界 | `stop_loss >= entry_low` → 返回错误，不计算 |
| 边界 | `risk_budget_pct` 越界（<0.1 或 >5.0）→ 返回错误 |
| 边界 | 非正数入参 → 返回错误 |
| 契约 | 返回体恒含 `computed_by == "position_sizing@v1"` |
| 确定性 | 同入参调用两次结果完全一致 |

**验收命令**
```
uv run pytest tests/test_position_sizing.py -q
uv run ruff check plugins/tools/position_sizing.py tests/test_position_sizing.py
```

**Acceptance**
- 全部用例通过（目标 ≥10 条）
- ruff 全绿
- 覆盖上表每一类

## Answer

`tests/test_position_sizing.py`，**15 例全过**。

| 类别 | 用例数 | 覆盖 |
|---|---|---|
| 基准 | 1 | 手算基准（5_200 股 / 99_840 元 / 9.984%）逐字段比对 |
| 约束来源 | 2 | `constrained_by` == `risk` / `capital` |
| 取整 | 2 | 向下取整到手；自定义 `lot_size=500` |
| 边界 | 7 | 不足一手（`shares=0`+`reason`）、`stop_loss>=entry_low`（两例）、风险预算上下越界、入场区间倒置、非正数（4 个字段）、非数字、NaN、`lot_size=0` |
| 契约 | 2 | 成功/失败两条路径都带 `computed_by`；同入参两次结果完全一致 |
| 权重上限 | 1 | `max_weight_pct=10` 收紧后 `shares` 变小 |

```bash
uv run pytest tests/test_position_sizing.py -q   # 15 passed
uv run ruff check plugins/tools/position_sizing.py tests/test_position_sizing.py   # 全绿
```

**注意**：`@tool` 装饰后得到的是 `Tool` 对象，不是裸协程，
测试里要调 `position_sizing.func(...)`（与 `tests/test_site3_recovery.py` 等既有
用例一致）。直接 `await position_sizing(...)` 会 `TypeError: 'Tool' object is not callable`。

## Comments
