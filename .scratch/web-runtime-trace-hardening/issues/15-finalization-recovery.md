# 15：运行落账与崩溃恢复缺少一致性及幂等

Status: needs-triage
Priority: P1
Type: task
Requirements: PR-RUN-01/02、PR-GOV-01/03

## 问题与验收

完整代码证据、复现边界、修复要求和验收见[报告 F15](../../../docs/plan/web-runtime-trace-repair-report.md#f15运行落账与崩溃恢复缺少一致性及幂等)。
执行记录和覆盖矩阵见[存储链路复核](../../../docs/plan/web-storage-chain-audit.md)。

- 以隔离合成数据复现，不以真实账户/轨迹作为测试输入。
- 执行报告列明的正常、失败、恢复及兼容性验收。
- 启动恢复须区分本进程遗留与其他存活进程任务；验收多 worker/副本与滚动发布的任务所有权，不能将别的进程活跃 Run 直接收尾。
- 未实现；相关失败断言是待修复证据，不能按“测试已执行”关闭。

## Comments

- 2026-09-29：全面存储复核新增，详见报告证据等级；运行代码尚未修改。
- 2026-09-29 环境补查：源码确认恢复仅排除当前进程 handles，第二 API 共用业务库可能误标活跃 Run；未做真实双进程故障测试。修复前测试须独立库，详见[环境方案](../../../docs/plan/web-storage-validation-environment.md)。
