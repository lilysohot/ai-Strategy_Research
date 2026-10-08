# 10 · 评分器、开发标注范围与质量门冻结

Status: needs-info
Execution: 阈值与 E01—E12 部分关键检查点已人工签认并冻结；r2 非表格有限金标已由 xyl 签认并正式冻结，已按冻结预算完成两来源候选诊断抽取，但 material_items 原子覆盖未通过，关系依赖被 fail-closed 阻断，质量门未通过，M_main 交付评分仍未完成
Type: task
Plan: W0/W6 准备；R2-S0/S3
Blocked by: 需对有限目标的候选输出完成逐条人工/争议裁定，并补齐 query/delivery/context_use 观察；不得把本次抽取成功或未通过的原子覆盖当作质量放行
Real model calls: 48
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

独立于候选模型输出建立质量分母和评分程序，区分“接通”“抽取正确”“主线实际取得关键证据”。

## 前置与外部门

01 已冻结角色/路由/引用契约和合成范围。真实业务开发材料必须有明确准入和只读范围；人工标注缺口要列为待补资产，不能读取受保护留出或由候选输出反推金标。评分实现可与 02—09 并行，最终适配它们实际返回的已冻结协议。

## 范围与预期文件

- 新语义评分 Implementation 放在 plugins/corpus/ 现有层内的纯计算位置，不引入 benchmarks 依赖；按需复用 scoring.py 的原则但不改历史评分结论。
- tests/test_corpus_structured_scoring.py、合成金标/问题集；起始合成范围使用
  `tests/fixtures/corpus_structured_synthetic/asset-manifest.json`，并另建专项评测资产清单、评分定义、
  冻结指纹与人工裁定记录。
- 冻结有限真实开发样本与研究问题（具备授权后），不要求先完成整套建议的 12+8 份材料才能做单文档试点。
- 业务阈值采用 report 候选值作为待签认输入；预先明确报告支持率标准和不足样本时可声明的范围。

## 验收条件

- [x] Claims、items、relations 各有独立 TP/FP/FN 定义，重复输出计 FP，路由漏选计 FN，拒绝后未补齐仍计遗漏。
- [x] 原始候选与校验后结果分开，确定性表格与 LLM 正文分开；双角色同源记录不算双份独立来源。
- [x] 覆盖解析/切包、抽取、查询交付、原文到上下文的分母与失败归因；空/非法输出及缺观测不从统计删除。
- [x] 关键条件/风险必须作为完整证据单元交付；实际模型消息的遗漏不能因后台已抽出被抵扣。
- [x] 合成错年份、单位、事实/预测、归属、否定、包外条件、重复引文与分页遗漏均有评分反例。
- [ ] 真实样本/金标在看到候选模型输出前冻结；有争议的人工裁定单列，不能事后改分母提高通过率。
- [x] 阈值、报告支持率、关键错误否决项、零分母与小样本口径明确；回放通过不当作真实质量达标。
- [x] 样本或人工标注不足则保持真实试验质量门未满足；可以记录评分代码已验收，但本票不得以部分交付解除 11 的依赖。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_scoring.py tests/test_corpus_scoring.py -q
uv run ruff check plugins/corpus tests/test_corpus_structured_scoring.py
```

上述命令只用合成资产。真实标注检查必须另列显式清单与批准范围，不允许测试默认遍历仓库语料或留出目录。

## 非目标

不进行候选模型抽取，不用抽取模型作唯一裁判，不重写历史金标/分数，不将所有不可读材料归咎于模型。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
- 2026-10-03：用户明确要求开始执行 10。测试边界采用票据冻结的公开评分接口、
  合成评测资产清单与质量门报告；先按 TDD 完成零模型实现，不读取真实业务材料、
  受保护留出或候选模型结果。真实开发样本/人工标注不足将显式保留为未满足门，
  不以评分代码通过解除 11 依赖。

### 2026-10-03 · 合成评分程序交付与自验

按 TDD 交付 `plugins/corpus/structured_scoring.py`、专项测试及
`tests/fixtures/corpus_structured_scoring/`。评分器独立计算 Claims、R2 items、R2
relations 的 raw/validated TP/FP/FN 和确定性表格/LLM 正文切片；重复候选计 FP，
相同来源跨角色只计一个支持来源，严格语义身份要求一对一金标。覆盖账包含 parse、packet、
routing、extraction、query、delivery、context_use；缺观测、empty、invalid、failed 保留在
分母，并同时报告总体微平均、按来源宏平均及调用方预冻结的 family/channel/risk 分组。
报告支持率必须有 delivery 与实际 context_use，后台抽取成功不能抵扣消息遗漏。

质量门将候选百分比、风险/条件召回、报告支持率与关键错误绝对否决放在 rate gate，
把每角色最小样本、真实开发金标冻结顺序、争议裁定和阈值签认放在独立 readiness gate；
两者均过才允许 `live_trial_ready`。合成资产覆盖 8 类指定反例并用 SHA256 清单锁定；
人工裁定记录与评分定义单列。当前 development scope 明确为 `not_authorized`，没有真实
source/question，readiness 四项均未签认，holdout 未访问，因此只记录评分代码自验通过，
不宣称真实语义质量达标，也不解除 11 的依赖。

验收命令均退出 0：

```bash
uv run pytest tests/test_corpus_structured_scoring.py tests/test_corpus_scoring.py -q
# 69 passed
uv run ruff check plugins/corpus tests/test_corpus_structured_scoring.py
# All checks passed
uv run pyright plugins/corpus/structured_scoring.py
# 0 errors, 0 warnings, 0 informations
git diff --check
# clean
```

本轮 HEAD 为 `dc6572d`；真实模型调用和生产数据库访问仍均为 0。交付指纹：

| 文件 | SHA256 |
|---|---|
| `plugins/corpus/structured_scoring.py` | `4d14db7badc8f349ba5bd467702c203dddd12e8be70503bcf1b694f932683550` |
| `tests/test_corpus_structured_scoring.py` | `2d865f614e83ec8f8e8dbc76d93961e81dec43b460401c6d48e16461c4682eb6` |
| `tests/fixtures/corpus_structured_scoring/asset-manifest.json` | `bc6743d6e1fb5d1ed4f2c13c4ea1935b8ac545d08c4cbba150b7dee1d6f4715f` |
| `tests/fixtures/corpus_structured_scoring/gold-and-counterexamples.json` | `b01433674fab7bb89bece4c80809c5263b3a72bb5333e35695d0138a953c1b11` |
| `tests/fixtures/corpus_structured_scoring/scoring-definition.json` | `f0c583188976d95a990bbd026c02319544d5587a4d6270e3b0f3f494262c992b` |
| `tests/fixtures/corpus_structured_scoring/adjudications.json` | `dcdc2f4d53a9d256a28a3ed778bd82a66fb8c11fe46478b532f35ef6dae35c8b` |

### 2026-10-03 · 再次启动后的独立复验

用户再次要求开始执行 10 时，合成评分交付已位于提交 `8bfba73` 且工作树干净。本轮没有把既有
自验记录直接当作通过结论，而是重新读取冻结规格、评分实现、测试和四份资产，并原样复跑验收。
审查发现一个诊断遗漏：两个语义相同且都不命中金标的错误候选虽然总计为两个 FP，但第二条没有
进入 `duplicate_fp`。先新增失败回归（原实现得到 `duplicate_fp=0`），再改为对所有候选身份记录首次
出现；修复后仍保留两个 FP，同时把第二条分类为一个重复 FP。金标、阈值、资产清单和总分母均未
改变。

复验结果：

| 命令 / 范围 | 退出码 | 结果 |
| --- | --- | --- |
| 新增重复幻觉回归（修复前） | 1 | 预期失败：`duplicate_fp` 为 0 |
| 新增重复幻觉回归（修复后） | 0 | 1 passed |
| `uv run pytest tests/test_corpus_structured_scoring.py tests/test_corpus_scoring.py -q` | 0 | 70 passed |
| `uv run ruff check plugins/corpus tests/test_corpus_structured_scoring.py` | 0 | All checks passed |
| 两个修改文件 Ruff format check | 0 | 2 files already formatted |
| `uv run pyright plugins/corpus/structured_scoring.py` | 0 | 0 errors / 0 warnings |
| import smoke stage 1 / stage 2 | 0 / 0 | 386/386；435/435 |
| symbol closure | 0 | 0 missing / 484 files |
| `git diff --check` | 0 | 无空白错误 |

复验后指纹：`plugins/corpus/structured_scoring.py`
`172ce465492cf26cb7249599d9f53ac40d266c1883a49cea51b0b178894874f1`；
`tests/test_corpus_structured_scoring.py`
`1facf67a51fbd63ec63ed0c7a15e3cffa5af7ad1733b16a2a5f82ad8ff776794`。

本地可完成的评分实现、合成反例与门控逻辑已复验通过。真实开发门仍不能启动：当前没有获准的
`real_source_ids`、研究问题清单、候选输出前冻结的人工金标、争议裁定人或阈值签认；因此保持
`Status: needs-info`，不勾选真实样本验收项，也不解除 11 的依赖。真实模型调用 0、生产数据库访问 0、
受保护留出访问 0。

### 2026-10-08 · 状态回填

贵州茅台研报范围和研究问题随后已获确认，11 也已产生真实候选；因此“没有真实来源/问题范围”
不再是当前阻断。由于候选已经可见，不能把事后标注当前候选直接冒充“候选输出前冻结”的独立
开发金标。当前仍缺：未被现有候选污染的真实开发分母（或明确标为 seen-development 的标注方案）、
人工标注与争议裁定、阈值签认，以及据此生成的真实质量门报告。状态保持 `needs-info`，评分代码
通过不解除发布与 M_main 消费前置门。

### 2026-10-08 · 真实冻结包准备

用户要求执行人工金标与阈值冻结并运行质量评分。核查确认：2026-10-05 人工确认的 E01—E12
发生在真实候选之前，可作为预候选关键检查点，但原审阅稿明确声明不是完整三角色金标；当前候选
已经可见，不能事后改写为盲金标。已创建
[真实质量门冻结审阅](../evidence/10-quality-freeze-20261008-r1/quality-freeze-review.md) 和机读
[冻结状态](../evidence/10-quality-freeze-20261008-r1/freeze-state.json)，列出候选阈值、绝对否决项、
每角色 20 条最低样本及人工签认位置。正式冻结和评分等待该文件人工确认；在此之前不生成
`gold_frozen_before_candidates=true`，也不运行会被误解为正式质量放行的评分。

### 2026-10-08 · 人工签认、部分冻结与实际诊断评分

用户在对话中确认阈值、E01—E12 部分冻结、seen-development 诊断范围，并指定许永立同时担任
审核人与争议裁定人。已将状态写入
[冻结审阅](../evidence/10-quality-freeze-20261008-r1/quality-freeze-review.md) 与
[冻结状态](../evidence/10-quality-freeze-20261008-r1/freeze-state.json)，生成 13 条机读
[部分关键检查点金标](../evidence/10-quality-freeze-20261008-r1/critical-check-gold.json)，并使用正式
`structured_scoring.py` 对 48 items / 5 relations 候选的检查点投影执行确定性评分。E11 单列为
覆盖缺口，不伪装为语义金标；候选其余输出未获逐条人工 FP 裁定，因此 precision 明确不是完整
抽取 precision。

实际结果：Claims TP/FP/FN=6/0/4，检查点投影 precision 100%、recall 60%；items=2/0/0，
relations=1/0/0；风险/条件 recall 5/8（62.5%）；报告支持 0/1。覆盖率为 parse 13/14、
packet 10/14、routing 10/14、extraction 9/14，query/delivery/context_use 均 0/14。缺失关键项为
E01 现价/日期/归属、E08 EPS 预测归属、E09 预测表、E12 股利及利息支付复合表；E11 图像表格
解析继续失败。`rate_gate_passed=false`，`live_trial_ready=false`。

质量门阻断包括 Claims recall、风险/条件 recall、报告支持率低于阈值，关键报告失败及四条关键
Claims 缺失；准备度仍有 Claims 10/20、items 2/20、relations 1/20 三项最小样本不足。结果见
[评分摘要](../evidence/10-quality-freeze-20261008-r1/quality-score-summary.md) 与机读
[质量报告](../evidence/10-quality-freeze-20261008-r1/quality-report.json)；冻结输入、执行程序和输出
指纹见 [冻结清单](../evidence/10-quality-freeze-20261008-r1/freeze-manifest.json)。本轮无新增模型调用、
生产数据库访问或留出访问。任务仍保持 `needs-info`，不得据此发布候选或解除 M_main 质量前置门。

### 2026-10-08 · PDF 表格限制的评分口径

后续评分对未经显式 `verified_complete` 核验的 `reader-pdf-*` 表格采用 fail-closed 口径：运行结果
不得产生表格语义 TP/FP，packet 记 `partial / table_untrusted_or_incomplete`；但若冻结金标或关键
检查点要求该表内容，仍在 parse/routing/extraction 覆盖分母中计缺口，并按适用角色计 FN，不能因
当前禁止消费而删除 E09、E11、E12 或其他表格目标。完成独立完整性核验时应新建快照/候选/评分
修订，不覆盖本轮 freeze manifest、金标或质量报告。本次仅登记未来口径，历史实际得分保持不变。

### 2026-10-08 · 非表格真实开发金标待审草案

在已批准的 development scope 内，排除已经被贵州茅台候选覆盖的来源、受保护留出和全部表格单元，
从两份尚未执行本专项候选抽取的真实开发材料中建立追加式待审包：工业富联 Markdown 投委会报告和
光模块 DOCX 材料。确定性 reader 共导出 109 个非表格正文单元（14,259 字符），两份来源均无 reader
issue；标注草案包含 Claims 20 条、material_items 40 条、material_relations 20 条，其中 51 条标记为
风险或条件相关。所有记录均绑定来源 SHA256、精确 locator 和原文逐字引文，关系端点、允许关系类型、
语义身份唯一性和每角色最小数量均通过确定性校验。

该包状态仍是 `draft_pending_human_review`：80 条记录的 `review_status` 全部为 `pending`，reviewer 与
adjudicator 均未填写，`human_signoff_complete=false`、`formal_gold_frozen=false`，也未授权运行候选。
人工确认入口为
[gold-review.md](../evidence/10-quality-gold-expansion-20261008-r1/gold-review.md)，机读草案为
[gold-review-candidates.json](../evidence/10-quality-gold-expansion-20261008-r1/gold-review-candidates.json)，
校验结果见
[validation-report.json](../evidence/10-quality-gold-expansion-20261008-r1/validation-report.json)，完整输入与
脚本哈希见
[draft-manifest.json](../evidence/10-quality-gold-expansion-20261008-r1/draft-manifest.json)。这一步补齐了数量
候选，但不把 AI 辅助起草冒充人工金标，不改写既有冻结包，也不解除质量门；正式冻结必须发生在
这些来源的本专项候选执行之前。本轮模型调用、生产数据库访问和留出访问均为 0。

### 2026-10-08 · 金标审阅问题修复（r2，当前版本）

按用户要求修复 r1 审核发现的条件缺失、质疑立场丢失、动作重复、关系契约不符以及评分范围问题，
新增 [r2 审阅包](../evidence/10-quality-gold-expansion-20261008-r2/README.md)，r1 的所有输入哈希和来源
哈希复核一致，历史冻结资产未改写。当前共 Claims 20 / items 48 / relations 24（92 条 pending）：

- R02/R17 系统推断关系退出必答分母；I18 合并至 I16，两个止损条件共用同一动作端点。
- 观察仓条件恢复价格 52—58 元及负面管制公告限定、OCF/扣非 >=0.6、毛利率 >=6.99% 的可选结构；
  止损恢复相对 6.99% 下降超过 1 个百分点和公司改口的合取条件。I17 的公司改口子项内部逻辑不明，
  明示 unknown，不擅自补 AND/OR。
- C11—C13 与新增 items 明示被转述预测受到质疑；新增 challenges 保存讲者立场。补“持有＋观望”
  和税负转嫁反驳，保留 800G“超预期”的自我限定。R10/R20 改条件关系；R12 换为原文明确的理由。
- 候选输入范围限定 24 个非表格正文单元；金标为有限目标集，不宣称整篇穷尽。目标召回与完整候选
  正确率分开，额外正确输出单列 correct_extra、不能自动算 FP；未裁定候选存在时 precision 为 N/A，
  全部候选清单不能因未命中金标被筛掉。自由文本同义和关系端点采用保留原始候选的具名裁定。
- 风险/条件记录按角色计数为 0/21/12，不能称 33 个独立风险场景。关键项均附原因。

审核入口：[gold-review.md](../evidence/10-quality-gold-expansion-20261008-r2/gold-review.md)；机读编辑入口：
[gold-review-candidates.json](../evidence/10-quality-gold-expansion-20261008-r2/gold-review-candidates.json)；
范围与匹配规则：[scoring-contract.json](../evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json)。
生成器支持显示人工终态和拒绝后的数量变化，数值/期间归一化、精确引文偏移、关系端点及高风险
约束均检查；`valid_review_draft` 不代表任意语义已被自动证明，也不代表人工签认。

验证：本包 27 项回归通过（包括错年份/数值、丢条件、推断关系、重复动作、额外正确项、未裁定项及
遗漏候选清单反例）；Ruff check/format 和 Pyright 通过；import smoke 386/386、435/435，symbol
closure 0 missing/484 files。原始两份材料经确定性 reader 重读，与旧正文导出完全一致。
真实模型 preflight 未运行，本轮模型调用、数据库访问和留出访问均为 0。任务仍为 needs-info：
本次修复完成，逐条人工签认及新增冻结、真实候选评分和交付观察仍待后续，不提前解除质量门。

### 2026-10-08 · r2 金标签认、正式冻结与候选诊断执行

用户确认两份 r2 文档已签认；签认人/争议裁定人记录为 `xyl`。已通过冻结脚本生成并校验
[正式冻结金标](../evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json) 及其状态、清单；
冻结目标为 Claims/items/relations=20/48/24，共 92 条，候选执行授权为真，金标未暴露给模型。
冻结校验命令退出 0，计数为 20/48/24。

随后按有限、无自动重试、单并发预算执行两份来源。详细账本见
[候选执行摘要](../evidence/11-live-20261008-non-table-gold-r2/candidate-evaluation-summary.md)。
工业富联 Markdown 使用 21/32 次调用，光模块 DOCX 使用 27/47 次调用，合计 48/79 次；两份
`plan_consistent=true`。Claims 均为 execution succeeded / protocol valid / quality review_required，
分别产生 91 和 41 条候选事实。两份 `material_items` 均 execution succeeded 但 protocol invalid、
quality review_required：Markdown 为 53 条 item（46 extracted、9 partial、1 no_supported），DOCX 为
82 条 item（71 extracted、20 partial、1 no_supported）。失败原因是原子槽的否定/论据等必需信号未
完整覆盖及部分 item 校验失败，不是网络或预算失败。故 material_relations 均未调用，并按依赖门禁
记录 `CS_DEPENDENCY_NOT_READY`；没有自动重试、生产数据库访问或 holdout 访问。

本轮完成的是“签认 → 正式冻结 → 有界真实候选诊断”闭环，不是质量放行。有限目标的候选逐条裁定、
precision 仍为 N/A 的额外候选处理，以及 query/delivery/context_use 观察尚未完成；
`quality_gate_passed=false`，不得发布或解除 M_main 质量前置门。
