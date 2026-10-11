# Claims／R2 独立结构化提取：实施规格与任务索引

- 日期：2026-10-02；状态复核：2026-10-10
- 状态：01—10 的基础架构、回放和冻结已完成；17 的 P1R5 Claims 110 条裁定已由 xyl 签认并通过冻结门。18 已完成严格 parent 门、items/relations selector、accepted-items formal import 和 P10 有界 relation live 执行。P11 relation 样本已由 xyl 签认；P12 selector v2 实跑退化并已拒绝。P13 已完成零调用 `material-relations-question-group-jsonl-v1`。P14 最终 relation-only batch 已执行并在协议门失败。19 的零调用反事实证明同模型语义 no-go。20 仅替换为 `glm-5.3-flash` 的 4-call 复验在 4K 输出上限耗尽 reasoning。21 将上限放宽到 16K 后，三个确定响应仍全部耗尽 reasoning 且为空，第四个为 outcome_unknown；因此 token-only 路线已关闭。Issue 26 已完成离线冻结包上的 10 次 M_main 价值消融；P2 的正向发布、真实 query/delivery/context_use 和产品消费仍未启动。
- 2026-10-10 收口：Issue 25 虽通过 boolean-v2 协议门但未通过关系质量门；Issue 26 随后完成
  items-only 对 items+relations 的 5 题、10 次 M_main 配对消融并经 xyl 盲评签认。relation treatment
  提升 0/4、回退 2/4、持平 2/4，输入 token 中位数增加 24.33%，因此默认 relation 富化关闭。
  R2 默认交付和当前验收范围固定为 `material_items`；relations 只保留为非阻断、按需实验能力。
- 范围裁决：当前 R2 不再为 relations 安排修复、模型调用或质量验收；这不是未完成债务，也不影响
  Claims/items 的验收与发布。未来只有新的明确业务问题、独立预注册价值门和单独授权同时成立时，
  才能另立版本重评 relations；不得从当前 items 收尾预算中恢复该路线。
- 设计依据：[report.md](report.md)；阶段放行真源：[R2 主计划](../../docs/plan/claims-market-closed-loop-plan.md)。
- 本文件保存实施范围、依赖和任务索引；逐任务状态与验收证据保存在各 issue，主计划保留阶段状态。不得在三处各维护一份独立完成率。

## 1. 首轮目标与边界

首轮打通 `react → stateful-react-agent/tui` 的单文档路径：固定来源快照 → Claims 与 R2 items 独立执行 → 校验/文件发布 → 新研究运行查询 → 完整证据进入实际模型消息 → ConsumptionLedger → corpus_submit_manifest → A4 报告检查。R2 relations 默认关闭；只有新的独立价值门通过并获授权时，才作为按需实验分支接入。

先在合成夹具与 fake/replay 下零模型验证，再经独立授权试验真实提取模型和主线模型。文件工件试点不是恢复旧数据库写链，也不是完成 R2-S5 的生产 PG 验收。

非目标：第三条模型复判链、前置通用 LLM 抽取、自动模型级联、全库重跑、新解析/OCR 系统、Agent Team 全入口改造、默认生产启用、生产 PG 迁移和留出集试验。多模型组合和并发正确性用 fake/replay 验证；首轮真实执行并发上限 1。

## 2. 不得改变的契约

1. M_extract 在 `.env` 中独立配置 `STRUCTURED_EXTRACTION_PROVIDER/MODEL/BASE_URL/API_KEY`，不读 `OPENAI_*` 补缺值，不复用主线客户端；真实密钥由用户配置，不写入工件或测试。缺提取配置不阻断确定性处理、已发布结果查询或原文研究。
2. Claims、items、relations 是独立角色；首轮共用提取配置不包含 M_main。同源快照先于角色任务生成，R2 不以 Claims facts 为必需输入。
3. 复用 EvidenceRun/EvidenceFact、MaterialRun/MaterialUnderstanding；新增版本/执行/发布封装，不发明第三套断言 Schema。items-only 不隐式调用 relations，关系只使用固定且合格的 R2 端点。
4. 必要条件、否定、表头和脚注属于证据依赖；缺失/歧义必须降级，不把引文存在和执行成功当成语义完整。原文金标不能从路由输出或成功任务反推。
5. 外部取证绑定 `cv2:<build_id>`、`chunk:<chunk_id>` 及准确 unit/cell/区间；不直接转交现有 `cv2:<source_id>`，不由模型猜定位。
6. 每次实际模型请求单独登记 attempt 并预留角色/批次预算；兼容请求也计账，首轮自动重试为 0。未知 outcome 不自动重发、不记零费用。核查只读、零模型。
7. 不可变工件与版本化语义发布清单分离；跨运行回读走受控文件 Adapter，不调用旧表 load_evidence_run 加载新 JSON，不恢复 save_evidence_run。
8. 查询只读，不隐式抽取。完整证据单元须经所有后处理进入真实请求消息，才可确认送达；充分证据不要求 Agent 例行 fetch，后台确定性引文核验仍保留。
9. 抽取执行账、语义发布清单、研究消费账、报告证据清单各有职责。A4 的 skip/observe/异常不等于验收成功，不把 semantic manifest 直接提交为报告清单。
10. 原文研究始终可独立运行；真实模型、生产库、受保护样本和主计划阶段放行均不能由本规格自动授权。
11. `reader-pdf-*` 表格默认不可信任其完整性：原文与定位留在快照供审计，但 packet 必须以
    `partial / table_untrusted_or_incomplete` 阻断 Claims、R2、发布、语义查询和 M_main 消费；依赖该
    表格的 prose 不得通过 context 旁路。只有经过独立完整性核验，并在新快照中显式标记
    `table_consumption_status=verified_complete` 才可放行。评分范围内的表格目标继续计缺口/FN，
    不得从分母删除；本规则不追溯改写冻结金标或历史质量报告。

## 3. 任务索引与依赖

编号是依赖 ID，不是要求把所有任务顺序执行。表中不复制状态；状态以 issue 为准。01 完成后，02/03/10 的无外部副作用部分可协调推进；共享文件由任务负责人协调，不并发覆盖。跨 R2 阶段的开发夹具前置不等于绕过该阶段放行门。

| ID | 独立任务 | Blocked by | 工作包 / 主计划 |
|---|---|---|---|
| 01 | [冻结范围、契约与开工资产](issues/01-scope-contracts.md) | 无本地任务依赖 | W0；R2-S0，接口决议供 S2 使用 |
| 02 | [同源快照、证据依赖与取证映射](issues/02-evidence-snapshot.md) | 01 | W1；R2-S1 |
| 03 | [独立 env 与模型 Adapter](issues/03-extraction-config.md) | 01 | W2；R2-S2 |
| 04 | [角色入口、路由与关系拆分](issues/04-role-execution.md) | 02、03 | W2；R2-S2 |
| 05 | [调度、执行账、预算及只读核查](issues/05-execution-ledger.md) | 04 | W2/W3；R2-S2/S3 |
| 06 | [工件保存、发布与跨运行回读](issues/06-artifact-publication.md) | 05 | W3；R2-S2/S3，非生产 S5 |
| 07 | [语义查询、分页与完整证据交付](issues/07-semantic-query.md) | 06 | W5 前置接线；R2-S2/S3 |
| 08 | [消费账与报告清单/A4 适配](issues/08-consumption-report.md) | 07 | W5 前置接线；R2-S2/S3 |
| 09 | [react/tui 接线及零模型端到端门](issues/09-react-replay.md) | 08 | W5 回放；R2-S3 |
| 10 | [评分、标注范围与质量门冻结](issues/10-quality-gates.md) | 01 | W0/W6 准备；R2-S0/S3 |
| 11 | [获准后的真实模型有界试验](issues/11-bounded-live-trial.md) | 09、10、独立授权 | W4/W5 真实消费；R2-S4/S5 部分 |
| 12—16 | [r3 修复](issues/12-r3-quality-remediation.md)、[r3 复验](issues/13-bounded-r3-trial.md)、[r4 复验](issues/15-bounded-r4-trial.md)、[r5 重放](issues/16-r5-offline-replay-remediation.md) | 11 | 历史失败诊断与零调用校验器修复 |
| 17 | [结构化提取收敛闭环与最终去留门](issues/17-structured-extraction-convergence-closure.md) | 11—16 | Claims 替换证明与 copper 最终 P1 去留门 |
| 18 | [material extractor 替换实现与严格依赖门](issues/18-material-extractor-replacement.md) | 17 的 P1 失败终态 | 保留上层架构，替换 items/relations extractor |
| 19 | [relation selection 后继路线零调用去留门](issues/19-relation-selection-successor.md) | 18 的 P14 失败终态 | 零调用区分格式与语义失败；R0 no-go 后关闭同模型后继 |
| 20 | [GLM-5.3-Flash relation-only 单变量有界复验](issues/20-relation-model-replacement.md) | 19 no-go、独立授权 | 仅换模型的 4-call 复验；输出 token 耗尽后关闭 |
| 21 | [GLM-5.3-Flash 16K 输出兼容性有界复验](issues/21-glm-token-compatibility.md) | 20 输出耗尽、独立授权 | 仅放宽 output tokens；仍无可见输出并出现 outcome_unknown |
| 22 | [Doubao Seed 2.1 Lite 供应商上限能力复验](issues/22-doubao-lite-provider-ceiling.md) | 21 兼容性失败、独立授权 | 256K + minimal 的 4-call 能力试验；有可见输出但协议/语义门失败 |
| 23 | [Relation 语义边界更正与零调用敏感性复评](issues/23-relation-adjudication-correction.md) | 22 的 7 条签认误差 | 保留 signed-v1；44/44 统一审计并由 xyl 签认 gold-v2 |
| 24 | [Relation question-group 布尔终态协议与零调用回放](issues/24-relation-boolean-protocol.md) | 23 signed gold-v2 | non-answer 改为局部索引 + boolean；4/4 packet、333/333 决定零调用闭环 |
| 25 | [Relation boolean v2 最终有界真实服从性复验](issues/25-final-relation-live-compliance.md) | 24 零调用通过、独立授权 | 4/4 协议完整；gold-v2 仅 30/38，按终止规则关闭路线 |
| 26 | [relation 层对研报抽取价值的有界配对验证](issues/26-relation-layer-value-validation.md) | 25、签认价值金标、独立授权 | 5 题 × A/B；提升 0/4、回退 2/4、持平 2/4且触发成本止损；关闭默认 relation 富化 |
| 27 | [challenges 显式命题冲突规则](issues/27-challenges-rule-propositional-conflict.md) | 24；不依赖或复活 25 | 零调用高精度防护和回归测试；仅供未来按需路径，不构成当前 relation 验收重启 |
| 28 | [items-only 质量门零调用预注册](issues/28-items-only-quality-gate-preregistration.md) | 27 关闭 relation 后；10 冻结 48-item 金标 | 零调用冻结 items-only 质量门与 5 阶段消费闭环；已执行终结（run-2 结构性未过门，路线按门终态关闭，见 31） |
| 29 | [items 金标全量语义审计](issues/29-items-gold-semantic-audit.md) | 28 预注册后；10 冻结 48-item 金标 | 零调用只读复核 48 条 items 原子性/可评分性/字段裁定并澄清契约签认缺口；发现缺陷须另立修正票 |
| 30 | [items 评分契约补签与 condition 读路径定义](issues/30-items-scoring-contract-condition-readpath.md) | 29 审计 F1/F2/F3；用户裁定路线 A | 不改金标，补签契约并定义 condition 读路径；签认后同步再绑定 Issue 28 门 |
| 31 | [run-1 突增保护失效与模型替换重跑](issues/31-run1-429-invalidation-model-substitution.md) | 28 门执行受阻解除后；用户授权与模型指定 | 记录 run-1 429 失效、模型替换（deepseek-v4-flash）与 run-2 结构性未过门；按门终态关闭路线 |

01—10 已交付基础架构、回放、评分和冻结资产。17 已使 Claims 达冻结门；18 已使 copper items formal
parent 合格并完成 relation-only P10，但整篇 relation precision 尚未通过质量门。所有结果仍为未发布
候选，query/delivery/context_use 与 M_main 正向消费未启动。P11 已签认通用 selector 误接/漏接模式；
P12 已完成 v2 的 4-call 实跑，但签认样本与 target recall 均退化，故该版本只保留审计、不进入发布。
P13 已完成 question-group answer selector 的零调用实现与 oracle replay；P14 最终有界 relation-only
plan 已使用完整 4 次预算执行。四次模型请求均完成，但两包把关系类型写入仅允许 `present/absent` 的
`status`，实际仅 2/4 packet completed，故在协议完整性门即失败；签认 44 例与 target 质量门不再作
有效计分。按冻结终止规则，当前模型+extractor 路线已关闭，不再允许 P15、prompt/schema 放宽或追加
调用；任何模型或算法替换都是新任务。19 又以只读 what-if 将 15 条 type-as-status 窄化解释为
present，完整恢复 333 个决定，但签认样本仅
32/44、已知错误 5/9、既有正确项回退 8，只有 target 4/4 通过；因此 selected-indices 只能修格式，
不能修复该模型的语义质量，后继路线在实现前关闭。
20 在新授权下保持 P14 输入、候选、prompt、Schema、请求参数和 44/9/35/4 门不变，
只把模型换为 `glm-5.3-flash`。四次运输都成功，但均以 `finish_reason=length` 结束，
16,384 completion tokens 中 16,377 为 reasoning，可见协议内容为空；因此 0/4 packet completed，
语义门不可评分。本结论只拒绝 GLM 与冻结 4096-token profile 的组合，不得写成 GLM 语义质量已证伪。
21 又在其余条件不变时将 `max_output_tokens` 提到 16,384。三个确定响应分别用时约
4.4—4.6 分钟，全部以 `finish_reason=length` 结束且为空；49,152 completion tokens 中
49,121 为 reasoning。第四次在 300 秒处 outcome_unknown，不得重发。因此单纯增加 token 已被
反事实否决；未来只能控制/禁用 reasoning，或使用能保证可见结构化输出的模型。
22 使用用户切换后的 `doubao-seed-2.1-lite`，明确设置供应商最大回答 262,144 tokens 和
`reasoning_effort=minimal`。四次请求均成功且 reasoning 为 0，返回 100 行可见终态；5 行
`challenges` 被写入 status，严格门为 2/4 packet completed。零调用窄化归一可恢复 333/333 决定，
但质量门为 37/44、7/9、旧正确回退 5、target 4/4、supports/conditions 回退 1，仍不发布。
23 先对上述 7 条误差复核，再按相同规则覆盖全部 44 条，避免只审失败项的选择偏差。全量审计新增
发现 `不一定全部` 缺少宾语、`还是什么？` 缺少问题谓词和指代对象两条不可评分端点；连同泛化问题、
复合 supports target、产能/产品结构绑定、交付/回款绑定，共排除 6 条。完整 `pair_window` 证明
“扩产意愿不大”和“半年就得换”是互补 answer atoms，两条 truth 从 absent 建议更正为 present。
gold-v2 草案因此为 38 条；对 Issue 22 已有响应零调用重算得到 37/38，等比例最低门 35/38，已知
错误 9/9、旧正确回退 1、target 4/4、supports/conditions 回退 0。唯一保留错误是把兼容厚度排序判成
challenge。该草案仍须独立签认；签认前不替换 P11 signed-v1，也不把 Issue 22 事后改写为通过。
用户随后以 xyl 身份签认 gold-v2。24 新增显式协议 `material-relations-question-group-jsonl-v2`：answers
继续返回 question-local selected indices，non-answer 仅返回 `relation_index` 与 JSON boolean
`is_present`，relation type、pair identity、证据窗口和 relation ID 均由 controller 回填。Issue 22 的
冻结决定经新协议零调用重放后为 4/4 packet complete、333/333 candidate decisions、100 terminals、
212 relations，missing/duplicate/invalid 全为 0；gold-v2 分数维持 37/38。该结果只证明 Interface 和
parser 闭环，不证明模型会服从新 shape，最终 live compliance 仍须独立计划与明确授权。
用户随后明确授权 25 的最终最多 4 次真实复验。新计划与 Issue 22 相比只把 question-group v1 换成
boolean v2；4/4 请求成功并形成 4 completed、333/333 决定、0 missing/duplicate/invalid，证明协议
修复在真实模型上生效。但签认 gold-v2 只有 30/38（最低 35），known errors 6/9（最低 7），29 条
非 known-error 案例回退 5（最多 2）；只有 target 4/4 和 supports/conditions 回退 0 通过。因此失败
根因已经从协议收敛为模型语义不稳定。按冻结终止规则关闭当前模型 + extractor 路线，不追加调用、
不改 prompt、不降门槛、不依据结果重整金标。
26 随后用冻结 items 与 Issue 25 relation 产物完成 5 题 × A/B 下游价值验证；relations 在关系题中
提升 0/4、回退 2/4、持平 2/4，并使中位输入 token 增加 24.33%，故触发预注册成本止损。27 的
`challenges` 显式命题冲突防护已通过零调用回放和 88 项回归，但只保留作未来按需实验的安全资产。
由此，当前 R2 的 relation 修复和验收工作流已关闭；下一阶段只处理 material_items 质量门及其
items-only 正向消费闭环。28 已按此零调用冻结 items-only 质量门（以 Issue 10 的 48-item 冻结金标为
分母）与 5 阶段消费闭环口径；该冻结不授权任何执行，真实复验须经人工单独授权。
29 在授权真实复验前对该 48-item 金标做了零调用只读全量语义审计：金标**含义**健全，但发现 condition
角色 6 条（NT-I09/I15/I19/I29/I35/I39）把原子内容仅存于 `condition` 而 `proposition` 只是标签，与契约
「只要求 `proposition`、不列 `condition`」冲突；同时评分契约自身 `status=draft_pending_human_review`
却被 Issue 28 门钉为度量基准，且 `condition_logic` 未进入任何 schema。故 items-only 质量门**执行受阻**，
冻结金标与 Issue 28 门均不得就地修改，须以 Issue 23 模式另立修正票后再申请复验授权。
30 已经用户裁定走**路线 A**（不改金标，仅补签契约并定义 condition 读路径），并已落地：评分契约升级并
签认为 `non-table-selected-target-scoring-contract-v3`（新增 `condition_role_read_path`，规定 condition
角色 items 的原子命题由非空 `condition` 字段承载、`proposition` 可为标签，并补齐 `compound_condition`
析取读法与 `condition_logic` 定位），`review_assertions` 与 Issue 28 门高风险断言清单补入 5 条 label-only
condition 项（NT-I09/I19/I29/I35/I39）；门同步再绑定 v3、`quality_requirements_status` 转 `signed`。
冻结金标与 freeze-state 字节未变，旧 v2 契约与旧门哈希留存于各自 `revision_history`/`supersedes`。
Issue 29 的两项门就绪阻塞据此解除；门仍处 `frozen_before_execution`，真实复验须经人工单独授权。
31 记录并收口随后的有界真实复验（2026-10-11）：首次授权（doubao-seed-2.1-lite，24 次、零重试、无节流）
中 16/24 次被方舟突增流量保护以 HTTP 429 瞬时拒绝（零 token、未触达模型），判定为基础设施失效、
不触发 on_fail；用户随即更换模型为 deepseek-v4-flash（20s 节流）重跑。run-2 **结构性未过门**：
12/23 响应违反冻结 selector JSONL 严格校验（记录缺 `record_type`，记录类型被写入 `status:"items"`），
13/24 批次 partial、107/190 槽位失败，execution/protocol 状态不达门；另 1 次传输结果不明。
经用户确认，按门冻结 `terminal_decision.on_fail` 关闭本门所验「模型 + extractor」路线
（run-2 deepseek-v4-flash 组合；run-1 doubao 组合因 429 失效未取得有效结果）：不放宽阈值、不改 prompt、
不新增金标。run-1/run-2 全部证据与终态记录留存（`evidence/28-…/r1-live`、`r2-live/run2-final-decision.json`）；
后续任何新模型/新协议路线须另立新门并经新的显式授权。
W6 的独立留出/多模型比较、W7 的生产化仍须另行立项，
不能通过单角色或单样本候选抽取成功自动宣布完成。

## 4. 01 已冻结的实现决议

本节是后续票据的接口真源。`contracts/contract-manifest.json` 及其绑定的 v1 Schema/样例是
机读版本；本文解释落点、事务和恢复语义。名称是后续实现目标，不表示生产入口已经存在。

### 4.1 模块、公开 Interface 与命令

- 新封装统一放在 `plugins/corpus/structured/`：`contracts.py`、`config.py`、`snapshot.py`、
  `roles.py`、`ledger.py`、`store.py`、`query.py`、`cli.py`。它们分别组合既有能力，不移动或
  复制 `EvidenceRun/EvidenceFact`、`MaterialRun/MaterialUnderstanding`。配置加载不得进入通用
  ReAct 内核。
- Python 调用面固定为 `build_snapshot`、`plan_batch`、`execute_batch`、`replay_batch`、
  `check_batch`、`publish_semantic`、`query_semantic`；研究 Agent 只暴露只读工具
  `corpus_semantic_query`，不暴露抽取执行工具。
- CLI 模块固定为 `plugins.corpus.structured.cli`，精确命令为：

```bash
uv run python -m plugins.corpus.structured.cli plan --snapshot SNAPSHOT.json --out PLAN.json
uv run python -m plugins.corpus.structured.cli execute --plan PLAN.json --store-root ROOT --allow-model
uv run python -m plugins.corpus.structured.cli replay --plan PLAN.json --responses RESPONSES --store-root ROOT
uv run python -m plugins.corpus.structured.cli check --batch-id BATCH_ID --store-root ROOT
uv run python -m plugins.corpus.structured.cli query --source-id SOURCE --build-id BUILD \
  --purpose cite --limit 20 [--cursor CURSOR] --store-root ROOT
```

  `plan` 只读快照并写调用方指定的计划文件；`check`、`query` 以 SQLite URI `mode=ro` 打开索引，
  不改账、不发布、不触发模型；`replay` 只消费显式响应目录并可写测试账；只有 `execute
  --allow-model` 可进入实际请求 Adapter。缺 `--allow-model`、专用配置或有效预算均在请求前拒绝。
  恢复继续使用已有 batch/task/attempt；`outcome_unknown` 不自动重发，另发请求必须显式建立新 attempt。
- 退出码固定为：`0` 成功；`2` 输入/Schema/协议非法；`3` 配置、根目录或安全边界拒绝；`4`
  预算、依赖、上下文或发布门未过；`5` 对象/版本/游标不可用或工件损坏；`6` 调用 outcome
  未知、需人工核查。细分错误码及 retryable 语义以 `contracts/v1/state-codes.json` 为准。

### 4.2 配置、文件布局与事务

- 文件根目录唯一配置键为 `CORPUS_STRUCTURED_ROOT`；CLI 的 `--store-root` 可显式覆盖。两者都缺失
  返回 `CS_STORE_ROOT_REQUIRED`，绝不回退 cwd、仓库扫描或旧 evidence 表。解析后的所有路径必须
  位于该根目录，越界返回 `CS_PATH_OUTSIDE_ROOT`。
- M_extract 仍只读 `STRUCTURED_EXTRACTION_PROVIDER/MODEL/BASE_URL/API_KEY`。四项按 provider
  契约整体校验，缺失返回 `CS_CONFIG_MISSING`；不逐字段回退 `OPENAI_*`。确定性任务、回放、
  check、query 在这些变量缺失时仍可运行。
- 根目录格式冻结为：`objects/sha256/<前两位>/<hash>.json|jsonl` 保存不可变快照、响应和角色工件；
  `manifests/<publication_id>.json` 保存不可变语义发布清单；`index/structured.sqlite3` 保存 batch、
  task、attempt、预算预留、派生任务、发布 generation/head；`cache/heads/` 仅保存可重建的发布指针缓存；
  `scratch/` 保存临时文件。manifest/ledger 绝不保存 API key 或含凭据 URL。
- 写端使用 SQLite（WAL、`foreign_keys=ON`、`synchronous=FULL`、`BEGIN IMMEDIATE`）完成“批次与角色
  额度检查 + attempt 预留”单事务；框架 no-op EventStore 不参与。不可变对象先写同目录临时文件、
  fsync 后 `os.replace`，但该原子替换不承担预算事务。
- 发布由同一 SQLite 的 source/build 行串行化，事务中比较父 generation、登记不可变 manifest hash
  并更新权威 head；`cache/heads` 在提交后刷新，仅是缓存。进程在 DB 提交后、缓存刷新前崩溃时，读端
  以 DB head 为准并可重建缓存；对象写成但未被事务引用时视为孤儿，不自动发布。研究读端使用只读
  连接和只读对象权限，不获得后台写权限。

### 4.3 Schema、哈希与坐标

- v1 分别冻结 snapshot、batch/task/attempt、角色工件、semantic publication、query/page、report
  semantic reference 六类封装。所有封装必有 `schema_version`；合法/非法样例与字节指纹由
  `contracts/contract-manifest.json` 绑定。
- batch plan 的 accepted-items 导入使用 `corpus-batch-plan-v2`；v1 继续按原身份只读兼容，但不得携带
  import payload。v2 的新增字段是自包含且参与 plan hash 的源 artifact/payload，不从执行机路径解析。
- 角色工件只记录业务 payload 的媒体类型和 SHA-256：Claims payload 必须验证为现有
  `EvidenceRun/EvidenceFact`，R2 payload 必须验证为现有 `MaterialRun/MaterialUnderstanding`；不创建
  第三套 Claim/Item Schema。
- 身份哈希为小写 SHA-256；输入使用 UTF-8、键排序、紧凑 JSON，数组保序。snapshot 身份必须含
  schema/parser/clean/chunk 版本、source/build/publication generation、unit/chunk、证据类型、locator、
  坐标系与起止、text hash、metadata hash；task/artifact/publication 身份再绑定其 profile、输入、上游
  artifact 和规则版本。时间戳、绝对路径、密钥及可变状态不进入身份。
- 原文区间固定为 exact unit `text` 上的零起点、半开 `[start,end)` Unicode code-point 区间；不是
  UTF-8 byte、UTF-16、PDF glyph、页内或拼接全文坐标。对外句柄为
  `cv2:<build_id>#chunk:<chunk_id>`，另带 unit、locator、text hash 和区间。重复引文必须靠句柄与
  区间区分，不按首次字符串命中。

02 的追加实现修订 `structured-snapshot-2` 不修改已冻结 v1 Schema：完整 gaps 摘要通过
已参与身份的 metadata 绑定，dependencies 必须与已哈希的明细一致。旧 builder-1 快照缺少这些
保证，消费端拒绝并要求重建。packet 内部拼接坐标必须经 `structured/mapping.py` 转换为上述
原文句柄；cell 标签缺少显式原文区间时降级，不推测表头。修订证据与限制以 02 文末记录为准。

### 4.4 状态、转换与跨角色映射

- 六个状态域严格分开：execution、protocol、publication、context、mapping、quality。唯一枚举和
  合法转换在 `state-codes.json`；执行成功不推出协议有效、发布、语境完整、跨角色一致或质量通过。
- `unlinked` 表示尚无可证对应，不能解释为 `confirmed`；`suspected` 需保留原因；只有相同 snapshot、
  可定位命题跨度/cell 及主体/指标或对象/期间绑定可确认时才为 `confirmed`。可比字段在 value、unit、
  factuality、polarity、condition 或 attribution 上不同则为 `conflict`，受影响 compare/calculate
  许可撤去，但不静默改写任一业务 payload。
- Claims/items 可独立合格和发布；relations 只依赖固定且合格的 material item IDs。关系失败不撤销
  items；端点撤回后旧关系不能自动挂接新 item。未执行、无候选、未就绪、预算不足必须使用不同状态/
  原因，不能都写成“无关系”。
- relation plan 必须冻结 `dependency_policy`：`qualified_subset` 允许从 partial items 中仅取已验证
  extracted 端点，适合局部独立发布；`complete_parent` 要求 parent items 为
  `succeeded / valid / accepted`，适合完整样本质量门。两种策略不得由运行器临时口头切换，且必须进入
  plan hash。17 的 copper 证明 Markdown stop policy 不足以替代机读依赖策略；18 已补上该硬门。
- 已验收 items 的跨批复用必须通过 plan 内自包含的 `AcceptedMaterialItems` 导入：同时绑定源
  `RoleArtifact`、`MaterialRun` payload hash、snapshot 和 items-only 状态。导入 task 的 method 固定为
  `imported`、`max_attempts=0`，在当前 formal ledger 生成带 upstream artifact ID 的新父工件；不得以
  文件路径旁路、独立 attempt ledger 或重跑 items 代替。

### 4.5 首轮协议与关系候选范围

| 角色/方法 | 首轮唯一支持协议 | 约束 |
|---|---|---|
| Claims table | `claims-deterministic-v1` | 仅显式 `verified_complete` 的结构完整 cell 可确定性投影；PDF reader 表格默认审计留存且拒绝消费，零模型 |
| Claims prose | `claims-json-v2` | 复用 ClaimRecord/EvidenceFact 规范化与校验 |
| R2 items | `material-atomic-selector-jsonl-v5`（新计划显式选择）；selector v1-v4 / `material-atomic-jsonl-v5`（历史可读） | controller 拥有 slot/item ID、终态和逐字 evidence span；模型只返回批内义务 selector 与语义字段；controller 规范 absence-valued 字段、显式数值区间、明确话语归属与通用判断性标记，一个候选槽最多四个原子 item，禁止隐式 relations；extractor `material-semantics-32`，校验版本 `material-items-validation-v11` |
| R2 relations | `material-relations-question-group-jsonl-v2`（新最终计划显式选择）；question-group v1、selector v1-v2 / `material-relations-jsonl-v1`（历史可读） | answers 返回 question-local selected indices；non-answer 只返回 relation index 与 JSON boolean；controller 拥有 pair/relation ID、端点、类型和逐字 `pair_window` 并回填关系；字符串布尔、旧 status shape 和 type-as-status fail closed |

该表保留 relations 的历史可读与按需实验契约，不表示默认启用。Issue 26 之后，首轮产品和 R2 验收
默认只交付 items；除非新的业务问题另立价值门并获授权，调度不得把 relations 加回默认上下文、发布
前置条件或验收阻断项。Issue 27 的 `material-relation-rules-v2` 继续对按需路径生效：普通转折不构成
challenges，缺少显式纠正/否定线索的 positive terminal 归一为 absent。

历史联合 JSON、旧 `material-jsonl-v1`、slot 模式中的隐式关系和其他 provider 特有格式不在首轮支持
矩阵，真实请求前返回 `CS_PROTOCOL_UNSUPPORTED`，不静默降级。关系候选只从同一 snapshot、同一或
显式复合证据包中已合格 items 的原文明示连接词、问答配对、归属结构及已版本化确定性规则生成；不以
共现生成因果，不跨文档，不使用 Claims fact_id 作端点。每父 items task 最多一个派生候选清单；批次
计划分别冻结候选规则版本、dependency policy、最大关系 tasks 和最大 attempts，超出须新计划。

### 4.6 查询、分页与报告引用

- `corpus_semantic_query` 输入固定 source/build、purpose、词法/字段过滤、limit/cursor；首轮排序为
  `semantic-lexical-sort-v1`，不做 LLM query rewrite/rerank。游标绑定 query hash、排序版本、
  publication ID/generation 和页位置；撤回、用途收紧或发布变更返回 `CS_CURSOR_STALE`，不得跨版续页。
- 返回的 evidence unit 必须把 value/period/unit/header/footnote/condition/negation/attribution 依赖
  与原文范围成组交付；依赖状态与 `usable_for = cite|compare|calculate` 分开。预算放不下完整单元时少返
  一条并标 `budget_limited`，不截断 JSON，不只发裸数值。
- 报告引用固定携带 report anchor/quote、publication ID、record ID、purpose、一个或多个精确原文
  ranges、逐依赖 required_for/status、delivery/publication/quality/verification 状态。只有原文确实进入
  实际模型消息后 delivery 才能从 pending 变为 delivered；后台 resolver 核对或工具返回成功不算送达。
  semantic publication manifest、执行账、消费账和 report evidence manifest 互不替代。

### 4.7 合成资产与指纹

- Schema 清单：`contracts/contract-manifest.json`，SHA-256
  `039d56e5261ddf4847da7457d0972afebc628cb8fb35ccde40669ce83230befa`。
- 合成资产清单：`tests/fixtures/corpus_structured_synthetic/asset-manifest.json`，SHA-256
  `6f9cc51597601b05e220ce3b74696269311ff50d246cf8272aced833a491d073`；cases SHA-256
  `df2f1c9e4005a13702df798df0141b397c99a90e68ff9a8f1b4179692a23b179`。覆盖普通数字、纯观点、
  混合条件、否定、预测/实际、表头/脚注、跨包限定、重复引文、解析缺口；全部虚构，不含真实业务原文。

### 4.8 主计划前置核对与边界

- 已从唯一主计划公开台账核验：I0 A/B/C 已完成；I1 已完成并经 M4 独立复核与 U 签认；这些证据允许
  本票继续规格与合成资产工作。未读取其受保护来源或留出内容。
- I3/S3 的阶段放行不能由本专项替代。09 的零模型回放已通过但待复验签认；10 已将候选输出前
  人工确认的 E01—E12 冻结为部分关键检查点，阈值与裁定人也已签认，但诊断评分未通过，且该集合
  不是每角色至少 20 条的完整三角色金标。后续从两份获准、尚未执行本专项候选的真实开发材料
  起草并修订的非表格 Claims/items/relations=20/48/24 r2 有限目标包，已由 xyl 签认并通过追加式
  冻结；该包不宣称整篇穷尽标注，额外正确输出须独立裁定、不自动计 FP，全部候选未裁定前不能
  报告完整 precision，因此真实质量门仍未过。正式冻结证据位于 `evidence/10-quality-gold-freeze-20261008-r2/`。
- 用户已于 2026-10-04—05 明确批准贵州茅台研报范围并授权有界真实提取调用；11 已执行 Claims
  preflight 和第 1 页 R2 语义抽取。该授权只覆盖开发试验，不转授生产 PG、受保护留出、正式发布或
  M_main 消费，也不能补足 10 的金标与质量分母。
- 01 初始冻结没有修改主计划、report 或既有 freeze/guard/gold；后续 Issue 18 已在不修改既有金标和
  阈值的前提下追加执行证据，并同步本专项 spec/report。历史 plan、response object 和签认文件仍按
  manifest 保持不可变；修订均另立 P4—P8 目录或追加 Comments，不把旧失败原地改写成通过。

## 5. 全局执行约束与验收纪律

- 01—10 仍保持真实模型请求与生产数据库访问为 0，只用 fake/replay、合成夹具和显式批准的本地开发
  资产。11 已在独立授权下产生 116 次真实提取 attempt（其中本轮 r2 为 48 次），自动重试 0，生产数据库和 M_main 调用仍为 0。
  不得使用工具查询隐式触发模型；SDK 自动重试和隐藏兼容请求也必须计账。
- 文件测试写 pytest 临时目录或明确的专项输出目录。不得读取真实 `.env` 密钥作为测试数据；环境隔离测试使用假值。读端/主线不获得后台写权限。
- 01 已创建本专项的 v1 Schema、正反例和合成 fixtures；02—08 已实现第 4 节主要 Interface，并由
  09 的文件工件产品回放接通。这里的“已实现”不等于生产 PG、真实质量门或默认产品启用；未采集的
  环境/真实消费证据和被跳过的必要用例仍不能算通过。
- 每票使用调用方相同 Interface 测试。保存测试命令、退出码、结果、适用范围、基线/工件指纹及已知限制；仅把 fixture 手工填成预期状态不能证明接通。
- Python 环境按仓库使用 uv；命令从仓库根目录执行，不通过 pip 安装。新增开发测试须明确阻断真实网络/模型/生产数据库，尤其防止 uv 环境准备之外的测试业务路径触外部资源。
- 代码任务按影响执行 Ruff、类型检查、符号闭包及 import smoke；真实模型 preflight 只能在 11 获准预算内运行。零模型阶段明确记录其未执行，不宣称所有提交前门已通过。
- Issue 18—25 共有独立授权的 82 次 selector model attempts（P3 23、P4 23、P5 4、P8 relations 4、
  P10 relations 4、P12 relations 4、P14 relations 4、Issue 20 GLM relations 4、Issue 21 GLM-16K relations 4、Issue 22 Doubao Lite relations 4、Issue 25 boolean-v2 relations 4）；P6/P7 replay、P8 candidate-v4/v5 反事实、scorer-4 重评与 P9
  preflight 均为 0 模型调用。P9 在配置检查时 0 attempt 阻断并由新 plan 取代；P10 与 P12 各恰好执行
  4 次 relation 调用、4/4 succeeded、0 retry，items/Claims attempts 仍为 0。P12 协议成功但质量门失败；
  P14 在协议门失败；Issue 20 四次均耗尽 4K 上限且为空；Issue 21 放宽到 16K 后三次仍为空、一次 outcome_unknown；
  Issue 22 的 4 次 Doubao Lite 请求均成功并产生可见输出，但严格协议与签认语义门仍失败；Issue 23/24
  均为 0 调用审计/实现，Issue 25 最终 4 次通过 boolean v2 协议门但未通过 signed gold-v2 质量门。
  这些执行均不转授 publication、query、delivery、context_use 或额外 live budget。
- Issue 26 另经授权执行 10 次 M_main 配对研究运行，relation 抽取和 judge 均为 0；盲评、解盲与最终
  裁决证明默认 relation 富化无正向价值并触发成本止损。该预算不计入上述 82 次 selector attempts，
  也未产生生产 query、publication 或数据库访问。
- 未落定决议在对应 issue 中保持 needs-info/needs-triage，不由实现者选择会扩大数据、预算或产品范围的默认值。不得以“本地票已完成”代替主计划阶段签认。

## 6. 第一阶段完成条件

09 的回放闭环能从固定快照生成、发布并跨运行读取两路结果，经实际 react/tui 工具链送达证据、提交报告清单，正例最终 verified；仅新查询不 skip，充分证据不例行 Agent fetch。缺脚注、错误句柄、裁剪、撤回、未知调用和损坏工件均产生预期缺口/降级，零真实模型调用可核验。

10 单独交付质量评分与标注冻结；不得把接线通过当作模型准确率过门。11 已在具体模型/来源/预算获得
独立授权后开展有界开发试验，但 09/10 和阶段门未闭合，因此其结果只能作为候选与缺口发现，不能
倒推阶段验收。当前历史消费账/清单测试只作为回归基线，不是上述真实闭环的验收证据。

## 7. 任务状态维护

每个 issue 的 `Status` 使用仓库分诊标签；`Execution` 记录未开始/进行中/待验收/已验收，只有交付与验收证据齐备才可标已验收。`Blocked by` 指向必须先验收的票据，外部门另列。不得把 ready-for-agent 当作已完成；依赖解除后须复核任务契约，再改变分诊状态。每次执行结论追加到该票据 `Comments`，阶段证据回填唯一主计划，本索引不复制执行进度。
