# 113 · C4 已登记缺口消费闭环

本目录关闭 112 号未行使的 C4。`r0-zero-call/` 保存冻结预注册、克隆演练、生产 gen-3 规则升级与 19+2+2 个确定性探测；`r1-live/` 保存内部 turn 上限未生效的无效轮；`r2-live/` 保存硬上限和只读挂载均通过的有效消费轮。所有无效轮、修复与累计 token 均登记在 `invalid-runs.json`，最终裁定见 `landing-record.json`。

该任务登记并传播既有覆盖缺口，没有补抽缺失内容。两源 artifacts、snapshot、mappings、coverage 与 quality_status 均保持 gen-2 的值，生产 PostgreSQL 未写入。

