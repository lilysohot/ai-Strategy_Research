# 10 · 评分器、开发标注范围与质量门冻结

Status: needs-info
Execution: 合成评分程序已复验并修复重复误报分类；真实开发标注、阈值签认和真实质量门待授权
Type: task
Plan: W0/W6 准备；R2-S0/S3
Blocked by: 无本地实现依赖；真实开发样本/问题范围、人工标注与阈值签认待授权
Real model calls: 0
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
