# 01 证据选择策略落入产品代码

Status: needs-triage
Type: task
Depends: 00
Layer: 证据选择
Bound-byte impact: **无**（纯新增文件，不改已有绑定）
Reingest: 否

## 问题

`group_hits` / `max_chunks_per_top_document=8` / `observations_for`（按页聚合成 `FetchedEvidence`）**只存在于评测脚本**：

- `audits/20260920-i33-calibration/calibrate.py:37-74`
- `audits/20260920-i37-fullchain-backtest/*.py`
- `audits/20260920-i38-reshape/reshape.py`

`plugins/corpus/` 全仓搜不到 `group_hits` / `max_chunks_per_top_document`。产品 `service.py` 只有 `search_with_coverage` + `fetch_verbatim` 原语，无选择策略。
⇒ 每轮"修证据选择层"改的是一次性脚本副本，产品行为零变化。

## 改动面

新增 `plugins/corpus/preparation/selection.py`（唯一新增，无删除）。

## 接口（目标形态）

```python
@dataclass(frozen=True)
class SelectionPolicy:
    top_k: int = 5
    max_chunks_per_document: int = 8
    expand: str = "page"          # "chunk" | "page"
    per_source_unique_build: bool = True

@dataclass(frozen=True)
class SelectedDocument:
    source_id: str
    build_id: str
    evidences: tuple[FetchedEvidence, ...]

def select(hits: tuple[SearchHit, ...], policy: SelectionPolicy) -> tuple[SelectedDocument, ...]:
    """按 policy 从检索命中选出证据；不做 IO，只做选择。"""
```

要点：
- **默认 policy 行为必须与 `calibrate.py` 现状逐字节等价**（`top_k=5`、`per_document=8`、页展开）
- `expand="chunk"` 是 i38 S3/S3b 已验证的候选策略，**只作为可选项存在，不得成为默认**
- `per_document` 命名统一为 `max_chunks_per_document`；**默认值锁死 8**（r39 预先声明的实验边界）

## 不变量与反例

**I-C1（策略可注入且默认不变）**
- 正例：`select(hits, SelectionPolicy())` 的输出 == 现行 `group_hits` + `observations_for` 的输出
- 反例：传入 `max_chunks_per_document=48` 时，输出必须变化（证明参数真的被使用，不是死参数）
- 反向断言：`SelectionPolicy().max_chunks_per_document == 8`

## 验收

1. 新增常驻测试 `tests/test_corpus_selection.py`：I-C1 三条
2. **等价性证明（关键）**：在新目录复制 `calibrate.py`，把 `group_hits`/`observations_for` 替换为 `selection.select`，与 `audits/20260920-i33-calibration/candidate_question_lexemes_or-observations.json` **逐字节比对相同**
   - `calibrate.py` 是 write-once（`calibration-summary.json` 存在即 `RuntimeError`）⇒ **不可原地复跑**，必须新目录
3. 语料族回归不回退

## 收益

- 此后所有轮次的结论可复现、可比较（同一份策略代码）
- 换策略只改一处（locality）；评测与生产共用同一实现（leverage）
- 恰好有两个消费者（评测 + 生产）⇒ **这是真 seam，不是假设的 seam**

## 不做

- 不改默认 policy 的任何一个数值
- 不把 selection 接进 `service.py` 的生产路径（那是 02 之后的事）
