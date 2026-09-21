# 07 band 接生产 + 补 cell 投影（**生产默认已由 `i0c-r4n` 切换为 band**；当前语料 17→18/24）

Status: completed（F2 全部落地：band 读取路径 + cell 投影 + **生产默认 perdoc → band**）
- **`i0c-r4n`（2026-09-21，frozen）已完成生产默认切换**：`service.py` `_selected_chunk_hits`
  （`select_band` 选中带 → 带内原文序块摊平）、`read_pg.search_with_coverage_bands` / `fetch_bands` 首次入链、
  `select_band` 为生产默认策略；**U 具名决策**（spec §10.5 选项 A）。
- **成绩口径更正**（2026-09-21 审核）：标题原为"17/24→19/24 生产生效"。i41 的 19/24 测于**更早 reader-pdf-5 语料**；
  当前 index-4-zhcfg-2 上 **band = 17/24、band+cell = 18/24**，自检如实标 `band_s2_evidence_pass_19: false`（不虚报）。
  19/24 封口待 **company-003 独立议题**（文档级召回，band/cell 均不能修）。

> **实施完成（2026-09-21，`audits/20260922-f2-band-prod-cell/`）——U 已签收口口径：17→18/24（当前语料）**
> - 2a（band 接生产）：产品新增 band 读取路径，只读回测复现 **17/24**（company 5/8, industry 4/8, macro 8/8）——
>   `read_pg.search_with_coverage_bands`（同一 REPEATABLE READ 快照内 命中+覆盖+`chunk_order_by_source`，
>   `_chunk_order_by_source_on` 按 build 批量装配原文序全量块清单，禁 N+1）、`read_pg.fetch_bands`（批量带内逐字块，
>   禁 N+1）、`service.search_bands`/`_apply_selection_bands`/`_assemble_band_documents`。漏斗
>   S0=77/S1=66/S2=60/S3_band_cover=59/S4_matched=50 与 i42 逐字节一致；实测最大带宽 33 ≤ 可证上界 49；
>   负例 6→0 不回升；回归 corpus 家族 **748 passed / 12 skipped**、ruff/pyright 全绿。生产默认仍 perdoc，
>   band 为并行路径（切换默认归 `i0c-r4n` + U 签认）。
> - 2b（cell 投影）：`_emit_cells` 对命中带内对齐 table 单元派生 `(page,row,col)` 并经 `fetch_cell` 权威路径
>   发射 cell 证据（只派生、不改变选择）。当前语料 **band+cell = 18/24**、row:/col: **5/13** matched；
>   industry-002 e2 / industry-003 e2（金标合成列标签）确认不可派生、保持 fail。
> - **6 个 company-003 cell 目标**（每股收益/经营活动现金流 × 2026E/2027E/2028E）所在国信 doc（`dddc7cd0`）
>   在**当前语料** rank-6 落出 top-5，非 cell 机制问题（i41 的 19/24 测于更早 reader-pdf-5 语料；当前
>   index-4-zhcfg-2 上 band/cell 无法触及该文档）——归并至既有 company-003 独立议题（§10.2 文档级召回，
>   band/cell 均不修）。F2 收口 **18/24**。
> - 自检：band 层 17/24 与 `audits/20260921-band-product/` 逐层一致（`S0_S1_S2_match_i42=true`、
>   `width_le_provable=true`、`fp_not_increased=true`、`band_evidence_pass_17=true`）；band_s2 层如实标
>   `19=false`（不虚报 19/24）。新常驻测试 I-BAND-1 / I-BAND-2 / I-CELL-1 已落 `tests/test_corpus_selection.py`。
> - **冻结影响**：`i0c-r4n` 修订（捆绑 service.py/read_pg.py/tests 字节 + 生产默认 perdoc→band 具名 U 决策）
>   待 U 逐票批准，archive-first 成文，未自行写生产。
Type: task
Depends: 需 U 开关（生产默认由 perdoc 切换）；2b 依赖 2a
Layer: 消费侧（service.py / read_pg）+ 选择层（selection.py）
Bound-byte impact: **是**（`service.py`、`read_pg.py`；`selection.py` 若需扩展接口）
Reingest: 否（不重摄入，label_path/cells 已在现状语料就位）

## 背景（spec §14.5 判定 5）

band 接线是**有意分步**（r43 notes：U 2026-09-21 决策生产默认 perdoc），非漏接。故本票是把"已验证能力推进为生产默认"，需新冻结修订 + U 签认，**不是修错**。

| 形态 | 生产默认？ | 成绩 |
|---|---|---|
| perdoc（i42，r43） | 是 | 12/24 |
| band（`selection.select_band`） | 否 | 17/24 |
| band + cell（i41 S2 投影） | 否 | 19/24 |

## 改动面

### 阶段 2a：band 接生产（17/24）

1. `plugins/corpus/service.py::_apply_selection`：perdoc `select_structural` → band `select_band`。
2. `read_pg.search_with_coverage` **同快照**内按 build 装配该 source **原文序全量块清单**（`chunk_order_by_source`），沿用 `_enrich_hits` 同游标、禁 N+1。
3. 返回类型 `SearchHit`（块）→ `SelectedBand`（区间）；`fetch_verbatim` 支持"按区间取回带内全部块"。
4. BandPolicy 沿用 `gap=1/expand=1/band_cap=8/pool_cap=24`；不改 cap 值。

### 阶段 2b：补 cell 投影（17→19/24）

1. 对命中带内 `cells` 非空的 table 单元，用 `TableModel.label_path`（`readers/pdf_reader.py`）派生 `(page,row,col)`。
2. 经 `service.py:1142 fetch_cell`（I2-6 权威）**发射 cell 证据**，带 `row:/col:` 定位符。
3. 约束：只派生不改写、不再排一次序、不改变选择。

## 不变量与反例

- **I-BAND-1**：`self_check.S0_S1_S2_match_i42 == true`（band 不碰召回与文档 top-5 选择）。
- **I-BAND-2（带宽上界）**：可证带宽上界 49（§10.5）；实测最大带宽 ≤ 49。
- **I-CELL-1**：cell 证据只对该带内、`cells` 非空的 table 单元派生，chain 上不做任何改写。
- 反例：构造"金标合成列标签、网格无法派生等义 token"的目标，断言保持 fail（不强行补取）。

## 验收

1. 复现 `audits/20260921-band-product/band-summary.json` **17/24**（2a）。
2. i41 的 13 个 `row:/col:` 目标中 **11 条转绿**（2b）；industry-002 e2 / industry-003 e2 确认不可派生、保持 fail。
3. 负例误报 6 不回升；79 目标 `S0/S1/S2` 与 i42 逐字节一致。
4. 回归 `tests/test_corpus_*.py` 731 passed / 12 skipped 不回退；ruff/pyright 全绿。

## 冻结影响

新冻结修订 `i0c-r4n`：捆绑 `service.py`/`read_pg.py`（及 `selection.py` 若改）字节 + 随行测试；archive-first（先归档上一绑定）；supersession 覆盖 r43。
生产默认由 perdoc 切换为 band 的决策须具名记入修订 notes。

## 不做

- 不重摄入；不改 schema；不删除标签注入（§10.2 S2 判定：注入在排名侧必需）。
- 不调 `max_chunks_per_top_document=8`、不调 BandPolicy 数值。
- 不触金标、不调 scorer 门槛。