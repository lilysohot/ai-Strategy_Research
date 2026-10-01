# 18：产物索引与回滚后的文件不一致

Status: ready-for-human
Priority: P1
Type: task
Requirements: PR-RUN-06、PR-GOV-01

## 问题与验收

完整代码证据、复现边界、修复要求和验收见[报告 F18](../../../docs/plan/web-runtime-trace-repair-report.md#f18产物索引与回滚后的文件不一致)。
执行记录和覆盖矩阵见[存储链路复核](../../../docs/plan/web-storage-chain-audit.md)。

- 以隔离合成数据复现，不以真实账户/轨迹作为测试输入。
- 执行报告列明的正常、失败、恢复及兼容性验收。
- 未实现；相关失败断言是待修复证据，不能按“测试已执行”关闭。

## Comments

- 2026-09-29：全面存储复核新增，详见报告证据等级；运行代码尚未修改。
- 2026-10-01：**产物索引/下载/diff/回滚真链路复验通过（WSL，E1 结转项）**（批次
  [e1-wsl-batch-registry.json](../audit/e1-wsl-batch-registry.json)）：真实 worker `create_file`
  经审批落盘 → 索引 rel_path/size/sha256 正确；下载 sha256 与索引一致；diff `added +3`；
  `POST /revert` → 文件移除且索引**同步重算清空**（F18 修复的行为在真链路成立）。
  Windows 上不可验收的根因（shell/文件工具不可用）随 POSIX 复验消除。
