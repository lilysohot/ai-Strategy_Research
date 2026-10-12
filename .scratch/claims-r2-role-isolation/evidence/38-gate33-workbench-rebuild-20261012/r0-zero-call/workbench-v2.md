# 门 33 Stage 1 工作台 v2（超集增强）

- 取代：`workbench.json` `sha256:e00d8ae65536bf662101ba1d53b8c3e9f80189e2be6b8172472abd02ea489777`（v2 是 v1 的严格超集：候选集合、既有字段值与 Stage-1 建议逐条不变，仅补齐 layer A/B 字段与契约视图。）
- 候选：222 条 ；金标：48 条

## 超集自检（AC-1/AC-2/AC-3）

- candidate_id 集合与顺序一致：**True**
- v1 既有字段逐条不一致数：**0**
- 槽位分配交叉校验分歧数：**0**
- Stage-1 建议与候选序列化后仍逐条等于 v1：**True**

## 新增字段覆盖（AC-4/AC-8）

| 字段 | 有值候选数 / 222 |
|---|---|
| `speaker_ref` | 222 |
| `attribution` | 220 |
| `condition` | 221 |
| `factuality` | 222 |

## 契约视图覆盖（Stage 2 可执行性）

| 契约字段 | 有值候选数 / 222 |
|---|---|
| `proposition` | 222 |
| `semantic_type` | 222 |
| `statement_role` | 222 |
| `speech_role` | 222 |
| `perspective` | 222 |
| `speaker_ref` | 222 |
| `polarity` | 222 |
| `attribution` | 220 |
| `source_stance` | 0 |
| `condition` | 6 |

## 契约视图承运与前置条款

| 契约字段 | 载体 | 前置条款 |
|---|---|---|
| `proposition` | `item.text` | normalization |
| `semantic_type` | `item.semantic_type` | caliber_clause |
| `statement_role` | `item.statement_role` | caliber_clause |
| `speech_role` | `item.speech_role` | caliber_clause |
| `perspective` | `item.perspective` | caliber_clause |
| `speaker_ref` | `item.speaker_ref` | id_mapping_or_exclusion |
| `polarity` | `item.polarity` | none |
| `attribution` | `layer_b.attribution` | caliber_clause |
| `source_stance` | `none` | source_read |
| `condition` | `item.text (statement_role==condition) | layer_b.condition` | caliber_clause |

> carrier/requires 取自 evidence/37 的实测：perspective/speech_role/statement_role/semantic_type 存在口径差，speaker_ref 存在 ID 空间差，source_stance 无载体须读原文，polarity 无需条款。

## 说明

- 逐条裁定清单仍沿用门 33 的 `workbench.md`（按金标组织，未受本次缺陷影响）。
- 本文件只补候选侧字段与契约视图，**不改变** Stage-1 建议，也不产出任何评分输入。
