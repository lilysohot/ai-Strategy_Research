# 18 · material extractor 替换实现与严格依赖门

Status: closed-p14-final-gate-failed-current-model-extractor-route-rejected
Execution: P4 selector v2 为 22 success + 1 outcome_unknown；P5 仅重试 35 个失败槽并用完剩余 4 次授权。P6/v4 以不可变响应做零调用复合 replay，达到 487/487 终态、0 failed；P7/v5 零调用金标复评为 11/11 target recall、11/11 attribution、9/11 strict semantic。P8 关系实跑为 4/4 succeeded，scorer-4 校正后为 3/4。P9 配置 preflight 在 0 attempt 阻断；P10 formal-ledger import + v5 relations 为 4/4 succeeded、target relation recall 4/4。P11 relation 样本已由 xyl 签认；P12 v2 的 4 次调用在质量门失败并被拒绝。P13 完成零调用 question-group selector。P14 已用完最终 4 次 relation 预算：4 次传输成功、0 retry，但仅 2/4 packet completed，另两包因 15 条非法 `status` 严格失败。最终门失败；P15、追加调用及当前任务内 prompt/schema 放宽均禁止。发布与消费为 0
Type: task
Parent: [17 · 结构化提取收敛闭环与最终去留门](17-structured-extraction-convergence-closure.md)
Model attempts: 66（P3 23 + P4 23 + P5 4 + P8 relations 4 + P10 relations 4 + P12 relations 4 + P14 relations 4；P6/P7、P8-v4/v5 反事实与 P9 preflight 为 0）
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
- [P4 execution summary](../evidence/18-material-extractor-replacement-20261009/p4-copper-selector-v2-plan/execution-summary.json)
- [P5 targeted repair](../evidence/18-material-extractor-replacement-20261009/p5-copper-selector-v3-repair-plan/manifest.json)
- [P6 v4 composite replay](../evidence/18-material-extractor-replacement-20261009/p6-copper-selector-v4-composite/execution-summary.json)
- [P6 frozen-gold evaluation](../evidence/18-material-extractor-replacement-20261009/p6-copper-selector-v4-composite/evaluation-summary.json)
- [P7 v5 zero-call replay](../evidence/18-material-extractor-replacement-20261009/p7-copper-selector-v5-zero-call/manifest.json)
- [P7 item adjudication agent draft](../evidence/18-material-extractor-replacement-20261009/p7-copper-selector-v5-zero-call/candidate-adjudications.agent-draft.json)
- [P8 relation live execution](../evidence/18-material-extractor-replacement-20261009/p8-copper-relation-selector-live/execution-summary.json)
- [P8 relation target evaluation](../evidence/18-material-extractor-replacement-20261009/p8-copper-relation-selector-live/evaluation-summary.json)
- [P8 relation adjudication agent draft](../evidence/18-material-extractor-replacement-20261009/p8-copper-relation-selector-live/candidate-adjudications.agent-draft.json)
- [P8 candidate v4 zero-call counterfactual](../evidence/18-material-extractor-replacement-20261009/p8-copper-relation-selector-live/candidate-v4-counterfactual.json)
- [P8 candidate v5 zero-call pruning](../evidence/18-material-extractor-replacement-20261009/p8-copper-relation-selector-live/candidate-v5-counterfactual.json)
- [P9 accepted-items import plan](../evidence/18-material-extractor-replacement-20261009/p9-accepted-items-import-plan/manifest.json)
- [P10 formal-ledger live execution](../evidence/18-material-extractor-replacement-20261009/p10-accepted-items-import-live/manifest.json)
- [P10 target evaluation](../evidence/18-material-extractor-replacement-20261009/p10-accepted-items-import-live/evaluation-summary.json)
- [P10 incremental adjudication draft](../evidence/18-material-extractor-replacement-20261009/p10-accepted-items-import-live/candidate-adjudications.agent-draft.json)
- [P11 reusable precision sample](../evidence/18-material-extractor-replacement-20261009/p11-relation-precision-sample/sample-plan.json)
- [P11 adjudication agent draft](../evidence/18-material-extractor-replacement-20261009/p11-relation-precision-sample/candidate-adjudications.agent-draft.json)
- [P11 agent-draft evaluation](../evidence/18-material-extractor-replacement-20261009/p11-relation-precision-sample/evaluation-summary.agent-draft.json)
- [P12 selector-v2 remediation manifest](../evidence/18-material-extractor-replacement-20261009/p12-relation-selector-v2-zero-call/manifest.json)
- [P12 signed calibration cases](../evidence/18-material-extractor-replacement-20261009/p12-relation-selector-v2-zero-call/signed-calibration-cases.json)
- [P12 zero-call counterfactual](../evidence/18-material-extractor-replacement-20261009/p12-relation-selector-v2-zero-call/counterfactual-summary.json)
- [P12 frozen plan diff](../evidence/18-material-extractor-replacement-20261009/p12-relation-selector-v2-zero-call/plan-diff-summary.json)
- [P12 live execution summary](../evidence/18-material-extractor-replacement-20261009/p12-relation-selector-v2-zero-call/execution-summary.json)
- [P12 signed-sample regression](../evidence/18-material-extractor-replacement-20261009/p12-relation-selector-v2-zero-call/signed-sample-regression.json)
- [P12 failure analysis](../evidence/18-material-extractor-replacement-20261009/p12-relation-selector-v2-zero-call/failure-analysis.json)
- [P13 question-group manifest](../evidence/18-material-extractor-replacement-20261009/p13-question-group-answer-selector-zero-call/manifest.json)
- [P13 zero-call summary](../evidence/18-material-extractor-replacement-20261009/p13-question-group-answer-selector-zero-call/zero-call-summary.json)
- [P14 final plan manifest](../evidence/18-material-extractor-replacement-20261009/p14-question-group-live-plan/manifest.json)
- [P14 final gate](../evidence/18-material-extractor-replacement-20261009/p14-question-group-live-plan/final-gate.json)
- [P14 frozen plan diff](../evidence/18-material-extractor-replacement-20261009/p14-question-group-live-plan/plan-diff-summary.json)
- [P14 execution manifest](../evidence/18-material-extractor-replacement-20261009/p14-question-group-live-plan/execution-manifest.json)
- [P14 protocol audit](../evidence/18-material-extractor-replacement-20261009/p14-question-group-live-plan/protocol-audit.json)
- [P14 final decision](../evidence/18-material-extractor-replacement-20261009/p14-question-group-live-plan/final-decision.json)

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
- 2026-10-09：P4 实跑 23 次 items：22 次成功，attempt 8 在 300 秒边界为 `outcome_unknown`，影响
  24 槽；其余结果为 364 extracted、60 no-supported、63 failed。28 个 invalid terminal 仅由缺失
  `evidence_selector`（16）或 `perspective`（12）构成，另有 11 个语义拒绝。strict parent gate 继续
  阻断 relations。已记录 22 次已知 usage 239,290 tokens，未把未知调用伪记为 0。
- 2026-10-09：P5 只重试上述 35 个可恢复槽，4/4 transport succeeded，24,921 tokens；v3 留下
  10 个 failed。根因被收敛为 condition 误放 semantic_type、两条过宽 evidence 启发式及结构残片
  negative terminal。v4 将语义轴与话语轴分开、收窄硬 evidence 信号，并将结构性 negative terminal
  视为协议完成但保留 missing-signal 诊断。
- 2026-10-09：P6 将 P4 成功响应与 P5 修复响应按冻结坐标零调用合成，487 个坐标无缺失无重复；
  v4 replay 得到 469 items、420 extracted、67 no-supported、0 failed，四包 completed，items formal
  task 为 succeeded/valid/accepted。原 11-item 金标 target recall 和 attribution 都是 100%，但 strict
  semantic 仅 6/11，证明 formal protocol gate 不等于语义金标 gate。
- 2026-10-09：P7/v5 只加入可由原文决定的通用规范（显式数值区间、明确对话 perspective、判断性
  modality），同一 immutable response set 的 strict semantic 提升到 9/11，target recall 与 attribution
  保持 100%。两条剩余自动差异中，一条是真实 host clarification 分类分歧；另一条是事实+预测被原子
  拆分而历史 scorer 只选一个 item。逐条裁定已形成 agent draft，未冒充用户签认。P4+P5 已消费后续
  授权的 27 次尝试，因此下一次 relation-only 4-call trial 必须单独授权；此前继续禁止 publish/query/
  delivery/context_use。核心/合约 137 passed，publication 回归并入后 150 passed；全量 corpus 为
  1379 passed、17 skipped，仅保留既有的本地检索金标 0/20 与 reader-pdf-10/11 两项环境失败；Ruff、
  Pyright 通过。
- 2026-10-09：xyl 以“签认草案，开始执行”签认 P7 items 裁定后，P8 复用该 items artifact，未重跑
  items；4 个 relation packet 各调用一次，4/4 succeeded、96,046 tokens、0 retry，269 个固定候选中
  selector 判 present 190 条，四包均 completed。历史 scorer 只命中 1/4 gold relation；逐条回原文与
  原子端点后，capex Q/A、yield Q/A、quoted-yield support 三条成立，Mitsui Q/A 未进入候选，因此人工
  裁定口径为 3/4，且 candidate-conditional selector recall 为 3/3。gold 是 selected targets 而非整篇负例，
  不能把其余 187 条自动计为 FP；70.63% 接受率及包间 10/31、58/58、3/60、119/120 的差异仍阻断发布。
- 同日零调用定位到 `material-relation-candidates-v3` 的通用顺序 bug：回答 turn 末尾的“听懂了吗”式
  反问会在处理该 turn 前覆盖上一 turn 的真实问题。v4 改为按 source order 更新 pending questions；旧
  269 个候选全部保留，新增 71 个候选，Mitsui 两个原子答案均获得 answers 边。该修复有回归，相关
  211 tests passed，Ruff 与 Pyright 通过。新增 71 边尚未做 selector 判断；下一门是零调用剪枝和原子
  endpoint-group scorer 修复，而不是立即再开 live budget。
- 完整 corpus 回归为 1388 passed、18 skipped；失败仍仅是既有的本地 golden Recall@5=0/20 与
  reader-pdf-10 断言/当前 reader-pdf-11 环境不一致，没有新增失败。
- 现有 formal batch ledger 不能将 replay-mode 的已签认 items artifact 作为 live-mode relation task 的
  父产物。P8 使用同一生产 role executor/adapter，并以发送前原子落盘的独立四次 attempt ledger 执行；
  该缺口已显式记录，P8 evidence runner 不得作为常规发布路径。
- 2026-10-09：xyl 以“签认草案，开始执行”签认 P8 relation 裁定。零调用候选 v5 仅删除 7 条指向
  会务邀请“有请…提问，请发言”的 answers 边，v4 的其余 333 条全部保留；其中三井真实问题仍有两个
  答案原子候选。`material-development-scorer-4` 将 item 字段计分与 relation 原子端点组分开，并按
  gold relation 去重，P8 不可变 payload 的自动 relation recall 因而与签认裁定一致为 3/4。
- 同日 formal ledger 新增自包含的 accepted-items import：计划内的 imported task 验证源 artifact、
  payload hash、snapshot、items-only 与 accepted 状态，执行时生成绑定源 artifact 的新账本工件且不
  预留 model attempt。合成执行证明 items attempts=0、relations attempts=1；CLI 已冻结 P9 batch
  `batch:bf9f350d72d0d430be0eb8ede8c53a3ff07b1d40f6794bf4d223575929a5001e`，预算为 claims/items=0、
  relations≤4，strict `complete_parent`，冻结过程 0 calls，尚未 execute。
- P9 相关执行/CLI/角色/关系/发布回归为 231 passed；全量 `tests/test_corpus*.py` 为 1353 passed、
  48 skipped，仅 1 个既有环境失败（测试期待 reader-pdf-10，当前环境为 reader-pdf-11）。Ruff 与
  Pyright 通过。
- 2026-10-10：P9 首次 execute 成功导入 items，但因 CLI 未显式加载专用 dotenv，冻结 profile 为
  unconfigured，relation 在预留前以 `CS_CONFIG_MISSING` 阻断；attempt/reserved 均为 0。CLI 新增
  `--config-env-file`，执行器只校验实际会发请求的角色，合成回归证明未启用 Claims/导入 Items 不再
  错误阻断 relation。P9 保留为失败证据，不原地改 plan。
- P10 新 batch `batch:da6a70bbc4152430bf01a75201e198a1846146d51e0a99f1c2639b82559e3b78`
  以同一签认 P7 items 进行 formal import，items attempts=0；v5 relations 恰好 4 次，4/4 succeeded、
  0 retry，合计 122,011 tokens，成本元数据不可用且未记 0。333 候选中 present 217，包间为
  14/31、79/84、3/91、121/127。Mitsui 两个答案原子均判 present，4 条 target relation 全部召回。
  这只通过 selected-target recall，不建立整篇 precision；增量裁定仍是 agent draft，发布/消费继续为 0。
- P10 相关回归 140 passed；全量 corpus 为 1354 passed、48 skipped，仅保留测试期待
  reader-pdf-10/当前 reader-pdf-11 的既有环境失败。Ruff、Pyright 与 diff check 通过。
- 2026-10-10：P11 对 P10 不可变 333 候选/217 present 做零调用分层抽样：19 条非 answers
  present 全量纳入，三包 answers 以稳定 hash 固定 3/5/5 条，另固定 12 条 absent recall 哨兵。
  32 条 precision 草案中 27 条成立；因稀有类型过采样，不能用 84.38% 原始比例，按纳入概率分层
  展开为 118/217、54.38%，诊断区间 24.78%—83.98%，不足以形成发布门。12 条哨兵中 4 条明确
  应翻为 present，但该哨兵不是概率 recall 样本。失败集中在回答主题漂移/部分回答误接，以及直接
  列举、纠正问题前提、原子数值答案和自我修正漏判。裁定仍为 agent draft，下一步先补零调用规则与
  回归，不追加 live budget；publication/query/delivery/context_use 仍为 0。
- 2026-10-10：xyl 以“签认P11 草案，开始执行”签认 P11。9 个错误 pair 全部已存在于 candidate v5，
  因此 P12 不做词面候选剪枝；`material-relations-selector-jsonl-v2` 保持 v1 输出 Schema、pair identity
  与 controller evidence 不变，仅补充直接回答、数值/名单/前提纠正、同 turn 主题漂移、部分回答和
  自我修正等原子判定规则，v1 保持历史可读/可执行。签认 delta 的零调用 oracle 为 5 present→absent、
  4 absent→present，结果 216 present，且未移除 4 条 target relation；这不冒充 v2 已实跑。
  batch `batch:3728b5fb95633c916e70706827709ef3f80572a71aa41f733d7e46cbc01d5b23`
  已按同一 snapshot/items/candidate v5/model 冻结，items=0、relations≤4、strict complete_parent；冻结
  0 calls，execute 尚未授权。聚焦回归 206 passed；全量 corpus 1385 passed、17 skipped，仅两项既有
  环境失败（本地 golden 0/20、reader-pdf-10/11）。Ruff、Pyright 通过，发布/消费仍为 0。
- 2026-10-10：按 xyl 对 P12 最多 4 次 relation 调用的明确授权执行冻结 batch。相对 store-root 的首次
  preflight 在 attempt 前以 `CS_PATH_OUTSIDE_ROOT` 拒绝，因此不计模型调用；改用已核验的绝对根目录后，
  relations 恰好 4 次、4/4 succeeded、0 retry，items/Claims attempts=0。usage 为 prompt 92,095、
  completion 28,303、reasoning 19,995、total 120,398 tokens；provider 未返回可核成本，记为 unavailable。
  333 个候选中 present 从 P10 的 217 降到 141，但签认 44 例只从 35/44 退化为 34/44：TP/FN/TN/FP
  为 24/7/10/3，9 个已知错误只修复 4 个。四条 target relation 中 Mitsui 被删，recall 从 4/4 降到
  3/4。故 v2 仅作为可审计实验版本保留，不进入发布计划；下一步先零调用设计按 question 分组的 answer
  selector，由模型选择每个问题对应的原子 answer index，再由 controller 展开不可变 relation pair。
  supports/conditions 维持稳定路径，不再追加 prompt-only live trial。publication/query/delivery/
  context_use 仍为 0。为避免被否决版本被新直接调用方误用，selector 默认/`latest` 已退回 v1；v2
  只保留 read-compatible 审计与 replay。相关语义、执行和合约回归 130 passed，Ruff、Pyright 通过，
  P10/P12 两份冻结 plan identity 均保持有效。
- 2026-10-10：P13 新增实验协议 `material-relations-question-group-jsonl-v1`，默认协议仍为 v1，未冻结
  live plan。controller 按 question target 对既有 candidate-v5 `answers` pair 分组，模型接口每个问题
  只返回一次本地 answer indexes；非 answers 继续使用 pair terminal。controller 再把索引展开为原 pair、
  精确证据窗口和 relation ID；缺失、重复、越界与非法终态均 fail closed。P10 的 333 个冻结候选中，
  299 个 answer pair 形成 66 个 question group，另有 34 个非 answer pair，所需终态由 333 降到 100
  （-69.97%），prompt 字符数 195,046→127,133（-34.82%）。用 P10 决定加 P11 已签认 44 例构造的
  oracle replay 精确展开 216 个预期 pair，44/44 签认例和 4/4 target 均保留；这是接口/映射证明，不是
  live 模型准确率。聚焦文件回归 146 passed；全量 corpus 1389 passed、17 skipped，只保留本地 golden
  0/20 与 reader-pdf-10/11 两项既有环境失败；Ruff、Pyright 通过。model calls、publication、query、
  delivery、context_use 均为 0。
- 2026-10-10：P14 最终 batch
  `batch:391150525103650ff49af17a251091c0908e00bd299553d7108643c174f27a58` 已以 0 model requests
  冻结。P12→P14 仅 relation protocol 从被拒绝的 v2 变为
  `material-relations-question-group-jsonl-v1`，其余 snapshot、签认 items import、candidate-v5、
  validation-v11、strict `complete_parent`、provider/model 与预算均不变；计划只含 env credential ref。
  Claims/items attempts=0，relations≤4，0 retry expansion。最终门固定为：4 包 completed、0 partial/
  failed、签认样本≥40/44、9 个已知错误至少修复 7 个、35 个既有正确项最多回退 2 个、target 4/4。
  无论通过或失败都结束当前 extractor 修复线，P15 不允许；通过后仅可另行授权最小正向消费，失败后
  模型/算法替换必须新立任务。当前 execute、publication、query、delivery、context_use 均未授权。
- 2026-10-10：按 xyl 的下一步执行授权运行 P14，Claims/items attempts=0，relations 恰好 4 次且无
  retry；四次 HTTP/model attempt 均 succeeded。usage 为 prompt 53,370、completion 14,189、reasoning
  11,657、total 67,559 tokens，成本元数据不可用且不记为 0。第 2、3 包共 15 条 non-answer terminal
  把关系类型填入 `status`（8 challenges、5 supports、2 conditions），违反仅允许 `present/absent` 的
  冻结 Schema；controller 未归一化或放宽，结果为 2 completed、2 failed。故 P14 在协议完整性门即失败，
  44/9/35/4 质量指标不作有效计分；两包残留的 92 条关系只是 incomplete candidate payload，不发布、
  不消费。按已签认终止规则关闭当前模型+extractor 路线；P15、追加调用、当前任务内 prompt/schema
  修补均不允许，任何替换另立新任务。publication/query/delivery/context_use 仍为 0。
