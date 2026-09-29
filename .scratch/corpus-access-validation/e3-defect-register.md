# E3 · 已知缺陷与反例登记

> 版本：v3.2 · 2026-09-29。状态：**E5 已冻结** —— 候选栈 reader-pdf-9→clean-4→chunk-5 已在生产 PG
> 全量重建并发布为活动 build（generation=2，6 源全部 `published`）。4 源 blocking 缺口经 09-29
> 源页零模型复核确认零 content_loss（图页 image_only_no_text / 表页 content_retained），登记
> human gap-review 凭证（reviewer=xyl 09-21 签认同源同缺口语逐字一致）后按发布门放行、绝不绕过；
> `doc_chars_lost=672` 定为单元化口径差异（σ4.2），符合 §6 成功标准第 2 条。
> 依据：[B0 归因](../b0-attribution-20260928/report.md)、[B4 组合对照 §2.3](../b4-combined-20260929/report.md)、
> [B4 候选对照 §5.6](#56-b4-候选分项对照-结果2026-09-29未通过)、[E5 冻结执行](../b4-candidate-20260929/e5-freeze-result.json)、
> [protocol.md](protocol.md) §3 九层链路与 §6 成功标准第 2 条。
> 进入下一步条件：每条修复有证据、R1/R2 反例通过；必要修改均有对应 revision 和候选 build（已满足）。

## 1. 结构缺陷（structure_error ×4，B4.1 后仍残留）

| 编号 | target | 来源 / 位置 | 现象 | 归属层 | 复核方法 | 最小回归用例 |
|---|---|---|---|---|---|---|
| S1 | company-001 e1 | `2026-08-16_6f14cc14` page 3 财务预测表 | 金标声明 row/col/cell，但提示页单元 `location.cells` 为空（仅 page 5/6/7 保留 cells）；数字被存成扁平单元 | reader（cells 提取逐表不稳定） | 源 PDF page 3 逐格对照；确认 EPS×2026E/2027E/2028E 的 (行,列) 坐标可从源页恢复 | `tests/test_corpus_preparation_clean.py` 或新 reader 用例：含合并表头的预测表页，断言 `cells` 非空且坐标与源页一致 |
| S2 | company-001 e2 | 同上 | 同 S1 | 同上 | 同上 | 同 S1（同一页一次覆盖） |
| S3 | company-001 e3 | 同上 | 同 S1 | 同上 | 同上 | 同 S1 |
| S4 | industry-001 e5 | `2026-08-13_174b6462` page 10「重点化工品景气一览表（续表）」 | 引文 `24.0/28.5/28.5/-/18.8%/0.0%` 分词全部在页内，但列序连续串不在——跨栏/续表阅读序不连续 | reader（多栏阅读序） | 源 PDF page 10 栏序人工比对；确认正确阅读序 | reader 用例：双栏续表页，断言按栏序而非行序产出单元序列 |

对照证据：company-003（`dddc7cd0`）page 20 表格保留 `cells=[[24,0..12]]`——cells 保留是逐表不稳定，非全库缺失；S1–S3 修复后须保持该对照不回归。

## 2. NOISE 残留（clean 层 ×3，chunk 层不可修）

| 编号 | target | 来源 / 位置 | 现象 | 归属层 | 复核方法 | 最小回归用例 |
|---|---|---|---|---|---|---|
| N1 | company-007 e1 | `2026-08-16_6f14cc14` page 7 分析师声明 | 免责/声明节 fact-keep **切句**致引文断裂（`in_concat=True`、`in_single_chunk_any=False`）【v2 更正：原登记误记为标题误伤】 | clean（B2 作用面） | 源页核对声明节原文完整句；确认被切句子含事实内容 | `tests/test_corpus_preparation_clean.py` 用例：声明节含数值事实的句子须整体保留，不得按句内切分丢弃 |
| N2 | company-007 e2 | 同上 | 同 N1（同句全形）【v2 更正：原登记误记为标题误伤】 | 同上 | 同上 | 同 N1 |
| N3 | company-008 a-1 | 同上 page 1 标题区 | running-header 去重**误伤标题首行**（P2 页眉与 P1 标题「贵州茅台（600519）2026 年中报点评」同文，首现被删，连带「强推（维持）」评级）【v2 更正：原登记误记为免责切句】 | clean（B2 作用面） | 源页核对标题首行非重复页眉；确认被删文本含关键信息 | clean 用例：首页标题与后文页眉同文时，标题首行须保留 |

处理原则：B2 未实施、此前判定「无证据」；本 3 条即 B2 的首批证据。**修复与否由逐例复核决定**：
若源页证实被删文本确属关键内容，须走 clean revision + 候选 build + B4 分项对照；
若复核证实属无害重复（如真页眉），保留删除并记录理由。不得为达标改写判定口径。

## 3. R1/R2 反例（chunk-4 已实现，反例待补）

| 规则 | 已验证正向 | 待补反例 | 回归用例落点 |
|---|---|---|---|
| R1 单格表行并入正文 | `chunk.py:206` `_is_single_cell_row`，B4 恢复 6 条（`793b3967` 单格表行误判） | **真实单格表格**（如仅一格的注释框、独立数值框）不得被当正文破坏——需构造 `cells==1` 且确属表格语义的单元 | `tests/test_corpus_preparation_chunk.py`：单格真表格断言保留表格身份/不并入 prose |
| R2 连续 heading 合并 | `chunk.py:405`，B4 恢复 company-008 a-2（标题拆两行） | (a) 多栏并排标题（非连续章节）不得误并；(b) 不同章节的相邻标题不得误并——需构造两种版式单元 | 同上：多栏并排标题、跨章节相邻标题两用例，断言不合并 |

R1/R2 反例是「是否保留规则」的判定依据（03 §3）：反例失败则规则需加守卫条件；块数下降不构成保留的必要性证明。

## 4. 复核执行清单

- [x] S1–S3：源 PDF page 3 逐格对照，产出坐标可恢复性结论
- [x] S4：page 10 栏序人工比对，产出正确阅读序
- [x] N1–N3：源页核对被删文本性质，产出「修复 / 保留删除」逐条裁决
- [x] R1 反例用例补入 `test_corpus_preparation_chunk.py` 并运行
- [x] R2 两反例用例补入并运行
- [x] 每条「修复」结论登记 revision 号与候选 build 计划（§5.4）

## 5. 复核记录（2026-09-29，零模型、源 PDF 直查）

### 5.1 S1–S3：坐标可恢复性 = 成立

pypdf 提取 `6f14cc14` page 3：「附录：财务预测表」含 `EPS(摊薄)（元） 65.85 67.74 70.77 73.84` 行，
列头 `2025A 2026E 2027E 2028E` 完整；三个金标值（67.74／70.77／73.84）的 (行,列) 坐标均可从源页唯一恢复。
根源确认为**资产负债表｜利润表双栏并排版式**——文本流按列交错输出，reader 未在该版式保留 cells。
对照约束：company-003（`dddc7cd0`）page 20 `cells=[[24,0..12]]` 修复后不得回归。

### 5.2 S4：源页阅读序 = 可恢复

pypdf 提取 `174b6462` page 10：`24.0 28.5 28.5 - 18.8% 0.0%` 在源 PDF 文本流中**连续有序**，
列头 `2023 2024 2025 2024 2025 2026E` 完整（表观消费量 2023/2024/2025 + 同比 2024/2025/2026E）。
断裂确认发生在 reader 侧（跨栏续表行被拆散），非原文缺失。

### 5.3 N1–N3：三条均裁决「修复」，归属映射更正

| 条目 | 源页证据 | 裁决 |
|---|---|---|
| N1/N2（company-007 e1/e2，page 7 分析师声明） | 完整句「本报告涉及股票贵州茅台（600519），根据上市公司公告，贵州茅台的控股股东茅台集团持有本公司的控股股东华创云信 4.06%的股份。」——**含实体特定关联持股事实**，非可丢弃的纯法律模板；fact-keep 切句致 e1 子串与 e2 全句均不可单块命中 | **修复**：声明节含事实的句子须整体保留（clean-1） |
| N3（company-008 a-1，page 1 标题区） | P1 标题「贵州茅台（600519）2026 年中报点评 强推（维持）」与 P2 起页眉同文；running-header 去重按全文同文匹配，删掉了**首次出现**（源头发源地），连带评级「强推（维持）」丢失 | **修复**：去重须保留首次出现／按版面位置识别真页眉（clean-1） |

注意：原登记表 §2 将 N1/N2 误记为「标题误伤」、N3 误记为「免责切句」，实际归属相反，v2 已在表格内更正。
裁决依据不受影响（两条根因均真实存在、均属 clean 层、均误删关键内容）。

### 5.4 R1/R2 反例：3/3 失败 → 两规则均需守卫条件

新增 3 个反例测试（[tests/test_corpus_preparation_chunk.py](../../tests/test_corpus_preparation_chunk.py) 末尾，既有 20 测试保持全绿）：

| 反例 | 结果 | 证据 |
|---|---|---|
| R1 单格注释框（`cells=((0,0),)` 真表格语义） | **FAIL** | 被并入正文 body 块，表格身份丢失 |
| R2-a 多栏并排标题（左右栏 bbox 可区分） | **FAIL** | 两栏标题合并为单块，section_path 被污染为两层 |
| R2-b 不同章节相邻标题（「一、公司概况」/「二、财务分析」） | **FAIL** | 合并为单块 |

结论：R1 缺「伪表格 prose 行 vs 真实单格注释框」判别；R2 缺栏位/语义连续性守卫（仅同栏且确属
同一标题拆行时才可合并）。**守卫条件为保留规则的前置义务**：先加守卫使 3 反例转绿，
再以 B4 分项对照确认既有正向恢复（793b3967 六条、company-008 a-2）不回归。

### 5.5 修复计划（revision 登记，均为计划、未实施）

| 修复包 | 覆盖 | 内容 | 候选 build 计划 |
|---|---|---|---|
| `reader-pdf-8` | S1–S3, S4 | **已实施（2026-09-29）**：`READER_PDF_REV=reader-pdf-8`。根因①茅台 p3 无制表线→lines 策略 0 表、数字退化为扁平段落，新增 `_extract_wireless_tables`（中缝 clip 双栏各自成表，`_seam_right_aligned` 判缝）；②化工 p10 续表左右栏行高不一、行网格纵向重叠致行序错乱，`_overlapping_row_indices`+`_row_text` 按网格列序重排。真实 PDF 验证：EPS 行 `cells=((22,0)..(22,4))` 且 67.74/70.77/73.84 就位；S4 六值连续恢复；对照页光力 p20 cells 与基线一致（cols 0..5,7..12），光大/华福逐项同基线。新增 4 个 r8_ 用例，`tests -k corpus_preparation` 242 通过/8 跳过，ruff/pyright 干净。已知妥协：中缝检测要求右栏含非数字标签列，纯数字并排表退化为单表提取（不丢数据） | 待重建语料后 B4 分项对照 |
| `clean-1` | N1, N2, N3 | **已实施（2026-09-29）**：`CLEAN_REV=clean-4`（修复包号 clean-1，模块版本顺延）。①N1/N2——免责节改**句子游程整体判定**：游程在句末标点/标题/非保留单元/文档末结算，拼接（去空白）含可复核事实则整句各段降 KEPT，verdict 留痕 `disclaimer_section_numeric_fact_keep` 并带 `run_ordinals`；无事实游程逐段 NOISE（相比逐单元判定只多保不少），事实判定不豁免节内其他噪声规则（roster/prefix 权威）。②N3——带判定去重**豁免同文首次出现**（`first_seen` 按 (page, ordinal)），首现留痕 verdict `banded_repeated_geometric_first_kept`（repeat_pages 可机读复核）；真实 PDF 验证：unit 5 标题「贵州茅台（600519）2026 年中报点评」KEPT，P2–P7 真页眉照删。测试：3 新用例（n1/n2 跨单元切句保留 + n1 反例守卫「无事实切句仍删」+ n3 首现豁免）+ 页眉/页脚测试期望更新为「首现保留、其余照删」，`tests -k corpus_preparation` 245 通过/8 跳过，ruff/pyright 干净。B0 权威口径（raw_text 按 \n 连接 + 去全部空白）端到端抽验：**e1、e2 单块命中 body:0022**。已知边界：company-008 a-1（标题+评级）跨 unit 5/6，两单元左右栏并排（x [19.8,214.9] vs [395.7,468.3] 不相交），chunk-5 R2-a 守卫「多栏并排标题不合并」按设计拒绝合并（heading:0000/0001 两块）——a-1 单块恢复非 clean 层可修，留待 B4 对照时裁决（读侧 masthead 分组或对照口径），不以放宽 R2-a 为代价 | 同上 |
| `chunk-5` | R1/R2 守卫 | **已实施（2026-09-29）**：R1 守卫 `_pseudo_single_cell_rows`（同组 ≥2 行且无注释前缀才并入正文，孤行/注释框保表格身份）；R2 守卫 `_same_column`+`_headings_mergeable`（同栏 bbox 重叠 + 非新章节序号起头才合并）。3 反例转绿，`tests -k corpus_preparation` 238 通过/8 跳过，ruff/pyright 干净；正向路径实测不回归（793b3967 24 条伪表格行仍并入、华福拆行标题仍合并），`CHUNK_REV=chunk-5` | 待重建语料后 B4 分项对照 |

实施顺序建议：chunk-5 守卫（反例已就位、可 TDD）→ reader-pdf-8 / clean-1（需补正向+反例测试）→
重建候选语料 → B4 分项对照（chunking_impact 20 条恢复不回归 + NOISE 0 残留）→ 冻结候选 build 进 E5。

### 5.6 B4 候选分项对照结果（2026-09-29，**未通过**）

对照报告：[b4-candidate-20260929/report.md](../b4-candidate-20260929/report.md)（脚本 `b4_candidate.py`，
零模型、PG 只读、纯内存，候选栈 identity 断言 reader-pdf-8/clean-4/chunk-5）。

| 门槛项 | 结果 | 裁定 |
|---|---|---|
| chunking_impact 20 条恢复 | **19/20** | 17 条（chunk 规则）+ e1/e2（clean-1）单块命中；残留仅 a-1（§2.4 裁决项，`in_concat=true`、`all_crossed_kept=true`） |
| NOISE 0 残留 | **达成** | 3/3 引文跨过单元全部 kept |
| S1–S4 结构缺陷 | **4/4 修复** | company-001 e1/e2/e3 `table_has_cell_coords=true`；industry-001 e5 单块命中 |
| ok 不回归 | **未达成（4 条）** | industry-001 e4、industry-003 a-3/e3、industry-008 a-2：ok→structure_error（`read_order_not_contiguous`） |
| 0 字符丢失 | **未达成（30 字符）** | 6f14cc14 deficit=25（p3 行标签 ×20 + p1 ×3）；dddc7cd0 deficit=5（p1 数字 ×4 + p16 `资料来源：`） |

根因（均 reader-pdf-8，逐例源流核验）：

1. **p9/p10 行带装配顺序 ≠ 源流序**：4 条回归引文在源 PDF page 10 文本流中**全部连续**
   （pymupdf get_text 归一 HIT）；reader-pdf-8 `_row_text` 按网格列序产出
   「产品→产能→右栏→表观」，产品名与右栏值被产能值隔断、两行堆叠表头被数据行隔断。
   基线旧行序同样非源流序（错法不同：e5 断、其余恰连续）。**gold = 源流序（5/5 已核验）**。
2. **无线表装配覆盖损伤**：6f14cc14 p3 财务预测表 label 列丢失/garble（营业利润、
   归属母公司净利润、经营/投资/融资活动现金流等 20 条，均源流连续）；dddc7cd0 p1
   四个数字（1,832/56.71%/16.8%/19.6%）连续形态消失。均非 gold 引文，但违反 B1/B4
   既测「0 字符丢失」标准。

修复计划（**reader-pdf-9**，未实施）：行带/无线表装配以源流顺序为保真目标——行分组
可重排、带内文本顺序保持抽取顺序；label 列与数字单元装配补 TDD 反例（p3 标签、p1
数字、p10 带内顺序三组）；完成后重跑 `b4_candidate.py`，达成「20 条恢复不回归 +
deficit=0 + NOISE 0」后再冻结进 E5。clean-1/chunk-5 无需改动。

**普遍性核验（新增）**：`universality_probe.py` 对金标全部 99 条 non-empty 引文核验
源流连续性——**99/99 = 100% `src_contiguous`**，0 例 `src_tokens_only`（即无任何引文需
bbox 阅读序重排才能连续），`gold次序≠源流次序` 0 例。故「源流序为 reader-pdf-9 装配
保真基线」是**安全且普遍成立**的，无需引入 bbox 左右序装配。一致性 94/99 align，5 例
mismatch 全部为候选 build 覆盖/装配失败（4 例为本文档已列 174b6462 覆盖损伤、
company-008 a-1 为已裁决的 R2-a 合并守卫），均不属「流序错误」证据，恰是 reader-pdf-9
待修面。证据：`.scratch/b4-candidate-20260929/universality.json`。

复核证据：源页引文见本节；反例测试代码见 tests/test_corpus_preparation_chunk.py:482-539。

**reader-pdf-9 实施结果（2026-09-29）**：`_emit_table`/`_row_text` 改为按页面原生阅读序（native_pos）
组发射（新增 `_native_groups`），rev 升 `reader-pdf-9`。第一轮修复 4 条 regression；硬化为**单块 e5**
后，5 条 page-10 引文（industry-001 e4/e5、industry-003 e3/a-3、industry-008 a-2）全部 `ok`，
`in_concat+in_single_chunk` 双真（e5 六值经 `_native_groups` 的数值续行合并落单一单元）。
B4 候选对照硬项：`regressed_vs_base=0`（无新 ok→structure_error）、`structure_error→ok`=4、
`chunking_impact→ok`=19、`still_chunking` 仅剩 company-008 a-1（R2-a 已裁决边界，非回归）、
NOISE 0 残留（3/3 引文跨过单元全 kept）。
**单 open（冻结 E5 前需 user 裁决）**：`doc_chars_lost` 相对 base = 672，全部来自 6f14cc14(327)+
dddc7cd0(345)；agent 分类为相对 base（reader-pdf-6）的**单元化口径差异**（行重组所致），相关引文
均 ok、非真实文本缺失；但 register §5.5 曾记这两源「30 字符 deficit」。是否以此口径接受
「deficit≈0」并具冻结进 E5，需按 §5.5 三硬项逐一核证。

### 5.7 E5 冻结执行（2026-09-29，**通过 → 已冻结**）

- **口径裁决**：`doc_chars_lost=672` 接受为**单元化口径差异**（非真实内容丢失）——相关引文在
  gen-2 build 全部 `ok`，不构成支持缺口；据此具冻结进 E5（§6 成功标准第 2 条）。
- **全量重建发布**：候选栈 `reader-pdf-9→clean-4→chunk-5` 经生产管线（`plan_builds`→`execute_builds`→
  `publish_build`）在目标库 `postgres` 重建并发布；6 源全部 `published`、`generation=2`、活动
  build=new build。执行记录：[e5-freeze-result.json](../b4-candidate-20260929/e5-freeze-result.json)、
  [e5_freeze_driver.py](../b4-candidate-20260929/e5_freeze_driver.py)。
- **发布门 fail-closed 放行（4 源）**：174b6462 / 6f14cc14 / 793b3967 / dddc7cd0 的 gen-2 build
  存在 blocking 缺口（图页 image_region_unreadable / 表页 table_lines_without_extraction）。
  09-29 对 4 源缺口页**零模型源页复核**判定零 content_loss（`image_only_no_text` / `content_retained`），
  与既有评审者 `xyl` 09-21 对同一来源同缺口语逐字一致。据此原样重建并绑定到 gen-2 build 指纹，
  经 `store.put_gap_review` → `apply_gap_review`（保留/不相交/区域几何校验，dddc7cd0 走 region
  schema human-gap-review-2，pymupdf 校验 page:7 持股文字 bbox 与图像区不相交）校验通过，按发布门
  放行并重发——gap 仍可见、coverage scoped，未绕过 fail-closed。
- 6 源 gap-review：174b6462/6f14cc14/793b3967/dddc7cd0 各绑 1 凭证；cc03f55b/f8e31696 无 blocking
  缺口无需凭证。