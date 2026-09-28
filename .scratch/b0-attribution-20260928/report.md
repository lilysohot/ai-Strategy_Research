# B0 · 消费侧改善后的准备层归因（固定金标集，零模型）

> 生成：2026-09-28 · 脚本 [`b0_attribution.py`](b0_attribution.py) · 产物 [`b0_attribution.json`](b0_attribution.json)
> 驱动：[`docs/data_clean_dos/02-fragment-chunking.md`](../../docs/data_clean_dos/02-fragment-chunking.md) §B0、评审 [`report.md`](../a4-review-20260928/report.md) §7

## 1. 目的与边界

B0 的产出是**缺陷清单与归因证据**，不是重建语料。本档用只读语料库、零模型，对固定
金标集逐 `evidence_target` 归因，回答「A 组消费侧改善后，准备层／检索层是否仍有可复现缺陷」。

- **固定样本**：`.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl`
  （30 题：company/industry/macro 各 10；answerable 24／negative 6），共 **99 个 target**
  （75 required + 24 supplementary），覆盖 **6 个来源**。
- **零模型**：import 陷阱拒绝 `openai`／`anthropic`；只调真实注册工具 `corpus_search`
  （问题原文作**固定查询**）做 offered 判定。
- **只读**：`PGOPTIONS=default_transaction_read_only=on`，连接断言 `transaction_read_only=on`
  且 `current_database()=postgres`。
- **不是盲测**：金标用于固定样本与逐 target 归因，不进入模型决策；此档比较**准备层/检索层**，
  不含模型侧「已 offered+fetched 但未 delivered」（属消费侧，已在 A4 回放档处理）。

**归因判定口径**（`norm` = 去除全部空白后比较，抵消排版换行差异）：

| 码 | 判据 |
|---|---|
| `ok` | 证据在权威原文、落在单块、且固定查询命中的 offered 上下文覆盖该块 |
| `chunking_impact` | 引文存在于全文归一拼接，但**不落在任何单个 chunk**（跨块边界） |
| `structure_error` | (a) `table_cell_coords_absent`：金标声明 row/col/cell，但**提示页**单元 `location.cells` 为空；(b) `read_order_not_contiguous`：引文分词都在全文，但连续串不在 |
| `retrieval_not_offered` | 引文落在单块，但固定查询的命中未提供覆盖它的块 |
| `source_text_missing` | 引文在权威原文单元中逐字找不到 |

短引文（如 `67.74`、`0.36`）在多页重复，一律用金标 `page:N` 提示消解歧义。

## 2. 结果总览

| 归因码 | 数量 | required | supplementary |
|---|---|---|---|
| `ok` | **75** | 66 | 9 |
| `chunking_impact` | **20** | 13 | 7 |
| `structure_error` | **4** | 0 | 4 |
| `retrieval_not_offered` | 0 | 0 | 0 |
| `source_text_missing` | 0 | 0 | 0 |

按域：company 17 ok／15 chunking／3 structure；industry 31 ok／1 structure；macro 27 ok／5 chunking。
`structure_error` 细分：`table_cell_coords_absent` 3 + `read_order_not_contiguous` 1。

结论：**25/99 证据存在准备层可复现缺陷**（20 跨块 + 4 结构 + 1 已含于结构内），无「原文缺失」，
「检索未取」为 0。

## 3. 缺陷清单与证据

### F1 · 正文段落被拆进相邻 heading/body 块（`chunking_impact` 20 条）

引文存在于全文，但不落在任何单个 chunk——跨块单元的 chunk kind 分布（按 target 去重计）：
**heading 13／body 10／table 7**。典型：

- **company-004**（`2026-09-06_dddc7cd0`）e2/a-2/a-3：引文
  「公司发布新一期股权激励，订单承接向好，有望进入经营拐点。…营业收入触发值」
  跨 `unit:0044–0048` 五个单元，**每个单元各自是一个 `heading` 块**。这五行是同一段正文
  的硬换行（reader 逐行成 unit、未并段），却被 chunk 判为 heading——一次取证取不回连续引文。
- **macro-001/002/003**（`2026-09-06_793b3967`）：同一段引文跨 9 个单元（`body`+`table`
  边界），token 数达 42。
- **company-005/007/008**：同为跨 `heading`/`body`/`table` 边界的正文引文（2–8 单元）。

这直接指向 [B1.1](../../docs/data_clean_dos/02-fragment-chunking.md) 的 reader 分组与
B3.1 的块边界：**行级 unit 未按正向连续性证据并段，导致正文被切碎并按 heading 归类**。

### F2 · 表格单元格坐标仅部分保留（`structure_error` 3 条）

金标声明 `row/col/cell`，但**提示页**权威单元 `location.cells` 为空：

- **company-001**（`2026-08-16_6f14cc14`）e1/e2/e3：目标为 page 3 财务预测表
  的 `EPS(摊薄)（元） × 2026E/2027E/2028E`。该来源**仅 page 5/6/7 保留 cells**
  （page1 无、**page3 无**）——page 3 财务预测表被存成扁平单元（每个数字一个 unit），
  无法按 (页,行,列) 复核单元格关系。
- 对照：**company-003**（`2026-09-06_dddc7cd0`）的 page 20 表格**保留 cells**
  （unit:0744 = `每股收益` 行，`cells=[[24,0..12]]`），故该题的同类 target 判为 `ok`
  ——说明 cells 保留是**逐表不稳定**的，非全库缺失。

### F3 · 续表／跨栏阅读序不连续（`structure_error` 1 条）

- **industry-001**（`2026-08-13_174b6462`）e5：引文 `24.0 / 28.5 / 28.5 / - / 18.8% / 0.0%`
  （page 10 的「重点化工品景气一览表（续表）」列）。分词 `24.0`、`28.5`、`18.8%`、`0.0%`
  **全部存在于 page 10**，但列序连续串不在——**阅读序/栏序不连续**，而非原文缺失。

### F4 · 「检索未取」在本样本为 0——缺口在准备层而非检索层

固定查询命中的文档，其 offered 上下文（`context_locators`）覆盖了该文档**全部块**；
凡引文落在单块且该文档命中者均被 offered。因此 `retrieval_not_offered=0`。
即本样本中「取不到」不是检索召回不足，而是**跨块/结构**问题（F1–F3）。

## 4. 对 README 决策点的回答

- **B1（reader 分组）有证据**：正文行级 unit 未并段、被切碎并按 heading 归类（F1）。
- **B3（chunk 边界）有证据**：段落跨块、块类型误判（F1）。
- **B2（噪声判定）无证据**：无「关键事实被当噪声删」的样本。
- **不应整体重建语料**：缺陷是**局部、逐表/逐段**的（如 cells 仅 page3 缺、heading 误判集中
  在少数段落），符合 §B0「缺陷清单而非重建全语料」的定位；是否值得改由 B4 分项对照决定。

## 5. 限制

- 非盲测（见 §1）；offered 取整个文档上下文，故「检索未取」不能外推为「无检索缺陷」，
  只说明本固定查询下不是主因。
- `structure_error` 的 `table_cell_coords_absent` 以**提示页单元**为准；跨页续表可能改写定位。
- 零模型：本档不评价 agent 是否实际 fetch／交付（属 A4 消费侧回放档）。