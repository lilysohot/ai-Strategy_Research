# B4 候选分项对照（reader-pdf-8 → clean-4 → chunk-5）报告

- 日期：2026-09-29
- 依据：[e3-defect-register.md §5.5 实施顺序](../../.scratch/corpus-access-validation/e3-defect-register.md)「重建候选语料 → B4 分项对照」
- 脚本：`b4_candidate.py`（对照）、`b4_candidate_analysis.py`（诊断）；产物：`b4-candidate-comparison.json`、`analysis.json`
- 隔离保证：零模型（B0 import 陷阱，`MODELS_ABSENT=True`）、PG 只读（`transaction_read_only=on` 已断言）、候选 artifacts 纯内存、不写库不建索引不发布。
- 候选栈 identity 断言：`reader-pdf-8`（extractor_rev）/ `clean-4`（CLEAN_REV）/ `chunk-5`（CHUNK_REV）。

## 1. 变体与口径

| 变体 | 含义 |
|---|---|
| `base` | B0 活动 build（reader-pdf-6 时代，chunk-3） |
| `b1b3` | B4 组合档：reader-pdf-7 → clean-3 → chunk-4 |
| `candidate` | 候选栈：reader-pdf-8 → clean-4 → chunk-5（归档副本重读，纯内存） |

99 target / 30 题 / 6 来源。offered 判定沿用 B0 保存命中（受控假设，同 B1/B4）。
新增 **NOISE 残留核对**：gold 引文跨过的单元在候选 clean 台账中必须全部 kept。

## 2. 结果

### 2.1 达成项（相对 base）

| 项 | 结果 | 证据 |
|---|---|---|
| chunking_impact 恢复 | **19/20** | 17 条（chunk 规则，b1b3 同批）+ company-007 e1/e2（clean-1 句子游程，`in_single_chunk_any=True`）；残留仅 company-008 a-1（见 §2.4） |
| structure_error 修复 | **4/4** | company-001 e1/e2/e3（`table_has_cell_coords=True`，S1–S3）+ industry-001 e5（S4，六值连续且单块命中） |
| NOISE 残留 | **0** | 3/3 `all_crossed_kept=true`、`noise_crossed=[]`——e1/e2/a-1 引文不再位于任何 NOISE 单元 |
| ok 保持（vs b1b3） | 88 条 ok→ok | 17 条既有恢复无回归 |

### 2.2 未达成项一：4 条 ok → structure_error（174b6462 page 9/10 续表）

industry-001 e4、industry-003 a-3/e3、industry-008 a-2（全部 `page_hint=10`，
`read_order_not_contiguous`、`in_concat=false`）。**字符零丢失、纯次序问题。**

根因（逐条源流核验）：**4 条引文在源 PDF page 10 文本流中全部连续**（pymupdf
`get_text` 归一后 HIT；E3 复核 §5.2 曾对 e5 单独验证，本次扩至全部 4 条）。
reader-pdf-8 的行带装配（`_overlapping_row_indices`+`_row_text` 按网格列序重排）
产出的带内顺序为「产品→产能→右栏→表观」，与源流顺序不一致：

- e4 `纯碱\n0.0%\n0.0%\n82.9%`：候选中「纯碱」与三个右栏值之间插入了产能值
  （unit:0583 `纯碱\n2901.6 3596.3 3507.2\n0.0%\n0.0%\n82.9%…`）；
- e3 `尿素\n32.1%\n10.9%\n89.9%`：同型（unit:0567）；
- 表头 `产能（万吨/年）以及同比增长\n产品\n…`：两行堆叠标签被年份数据行从中间
  隔断（`…以及同比` + `增长20232024…`）；
- e5 恰因「表观值居单元尾、同比值居下单元首」跨单元拼接命中——命中是装配次序的
  副作用，非顺序正确性的证明。

基线（reader-pdf-6/7）的旧行序同样非源流序（e5 断、其余四条恰连续），即**新旧两版
装配都不等于源流序，只是错法不同**。gold = 源流序（5/5 连续已直接核验）。

### 2.3 未达成项二：raw 覆盖损伤 30 字符（B1/B4 时代为 0）

| 来源 | deficit | 位置 | 性质（逐单元源流核验：23+5 个旧单元全部源流连续） |
|---|---|---|---|
| 6f14cc14 | **25** | p1 ×3、p3 ×20 | p3 财务预测表**行标签**丢失/garble（营业利润、利润总额、归属母公司净利润、一年内到期的非流动负债、所有者权益合计、负债和股东权益、偿债/营运/获利/成长能力、现金流量表、经营/投资/融资活动现金流、每股指标(元)、估值比率、主要财务指标/比率、单位：百万元×3）——无线表中缝双栏装配对 label 列的处理缺陷；p1 另有 2 条历史报告引用行被拆断 |
| dddc7cd0 | **5** | p1 ×4、p16 ×1 | p1 四个数字（`1,832`/`56.71%`/`16.8%`/`19.6%`）连续形态消失（字符散落）；p16 `资料来源：Wind，国信证券经济研究所分析` 整行源流连续但新文档 `资料来源：` 前缀少一处 |

均非 gold 引文（故 target 级无体现），但违反「相对基线 0 字符丢失」的 B1/B4 既测标准。
174b6462 deficit=0；p5 销售名单 1 单元重排为良性（无 deficit）。

### 2.4 a-1 裁决证据（R2-a 张力，维持原判）

company-008 a-1：`in_concat=true`、`all_crossed_kept=true`（unit 5 标题 + unit 6
评级均 KEPT，clean-1 首现豁免生效）、`in_single_chunk_any=false`——两单元左右栏
并排（x [19.8,214.9] vs [395.7,468.3]），chunk-5 R2-a 守卫按设计拒绝合并。
文本已完整入库，单块命中需读侧 masthead 分组或放宽 R2-a（后者已被否决）。

### 2.5 成本

chunks 807→361（−446）；`old_chunk_not_contiguous_in_new` 合计 105（b1b3 为 98，
+7 来自 reader-pdf-8 重排），结合 deficit 定位均为行带重组/上述损伤，无其他阅读序损伤。

## 3. 结论

1. **clean-1 达标**：N1/N2/N3 三条全部修复且 0 NOISE 残留；e1/e2 单块命中。
2. **chunk-5 维持**：17 条恢复无回归，a-1 为唯一残留（§2.4，裁决项非缺陷项）。
3. **reader-pdf-8 引入回归，B4 门槛未通过**：①p9/p10 行带装配顺序 ≠ 源流序
   （4 条 ok→structure_error）；②p3 label 列丢失等 30 字符覆盖损伤。
   修复方向（reader-pdf-9）：行带/无线表装配以**源流顺序**为保真目标——行分组可重排、
   带内文本顺序须保持抽取顺序；label 列与数字单元装配补 TDD 反例。
4. 修复后须重跑本对照（同脚本），达成「20 条恢复不回归 + deficit=0 + NOISE 0」后再冻结进 E5。

## 4. 限制

- offered 判定为受控等价重现，非对新 build 索引重新检索。
- 候选为纯内存重建，未建 PG 候选 build；冻结（E5）另行执行。
- 字符核验为归一 multiset 差 + 单元连续性，不覆盖同字符异序外的语义重排。
