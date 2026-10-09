# 18 · material extractor 替换实现与严格依赖门

Status: in-progress-p0-complete
Execution: P1 copper 已用冻结 16 次调用证明现 extractor 在 487 槽规模下无法满足终态与逐字证据契约；严格 relation parent policy 已实现并通过回归，items/relations extractor 替换尚未完成，未冻结新真实预算
Type: task
Parent: [17 · 结构化提取收敛闭环与最终去留门](17-structured-extraction-convergence-closure.md)
Model calls: 0
Production database access: 0

## 目标

保留 snapshot、角色隔离、formal ledger、不可变 response object、冻结金标和发布/消费门；替换
`material_items` / `material_relations` extractor，使终态和证据范围由确定性控制器拥有，模型不再负责复制
opaque slot ID、逐字引文或补齐批次终态。本票不再增加样本词典或提示词特例。

## P0 · 先关闭执行语义缺口（零调用）

1. [x] 在 plan 身份中新增可冻结的 relation dependency policy。严格试验要求 parent items 同时满足
   `execution=succeeded`、`protocol=valid`、`quality=accepted` 才能派生 relations；partial endpoint 子集
   模式保留为显式的另一策略，禁止依赖调用方口头约定。
2. [x] 增加回归：strict policy 下 partial items 为 `dependency_not_ready` 且 relation attempt 为 0；subset
   policy 继续覆盖既有行为。旧 plan 读取与身份校验不得破坏。
3. [x] 将 P1 的“items 失败必须阻断 relations”纳入执行前机检，不能再只写在 Markdown stop policy 中。

## P1 · 替换 items extractor（零调用开发）

1. 确定性 controller 逐槽创建 obligation，并负责终态账；模型只返回受约束的语义字段和 source-span
   selector。缺失/重复/无效模型记录由 controller 记为显式失败，不能成为“漏终态”。
2. evidence quote 只能由 controller 从冻结 packet 的 `[start,end)` 切片生成；模型不得自由复制或添加
   `专家：`、`主持人：`。speaker attribution 与 evidence span 分离。
3. 在 reader/clean 层去除或结构化保留 Markdown 内嵌 HTML span/style；原文 offset 映射必须可逆，
   不能以删除标记换取不可追溯文本。
4. 批次改为基于输入/输出 token 预算的微批，硬上限不超过 24 槽；批次大小只影响成本，不影响终态
   完整性。487 槽铜箔范围必须在 plan 阶段给出确定性调用上限。
5. 否定、条件、风险、问题、forecast、evidence 等硬信号保持 fail closed；不降低 Schema 必需字段，
   不把缺失记录自动解释为 `no_supported_item`。

## P2 · 替换 relations extractor（零调用开发）

1. 继续由确定性规则冻结 candidate pairs；模型只返回 pair ID 与 `present/absent`，以及固定 evidence
   selector，不再生成自由文本引文。
2. relation evidence 由 controller 从允许的 item/source spans 组装；越界、重复或无候选的 selector
   显式失败。
3. 对本次 180 pair / 5 个伪 speaker-prefix 失败建立固定回归；新实现必须在不放宽逐字证据门的前提下
   消除这类失败。

## P3 · 零调用证明与下一次唯一真实门

1. 先用现有 16 份不可变响应做差分诊断，再用合成受约束响应覆盖 controller 的完整/缺失/重复/越界
   分支；不得把旧响应离线改写成通过。
2. 运行相关测试、全量 corpus、Ruff、Pyright；冻结实现、Schema、配置、批次上限与 gold hash。
3. 只有零调用门全部通过后，才另行冻结一次 copper-only 新 batch。仍使用原 11 items / 4 relations
   金标和原阈值，不重做金标。
4. 新实跑必须先达到 487/487 槽终态完整、0 partial、严格 parent gate 生效，再开展增量候选裁定；
   只审新增或有争议的决定，精确复用既有具名签认，不做全量人工重标。

## 完成定义

- 终态、证据 span、依赖门均由代码约束，不再靠模型遵守提示词。
- strict/subset 两种 relation policy 都被 plan hash 冻结并有回归。
- copper 新实跑不低于冻结 item/relation floors，成本不超过新冻结预算。
- 通过前不发布、不 query、不 delivery、不 context_use、不调用 M_main。

## Evidence

- [P1 execution summary](../evidence/17-structured-extraction-convergence-closure-20261009/p1-plan-freeze/copper-items-relations/execution-summary.json)
- [P1 failure analysis](../evidence/17-structured-extraction-convergence-closure-20261009/p1-plan-freeze/copper-items-relations/failure-analysis.json)

## Comments

- 2026-10-09：`RelationPlan.dependency_policy` 新增 `qualified_subset`（历史默认、序列化省略，保持旧
  plan hash）与 `complete_parent`（写入新 plan hash）两种策略。后者仅在 parent items 为
  `succeeded / valid / accepted` 时派生 relations。新增 strict partial 回归；执行账 31 passed，
  roles/relation guards/publication 92 passed；issue 17 下全部历史 plan 身份复验通过。
- 全量 corpus：1361 passed、17 skipped；仅两项既有环境基线失败（本地 golden 语料 0/20、
  reader-pdf-10 测试断言与当前 reader-pdf-11 环境不一致）。Ruff 与 Pyright 通过。
