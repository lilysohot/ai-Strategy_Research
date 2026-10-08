# 12 · r3 抽取质量修复与冻结

Status: completed
Execution: 已完成 `material_items` 原子边界/多 item 槽位协议、Claims 坐标绑定提示与可信文档主体继承、指标别名、relations 多端点槽位放行，以及对应回归；新版本已独立冻结，尚未进行 r3 真实模型复验或发布
Type: task
Parent: [11 · 获准后的真实模型有界试验与单文档消费](11-bounded-live-trial.md)
Model calls: 0
Production database access: 0

## 修复结论

本轮先用已签认的 24 个非表格单元排除“上游清洗/裁切丢失”假设：48/48 条
`material_items` 金标引文均可在冻结 snapshot 原文中逐字回取，全部 unit 的
`context_status=complete`，snapshot gaps 为空。主要问题位于语义槽位和输出协议，而不是本轮
上游数据丢失。

已完成：

- `material-semantics-20`：扩展冒号、并列财务坐标、否定/条件/原因/结论的候选边界；对
  “但/不过/然而/可是”自我修正保留同槽；对“专家：/主持人：”等归属冒号不切断。
- `material-atomic-jsonl-v5`：同一粗槽允许最多 4 个原子 item；每个 item 仍须有唯一 ID，
  引文仍须完全位于槽内；一个槽不得同时提交 item 与 coverage。
- `material-items-validation-v3`：多个合法 item 可共同满足槽位信号；失败 item、重复终态和
  无支持声明继续 fail closed。
- relations 入口允许一个合格槽位包含多个端点 item，但每个端点仍须唯一归属于一个已通过
  coverage 的槽位，不能用 Claims fact 或未校验 item 绕过。
- `claims-v2-lint-5` / Claims extractor `af59c933380b`：明确一条 Claim 只能绑定一个
  `subject × metric × period × value/unit` 坐标；并列数值拆条，纯条件/风险/因果片段交给
  material items。
- `evidence-pipeline-8`：公司范围且模型省略主语时，可从可信 snapshot 文档元数据继承主体，
  并写入 `subject_basis=document_metadata`；显式主体从不被覆盖。补充扣非净利润、经营现金流、
  存货、应收、收盘价等受控指标别名。

## 零模型结构复算

在同一冻结 48 条 items 金标上，旧版“一槽最多一 item”结构上限为 30/48（62.5%）；仅细切后
为 36/48（75%）。v5 允许同槽多个原子 item 后，42/48 条严格完整引文可落入一个槽，结构上限
升至 87.5%。剩余 6 条金标引文本身跨越新的原子边界；不能为了 exact-quote 分数重新合并条件、
原因和结果，后续 r3 应按签认评分契约做人审语义匹配并记录这类边界差异。

## 验证

- 受影响测试：`118 passed`。
- 全部 corpus 测试：`1309 passed, 17 skipped, 2 failed`。两项失败是现存外部状态：黄金检索
  样本库 Recall 为 0，以及开发 PDF reader 测试仍期待 `reader-pdf-10+`、当前实际为
  `reader-pdf-11+`；均不触及本轮文件。
- 全仓测试未完成：本地未安装 Web/PG 可选依赖（SQLAlchemy、JWT、Alembic），收集阶段失败；
  不将其表述为全仓通过。
- 修改文件的 Ruff 检查通过；6 个修改的生产模块 Pyright 为 `0 errors, 0 warnings`。

## 冻结与下一门

冻结证据见
[12-r3-quality-remediation-freeze-20261008](../evidence/12-r3-quality-remediation-freeze-20261008/README.md)。
该包冻结提示词、Schema、路由配置、实现与测试字节，父金标和签认裁定只读引用，不覆盖 r2。

下一步是用相同 24 个冻结非表格单元执行一次新的 r3 有界真实模型复验：并发 1、自动重试 0、
失败停止；重新逐条裁定 Claims/items/relations，再决定 query、delivery、context_use 与发布。
本票不把零模型修复直接等同于 precision/recall 已达门，也不授权发布。
