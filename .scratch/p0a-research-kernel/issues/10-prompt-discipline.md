# 10 · 提示词：引用纪律与「缺失参数必须追问」

Type: task
Status: closed
Blocked by: 07, 08

**Goal**: 把三条硬闸写进模型行为，而不只是写在文档里。

**背景约束（已查证）**
TUI 侧**没有**结构化输入通道（`apodex/` 下 `addendum|extra_prompt|user_context` 零命中），
所以参数只能走首轮 task 文本 + Agent 追问。这要求提示词层面强制。

**Work**
在投研提示词中加入（P0a 阶段可先写在 task 文本里，P0b 后固化）：

1. **算术纪律**
   - 任何仓位/金额/占比数字必须调用 `position_sizing`，**禁止自行计算**
   - 产出前必须调用 `strategy_lint`；报错则修正后重跑，**不得绕过**

2. **缺失参数必须追问，不得假设**
   缺失清单：总资金 / 单笔风险预算 / 当前持仓 / 时间窗
   ——缺任一项则向用户提问，**不许用默认值蒙混**
   （这条是 P0a 验收项之一：Agent 必须表现出追问行为）

3. **引用纪律（P0b 起生效，P0a 先埋）**
   - 数字只能来自 `corpus_fetch` 的逐字原文或 stub 研报，**禁止引用 snippet 或记忆**
   - `kind` 必须区分 fact / forecast / opinion
   - 每条 evidence 带 `source_ref` + `page`
   - **下结论前必须检索并陈述至少一条反方证据**（防确认偏误经检索系统放大）

**不建议此时做**：不要为 TUI 新建 addendum 通道——接 web 时直接用 server 现成的
`metadata["_sys_prompt_addendum"]`（`server/worker.py:351` → `main_agent.py:817`），零成本。

**Acceptance**
- 只给「我有 100 万，帮我分析 X」（不提风险预算）→ Agent **主动追问**而非假设
- Agent 产出前可见 `position_sizing` + `strategy_lint` 两次工具调用
- `strategy_lint` 报错时 Agent 修正重跑，不绕过

## Comments
