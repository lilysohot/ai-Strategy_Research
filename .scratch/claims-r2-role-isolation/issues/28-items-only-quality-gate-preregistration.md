# 28 · items-only 质量门零调用预注册

Status: open
Type: task
Parent: [10 · 评分、标注范围与质量门冻结](10-quality-gates.md)、[17 · 结构化提取收敛闭环与最终去留门](17-structured-extraction-convergence-closure.md)
Model attempts: 0（零调用冻结与复验）
Production database access: 0

## 问题

R2 关闭 relation 修复与验收后，`spec.md` 明确「下一阶段只处理 material_items 质量门及其 items-only
正向消费闭环」（L117-118）。但当前存在两项真实缺口：

- Issue 10 冻结的 48-item 非表格金标从未用当前 `material-atomic-selector-jsonl-v5`（Issue 18 替换后的
  extractor）复验。
- items-only 正向消费闭环（publish → positive_query → delivery → context_use → report_reference）
  的完成度为 0。

直接发起真实调用会绕过预注册纪律；因此须先把计划、金标口径、阈值、消费链口径与授权待填项
**零调用冻结**为预注册门，再单独申请有界真实复验。

## 目标

在不发起任何真实模型调用的前提下，冻结 items-only 质量门：

- 用 selector-v5 协议、单角色 `material_items` 规划两份已签认非表格来源，产出确定性可复现的冻结 plan。
- 以 Issue 10 冻结的 48-item 金标为验收分母，冻结执行要求、质量阈值提案、5 阶段消费闭环口径与终止规则。
- 形成预注册门与授权待填项，使后续真实复验只能在本门约束内、且经人工逐项授权后进行。

## 边界与约束

- 不动 relation、不改 claims；`claims_attempts = 0`、`material_relations_attempts = 0`。
- 不修改或取代 Issue 10 已签认金标；不新增金标（`new_gold_allowed = false`）。
- 不发布、不写生产库；`publication` / `query_delivery_context_use` / `production_database_access` 均不授权。
- 阈值、prompt、协议/extractor 一经冻结，不得按执行结果反向放宽。
- 预注册门自身不授权任何行为；授权四要素须由人工显式填写。

## 执行结果

- 零调用确定性重建两份来源快照：`industrial-fulian-md`（10 unit / 76 槽 / attempts_max=10）、
  `optical-module-docx`（14 unit / 114 槽 / attempts_max=14），source_id 与 r2 产物一致。
- 以 selector-v5 规划 items 单角色：`role_max_attempts` 恰含三键、`relations.enabled=false`、
  `material_items_options = 64/24/8192`；批次按 packet 断批，任务计数 0/1/0。
- 冻结 `preregistered-gate.json`（schema `items-only-quality-gate-preregistration-1`）与
  `freeze-manifest.json`；`quality_requirements` 与 `countersignature` 均为 pending。
- 零调用复验通过：`status = verified_zero_call`、`reproducible = true`、
  `model_requests_during_verification = 0`、授权全 false。
- 冻结/复验期间模型调用 0、生产库访问 0、holdout 访问 false。
- **契约再绑定（2026-10-11，Issue 30 路线 A）**：评分契约升级签认为
  `non-table-selected-target-scoring-contract-v3` 后，门 `gold.scoring_contract_sha256` 再绑定至 v3、
  `quality_requirements.metric_basis` → `-v3`、`quality_requirements_status` → `signed`、
  高风险断言清单补 5 条（NT-I09/I19/I29/I35/I39）。门阈值、执行要求、授权四项与终态判定均未变；
  冻结金标与 freeze-state 字节不变。新门哈希 `sha256:c6652591…`（旧 `sha256:7cf87208…` 留存于门 `revision_history`）。
  门仍处 `frozen_before_execution`，真实复验须另行授权。

## 关联

- 金标：Issue 10 `evidence/10-quality-gold-freeze-20261008-r2`（48-item 非表格冻结金标，xyl 签认）。
- 协议来源：Issue 18 material extractor 替换（selector-v5 默认）。
- 消费闭环定义：Issue 17 P2 正向消费。
- 阶段声明：`spec.md` §3 L117-118。

## Evidence

- `../evidence/28-items-only-quality-gate-20261010/README.md`
- `../evidence/28-items-only-quality-gate-20261010/r0-zero-call/`

## 下一步（需独立授权，本票不自动发起）

申请一次有界 items-only 真实复验：`attempts_max` = md 10 + docx 14 = 24、`concurrency = 1`，
模型须由用户指定；仅在用户明确授权后执行，且不得放宽阈值、不改 prompt、不新增金标。
