# 切走研究再切回导致运行中对话「没内容」

Status: implemented — 代码改动与流层证据已具备，浏览器端到端待人工验收（未自宣 closed）
Date: 2026-10-09
来源: 用户现场反馈 + 截图（运行中点击其他会话，回到原会话后对话为空）
编号: 本次未占用修复报告的 F 编号（报告现为「F01–F22 已收口」）；若需纳入
[修复报告](../../docs/plan/web-runtime-trace-repair-report.md) 与工单，建议登记为 F23，待 U 裁决。

## 现象

某研究会话内一次 Run 正在运行（assistant 尚未回话）时，点击左侧另一个研究，再点回原研究：
中间对话区只剩用户自己那条消息（截图里还伴随 `状态 idle`、列表 `0 条`），运行中的
流式内容全部消失，重新回到该研究也不会自己恢复；等到 Run 真正结束时也不会自动补上。

## 根因（源码事实）

1. `web/src/views/ChatView.vue::onSelectSession` 在**任何**选中变化时无条件 `runStream.reset()`，
   它关闭 SSE 并清空 `runId/status/answer/steps`。
2. 同时 `web/src/stores/sessions.ts::select` 只重新拉取 `turns`。而 assistant 回合是 **Run 结束
   才写入**（`server/orchestrator.py` 的 `append_turn(..., role="assistant", ...)`），运行中数据库里
   没有这条记录 —— 于是「断流 + 只剩持久化消息」= 对话看起来被清空，右栏 `状态` 落回 `idle`。
3. 回到原研究时没有任何续接：`runStream.resumeForSession(...)` 只在 `onMounted → restoreSession`
   里调用（刷新/首屏路径），会话切换路径没有它。
4. 附带：Run 在别的研究页面期间结束时，界面也不会自动刷新（`watch(() => runStream.status)` 已被
   reset 打断）。

## 改动

| 文件 | 改动 |
|---|---|
| `web/src/stores/runs.ts` | 新增 `sessionId`（被观看 Run 所属研究）；`watch(id, after?, ownerSessionId?)` 记录归属，`retry()` 保留归属，`reset()` 释放归属；`resumeForSession` 返回 `ResumeResult{outcome:'attached'\|'finished'\|'none', runId}` |
| `web/src/views/ChatView.vue` | 选中研究时仅在**流属于别的研究**时 `reset()`；随后 `attachSessionRun()` 续接流；Run 已在离线期间结束时按 `outcome==='finished'` 补读一次 `turns`；`onSend`/`onRerunStarted` 传所属研究 id |
| `web/src/utils/chat.ts` | 新增纯函数 `streamBelongsToSession()`（切研究是否该断流）与 `hasRunAnswer()`（是否还需补读） |
| `web/src/stores/sessions.ts` | `loadTurns`/`loadOlderTurns` 加「过期响应」守卫：切研究竞态下迟到的响应不得覆盖当前线程；`loadingTurns` 改为在飞计数 |

不改动后端、不改动数据、不改动 `turns`/Run 落库时机；续接走既有 F21 通道
（`run_state.lastRun:<researchId>` + `GET /api/runs/{id}` 状态判定），重放由 relay 的
`assistant_delta`（`full=true`）重建整轮内容。

## 证据（实跑）

```
cd web && npm test                         → tests 76 / pass 76 / fail 0（新增 chat.test.ts 2 项）
cd web && node ./node_modules/vue-tsc/bin/vue-tsc.js --noEmit   → exit 0（npm run typecheck 因 .bin 权限失败，改用 node 直调）
cd web && node ./node_modules/vite/bin/vite.js build            → ✓ built in 4.79s
node .scratch/web-session-switch-20261009/audit/frontend-session-switch.mjs → 7 passed / 0 failed
node .scratch/web-runtime-trace-hardening/audit/frontend-audit.mjs          → 14 passed / 0 failed（F09/F10/F11/F21 无回归，结果文件字节未变）
```

`audit/frontend-session-switch.mjs` 执行仓库**真实 TS**（`stores/runs.ts` + `utils/chat.ts`），
只替换响应式环境、鉴权与 HTTP/流输入，无浏览器、无网络、无模型调用；结果见
`audit/results.json`。含一条负向对照：按修复前的调用形态 `watch(id)`（不记归属）时，
`streamBelongsToSession(null, 'A') === false` —— 即断言确实能区分「绑定/未绑定」，
不是空断言。

## 验证边界（未做，不视为已验收）

- **浏览器端到端未跑**：ChatView 是 SFC，本 harness 不能执行它；`runStream.reset()` 调用点的
  改动由类型检查与源码阅读保证，缺真实浏览器时序证据（A 运行中 → 切 B → 切回 A → 流恢复、
  续跑结束后回话自动出现、审批弹窗在切回后重建）。
- 断线重连、Run 在离线期间结束的时序窗口（`finished` 分支补读）未做真实时序验证。

## 范围外（另行裁决，未在本次改动）

- **左侧列表恒显「0 条」**：`web/src/types.ts` 的 `Session.turn_count` 注释称由列表接口返回，
  但 `server/routes/sessions.py::_session_view` 从不返回该字段，`ResearchRail.vue` 只能
  `?? 0`。属客户端/服务端契约缺口（截图里活跃研究也显示 `0 条`），与本次「运行中切走丢内容」
  是两个独立缺陷。
- 会话列表 `updated_at` 在运行期间不刷新，列表排序/时间与流进度无关。

## 签认

实现与证据：见上（2026-10-09）。里程碑/关闭需独立复核 + U 具名签认；本文件不作 `closed` 声明。
