# 08：提交 Run 缺少会话归属校验

Status: needs-triage
Priority: P1
Type: task
Requirements: PR-GOV-06, PR-RUN-02

## 问题与验收

代码证据、影响、修复建议和完整验收见[报告 F08](../../../docs/plan/web-runtime-trace-repair-report.md#f08提交-run-缺少会话归属校验)。

- 实施前用隔离环境和合成数据固定触发条件，记录修复前行为。
- 按报告验收正常、失败和恢复路径，补充历史兼容性与回退影响。
- 只有动态验证通过才能关闭；源码检查不能替代端到端验收。

## Comments

- 2026-09-29：遗漏复核补充。源码路径已核对，动态复现与修复尚未执行。
