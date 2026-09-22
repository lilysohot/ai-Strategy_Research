# B5（M6 大门槛）机读盘点与逐目标归因

- 日期：2026-09-22；产物：`b5_inventory.py` → `b5-inventory.json`（write-once，语义逐字段、剔 `generated_at`，`--no-write` 支持）+ 探针 `probe-attribution.txt`
- 口径：产品路径（`svc.search_bands`，`RANK_LEXEME_PRUNE` 默认 on）+ 冻结 policy（`calibration-plan-v2.json`，`min_rate=19/20`、`top_k=5`、`require_critical_all_pass=True`、`max_false_positives=0`）；只读 PG（`i2_sandbox_corpus`，corpus schema 零写入）、0 model calls
- 对照：`audits/20260922-c3w-landing/r4v-replay.json`（21/24 复验基线，本盘点 G2 层逐值一致）

## 1. M6 可只读实测判据现状

| M6 判据（plan:260） | 现状 | 门 | 判定 |
|---|---|---|---|
| 逐类三指标（evidence_pass ≥95%/类） | company **8/8**、industry **5/8**、macro **8/8**（合计 21/24） | 每类 8 题 ⇒ 95% 即 **8/8** | ❌ 仅 industry 未达 |
| 逐类 doc_recall（候选 ≥95%） | 三类均 **1**（金标文档全部进 top-5） | ≥19/20 | ✅ |
| question_pass | 与 evidence_pass 同题集（21/24） | ≥19/20/类 | ❌ 同上 |
| 关键引用题 100% | `critical=True` 28/30；未过者恰为 industry-002/003/008（均 critical） | 100% | ❌ 与上同源 |
| 已知伪引用负例 0 | 产品侧（`CORPUS_ABSTAIN_NO_ANSWER=on`）6/6 `hits=0+abstain`（B2）；诊断口径（abstain 关、真检索）各 5 篇召回 | 0 | ✅（产品侧）/诊断口径另有 B2 关闭记录 |
| 阻断项（`score().blockers`） | `below_threshold:industry:evidence_pass=62.5%` + 3 条 `critical_failed` | — | 机读 |

**结论：21/24 的全部缺口集中在 industry 类的 3 道关键题（4 个失败目标），且全部 `also_fails_under_switch_off=true`——非 r4v 排序信号回退。**

## 2. 4 个失败目标逐个归因（同一来源 174b6462，图6 续表 page:10）

### A 类：金标合成列标签，locator 不可派生（industry-002/e2、industry-003/e2）

| 目标 | locator | quote | 观测 |
|---|---|---|---|
| industry-002/e2 | `page:10 + row:R32 + col:2026E产能（配额）` | `"28.5"` | `quote_in_band_text=true`；缺 `row:R32` 与合成列名 |
| industry-003/e2 | `page:10 + row:尿素 + col:2026E产能` | `"8068.0"` | `quote_in_band_text=true`；`row:尿素` 已有，仅缺合成列名 |

- 机读证据：page:10 表头单元（ord519/520）列结构为「产能(万吨/年)：2023/2024/2025」「表观消费量：2024/2025/2026E」；cell 证据派生标签含 `col:2026E` 但**不存在** `col:2026E产能`/`col:2026E产能（配额）`。金标列名是**人工合成**（"产能×2026E"，且"配额"语义来自注3「产能为配额」——需跨单元语义联结）。
- 判定：**管线侧不可修**（派生该 locator 需语义推理；放宽 `EvidenceTarget.matches` locator 语义 = 改 scorer/判据，纪律禁止）。
- 出路（须 U 裁决）：(a) 金标修订（plan:529 允许：须原文依据 + 人工裁决，把 locator 改到可派生口径或改绑 cell 实际标签）；(b) 登记不修 + 按 §8.3 分母分层单列（金标合成类，非管线职责）；(c) 观测侧放宽 = 违纪，不做。

### B 类：表注块未进带（industry-008/a-3、a-5）

| 事实 | 机读值 |
|---|---|
| 注1 全文所在单元 | **ord518（paragraph，kept，page:10，bbox y709.7–764.4）**，完整含 注1/注2/注3（无跨单元切句） |
| 所在块 | `chunk(unit:0517,unit:0518)`，body |
| industry-002 下 | doc 内名次 **13/166**（注3 同块 ⇒ industry-002/a-3 matched） |
| industry-008 下 | doc 内名次 **47/120**（global 110），band 预算 8 冻结 ⇒ 不进带 ⇒ `quote_in_band_text=false` |
| 机制 | 选择层：注1 文本与题面（R32/99.6%/氩气/涨幅）词法重叠低，纯词法排序带不上来 |

- 可修方向：`cross_boundary` 扩展「表格来源注聚合」（kept 来源注段 y 紧邻所选表块下方 ⇒ 聚合进带证据，同 F4/r4u 先例、内容哈希 fail-closed、免重摄入）。
- **误伤面实测（全库 8 active builds）**：kept 的「资料来源/注N」段共 **78 段 / 5 sources**；紧口径（与 kept 表行同页、y 相邻 <12pt）配对 **139**——远超 r4u 的全库单例，band 证据文本将普遍增长，须全量回放证零回退。
- 出路（须 U 裁决）：立项（新冻结修订 + 具名签认 + 全量回放）或登记不修。

## 3. M6 其余判据（本脚本范围外，现状登记）

| 项 | 现状 |
|---|---|
| I3-5 开发非回归（旧检索 golden、财务 57/57、公式 7/7、客户表 12/12、正文 3/3、宏观 0/3 另列、零模型约束门） | **未执行**（需环境/预算授权；执行时须绑定最终资产） |
| I3-6 最终冻结（不可变最终 manifest） | **未执行**（前置 I3-3/4/5） |
| I3-7 用 I3-6 版本全链重验（E2E 12 项 + gap dispositions + 受影响 M4/M5 门） | **未执行**（前置 I3-6） |
| 格式门（PDF/DOCX/MD） | r38：满足=true，13 acknowledged / 0 blocking |
| M6 放行 | 只能由**独立复核 + U 具名签认**给出（plan 纪律），不以本盘点放行 |

## 4. 呈 U 的决策点

| # | 决策 | 影响 |
|---|---|---|
| D1 | industry-002/003 e2 金标合成列标签：金标修订 vs 登记不修+分母分层单列 | 不修则 industry 类 8/8 不可达，M6 逐类门恒红 |
| D2 | industry-008 a-3/a-5：是否立项「表格来源注聚合」（误伤面 78 段/139 配对） | 立项则 +1 题（21→22），M6 仍差 e2×2 |
| D3 | I3-5 / I3-6 / I3-7 授权与排期 | M6 放行的流程前置 |
| D4 | M6 独立复核安排（全新会话 + 独立性偏差登记先例） | 放行形式要件 |

## 纪律

不 commit、不 publish、不重摄入、不写库；不改 scorer/金标/`max_chunks_per_top_document=8`；未获 U 裁决不动产品字节。

## 5. U 裁决记录（2026-09-22，AskUserQuestion 具名答复）

| # | 决策点 | U 裁决 |
|---|---|---|
| D1 | industry-002/003 e2 金标合成列标签处置 | **暂不裁决**（挂起） |
| D2 | industry-008 a-3/a-5「表格来源注聚合」 | **不立项、登记不修**（a-3/a-5 恒 fail 记录在案） |
| D3 | I3-5 现在执行 | **暂不执行** |

⇒ B5 阻塞于 D1：e2×2 未处置前 industry 8/8 恒不可达，EvidencePass 产品上限 21/24；I3-5/6/7 与 M6 复核签认随 D1/D3 解冻后推进。登记同步于 spec §14.9。
