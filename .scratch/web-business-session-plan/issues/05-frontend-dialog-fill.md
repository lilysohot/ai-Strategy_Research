# 05 前端：补数弹窗、计划表单去价格、成交回填

Type: task
Status: open
Blocked by: 02, 03, 04

## 目标

- 新增补数弹窗组件：显示主账户总资金/可用资金（只读）+ 规划资金（必需）、承受风险、
  期望盈利（可后补）；无主账户时引导创建；超出可用资金字段级报错；明示持久化语义。
- `SessionPlanManager.vue` 去掉计划价/目标价输入，改为规划资金；`BusinessProfileView.vue`
  同步（含 `allocated_capital`）。
- 成交回填入口：已成交时填实际成交价 → 保存并触发重新分析，展示"已保存成交 / 分析排队中"。
  后端路径已在 03 落地：`declared.trade` 无引用即新登记成交，用途走 `holding_cost`。
- Agent 建议价以系统建议展示（标 `system_computed`），采纳只记来源，不写价格字段。
- 建议价与成交价在聊天回执中分开表述。

## 验收

- `vue-tsc` 与构建通过；隔离 fixtures 的浏览器验证覆盖：弹窗必填、超限报错、无账户引导、
  计划表单不含价格字段、回填后触发新 Run、离开页面草稿保护。
- 不把 `draft_pending` 显示为可用于分析，不把建议价显示为成交价。

## 落点

`web/src/components/business/`（新增弹窗组件、`SessionPlanManager.vue`、`BusinessProfileView.vue`、
`AnalysisRerunPanel.vue`）、`web/src/api/index.ts`、`web/src/stores/business.ts`、`web/src/types.ts`、
`web/tests/`

## Comments

2026-10-08：本项未开始。03 已把「回填成交价 → 新 Run」的后端接口确定下来（`declared.trade` +
`use_case=holding_cost`），前端可按此接线；弹窗部分等 04 决定 worker→API 意图通道后再定数据来源。
