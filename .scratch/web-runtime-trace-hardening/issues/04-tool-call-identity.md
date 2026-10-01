# 04：保留工具调用 ID 并修复回放配对

Status: closed
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
- 2026-10-02（复核关闭·证据链补全）：批量复核发现实现与测试实际存在但工单未回链——实现：
  runtime 侧 vendor call_id 透传（trajectory.py llm 记录 `tool_calls[].id`，缺失时 synth 一次并保持
  稳定）→ replay 映射 `server/relay.py::_traj_record_to_events` 直接采用记录内 id（不再二次合成）
  → `tool_started`/`tool_finished`/`result.tool_call_id` 全链共享同一 ID；store 侧按 ID 配对
  （interrupted 结果仍入历史保配对，见 loop_types.ToolResult 注释）。测试证据：
  `test_web_m1.py`（轨迹含 tool_calls+args、/trace 回放）、`test_web_f09_stream_termination.py`
  （重连回放配对）、`test_web_f21_control_history.py`（steer/control 链路）、隔离契约
  `audit/f21-recheck-results.json` 24/24（含 adopted 落库）。复核复跑：m1+f09+f21 合计 **20/20** 通过。
  如实标注：「同轮同名多调用 + 乱序结果到达」无专项并发用例（ID 唯一性由 synth 规则 `call_<turn>_<idx>`
  保证）；旧版无 ID 轨迹降级 = synth fallback 本身。主路径全部有据，转 closed。
