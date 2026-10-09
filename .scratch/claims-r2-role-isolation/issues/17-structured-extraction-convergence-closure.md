# 17 · 结构化提取收敛闭环与最终去留门

Status: p1r5-claims-metrics-pass-awaiting-delta-signoff
Execution: 替换 Claims 实现已完成 19 个不可变响应的最终零调用重放；增量裁定预览 precision 50.91%、recall 100%，数值门通过但 36 条新增/变更裁定仍待 xyl 签认。copper、生产库与发布均未启动
Type: task
Parent: [11 · 获准后的真实模型有界试验与单文档消费](11-bounded-live-trial.md)
Model calls: 36（P1 17；P1R1 9；P1R2 8；P1R3 路由增量 2；其余重放 0）
Production database access: 0

## 目标

保留同源快照、Claims/items/relations 角色隔离、执行/发布/消费分账和 fail-closed 门禁；停止继续堆叠
样本词典或重复前三个开发样本。先关闭历史回读、attempt 留痕、自动早停、评分契约和任务容量问题，
再用一次有界证明决定是否保留当前 extractor 实现。

## 范围约束

- 本票不重新制作或修改已签认金标，不改变质量阈值。
- P0 全部为零模型工作；P0 未完成前禁止新真实请求。
- 第 2—3 页未核验图像表格继续 fail-closed，本票不引入 OCR/reader 新项目。
- 不发布未过门候选，不调用 M_main，不访问 holdout 或生产数据库。
- 历史 `outcome_unknown` 不自动重发；新请求必须使用新 batch/attempt。

## P0-A · 已完成的工程闭环

- [x] 补齐 `material-semantics-14`—`21` 的历史 payload shape；现存 139 份工件副本、109 个唯一
  `run_id` 均能在当前版本下通过身份校验。
- [x] 增加 v14—v21 回读回归测试，避免再次把已有结构化版本误判为 pre-structure。
- [x] 开发实跑器在调用前追加只写 `running` attempt 记录；成功响应不再只为 failed/partial 保存，
  而是在返回后立即以 0600 权限保存原文、响应哈希和 terminal 记录。
- [x] 未分类异常/中止记为 `outcome_unknown`；同 round/sample 已存在 attempt 审计时在请求前拒绝复跑。
- [x] 每个样本完成后立即执行冻结的 stage-1 gate；命中
  `any_failed_or_partial_packet` 或 `any_in_scope_metric_floor_decrease` 时，不启动下一样本。
- [x] spec 的 item 协议更新为 `material-atomic-jsonl-v5` + validation v6；report 明确标为历史方案基线。

## P0-B · 零调用任务

1. **统一执行入口（已完成）**：development scratch runner 已在读取预算或初始化 provider 前拒绝直接
   live 模式，只保留 `--plan-only` 和 `--replay-report`。后续真实请求必须先经
   `python -m plugins.corpus.structured.cli` 冻结 plan，再由正式 ledger 原子预留授权、attempt、响应对象与
   terminal 状态；不能再由 scratch 的文件记录旁路授权。
2. **复合评分规则（已完成）**：`material-development-scorer-3` 允许一个复合金标由最多四个、同一
   semantic/statement/speech/perspective/speaker/behavior/temporal 坐标且引文匹配的原子 item 共同满足；
   mixed polarity 必须包含 mixed 或 affirmed+negated，复合 value 必须完整拼合，unknown_fields 取并集，
   relation endpoint 按原子端点笛卡尔映射。最小满足组优先，不相关 speaker 即使同引文也不得并入；
   option expiry 等值表示不一致仍失败。金标与阈值未修改。
3. **压缩铜箔任务容量（已完成确定性规划）**：不删除 487 个槽、不改变原文范围和金标覆盖；新增
   `material-slot-batching-v2`，普通原子槽按硬信号数预留 item 容量，summary 和无法归属的混合话轮仍按
   四条上限保守预留。在 `max_slots=48/max_items=64` 下，铜箔 item batches 从 32 降至 12，四样本计划
   从 42 降至 17；原 `max_slots=16` 基线仍为 42，证明变化来自显式新容量配置而非暗改历史计划。
4. **Claims 绑定门（零调用审计已完成，质量门未过）**：已用现存签认候选与 20 条冻结目标复算。
   132 个候选中 15 matched、22 correct-extra、94 incorrect、1 duplicate，precision 28.03%、recall 75%；
   主体绑定失败涉及 67 条、指标绑定 94 条、期间绑定 57 条、值/单位绑定 63 条（各组重叠）。当前
   `evidence-pipeline-8` 的可信文档主体继承能反事实修复 67 条的主体轴，但这 67 条全都仍有至少一个
   非主体阻断原因，不能据此宣称通过。5 条未召回目标及并列数值/期间歧义已冻结在
   `claims-binding-audit.json`；下一次只做 Claims-only 最小真实证明，不重制金标。
5. **版本冻结清单（待最终真实计划生成时封口）**：本轮清单已记录 extractor v27、slot batching v2、
   item protocol v5、validation v6、relation candidate v3、scorer 与修改文件哈希；P1 的正式 plan、配置和
   预算哈希必须在请求前追加冻结，任何漂移均拒绝执行。

## P1 · 唯一允许的最终真实证明

P0-B 全部完成后建立新 batch，分成两个可独立早停的最小臂：Claims 只复验冻结的两来源/24 单元，
验证当前原子坐标与主体继承修复；items 仅执行此前未完成的铜箔范围，随后只对固定合格端点执行
relations。items 不重复 company/industry/trade 三个已执行样本，不全量重制或重审金标。并发 1、
自动重试 0、逐 attempt 留痕、样本/批次边界自动早停。

通过条件：Claims 达冻结 precision/recall 门；第四样本完整、冻结 item 指标不低于 floor、relations
达冻结门且成本在新容量上限内。
任一失败时停止当前 extractor 的 prompt/lexicon 修补，保留上层接口并另立替换实现任务。

## P2 · 最小正向消费闭环

仅在 P1 通过后，从实际通过质量门的最小 Claims/items/relations 范围执行一次：

`publish → positive query → delivery → context_use → report reference`

该步骤只证明受测范围接通，不宣称表格、holdout、全库、生产 PG 或普遍收益。

## 完成定义

- P0-B、P1、P2 各有独立工件、指纹和零/真实调用计数。
- 不再以全量重做人工金标作为每轮默认步骤；已冻结金标用于回归，仅在新增来源类型、Schema 语义变化
  或抽样争议项上做增量人工裁定。
- P1 失败则明确记录“保留架构、替换 extractor 实现”，不创建 v27/v28 样本词典补丁继续循环。

## Comments

- 2026-10-09：根据结构化提取执行回溯建立；P0-A/P0-B 已完成。下一动作仅为冻结两个正式
  structured P1 plans；在其预算与哈希落盘前不发起真实请求。
- P0-A 验证清单：
  [repair-validation.json](../evidence/17-structured-extraction-convergence-closure-20261009/repair-validation.json)。
- Claims 零调用绑定审计：
  [claims-binding-audit.json](../evidence/17-structured-extraction-convergence-closure-20261009/claims-binding-audit.json)。
- 2026-10-09：P1 两份 Claims 正式计划共执行 17 次、自动重试 0；125 个候选中至少 7 个冻结
  目标被必需字段/漏召回硬阻断，理论召回上限 13/20（65%），因此没有继续做 125 条全量人工裁定，
  也没有启动 copper。门禁结果：
  [p1-claims-gate-result.json](../evidence/17-structured-extraction-convergence-closure-20261009/p1-claims-gate-result.json)。
- 2026-10-09：按失败分支保留 snapshot/ledger/role/store 接口，替换 Claims 绑定实现：新增
  `claims-atomic-json-v1` + `claims-slot-obligations-v1`，每个确定性原子候选槽必须返回 Claim 或带原因的
  `no_supported_claim` 终态；漏终态/跨槽引文直接把包标为 partial。绑定层新增短年份/相对期间、范围值、
  `亿` 与计数单位、industry 子主体误放 metric 的确定性修复；旧 `claims-json-v2` 继续兼容。
- P1R 零调用冻结：
  [manifest.json](../evidence/17-structured-extraction-convergence-closure-20261009/p1r-claims-plan-freeze/manifest.json)。
  两来源仍为同一签认 24 单元，预算上限 24 次、并发 1、自动重试 0；工业富联 49 个候选槽/9 个候选包，
  光模块 27 个候选槽/8 个候选包。P1R 未过冻结门前继续禁止 copper 与发布。
- 回归验证：相关测试 305 passed；全量 corpus 1354 passed、17 skipped，仅保留两项已知环境基线失败
  （本地 golden 检索语料 0/20；reader-pdf-10 断言与当前 reader-pdf-11 环境不一致）；ruff 与 pyright 通过。
- 2026-10-09：P1R1 工业臂 9 次响应语义可用，但两包未复制槽位 ID，协议 fail-closed，光模块未启动；
  `claims-atomic-json-v2` 仅允许“唯一精确引文所有者”确定性回绑。P1R2 随后零调用重放工业臂、8 次执行
  光模块臂，17 包全部协议有效。
- 2026-10-09：门禁复核发现 `body[3]` 含 1.5 亿只及 5—10 万个仍被 v1 路由排除。路由升级为
  `corpus-role-routing-v2` 后只新增 `body[3]`、`body[51]` 两包；P1R3 复用前 17 份响应，仅新增 2 次调用，
  19 包全部协议有效。随后用 P1R4/P1R5 零调用重放验证共享倍率、计数单位、近似季度、分类状态、隐式
  公司/产品主体及早期估计的同句边界，未再次调用模型。
- 2026-10-09：P1R5 共产生 110 条 Claims 候选；74 条复用既有 xyl 签认，36 条为新增或坐标变化的
  增量裁定草案。代理预览为 matched/correct-extra/incorrect/duplicate = 20/36/51/3，precision
  56/110（50.91%）高于 37/132（28.03%）floor，recall 20/20（100%）高于 15/20（75%）floor。
  在 36 条增量裁定获具名签认前，`human_gate_satisfied=false`，继续禁止 copper 与发布。证据：
  [P1R5 执行摘要](../evidence/17-structured-extraction-convergence-closure-20261009/p1r5-claims-replay-freeze/execution-summary.json)、
  [增量裁定草案](../evidence/17-structured-extraction-convergence-closure-20261009/p1r5-claims-adjudication-v2/candidate-adjudications.agent-draft.json)、
  [门禁预览](../evidence/17-structured-extraction-convergence-closure-20261009/p1r5-claims-adjudication-v2/gate-preview.json)。
- 最新全量 corpus 回归：1360 passed、17 skipped；仅两项既有环境基线失败（本地 golden 语料
  Recall 0/20；测试仍断言 reader-pdf-10 而当前环境为 reader-pdf-11）。
