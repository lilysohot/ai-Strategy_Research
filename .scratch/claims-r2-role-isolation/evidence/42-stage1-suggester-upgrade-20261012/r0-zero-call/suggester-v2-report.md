# Stage-1 助手 v2（含可核验证据链）

- 预注册：`preregistered-suggester-v2.json` `sha256:96fb234fcc8bbd95e636516ee24a3ef999da91062b33465edbb0b644b56b16d2`
- **不报准确率**：无人工裁定真值（EC-S2）

## 信号与权重（预注册固定，未调参）

| 信号 | 权重 | 定义 | 是否用到金标答案 |
|---|---|---|---|
| `slot_overlap` | 0.45 | 候选 slot ∈ 金标证据跨度的覆盖槽位（复用 evidence/36 covering_slots 同法） | 否 |
| `verbatim_quote` | 0.35 | 候选 evidence_quote 与金标 quote（或 context_evidence 引文）互相包含 | 否 |
| `number_hit` | 0.1 | 候选 text/value 与金标 quote 的数值交集 ≥1；≥2 时 +0.2 | 否 |
| `bigram_containment` | 0.1 | 金标 proposition/condition/value 文本在候选 text 中的字符 2-gram 包含率 ≥0.5 | 是（仅排序用） |
| `enum_agreement` | 0.05 | 归一化后 semantic_type/statement_role/perspective/polarity 中 ≥3 项一致 | 是（仅排序用） |

## 覆盖测量（R1–R4）

- 有建议的候选：**217/222**
- 金标可及（top3 中出现）：**44/48**
- 其中经槽位信号可达：**39/48**
- 有**逐字引文证据链**的金标（quote + context）：**41/48**
- 限定为 **quote-only**：**39/48**（与 issue-35 的 39/48 一致：**True**）
- EC-S1 口径差说明：口径差定位：助手 v2 的 verbatim 信号同时使用金标 `quote` 与 `context_evidence` 引文（更宽），而 issue-35 只用 `quote`；限定为 quote-only 后应与 39 对齐。二者差异必须显式披露，不得用其中一个数字替代另一个。

### 置信分布对比（同一批 222 候选）

| 来源 | high | medium | low | none |
|---|---|---|---|---|
| 旧（工作台 v1/v2 建议） | 3 | 17 | 146 | 56 |
| 新（助手 v2） | 46 | 129 | 8 | 39 |

- top1 发生变化的候选：**161/222**（⇒ 属新基线，Stage 2 须以 `suggestions-v2.json` 为准）
- 建议均带证据链：**1.0**
- 候选未被改写（EC-S5）：**True**

## 使用约束

- **禁止**把金标 `semantic_fields` 写进候选（这恰是 issue-33/34 旧预填 19 条的错误：`build_adjudication_draft.py:98-100`）。本助手只在对候选**排序**时使用金标记录，且不得改写候选任何字段。
- 沿用契约 v4 草案 `adjudication_clause.tooling`：建议仅作辅助；**抽样或独立复核时必须隐藏建议**。

## 说明

- 本文件是**裁定辅助**，不是评分输入；工作台 v2 字节未变。
- 合并方式（Stage 2 启动时）：工作台 v2 + 本目录 `suggestions-v2.json` 的 `suggestions` 字段。
