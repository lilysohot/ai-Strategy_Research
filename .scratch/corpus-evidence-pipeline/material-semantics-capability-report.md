# R2 结构能力与候选槽位开发报告

日期：2026-09-13  
结论：**未通过；单轮预算已关闭，holdout=0，R3 未启动。**

## 冻结范围

- 预算：`r2-capability-development-budget-v3.json`
- 模型：`glm-5.3-flash`
- 开发样本：既有 4 份联合金标材料
- 轮次：仅 `capability-baseline` 一次
- 调用：计划上限 14、硬上限 16、单文档上限 8、单次超时 60 秒
- 无标签光模块 DOCX：仅确定性压力测试，模型调用 0
- holdout：0

## 实现变化

1. 在不可变 `EvidenceRun` 上增加 `MaterialStructure`，正交记录对话结构、归属能力和处理模式。
2. 没有专家/说话人标签时进入 `document_voice + document_only + degraded`，不在源头拒绝。
3. 增加候选槽位和逐槽位覆盖台账；display name 允许未知，来源元数据表达者和文档声音分开。
4. 空姓名或未声明 speaker 只降级相关字段，不再丢弃整包 item。
5. item 数恰好达到上限即记容量饱和；关系阶段只检查确定性候选端点/类型组合。
6. 评分新增额外 item/relation 计数，并明确 mapped precision 只覆盖选中金标端点。

## 单轮结果

实际调用 12 次，无自动重试；prompt 39,079 tokens，completion 18,984 tokens。

| 指标 | 结果 |
|---|---:|
| item recall | 20/24（83.3%） |
| critical item recall | 19/23（82.6%） |
| semantic target accuracy | 18/24（75.0%） |
| attribution target accuracy | 8/24（33.3%） |
| source relation recall | 1/5（20.0%） |
| mapped relation precision | 1/1（100%，仅 selected-target-endpoints） |
| 未匹配额外 item | 82 |
| 无法评分的额外 source relation | 35 |

公司研报 5/5、个人交易 4/4、行业问答 3/4、铜箔纪要 8/11。铜箔一个 2,956 字包在
60 秒超时；该包不含冻结目标，因此三个铜箔关键遗漏不是超时造成，而是成功包内选择/结构覆盖失败。
遗漏为总结展望、混合听音话轮、良品率问题；行业研报漏掉一个编号问题。

## 回溯结论

- 正向效果：空 speaker 不再级联，前三份文档槽位台账完成；目标召回由 JSONL 最终轮 14/24
  恢复至 20/24；映射范围内未出现关系误报。
- 未解决：执行版本的槽位仍偏粗，成功包不能证明总结、问题和混合话轮均被覆盖；表达者注册表把
  明确来源作者过度降为 document voice；关系候选虽缩窄，仍产出大量非穷举金标无法裁决的关系。
- 评分遗漏已确认：现有金标不是全文正负例，不能从 mapped precision 推导真实 precision；value 和
  unknown_fields 也必须进入关键字段门禁。

模型轮结束后只做离线修正，未再次调用模型：`material-semantics-9` 将槽位细化为结构段内的多信号
义务，要求 question/forecast/condition/risk/negation/behavior/evidence 分别有相符 item；匿名
`display_name=null` 合法，研报/个人记录可从来源标题建立受限作者元数据。该版本只有确定性测试证据，
尚无新的模型验收，不能据此放行 R2。

静态预算检查显示，v9 的开发槽位数分别为 1、11、1、121，仍落在原 7 个候选证据包内；最长
item prompt 为 10,898 字符，24/24 冻结目标引文均被至少一个槽位覆盖。无标签光模块文档为
44 个结构段/44 个槽位，处理模式仍为 `degraded`，没有模型调用。

## 微型穷举正负例回放

按后续前置条件新增 `r2_material_micro_gold_v1_20260913.json`，仅取 6 个短开发范围，逐项穷举合法
item、17 条原文明示正关系、8 条刻意负关系及 5 个排除片段。共 35 个 item；来源 SHA、开发集身份、
locator、35 条 item 引文和 5 条排除引文均已确定性验证且在各自范围唯一回取。

未调用模型，将已消费的 `capability-baseline` 产物离线回放到该金标，结果为：

| 指标 | 结果 |
|---|---:|
| item recall | 9/35（25.7%） |
| micro-scope item precision | 9/9（100%） |
| source relation recall | 1/17（5.9%） |
| source relation precision | 1/2（50.0%） |
| 可判负关系规避率 | 2/3（66.7%） |
| 尚不可判负关系 | 5/8（端点 item 未召回） |

这组结果推翻了此前 `selected-target-endpoints` 下 100% relation precision 的乐观表述。个人交易
范围中，模型把 CEO 买入事实与作者加仓动作建立了原文未明示的 `supports`；行业问答只召回 2/14，
铜箔良品率问答只召回 2/8。公司研报、个人复盘也存在原子化合并和风险项遗漏，因此失败不是某一份
电话纪要格式异常，而是跨文档共有的选择完整性、原子化和关系约束问题。

离线评分报告为
`material-semantics-runs/micro-score-2686b3be2bccb3fa67f70edeab0f997abe6cc59a7a01c5e43876b28b6256679b.json`；
`model_calls=0`，未访问 holdout、未入库。

## 后续前置条件

小型穷举正负例前置条件已经满足。下一次模型预算前应先在离线实现中解决三件事：按槽位逐项完成而
非包级完成、强制原子命题拆分、关系必须同时通过显式触发证据与负关系护栏；再用本微型金标做零模型
回归并冻结新的有限开发预算。此前不访问 holdout，不启动 R3，也不因新光模块文档无说话人标签而
拒绝入库。

为防止修复铜箔/行业问答时破坏已表现较好的公司研报和个人复盘，当前结果已冻结为
`r2-non-regression-policy-v1.json`。后续候选必须包含全部 4 个 development 类目，逐样本的召回、
语义、归属、关键字段、关系指标及包失败数均不得低于当前值；6 个微型范围也逐范围比较 item/关系
precision、recall 和负例命中数。任一单类下降即失败，不能用总体均分上涨抵消。该基线只是防退化
下限，不替代 R2 的更高放行阈值；未来预算仍固定 `holdout_calls_allowed=0` 且先只允许一轮。

## 工程门禁

- Corpus 测试：364 passed
- R2 定向测试：22 passed
- R2 定向 Pyright：0 errors
- Ruff：passed
- 金标校验：37 items、7 relations、44 quotes，全部通过
- 微型穷举金标：6 scopes、35 items、17 正关系、8 负关系，全部引文唯一回取
- import smoke：framework 336/336，eval 385/385
- symbol closure：435 files，0 missing
