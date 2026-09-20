# 03 chunk：连续块区间（cover）与召回/排序拆分

Status: needs-triage
Type: task
Depends: 02
Layer: chunk + search 排序
Bound-byte impact: **是**（`chunk.py`、`search_pg.py`）
Reingest: **是**（块划分/索引文本变更）

## 问题 A：块只能单块承载引文

```80:96:plugins/corpus/preparation/chunk.py
@dataclass(frozen=True)
class ChunkCandidate:
    """一个检索块候选（契约 ``Chunk`` 的前置投影，id 由引擎装配）。"""

    key: str
    kind: str
    unit_ordinals: tuple[int, ...]
    search_text: str
```

`search_text` 是给 `ts_rank` 打分的（要小、要纯），`unit_ordinals` 是给证据匹配的（要大到装下整条引文）。**两者方向相反却共用同一个输出**。i37 议题 A 的 11 条（③ 跨块 4、④ 半在池内 4、⑤ 长引文 3）是直接产物。

## 问题 B：召回与排序焊死在同一条 SQL

```41:49:plugins/corpus/preparation/search_pg.py
_SEARCH_SQL = """
SELECT p.source_id,
       c.build_id,
       c.chunk_id,
       c.kind,
       c.title_text,
       c.section_path,
       c.unit_refs,
       ts_rank(c.search_tsv, q.tsq) AS score,
```

GIN 召回 + `ts_rank` 打分 + `LIMIT` 一体，排序策略无注入口。i37 议题 B 的 10 条即此：引文在候选池内，被词法 `ts_rank` 排到 **11/12/13/18/48/62**。

## 改动面

### A. chunk 加深：`ChunkResult.cover(quote) -> tuple[int, int] | None`

```python
def cover(self, quote: str) -> tuple[int, int] | None:
    """返回承载 quote 的最小连续块区间 [i, j]（按块序拼接、去空白后包含）。

    无区间可承载时返回 None（不得返回"最接近"的近似区间）。
    """
```

- 语义：块序 = `self.chunks` 的 tuple 序；拼接按 `"\n".join`，比较用**去空白包含**（与评分器口径一致）
- 纯函数、无 IO、无金标依赖

### B. search 拆 seam

```python
def recall(dsn, query, *, domain=None, ..., limit=2000) -> tuple[SearchHit, ...]   # 只筛范围 + GIN 命中
def rank(hits, *, signals: tuple[str, ...] = ("lexical",)) -> tuple[SearchHit, ...] # 排序可插信号
```

- 默认 `signals=("lexical",)` ⇒ 行为与现状逐字节一致（`score DESC, build_id, chunk_id`）
- 结构信号（`kind == "table"` + `label_path` 命中）作为**可选**信号加入，须预先声明
- **改的是信号不是阈值**，不违反 r39 的 `No tuning after scores`

## 不变量与反例

- **I-A1（句内不切）**：块边界不得落在句子内部。近似判定：边界左端不以句末标点结束 **且** 右端不是新段落/标题起点 ⇒ 违规候选
- **I-A2（连续块可承载引文）**：对任意引文，存在连续块序列拼接后（去空白）包含它。测试用伪引文抽样（不依赖金标）
- **I-A3（超长引文）**：引文超单块上限时由相邻块并集承载，选择层须支持块区间取回
- **I-B3（不调 cap）**：显式断言 `max_chunks_per_top_document == 8`

反例样本：`company-008 a-2`（42 字被切在 36/37 块）、648 字长引文（macro-002 e4）。

## 验收

1. 常驻测试四条（i37 §5 草案）：`test_chunk_never_splits_inside_sentence`、`test_any_quote_within_page_is_coverable_by_consecutive_chunks`、`test_long_quote_requires_consecutive_chunk_union`、`test_cap_unchanged_by_this_work`
2. **目标级**：议题 A 的 11 条在同口径回测中由 `kept_page_not_selected` → **matched**
3. 系统级：DocRecall 不降；负例误报数不得增加；块大小分布附带回测
4. 语料族回归不回退

## 冻结影响

动 `chunk.py`（`CHUNK_REV` / `index_rev` 可能升级）+ `search_pg.py` ⇒ 与 **04、05 合并为一次** `i0c-r41`，一次全量重摄入 + 一次双门复跑。

## 不做

- 不改 `TARGET_MIN/TARGET_MAX/HARD_LIMIT` 的默认值
- 不调 `max_chunks_per_top_document`
- 不把证据选择退化为整篇文档取回
