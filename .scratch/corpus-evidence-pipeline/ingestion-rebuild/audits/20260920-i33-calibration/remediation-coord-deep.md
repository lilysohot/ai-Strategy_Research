# FIX-1 阅读顺序重建：只读断言 + 交叉验证（Stage-1 part 3，改判）

- 生成：2026-09-20（只读；未改 PG/金标/评分器/reader/版本号；未写回 `evidence-diagnosis.json`）
- 脚本：`repro_coord_deep.py` → `remediation-coord-deep.json`
- 依据：guide §5 FIX-1「页内阅读顺序重建」。数据源 = 6 份真实开发 PDF。

## 1. 关键改判

此前结论"区域隔离最多 22→17、17 条不可由阅读顺序修复"**被推翻**。根因不在侧栏/页眉分区，
而在 **reader 用全局 `(y,x)` 行重排打散了 pymupdf 原生块的跨块内聚性**。

34 条 `exact_quote_not_in_kept_page_text` 在多种只读阅读序下的去空白连续命中：

| 策略 | hit | miss |
|---|---:|---:|
| before（当前：全局 `(y,x)` 行重排 + `_merge_lines` 二次重排） | 12 | 22 |
| center（guide FIX-1 x 中心聚类） | 14 | 20 |
| x0（x 左缘聚类分侧栏） | 17 | 17 |
| blockcols（块级保留，按块 `(top,x0)` 排序） | 30 | 4 |
| **blockraw（pymupdf 原生块/内容流序，原样保留）** | **34** | **0** |
| **pytext（pymupdf 内置 `get_text("text")` 阅读序）** | **34** | **0** |

`blockraw`（按 `get_text("dict")` 的块→行→span 原序拼接）与 `pytext`（`get_text("text")`
已按阅读序）两种**相互独立**机制均 34/34。前者使用 reader 同源的数据入口，证明"数据都在、
是排序次序被破坏"。

## 2. 破坏点定位（谁把 12 打成 34 的原生序弄坏）

- [pdf_reader.py L405](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/readers/pdf_reader.py#L403-L405)：
  `for line in sorted(column_lines, key=(y,x))` 对页内全部行（无分栏时 `ordered_columns=[lines]`）
  做全局重排，跨块交错被重排进正文。
- [pdf_reader.py L146](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/readers/pdf_reader.py#L144-L156)：
  `_merge_lines` 内部再次 `sorted(key=(y,x))`，二次打散。

两处都以 `(y,x)` 几何排序覆盖 pymupdf 已给的正确阅读序。修复方向唯一：**发射/段装配保留
原生块→行顺序，不再全局几何重排**。`_split_columns`（L117）分出左右栏时用过滤保留列内
相对序，可兼容；单栏页原生序≈`(y,x)` 序，预期逐字节回归风险低（待测试确认）。

## 3. 与 guide 的关系

- FIX-1（阅读序重建）：本发现即其现实落地——不是加"列聚类"sorter，而是**不再覆盖原生序**。
- FIX-3（页眉/页脚/图例/侧栏隔离）对 34 条**非必要**：blockraw（纯原生序、无任何区域隔离）已 34/34。
- FIX-4（2 条 C 类）：company-008 a-1(p1) 在原生序下已命中；无 C 类残留。

## 4. 判定与红线

- **值得落地**：保留原生阅读序是唯一同时满足"不改金标/评分器/locator、不动单元集合、不放松
  判据"的摄入侧修复，理论上把 34 条 `exact_quote_not_in_kept_page_text` 清零。
- 注：blockraw/pytext 是**整页连续流上界**；真实 reader 按段落/标题/表格切分单元后，段内/跨
  段命中仍可能有个别回落到 blockcols 档（约 30）。落地后需以重摄入的 kept 文本复测取准数。
- 全程只读：未改任何生产代码；不因本预检宣称 I3-3/M6 放行（仍须重摄入 + 冻结链重绑 + 逐条
  清单 + 单栏回归 + 651 测试）。

## 5. 实施落地（reader-pdf-3，已改代码 + 内存回归验证，未重摄入）

**代码改动**（`plugins/corpus/preparation/readers/pdf_reader.py`）：
- `READER_PDF_REV` `reader-pdf-2` → `reader-pdf-3`。
- [L405](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/readers/pdf_reader.py#L408-L413)：
  发射循环去掉全局 `sorted(column_lines, key=(y,x))`，按 pymupdf 原生块→行序流经累积器。
- [L144 `_merge_lines`](file:///home/administrator/FrontierAgent/plugins/corpus/preparation/readers/pdf_reader.py#L144-L151)：
  去掉内部二次 `sorted(key=(y,x))`，段装配保留传入原生序（单栏页原生序≈`(y,x)` 序，分组不变）。
- 对应测试 `tests/test_corpus_preparation_readers.py` rev 断言同步为 `reader-pdf-3+`。

**真实 reader 全链路验证**（6 份开发 PDF，`repro_reader_native_verify.py`、
`repro_compare_split.py` → `remediation-reader-native-verify.json`、
`remediation-compare-split.json`；只读，未写 PG）：

| 口径 | hit | miss |
|---|---:|---:|
| before（reader-pdf-2） | 12 | 22 |
| reader-pdf-3（保留原生序，含 split_columns） | **23** | **11** |
| reader-pdf-3 + 关闭 `_split_columns` 强制重排 | **28** | **6** |

`_split_columns`（强制"左→右栏"）在本批页面是负收益（-5）：pymupdf 原生序已正确，分栏探测
把侧栏当作右栏拉到末尾而打散。属独立、语义风险更大的改动（影响真实双栏文档），列为后续杠杆，
本次未并入。

**回归**：`uv run pytest tests/test_corpus_*.py -q` → **697 passed / 12 skipped / 0 failed**；
`ruff check` via；`pyright` 0 errors。

**红线**：未写 PG / 未重摄入 / 未改金标·评分器·locator / 未动单元集合；I3-3、M6 仍不放行。
剩余 ~6 条（industry-003 a-3 p10、industry-008 a-2 p10、macro-001 a-3 p3、macro-002 e4 p1、
macro-003 a-2/a-4 p1）多为表格内文本改组，属表格结构重建类，需单独跟进。