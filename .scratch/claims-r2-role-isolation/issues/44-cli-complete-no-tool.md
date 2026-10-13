# 44 · CLI 接受显式 complete 的 workflow no_tool 终态

Status: completed
Execution: 已完成
Type: bugfix
Blocked by: 43 真实消费运行暴露终端状态差异

## 问题

Issue 43 的两个 Stateful ReAct 运行均返回 `answer_status=complete`，A4 发布边界也为 `boundary_answer_status=complete`，但主 Agent 的正常无工具最终回答使用 `stopped_by=no_tool`。`apodex.task_runner._is_complete_run()` 原先只信任 `reporter_llm` 来源的显式 complete，因此 terminal task runner 把两个结果渲染为 `run incomplete`。

## 修复

- 当且仅当 workflow 同时返回 `answer_status=complete` 与 `stopped_by=no_tool` 时，将其视为完成交付。
- 无显式状态的 workflow `no_tool` 仍失败关闭；`best_effort`、`partial`、`not_found`、`wall_deadline` 和 `max_turns` 的既有未完成语义不变。
- reporter 完成态与 generic loop 的 `no_tool_behavior=stop` 语义保持不变。

## 回归与验证

- 新增真实 terminal workflow 调用点回归，固定 `complete + agent + no_tool` 必须显示 Result，且不得显示 `run incomplete`。
- 回归在修复前稳定失败，原输出为 `Incomplete output (turns=3 · tools=0 · no_tool)`；修复后与三个失败关闭反例共同通过（4 passed）。
- `apodex/tests`：823 passed；18 条既有 pytest marker warning。
- Ruff：相关实现与测试通过。
- Pyright：`apodex/task_runner.py` 0 errors。
- framework import smoke：390/390；symbol closure：0 missing / 488 files。

历史 Issue 43 运行不会被追溯改写，原本未写入 `outputs/` 的状态仍保留；修复作用于后续运行。
