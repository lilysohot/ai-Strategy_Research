# [已整合] 投研 Agent 平台 · 用户与运行平台需求

| 项 | 内容 |
|---|---|
| 状态 | **兼容入口；不再单独维护需求** |
| 替代文档 | [product-requirements.md](product-requirements.md) |
| 更新日期 | 2026-09-12 |

原文只覆盖认证、模型连接、会话、留痕与用量，后来又把实现机制和阶段性结论写进 FR，导致它与已落地的 Web 控制能力、语料/市场链路及投研闭环计划互相偏离。产品需求现已整合到
[《FrontierAgent 投研工作台 · 产品需求基线》](product-requirements.md)。

请按以下入口阅读：

- 产品范围、优先级、当前状态与验收：[product-requirements.md](product-requirements.md)
- 当前与目标业务流程：[business-process.md](business-process.md)
- 数据模型、运行时和部署实现：[tech-stack.md](tech-stack.md)
- Web 交互表达：[design/investment-research-workbench-prd.md](design/investment-research-workbench-prd.md)

## 原 FR 编号迁移

| 原编号 | 新需求域 |
|---|---|
| FR-1 用户注册与登录 | `PR-AUTH-*` |
| FR-2 用户级大模型配置 | `PR-LLM-*` |
| FR-3 对话与会话管理 | `PR-WB-*`、`PR-RUN-*` |
| FR-4 留痕与可追溯 | `PR-RUN-*`、`PR-GOV-*` |
| FR-5 用量与成本归属 | `PR-GOV-03`、`PR-GOV-04` |

## 重要状态修正

- `steer` 和审批不再是“P2/不含”：服务端、worker 和 Web 交互均已有实现，现归 `PR-RUN-04/05`。
- 文件预览、diff 与 revert 已进入工作台，现归 `PR-WB-04`、`PR-RUN-06`。
- 语料库已迁移到 PostgreSQL；SQLite/FTS5 只代表早期验证阶段。
- 市场工具和 Claims 已分别落地，但 Web 默认工具暴露、Run 级市场证据和“预期 vs 实际”比较仍未闭合。
- “Turn = 一问一答”的旧定义作废：`turns` 中一行是一条消息；一问、一次 Run 与一条助手结果组成“研究回合”。

保留本文件是为了不破坏历史链接。新增或变更需求不要再写入本文件。
