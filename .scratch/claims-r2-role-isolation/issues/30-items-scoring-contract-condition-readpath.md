# 30 · items 评分契约补签与 condition 读路径定义（路线 A，不改金标）

Status: complete
Type: task
Parent: [29 · items 金标全量语义审计](29-items-gold-semantic-audit.md)、[10 · 评分、标注范围与质量门冻结](10-quality-gates.md)
Model attempts: 0（契约文本修订与签认为零调用）
Production database access: 0

## 问题

Issue 29 的零调用审计在 Issue 10 冻结的 48-item 金标上发现三处缺口（详见
`../evidence/29-items-gold-semantic-audit-20261010/`）：

- **F1**：10 条 `statement_role=condition` items 全部携带 `condition` 字段，但 `proposition` 分裂——
  4 条（NT-I13/I17/I42/I43）是完整原子命题，6 条（NT-I09/I15/I19/I29/I35/I39）只是标签，
  原子内容仅存于 `condition`。契约 `role_required_fields.material_items` 只要求 `proposition`、
  不列 `condition`，`matching.items` 要求「一个原子命题」，故按必需字段读取的 scorer 对这 6 条无法评分。
  实例：`NT-I09.proposition = "估值风险触发条件"`，真正的原子命题在
  `NT-I09.condition = "毛利率继续下降或Rubin延期"`。
- **F2**：评分契约 `status = draft_pending_human_review`、`metrics.quality_gate` 声明仍待人工签认，
  却被 Issue 28 门绑定为「已冻结评分口径」；门 `quality_requirements_status = proposed_pending_human_signoff`。
- **F3**：`condition_logic` 仅出现在 10 条 condition 项中 5 条的 `review_assertions` 内，不在任何 schema；
  契约未定义 condition 角色读路径；5 条 label-only 项同时在门高风险断言清单之外（未被回归防护）。

**用户已裁定修正路径 = 路线 A**：补签评分契约并定义 condition 读路径，**不修改冻结金标**
（对比路线 B：后继冻结归一化 6 条 condition 项）。本票执行路线 A。

## 目标

在不发起任何真实模型调用、不改动或取代 Issue 10 冻结金标、相同前提：

- 在评分契约中显式定义 condition 角色 items 的**原子命题读路径**，使 6 条 label-only 项可被正确评分。
- 补齐 F3 的回归防护：明确 `condition_logic` 的定位，并把 label-only 项纳入门的高风险断言清单。
- 使评分契约从 `draft_pending_human_review` 完成人工签认；同步更新 Issue 28 门对契约哈希的绑定
  （门的 `quality_requirements_status` 由 `proposed_pending_human_signoff` 转为签认态）。

## 建议的契约修订（待人工签认，agent 不自行定稿）

在 `non-table-selected-target-scoring-contract-v2` 中新增 condition 读路径条款，语义如下：

```json
"condition_role_read_path": {
  "applies_to": "statement_role == 'condition'",
  "atomic_proposition_source": "condition 优先，proposition 兜底",
  "rule": "condition 角色 items 的原子命题由非空 `condition` 字段承载；`proposition` 可为命名该条件的短标签。scorer 必须把非空 `condition` 值作为可匹配的原子命题；仅当 `condition` 缺失时才以 `proposition` 为准。",
  "condition_logic": "存在时为规范化/机读形式，仅作辅助，不得作为命题文本参与匹配。",
  "compound_condition": "当 `condition` 为复合（含 AND/OR 连接多个子条件）时，scorer 必须按子条件计分：各子条件均可匹配，命中任一子条件计为部分命中；复合项不得作为单一原子命题整体匹配。仅 NT-I09（`condition=\"毛利率继续下降或Rubin延期\"`，二元析取、无 `condition_logic`）落此项，其余复合项 NT-I17/NT-I42 已有 `condition_logic` 显式承载。",
  "required_fields_override": "statement_role == 'condition' 时，`condition` 追加为必需字段（其余角色不变，避免误伤 NT-I34 等非 condition 角色携带 condition 的情况）。"
}
```

配套条款：

- `matching.items`/`matching.conditions` 引用上述读路径，删除只认 `proposition` 的隐含假设。
- `review_assertions`：为 NT-I09/I15/I19/I29/I35/I39 补条件断言（或明确不计入的理由），
  至少使 6 条 label-only 项全部进入门 `high_risk_item_assertions_required`。
- `status` 由 `draft_pending_human_review` 改为经人工签认的终态。

> 上述文本仅为**提案**，最终措辞与签认由人工（xyl）裁定；agent 不自行改写 `status` 或签署。

## 边界与约束

- **不改冻结金标**（`frozen-gold.json` 与 `freeze-state.json` 保持字节不变）；不新增金标。
- 不改 Issue 28 门的阈值/执行要求；仅在其绑定的契约哈希因修订变化后**同步再绑定**，并保留旧绑定记录。
- 零模型调用、零生产库访问、不发布。
- 契约一经签认即冻结，不得按 items-only 执行结果反向放宽。
- 签认前 items-only 质量门保持**执行受阻**（见 Issue 29 `verdict.gate_execution_blocked_pending`）。
- 禁止就地覆盖式改写历史：修订以新契约版本或显式版本字段记录，旧 `draft` 与旧哈希留存可追溯。

## 执行结果

用户于 2026-10-11 指令「按 Issue 30 的提案执行」，agent 据签认版本落地（零调用、零生产库访问、不发布）：

- **契约修订**（`evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json`）：
  - `schema_version` → `non-table-selected-target-scoring-contract-v3`；`status` → `frozen_signed`。
  - 新增 `condition_role_read_path`（含 `rule`、`condition_logic` 定位、`compound_condition`、
    `required_fields_override`、`audit_reference`）。
  - `matching.items`/`matching.conditions` 显式引用读路径。
  - `review_assertions` 增补 NT-I09（compound 二元析取）/NT-I19/NT-I29/NT-I35/NT-I39。
  - 新增 `supersedes`（记 v2 哈希 `2eb24be7…` 与当时 `draft_pending_human_review` 状态）、
    `revision_history`（v2→v3 变更清单）、`signoff`；旧 v2 内容与哈希留存可追溯，未就地覆盖。
  - 新哈希：`sha256:d9bc51f286a977ec92315b6e97c7ac303a971691334f4752ccd7e61d5b75a7ce`。
- **门再绑定**（`evidence/28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate.json`）：
  - `gold.scoring_contract_sha256` → v3 哈希；`quality_requirements.metric_basis` → `-v3`。
  - `quality_requirements_status` → `signed`。
  - `high_risk_item_assertions_required` 由 11 条扩为 16 条（补 NT-I09/I19/I29/I35/I39）；
    `high_risk_item_annotations` 同步补 5 条。
  - 新增 `revision_history`（revision 1 记旧契约哈希与 `proposed_pending_human_signoff`；revision 2 记本次再绑定）。
  - **未改动**门阈值/执行要求/授权四项/终态判定；`terminal_decision` 不变。
  - 新门哈希：`sha256:c665259153d98fa9b41275595383408e66baf95737f89870369decfe3c015acc`。
- **未改动** `frozen-gold.json` / `freeze-state.json`（字节不变）、未新增金标、未放宽阈值、未改 prompt/协议。
- Issue 29 阻塞项（「契约签认」+「condition 读路径入已签认契约」）**据此解除**；但门仍处
  `frozen_before_execution`，真实复验及授权四项仍全 false，须另行申请。

> 签认后需：重算契约哈希 → 更新 Issue 28 `preregistered-gate.json` 的契约绑定与
>  `quality_requirements_status` → 记录新门哈希 → 方可将 Issue 29 的阻塞项置为解除。（已完成）

## 关联

- 审计：Issue 29 `../evidence/29-items-gold-semantic-audit-20261010/`（F1/F2/F3）。
- 金标：Issue 10 `evidence/10-quality-gold-freeze-20261008-r2`（48-item，xyl 签认，不修改）。
- 契约：`evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json`
  （已签认 `non-table-selected-target-scoring-contract-v3`，`sha256:d9bc51f2…`；旧 v2 `sha256:2eb24be7…` 留存于 `supersedes`）。
- 门：Issue 28 `evidence/28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate.json`
  （再绑定后 `sha256:c6652591…`；旧 `sha256:7cf87208…` 留存于门 `revision_history`）。
- 修正模式对比：Issue 23（路线 B 先例，后继冻结 + 保留 signed 原件）——本票采路线 A，故不适用。

## Evidence

- `../evidence/29-items-gold-semantic-audit-20261010/`（缺口来源）
- 修订后契约：`../evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json`（v3，已签认）
- 再绑定后的 Issue 28 门：`../evidence/28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate.json`

## 下一步（需人工单独授权，本票不自动发起）

1. ~~人工（xyl）审阅并签认 condition 读路径条款与配套修订。~~ 已完成。
2. ~~落地契约修订、重算哈希、再绑定 Issue 28 门并更新记录。~~ 已完成。
3. 解除 Issue 29 阻塞项后，再单独申请有界 items-only 真实复验授权
   （`attempts_max` = md 10 + docx 14 = 24、`concurrency = 1`，模型由用户指定）。**待用户发起。**
