# 03：统一实时、回放和详情轨迹的安全返回契约

Status: needs-triage
Priority: P1
Type: task
Requirements: PR-GOV-06, PR-BIZ-04

## 问题与范围

见[报告 F03](../../../docs/plan/web-runtime-trace-repair-report.md#f03轨迹接口与-sse-的脱敏和数据最小化不一致)。
保留 owner-only 访问；服务端返回展示投影，不依赖前端隐藏已收到的敏感内容。

## 修复前提与验收

- 明确可见推理、受限原生块、工具结果、system prompt 和用户业务值各自的返回规则。
- 使用虚构密钥及嵌套输入，验证 HTTP/SSE/导出实际响应，覆盖旧轨迹及错误。
- 未授权访问仍返回 404；授权展开工具全文仍经过同一处理。
- 记录原始存储治理和备份策略；不能把一个 regex 通过当作所有数据已安全。

## Comments

- 2026-09-29：`/trace` 与 SSE 出口不一致已确认；动态接口复现未执行。
- 2026-09-29 全面复核：ASGI trace 返回合成凭据原文已复现；完整出口治理仍待修复。 执行结果见 `audit/` 及全面复核记录，未修复。
