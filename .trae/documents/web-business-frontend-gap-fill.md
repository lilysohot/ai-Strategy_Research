# Web 业务前端：盘点差距并补齐缺口（接线真实服务端）

## Context（为什么做）

`docs/plan/web-business-ui-tasks.md` 定义了 UI-01—11 前端业务交互任务。后端 DATA-01—15
已实现并提交（`server/routes/business.py` 全部业务接口在网），本地真实服务已起。前端
Vue3+Pinia+Element Plus 工作台已有业务组件骨架，但其中一半仍未接后端：

- **已接真实 API**：`BusinessRequestCenter.vue`（补数 list/get/answer/cancel + 幂等键 +
  版本冲突 409）、`BusinessNotificationCenter.vue`（通知 list/markRead/markAllRead + SSE 流）。
- **仍是禁用 STUB（等后端却后端已就绪）**：
  - `BusinessProfileView.vue`：保存资料/保存并分析按钮 disabled（"等待 DATA-01/03"），资料从不读取。
  - `BusinessMonitorCenter.vue`：创建监控规则按钮 disabled（"等待 DATA-09/10"），无规则列表。
  - `SessionPlanManager.vue`：底部文案"暂不写入服务端"，`sessionPlans` 用 `crypto.randomUUID()` 造假 id。
- **api/index.ts 缺失模块**：accounts、plans、link、trades、watch-rules、watch-events、
  operations（幂等恢复）、archive/delete、rerun/snapshot。

本计划把这三个 STUB 接到真实 DATA 接口，补齐 UI-01/02/03/04/06/08 中未接线部分；
UI-05（聊天修改回执）、UI-07（补数，已接）、UI-09（通知，已接）、UI-10（归档反馈）、
UI-11（浏览器验收）说明是否在本轮处理。

## 差距对照（UI 清单 vs 现状）

| UI | 差什么 | 现状 |
|---|---|---|
| UI-01 工作台入口/资料卡/关系总览/详情 | 服务端绑定、加载/归档状态 | 入口已接；资料 detail 纯前端预览 |
| UI-02 账户/计划录入 | 保存资料/保存并分析、decimal 传输、待补充记录 | 表单+`isDecimalText` 已就绪；**写未接** |
| UI-03 实际记录/成交 | 成交登记/更正、历史对比 | records 段仅 `actualPrice` 占位；**未接** |
| UI-04 幂等/回执/版本冲突/分析态 | 幂等键、操作恢复、diff、失败/派发/运行中区分 | 仅补数模块有幂等+409；资料/监控没有 |
| UI-06 分析依据/重算 | `investment-snapshot`、`rerun` 入口 | 端点已存在（runs.py:421、464）；前端无 |
| UI-07 补数 | — | ✅ 已接完整 |
| UI-08 监控创建/管理/版本/暂停恢复取消 | 规则 CRUD 接线 + 状态展示 | 表单就绪；**未接** |
| UI-09 通知 + 行情事件回合 | 行情事件回合/规则版本 | 通知 ✅；行情事件回合未做 |
| UI-10 归档/删除反馈 | 危险操作确认 + 联动反馈 | 未接 |

## 实施计划

### Phase A — 资料闭环接线（UI-01/02/03/04 · 资料部分）

1. **api/index.ts 新增模块**（复用 `request` 的 `headers` 传 `Idempotency-Key`）：
   - `accounts`：create/list/get/patch/getRevisions
   - `plans`：create(list per session)/patch/getRevisions
   - `link`：get/put(sessions/{rid}/link, account_id+primary_plan_id)
   - `operationHistory`：list?scope、（get by id）
   - 全部写接口：`headers: { 'Idempotency-Key': key }`，返回 `{replayed, operation_id, ...}`。
2. **web/src/types.ts 追加**：`Account{id,name,base_currency,archived,revision,values}`、
   `Plan`、`Trade`、`Operation`、`BusinessOperationResponse`。金额全部保持 `string`。
3. **web/src/stores/business.ts 新建**（对齐 `stores/sessions.ts`）：持有当前会话的
   plans、本账号 accounts、相关 operation 回执列表；`loadPlans(rid)`、`loadAccounts()`、
   `recordOperation(op)`。BusinessWorkspace 与 profile/plan 共享。
4. **BusinessProfileView.vue**：
   - 解禁"保存资料"：account 段调 `accounts.create`/`accounts.patch`，`declared{}` 用十进制
     **字符串**透传（`totalCapital/availableCapital/...`），`expected_revision` 从当前读取版本带入。
   - "检查可提交性"后 `canSubmit` 才可保存；保存成功用返回 `operation_id` 记 operation 回执并 `dirtyChange(false)`。
   - 409 版本冲突：捕获 `ApiError.status===409`，拉 `accounts/{id}/revisions` 展示"我要写 vs 服务端当前"diff，用户确认后带新 `expected_revision` 重提，绝不静默覆盖。
   - 保存并分析：**串行**——先 await 业务写成功，再 `runs.submit` 建 Run；"保存成功"与"分析已派发"两条提示分开，不从聊天文本认定成功。
   - "服务端版本"行改为显示真实 `revision`；去掉"待 DATA-01/待 DATA-05/06"禁用 tooltip。
   - 资料读取：进入 profiles 时从 store/accounts 加载列表并展示状态（加载/空/已归档/读取失败）。
5. **SessionPlanManager.vue + ChatView.vue**：
   - `saveSessionPlan` 改调 `plans.create(activeId, {...}, allow_incomplete)`，成功后按返回 object 刷新 `sessionPlans`（不再 randomUUID 造假）；删掉"暂不写入服务端"。
   - ChatView 的 `sessionPlans` 改为由 store 初次进入会话时 `loadPlans` 填充。
6. **BusinessWorkspace.vue**：保持 area 分发；profiles/monitoring 中 plans 统一从 store 取。

### Phase B — 分析依据 + 重算（UI-06）

7. **api 追加** `runs.investmentSnapshot(runId)`、`runs.rerun(runId, body, key)`（端点
   `GET /runs/{id}/investment-snapshot`、`POST /runs/{id}/rerun`，均已在 runs.py）。
8. **新组件** `AnalysisEvidence.vue`（读 run 快照展示"本次分析依据"，404 时显示 `snapshot_absent` 空态）
   与 `AnalysisRerunPanel.vue`（"用新资料重算"=/停止旧+建新 Run；成功后用返回 `run_id` 走 ChatView 已有 `runStream.watch` 订阅）。
9. ChatView run 状态区增加快照入口与重算按钮；只对**本会话**的 run 显示。

### Phase C — 监控接线（UI-08）

10. **api 追加** `watchRules`（create/list/get/patch/pause/resume/cancel + versions）、
    `watchEvents`（list）。
11. **BusinessMonitorCenter.vue**：解禁"创建监控规则"；"规则管理"空态改为 `watchRules.list` 渲染列表
    （状态/版本/最近检查）；表单提交带幂等键与 `expected_version`；规则编辑/暂停/恢复/取消走对应端点；
    行情可用性卡由能力探测/最新观测填充。C 阶段保持 `trigger_mode=single`（D 阶段 repeat 仍禁用）。

### 范围外 / 顺带

- **UI-10 归档/删除**：Phase A 中接入 `archive`（account/plan）+ 研究删除，仅做危险操作二次确认与联动反馈（`sys.confirm`/`ElMessageBox`），不引入额外审批体系。
- **UI-11 浏览器验收**：本轮不改已有骨架验收流程，不新建 mock 页面；完成后不声明"功能上线"。

## 复用清单

- `client.ts request` 已支持 `headers`(幂等键)、`query`、`body`、`ApiError(409).status` —— 无需改底层。
- `utils/business.ts` `isDecimalText`/`validateBusinessDraft` 复用于前端引导校验。
- `BusinessRequestCenter.vue` 的幂等键风格（每次写前 `crypto.randomUUID()`、成功后重置）和服务端版本冲突 409 刷新模式作为资料/监控模块复刻蓝本。
- ChatView 已有的 `runStream.watch` / `openRunStream` 复用于 rerun 订阅。

## 校验方式（端到端）

1. 起后端：`uv run uvicorn server.app:app --port 8000`（或现有本地已起服务）；本地真实 PG。
2. 起前端：`npm run dev`（web/ 下），dev server 代理 `/api`。
3. Phase A 验收：双 Tab 同账号改资料 → 第二次应 409；超时重试同一幂等键只建一个账户/计划；保存成功回执显示服务端 `revision`；刷新后 profiles 显示服务端绑定；保存并分析产生真实 Run。
4. Phase B 验收：跑一个分析 Run → 快照面板显示该 Run 冻结依据；改资料后"用新资料重算"→ 旧 Run 保留、新 Run 指回 `rerun_of_run_id`。
5. Phase C 验收：创建单次监控规则 → 列表显示状态；编辑阈值产生新版本；暂停/恢复/取消回执正确；`trigger_mode=repeat` 创建被服务端拒绝并提示。
6. Type check：`uv run tsc`（web/ 若配置）或 `npm run type-check`；确保无类型错误。
7. 不谎报上线：mock/预览项不声明为已交付用户流程。