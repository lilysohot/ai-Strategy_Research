# L9 重做（金标盲 + 留出记录）

- 预注册：`preregistered-l9-redo.json` `sha256:d1c5672ee70509c362e6a7ff10a40006a0edfd4510a0452d45ecdb3e985f74fd`
- 切分：development = `optical-module-docx`，held-out = `industrial-fulian-md`
- 归因：只按槽位跨度重叠（不读金标 semantic_fields）

## 契约字段的载体可得性（按记录，48 条金标）

| 契约字段 | 全体命中/分母 | md（留出） | docx（开发） |
|---|---|---|---|
| `proposition` | 39/48 | 13/22 | 26/26 |
| `semantic_type` | 39/48 | 13/22 | 26/26 |
| `statement_role` | 39/48 | 13/22 | 26/26 |
| `speech_role` | 39/48 | 13/22 | 26/26 |
| `perspective` | 39/48 | 13/22 | 26/26 |
| `speaker_ref` | 0/48 | 0/22 | 0/26 |
| `polarity` | 39/48 | 13/22 | 26/26 |
| `attribution` | 0/48 | 0/22 | 0/26 |
| `source_stance` | 0/48 | 0/22 | 0/26 |
| `condition` | 1/10 | 0/7 | 1/3 |
| `estimate_status` | 0/48 | 0/22 | 0/26 |

## 记录级可达性（route a 的上界，诊断口径）

- 金标记录：48
- 覆盖槽位内无任何候选（传输事件丢包）：**9**
- 全部必需字段都有载体（strict）：**0**
- 仅按有载体的字段计（carrier-only）：**35**

## 四臂（现有评分器，严格 identity 相等）

| 臂 | tp | fp | fn | precision | recall |
|---|---|---|---|---|---|
| A_native | 0 | 222 | 48 | 0 | 0 |
| B_gold_injected | 19 | 0 | 29 | 1 | 19/48 |
| C_route_a_projection | 0 | 222 | 48 | 0 | 0 |

- `D_field_alignment_tp` = **0**（诊断口径，禁止称召回）
- `D2_lexical_containment_tp` = **0**（探索性，不参与任何判据）

## 候选侧实测（222 条）

| 字段 | key 存在数 | 非空数 |
|---|---|---|
| `proposition` | 0 | 0 |
| `semantic_type` | 222 | 222 |
| `statement_role` | 222 | 222 |
| `speech_role` | 222 | 222 |
| `perspective` | 222 | 222 |
| `speaker_ref` | 0 | 0 |
| `polarity` | 222 | 222 |
| `attribution` | 0 | 0 |
| `source_stance` | 0 | 0 |
| `condition` | 0 | 0 |
| `estimate_status` | 0 | 0 |

## 归因口径

> 载体可得性按'设计意图的覆盖槽位'统计（与 issue-34 L1/L2 的 locator→unit→packet→slot rebasing 同法）。这不是评分器的约束：identity 匹配不含槽位，因此 39/48 是**受限口径**；不受限口径（源内任一候选）下 proposition 与 5 个枚举字段均有候选（text 非空 222/222）。两份口径都不改变 EC-1：4 个字段在两份口径下都是 0/48。

## 预注册判据逐条回答

- **EC-1**：触发：契约 material_items 必需字段中 4 个在候选上零载体（含 speaker_ref），其余非必需字段 estimate_status 亦为 0。route a 无法产出契约形态记录。
- **EC-2**：成立：B=19 且 C=0 ⇒ 旧 L9 的 19/48 全部来自金标注入，该数不构成路线 a 的可行性证据。
- **EC-3**：字面触发（多项差 > 10pp），但差异 100% 由 corpus_absent 解释：剔除覆盖槽位内无候选的记录后，md 与 docx 同为 1.0 ⇒ 规则本身跨源成立。判据字面结论与可归因结论相反，属预注册时未预见，记 backlog。
- **EC-4**：route a 的记录级上界 = 0/48（strict 口径）；仅按候选有载体的字段计 = 35/48，其中 9 条为覆盖槽位内无候选（全部属 md）。两个数字不得合并表述。
- **EC-5**：判据外新发现已登记为 backlog，不回流本次判据。
- **EC-6**：冲突项以实测为准并留待报告修订；本产物即修订依据。

## backlog（不回流本次判据）

- **B-1**：覆盖槽位内无候选的 md 记录为 9 条，而非 issue-34 §6 假定的 7 条：除丢包区 char:5246-5537 的 7 条外，另有 NT-I06（char:1393-1655）与 NT-I41（char:5055-5071）。这两条未出现在 residual-attribution 的 9 个未产出槽位归因里。
- **B-2**：arm D / D2 均为 0，但两臂要求 5 个枚举字段逐字相等，故 0 无法区分'枚举值不一致'与'命题文本不一致'两种原因。
- **B-3**：条件载体在实践上近乎不存在：10 条 condition 角色金标中仅 1 条（docx）的覆盖槽位内存在 statement_role=condition 的候选。契约 v3 新增的 condition_role_read_path 因此几乎没有可读数据。
