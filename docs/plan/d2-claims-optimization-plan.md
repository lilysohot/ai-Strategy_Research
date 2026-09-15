# D2 Claims 优化改进执行计划

| 项 | 内容 |
|---|---|
| 状态 | **历史实施与验收记录**；剩余任务迁移到统一执行计划 |
| 日期 | 2026-09-12 |
| 替代文档 | [D2 Claims 质量加固执行清单](./d2-claims-quality-hardening-失效.md) · [D2 Claims v2 架构重塑设计](./d2-claims-v2-design-失效.md) |
| 上游设计 | [D2 Claims 设计](./d2-claims-design.md) |
| 关联闭环 | [Claims × 同花顺闭环](./claims-market-closed-loop-plan.md) · [投研双数据链路优化报告](./research-data-closed-loop-optimization-report.md) |
| 主要代码 | `plugins/corpus/claims.py`、`plugins/corpus/claims_v2.py`、`plugins/corpus/service.py`、`plugins/corpus/audit.py`、`tests/test_corpus_claims.py`、`tests/test_corpus_claims_v2.py`、`tests/test_corpus_metadata.py` |
| 当前验收范围 | **PG 现有 87 份全量数据**（2026-09-12 用户确认 84 份全量验收；随后新增 3 份个股研报并纳入验收） |
| 总目标 | 将 Claims 建成可靠的证据生产层：每条断言原子、可回链、语义坐标明确、确定性字段可重算、质量状态可审计，并能安全交给后续比较与判断层 |

> 2026-09-13 更新：当前唯一跨层执行清单为 [研究材料 × 同花顺数据 × 分析](claims-market-closed-loop-plan.md)。
> 本文保留原始规则、金标和失败/通过记录；下文旧待办、优先级和“下一步”不再直接驱动实施。
> 观点、论据、视角、问答与行为状态的工作归 R1—R3，数据与分析归 D/A，独立验收归 V1。

> 进度标记（2026-09-12）：`[√]` 表示已经在代码或自动化测试中落地；仍为 `[ ]`
> 的条目需要金标样本、真实语料影子运行、人工评审、发布切换或备份恢复演练确认。

> C1 标注进展（2026-09-12）：用户已完成 180 条 full 样本块级标注，文件为
> `data/corpus/.audit/c1_full87_gold_candidates_20260912_merged_smoke30.csv`；
> `label_notes` 暴露出的个人交易记录误放行、免责声明/销售通讯录噪声、债券/QE 宏观
> 分类和中英文混杂样本已进入 C2 规则与测试。金标表已新增 `label_content_genre`
> 人工标签和 `suggested_content_genre` 系统建议，用于区分 research_report、
> market_commentary、personal_trade_log、disclaimer、sales_contact 等内容类型；个人
> 交易记录有参考价值时可进入抽取，不再天然视为噪声。
> 字段级 Claim 金标仍需继续补齐；当前 `label_claims_json=claim` 可作为块级正例占位。

> C2 full180 块级复核（2026-09-12）：已更新
> `data/corpus/.audit/c2_full180_block_validation_20260912.md` 与
> `data/corpus/.audit/c2_full180_review_queue_20260912.csv`。当前结论是“C2 full180
> 块级门槛通过”：`label_candidate` 无空值，个人交易口径无冲突；triage precision
> 100.0%、recall 100.0%，doc-kind accuracy 100.0%，review queue 为空。

> C3/C4 字段级金标准备（2026-09-12）：已生成优先 50 条字段级模板
> `data/corpus/.audit/c3c4_field_gold_priority50_20260912.csv`、全量 133 条正例骨架
> `data/corpus/.audit/c3c4_field_gold_all133_skeleton_20260912.csv`、字段字典
> `data/corpus/.audit/c3c4_field_dictionary_20260912.csv` 和标注说明
> `data/corpus/.audit/c3c4_field_gold_instructions_20260912.md`。当前状态是模板就绪，
> 仍需人工补齐字段级 Claim 后，再计算原文可回链率、字段有效率、数字忠实率和期间锚定率。

## 1. 范围与完成定义

Claims 阶段只回答：

> 原文中存在什么可追溯、结构化、质量可判定的断言？

一条可进入下游的 Claim 必须同时具备：

```text
原子断言
+ 精确原文证据
+ 文档与块定位
+ 主体和指标坐标
+ 原始值与确定性派生值
+ 期间与可知时点
+ 抽取及规则版本
+ 质量状态与原因
```

### 1.1 本阶段负责

- 候选块召回、噪声过滤与原因记录；
- 公司、行业、宏观文档分类及人工覆写；
- 原子 Claim、评级观点和表格值抽取；
- 原文证据、定位信息和抽取版本留痕；
- 主体、指标、限定口径、数值、单位和时间的确定性规范化；
- 写入前 lint、复核队列、块级原子提交、重跑和死信治理；
- 金标集、基线指标、新旧差异报告和影子切换。

### 1.2 本阶段明确不负责

- 不判断两个观测是否语义可比；
- 不判断一组证据是否足以推出投资策略；
- 不生成 `allowed_conclusions`、策略强度或投资置信度；
- 不连接同花顺实际值，不计算预期差；
- 不做 D4 机构去重或“市场一致预期”；
- 不把 narratives、主题和逻辑链塞进 Claims；叙事载体另行设计；
- 不让 LLM 自由完成单位换算、算术、财务字段映射或质量裁决。

## 2. 设计纪律

1. **原文与派生分离**：`*_raw` 和精确证据永不被规范化结果覆盖。
2. **宁缺勿错**：无法确认的主体、指标、期间、单位和时间留空或进入复核，不猜测填充。
3. **评估先行**：金标和基线完成前不改变默认生产管线。
4. **影子切换**：新模型先写影子表，完成差异评审后再切换读取路径。
5. **写入前治理**：非法 Claim 不得静默进入正常聚合；拒绝和复核记录必须保留。
6. **小 Interface、深 Implementation**：外部调用方只提交块和文档上下文并接收抽取结果；分类、解析、lint 和重试复杂性留在 Claims Module 内部。
7. **兼容优先**：在新读取路径放行前，通过 Adapter 保持 D3/D4 现有调用方式稳定。

## 3. 目标 Interface

### 3.1 ClaimRecord

```text
provenance
  doc_id
  source_rev
  seq
  locator
  evidence_quote
  evidence_kind        # prose | table
  table_ref            # 可选：表名/行名/列头/单元格定位

semantics
  scope                # company | industry | macro
  subject_raw
  subject
  metric_raw
  metric
  qualifiers
  kind                 # fact | forecast | opinion

value
  value_text
  value_num
  unit_raw
  unit

time
  period_raw
  period_end
  period_grain         # annual | half | quarter | month | point
  observed_at
  known_at

governance
  quality_status       # ok | review | rejected
  reason_codes
  model
  extractor_version
  lint_version
  extracted_at
```

`qualifiers` 用于保留会计范围、同比/环比、actual/consensus/previous、表格口径等限定信息。
第一阶段先定义受控键，不把所有限定信息压进一个不可验证的 `metric` 字符串。

### 3.2 ExtractionResult

```text
ExtractionResult
  accepted[]
  review[]
  rejected[]
  diagnostics[]
  usage
  truncated
  model
  extractor_version
```

现有 `extract_from_block()` 可先通过兼容 Adapter 只返回 `accepted`；生产切换后再决定是否扩大其
Interface。内部实现和测试优先使用完整结果，避免拒绝原因静默丢失。

### 3.3 后续判断层 Seam

Claims 最终只提供只读投影：

```text
ClaimObservationProjection
  → 原文证据
  → 主体
  → 指标及限定口径
  → 原始值和规范值
  → 期间
  → known_at
  → 质量状态
```

后续另行设计：

```text
ComparabilityEvaluator   两个观测是否语义可比
EvidenceProfile          当前有哪些证据、反证和缺口
JudgmentPolicy           证据允许推出什么结论
ArgumentAudit            论证是否过度或遗漏反证
```

## 4. 交付顺序

| 任务包 | 优先级 | 依赖 | 默认行为变化 | 核心产物 |
|---|---:|---|---|---|
| C0 Interface 与迁移决策冻结 | P0 | 无 | 否 | 字段、不变量、状态和兼容方案 |
| C1 金标集与基线 | P0 | C0 | 否 | ≥180 块金标、审计报告、v1 快照 |
| C2 候选召回与文档分类 | P0 | C1 | 影子路径 | 原因码、评级召回、分类详情 |
| C3 原文忠实性与抽取安全 | P0 | C1 | 影子路径 | 精确证据、注入防护、截断诊断 |
| C4 确定性规范化 | P0/P1 | C0、C1 | 影子路径 | 坐标、数值、单位和时间派生 |
| C5 lint 与质量门禁 | P1 | C3、C4 | 影子路径 | ok/review/rejected 与原因码 |
| C6 表格与长块专项 | P1 | C3、C4 | 影子路径 | 表格定位、结构压缩、期间锚定 |
| C7 持久化、重入与运行治理 | P1 | C0、C5 | 影子路径 | claims_v2、source_rev、运行台账 |
| C8 影子运行、验收与切换 | P1 | C2–C7 | 评审后切换 | 新旧差异报告、读取 Adapter、回退方案 |

## 5. C0：Interface 与迁移决策冻结（P0）

- [√] 将 §3 字段整理成可实现的数据类型和数据库草案。
- [√] 为每个字段写明语义、可空条件、来源和派生规则。
- [√] 冻结 `fact / forecast / opinion` 三类含义；评级归入 `opinion`，不再伪装成预测数字。
- [√] 冻结 `ok / review / rejected` 状态及其进入查询和聚合的规则。
- [√] 冻结原始字段不可回写的不变量。
- [√] 冻结时间语义：`period_end`、`observed_at`、`known_at` 互不替代。
- [√] 采用 `claims_v2` 影子表；现有 `claims` 保留为对照和回退数据。
- [√] 暂时保留 `tickers[]` 读取兼容；新写入使用规范 `subject`，由 Adapter 转换。
- [√] 决定 `review/rejected` 是保存在影子表还是独立审计表；两者都必须可查询。
- [√] 确认不会在本轮顺带建设 narratives 或策略判断 Module。

**验收**：字段语义、不变量、错误模式、版本策略和兼容方式均有测试草案；不改变生产结果。

## 6. C1：金标集与基线（P0）

### 6.1 金标样本

- [√] 分层选择至少 180 个块：company、industry、macro 各至少 60 个。
- [√] 生成 C3/C4 字段级 Claim 优先模板、全量正例骨架和字段字典。
- [ ] 覆盖数字事实、预测、无数字评级、宏观实际/预期/前值。
- [ ] 覆盖普通表格、压平长表、一行多期间、多单位、表头缺失和会计括号负数。
- [ ] 覆盖公司报告中的同业比较、行业报告中的多公司代码和无代码文档。
- [ ] 覆盖目录、免责声明、评级定义、联系人页和无信号正文。
- [ ] 覆盖冲突数字、修订数字、模糊期间和缺失单位。
- [ ] 覆盖恶意指令、提示词注入和诱导模型编造的数据块。
- [ ] 标注候选判断、文档类型、原子 Claim、精确证据、主体、指标、数值、单位、期间和时间字段。
- [ ] 私有原文不进入公开 fixture；保留 `doc_id + locator + 标注结果` 或脱敏样本。
- [ ] 金标文档冻结 locator；重入协议不得静默破坏定位。

### 6.2 审计和指标

- [√] 新增只读审计入口，不调用 LLM、不修改数据库。
- [√] 输出块长度、triage 结果及原因、文档类型及原因、表格判断和已有运行状态。
- [ ] 输出候选召回率、噪声放行率、分类准确率、表格 precision/recall。
- [ ] 输出原文可回链率、数字忠实率、字段有效率、坐标合法率和期间锚定率。
- [ ] 输出空结果率、失败率、截断率、平均 token 和耗时。
- [ ] 区分候选漏失、LLM 错误、确定性解析错误和持久化错误。
- [√] 保存当前 v1 结果快照，作为 v2 差异对照。

**验收**：相同语料、配置和版本可重复生成相同报告；指标定义和标注规则进入版本控制。

## 7. C2：候选召回与文档分类（P0）

- [√] 将 triage 内部结果改为“是否候选 + 原因码”。
- [√] 至少支持 `numeric / rating / personal_trade / qualitative / noise / no_signal`。
- [√] 放行“维持买入”“上调至增持”“Buy”“Neutral”“Overweight”等无数字评级。
- [√] 继续过滤评级定义页、免责声明、联系人和分析师名单。
- [√] 为中英文评级增加正例和至少三类误放行反例。
- [√] 新增 `classify_doc_kind_detail()`，返回 `kind / reason / confidence`。
- [√] 保持 `classify_doc_kind()` 现有 Interface。
- [√] 统一分类原因码：`manual_override`、`title_ticker`、`single_body_ticker`、
  `multiple_tickers`、`industry_title`、`macro_title`、`fallback`。
- [√] 人工 `doc_kind_override` 始终优先于自动规则。
- [√] `fallback` 和低置信度文档只进入覆写候选清单，审计命令不得自动写入。
- [ ] 单列评级候选数量、有效输出数量和空输出数量，评估新增成本。

**验收**：纯评级候选召回率 ≥95%；文档分类准确率 ≥95%；数字类召回不下降；噪声金标不新增误放行。

**实测（2026-09-12 full180）**：候选 precision 100.0%、recall 100.0%；文档分类准确率 100.0%；review queue 为空。

## 8. C3：原文忠实性与抽取安全（P0）

- [√] 将 `claim_text` 与 `evidence_quote` 分离：前者是原子化断言，后者是精确原文证据。
- [√] 散文 Claim 的 `evidence_quote` 必须能在对应 block 中逐字找到。
- [√] 表格 Claim 保存表名、行名、列头、单元格原文或等价定位信息。
- [√] 无法提供精确证据的 Claim 不得进入 `ok`。
- [√] 数字必须能在精确证据或对应表格单元格中找到。
- [√] 文档内容按不可信数据处理；system prompt 明确禁止执行文档中的指令。
- [√] 添加“忽略规则”“输出虚构目标价”“调用工具”等提示词注入 fixture。
- [√] 限制 LLM 只做结构化抽取，不做算术、市场查询、比较和投资判断。
- [√] 保留 JSON fence、外围文本、对象包裹和截断数组的宽容解析。
- [√] 截断恢复必须写入 `truncated` 诊断，不得伪装成完整抽取。
- [√] 解析失败不得静默当成“原文没有 Claim”；必须区分 empty 与 failed。

**验收**：所有 `ok` Claim 均可回链原文；金标数字幻觉为 0；注入内容不能改变抽取契约。

## 9. C4：确定性规范化（P0/P1）

### 9.1 主体和指标

- [√] 将复合 `metric` 拆为 `scope / subject / metric / qualifiers`。
- [√] 永久保留 `subject_raw` 和 `metric_raw`。
- [√] 公司主体规范为证券标识；无法唯一识别时留空，不按弱号段猜测。
- [ ] 非公司 Claim 不携带公司标的，跨主体 Claim 必须拆成多条原子 Claim。
- [ ] 指标别名新增必须具备样本依据、fixture 和不误合并反例。
- [√] 不在 Claims 中映射同花顺字段或 `MetricMap` 的市场侧标识。

### 9.2 数值和单位

- [√] 继续使用 `Decimal` 派生 `value_num`。
- [√] 支持千位分隔符、会计括号负数、百分比和常见中文量级。
- [√] 永久保留 `value_text` 和 `unit_raw`。
- [√] 未知单位保持原样；不得默认为 1、0 或某个基准币种。
- [√] 单位换算规则版本化，并可由原始值重复计算。
- [ ] 同一句含多个数值时拆成原子 Claim，避免 `value_num` 指向不明。

### 9.3 期间和时间

- [√] 永久保留 `period_raw`。
- [√] 安全归一年度、半年度、季度、月度和时点型期间。
- [√] 支持 `2026H1` 与“2026 年上半年”等确定性等价关系。
- [√] 不根据附近文本猜测缺失年份。
- [√] 分离 `period_end`、`observed_at` 和 `known_at`。
- [√] 文档发布日期只可作为 `known_at` 候选，不得静默填成事实发生时间。
- [√] 有歧义的期间进入 `review`，并保留原因。

**验收**：派生字段均能由原始字段和规则版本重算；任何规范化都不覆盖原文。

## 10. C5：lint 与质量门禁（P1）

- [√] 实现 `lint_claim()`，只接受 Claim 数据并返回状态和原因码。
- [√] LLM 不参与 lint 裁决。
- [√] 校验非公司 Claim 不得错误携带公司代码。
- [ ] 校验 company、industry、macro 的限定口径是否合法。
- [ ] 校验 `actual / consensus / previous` 不得静默混用。
- [√] 校验 `opinion` 不得携带伪造的数值投影。
- [√] 校验有 `period_raw` 但无法可靠解析时不得进入 `ok`。
- [√] 校验数值能否在证据中找到，单位是否与原文一致。
- [ ] 同一坐标的单位冲突、数值冲突和修订关系进入可见诊断。
- [√] `review/rejected` 保留审计记录，但正常查询和聚合默认排除。
- [√] lint 规则建立独立版本号；历史结果能解释当时使用的规则。

建议原因码至少包括：

```text
evidence_not_found
value_not_in_evidence
subject_ambiguous
subject_scope_mismatch
metric_missing
qualifier_invalid
unit_unknown
unit_conflict
period_ambiguous
period_unanchored
time_invalid
coordinate_conflict
response_truncated
prompt_injection_detected
```

**验收**：金标非法坐标进入正常聚合的数量为 0；任何拒绝均可解释和复现。

## 11. C6：表格与长块专项（P1）

- [ ] 建立真实预测表、普通正文、目录、脚注和压平长表 fixture。
- [ ] 测量 `is_flat_table()` precision/recall，规则调整前后均输出基线变化。
- [ ] 长表采用结构优先压缩，保留表名、单位、行名、列头、期间和数值单元格。
- [√] 为每条表格 Claim 保存可以重建“行名 × 列头 → 单元格”的证据定位。
- [ ] 表头缺失、列错位或期间无法锚定时进入 `review`，不猜测、不静默丢弃。
- [ ] 一行多期间、多单位、同比/环比混排分别建立正反例。
- [ ] 记录压缩前后字符数、token 估算、截断状态和 Claim 损失数量。
- [ ] 验证压缩后仍保留至少一组完整的主体—指标—期间—数值关系。

**验收**：表格金标期间错配为 0；无法锚定的数据不会进入正常聚合；压缩过程可审计。

## 12. C7：持久化、重入与运行治理（P1）

- [√] 新建 `claims_v2` 影子表，v1 表不做破坏性迁移。
- [√] 保持“单块结果 + 块级运行台账”原子提交。
- [√] 台账记录模型、提示词版本、解析版本、lint 版本和 token 使用。
- [√] 抽出 0 条、全部 review、全部 rejected 和调用失败必须是不同状态。
- [√] 引入 `source_rev`；文档清洗重入后不得复用旧块结果。
- [√] 指纹变化时按块替换，不混用两代结果。
- [√] 已成功处理的空结果仍然跳过，避免重复消耗。
- [√] 失败块支持有限重试、熔断、死信和人工复核。
- [√] 运行统计增加 accepted/review/rejected/truncated/failed 数量。
- [√] schema 增加字段时同步备份、恢复、导出列和序列校准测试。
- [ ] 提供重跑前 dry-run：影响文档、候选块、预计 token、版本差异和死信数量。
- [ ] 提供指定 `doc_id / source_rev / extractor_version` 的小范围重抽入口。

**验收**：重跑幂等；中断后已提交块不丢失；版本升级不会静默复用旧结果；备份恢复字段完整。

## 13. C8：影子运行、验收与切换（P1）

- [ ] 在金标文档和至少 10 份真实文档上执行 v1/v2 双跑。
- [√] 差异报告拆分为新增、删除、证据变化、坐标变化、数值变化、时间变化和状态变化。
- [ ] 人工检查全部数值变化、`ok → rejected` 和 `rejected → ok` 变化。
- [√] 建立只读兼容 Adapter；D3/D4 在切换前不直接依赖 v2 表结构。
- [√] 验证 Adapter 不会把 `review/rejected` 暴露给正常聚合。
- [ ] 达到发布门槛后再切换默认读取版本。
- [ ] 保留明确的回退开关、v1 数据保留期和切换日志。
- [ ] 切换成功后才批准全量重抽。
- [ ] 全量重抽后复跑金标和抽样审计，确认结果未因规模变化退化。

## 14. 发布门槛

- [ ] 所有 `ok` Claim 原文可回链率 = 100%。
- [ ] 金标数字幻觉率 = 0%。
- [ ] 表格期间错配 = 0。
- [ ] 非法坐标进入正常聚合 = 0。
- [ ] 纯评级候选召回率 ≥95%。
- [ ] 文档类型准确率 ≥95%。
- [ ] 数字类候选召回不低于 v1 基线。
- [ ] 噪声放行率不高于 v1 基线，或回退已被明确记录并批准。
- [ ] 重跑幂等、块级原子提交、死信和版本替换测试全部通过。
- [ ] v1/v2 差异报告完成归档和人工评审。
- [ ] 备份与恢复完成一次真实演练。

验证命令：

```bash
uv run pytest tests/test_corpus_claims.py -q
uv run pytest tests/test_corpus_metadata.py -q
uv run ruff check plugins/corpus tests
uv run ruff format --check plugins/corpus tests
uv run pyright
```

## 15. 实施纪律

- 每个任务包单独提交，禁止把 schema、抽取行为和全量重抽混成一次不可审查变更。
- 所有 LLM 测试通过注入的固定返回实现，不在单元测试中调用真实模型。
- 测试通过 Claims Interface 跨 Seam 验证，不以大量私有函数白盒测试替代行为测试。
- 提示词、解析、分类、坐标、期间或 lint 语义变化都必须推进相应版本。
- 全量重抽属于发布动作，不是普通开发步骤；必须经过 dry-run、差异评审和备份确认。
- `claims.py` 暂不因文件长度机械拆分。只有出现真实变化点或第二个 Adapter 时才增加内部 Seam，
  保持调用方 Leverage 和维护 Locality。
