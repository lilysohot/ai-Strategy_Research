# 04：保留工具调用 ID 并修复回放配对

Status: ready-for-human
Priority: P1
Type: task
Requirements: PR-RUN-02, PR-GOV-02

## 问题与范围

见[报告 F04](../../../docs/plan/web-runtime-trace-repair-report.md#f04工具请求与结果丢失共同调用身份)。
涉及共享 `TrajectoryFileObserver`、Web relay/store；需显式扩展旧 Web 加固计划的 framework 范围。

## 修复前提与验收

- 请求、授权/跳过、结果、文件、实时与回放事件共享稳定 ID；无供应商 ID 时只生成一次。
- 通过真实 observer → 文件 → relay → store 链路验证任意 ID、同轮同名调用、乱序结果、重连。
- 拒绝/跳过不显示为成功；旧版无 ID 轨迹不能唯一匹配时明确降级。
- 验证 JSON/JSONL 契约及 CLI、工作流消费者兼容性。

## Comments

- 2026-09-29：字段丢失与回放合成 ID 的差异确认，端到端动态复现未执行。
- 2026-09-29 全面复核：真实 observer → JSONL → replay 的调用 ID 丢失已复现。 执行结果见 `audit/` 及全面复核记录，未修复。
