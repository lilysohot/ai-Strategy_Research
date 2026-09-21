# 09 a-1 表头 NOISE 与正文评级边界（表归属 / 引文粒度）

Status: completed
Type: task
Depends: 与 F2（issues/07）同批评估（都动 table）
Layer: 清洗边界 / 表归属（跨 NOISE–kept）
Bound-byte impact: **消费侧读取路径**（新增 `cross_boundary.py` + 接线 `service.search_bands`；不改 clean 判定）
Reingest: 否（不改 clean 判定，只读 PG）

## 问题

company-008/a-1（spec §10.4 / §7.5 归因）：引文前半「贵州茅台（600519）2026 年中报点评」在 `noise/header_repeated_geometric`（+`heading_by_font_size` p1）表头（跨 p1–p7），后半「强推（维持）」在 **kept** 单元 ord=6 p1 ⇒ **引文横跨 NOISE/kept 边界**。属表归属 / 引文粒度问题，非单纯清洗误判。

## 改动面（候选，先归因后定）

1. **跨边界联合取证**：对横跨 NOISE/kept 的引文，消费侧提供"跨 NOISE/kept 边界聚合取证"路径，使引文前后两段协同承载。
2. 或把**承载真实评级的表头行**降为 KEPT（表归属重判）。
- 前置：先产出机读归因（改判定/取证前的依据落盘），据此定"判空是否本就该剔 vs 属于表归属缺失"。

## 不变量与反例

- **I-ATT-1**：对任一"声明页引文横跨 NOISE/kept"目标，须有明确归属（kept 侧承载完整）或显式跨边界取证，禁止静默丢半条。
- 反例：构造"表头 in NOISE + 评级句 in kept"的伪单元对，断言取证路径取到完整引文。

## 验收

1. company-008/a-1 给出机读归因结论 = "表归属问题" 或 "本就该剔"，据此落地对应路径。
2. 负例误报不回升；语料族回归不回退。
3. 与 F2（issues/07）同批评估；判定独立、不得先调阈值再验归因。

## 冻结影响

若动 `clean.py` 判定 ⇒ 归入 F2/F3 重摄入批次（与 07/08 合并），单条不独占修订。

## 不做

- 不按金标词/页补取证据（评测量尺不得来自金标）。
- 不把整个表头降 KEPT（需按"是否承载真实评级"甄别）。

## 完成记录（2026-09-21，`audits/20260922-f4-table-attribution/`）

- **机读归因**（`f4_attribute`/`f4_scan`，0 model calls）：a-1 = **非本就该剔，属表归属缺失**。p1 封面标题（ord5，heading）与 p2–7 页眉文字相同被 `header_repeated_geometric` 连带剔除；全库 355 个重复表头/脚注 NOISE 中 77 个 heading 型几乎全是真实页眉，"首现保留/heading 豁免"方案不成立（会误留真实页眉）。
- **落地路径＝跨边界联合取证（消费侧）**：新增 `plugins/corpus/preparation/cross_boundary.py::aggregate_band_chunks`——把与 kept 单元同页且水平行带（bbox 垂直重叠）的 `header_repeated_geometric`/`footer_repeated_geometric` NOISE 单元按 `(ordinal, unit_id)` 保序聚合进块证据（内容哈希校验 fail-closed）；接线 `service.search_bands`。不改 clean 判定、不重摄入、不按金标补取。
- **验证**（`f4_replay.py` 产品接线，与 F2 同口径）：a-1 `false→true`，EvidencePass `off/on 均 18/24` 不回退，6 负例 `retrieved_documents=0`。
- **常驻测试**：`tests/test_corpus_selection.py` +3 条 I-ATT-1（伪单元对取完整引文且序正确 / 不同页或无 y 重叠不聚合 / 不重复聚合）。selection 30 passed；corpus 家族 **751 / 12 skipped**；ruff/pyright 全绿。
- **冻结影响**：接线改 `service.py` 字节（r4n 绑定漂移）＋新增模块，待 archive-first 建新冻结修订（U 门控，不并入 F2/F3 修订）。不 publish、不 commit。