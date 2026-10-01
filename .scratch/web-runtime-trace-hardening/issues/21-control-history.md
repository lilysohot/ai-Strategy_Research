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
- 2026-10-01：**浏览器 DOM 层复核完成：实时链路通过；「刷新恢复」发现实现缺口**（记录见
  [e2e/f05e2e/e2e-record.md](../e2e/f05e2e/e2e-record.md)）。
  **通过**（隔离栈 + 真实审批门 + Playwright/Edge）：live 弹窗（`approval-dialog`、目标/原因/沙箱警示、
  默认聚焦拒绝）、D1 修正文案、steer 在下一工具边界生效 → 状态栏「插话 1 / 插话已生效 1」、
  生效 steer 落为 `[运行中补充方向]` 消息、`GET /controls` 返回 steer=`adopted`、
  approval=`adopted(session_all)`。
  **缺口（刷新恢复未通过）**：Run 停在审批门时刷新页面——会话与消息恢复，但
  **无弹窗、无任何 Run 标识**（等待 11s 无变化）；同一时刻
  `GET /controls?kind=approval&status=pending` 返回完整 pending 记录。根因：
  `loadPendingApproval()` 只在 store `watch()` 内调用，而 `watch()` 仅被 ChatView
  的发送消息路径调用；刷新后 `runId` 为 null，且 UI 无任何入口对「停在审批门的运行」
  重新订阅（`retry()` 也需要非空 runId）。证据截图 `e2e/f05e2e/f21-refresh-no-dialog.png`。
  **修复方向**：`restoreSession` 后（或活跃会话轮询中）检测 pending 控制记录 /
  活跃 Run 并 `watch(run_id)` 或就地重建弹窗。该缺口与工单 05 记录的
  「刷新后无法重开历史 Run」同源。`Status → ready-for-agent`（仅剩此前端缺口 +
  业务库迁移 + POSIX 复验项）。
- 2026-10-01（下午）：**刷新恢复缺口已修复并浏览器闭环复验通过**（记录见
  [e2e/f05e2e/e2e-record.md](../e2e/f05e2e/e2e-record.md) F21 修复段落）。
  **实现**：`runs.ts` 新增会话级最近运行记忆（`rememberRun`，提交时记录）与
  `resumeForSession(sessionId, isCurrent)`（状态仍 queued/running 且会话未切走才重订阅，
  随 `watch` 的 `loadPendingApproval` 重建弹窗）；`ChatView.restoreSession` 接线。
  **复验揪出第二个缺陷**：`control_to_dict` 不暴露 worker 侧 `external_id`，重建弹窗
  只能以 DB 行 id 当 `approvalId` 批准 —— worker gate 按帧 id 匹配不上，决议被静默
  丢弃，运行停在门上直到超时。修复：投影增加 `external_id`，前端优先使用之。
  **回归**：前端审计 14/14（新增 4 条 resume 用例；负向对照移除状态检查 →
  `F21_resume_ignores_a_finished_run` 失败后恢复）、`vue-tsc` 0 错误、前端单测 70/70、
  `test_web_f21_control_history.py` 14/14。**浏览器闭环**（Run 0c65cbf3）：提交→弹窗→
  F5 刷新→弹窗重建+流重订阅→在重建弹窗上「允许一次」→弹窗消失、文件执行、终态、
  记录 `adopted/once/external_id`（实测与行 id 不同）——全部通过。
  **边界如实记录**：恢复依赖 localStorage 的会话级记忆（与 lastSession 同级）；换
  浏览器/清存储后停在审批门的运行仍无恢复入口，若产品需要应另立服务端驱动的
  「活跃运行/待决事项」发现任务。`Status → ready-for-human`（剩余：业务库迁移、
  POSIX 复验、真实重启后观测）。

