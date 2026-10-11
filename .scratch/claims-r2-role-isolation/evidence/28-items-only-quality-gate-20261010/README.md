# Issue 28 · items-only 质量门预注册（零调用冻结）

Status: frozen_before_execution（冻结态；执行记录见 §12）
Model calls: 冻结/核验 0；执行 run-1 24（失效）+ run-2 24（结构性未过门）
Production database access: 0

本目录在**不发起任何真实模型调用**的前提下，冻结 items-only 质量门 + items-only 正向消费闭环的
计划、金标口径、阈值提案、消费链口径与授权待填项。它只做预注册，不授权任何执行；所有真实调用
（若有）须在用户单独授权后进行。

## 1. 目的与范围

- 角色范围固定为 `material_items` 单角色；`claims` 与 `material_relations` 的执行次数均为 0。
- 这是 R2 关闭 relation 修复后的「下一阶段」：只处理 material_items 质量门及其 items-only 正向
  消费闭环（见 `../../spec.md` L117-118）。
- 本阶段不声称任何 publication、query/delivery/context_use、生产化已完成。

## 2. 协议与金标口径

- items 协议：`material-atomic-selector-jsonl-v5`（当前默认 selector 抽取器）。
  相关版本：extractor `material-semantics-32`、items 校验 `material-items-validation-v11`、
  槽切批 `material-slot-batching-v3`；`relations_default_off = true`。
- 金标：Issue 10 冻结的 48-item 非表格金标（`10-quality-gold-freeze-20261008-r2`），
  签认人 reviewer/adjudicator = `xyl`。冻结分母为 `claims 20 / material_items 48 / material_relations 24`，
  本票只消费其中的 `material_items = 48`。
- 评分口径：`non-table-selected-target-scoring-contract-v3`（2026-10-11 依 Issue 30 路线 A 由 v2 升级签认；
  冻结当时绑定的是 v2 `draft_pending_human_review`），评估范围为
  **`selected_target_recall_not_exhaustive_document_gold`**——金标是有限目标集，不宣称整篇穷尽；
  额外正确的输出单列 `correct_extra`；存在未裁定候选时 precision 记为 N/A。
- 金标不得暴露给模型：plan 的 unit metadata 带 `gold_not_exposed_to_model = true`。

### 冻结输入哈希

| 输入 | sha256 |
| --- | --- |
| frozen-gold.json | `sha256:603de5e6…dfa7de2` |
| freeze-state.json | `sha256:08703b8d…9b237d85` |
| freeze-manifest.json | `sha256:da85e293…23632b23e` |
| scoring-contract.json | `sha256:d9bc51f2…5b75a7ce`（v3，2026-10-11 再绑定；冻结时为 v2 `sha256:2eb24be7…498f3bdbe`） |
| source-prose-units.json | `sha256:58aa7c99…048a37436` |

## 3. 确定性重建的两份来源

按 `run_frozen_non_table_gold_trial_r2.py` 的快照构建逻辑重建，无时间戳字段，故快照/计划哈希可确定性复现。

| slug | unit 数 | candidate 槽 | material_items attempts_max | snapshot_id |
| --- | --- | --- | --- | --- |
| industrial-fulian-md | 10 | 76 | 10 | `sha256:d6546966…18bac055` |
| optical-module-docx | 14 | 114 | 14 | `sha256:7d8f27c8…a7fa7195` |

- 批次按 packet 边界切分（遇 `slot.packet_id` 变化即断批），受 slots=24 / items=64 / tokens=8192 三重容量约束；
  因候选槽按 packet 连续，全局调用等价于逐 packet 调用，故 md=10 批、docx=14 批。
- `role_max_attempts` 恰含三键（claims=0 / material_items=n / material_relations=0），`relations.enabled=false`。

## 4. 冻结产物

- `r0-zero-call/freeze_items_only_plan.py`：零调用冻结脚本（重建快照 + `plan_batch` + 落盘 gate/manifest）。
- `r0-zero-call/verify_items_only_plan.py`：零调用复验脚本（哈希/身份/scope/预算可复现性）。
- `r0-zero-call/plan-industrial-fulian-md.json`、`r0-zero-call/plan-optical-module-docx.json`：两份冻结 plan。
- `r0-zero-call/preregistered-gate.json`：预注册门（`items-only-quality-gate-preregistration-1`）。
- `r0-zero-call/freeze-manifest.json`：冻结清单（输入与产物字节哈希、零调用断言）。
- `r0-zero-call/verification-summary.json`：复验摘要（`status = verified_zero_call`，`reproducible = true`，
  `model_requests_during_verification = 0`）。

## 5. 执行要求（若获授权）

- `claims_attempts = 0`、`material_relations_attempts = 0`、`automatic_retries = 0`、`concurrency = 1`。
- `protocol_status` 必须 `valid`、`execution_status` 必须 `succeeded`、`context_status` 必须 `complete`。
- failed / partial / missing / duplicate / invalid 批次上限均为 0。
- per-source：md attempts_max=10 / completed_min=10；docx attempts_max=14 / completed_min=14。

## 6. 质量门（阈值已签认）

`quality_requirements.status = signed`——以下阈值原为提案，已随评分契约 v3 于 2026-10-11 一并签认
（原值 `proposed_pending_human_signoff`），且**一经冻结不得按执行结果反向放宽**：

- `target_recall_overall_min = 0.85`；`target_recall_per_source_min = 0.80`。
- `candidate_precision_min = 0.80`；`unresolved_candidates_max = 0`。
- `accepted_records_total_min = 40`；`accepted_records_per_source_min = 20`。
- 另有由契约派生的必需字段、语义类型、话语角色、视角枚举，以及 16 条高风险 item 断言
  （NT-I09/13/15/17/19/29/35/37/38/39/42/43/45/46/47/48）必须在输出中成立
  （2026-10-11 由 11 条扩充，补入 label-only condition 项 NT-I09/I19/I29/I35/I39）。

## 7. items-only 正向消费闭环（5 阶段）

链：`publish → positive_query → delivery → context_use → report_reference`。

- 零调用阶段：`publish`、`positive_query`——可在无模型调用下验证（稳定 item id、逐字 evidence span、
  已知真谓词的正向查询至少命中一条且证据指针正确）。
- 需授权真实路径的阶段：`delivery`、`context_use`、`report_reference`——须经授权的 live path。
- 断言边界：`proves the tested scope is connected only, not full coverage`
  （只证明受测范围接通，不宣称完整覆盖）。

## 8. 授权待填项（本门自身不授权任何行为）

`authorization` 四项全部 `authorized = false`，须由人工逐项显式填写后才可执行：

1. `items_live_extraction`：授权人 / 日期 / `attempts_max` / `model`。
2. `publication`：授权人 / 日期。
3. `positive_query_delivery_context_use`：授权人 / 日期。
4. `production_database_access`：授权人 / 日期。

## 9. 终止规则

- `on_pass`：items-only 质量门满足 → 进入**已授权**的正向消费闭环。
- `on_fail`：关闭当前「模型 + extractor」路线；**不放宽阈值、不改 prompt、不新增金标**。
- scope 约束：`new_gold_allowed=false`、`threshold_relaxation_after_execution_allowed=false`、
  `prompt_revision_after_execution_allowed=false`、`protocol_or_extractor_change_after_execution_allowed=false`、
  `holdout_accessed=false`。

## 10. 复验结果（冻结时点记录；已被执行超越）

> **注（2026-10-11）**：本节及 `verification-summary.json` 为冻结时点的零调用输出——其
> 「授权全 false、签认 pending」断言已被门 revision 3/4 超越（授权已填写并签认、模型已替换，
> 两轮执行与终态见 §12）。JSON 保留原样作为当次输出，不再代表当前状态。

`verify_items_only_plan.py` 零调用通过：manifest 字节哈希与磁盘一致、plan `verify_identity()` 通过、
`enabled_roles == ("material_items",)`、`relations.enabled == False`、`role_max_attempts` 三键、
任务计数 0/1/0、`material_items_options == 64/24/8192`、`gold_not_exposed_to_model is True`、
scope locators 与评分契约一致、批次预算可确定性复算、gate 计数 20/48/24、授权全 false、签认 pending。

## 11. 下一步（已终结）

本预注册已执行并终结：run-1（doubao-seed-2.1-lite）因方舟突增保护 429 失效；run-2
（deepseek-v4-flash）结构性未过门；经用户确认按冻结终态关闭本门所验「模型 + extractor」路线
（详见 §12 与 `../../issues/28-…md`、`../../issues/31-…md`）。后续任何新模型、新协议或归因实验
路线须**另立新门**并经新的显式授权；本门不得再执行、不得放宽阈值、不改 prompt、不新增金标。

## 12. 执行记录（2026-10-11）

### run-1（`r1-live/`）— 基础设施失效

- 门 rev 3 授权（xyl；doubao-seed-2.1-lite；attempts 10+14；零重试；并发 1；无节流）。
- 24 次尝试：md #01–#08 返回响应（HTTP 200、`finish_reason=stop`、30,407 tokens；其中
  **6 次格式完全合规、2 次违反严格 JSONL 校验**——见 `r1-live/run1-protocol-compliance.json`）；
  md #09–#10 与 docx #01–#14 共 **16 次被 HTTP 429 瞬时拒绝**（~180ms、零 token）——
  方舟「突增流量保护」（`RequestBurstTooFast`，seed-2.x 系列；配额未必耗尽）。
- 判定：基础设施失效、不触发 on_fail；证据保留（`r1-live/live-store`、
  `live-run-summary.json`、`pre-execution-verification.json` 86 项零调用核验）。

### run-2（`r2-live/`）— 模型替换后结构性未过门

- 门 rev 4（`sha256:987772e9…`，用户指示更换模型，节流 20s）；`r2-live/replan-manifest.json`
  零调用重冻结（快照/槽位/预算不变、attempts 仍 10/14、profile `033e5f19…`）；
  `r2-live/pre-execution-verification.json` 78 项零调用核验通过。
- 24 次尝试全部发出（无 429、零重试、并发 1）：23 次响应、1 次 `TransportOutcomeUnknown`；
  **12/23 响应违反冻结 selector JSONL 严格校验**（记录缺 `record_type`、类型被写入
  `status:"items"`）；13/24 批次 partial、107/190 槽位失败；execution/protocol 不达门。
- 后置零调用核查：`r2-live/post-run-check.json`（门执行要求 11 项 unmet）；
  `r2-live/run2-protocol-violations.json`（违规逐条分类）；`r2-live/run2-candidates.json`（候选清单）。
- **终态**：`r2-live/run2-final-decision.json` — 按冻结 `terminal_decision.on_fail` 关闭本路线
  （用户确认登记关闭）；不做质量评分（执行要求先行未过）；全部证据保留。
