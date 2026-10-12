# claims / material_relations 同型 L3 审计（§7-9）

- 预注册：`preregistered-roles-l3.json` `sha256:8f970041130d1a66be86d6b128eebd606bf4e4809b359337ed4a97031c0ba25a`
- 范围声明：claims = no production artifact in this workstream (items-only gate-32 protocol)；relations = measured 0 relations across both treatment sources

## 金标侧（实测）

| 角色 | 金标记录数 |
|---|---|
| `claims` | 20 |
| `material_items` | 48 |
| `material_relations` | 24 |

## `claims`：契约必需字段 × 载体

| 契约字段 | gold 非空 | 生产端载体 | 依据 |
|---|---|---|---|
| `subject` | 20/20 | item_field | code_level (claims_detail.ClaimRecord) |
| `metric` | 20/20 | item_field | code_level (claims_detail.ClaimRecord) |
| `period` | 20/20 | derived | code_level (claims_detail.ClaimRecord) |
| `unit` | 20/20 | item_field | code_level (claims_detail.ClaimRecord) |
| `value` | 20/20 | item_field | code_level (claims_detail.ClaimRecord) |
| `factuality` | 20/20 | alias | code_level (claims_detail.ClaimRecord) |
| `attribution` | 20/20 | absent | code_level (claims_detail.ClaimRecord) |
| `perspective` | 20/20 | absent | code_level (claims_detail.ClaimRecord) |
| `source_stance` | 20/20 | absent | code_level (claims_detail.ClaimRecord) |
| `estimate_status` | 20/20 | absent | code_level (claims_detail.ClaimRecord) |
| `qualifier` | 20/20 | derived | code_level (claims_detail.ClaimRecord) |

- 无载体/不可评分字段：['attribution', 'perspective', 'source_stance', 'estimate_status']

## `material_items`：契约必需字段 × 载体

| 契约字段 | gold 非空 | 生产端载体 | 依据 |
|---|---|---|---|
| `proposition` | 48/48 | text_carried | measured (evidence/37) |
| `semantic_type` | 48/48 | item_field | measured (evidence/37) |
| `statement_role` | 48/48 | item_field | measured (evidence/37) |
| `speech_role` | 48/48 | item_field | measured (evidence/37) |
| `perspective` | 48/48 | item_field | measured (evidence/37) |
| `speaker_ref` | 48/48 | item_field | measured (evidence/37) |
| `polarity` | 48/48 | item_field | measured (evidence/37) |
| `attribution` | 48/48 | item_field_layer_b_coarse | measured (evidence/37) |
| `source_stance` | 48/48 | absent | measured (evidence/37) |

- 无载体/不可评分字段：['source_stance']

## `material_relations`：契约必需字段 × 载体

| 契约字段 | gold 非空 | 生产端载体 | 依据 |
|---|---|---|---|
| `from_gold_record_id` | 24/24 | structurally_unscoreable | measured(0 relations) + code_level |
| `to_gold_record_id` | 24/24 | structurally_unscoreable | measured(0 relations) + code_level |
| `relation` | 24/24 | alias | measured(0 relations) + code_level |
| `provenance` | 24/24 | absent | measured(0 relations) + code_level |

- 无载体/不可评分字段：['from_gold_record_id', 'to_gold_record_id', 'provenance']

## 判定

- **material_items**（measured）：同型接缝（已实测确认）
  - 依据：evidence/37：零载体必需字段 = source_stance；枚举轴口径相反
- **claims**（code_level）：疑似同型（同为『归属／来源态度／估计状态』族字段缺载体），但**未在数据上验证**
  - 依据：code_level：ClaimRecord 无 ['attribution', 'perspective', 'source_stance', 'estimate_status'] 的承载字段；claims 运行产物在本范围不存在
- **material_relations**（measured + code_level）：不同型：属协议范围外 + 契约结构性不可评分，不是字段错配
  - 依据：实测 relations 条数 = 0；协议明文排除（MATERIAL_ITEM_JSONL_PROMPT: 本阶段只抽 speakers 和 items，不输出 relations）；契约必需字段含金标主键 ['from_gold_record_id', 'to_gold_record_id']

### EC-B4 结构性不可评分

- 字段：['from_gold_record_id', 'to_gold_record_id']
- 后果：严格 identity 匹配要求候选 semantic_fields 逐字等于金标；要求候选携带金标主键，等于要求候选先知道答案 ⇒ 该角色在现评分器下恒为 0。

### §7-11 建议（EC-B5）

- 结论：**每角色通用读路径机制（但先只对 items 落地）**
- 依据：三角色的缺口同属『归属／来源态度／估计状态 + 口径归一化』这一族；写成 items-only 的条款将来必然在 claims 上重做一次；但 claims 缺产物、relations 属范围外，故本期只对 items 实现，机制留接口。

## 与 issue-34 的对照

- §5.6『另两角色的同型接缝未验证』：现仍为未验证（claims code_level / relations 范围外），但可进一步确定 relations 不是字段错配而是协议范围外 + 契约含金标主键。
