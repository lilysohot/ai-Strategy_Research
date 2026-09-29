# 11：切换 Run 后旧异步响应可能覆盖新视图

Status: needs-triage
Priority: P1
Type: task
Requirements: PR-RUN-02, PR-GOV-02

## 问题与验收

代码证据、影响、修复建议和完整验收见[报告 F11](../../../docs/plan/web-runtime-trace-repair-report.md#f11切换-run-后旧异步响应可能覆盖新视图)。

- 实施前用隔离环境和合成数据固定触发条件，记录修复前行为。
- 按报告验收正常、失败和恢复路径，补充历史兼容性与回退影响。
- 只有动态验证通过才能关闭；源码检查不能替代端到端验收。

## Comments

- 2026-09-29：遗漏复核补充。源码路径已核对，动态复现与修复尚未执行。
