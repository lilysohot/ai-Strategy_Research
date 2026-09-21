# 02 SearchHit 加深：检索命中自带结构坐标

Status: completed（2026-09-21：`search_pg.py:94` 增 `page`/`cells`/`label_path`，`:105` `_enrich_hits` 同游标批量加深，禁 N+1）
Type: task
Depends: 01
Layer: search 接口
Bound-byte impact: **是**（`plugins/corpus/preparation/search_pg.py`）
Reingest: 否（索引未变，仅读侧投影）

## 问题

```68:84:plugins/corpus/preparation/search_pg.py
@dataclass(frozen=True)
class SearchHit:
    """读侧检索命中：定位 chunk 并回接活动来源（消费侧证据起点）。"""

    source_id: str
    build_id: str
    chunk_id: str
    kind: str
    title_text: str | None
    section_path: tuple[str, ...]
    unit_refs: tuple[str, ...]
    score: float
```

没有 `page`、没有 `cells`、没有标签路径。于是下游只能靠 `fetch_verbatim` 回捞单元再自己聚合：

```66:71:.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibrate.py
            # Pages are obtained from actual units, never copied from expected locators.
            pages = {}
            for unit in result.units:
                pages.setdefault(unit.page, []).append(unit.raw_text)
            for page, texts in pages.items():
                evidences.append(FetchedEvidence("\n".join(texts),
                    locator=(f"page:{page}",) if page is not None else (), verified=True))
```

**这就是"块选择退化成页覆盖选择"的机械原因。**

## 改动面

`SearchHit` 增加字段（均为带默认值的只读投影，不改变已有字段语义）：

```python
    page: int | None = None                                  # 命中块首个带页单元的页
    cells: tuple[tuple[int, int], ...] = ()                   # 命中块内单元格网格坐标并集
    label_path: tuple[str, ...] = ()                          # 行列标签路径（依赖 04，04 前恒空）
```

## 实现约束

- **不得在 SQL 里做 N+1**：`_SEARCH_SQL` 已返回 `c.unit_refs`；用一次额外的 `IN` 查询（同一游标）批量取 `corpus_units.location`，或改用 `jsonb` 聚合。必须在**调用方事务/快照内**完成（`search_chunks_on(cur, params)` 已具备该语义）。
- `snippet` 维持"非权威展示"语义不变（其 docstring 已声明）。
- 不得把 `page` 从 expected locator 抄来（评测量尺仍只认实际单元）。

## 不变量与反例

**I-D1（检索命中自带结构坐标）**
- 正例：对任一 hit，`hit.page` / `hit.cells` == 由 `fetch_verbatim(hit)` 的 `units` 推导出的同名字段，**逐条一致**
- 反例：构造一个 `unit_refs` 跨两页的块，断言 `page` 取首单元页且 `cells` 是并集（不取交集、不取第一单元）

## 验收

1. `tests/test_corpus_search_pg.py`（或既有检索测试文件）新增 I-D1 常驻用例，含上述反例
2. 语料族回归不回退
3. 回测基线不劣化：DocRecall 保持 1.0、负例误报不从 0 回升

## 冻结影响

动 `search_pg.py` ⇒ 必须并入新修订 `i0c-r41`（与 03/04/05 同批），跑双门。

## 不做

- 不在本票内改排序 SQL（那是 03 票）
- 不把 `label_path` 在 04 之前填任何值（保持空，避免假字段）
