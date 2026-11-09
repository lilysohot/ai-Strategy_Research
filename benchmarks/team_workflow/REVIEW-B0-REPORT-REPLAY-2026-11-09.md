# 待审核：B0-REPORT-REPLAY-1 报告接收与终结边界

本次新增两个确定性用例，计划 **0 次真实模型调用、2 次隔离的 submit_report 工具执行**。当前只完成输入构造与逐字段离线校验，尚未执行回放。

目的：确认上一轮 E1-r1 已生成的具体报告是否通过工具与终结观察器；不改变模型输出，不用新的提示词诱导它停止。

| 用例 | 输入 | 预期 |
|---|---|---|
| R1 原样报告 | E1-r1 保存的 submit_report 调用，content、confidence、调用 ID 原样保留 | 工具非错误；final_answer 等于原报告；观察器返回 final_answer 停止原因 |
| R2 空内容负对照 | R1 仅把 content 改为空字符串，其他字段不变 | 工具错误；不写 final_answer；不产生终结干预 |

每例单独建立新的 TurnContext 和 FinalizeAnswerObserver，不共享触发状态。使用真实 `frontier_agent.core.runtime.loop.tool_exec.execute_tools` 和生产 `submit_report`，工具表只注册这一项。单次工具超时 5 秒，每例执行一次；异常记执行错误，不补造成功回执、不自动重试。

在新进程中运行，不初始化模型客户端，不挂载线上 AgentBus、会话或资料库。R1 原始参数只有 content 与 confidence，没有附件或 verification_results，因此不补造附件、核验检查或来源。R2 使用独立状态，防止 R1 成功结果污染负对照。

明确不覆盖：完整成员观察器栈及任务准入、AgentBus 汇总、协调员、最终用户交付、报告事实核验。工具接收和成员终结字段不等于整个任务成功。本测试也不测模型是否自愿停止，因为没有模型调用。

判定解释：

- R1 通过且 R2 拒绝：该具体报告通过工具与终结观察器边界。其他两个 E1 样本仍是动作生成阶段选择继续研究，不能用本测试宣称已修复。
- R1 拒绝：保存真实错误并定位该边界，先不要改提示词。
- R2 也终结：终结错误处理存在问题，应先修运行时。
- 执行异常：记未取得边界结论，不算行为失败。

审核包：`results/b0-report-replay-proposal-20261109-v1/`。

- `R1.call.json`、`R2.call.json`：完整实际执行参数。
- `cases.draft.json`：用例目标与预期。
- `protocol.json`：执行范围、限制、源包和输入指纹。
- `verification.json`：离线校验已通过，R1 与保存输出一致，R2 仅 content 变化。

不会修改已有 benchmark 评分或解锁上一轮未执行的 E2/E3。审核后只执行这两个确定性回放，不自动追加真实模型实验。
