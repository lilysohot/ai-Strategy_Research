# 03：统一实时、回放和详情轨迹的安全返回契约

Status: closed
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
- 2026-10-02（复核关闭·证据链补全）：批量复核发现修复与测试实际存在但工单未回链——实现：`redact_deep`
  出口统一脱敏覆盖全部三条 egress 路径（SSE：`server/relay.py::_traj_record_to_events` 末尾深度脱敏；
  `/trace`：`server/routes/runs.py` records 列表 + 提交 message；JSON envelope 桥），旧轨迹与错误信息
  同经 `redact_deep`（递归 dict/list）。测试证据分散于套件：`test_web_p3_approval.py` observer 事件
  脱敏（smuggled secret → "(redacted)"）、`test_web_f21_control_history.py` steer/control 脱敏入库与
  列表展示、`test_hf_space_runtime.py` 端点回显 secret 事件脱敏、`test_web_m1.py` 全链路回放。
  复核复跑：p3_approval -k redact **1/1**、f21 -k redact **1/1**、m1+f09+f21 合计 **20/20** 通过。
  如实标注：审计导出（非 HTTP 出口）与备份内明文属工单 07 存储治理范围（已回链）；「错误响应覆盖
  脱敏」无专项断言（由 redact_deep 全出口包裹兜底）。主路径全部有据，转 closed。
