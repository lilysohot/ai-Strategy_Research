# 05 清洗判定依据可机读

Status: needs-triage
Type: task
Depends: 03
Layer: clean
Bound-byte impact: **是**（`clean.py`）
Reingest: **是**（与 03 合并成一次）

## 问题

```384:421:plugins/corpus/preparation/clean.py
def clean_reader_result(result: ReaderResult) -> CleanResult:
    """对读取结果做保真清洗：噪声判定 + 空白投影 + 全量区域台账。"""
```

噪声判定（`_banded_noise` / `_toc_noise` / `_is_analyst_roster` / disclaimer）与空白投影在**同一个循环**里完成，共用同一个 `UnitStatus` 出口。`CleanRegion.reasons` 只有**码**（如 `header_repeated_geometric`），没有**依据值**（重复了几页、带边界在哪、命中哪一行）。

⇒ i37 的 `doc_not_kept_clean_stage_loss`（2 条：`company-007/e1`、`company-008/a-1`）**无法回答"这条剔除是判错了，还是它本来就该剔除"**。

## 改动面

新增结构化的判定记录，**不改变 `reasons` 的形状**（`reasons` 被多处测试断言，改形状会牵动冻结测试族）：

```python
@dataclass(frozen=True)
class NoiseVerdict:
    code: str                    # 与 reasons 中的码一致
    rule: str                    # 命中的具体规则名
    observed: dict[str, object]  # 依据值：重复页数 / 带边界 / 命中行 / 占比
    threshold: dict[str, object] # 当时生效的阈值（_REPEAT_MIN_PAGES / _BAND_RATIO 等）

# CleanRegion 新增字段（带默认值）
verdicts: tuple[NoiseVerdict, ...] = ()
```

要点：
- `reasons` 保持原样（向后兼容，既有断言不动）
- `verdicts` 只增不改；噪声区与保留区都产出（保留区为空元组）
- 阈值在判定时**读取当时的常量**并抄进 `threshold`，使"改阈值"可被 diff 出来

## 不变量与反例

- **I-E1（判定可归因）**：任一 `status is NOISE` 的区域，其 `verdicts` 非空且每条 `code` 都在 `reasons` 中
- **I-E2（依据值非空）**：`verdicts[i].observed` 必须含至少一个可复核的数值/坐标（不得是空 dict）
- 反例：构造一个"重复 2 页"的页眉（低于 `_REPEAT_MIN_PAGES=3`），断言**不产生** `header_repeated_geometric` 判定，且 `observed["repeat_pages"] == 2`

## 验收

1. 常驻测试：I-E1、I-E2 + 上述反例
2. **目标级**：`company-007/e1`、`company-008/a-1` 两条给出机读归因结论（"命中哪条规则 / 依据值多少 / 阈值多少"），并据此判定是"规则过宽"还是"本就该剔"
3. 语料族回归不回退（`tests/test_corpus_preparation_clean.py` 现有断言全部保持）

## 冻结影响

动 `clean.py` ⇒ 与 03/04 合并为一次 `i0c-r41`。

## 不做

- **不动 `clean.py:26-28` 的 seam 纪律**：缺口是否阻断发布仍由 `gaps.py` 裁决，本模块只保证"每个缺口都在台账里、带坐标"
- 不在本票内调整任何噪声阈值（只记录依据；调阈值须单独立项 + 具名签认）
- 不改 `reasons` 的形状
