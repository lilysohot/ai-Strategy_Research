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

## 未做

1. **补数弹窗组件**（接口就绪：`GET /api/business/input-requests`）与无主账户引导、超限字段级报错。
2. **成交回填入口**与"已保存成交 / 分析排队中"回执。
3. Agent 建议价展示与聊天回执的"建议价/成交价"区分。
4. 浏览器验证（弹窗必填、超限报错、无账户引导、回填触发新 Run、草稿保护）。

## 说明

- `target_price`（目标价）仍保留为可选字段：契约 §11 未冻结其与 `target_profit` 的分工，
  本批不动，避免擅自扩大范围。
