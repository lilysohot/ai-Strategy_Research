# 18 · material extractor 替换实现与严格依赖门

Status: live-v1-items-gate-failed-v2-fix-frozen-not-executed
Execution: selector v1 batch 的 23/23 items attempts 传输成功并返回 487/487 顶层终态，但严格字段/语义门留下 252 failed 槽；complete-parent 正确阻断 relations（0 calls）。零调用修复 replay 将 extracted 57→209、failed 252→100、Schema failures→0；selector v2 新计划已冻结但未执行
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

1. [x] 确定性 controller 逐槽创建 obligation，并负责终态账；模型只返回受约束的语义字段和 source-span
   selector。缺失/重复/无效模型记录由 controller 记为显式失败，不能成为“漏终态”。
2. [x] evidence quote 只能由 controller 从冻结 packet 的 `[start,end)` 切片生成；模型不得自由复制或添加
   `专家：`、`主持人：`。speaker attribution 与 evidence span 分离。
3. [x] Markdown 内嵌 HTML span/style 在 selector path 中按冻结原文结构化保留；模型不再承担清洗后
   quote 回写，controller 始终按原始 `[start,end)` 切片，重复文本也由坐标区分，不删除标记或丢失 offset。
4. [x] 批次改为输入文本与每槽输出义务的确定性 token 估算微批；新 selector 协议首次安全上限为
   24 槽、64 items、8192 estimated tokens。`24` 不是全局质量常数；487 槽 copper 零调用反事实为
   23 批并覆盖 487/487 槽。
5. [x] 否定、条件、风险、问题、forecast、evidence 等硬信号保持 fail closed；不降低 Schema 必需字段，
   不把缺失记录自动解释为 `no_supported_item`。

## P2 · 替换 relations extractor（零调用开发）

1. [x] 继续由确定性规则冻结 candidate pairs；模型只返回批内 `relation_index`、`present/absent` 和
   固定 `pair_window` selector，不再复制 pair ID、端点或自由文本引文。
2. [x] relation evidence 由 controller 从允许的 item/source spans 组装；缺失、重复、越界或非法 selector
   显式计为 incomplete/partial。
3. [x] 对本次 180 pair / 5 个伪 speaker-prefix 失败建立固定回归；旧 copper 只读反事实验证
   180/180 candidate pair 均可生成逐字 source window，不放宽证据门，也不改写旧决定。

## P3 · 零调用证明与下一次唯一真实门

1. [x] 先用现有 16 份不可变响应做差分诊断，再用合成受约束响应覆盖 controller 的完整/缺失/重复/越界
   分支；不得把旧响应离线改写成通过。
2. [x] 运行相关测试、全量 corpus、Ruff、Pyright；冻结实现、Schema、配置、批次上限与 gold hash。
3. [x] 只有零调用门全部通过后，才另行冻结一次 copper-only 新 batch。仍使用原 11 items / 4 relations
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
- [P1 items selector zero-call freeze](../evidence/18-material-extractor-replacement-20261009/p1-selector-protocol/manifest.json)
- [P2 relations selector zero-call freeze](../evidence/18-material-extractor-replacement-20261009/p2-relation-selector/manifest.json)
- [P3 copper selector live plan freeze](../evidence/18-material-extractor-replacement-20261009/p3-copper-selector-plan/manifest.json)
- [P3 execution summary](../evidence/18-material-extractor-replacement-20261009/p3-copper-selector-plan/execution-summary.json)
- [P3 failure analysis](../evidence/18-material-extractor-replacement-20261009/p3-copper-selector-plan/failure-analysis.json)
- [P4 selector v2 zero-call fix and plan](../evidence/18-material-extractor-replacement-20261009/p4-copper-selector-v2-plan/manifest.json)

## Comments

- 2026-10-09：`RelationPlan.dependency_policy` 新增 `qualified_subset`（历史默认、序列化省略，保持旧
  plan hash）与 `complete_parent`（写入新 plan hash）两种策略。后者仅在 parent items 为
  `succeeded / valid / accepted` 时派生 relations。新增 strict partial 回归；执行账 31 passed，
  roles/relation guards/publication 92 passed；issue 17 下全部历史 plan 身份复验通过。
- 全量 corpus：1361 passed、17 skipped；仅两项既有环境基线失败（本地 golden 语料 0/20、
  reader-pdf-10 测试断言与当前 reader-pdf-11 环境不一致）。Ruff 与 Pyright 通过。
- 2026-10-09：P1 items extractor 新增 `material-atomic-selector-jsonl-v1`、`material-semantics-28`、
  `material-slot-batching-v3`、`material-items-validation-v7`。模型只选择批内义务和 `slot` evidence，
  controller 生成业务 ID、逐字引文及显式失败终态；speaker prefix、HTML markup、重复文本、漏终态和
  重复终态均有零调用回归。新协议必须在 plan/CLI 显式选择，v5 保持可读；16/16 历史 plan identity
  通过。全量 corpus 为 1369 passed、17 skipped、2 个上述既有环境失败；Ruff、Pyright 通过。copper
  487 槽按 24/64/8192 三维安全预算确定性规划为 23 批，未授权模型调用。冻结证据见 P1 selector
  manifest；P2 relations selector 仍是下一依赖。
- 2026-10-09：P2 relations extractor 新增 `material-relations-selector-jsonl-v1`。模型只返回批内
  `relation_index`、`present/absent` 和固定 `pair_window` selector；controller 绑定 pair ID、端点、类型、
  relation ID 及 `[start,end)` 原文。旧 copper 只读反事实保留 180 个候选对，并为 180/180 生成精确
  source window，因此原 5 个伪 speaker-prefix 失败不再进入引文复制路径；这不是对旧语义决定的离线
  改判。121 项主回归、合约回归、16/16 历史 plan identity、Ruff、Pyright 均通过；全量 corpus 为
  1374 passed、17 skipped、2 个既有环境失败。下一步只剩冻结并执行一次 copper-only selector live plan，
  在执行前仍保持 0 新模型调用、0 publication/query/delivery/context_use。
- 2026-10-09：补齐 CLI 的 `--relation-dependency-policy`，防止命令行计划静默回到
  `qualified_subset`。随后冻结 batch `batch:98f02adad93998b0d87a7c5d21d3d8dd10631c09fca64974bcb4c43d3754af4c`：
  items selector 上限 23 calls、relations selector 上限 4 calls、总上限 27，strict `complete_parent`；
  provider profile 已配置且计划只保存 credential ref，没有内联密钥。冻结过程 0 model calls，尚未 execute。
- 2026-10-09：执行上述 batch。23/23 items attempts 均为 transport succeeded，共 201,366 tokens；模型返回
  487/487 个 exact 顶层 obligation terminal，缺失/重复/畸形均为 0，证明 24-slot 微批与终态控制不是本次
  主因。严格门最终为 57 extracted、178 no-supported、252 failed；156 个 item 缺少可默认字段，另外多批
  把已经位于 `evidence_selectors.slot.text` 的原文误判为 source/context 缺失。四包均 partial，strict gate
  将 relations 阻断为 0 calls。未开展裁定或消费。下一步是零调用接口修复与 23 份 immutable response replay，
  通过前不得追加 live budget。
- 2026-10-09：完成零调用接口修复并升版为 `material-atomic-selector-jsonl-v2`、
  `material-semantics-29`、`material-items-validation-v8`。controller 仅规范缺失的 absence-valued 字段，
  不补造肯定语义；跨维度常见漂移（semantic other/negation、statement forecast）映射到 unknown/claim，
  硬信号拒绝与 terminal invalid 分开记账。23 份 immutable response replay 把 extracted 57→209、
  failed 252→100、item Schema failures 10→0；剩余 100 是旧响应语义拒绝，未离线改判。核心/合约
  134 passed，全量 corpus 1376 passed、17 skipped、仍仅 2 个既有环境失败；Ruff、Pyright 通过，
  16 份历史计划及 v1 live plan identity 均可验证。v2 batch
  `batch:c8c98ed42fb25d3fce9ea8e75b4d864c9fefe1ce0ed3ee28448d0d8c96b9d05f` 已冻结，尚未执行。
