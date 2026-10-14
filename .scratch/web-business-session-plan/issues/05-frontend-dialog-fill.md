# 05 前端：补数弹窗、计划表单去价格、成交回填

Type: task
Status: open
Blocked by: 02, 03, 04
Labels: ready-for-agent

## 目标

- 新增补数弹窗组件：显示主账户总资金/可用资金（只读）+ 规划资金（必需）、承受风险、
  期望盈利（可后补）；无主账户时引导创建；超出可用资金字段级报错；明示持久化语义。
- 计划表单去掉计划价/目标价输入，改为规划资金（会话内计划与资料页同步）。
- 成交回填入口：已成交时填实际成交价 → 保存并触发重新分析（后端已定：`declared.trade` +
  `use_case=holding_cost`）。
- Agent 建议价以系统建议展示（`system_computed`），采纳只记来源，不写价格字段。
- 建议价与成交价在聊天回执中分开表述。

## 已做并通过验证（2026-10-08）

计划表单去价格、改规划资金：

- `web/src/business-ui.ts`：`SessionPlanPreview.planPrice/targetPrice` → `allocatedCapital`。
- `web/src/components/business/SessionPlanManager.vue`：草稿/脏检查/重置/保存 + 表单与预览
  全部改 `allocatedCapital`（"本标的规划资金"，提示"从主账户可用资金中划出，不得超过可用资金"）。
- `web/src/stores/business.ts`：计划预览映射 `values.allocated_capital`。
- `web/src/views/ChatView.vue::saveSessionPlan`：`declared` 改为 `allocated_capital`。
- `web/src/types.ts`：计划 wire 类型去 `plan_price*`，加 `allocated_capital` 与
  `target_profit{value,unit}`。

残留清理（本项 ③④）：

- `web/src/components/business/BusinessProfileView.vue`：草稿与重置里的
  `planPrice/planPriceLow/planPriceHigh` 全部移除，改为 `allocatedCapital`。
- `web/src/utils/business.ts`：`BusinessDraft` 字段、十进制校验清单、`plan_analysis` 必填
  校验均改为 `allocatedCapital`（不再校验计划价区间）。
- `web/src/utils/business.test.ts`：对应单测改为"plan analysis 需要规划资金与目标价"。
- `web/src/components/business/AnalysisEvidence.vue`：字段标签由"计划价/计划价下限/计划价上限"
  改为"规划资金"，并新增"期望盈利"。
- `web/src/sse.ts`：补 `export type { SseEvent }`（HEAD 即存在的既有类型缺陷）。

验证结果：

- `grep -rn "planPrice|plan_price" web/src/` → **无残留**。
- `node node_modules/vue-tsc/bin/vue-tsc.js --noEmit` → 无输出、**全绿**。
- `node --experimental-strip-types --test "src/**/*.test.ts"` → **74 passed / 0 failed**。
- `node node_modules/vite/bin/vite.js build` → built in 4.64s（仅既有大 chunk 警告）。

前端环境说明：`web/node_modules` 完好，仅 `.bin` 缺可执行位；用 `node node_modules/<pkg>/bin/*.js`
直接运行即可，无需 `npm ci`。

## 本轮补做：成交回填入口（2026-10-08，静态验证通过）

- `web/src/components/business/SessionPlanManager.vue` 新增"回填实际成交价"区块：方向 / 成交量 /
  实际成交价 / 成交时间 / 费用（可选）；提示"计划不保存价格，价格以成交记录为准"与
  "不得用现价或建议价代替"；缺项或未绑定账户/主计划时就地报错。
- 提交走 `runsApi.submit`：`use_case=holding_cost` + `declared.trade`（无引用 → 后端在提交事务内
  新登记一条成交，见 issue 03）+ 幂等键 `fill-trade:<uuid>`；成功后提示"成交已保存，分析已排队
  （Run …）"，失败保留表单并显示原因。账户/计划取自 `useBusinessStore().link`，
  标的与币种取自当前主计划。
- 验证：`vue-tsc --noEmit` 全绿；`vite build` built in 4.32s。

## 本轮补做：结构化补数弹窗 + agent 缺数据自动弹出（2026-10-08，静态验证通过）

- 新增 `web/src/components/business/BusinessInputRequestDialog.vue`：主账户总资金/可用资金只读；
  本标的规划资金（必需）、可承受风险与期望盈利（值 + 单位，可后补）；无主账户时就地引导
  "先到交易账户资料创建主账户"；提交走既有 `inputRequests.answer`（`declared.plan` +
  `expected_versions`）；服务端字段级错误（例如规划资金超过可用资金）直接展示；
  成功提示"资料已保存，后续分析已进入队列"。
- `web/src/views/ChatView.vue` 接入**自动弹出**：`reloadTurns()`（Run 结束与页面刷新都会走）之后
  查询该研究 `status=pending` 的补数请求，命中未提示过的请求即自动打开弹窗；同一请求只自动弹
  一次（`promptedRequestIds`），"稍后补充"可关闭，回答成功后刷新对话。
- 信号来源是服务端而不是前端猜测：worker 缺料意图 → API 落库为 pending 请求（issue 04）。
- 验证：`vue-tsc --noEmit` 全绿；`vite build` built in 4.45s。

## 未做

1. Agent 建议价展示与聊天回执的"建议价/成交价"区分。
2. **浏览器与端到端验证（全部未跑）**：补数弹窗自动弹出与提交、成交回填、必填/超限/无账户报错、
   草稿保护均未跑 Playwright；也**未做真实后端联调**，含"worker 真的调用工具产生请求"的完整链路。
3. 成交 Run 挂载已有纯逻辑回归；弹窗字段校验、时间选择器与完整提交仍缺组件/浏览器级自动化覆盖。

## 对话结束后补数续接（2026-10-12）

为降低“必须由 Agent 在运行中准确调用补数工具”的触发难度，新增用户主动的后置续接路径：

- Run 进入终态后，对话区显示“补充资料并继续”；普通材料阅读不会自动弹窗或自动创建请求。
- 用户点击后，`POST /api/business/runs/{run_id}/input-request` 按 `plan_analysis` 在服务端读取该
  Run 的冻结业务快照；旧 Run 没有快照时兼容读取研究当前绑定。缺项由 `evaluate_purpose` 计算，
  前端不解析自然语言、不自行猜字段。
- 同一个来源 Run 重复点击复用 pending 请求；仍在运行的 Run 返回冲突，其他用户的 Run 不可见。
- 请求字段能由专用弹窗覆盖时直接打开；尚无主计划时先打开现有会话计划表单；其它基础字段缺失
  时进入补数中心，避免固定弹窗无法完成请求。
- 用户提交后沿用既有 `answer_request` 事务：结构化资料写入业务对象，创建不可变快照及关联的新
  Run，并进入持久派发队列。弹窗把 `follow_up_run_id` 回传给 `ChatView`，页面自动关注新 Run。
- Agent 的 `request_investment_input` 路径继续作为运行中提前中止的兼容入口；后置路径不依赖它。

零模型回归 `tests/test_post_run_input_request.py` 覆盖：已有账户/主计划但缺规划资金 → 后置请求 →
重复点击幂等复用 → 保存结构化规划资金 → 新 Run queued → `input_answer` 快照包含该值。结果 1 passed；
目标 Ruff/Pyright、前端 `vue-tsc`、84 项前端单测通过。Vite build 在 Windows Node 读取 WSL 的 Linux
`node_modules` 时缺 `@rollup/rollup-win32-x64-msvc`，属于当前依赖平台不匹配，本轮未重装依赖。

本 issue 仍保持 `open`：后置路径已实现并完成代码级闭环，但真实浏览器 + 真实 worker 验收尚未执行，
且 Agent 建议价/成交价的展示区分仍未完成。

## Comments

### 2026-10-14 成交 Run 前端挂载与时间选择器

- 修复成交提交成功后只显示 toast、未进入当前对话的问题：`SessionPlanManager.vue` 发出包含
  `sessionId/runId/message` 的 `runSubmitted`，`ChatView.vue` 立即追加用户回合、记录并订阅该 Run，
  随后关闭计划弹窗；切换研究后到达的事件不会挂到错误会话。
- `web/src/utils/chat.ts::attachSubmittedRun` 统一这一步状态转换；新增两项回归覆盖正常挂载和会话切换隔离。
- 成交时间由自由文本框改为 Element Plus 日期时间选择器；显示到秒，提交值使用带本地时区的
  ISO 8601 格式（例如 `2026-10-14T14:58:50+08:00`），避免服务端把无时区时间按 UTC 解释。
- 验证：前端 Node 单测 **93 passed**，`vue-tsc --noEmit` 通过，Vite 生产构建通过，
  `git diff --check` 通过。未执行会产生真实成交与新 Run 的浏览器提交测试。

## 说明

- `target_price`（目标价）仍保留为可选字段：契约 §11 未冻结其与 `target_profit` 的分工，
  本批不动，避免擅自扩大范围。
