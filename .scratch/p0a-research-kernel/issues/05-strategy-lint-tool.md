# 05 · `strategy_lint` 工具实现

Type: task
Status: closed
Blocked by: (none)

**Goal**: 确定性策略校验。LLM 可以提出策略，但**能不能落卡由它说了算**。

**Work**
新建 `plugins/tools/strategy_lint.py`：

```python
@tool
async def strategy_lint(strategy_json: str) -> str:
    """校验策略卡：价格关系、风险上限、必填字段、参数数量。返回 errors/warnings。"""
```

校验规则表：

| 校验项 | 级别 | 规则 |
|---|---|---|
| 价格关系 | ERROR | `stop_loss < entry_low < entry_high < target` |
| 风险预算 | ERROR | `0.1 <= risk_budget_pct <= 5.0` |
| 单票权重 | ERROR | `weight_pct <= max_weight_pct` |
| 失效条件 | ERROR | `invalidation` 非空（**无失效条件的策略不允许落卡**） |
| 时间窗 | ERROR | `horizon` 非空且为预设枚举 |
| 止损存在 | ERROR | `stop_loss` 必填 |
| 最小交易单位 | ERROR | `shares >= lot_size` 且为 `lot_size` 整数倍 |
| `computed_by` | ERROR | `sizing.computed_by` 必须存在（**硬闸②**） |
| 参数数量 | WARN | 可调参数 ≤ 6（反过拟合） |
| 风险收益比 | WARN | `(target-entry_high) / (entry_high-stop_loss) >= 1.5` |

输出：`{"passed": bool, "errors": [...], "warnings": [...]}`
（`passed == errors 为空`，warning 不阻断）

**设计要求**
- **纯函数**：不读文件、不调 LLM、无副作用，便于单测
- 入参是 JSON 字符串（LLM 容易传），解析失败返回明确错误而非抛异常
- 错误信息要**可执行**：写清「期望 X 实际 Y」，让 Agent 知道怎么改

**Acceptance**
- 每条 ERROR 规则各有一个触发用例 → `passed=false` 且 errors 含该项
- WARN 不阻断 `passed`
- 非法 JSON 输入返回错误，不抛未捕获异常

## Answer

`plugins/tools/strategy_lint.py`，纯函数：不读文件、不调 LLM、无副作用。

**10 条 ERROR**（规格表 8 条 + 2 条自洽重算）+ **2 条 WARN**。

多出的两条是硬闸②的**在线形态**：

- `amount_mismatch`：`shares × entry.high ≠ amount`
- `weight_mismatch`：`amount / capital_total × 100 ≠ weight_pct`

规格把「重算一遍、不信任字段」留给离线校验脚本；放进在线校验是为了让
手改过数字的策略**当场**被挡住，而不是等跑完写进文件才发现。
容差 0.01（金额到分、权重到 1bp）——足够宽以容忍 `position_sizing` 的四舍五入
与 JSON 序列化，又足够窄：改一手股必定被抓到（见 06 的两条用例）。

其他实现要点：

- 结果恒带 `checked_by: "strategy_lint@v1"`，让离线脚本能确认这份结果
  确实出自本工具，而不是 Agent 自己写的 `"passed": true`。
- 错误信息统一写成「期望 X 实际 Y」，可直接照着改字段。
- 非法 JSON / 非对象 / 缺 `position` 都返回错误，不抛异常。
- 权重上限与 `lot_size` 缺省回落为 schema 常量（`40.0` / `100`），
  缺失即按最严口径判。

**发现的坑（设计层面）**：反过拟合计数第一版把 `sizing` 段的未知键也算成
「作者新增旋钮」，而 `sizing` 是 `position_sizing` 原样搬来的**机器产物**——
于是工具每多返回一个回显字段（`ok` / `entry_high` / `stop_loss`）就误报 WARN。
已改为只统计 `position` 的未知键 + `parameters`：
反过拟合数的是**作者**的自由度，不是工具的。

## Comments
