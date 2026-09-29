# 06：定义并落实中断后的轨迹完整性

Status: needs-triage
Priority: P1
Type: task
Requirements: PR-RUN-02, PR-GOV-02, PR-BIZ-05

## 问题与范围

见[报告 F06](../../../docs/plan/web-runtime-trace-repair-report.md#f06中断后的轨迹完整性契约不足)。
涉及共享记录器、worker/bridge、读取状态及架构文档；先明确耐久级别，不默认承诺每 token 永久保存。

## 修复前提与验收

- 定义 complete/partial/unavailable 与请求尝试身份；写入失败及未完成响应有可见缺口。
- 若要求恢复已显示片段，实现有边界的流式检查点；不另造互相冲突的轨迹真源。
- 隔离进程测试正常结束、取消、SIGKILL、磁盘错误、半行恢复；不得杀真实运行。
- 配置关闭必需 JSONL 时可检测；说明 flush 与物理持久的区别，修正文档过度保证。
- 对共享 observer 做 CLI/工作流回归，并记录失败尝试是否纳入本轮契约。

## Comments

- 2026-09-29：已确认轮次级记录与非持久 delta 的边界，尚未做故障注入。
