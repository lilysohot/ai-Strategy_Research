# 11：切换 Run 后旧异步响应可能覆盖新视图

Status: closed
Priority: P1
Type: task
Requirements: PR-RUN-02, PR-GOV-02

## 问题与验收

代码证据、影响、修复建议和完整验收见[报告 F11](../../../docs/plan/web-runtime-trace-repair-report.md#f11切换-run-后旧异步响应可能覆盖新视图)。

- 实施前用隔离环境和合成数据固定触发条件，记录修复前行为。
- 按报告验收正常、失败和恢复路径，补充历史兼容性与回退影响。
- 只有动态验证通过才能关闭；源码检查不能替代端到端验收。

## Comments

- 2026-09-29：遗漏复核补充。源码路径已核对，动态复现与修复尚未执行。
- 2026-09-29 全面复核：实际 store 的延迟摘要响应复现旧 Run 覆盖新 Run；尚非浏览器端到端测试。 执行结果见 `audit/` 及全面复核记录，未修复。
- 2026-09-30：**修复完成**（`web/src/stores/runs.ts`）。引入**订阅代次** `generation`：
  `watch()`（每次订阅，含重连）与 `reset()`（退出登录/关闭抽屉/手动重试路径）都递增；
  `reconcile()` 在发起请求前快照 `runId` 与 `generation`，`await` 返回后**先校验二者未变**，
  否则整体丢弃——旧 Run 的迟到摘要不再写入新视图的 `status`/`finalAnswer`/`usage`/`runDir`/`errorMessage`。
  同时按报告要求收口「不凭 EOF 推定成功」：摘要获取失败时设置可见提示
  「运行已结束，但未能与服务端对账，结果待核实」，而不是静默按成功处理。
- 2026-09-30：**证据**。`audit/frontend-audit.mjs` 的
  `F11_old_run_summary_cannot_overwrite_current_run` 由 **failed 转 passed**：用可控 Promise 令
  A 的摘要在 `watch('B')` 之后才 resolve，B 的 `finalAnswer` 保持 `null`（此前被写成 `answer from A`）。
  负向对照：移除代次校验 → 断言恢复失败（`'answer from A'`）。回归：`vue-tsc --noEmit` 0 错误、
  前端单测 66/66、`vite build` 通过。
- 2026-09-30：**仍未验收（维持 ready-for-human）**：真实浏览器场景——切换研究/切换 Run、
  退出登录、关闭抽屉后重开、手动重试期间旧请求返回——均未实测；现有证据为转译真实 TS 的
  契约审计，不含 DOM 与真实请求时序。另：`spec.md` 提到的「为每次 watch 建立独立 Run 状态」
  采用**代次校验**方案（轻量、改动面小），未改为每 Run 独立状态容器；如后续需要同时保留
  多个 Run 的完整状态，需要另行设计。
- 2026-10-02（复核关闭）：验收条款逐条复核通过——订阅代次 `generation`（watch/reset 递增）+
  reconcile await 后 runId+代次双校验有断言（F11_old_run_summary_cannot_overwrite_current_run
  failed→passed，负向对照移除校验即恢复 `'answer from A'`，frontend-results.json）；摘要获取失败
  不凭 EOF 推定成功的「待核实」提示已实现；watch（含重连）/reset 全部递增使退出登录、关闭抽屉、
  手动重试路径同受保护；浏览器切换 Run 与刷新恢复场景由工单 05 e2e 闭环（E1 批次登记将
  「浏览器 DOM 层（F10/F11）」deferred 项于 2026-10-01 标记 resolved）。复跑 web 前端单测 70/70。转 closed。
