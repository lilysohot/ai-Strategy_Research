# 14：排队 Run 的历史上下文没有明确截止点

Status: closed
Priority: P1
Type: task
Requirements: PR-RUN-02, PR-BIZ-04, PR-BIZ-06

## 问题与验收

代码证据、影响、修复建议和完整验收见[报告 F14](../../../docs/plan/web-runtime-trace-repair-report.md#f14排队-run-的历史上下文没有明确截止点)。

- 实施前用隔离环境和合成数据固定触发条件，记录修复前行为。
- 按报告验收正常、失败和恢复路径，补充历史兼容性与回退影响。
- 只有动态验证通过才能关闭；源码检查不能替代端到端验收。

## Comments

- 2026-09-29：遗漏复核补充。源码路径已核对，动态复现与修复尚未执行。
- 2026-09-29 全面复核：真实 history 构造路径复现当前 Run 包含后续排队消息，worker 启动用替身截断。 执行结果见 `audit/` 及全面复核记录，未修复。
- 2026-10-02（复核关闭）：验收条款逐条复核通过——修复前复现在案（当前 Run 历史含后续排队消息）；
  `server/orchestrator.py::_turns_as_of_submission` 以本 Run 提交时刻为截止单点实现（所有 spawn 路径统一生效，
  取消/失败/重试同规则；F21 生效 steer 写成的 turns 行复用同一截止点，与排队消息语义区分），
  契约 test_f14_queued_future_message_excluded_from_history 断言排队未来消息不入历史；业务上下文快照/
  长会话预算由报告 §7 明确划出本次范围（「不意味着业务快照、价格监控已经实现」）。复跑隔离契约 24/24
  （含该 F14 检查）。转 closed。
