# 29 · items 金标全量语义审计（零调用只读）

Status: completed
Type: task
Parent: [10 · 评分、标注范围与质量门冻结](10-quality-gates.md)、[28 · items-only 质量门零调用预注册](28-items-only-quality-gate-preregistration.md)
Model attempts: 0（零调用只读审计）
Production database access: 0

## 问题

Issue 28 已把 items-only 质量门与 5 阶段消费闭环零调用预注册，下一步须由用户单独授权有界真实复验。
但在放行前存在一个前置疑问：Issue 10 冻结的 48-item 非表格金标，从未像 relations 线那样做过独立对抗
式语义审计——它此前只有机械校验（`material-items-validation-v11`）与人工逐条签认（
`review_status=accepted`，理由「按整包原样接受」）；机械校验「不证明任意语义蕴含」，
`review_assertions` 也明确「不自动证明语义正确」。若金标本身存在语义或契约缺陷，直接开跑真实复验会把
缺陷混入验收结论。

因此须先做一次**零调用、只读**的全量语义审计，核实金标并澄清评分契约的签认缺口。

## 目标

在不发起任何真实模型调用、不访问生产库、不修改任何冻结产物的前提下：

- 独立复核 48 条 `material_items` 的原子性 / 可评分性 / 字段裁定是否自洽。
- 顺带澄清评分契约 `status=draft_pending_human_review` 与「评分口径已冻结」之间的缺口。
- 结论干净则附为 Issue 28 门就绪证据；发现缺陷则另立修正票，**不直接改冻结金标**。

## 边界与约束

- 只读：不改冻结金标、不改 Issue 28 门、不新增金标、不放宽阈值。
- 零模型调用、零生产库访问、零 holdout 访问。
- 审计通过 ≠ items-only 质量门通过；本票不授权任何执行。
- 缺陷修正遵循 Issue 23 模式：后继冻结 + 保留已签认原件，禁止就地覆盖。

## 执行结果

- 以只读脚本 `audit_items_semantic.py` 对 48 条 items 完成全量复核，产出 `findings.json`
  （`items-gold-semantic-audit-1`，含 4 个输入哈希）。
- 变体计数：48 items；`statement_role=condition` 10 条；其中完整原子命题 4 条（NT-I13/I17/I42/I43）、
  非命题标签 6 条（NT-I09/I15/I19/I29/I35/I39）；有 `review_assertion`/`condition_logic` 5 条；
  门高风险断言之外的 condition 项 5 条（NT-I09/I19/I29/I35/I39）。
- 契约快照：`status = draft_pending_human_review`、`proposition` required=true、`condition` required=false；
  门 `quality_requirements_status = proposed_pending_human_signoff`。
- 审计发现：
  - **F1（high）** condition 角色原子命题存储不一致——6 条把原子内容只放在 `condition`，而契约只要求
    `proposition` 且不列 `condition`；按必需字段读取的 scorer 对这 6 条只拿到标签，无法评分。
    逐条核对（`condition-items-detail.json`）：6 条中 **5 条 `condition` 本身即完整单一原子命题**
    （NT-I15/I19/I29/I35/I39，可直接作读路径文本）；**NT-I09 例外**——`condition="毛利率继续下降或Rubin延期"`
    为 `或` 二元析取（复合）、且无 `condition_logic`，补读路径后仍违反「一个原子命题」，需额外拆分或定义析取读法。
  - **F2（high）** 评分契约未签认（`draft_pending_human_review`），却被钉为 Issue 28 门的度量基准。
  - **F3（medium）** `condition_logic` 仅存在于 `review_assertions`、不在任何 schema；契约未定义
    condition 角色读路径；5 条 label-only 项同时在门高风险断言之外（未被回归防护）。
  - **F4（low）** NT-I22/NT-I33 近重复、NT-I25 评价性表述标为 fact、NT-I34 claim 携带 `condition`——
    非阻断人工裁定记录。
- 裁定结论：金标**含义健全**（`gold_meaning_sound=true`），问题在机读序列化与契约读路径；不得就地修改
  冻结金标或 Issue 28 门；**须另立修正票**；items-only 质量门**执行受阻**，阻塞条件为
  「在已签认契约中定义 condition 角色 proposition 读路径」+「评分契约完成签认」。
- **阻塞解除（2026-10-11）**：Issue 30 已按路线 A 落地——评分契约升级并签认为
  `non-table-selected-target-scoring-contract-v3`（`sha256:d9bc51f2…`，新增 `condition_role_read_path`），
  Issue 28 门再绑定至 v3 并把 `quality_requirements_status` 转为 `signed`、高风险断言补 5 条
  （门 `sha256:c6652591…`）。上述两项阻塞条件均已满足；金标与 freeze-state 字节未变。
  门仍处 `frozen_before_execution`，真实复验须另行授权。

## 关联

- 金标：Issue 10 `evidence/10-quality-gold-freeze-20261008-r2`（48-item 非表格冻结金标，xyl 签认）。
- 契约：`evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json`
  （审计时 `-v2` `draft_pending_human_review`；经 Issue 30 升级签认为 `-v3` `frozen_signed`）。
- 门：Issue 28 `evidence/28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate.json`
  （经 Issue 30 再绑定契约哈希并转 `quality_requirements_status=signed`）。
- 修正模式先例：Issue 23（relation 语义边界更正，后继冻结 + 保留 signed 原件）。

## Evidence

- `../evidence/29-items-gold-semantic-audit-20261010/README.md`
- `../evidence/29-items-gold-semantic-audit-20261010/r0-zero-call/findings.json`
- `../evidence/29-items-gold-semantic-audit-20261010/r0-zero-call/audit_items_semantic.py`

## 下一步（需用户裁定，本票不自动发起）

1. 缺陷修正路径已由用户裁定为**路线 A**（不改金标，补签契约并定义 condition 读路径），
   修正工作另立 Issue 30：[30 · items 评分契约补签与 condition 读路径定义](30-items-scoring-contract-condition-readpath.md)。
   - 路线 A：**补签契约并定义 condition 评分读路径**——不改金标，仅补契约条款与读路径；
   - 路线 B（未选）：**后继冻结归一化 6 条 condition 项**——Issue 23 模式，保留 signed 原件另立后继版本。
2. 修正票闭合（门阻塞项解除）后，再单独申请有界 items-only 真实复验授权
   （`attempts_max` = md 10 + docx 14 = 24、`concurrency = 1`，模型由用户指定）。
3. 本票不授权任何模型调用、发布或生产库访问。
