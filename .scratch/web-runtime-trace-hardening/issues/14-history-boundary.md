# 14：排队 Run 的历史上下文没有明确截止点

Status: needs-triage
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
