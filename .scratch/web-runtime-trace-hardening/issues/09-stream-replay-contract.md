# 09：SSE 游标与终态恢复协议存在缺口

Status: ready-for-human
Priority: P1
Type: task
Requirements: PR-RUN-02, PR-RUN-04, PR-GOV-02

## 问题与验收

代码证据、影响、修复建议和完整验收见[报告 F09](../../../docs/plan/web-runtime-trace-repair-report.md#f09sse-游标与终态恢复协议存在缺口)。

- 实施前用隔离环境和合成数据固定触发条件，记录修复前行为。
- 按报告验收正常、失败和恢复路径，补充历史兼容性与回退影响。
- 只有动态验证通过才能关闭；源码检查不能替代端到端验收。

## Comments

- 2026-09-29：遗漏复核补充。源码路径已核对，动态复现与修复尚未执行。
- 2026-09-29 全面复核：完成后新订阅挂起、steer 序号误作轨迹游标已复现；其余重连场景继续验收。 执行结果见 `audit/` 及全面复核记录，未修复。
- 2026-09-30：**后端盲区已按权威状态修复**。`Orchestrator.has_worker` 报告本进程是否持有该 run 的
  worker handle，`server/routes/runs.py::_live_queue_for` 仅在「有 handle」或「行状态仍在 queued/running」
  时订阅；否则 `sse_for_run` 走 replay-only，只回放轨迹后自然结束（前端把干净 EOF 视为 `completed`，
  再经 `GET /api/runs/{id}` 对账终态）。本进程结束的流仍由 `_closed_stream_ids` 兜底。
  回归：`tests/test_web_f09_stream_termination.py` 4 条通过；把判据临时还原为「总是订阅」时，
  `test_f09_finished_in_another_process_replays_and_ends` 以 15s `TimeoutError` 失败，确认用例抓住修复前行为。
  **仍未验收**：前端游标语义（steer 序号被当作轨迹游标）与真实浏览器/多进程部署下的端到端验收，故状态不变。
- 2026-09-30：**回溯核查，完成状态确认**。当日三项重跑与上轮结论一致：
  ① 隔离审计契约 **24/24 通过**（`run_audit.py --audit-report f09-recheck-results.json`，断网/禁子进程，
  含 `test_f09_late_subscription_finishes`；该契约只覆盖「本进程结束」路径，盲区路径由 ② 补上）；
  ② 盲区回归 `tests/test_web_f09_stream_termination.py` **4/4 通过**（跨进程结束 replay-and-end、
  queued/running 无 handle 仍订阅、本进程快路径、权威状态决策矩阵）；
  ③ 前端审计重跑 `F09_steer_sequence_is_not_trajectory_cursor` **仍失败**（10 !== 0，
  `frontend-results.json` 已刷新），即 F09 前端游标语义未修复。
  **完成状态**：后端盲区=已修复并有隔离动态证据；前端游标语义=未动。整张工单维持 `ready-for-human`，
  待前端游标修复与真实浏览器/多进程部署端到端验收后方可关闭。
- 2026-09-30：**浏览器 / 多进程端到端验收通过（盲区本体）**。隔离栈：mock LLM(8018) + API 进程
  A→B(8471，同 SQLite 库/运行根/JWT) + vite(5273→8471) + Playwright/Edge。三个场景：
  ① 进程 A 内提交→活流→终态正常（`72c61374…`，stopped/no_tool，usage 完整）；
  ② 杀 A→起 B（同库）→浏览器重订阅已结束 run：页面内 fetch 读 `/events` 至 EOF **19ms 结束**
  （HTTP 200，685B 重放）——修复前该场景为订阅死队列永不结束；③ B 上新 run 活流与终态正常
  （`d93fd941…`），反向守卫未被误判。页面 console 0 error。隔离证明：run 落盘于
  `%TEMP%\f09-e2e2\runs`，真实 `server/runs` 无新目录；监听进程身份经 Win32_Process 核验。
  完整记录与截图见 [`e2e/e2e-record.md`](../e2e/e2e-record.md)。
  **仍然未完成**：仅剩前端游标语义（`F09_steer_sequence_is_not_trajectory_cursor`），修复后本工单方可关闭。
  备注：同日早些时候因 IDE 端口转发代理占用 8001/5174，一轮隔离尝试的流量误入真实 API（已留痕并经
  用户确认保留）；本次改用冷门端口并先行核验监听进程身份与数据落点。
