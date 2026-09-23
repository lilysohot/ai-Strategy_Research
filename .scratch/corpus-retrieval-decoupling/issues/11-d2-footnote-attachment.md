# 11 D2 表格来源注聚合（industry-008 a-3/a-5）

Status: completed（2026-09-23，U 授权实施 + 入链 `i0c-r4y`；复验 24/24、逐类门全过）
Type: task
Depends: F4/r4u 跨边界取证先例（`cross_boundary.aggregate_band_chunks`）
Layer: read（取证聚合，选择层不动）
Bound-byte impact: **是**（`plugins/corpus/preparation/cross_boundary.py`；`service.py` 零改动）
Reingest: **否**（免重摄入，读取侧生效）
Resolved: 2026-09-23（冻结 `i0c-r4y`，parent `i0c-r4x`）

## 问题

industry-008 的 a-3/a-5 两个必需目标引用注1（「价格、价差分位为2016 年1 月1 日至2026 年7 月27 日」），
该文本在 `ord518`（kept，page:10）；其所在块在本题 doc 内名次 **47/120 > `pool_cap=24`**
⇒ 不在任何证据带内 ⇒ `quote_in_band_text=false` ⇒ 两条目标同时 fail ⇒
单题 3/5 = 60% < 95% ⇒ industry 7/8 = 87.5% < 95% ⇒ **M6 逐类门恒红**。

同一段在 industry-002 题下排 13/166（进带）⇒ 该题过。"同段两题两命"的机制 = 题面词元不同 ⇒ `ts_rank` 不同。

## 关键否证（防走弯路）

`a-3` 与 `a-5` 的 `quote` **一字不差**（同槽位 `p10 idx1`），差别仅 `decided_item_id`
（`I32-industry-008-02` facet=q3「批准」/ `I32-industry-008-03` **facet=null**「改选」）。
⇒ 即使判 a-5 冗余并删除，单题门要 4/4（80% < 95%），而 **a-3 仍依赖注1** ⇒ **不能解锁**。
唯一解 = 让注段进带。改锚点亦不可行：带内无原文能承载该统计窗口。

## 普遍性论证（r4u 三层扫描法）

| 层 | 谓词 | 命中 |
|---|---|---|
| L1 | kept + 段首「资料来源/注N/注：/数据来源/说明：」 | 91 段 |
| L2 | + 段内含说明性分句（`注N：/注：/备注：/口径`） | **16 段 / 5 份语料** |
| L3 | + 同页 + 上方紧邻 kept 表格行（Δ<12pt） | **4 条配对 / 2 份语料** |

L3 命中含目标 `ord518 ← 表ord582 (Δ5.45pt)`。判据纯结构、不绑金标；触发面与 r4u（全库 1 处）同量级。
**§14.9 / `b5-report.md` 的"78 段/139 配对"是 L1 裸谓词口径，高估真实影响面。**
⚠ **ordinal 序 ≠ 版面序**：ord518 的 ordinal 在表格单元之前、版面在其下方 ⇒ 上下只能按 bbox 判。

## 改动面

- `cross_boundary.py`：新增 `attach_source_note`（默认开）、`_is_source_note`、
  `_SOURCE_NOTE_LEAD` / `_SOURCE_NOTE_EXPLAIN` / `_SOURCE_NOTE_MAX_GAP_PT=12.0`；
  `_BOUNDARY_UNITS_SQL` 增第四支候选；`_merge_chunk` 增 `notes` 参数与版面谓词
  （表格行判定用 `UnitEvidence.cells` 非空；段形判据在 `_merge_chunk` 内复算 ⇒ 离线可测）。
- `service.py`：**不改**（`aggregate_band_chunks` 既有接线直接生效，仿 r4u）。

## 不变量与反例（I-NOTE-1，常驻）

- 正向：注段在块内表格行下方且 Δ<12pt ⇒ 保序聚合，引文逐字可承载、spans 自洽。
- 反向：纯「资料来源：WIND，光大证券研究所」（无口径说明）不聚合。
- 反向：版面在表格**上方** / 间距 ≥12pt / 不同页 ⇒ 均不聚合。
- 反向：块内单元非表格行（`cells` 为空）⇒ 不作锚，不聚合。

## 验收（已达成）

1. industry-008 a-3/a-5 off `False,False` → on **`True,True`**。
2. 82 目标**零回退**，新增恰为 {a-3, a-5}。
3. EvidencePass **23/24 → 24/24**（company/industry/macro 各 8/8）；负例 6×0；选择不变（带宽 33≤49）；产品路径逐字段相等。
4. 最终态盘点：24/24、`blockers` 空、`score_report_passed=true`。
5. 回归：selection **38 passed**（+4 I-NOTE-1）、语料族 **772/17**（768 基线不回退）、ruff/pyright 通过。
6. 三门 exit 0；`i0c-r4y` 入链（archive-first `before-r4y/`）。

## 冻结影响

- 新修订 **`i0c-r4y`**（parent `i0c-r4x`）；archive-first 归档改前字节并断言 == 上一绑定。
- `manifest` 未动（`frozen_in` 仍 `i0c-r4x`，r4x 语义门保持）。

## 不做

- 不改调 `pool_cap` / `band_cap` / `max_chunks_per_document=8`（I-B3 / r39 纪律）。
- 不改金标（a-5 的 facet=null 疑似登记冗余，**记录在案**，如需另行裁定另立项）。
- 不重摄入、不 publish、不写库。
- 不以本票放行 M6（放行只能由独立复核 + U 具名签认给出）。

## 证据

`audits/20260923-d2-footnote-scan/`（普遍性扫描）、`audits/20260923-d2-footnote-landing/`（A/B 复验）、
`audits/20260923-r4y-footnote-rebind/`（生成器 + `before-r4y/`）、`audits/20260923-b5-final/`（最终态盘点）、
spec §14.11。
