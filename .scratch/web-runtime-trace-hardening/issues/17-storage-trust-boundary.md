# 17：产物根目录与回滚基线可经符号链接越界

Status: ready-for-human
Priority: P1
Type: task
Requirements: PR-GOV-06、PR-RUN-06

## 问题与验收

完整代码证据、复现边界、修复要求和验收见[报告 F17](../../../docs/plan/web-runtime-trace-repair-report.md#f17产物根目录与回滚基线可经符号链接越界)。
执行记录和覆盖矩阵见[存储链路复核](../../../docs/plan/web-storage-chain-audit.md)。

- 以隔离合成数据复现，不以真实账户/轨迹作为测试输入。
- 执行报告列明的正常、失败、恢复及兼容性验收。
- 未实现；相关失败断言是待修复证据，不能按“测试已执行”关闭。

## Comments

- 2026-09-29：全面存储复核新增，详见报告证据等级；运行代码尚未修改。
- 2026-10-01：**部署侧观测（WSL native，E1 真链路）**（批次
  [e1-wsl-batch-registry.json](../audit/e1-wsl-batch-registry.json)）：worker/工具进程身份
  euid=1000(administrator)，**tool-user 降权不激活**（非 root 无法 setuid `agent-tool`，
  engine.log 记录 harness-uid 告警）——非 root 部署下运行隔离边界=文件系统权限与 env 清洗；
  native 后端无挂载；runs 根与 run 目录均为 755 administrator:administrator（F01 迁移口径）。
  符号链接越界拒绝（`_trusted_outputs_root`/基线链接）已有隔离契约与 43/43 回归
  （diff/revert/artifacts 套件在 POSIX 全过）；共享目录构造越界链接按环境方案仍属 E2，未在真库演练。
