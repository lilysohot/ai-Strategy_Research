# 09：SSE 游标与终态恢复协议存在缺口

Status: closed
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
- 2026-09-30：**前端游标语义修复完成（本工单最后一项缺口）**。两端分开处理：
  ① 后端根因 —— `Orchestrator.steer()` 的 `steer_queued` 事件改用独立字段 `steer_seq`，
  不再占用 `seq`（`seq` 是轨迹行号／重连游标 `?after=seq`，被 steer 计数器复用会让下一次重连
  跳过未读行）；HTTP `POST /{id}/steer` 的响应体 `body["seq"]` 保持不变——那是 API 契约而非 SSE 游标。
  ② 前端 —— `web/src/sse.ts` 新增 `CONTROL_EVENT_TYPES`（`steer_queued`/`approval_requested`/
  `approval_resolved`），这些控制帧即使携带数字 `seq` 也不推进游标；`web/src/types.ts` 补
  `steer_seq?` 并更正原注释中「seq 被重载」的描述。
  **证据**：`frontend-audit.mjs` 的 `F09_steer_sequence_is_not_trajectory_cursor`
  由 **failed（10 !== 0）→ passed**（修复前结果另存 `frontend-results-before-f09-cursor.json`，
  未覆盖方式保留基线）；双向负向对照：移除前端守卫 → 断言恢复 `10 !== 0`；
  后端还原 `seq=` → `tests/test_web_p3_steer.py::test_orchestrator_steer_writes_stdin_and_publishes` 失败，
  确认两侧都真被测到。既有测试同步：该用例两处断言改为 `steer_seq` 并新增 `"seq" not in event`。
  `tests/test_web_f09_stream_termination.py` 4/4 仍通过（后端盲区无回归）。
  **与本次无关的既有失败**：`test_steer_route_*` 3 条失败于 F16 外键启用后 fixture 缺父行
  （`FOREIGN KEY constraint failed`），负向对照前后均失败，非本次引入。
  **仍未验收**：真实浏览器下端到端确认「steer 后重连不跳行」——现有证据为转译真实 TS 的前端审计
  与后端单测，未跑真实 SSE 断线重连。故状态维持 `ready-for-human`。

## 2026-10-01 真实重启后观测（批次登记 restart_obs_20261001）

live API 进程 kill + 重启（观测材料：real_provider_20261001 的 3 个真实供应商 run）。F09 项：重启后
closed-stream 进程内记忆清空，SSE 重连已结束 run 由 `_live_queue_for` 双事实判定（无 worker handle +
DB 状态非 active）正确路由 replay-only——流正常关闭（exit=0，非悬挂），11 条重放事件与轨迹行数学吻合。
多进程盲区复核：另一进程结束的 run 重连行为与同进程一致（判定只依赖 DB 与 handle，不依赖记忆窗口）。
**真实重启观测通过，无代码改动。**
- 2026-10-02（复核关闭）：验收条款逐条复核通过——修复前行为有复现与基线留存（frontend-results-before-f09-cursor.json；判据还原即 15s TimeoutError / 10 !== 0 双向负向对照）；后端盲区（`_live_queue_for` 按 has_worker+DB 双事实路由 replay-only）、steer 游标分离（后端 `steer_seq` 独立字段 + 前端 `CONTROL_EVENT_TYPES` 不推进游标）各有回归与真实 TS 审计断言；浏览器/多进程端到端三场景见 e2e/e2e-record.md；2026-10-01 真实重启观测（批次登记 restart_obs_20261001：11 条重放事件与轨迹行数学吻合、跨进程重连判定一致、exit=0 不悬挂）补齐最后缺口。复跑 tests/test_web_f09_stream_termination.py 4/4、tests/test_web_f13_capacity.py 8/8、tests/test_web_p3_steer.py 12/12（与 F06/F22 套件合跑 26/26）、隔离契约 24/24（含 test_f09_late_subscription_finishes）。转 closed。
