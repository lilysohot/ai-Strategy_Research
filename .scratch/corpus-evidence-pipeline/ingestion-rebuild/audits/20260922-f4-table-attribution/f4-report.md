# F4：company-008/a-1 表头 NOISE 与正文评级边界（表归属 / 跨边界联合取证）

日期：2026-09-21 · 目录：`audits/20260922-f4-table-attribution/` · 0 model calls · 只读 PG `i2_sandbox_corpus`

对应：spec §14.5 F4 / §10.4 / issue 09。结论：**机读归因=非本就该剔（表归属缺失），采用跨边界联合取证落地，a-1 转绿、EvidencePass 18/24 不回退、负例=0。**

## 1. 机读归因（f4_attribute / f4_scan）

- a-1 引文前半「贵州茅台（600519）2026 年中报点评」在 NOISE `header_repeated_geometric`（+`heading_by_font_size`）p1 封面标题 ord5（heading，bbox y88–101 在页顶带 `t_min+0.12*h=107.7`），后半「强推（维持）」在 **kept** ord6 p1 ⇒ 引文横跨 NOISE/kept 边界。
- 全库扫描：355 个重复表头/脚注 NOISE 单元中 **77 个 heading 型**，几乎全是真实页眉（华福证券 / 证券研究报告 / 行业定期报告|基础化工 / 宏观经济 / 请阅读最后评级说明 / 仅供内部参考…）；p1 封面标题是**唯一**被连带剔除的"文档标题"。
- ⇒ 「首现保留 / heading 豁免」会误留真实页眉，**不可行**；a-1 的 lever 不是改 `clean.py` 判定，而是跨边界取证。

## 2. 落地：跨边界联合取证（消费侧读取路径）

- 新增 `plugins/corpus/preparation/cross_boundary.py`
  - `aggregate_band_chunks(dsn, chunk_evs, *, sandbox_db)`：把与某 kept 单元**同页且水平行带（bbox 垂直重叠）**的 `header_repeated_geometric`/`footer_repeated_geometric` NOISE 单元，按 `(ordinal, unit_id)` **保序**聚合进块证据；逐字原文 + 内容哈希校验（fail-closed）；0 model calls。
  - `_merge_chunk(ev, kept, noise)`：纯合并逻辑（可离线测试，I-ATT-1）。
- 接线：`service.search_bands` 在 `_assemble_band_documents` 前对 `fetch_bands` 结果调用 `aggregate_band_chunks`（与 f4_replay 验证路径同一接入点）。
- 纪律：不改 `clean.py` 判定、不重摄入、不把整表头降 KEPT、不按金标词/页补取证据；仅聚合同页同水平带的 NOISE 表头/脚注，不改变检索/选择。

## 3. 验证（f4_replay.py，产品接线，与 F2 同口径）

| 指标 | off（不聚合） | on（`svc.search_bands` 已接 cross_boundary） |
|---|---|---|
| EvidencePass | 18/24 | **18/24**（不回退） |
| company-008 / a-1 matched | false | **true（转绿）** |
| 6 负例 retrieved_documents | 0 | 0 |

- `off` 基准 18/24 与 F2 `band_s2=18/24` 逐字一致（methodology 对齐）。
- `on`＝真实产品读取路径 `service.search_bands`（内部含 `cross_boundary.aggregate_band_chunks`），证明接线使 a-1 转绿且无题级回归。

## 4. 常驻测试

`tests/test_corpus_selection.py` 新增 3 条 I-ATT-1 永驻测试：
1. 伪单元对「表头 in NOISE + 评级句 in kept」取到完整引文且标题序在评级前、spans 自洽可还原 text；
2. 不同页 / 无 y 重叠的 NOISE 不聚合（返回原 chunks）；
3. 块内已有单元不重复聚合（保幂等）。

## 5. 回归与质量门

- `tests/test_corpus_selection.py`：**30 passed**（27 基线 + 3 新增）
- corpus 家族 `tests/test_corpus_*.py`：**751 passed / 12 skipped**（748 基线 + 3，无回退；12 skip 为 I2 沙箱旧库监守）
- ruff check / ruff format / pyright：**全绿**

## 6. 冻结影响（待 U 门控）

- 接线改 `service.py` 字节（r4n 绑定 `service.py=54ef53b8` 现**漂移**）＋新增 `cross_boundary.py`。
- 待 archive-first 建**新冻结修订**（U 门控，不并入 F2/F3 修订）；不重摄入、不 publish、不 commit。