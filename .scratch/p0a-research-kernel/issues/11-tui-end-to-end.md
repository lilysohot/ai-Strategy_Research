# 11 · TUI 端到端跑通 + P0a 验收

Type: task
Status: open
Blocked by: 01, 02, 03, 04, 05, 06, 07, 08, 09, 10

**Goal**: P0a 的唯一正式验收。跑不通则 **P0b 不做**。

**验收场景**
```
uv run frontier-agent --mode react --cwd <工作目录>
> 我有100万，空仓，风险偏好中等，想做3-6个月，帮我分析 X
  （stub 研报内容随对话给出，或 Agent 用 read_file 读 tests/fixtures/stub_reports/）
```

**通过标准（全部满足才算过）**

| # | 标准 | 验证方式 |
|---|---|---|
| 1 | Agent **调用** `position_sizing`（而非自己算） | trajectory / TUI 工具卡片 |
| 2 | Agent **调用** `strategy_lint` 且返回 `passed=true` | 同上 |
| 3 | `/outputs/strategy.json` 产出，`sizing.computed_by == "position_sizing@v1"` | 读文件 |
| 4 | `/outputs/report.md` 产出，关键数字带 `source_ref` | 读文件 |
| 5 | 故意漏给风险预算时，Agent **追问**而非假设 | 重跑一次，只说「我有100万，帮我分析 X」 |
| 6 | 手工核对：`sizing` 数字与 `position_sizing` 返回一致 | 手算或脚本比对 |

**反例验收（必须也能过）**
构造一个 `stop_loss >= entry_low` 的策略 → `strategy_lint` 返回 `passed=false`，
且 Agent **修正后重跑或直接报告不可行**，**不得绕过校验落卡**。

**失败即停**：若 P0a 跑不通，停止 P0b，回到 03/05/07/08 定位。
理由见 `docs/tittel/trading-strategy-platform-feasibility.md:271`——
「若 P0 跑不通，后面投再多数据也救不回可信度」。

**验收后**
- 在 `docs/plan/plan.md` 的 P0a 区块把状态改为 ✅，并补一句实测结论
- 本 issue 底部 `## Answer` 记录实际跑通情况（含发现的 bug）

## Comments
