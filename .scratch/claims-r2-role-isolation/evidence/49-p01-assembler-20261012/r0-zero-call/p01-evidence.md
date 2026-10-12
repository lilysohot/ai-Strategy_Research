# P01 · 裁定→评分输入装配器 · 证据运行

- 零模型调用；只读输入；`in_place_edits = 0`。
- 契约绑定：`non-table-selected-target-scoring-contract-v4.1`（`frozen_signed`，签认人 xyl）
- 工作台目录：222 条候选 / 2 个源

## 一、忠实运行：门 33 草案的 19 条 `accepted` 全部被拒

- 提交：**19**　装配成功：**0**　拒绝：**19**

| 候选 | 首个违约 |
|---|---|
| `itm_abebb2a7163927e9` | itm_abebb2a7163927e9: reviewer is required (adjudication_clause.responsible_party) |
| `itm_d0e9f3a0a75f5157` | itm_d0e9f3a0a75f5157: reviewer is required (adjudication_clause.responsible_party) |
| `itm_45c20faff776385b` | itm_45c20faff776385b: reviewer is required (adjudication_clause.responsible_party) |

## 二、独立规则探测（不被 fail-fast 掩盖）

| 违约类 | 命中数 |
|---|---|
| `reviewer_missing` | 19 |
| `evidence_missing` | 19 |
| `judgement_outside_contract_enum` | 19 |
| `proposition_rewritten_or_copied` | 19 |
| `field_filled_from_outside_candidate::attribution` | 19 |
| `field_filled_from_outside_candidate::speaker_ref` | 19 |
| `field_filled_from_outside_candidate::source_stance` | 19 |
| `deterministic_field_declared_differently::perspective` | 3 |

- 有违约记录：**19**；无违约记录：**0**

## 三、草案与契约的形态差

- 草案 judgement 分布：`{'pending': 203, 'accepted': 19}`
- 草案 stage 分布：`{'raw': 222}`
- 草案缺失的 `required_per_record_fields`：[]
- 契约枚举冲突：{'accepted': "adjudication_clause.candidate_judgements has no 'accepted' (record_states are a separate vocabulary and are not judgements)"}

## 四、结论

> 契约合法裁定数 = 0 ⇒ 装配器输出为空 ⇒ 门 33 的 0 分是**装配缺口**造成的，不是抽取质量问题。这以可执行形式证实了 §5.13.2『链路末端两处缺环』：P01 装配器此前不存在，且现有草案裁定不是契约形态（含金标注入）。

## 五、不宣称

- 本产物不评价抽取质量，不产生任何门分数。
- 本产物不修改 draft；draft 仍是其原样（其金标注入见 evidence/33 build_adjudication_draft.py:98-100）。
- 『19 条被拒』不等于『19 条都真的不对』；它只说明其 canonical_observed_fields 非契约可接受形态。
