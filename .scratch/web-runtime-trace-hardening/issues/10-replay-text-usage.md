# 10：流式去重导致文字缺失与用量漏计或重复

Status: closed
Priority: P1
Type: task
Requirements: PR-RUN-02, PR-GOV-03

## 问题与验收

代码证据、影响、修复建议和完整验收见[报告 F10](../../../docs/plan/web-runtime-trace-repair-report.md#f10流式去重导致文字缺失与用量漏计或重复)。

- 实施前用隔离环境和合成数据固定触发条件，记录修复前行为。
- 按报告验收正常、失败和恢复路径，补充历史兼容性与回退影响。
- 只有动态验证通过才能关闭；源码检查不能替代端到端验收。

## Comments

- 2026-09-29：遗漏复核补充。源码路径已核对，动态复现与修复尚未执行。
- 2026-09-29 全面复核：实际 store 方法复现文本不补齐、用量 0/10 与 20/10 的偏差。 执行结果见 `audit/` 及全面复核记录，未修复。
- 2026-09-30：**修复完成**（`web/src/stores/runs.ts` + `web/src/utils/statusbar.ts`）。三处根因分别处理：
  ① **文本**：原 `if (replay && streamedTurns.has(turn)) break` 一旦该轮收到过任意 live 片段就丢弃整条回放，
  导致断流/背压后的缺字永远补不回来。改为**按轮次保存文本**（`turnTexts: Map<turn, string>`），
  live 片段追加、回放的整轮记录**替换**该轮文本并重建 `answer`——回放成为完整副本，既幂等
  （重复回放落到同一内容）又能**修复**被丢弃的片段；`streamedTurns` 因此删除（已无消费者）。
  ② **用量计量**：原代码的 `break` 同时跳过了 usage 处理，使"收到过 live 片段的轮次"完全不被计量。
  改为 usage 在文本判定**之前、独立**处理（报告要求「文本与 usage 去重分别处理」）。
  ③ **对账叠加**：`reconcile()` 原用 `accumulateUsage` 把服务端整次 Run 的用量**加到**已逐轮累计的
  统计上，导致已计量的轮次被重复计算（20/10）。新增 `usageTotalsFrom()`（复用同一套别名/推导归一化，
  语义是从零累加=绝对值）并**替换**运行总量。
- 2026-09-30：**证据**。既有契约审计 `audit/frontend-audit.mjs`（执行真实 TS，非浏览器）：
  `F10_full_replay_repairs_missing_live_text`、`F10_live_turn_still_counts_replay_usage`、
  `F10_final_usage_reconciliation_is_not_additive` 三项由 **failed 全部转为 passed**
  （连同 F09/F11 共 5/5）。负向对照逐项确认断言有效：回放改回追加 → 文本断言失败
  （`'comcomplete text'`）；`reconcile` 改回累加 → `20 !== 10`；禁用回放用量计量 → `0 !== 10`。
  回归：`vue-tsc --noEmit` 0 错误、前端单测 **66/66**、`vite build` 通过、F05 审计仍通过。
- 2026-09-30：**仍未验收（维持 ready-for-human）**：真实浏览器端到端——断线/背压后重连的缺字补齐、
  多轮混合（部分轮 live、部分轮回放）、重复回放的幂等性、仅 thinking 片段的轮次——均未在浏览器实测。
  现有证据为转译真实 TS 的契约审计与单测，不含 DOM 与真实 SSE 时序。
- 2026-10-02（复核关闭）：验收条款逐条复核通过——三处根因修复各有断言：按轮保存文本整轮替换
  （F10_full_replay_repairs_missing_live_text）、usage 先于文本判定独立计量（F10_live_turn_still_counts_replay_usage）、
  reconcile 用 usageTotalsFrom 替换而非累加（F10_final_usage_reconciliation_is_not_additive），
  三项均 failed→passed 且负向对照逐项确认（frontend-results.json）；修复前偏差（文本不补齐、0/10、20/10）已留存；
  替换语义使重复回放天然幂等；运行时路径由真实供应商批次（real_provider_20261001 契约检查含 F10 full 标记）
  与浏览器刷新→重订阅→回放渲染闭环（工单 05 e2e，E1 批次登记 deferred 项 2026-10-01 resolved）覆盖。
  复跑 web 前端单测 70/70（含 statusbar usageTotalsFrom）、隔离契约 24/24（含终态回放不重复落助手轮）。转 closed。
