# 落地方案：prune_fn_punct（排序信号剔除虚词 + 标点）

**状态：待 U 具名裁决；截至本稿未改任何产品字节。**
依据：`c3w-eval.json` / `c3w-report.md`（本目录）与 `audits/20260922-c3-lexical-signal/`（姊妹篇）。

## 1. 目标与预期收益（已离线实测）

| 指标 | base | prune_fn_punct |
|---|---|---|
| EvidencePass | 19/24 | **21/24** |
| 82 目标 matched | 67 | **75（+8）** |
| 回退 | — | **0** |
| company-003 | 0/6 | **6/6** |
| 负例（主口径 / 真检索） | 0 / 5 | 0 / 5（不回升） |
| 带宽 max | 33 | 33（≤ 49） |

新增恰为：company-003 ×6、company-008/a-2、industry-008/a-2。

## 2. 原理与不变式

打分式（`w_f = 0`）：

```
score = ts_rank(c.search_tsv, tsq_content)          # 排序信号只算实词
WHERE c.search_tsv @@ tsq_all                        # 候选池仍用全词元
```

**两条不变式（这是方案成败的关键，必须在测试里钉死）**：

- **I-1 候选池不收缩**：`WHERE` 与命中集合必须与改动前逐块一致（姊妹篇已证明：一收缩候选，
  同词元划分就从 +8 变成回退 3 条）。
- **I-2 只有 score 变**：`ORDER BY` 的 tie-break（`score DESC, build_id, chunk_id`）、
  `chunk_order`（来源全量原文序，与命中顺序无关）、`ts_headline` snippet 全部保持原样。

## 3. 改动点（4 处，全部在 `plugins/corpus/preparation/`）

### 3.1 `negative_query.py`：新增词元划分函数（判据沿用既有非金标词表）

```python
def is_punct_lexeme(token: str) -> bool:
    """标点词元的结构判定（非金标）：词元内不含任何字母/数字/汉字。"""
    return not any(ch.isalnum() for ch in token)


def rank_lexemes(lexemes: Sequence[str]) -> tuple[str, ...]:
    """排序信号词元：剔除 `_FUNCTION_WORDS` 与标点；**全部被剔除时回退原词元**（fail-closed）。"""
    kept = tuple(t for t in lexemes if t not in _FUNCTION_WORDS and not is_punct_lexeme(t))
    return kept or tuple(lexemes)
```

- 复用现成 `_FUNCTION_WORDS`（F1/B2 已在用的非金标表），新增的只有"标点"这一**结构判定**；
- 兜底：若某查询词元全是功能词/标点 ⇒ 回退全词元，避免 score 全 0 导致排序退化为 build/chunk 字典序。

### 3.2 `search_pg.py`：生成 `rank_query`（与检索同一游标/同快照）

```python
def _rank_query_on(cur, query: str) -> str:
    cur.execute("SELECT tsvector_to_array(to_tsvector('zhcfg', %s))",
                (normalize_search_text(query),))
    row = cur.fetchone()
    lexemes = tuple(str(t) for t in (row[0] if row and row[0] else ()))
    kept = rank_lexemes(lexemes)
    return " OR ".join('"' + t.replace('"', " ") + '"' for t in kept)
```

`search_chunks` / `search_chunks_on` 在**同一游标**内取词元后把 `rank_query` 注入 params
（`build_search_params` 增加可选键，保持它是唯一归一化入口）。

### 3.3 `search_pg.py::_SEARCH_SQL`：score 换 tsquery（最小 diff）

```sql
FROM (SELECT websearch_to_tsquery('zhcfg', %(query)s)      AS tsq,
             websearch_to_tsquery('zhcfg', %(rank_query)s) AS tsq_rank) AS q
...
  ts_rank(c.search_tsv, q.tsq_rank) AS score,               -- ← 只改这一列
  ts_headline('zhcfg', c.search_text, q.tsq, ...) AS snippet,   -- 保持全词元
...
WHERE c.search_tsv @@ q.tsq                                  -- 候选池不变（I-1）
ORDER BY score DESC, c.build_id, c.chunk_id                   -- tie-break 不变（I-2）
```

### 3.4 开关（可回滚 / 可 A/B）

模块级常量 `RANK_LEXEME_PRUNE = True`（冻结绑定该默认值）。
关闭 ⇒ `rank_query` 直接等于 `query`，行为逐字节回到 base。

## 4. 不在本次范围内（显式声明）

- 不改写侧（不 `setweight`、不重建索引、不重摄入）；
- 不动选择（`select_structural` / `select_band`）、不动 band 聚合（`stitch_continuation` 保持默认开）；
- 不动负例判定（F1 `tighten_no_answer_query`、B2 abstain 的 AND 语义路径）与 `scoring.py`；
- 不改 `EvidenceTarget.matches`、不降 `max_false_positives=0`、`max_chunks_per_document=8` 保持。

## 5. 常驻测试（新增 I-RANK-1，落 `tests/test_corpus_search_pg.py` 或既有检索测试）

1. **候选池不变**：同一 query，命中 `chunk_id` 集合与改动前一致（I-1）；
2. **score 只由实词决定**：构造 toy 块 A（只命中虚词/标点）与块 B（只命中实词），
   断言 `score(A) == 0 < score(B)`，且 A 仍在候选集中；
3. **标点剔除**：仅标点命中的块 score 为 0；
4. **空兜底**：query 全为功能词/标点 ⇒ `rank_query == query`（不出现空 tsquery）；
5. **tie-break 不变**：score 相同时按 `(build_id, chunk_id)`；
6. **开关可回滚**：`RANK_LEXEME_PRUNE=False` 时输出与改动前逐字段相等。

## 6. 门禁与里程碑

| 阶段 | 内容 | 放行条件 |
|---|---|---|
| M1 | 只读离线评估 | 已完成（本目录 + 姊妹篇） |
| M2 | 代码落地 + I-RANK-1 测试 | `pytest tests/test_corpus_*.py -q` 不回退（现 762 passed / 12 skipped） |
| M3 | 冻结修订 `i0c-r4v`（archive-first）+ 三门 | `validate_i0c/i1/i3_2` 均 exit 0 |
| M4 | 端到端复验（新目录，不可原地复跑） | 与离线评估一致：21/24、+8、**零回退**、负例 6/6=0、带宽 ≤ 49 |
| M5 | 独立复核 + **U 具名签认**（排序/粒度类变更） | 签认后生效 |

## 7. 风险与影响面

- **影响面**：24/24 题的 SelectedBand 集合发生变化（端到端零回退已实证，仍须全量回归确认）；
- **语义复用**：`_FUNCTION_WORDS` 原本只服务负例拒检，本次复用到正例排序降噪 ⇒ 属口径/粒度变更，
  须在冻结 notes 中写明并**具名签认**；
- **残留**：company-007 的断句根治（路径 A）仍为独立待裁项；company-003 在 P1 解除后已 6/6，
  不再需要 P2 表格模型改造。

## 8. 回滚

- 一级：`RANK_LEXEME_PRUNE = False`（不改字节结构，行为回 base）；
- 二级：revert `i0c-r4v` 绑定的字节（按修订哈希 / `git show HEAD:<path>` 还原并核对 sha）。
