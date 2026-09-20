# 04 表格结构模型（下沉到 reader）

Status: needs-triage
Type: task
Depends: 03
Layer: reader
Bound-byte impact: **是**（`readers/pdf_reader.py`、`preparation/contract.py`）
Reingest: **是**（与 03 合并成一次）

## 问题

结构信息缺失是**上游唯一缺陷**，在下游三层各露一次脸（i33 §1 记 6 条 `cells=[]`/`element=null`）。当前落点：

```169:180:plugins/corpus/preparation/chunk.py
def _table_group_key(
    unit_by_ordinal: dict[int, CandidateUnit], ordinal: int, region: CleanRegion
) -> tuple[str, str]:
    """表格行分组键（页码/元素, 表序）：页界即分组边界，跨页不猜接。"""
    unit = unit_by_ordinal.get(ordinal)
    page = ""
    element = ""
    if unit is not None:
        page = str(unit.location.page) if unit.location.page is not None else ""
        element = unit.location.element or ""
    tbl = next((reason for reason in region.reasons if reason.startswith("tbl[")), "")
    return (page or element.split(":")[0], tbl)
```

- `chunk.py:416` 的 `context = pieces[0]`：**只有首行当列头**，且只有一行的粒度
- `contract.py:296-303` 的 `UnitLocation.cells` **只有 `(row, col)` 数字，没有标签文本**

⇒ i37 议题 B 的 8 条：单元格/表头/脚注与问题词元重叠极低，被 `ts_rank` 挤到 11–62。

## 关键判断：必须做在 reader 层

只有 reader 同时拥有**网格**（`_extract_tables` 的 `table.extract()`）、**原生序位次**（`_cell_native_pos`）与 **bbox**。放在 chunk/search 就是打补丁——i37 议题 B §6 已自述"本议题与表格结构重建是同一批工作"。

## 改动面

### A. reader 侧新增结构模型

```python
@dataclass(frozen=True)
class TableModel:
    page: int
    table_index: int
    header_rows: tuple[int, ...]                     # 识别出的表头行（可多级）
    def label_path(self, row: int, col: int) -> tuple[str, ...]:
        """(行标签, 列标签, 列标签父级, ...)——多级表头按层级展开。"""
    def cell_text(self, row: int, col: int) -> str: ...
```

- 表头识别规则须**确定性**（不得用模型）：行内非空单元格占比、加粗/字号可选、与数据行的位置关系
- 合并单元格（`table.extract()` 的 `None` 与跨格）须显式处理，不得静默填空字符串
- **不得重排文本**：文本顺序仍由 `_row_text` 按 `native_pos` 决定（见 04 §不变量）

### B. 单元携带标签路径

`UnitLocation` 增加 `label_path: tuple[str, ...] = ()`（**新增字段带默认值**，不改 `cells` 语义，避免牵动既有断言）。

### C. chunk 消费

`_table_group_key` 与 `context` 改为从 `TableModel` 取标签路径，索引文本变为"行标签 × 列标签"（例如 `尿素 × 开工率 × 2026E`）。

## 不变量与反例

- **I-B1（单元格可被结构信号定位）**：任一单元格的索引文本必须同时包含其**列标签路径**与**行标签**
- **I-B2（结构命中进入选择范围）**：问题含行/列标签词时，对应 cell 块必须进入该文档前 N 块
- **I-B3（不调 cap）**：`max_chunks_per_top_document` 保持 8，显式断言
- **保真反例（必须同时守）**：`_row_text` 仍只用换行连接、仍按 `native_pos` 排序。**插入 `" | "` 或按网格重排是历史 bug**（`pdf_reader.py:333-345` 注释已点名），本票不得回退

## 验收

1. 常驻测试：`test_table_cell_index_text_carries_row_and_column_labels`、`test_structural_match_enters_selection`、`test_cap_unchanged_by_this_work` + 保真反例
2. 回归样本：长江证券《化工专题：景气投资"十问十答"》p10 图 6 的 10 条引文，断言排名从 11–62 进入选择范围
3. **目标级**：议题 B 的 8 条 → **matched**
4. 系统级：DocRecall 不降；负例误报数不得增加；语料族回归不回退

## 风险

- 结构信号入排序会改变检索语义 ⇒ 须预先声明 + 跑负例回归（当前 0，不得回升）
- 表头识别若过于激进会污染索引文本 ⇒ 以 I-B2 为主判据，附带"块索引文本长度分布"回归

## 不做

- 不用模型识别表头（须确定性）
- 不在 chunk/search 层做表格结构补偿
- 不改 `cells` 的既有语义（只新增 `label_path`）
