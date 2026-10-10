# Issue 29 · items 金标全量语义审计（零调用只读）

Status: read_only_zero_call
Model calls: 0
Production database access: 0

本目录在**不发起任何真实模型调用、不访问生产库、不修改任何冻结金标**的前提下，对 Issue 10 冻结的
48-item 非表格金标做一次**独立对抗式语义审计**，并顺带澄清评分契约 `status=draft_pending_human_review`
与「评分口径已冻结」之间的缺口。它只审计与记录，不改冻结金标、不改 Issue 28 预注册门。

## 1. 目的与范围

- 直接动因：relations 线曾因语义边界模糊必须做 Issue 23 全量复核；items 线此前只有机械校验
  （`material-items-validation-v11`）与人工逐条签认（`review_status=accepted`，理由「按整包原样接受」），
  从未做过独立对抗式语义审计。在授权 items-only 真实复验之前，先核实金标本身是否有语义缺陷。
- 审计问题：48 条 items 的**原子性 / 可评分性 / 字段裁定**是否自洽，以及用于验收的**评分契约是否已签认**。
- 边界：只读；零模型调用；零生产库访问；不改冻结金标；发现缺陷则另立修正票，不就地改写。

## 2. 方法与来源

- 确定性只读脚本：`r0-zero-call/audit_items_semantic.py`（读取三份冻结输入 + Issue 28 门，
  产出 `r0-zero-call/findings.json`）。脚本无网络、无模型、无生产库访问，不写任何冻结产物。
- 审计口径：筛 `role == "material_items"` 记录；按 `statement_role == "condition"` 分组；
  判定 `proposition` 是**完整原子命题**还是**非命题标签**（原子内容仅存在于 `condition` 字段）；
  交叉核对契约 `role_required_fields`、`review_assertions` 与 Issue 28 门的高风险断言清单。
- 结论可追溯：`findings.json` 记录 4 个输入哈希、计数、condition 角色分析、契约快照与 F1–F4。

### 冻结输入哈希

| 输入 | sha256 |
| --- | --- |
| frozen-gold.json | `sha256:603de5e6c532463db8ae2788b830c2c1a74400b4ba736292bd5503468dfa7de2` |
| freeze-state.json | `sha256:08703b8dad9fc6c130872899741534c940787c29a15423db19d398999b237d85` |
| scoring-contract.json | `sha256:2eb24be7e74f9e6003ca623487478790cdb60265c5f05377eda377f498f3bdbe` |
| preregistered-gate.json（Issue 28） | `sha256:7cf87208e7c22ba545836d319010ef9afc0c5b8406812464d8dadd08a7319f47` |

## 3. 计数与 condition 角色分析

| 项 | 值 |
| --- | --- |
| 冻结分母 | claims 20 / material_items 48 / material_relations 24 |
| material_items 总数 | 48 |
| statement_role=condition 的 items | 10（NT-I09/I13/I15/I17/I19/I29/I35/I39/I42/I43） |
| 携带 `condition` 字段的 items | 11（含 1 条非 condition 角色：NT-I34） |
| condition 项中「完整原子命题」的 proposition | 4（NT-I13/I17/I42/I43） |
| condition 项中「非命题标签」的 proposition | 6（NT-I09/I15/I19/I29/I35/I39） |

人工已签认：condition 项的**底层语义裁定本身健全**（原子内容存在于 `condition` 字段），
缺陷在于**机读序列化与契约读路径**，而非金标含义错误。

## 4. 审计发现

### F1（high）· condition 角色原子命题的存储不一致

10 条 `statement_role=condition` 的 items 全部携带 `condition` 字段，但其 `proposition` 字段分裂为：
- **4 条**为完整原子命题（NT-I13/I17/I42/I43）；
- **6 条**为非命题标签，原子内容仅存于 `condition`（NT-I09/I15/I19/I29/I35/I39）。

例：NT-I09 的 `proposition = "估值风险触发条件"`，真正的原子命题在
`condition = "毛利率继续下降或Rubin延期"`。

契约 `role_required_fields.material_items` 要求 `proposition` 且**不包含 `condition`**，
`matching.items` 要求「一个原子命题」——因此**按必需字段读取的 scorer** 对这 6 条只拿到标签，
无法评分。定性：**gold 序列化一致性缺陷**（非金标含义错误）。

**逐条核对 `condition` 是否为完整原子命题**（基于原文 `quote`/`context_evidence`，明细见
`r0-zero-call/condition-items-detail.json`）：

| ID | `condition` | 完整原子命题？ | 依据 |
| --- | --- | --- | --- |
| NT-I15 | 下季 OCF/扣非净利润 < 0.5 | 是 | 单一数值比较，含指标/周期/算子/阈值；已有 `condition_logic` |
| NT-I19 | 出口管制影响GPU系统集成 | 是 | 单一因果式命题，无并列连词 |
| NT-I29 | 政策变化导致成本上升 | 是 | 单一因果式命题 |
| NT-I35 | 无差别相信所有公司的份额陈述 | 是 | 单一假设式命题 |
| NT-I39 | 海外产能税率增加 | 是 | 单一主谓命题 |
| NT-I09 | 毛利率继续下降**或**Rubin延期 | **否** | 「或」连接两个独立条件，是二元析取（复合），非单一原子 |

→ 修正表述：6 条 label-only 项的**共同缺陷**是 `proposition` 为标签（读路径缺陷）；但其中
**5 条 `condition` 已是完整单一原子命题**，可直接作为读路径命题文本；**NT-I09 例外**——
其 `condition` 为析取复合项、且无 `condition_logic` 承载，补读路径后仍违反「一个原子命题」，
需**额外拆分或定义析取读法**（对照组：NT-I17/NT-I42 的 `AND` 复合项由 `condition_logic` 显式承载）。

### F2（high）· 评分契约未签认，却被钉为门的度量基准

评分契约自身 `status = draft_pending_human_review`，`metrics.quality_gate` 明确声明「当前包和新增裁定
口径均待人工签认」；而冻结包 README 与 Issue 28 把该契约哈希（`2eb24be7…`）绑定为「已冻结评分口径」。
Issue 28 门 `quality_requirements_status = proposed_pending_human_signoff`。→ 门的度量基准实际**未签认**。

### F3（medium）· condition 角色在契约中建模不足

`condition_logic` 结构仅出现在 10 条 condition 项中 5 条（NT-I13/I15/I17/I42/I43）的
`review_assertions` 内，不在 `role_required_fields`、不在任何 item schema；契约**未定义 condition
角色的读路径**。6 条 label-only 中，5 条（NT-I09/I19/I29/I35/I39）同时落在 Issue 28 门
`high_risk_item_assertions_required` 之外——**既非自足命题、也未被回归防护**。

### F4（low）· 非阻断人工裁定记录

- NT-I22（2026 CPO 出货可忽略）vs NT-I33（CPO 当前尚无实际出货）：近重复，可能在 duplicates 口径碰撞。
- NT-I25 将评价性「良率仍不理想」标为 `semantic_type=fact`。
- NT-I34 在 `statement_role=claim` 下携带 `condition` 字段。

仅记录，不视为缺陷，交人工裁定。

## 5. 裁定结论

- `gold_meaning_sound = true`：金标**含义**健全，condition 项语义裁定正确，问题在机读序列化与契约读路径。
- `in_place_mutation_allowed = false`：不得就地修改冻结金标，也不得就地改写 Issue 28 门。
- `correction_ticket_required = true`：须以 **Issue 23 模式**（后继冻结 + 保留已签认原件）另立修正票。
- `gate_execution_blocked_pending`：items-only 质量门**执行受阻**，解开阻塞需满足：
  1. 在**已签认**契约中定义 condition 角色的 proposition 读路径；
  2. 评分契约完成签认（`status` 不再是 `draft_pending_human_review`）。

> **阻塞解除（2026-10-11，Issue 30 路线 A）**：评分契约升级并签认为
> `non-table-selected-target-scoring-contract-v3`（`sha256:d9bc51f2…`，新增 `condition_role_read_path`
> 及 `compound_condition`/`required_fields_override`）；Issue 28 门再绑定 v3、`quality_requirements_status`
> 转 `signed`、高风险断言补 5 条（门 `sha256:c6652591…`）。上述两条阻塞条件均已满足；冻结金标与
> freeze-state 字节未变。门仍处 `frozen_before_execution`，真实复验须另行授权。

## 6. 边界与不变量

- 本审计只读；未改冻结金标、未改 Issue 28 门、未新增金标、未放宽阈值。
- 零模型调用、零生产库访问；`unlinked ≠ confirmed`、执行成功 ≠ 协议有效 ≠ 发布 ≠ 语境完整 ≠ 质量通过。
- 审计通过**不等于** items-only 质量门通过；它只证明了金标含义健全，并暴露两项门就绪缺口。

## 7. 产物

- `r0-zero-call/audit_items_semantic.py`：零调用只读审计脚本。
- `r0-zero-call/findings.json`：机读审计结论（`items-gold-semantic-audit-1`），含 4 个输入哈希与 F1–F4。

## 8. 下一步

1. 就修正路径取得用户裁定（见 Issue 29「下一步」）：
   - 路线 A：**补签契约并定义 condition 评分读路径**（不改金标，仅补契约）；
   - 路线 B：**后继冻结归一化 6 条 condition 项**（Issue 23 模式，保留 signed 原件另立后继版本）。
2. 修正票闭合后，再单独申请有界 items-only 真实复验授权；本目录不得自动发起任何模型调用。
