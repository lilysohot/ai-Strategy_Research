# 21：用户纠正与审批决定缺少持久追溯契约

Status: ready-for-human
Priority: P1
Type: task
Requirements: PR-RUN-04/05、PR-GOV-02、PR-BIZ-02/06

## 问题与验收

完整代码证据、复现边界、修复要求和验收见[报告 F21](../../../docs/plan/web-runtime-trace-repair-report.md#f21用户纠正与审批决定缺少持久追溯契约)。
执行记录和覆盖矩阵见[存储链路复核](../../../docs/plan/web-storage-chain-audit.md)。

- 以隔离合成数据复现，不以真实账户/轨迹作为测试输入。
- 执行报告列明的正常、失败、恢复及兼容性验收。
- 已实现（2026-10-01）；验收与未完成项见契约 §12，未完成项不得视为已验收。

## Comments

- 2026-09-29：全面存储复核新增，详见报告证据等级；运行代码尚未修改。
- 2026-10-01：**最小契约草案已出**（[f21-control-history-contract.md](../f21-control-history-contract.md)，v0.1）。
  内容：新增 `control_records` 表（字段表 + `(kind, external_id)` 唯一约束）、`steer` 四态
  （`undelivered`/`queued`/`adopted`/`dropped`）与 `approval` 五态（`pending`/`adopted`/`rejected`/`expired`/`abandoned`）、
  逐文件接入点、`GET /controls` 恢复面、生效 steer 写成 `turns` 行的方案 A，以及 A1—A10 验收表。
  同时核出 5 个现状缺口（G1 零持久化、G2 409 无痕、G3 纯文本收尾轮 steer 静默丢弃
  `steer.py:58`、G4 审批 live-only 刷新即丢、G5 生效 steer 不进 `turns` 致下一轮历史看不到纠正）。
  **本轮只出草案，未改运行代码**；`Status` 维持 `needs-triage`，待 D1—D3（`persist` 语义 / steer 是否写成 turn / 重启后待审批语义）
  确认后再进入实现。
- 2026-10-01：**已实现并跑通隔离契约**（契约 v1.0，[f21-control-history-contract.md](../f21-control-history-contract.md) §12；D1—D3 按草案建议口径执行）。
  ① **落库**：新增 `control_records` 表（Alembic `0004_control_records`，含 `uq_control_records_kind_external`）；父进程是唯一落库点，
  **worker 仍不 import `server.store`**，只经 `control_applied` 帧回报"确实注入了"。
  ② **状态机**：`steer` = `undelivered`/`queued`/`adopted`/`dropped`；`approval` = `pending`/`adopted`/`rejected`/`expired`/`abandoned`，
  终态不可回写（幂等）。`ApprovalDecision` 新增 `source`（user/timeout/stopped/unknown），使**超时/停止不再被写成用户拒绝**。
  ③ **收口**：Run 终态（`_spawn` 收尾）与启动孤儿扫描（`reconcile_orphan_runs`）都把未终态记录收口为 `dropped`/`abandoned` ——
  修掉"纯文本收尾轮排队的 steer 永远停在 queued"的静默丢弃。
  ④ **下一轮历史**：生效 steer 写成带 `[运行中补充方向] ` 前缀的 `turns` 行（仅 adopted 才写），
  因此复用 F14 的提交截止点、无需改动 `_turns_as_of_submission`；未生效的 steer 绝不进历史。
  ⑤ **刷新恢复**：`GET /api/runs/{id}/controls` + 前端 `loadPendingApproval()`（带 F11 代次守卫）重建待审批弹窗，
  关闭 F09 遗留的"审批状态 live-only，刷新即丢"；`steer_applied` 已登记进 `CONTROL_EVENT_TYPES`（不推进游标）。
  ⑥ **D1 文案修正**：审批按钮「保存为永久规则」/「本次会话内允许」改为「本次运行内始终允许」/「本次运行内允许」——
  `ApprovalGate` 实际只在本次 Run 内记住，原文案承诺了不存在的跨 Run 规则库。
  **证据**：`tests/test_web_f21_control_history.py` **14/14**（负向对照去掉三处守卫后 4 条失败）；
  `tests/test_web_p3_steer.py` **12/12**（含真实 worker e2e：steer 注入后记录为 `adopted` 且 turn 落库；并修复 3 条因 fixture 缺 session 父行的既有失败）；
  隔离审计契约 **24/24**（报告 `audit/f21-recheck-results.json`，另修复该夹具随 F01 失效的 `uploads_root` 一行）；
  前端 `npm run test` 70/70、`vue-tsc` 0 错误、`vite build` 通过、`audit/frontend-audit.mjs` **10/10**（F21 ×5，负向对照 2 条失败）。
  **未完成**：业务库 `apodex` 尚未执行 `alembic upgrade head`（0003/0004 均未应用，本轮全部验证在隔离 SQLite/ASGI 内）；
  浏览器 DOM 层复核、真实重启后观测；`test_approval_end_to_end`/`test_upload_t210`/`test_stop_t28::sigkill` 三处失败为本机 Windows 既有限制（需 POSIX 复验）。
  `Status → ready-for-human`。

