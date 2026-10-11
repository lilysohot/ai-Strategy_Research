# 32 · items selector v6 与执行配置重冻结（零调用预注册）

Status: executed（零调用冻结 + 双臂真实执行完成；treatment 结构性未过门，见 §11）
Type: gate task
Parent: [28 · items-only 质量门预注册](28-items-only-quality-gate-preregistration.md)、
[31 · run-1 突增保护失效与模型替换](31-run1-429-invalidation-model-substitution.md)
Model attempts: 0（尚未授权；本文件为零调用预注册）
Production database access: 0

## 1. 问题

28/31 关闭的路线暴露两个可归因位点，且都属**我方契约/配置缺陷**，与模型能力无关：

- **L2 prompt/规格**：`MATERIAL_SELECTOR_PROTOCOL` 同句要求 `record_type="obligation_result"`，却在
  「字段只能是」白名单里排除它；校验器/解析器要求恰好五字段（含 `record_type`）。两种读法皆可辩护，
  仅一种被接受。run-2 因该歧义整篇省略标签 → 98 条 obligation 记录 / 148 条已成形 item 被整批丢弃。
- **执行配置**：冻结配置使用 `reasoning_effort="minimal"`（DeepSeek 兼容映射为 `low` = 思考开启），
  run-2 输出 token 中 reasoning 占 72%（md 76,301/105,317）与 77%（docx 148,731/192,964）。

## 2. 已落地的零调用修正（本门所验对象的定义）

### 2.1 items selector v6（协议）

- `MATERIAL_SELECTOR_PROTOCOL_V6`：白名单由单一事实来源 `_SELECTOR_RESULT_FIELD_ORDER` 渲染（含
  `record_type`）+ 一条合法 `no_supported_item` 示例行；`_SELECTOR_RESULT_FIELDS` 同源派生。
- v5 文本字节不变（原常量保留为 `MATERIAL_SELECTOR_PROTOCOL_V5`，旧名 `MATERIAL_SELECTOR_PROTOCOL`
  仍指向 v5）；`MATERIAL_SELECTOR_JSONL_VERSION` 默认仍为 v5。v6 只改请求侧 prompt，
  **响应契约、严格校验器、解析器完全未放宽**（缺标签仍整批拒）。
- 登记点同步：`structured/roles.py`（`RoleArtifact.protocol` Literal、items 可执行协议集、上游 items 白名单）、
  `structured/cli.py`（`--material-items-protocol` choices）。
- 常驻测试（`tests/test_corpus_material_semantics.py`）：字段同源、每个 selector prompt 白名单覆盖其
  校验器、v5 缺口锁定为 `{"record_type"}`、缺标签在 `_strict_role_llm` 与 `_parse_selector_response`
  下仍 fail-closed、默认 prompt 仍是 v5、v6 端到端走通、prompt 仅协议头不同。

### 2.2 执行配置装配（transport）

- `RequestOptions` 增 `thinking: Literal["enabled","disabled"] | None`（发 `{"type": ...}`），与
  `reasoning_effort` **互斥**（`model_validator` fail-closed）；适配器发送并写入诊断 `thinking`。
- CLI `plan` / `execute` 同时获得 `--reasoning-effort` / `--thinking` / `--max-output-tokens`，
  由 `_request_options()` 组装；未显式给出时完全不构造（默认行为、既有 plan 复跑均不变）。
  两个命令共用同一组参数，保证 plan 冻结的 `request_options` 与 execute 校验的 profile 指纹一致。
- 常驻测试：`tests/test_corpus_structured_config.py`（thinking 形状、`reasoning_effort=none`、
  互斥拒绝、指纹随选项变化）、`tests/test_corpus_structured_cli.py`（plan 冻结 options、互斥报
  `CS_INPUT_INVALID`）。

## 3. 目标

在**同一代码、同一快照、同一模型、同一并发与节流**下做双臂对照，验证「v6 + 关闭思考」是否把
「协议违规 → 整批作废」降到 0，并满足执行要求（质量评分不在本门，见 §6）。

## 4. 执行设计（双臂，单臂不可归因）

| 臂 | 协议 | 传输配置 | 作用 |
| --- | --- | --- | --- |
| control | `material-atomic-selector-jsonl-v5` | 不传 reasoning 开关（复现 28/31 条件） | 复现当前失效形态 |
| treatment | `material-atomic-selector-jsonl-v6` | `--thinking disabled`（或 `--reasoning-effort none`，二选一） | 本门所验修正 |

- 模型以 `.env` 现值为准（`STRUCTURED_EXTRACTION_MODEL`），门冻结时须逐字登记；`base_url` 为
  `https://api.deepseek.com`，端点仍为 `/chat/completions`。
- 快照与槽位沿用 28 的确定性重建（md 10 unit/76 槽/attempts_max=10；docx 14/114/14）。
- 节流、并发 1、零自动重试：与 run-2 相同（间隔 20s）。

## 5. 预注册退出判据（执行要求先行）

通过（treatment 臂）须**同时**满足：

1. 每源 attempts 实际值 = 计划值（md 10 / docx 14），无自动重试，无 HTTP 429；
2. `protocol_status == "valid"`，failed / partial / invalid / duplicate 批次数均为 0；
3. 每源 `completed_min`：md ≥ 10、docx ≥ 14；槽位 `extracted + no_supported_item` 覆盖该源全部槽位；
4. `execution_status == "succeeded"`、`context_status == "complete"`；
5. 关闭思考的**硬证据**：`usage.completion_tokens_details.reasoning_tokens` 为 0 或字段缺失
   （若该字段仍有大量 reasoning token，则判定「配置未生效」，不得宣称省 token）；
6. control 臂必须复现失败（否则说明对照条件不成立，不得据此宣称修复有效）。

不通过时的归属：仍出现「整篇一致省略 `record_type`」→ 归模型行为，但须先排除第 5 条与配置未生效；
先按根因层判定，不回流本门之外的改动。

## 6. 范围外／不做

- 不做质量评分（target recall / precision / 16 条高风险断言）——属下游质量门，须另立；
- 不做 publication、positive_query / delivery / context_use / report_reference；
- 不启用 `response_format` / `text.format`（形态与 NDJSON 冲突，且不解决字段缺失）；
- 不改金标（48-item）、不改阈值、不改评分契约 v3、不动 relation/claims；
- 不放宽严格校验/解析的 fail-closed 行为；不改 v5 prompt 字节。

## 7. 授权待填项（本门自身不授权任何行为）

| 项 | 授权人 | 日期 | 参数 |
| --- | --- | --- | --- |
| `items_live_extraction` |  |  | attempts_max md=10 / docx=14；model=；节流= |
| `publication` |  |  | —（默认 false） |
| `positive_query_delivery_context_use` |  |  | —（默认 false） |
| `production_database_access` |  |  | —（默认 false） |

## 8. 报分口径

- 本门只报**执行要求**（协议/执行/上下文状态、批次与槽位计数、token 与 reasoning 占比）；
- 不得把本门的结构通过表述为「质量达标」；质量分须在另立的质量门内、按生产默认口径报。

## 9. 关联

- 根因归因：`../evidence/28-items-only-quality-gate-20261010/r2-live/run2-error-attribution.json`
- 违规逐条分类：`.../r2-live/run2-protocol-violations.json`
- 终态记录：`.../r2-live/run2-final-decision.json`
- 代码改动：`plugins/corpus/material_semantics.py`、`plugins/corpus/structured/{roles,cli,config,adapter}.py`
- 常驻测试：`tests/test_corpus_material_semantics.py`、`tests/test_corpus_structured_{config,cli}.py`

## 10. 签认栏

- 复核人：xyl　日期：2026-10-11
- 结论： 准予执行（按 §7 填授权）　☐ 退回修改

## 11. 执行结果（2026-10-11）

**零调用冻结**：`r0-zero-call/freeze_two_arms.py` → `freeze-manifest.json`
`sha256:1a0e008a…`、`preregistered-gate.json` `sha256:6fb47e79…`；`verify_two_arms.py`
零调用核验 **56/56 通过**（`verification-summary.json.status = verified_zero_call`，模型调用 0、生产库访问 0）。

**授权依据（诚实登记）**：§7 授权表**未填写**；`gate.authorization.items_live_extraction` 依据 §10 具名
签认（复核人 xyl、2026-10-11、准予执行）与用户 2026-10-11 的明确指令「已经签认，可执行」，参数**逐字取自
§4/§5 与 `.env` 现值**（model `deepseek-flash`、attempts max md=10/docx=14、节流 20s、并发 1、零重试），
未由实施方自行裁量；其余三项授权保持 false。此差异已写入 `gate.authorization.basis` 供复核。

**真实执行**（每臂 24 次调用，20s 节流，并发 1，零自动重试；两臂模型/快照/槽位/预算一致）：

| 臂 | 协议 | 思考开关 | attempts | reasoning_tokens | 协议违规批次 | 槽位 failed | items |
| --- | --- | --- | --- | --- | --- | --- | --- |
| control | `…selector-jsonl-v5` | 未设置（provider 默认＝开） | 10 + 14 | 352,006 | 3 + 8 = **11** | 22 + 60 = 82 | 80 + 66 = 146 |
| treatment | `…selector-jsonl-v6` | `thinking="disabled"` | 10 + 14 | **0** | **0 + 0 = 0** | 7 + 2 = 9 | 88 + 134 = 222 |

- **判据 5 满足**：treatment `reasoning_tokens = 0`（control 352,006）→ 关闭思考的配置确实生效。
- **判据 6 满足**：control 复现 v5 失效（11 个批次 `ValueError: role response contains an unsupported
  JSONL record`，与 Issue 28/31 同形态）。
- **根因位点已消除**：treatment 零次同类协议违规。

**终态判定：`structural_fail`（未过门）**，未满足 4 项：`protocol_status == valid`、批次
failed/partial = 0、`completed_min`、`execution_status == succeeded`。原因与协议修复无关：

1. `industrial-fulian-md`：1 次 `TransportOutcomeUnknown`（零重试、不重发）→ 该批 7 槽 failed、
   packet partial（9/10 completed）、任务 `outcome_unknown`；为独立基础设施事件，与 Issue 31 run-2 同形态。
2. `optical-module-docx`：2 个槽位被控制器语义判定拒绝（`controller_semantic_validation_failed`
   伴随 `missing_signal:*` / `commentary_only`）→ packet partial（13/14 completed）、任务 `failed`；
   属 fail-closed 的语义判定，非 JSONL 格式违规。

**token 效果（treatment vs control）**：completion 377,293 → 21,905（**-94.2%**）；
reasoning 352,006 → 0；total 429,020 → 72,808（**-83.0%**）。

**证据**（全部保留，未删除）：`../evidence/32-items-v6-reasoning-refreeze-20261011/`
`r0-zero-call/{freeze-manifest,preregistered-gate,verification-summary}.json`、
`live/{control-run-summary,treatment-run-summary,post-run-check,gate-decision,candidates}.json`、
四个独立 store（`control-store/{md,docx}`、`treatment-store/{md,docx}`）。

**归因边界**：本门只报执行要求，不宣称质量达标（§8）；v6 的结论限定为「消除 L2 协议缺陷」。
剩余未过门项分别是基础设施事件与语义层判定，继续推进须另立门（语义层/重试策略/质量评分）。


