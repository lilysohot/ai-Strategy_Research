# P02 设计说明 · 评分器匹配机制改造

- 状态：**待 U 审阅**（本文件只是设计说明，未改任何代码）
- 依据契约：`non-table-selected-target-scoring-contract-v4.1`（`sha256:c76ac13e…`，已签 2026-10-12）
- 前置：P01 已完成（`plugins/corpus/adjudication_assembly.py`，装配器输出 `AdjudicatedMapping`）
- 零模型调用

## 一、问题（现状，带行号）

| 现状 | 契约要求 |
|---|---|
| `_score_candidates` 用 `item.identity == candidate.identity` 决定匹配（`structured_scoring.py:456-458`），identity = `(role, source_id, origin, semantic_fields)`（`:117-120`、`:139-142`） | `read_path.equivalence_judgement.scorer_contract`：**「身份相等不得作为匹配前提」** |
| 评分器无任何裁定输入入口 | 同上：**「评分器只消费裁定完成的映射」** |
| 契约合法操作下自动匹配数 = 0（实测：evidence/36 四臂 tp=0；evidence/37） | — |

即：**匹配机制本身就是"链路末端缺环"**。P01 修了上游（装配器），P02 修下游（消费方式）。

## 二、方案：新增「裁定驱动」通道，身份相等降级为显式 legacy 诊断

### 2.1 接口变更（最小、向后兼容）

```python
class MatchingMode(StrEnum):
    ADJUDICATED = "adjudicated"            # 默认：契约路径
    LEGACY_IDENTITY = "legacy_identity"    # 仅诊断/对照臂，须显式指定

def score_structured_quality(
    gold, *,
    raw_candidates, validated_candidates,
    raw_mappings: tuple[AdjudicatedMapping, ...] | None = None,
    validated_mappings: tuple[AdjudicatedMapping, ...] | None = None,
    matching_mode: MatchingMode = MatchingMode.ADJUDICATED,
    ...  # 其余参数不变
)
```

- `matching_mode=ADJUDICATED` 且 `raw_mappings is None` ⇒ **报错**（fail-closed），不再回落到身份相等。
- `LEGACY_IDENTITY` 下必须**同时**显式传 `matching_mode` 且不得传 mappings；用于 evidence/36 的控制臂复现与防退化对照。
- 现有 23 个评分器测试：其中用身份相等的会显式改为 `matching_mode=LEGACY_IDENTITY`（**测试改的是调用点，不是断言**）。

### 2.2 裁定驱动路径的匹配语义

| judgement | 匹配 | 计入 |
|---|---|---|
| `matched` | 匹配 `matched_gold_id` | TP |
| `correct_extra` | 不匹配（gold_record_id=None） | `correct_extra` 计数 |
| `incorrect` | 不匹配 | FP |
| `duplicate` | 不匹配 | `duplicate_fp` |
| `out_of_scope` | 不进候选（由装配器剔除） | 不计 |
| `unresolved` | 装配器已拒绝 | — |

**不做**：不按 `semantic_fields` 二次判定、不做相似度、不做兜底匹配。评分器只校验裁定合法性。

### 2.3 评分器侧的校验（fail-closed）

1. 每个候选**必须**有 mapping；缺失 ⇒ 报错（契约 `unresolved_candidates_max = 0`）。
2. `matched` 的 `gold_record_id` 必须存在且在该候选的 role/source 内；不存在或跨 role/source ⇒ 报错。
3. 一个 gold 记录只能被匹配一次（一对一）；重复 ⇒ 报错。
4. 两条通道不得混用（同一 role 内 mappings 与 identity 不可并存）。

## 三、指标口径的对应改动（契约 `metrics`）

```python
candidate_precision = (matched + correct_extra) / (matched + correct_extra + incorrect + duplicate)
```

- `RoleMetrics` 增 `correct_extra: int = 0`；`precision` 改为上式。
  **向后兼容验证**：默认 0 时 `(tp+0)/(tp+0+fp)` 与原 `tp/(tp+fp)` 恒等 ⇒ 既有断言不受影响。
- `target_recall` 分母不含 `correct_extra`（契约：不追溯增加召回分母）。
- `risk_condition` 仍按既有算法；P02 不动。

## 四、明确不在 P02 范围内

| 事项 | 归口 |
|---|---|
| 阈值改读契约（0.85/0.80/20） | **P03**（P02 不动 `PILOT_CANDIDATE_POLICY`） |
| 其它字段的口径归一化（attribution/speaker_ref 之外） | **P04** |
| 口径映射回归测试 | **P05** |
| 冻结链校验器 | **P16** |

## 五、回归测试计划（P02 的退出判据）

新增 `tests/test_corpus_structured_scoring_adjudicated.py`：

1. matched 映射 ⇒ TP，不比对字段（构造一个字段**完全不同**但映射正确的样例，必须算 TP——这是"身份相等不再是前提"的可执行证明）。
2. 字段**完全相同**但 mapping 判 `incorrect` ⇒ 必须算 FP（反向证明：字段相等也不能自动匹配）。
3. `correct_extra` 进入 precision 分子；不入 recall 分母。
4. `duplicate` 计 FP。
5. mapping 缺失 ⇒ 报错；matched 指向不存在的 gold ⇒ 报错；跨 role/source ⇒ 报错；一对一冲突 ⇒ 报错。
6. `ADJUDICATED` 无 mappings ⇒ 报错（不得回落）。
7. 既有 23 个测试：改调用点显式声明 `LEGACY_IDENTITY`，断言不变，全绿。
8. evidence/36 的四臂在 `LEGACY_IDENTITY` 下重跑，字节级结果不变（防止"改造顺手改了 legacy"）。

## 六、需要你确认的两点

1. **默认值**：`ADJUDICATED` 为默认、`LEGACY_IDENTITY` 必须显式（我建议这样；若你希望默认保持现状以免动既有调用点，我改为显式双参）。
2. **既有测试改调用点**：`tests/test_corpus_structured_scoring.py` 共 14 个测试、**14 处** `score_structured_quality(...)` 调用点，全部依赖身份相等匹配，需逐一加 `matching_mode=LEGACY_IDENTITY`。这是改**调用点**（不是放宽断言）。是否同意？

## 七、复算口径提示

P02 完成后**不要**立刻读成"门 33 有分了"：真实裁定数仍为 0（Stage 2 阻塞，203 条 unresolved），装配器输出为空。P02 的可验证效果是**构造样例下的匹配语义正确 + legacy 臂字节级不变**，不是真实分数。

