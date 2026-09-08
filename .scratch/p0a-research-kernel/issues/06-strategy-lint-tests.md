# 06 · `strategy_lint` 单测

Type: task
Status: closed
Blocked by: 05

**Goal**: 锁死 05 的 10 条规则，确保「不合规策略一定被拒」。

**Work**
新建 `tests/test_strategy_lint.py`。

必须覆盖：

| 用例 | 期望 |
|---|---|
| 合规策略卡 | `passed=true`，errors/warnings 均空 |
| `stop_loss >= entry_low` | ERROR |
| `entry_low >= entry_high` | ERROR |
| `entry_high >= target` | ERROR |
| `risk_budget_pct` 越界（两个方向各一例） | ERROR |
| `weight_pct > max_weight_pct` | ERROR |
| `invalidation` 空 | ERROR |
| `horizon` 空 / 非枚举 | ERROR |
| `shares` 非整手 / 小于一手 | ERROR |
| **删掉 `sizing.computed_by`** | **ERROR（硬闸②回归测试，最关键）** |
| 参数数量 > 6 | WARN 且 `passed=true` |
| 风险收益比 < 1.5 | WARN 且 `passed=true` |
| 非法 JSON 字符串 | 返回错误，不抛异常 |

**重点用例说明**
「删掉 `computed_by`」这条是硬闸②的回归测试：它保证**任何绕过 `position_sizing`
自行编造仓位的策略都无法通过校验**。这条测试一旦变绿，整个 P0a 的意义就没了。

**验收命令**
```
uv run pytest tests/test_strategy_lint.py -q
uv run ruff check plugins/tools/strategy_lint.py tests/test_strategy_lint.py
```

**Acceptance**
- 全部用例通过（目标 ≥14 条）
- ruff 全绿

## Answer

`tests/test_strategy_lint.py`，**23 例全过**（目标 ≥14）。

覆盖：合规卡通过 · `checked_by` 戳 · 价格关系 3 条（含 `missing_stop_loss`）·
风险预算越界 2 个方向 · 权重超限 · `invalidation` 空 · `horizon` 空/非枚举 ·
`shares` 非整手 / 不足一手 · **删掉 `computed_by` → ERROR** ·
`computed_by` 被改写成别的值 → ERROR · 参数 >6 → WARN 且 `passed=true` ·
风险收益比 <1.5 → WARN 且 `passed=true` · 非法 JSON / 非对象 / 缺 `position` ·
`build_strategy_card` 组装出的卡能通过校验。

外加 `tests/test_p0a_chain.py` 的两条**手改检测**用例（对应 05 新增的自洽重算）：

- 只改 `shares` → `amount_mismatch`
- `shares` 与 `amount` 一起改、但 `weight_pct` 忘了改 → `weight_mismatch`

```bash
uv run pytest tests/test_strategy_lint.py tests/test_p0a_chain.py -q   # 全过
uv run ruff check plugins/tools/strategy_lint.py tests/test_strategy_lint.py   # 全绿
```

「删掉 `computed_by`」这条仍是最关键的一条：它挡的是「LLM 自己编一个仓位数字」
这条路径。它变绿 = 校验失去约束力 = P0a 全部意义归零。

## Comments
