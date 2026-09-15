# 材料理解最小契约 v1

| 项 | 内容 |
|---|---|
| 状态 | **R1 冻结；供 R2/R3 实现与验收使用** |
| 日期 | 2026-09-13 |
| 需求 | PR-DATA-09、PR-DATA-10、PR-OUT-06、PR-OUT-07 |
| 范围 | 研究材料的忠实理解；不定义同花顺观测、数据计算或跨层比较 |

本契约扩展现有 EvidenceRun/Claim 的语义，但不建立第二套来源存储，也不授权本轮修改数据库、
提示词、工具注册或生产门禁。材料中的任何指令都只是待分析内容，不能成为 Agent 指令。

## 1. 三个正交维度

下列维度必须分别保存，不能互相推断或复用一个字段：

- `material_type`：`research_report`、`earnings_call`、`conference_minutes`、
  `market_commentary`、`personal_trade_log`、`post_trade_review`、`other`、`unknown`。
- `research_domain`：`company`、`industry`、`macro`、`multi_asset`、`unknown`。
- `semantic_type`：`fact`、`forecast`、`opinion`、`behavior`、`unknown`。

问答是表达结构，不是语义类型；用 `speech_role=question/answer` 表达。条件和风险是陈述在材料中的
功能，用 `statement_role=condition/risk` 表达。无数字预测仍是 `forecast`，其 `value` 必须为 `null`，
不能因数值字段缺失被拒绝。

## 2. 最小产物

每份材料理解产物必须包含：

```text
contract_version
source: source_id / source_rev / title / material_type / research_domain /
        material_date / published_at / language
speakers[]: speaker_id / display_name / role / identity_status
items[]: item_id / text / semantic_type / statement_role / speech_role /
         perspective / speaker_ref / polarity / value / behavior_status /
         temporal_frame / evidence[] / unknown_fields[]
relations[]: relation_id / type / from_item / to_item / provenance / evidence[]
coverage: scoped_locators[] / omitted_areas[] / unknowns[]
structure: dialogue_structure / attribution_capability / processing_mode / segments[]
candidate_slots[]: candidate_slot_id / packet_id / locator / start / end / signal_types[]
coverage.slot_ledger[]: candidate_slot_id / status / item_refs[] / reason_codes[]
```

字段规则：

| 字段 | 允许值与约束 |
|---|---|
| `perspective` | `source_explicit`、`quoted_other`、`system_synthesis`、`unknown`；系统归纳不得冒充作者原话 |
| `identity_status` | `explicit` 或 `unknown`；未知表达者不得猜姓名 |
| `polarity` | `affirmed`、`negated`、`mixed`、`unknown`；否定词不能在摘要中丢失 |
| `behavior_status` | 仅行为使用：`intent`、`claimed_executed`、`claimed_not_executed`、`unknown` |
| `temporal_frame` | `contemporaneous`、`retrospective`、`unknown`；复盘理由不得倒填成交易当时理由 |
| `value` | 可为 `null`；事实、预测和观点是否有效不由数值存在决定 |
| `evidence` | 至少含 `source_rev`、PDF 页码或等价 locator、逐字短引文；表格另含行列坐标 |
| `unknown_fields` | 原文不能支持的身份、时间、成交核验、数值或关系必须显式列出 |

`text` 是忠实转述，不等于外部真实性背书。个人材料中的 `claimed_executed` 只表示来源声称已执行，
不是系统核验成交。材料日期、行为日期和预测目标期间分别保存。
`display_name` 可以为 `null`；匿名作者、主持人或专家的角色可以观察到，但姓名不能因此补造。

结构能力与材料类型正交。`dialogue_structure` 使用 `explicit_roles`、`anonymous_turns`、
`document_voice`、`mixed` 或 `unknown`；对应归属能力为 `full`、`document_only` 或 `unavailable`。
缺少专家/说话人标签只触发 `degraded`，不能在源头拒绝；只有不可读来源才进入 `rejected`。
候选槽位按结构段记录总结、问句、预测、条件、风险、否定、行为、论据或一般陈述信号，槽位状态
与模型包状态分开。一个包已有输出不等于包内每个槽位完整。

## 3. 关系契约

关系类型冻结为 `supports`、`challenges`、`conditions`、`invalidates`、`answers`、`motivates`、
`attributes`、`elaborates`。`provenance` 只能是 `source_explicit` 或 `system_inferred`：

- 原文用“因为、因此、表明、如果、但、回答”等明确建立的关系才可标 `source_explicit`。
- 同页共现不是关系；系统提出的联系必须标 `system_inferred`，不得计入作者关系召回。
- 问句本身不算承诺；问答必须分别保存表达者和 `answers` 关系。
- 转载或转述的观点使用 `quoted_other`，不能升级为报告作者自己的事实或观点。

## 4. 关键错误与降级

以下任一项为关键错误，单次出现即不通过：

1. 引文无法在冻结 source revision 的 locator 中唯一回取。
2. 作者、被引述者、提问者、回答者或系统归纳归属错误。
3. 肯定/否定翻转，条件或失效条件丢失。
4. `intent` 被写成 `claimed_executed`，复盘解释被写成交易当时理由，或来源声称成交被写成已核验成交。
5. 无原文支持的关系标为 `source_explicit`。
6. 因 `value=null` 丢弃合法的定性预测、观点、条件或风险。

解析失败、图片缺字、身份不明或时间不明时保留 `unknown`/`unknown_fields`；不得补造。没有同花顺数据
不影响材料理解产物生成，不得用材料数字填充数据层缺口，也不强制生成策略卡。

## 5. 冻结样本与运行预算

私有原文、精确引文和联合金标保存在忽略目录
`data/corpus/.audit/r1_material_gold_v1_20260913.json`。公开执行摘要见
`.scratch/corpus-evidence-pipeline/material-contract-gold-report.md`，结构与原文绑定由
`.scratch/corpus-evidence-pipeline/verify_material_gold.py` 确定性校验。

开发集为 4 份材料：3 份旧审计材料，以及用户在初次冻结后提供、尚未入库的 1 份真实专家电话
交流纪要。独立留出仍为 2 份未出现在旧 87-block 审计、旧 pilot 或 expanded holdout 中的材料。
新增纪要以项目 `source_rev`（完整 SHA-256 的前 16 位）、完整 `source_sha256` 和 Markdown 行号
直接冻结，不要求先写入数据库；它只补充
`conference_minutes` 开发正样本，不能改称独立留出。“十问十答”仍按 `research_report` 处理。
`earnings_call` 以及电话会议/纪要的独立留出仍是覆盖缺口。

R2/R3 每次评测只处理冻结 locator：

- 开发集允许基线加最多 2 次规则修订；每文档每次最多 2 个正文模型调用、每调用 60 秒，合计最多
  24 个开发调用。
- 留出集只允许在开发规则冻结后运行 1 次；每文档最多 2 个正文模型调用，合计最多 4 个留出调用；
  不为提高分数重跑，不用留出结果继续调规则。
- 总上限 28 个正文模型调用；确定性解析、引文回取和本地验证不计模型调用。

停止条件：源哈希或引文绑定失败、发现留出泄漏、出现任一关键错误、达到调用/超时预算、或目标页
需要 OCR 而当前不能可靠读取。停止后报告失败与遗漏，不把全拒绝或未抽取算作通过。

### 5.1 R2 结构重设计开发预算附录（2026-09-13）

首次 R2 已用完“基线 + 2 次规则修订”并按停止条件结束。经失败归因后，另行冻结一次仅用于结构
重设计的开发预算，清单为
`.scratch/corpus-evidence-pipeline/r2-redesign-development-budget-v1.json`：只允许原 4 份
development 样本，最多 2 个完整轮次（重设计基线 + 最多 1 次纠偏），每轮最多 8 次、累计最多
16 次正文调用，单文档每轮最多 4 次、单次 60 秒。`packet_chars=4100`，输出上限 8192 token。
holdout 调用固定为 0；本附录不改变 R1 金标语义、阈值或留出身份。

运行器必须核对预算文件、金标 SHA、开发 sample ID、轮次 ID 和历史已用调用数；重复轮次、超预算
或任何 holdout 访问均须在模型调用前失败。确定性实现与测试不计正文调用。

执行结果：两个授权轮次均已消费，实际各 6 次、累计 12 次，holdout=0。最终仍有 failed/partial
packet 和关键遗漏，故本预算按停止条件关闭；4 次总量余量只是超限保护，不构成第三轮授权。结果见
`.scratch/corpus-evidence-pipeline/material-semantics-redesign-report.md`。

### 5.2 R2 JSONL 两阶段开发预算（2026-09-13）

用户授权按结构重设计报告继续 R2。新预算独立冻结在
`.scratch/corpus-evidence-pipeline/r2-jsonl-development-budget-v2.json`：只使用相同 4 份
development，最多 2 轮、每轮最多 16 次、累计最多 32 次，单文档每轮最多 8 次，holdout=0。
每个 3000 字结构包依次运行 items 与 relations 两阶段，items 最多 30 条；内部响应格式固定为
`material-jsonl-v1`，输出上限 8192 token、单次 60 秒。

failed/partial 响应只允许保存在本地忽略目录，权限 0600；成功响应不留原文副本。原始响应不得打印
到控制台或写入正式文档。预算运行器继续绑定金标 SHA、模型、开发 sample ID、轮次和历史调用数。

执行结果：两个授权轮次均已消费，实际调用 7 + 13 = 20 次，holdout=0。JSONL 消除了成功包的大对象
截断，但最终开发门禁仍失败：item 14/24、critical 13/23、关系 2/5，mapped relation precision
50%。行业问答仍有 failed packet，其他样本仍有关键归属与关系误报。本预算按停止条件关闭；12 次
总量余量不是第三轮授权。结果见
`.scratch/corpus-evidence-pipeline/material-semantics-jsonl-report.md`。

### 5.3 R2 结构能力与槽位开发预算（2026-09-13）

用户授权有限模型调用后，另行冻结
`.scratch/corpus-evidence-pipeline/r2-capability-development-budget-v3.json`。只允许同一 4 份
development 样本运行 `capability-baseline` 一次，计划上限 14 次、整轮硬上限 16 次、单文档
最多 8 次；`packet_chars=3000`，holdout=0。用户新增的无标签光模块 DOCX 只作为确定性开发压力
样本，模型调用固定为 0，不能改称独立留出。

实际使用 12 次正文调用，没有重试或追加轮次。item 20/24、critical 19/23、关系 1/5；映射到
已选金标端点的关系 precision 为 100%，但另有 35 条关系无法由非穷举金标判真伪，因此不得把该
数值表述为整份材料的真实 precision。铜箔有 1 个非金标目标包在 60 秒超时，其他 3 个关键遗漏
均位于成功包，证明包级“completed”不是完整性定义。预算已关闭，详见
`.scratch/corpus-evidence-pipeline/material-semantics-capability-report.md`。

## 6. 冻结指标与阈值

开发集和留出集分别报告分子/分母、遗漏、误报、失败、调用数和耗时，不用 pytest 数量替代业务指标。
当前联合金标是目标集合而非全文穷举标注；额外 item/relation 必须计数，但在补齐负例金标前不得
纳入或宣称全文 precision。报告中的关系 precision 必须明确标为 selected-target-endpoints 范围。
另有 `data/corpus/.audit/r2_material_micro_gold_v1_20260913.json` 冻结 6 个 development 微型穷举
范围，可在这些范围内计算 item/relation precision；该结论不得外推为整页、整份材料或 holdout
precision。关系负例仅在两个端点均成功映射时计入“可判负例”，端点未召回必须单列，不得算作规避。

R2 后续改造还必须通过 `.scratch/corpus-evidence-pipeline/r2-non-regression-policy-v1.json`：全部 4 个
development 类目及 6 个微型范围逐类比较，任何指标下降、包失败增加、负例命中增加或关系误报增加
均停止；总体平均改善不能抵消单类退化。该策略中的 floor 只是当前能力下限，不能替代本节正式阈值。

| 指标 | 门槛 |
|---|---|
| 目标 item 召回率 | 每个集合 `>= 90%`；关键 item 必须 `100%` |
| 语义类型 precision / recall | 各 `>= 90%`；`value=null` 的定性预测单列 |
| 表达者、视角、问答归属准确率 | `100%` |
| 否定、条件、风险保留率 | `100%` |
| 行为状态与当时/复盘时间框架准确率 | `100%` |
| `source_explicit` 关系 precision | `100%`；recall `>= 90%` |
| locator + 短引文唯一回取率 | `100%` |
| 未知项诚实率 | `100%`；不得把 unknown 补成确定值 |
| 未支持陈述 precision | `>= 95%`，且关键归属/行为/关系误报为 0 |

阈值只衡量抽取忠实度，不用预测后来是否成真作为成功标准。电话交流纪要目前只有开发正样本，
没有独立留出；`earnings_call` 仍无样本。因此 R1 完成仅代表契约和可用小样本已冻结，不代表
PR-DATA-10 的类型泛化能力或完整材料理解链路已经验收。
