# 评分契约 v4 条文草案（待人工签认）

- 日期：2026-10-12
- 状态：**提案**。本文不修改任何既有契约文件；签认后另行落地为
  `non-table-selected-target-scoring-contract-v4` 并保留 v3 哈希与内容可追溯（禁止就地覆盖）。
- 依据：Issue 34 `chain-report.md`、Issue 36 `accounting-checks.json`（AC-1/AC-3/AC-4/AC-5/AC-6）、
  `contract-gap-report.json`
- 零调用：本文为文本提案，未发起任何模型调用

## 0. 为什么需要 v4

v3 新增的 `condition_role_read_path` 方向正确（以 `condition` 作为 condition 角色的原子命题载体），
但没有回答三个已被实测证明必须回答的问题：

1. **载体映射由谁做、允许做什么**：候选只携带 `text`，不携带 `proposition`；人工若"改写"命题即违反
   `matching.projection`，而不改写则该记录无法裁定。Stage 2 因此在结构上不可执行（机读证据：
   `contract-gap-report.json.blocking_decision_required`）。
2. **缺失字段如何表示**：候选缺 `attribution` / `source_stance` / `speaker_ref`（实测 4 项）。
   未规定时必须记什么，人工只能自由发挥，结果不可复现。
3. **阈值与判据的单一来源**：门 28（已签认）为 `0.85 / 0.80`，评分器实现为 `0.95 / 0.90`
   （`structured_scoring.py:334-339`），两者不读彼此。

## 1. 建议新增条款（插入 `matching` 之下）

```json
"items_field_carrier_read_path": {
  "applies_to": "role == 'material_items'",
  "authoritative_side": "冻结金标（48/48 逐字可回取、xyl 签认、Issue 29 判定 gold_meaning_sound=true）",
  "carrier_mapping": {
    "rule": "裁定前允许且仅允许做确定性载体映射：候选 `text` 视为契约 `proposition` 的载体。映射只改字段名，不生成、不改写、不摘要任何语义文本。",
    "forbidden": "不得从金标反填候选缺失字段；不得把目标字符串直接赋给候选；不得为凑匹配而重写候选文本。",
    "recording": "映射后的字段集记入 `canonical_observed_fields`；未映射的契约必需字段必须显式记为 absent，不得留空、不得猜测。"
  },
  "absent_required_fields": {
    "list": ["attribution", "source_stance", "speaker_ref"],
    "rule": "候选未携带上述字段时，`canonical_observed_fields` 记 absent，等价性判定按契约 `unknowns` 条款处理；不得因缺字段直接判不匹配，也不得补造。",
    "condition_role_addition": "statement_role == 'condition' 且候选无 condition 载体时，裁定人须逐条判定候选 `text` 是否表达了该条件，并在 `reason` 记录判据。"
  },
  "equivalence_judgement": {
    "owner": "human adjudicator",
    "rule": "等价性一律由人工判定（沿用 matching.mode）；评分器不得自行按字段相等推导匹配。",
    "scorer_contract": "评分器只消费裁定完成的映射，并校验其 role/source_id 合法性与 `canonical_observed_fields` 是否齐备；身份相等不得作为匹配前提。"
  },
  "compound_condition": "沿用 v3：复合条件按子条件计分，命中任一子条件计部分命中，不得整体匹配。"
},
"threshold_single_source": {
  "rule": "召回/精确率/未裁定上限/断言清单以本契约与签认门为唯一来源；任何实现方不得另存一份。",
  "conflict_resolution": "实现值与契约不一致时以契约为准，实现方须改为读取或与契约同步，变更须具名签认。",
  "required_alignment": {
    "target_recall_overall_min": 0.85,
    "target_recall_per_source_min": 0.8,
    "candidate_precision_min": 0.8,
    "unresolved_candidates_max": 0
  }
}
```

## 2. 配套变更

- `matching.items` / `matching.conditions` 引用 `items_field_carrier_read_path`，删除只认
  `proposition` 逐字内容的隐含假设（v3 已改 `matching.conditions`，items 侧补齐）。
- `matching.projection` 保留原文，并显式指向「载体映射允许、改写禁止」的边界。
- `review_assertions`：为 6 条 label-only condition 项（NT-I09/I15/I19/I29/I35/I39）补条件断言
  （v3 已补 5 条，NT-I09 走 `compound_condition`）。
- 版本字段：`schema_version → non-table-selected-target-scoring-contract-v4`，
  `supersedes` 记 v3 哈希 `d9bc51f2…`，`revision_history` 记 v3→v4 变更清单。

## 3. 风险与不做

- 本草案**不放宽**任何 fail-closed 规则：载体映射只搬字段名，`absent` 必须显式记录。
- 本草案**不新增金标**、**不改阈值**（阈值只在 `threshold_single_source` 里声明单一来源）。
- 本草案**不授权**任何真实调用；重跑仍须另立门并具名授权。

## 4. 待签认

- 签名人：　　xyl　　日期： 2026-10-12
- 选项：☐ 采纳 v4 草案　☐ 改为仅扩抽取协议字段（路线 b）　☐ 退回修改
