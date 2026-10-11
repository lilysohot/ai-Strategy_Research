# 31 · run-1 突增保护失效与模型替换重跑（deepseek-v4-flash）

Status: complete
Type: task
Parent: [28 · items-only 质量门预注册](28-items-only-quality-gate-preregistration.md)
Model attempts: run-1 24（16×429 失效、零 token）；run-2 24（deepseek-v4-flash，12/23 响应违反严格校验、1 次传输未知）
Production database access: 0

## 问题

按门 revision 3 授权执行的有界 items-only 真实复验（run-1，模型
`doubao-seed-2.1-lite`、attempts 10+14、并发 1、零自动重试、无节流）出现**基础设施失效**：

- `industrial-fulian-md`：attempt #01–#08 全部成功（HTTP 200、`finish_reason=stop`、
  耗时 4.3–22.7s、累计 30,407 tokens）；#09、#10 被 HTTP 429 瞬时拒绝（~180ms、零 token）。
- `optical-module-docx`：14 次尝试**全部** HTTP 429 瞬时拒绝（176–250ms、零 token）。
- 合计 24 次尝试中 16 次 429，均未触达模型（usage 为空）。
- **补记（零调用复扫，2026-10-11）**：`#01–#08` 的 8 次成功响应中 **6 次完全合规、2 次违反同一严格
  JSONL 校验**（记录缺 `record_type`，与 run-2 违规同形态），对应 partial 包 `eeff713f`（3 槽）与
  `0f22fc72`（9 槽）；跨模型对照 doubao 2/8（25%）vs deepseek 12/23（52%），详见
  `r1-live/run1-protocol-compliance.json`。此前「8 次成功」未细分格式合规性，本补记予以细化。

依据方舟官方文档（突发流量处理/接入 FAQ）：seed-2.0 及之后模型的 429
`RequestBurstTooFast` 为「请求量激增触发系统保护，请放缓流量提升速度，逐步增加请求量」，
且**配额未必耗尽**。run-1 的时间线与之吻合：8 次匀速成功调用后，尾随的 2 次 + docx 的
14 次在数秒内密集发出，整体触发突增保护。

**判定**：429 拒绝未触达模型，不构成模型/抽取器质量证据，**不触发门 `terminal_decision.on_fail`**
（该终态面向质量失败、且禁止放松阈值/改金标）；run-1 全部证据保留，不删除、不改写。

## 用户裁定与授权（2026-10-11）

- 「**模型我已经更换，重新尝试请求模型**」：授权将执行模型更换为 **`deepseek-v4-flash`**
  （base_url `https://api.deepseek.com`，用户已在 `.env` 完成配置）。
- 节流标准：「**标准：间隔 20s**」：首叫前 20s、此后每叫间隔 20s；实现为
  `checkpoint("after_reserve")` 发送前等待（**是节流，不是重试**，自动重试仍为 0）。
- `.env` 最小修正披露：用户新增的 `STRUCTURED_EXTRACTION_BASE_UR` 缺尾字母 `L`
  （loader 仅读 `STRUCTURED_EXTRACTION_BASE_URL`，导致 `configured=false`）；agent 依既定
  意图单字符修正为 `STRUCTURED_EXTRACTION_BASE_URL=https://api.deepseek.com`，
  `.env` 其余内容未动。

## 已完成（零调用部分）

- **门 revision 4**（`r0-zero-call/preregistered-gate.json`，哈希 `987772e9…`）：
  记录 run-1 失效与模型替换（`authorization.items_live_extraction.model=deepseek-v4-flash`）；
  **阈值、金标、评分契约 v3 绑定、协议/抽取器版本、执行要求其余项与终态判定均未改动**。
  `freeze-manifest.json` 增补 revision 4 条目并同步门哈希。
- **r2 零调用重冻结**（`r2-live/replan-manifest.json`）：新模型 `profile_sha256=033e5f19…`；
  快照与槽位不变（md `d6546966…`/76 槽、docx `7d8f27c8…`/114 槽）；
  attempts 仍 10/14；新 batch id md `a3d44516…`、docx `2a632e87…`。
- **r2 前置零调用核验**（`r2-live/pre-execution-verification.json`）：78 项全过——
  四步修订链完整、run-1 证据哈希一致（`1c7eab9c…`）、计划/预算/批次数（10/14）/
  逐 locator 一致、金标隔离标记、endpoint 校验通过、门四项授权仅 items 一项为真。
- **request_options 逐字沿用**：timeout 300 / max_output_tokens 262144 /
  token_parameter `max_tokens` / reasoning_effort `minimal`。DeepSeek 官方文档明确
  `minimal` 被接受并映射 `low`；`max_tokens` 262144 在合法区间 [1, 384K] 内。

## 尝试预算会计

| 轮次 | 模型 | 尝试上限 | 实际 | 备注 |
| --- | --- | --- | --- | --- |
| run-1 | doubao-seed-2.1-lite | 24 | 24（8 成功 + 16×429） | 基础设施失效，证据保留 |
| run-2 | deepseek-v4-flash | ≤24 | 24（11 合规响应 + 12 违规 + 1 传输未知） | 结构性未过门，证据保留 |

两轮累计真实请求 48 次（24 + 24）；阈值/金标/协议与此前冻结完全一致。

## run-2 执行结果（2026-10-11，deepseek-v4-flash，20s 节流）

- 24 次尝试全部发出：无 429、零重试、并发 1；23 次收到响应（HTTP 200、`finish_reason=stop`），
  1 次传输结果不明（`TransportOutcomeUnknown`，15.0s，按契约不自动重发）。
- **12/23 响应违反冻结 selector JSONL 严格校验**（`_strict_role_llm`）：记录缺 `record_type`、
  记录类型被写入 `status:"items"`（键集 `{items, obligation_index, reason_code, status}`，共 98 行记录）
  → 整批 ValueError、该批槽位全部 failed；合规响应仅 11/23。逐条分类见
  `r2-live/run2-protocol-violations.json`（原始响应对象保留于 live-store/objects）。
- 结构后果：包级 md 3 completed / 7 partial、docx 8 / 6；槽位 md 18 extracted + 2 no_supported_item +
  56 failed（76 槽）、docx 61 + 2 + 51（114 槽）；任务 execution = outcome_unknown（md，因传输未知）/
  failed（docx），protocol = not_checked；omitted_areas 7 / 6。
- 产出（仅完成批）：items 31（md）+ 80（docx）= 111 条；用量 md 105,317 tokens（reasoning 76,301）、
  docx 192,964（reasoning 148,731）——`minimal` 经 DeepSeek 官方映射为 `low` 即思考模式。
- 后置零调用核查：`r2-live/post-run-check.json` → 门执行要求 **11 项 unmet（结构性未过门）**；
  候选清单 `r2-live/run2-candidates.json`。

## 终态（经用户确认，2026-10-11）

按门冻结 `terminal_decision.on_fail` 关闭本门所验「模型 + extractor」路线（run-2 deepseek-v4-flash
组合；run-1 doubao 组合因 429 失效未取得有效结果）：**不放宽阈值、不改 prompt、不新增金标**。
质量评分（target recall / precision / 16 条高风险断言）因执行要求先行未过而不再执行，原因记录于
`r2-live/run2-final-decision.json`。run-1/run-2 全部证据（两个 live-store、原始响应对象、槽位台账）
保留不删。后续任何新模型、新协议或归因实验路线须**另立新门**并经新的显式授权。

## Evidence

- `../evidence/28-items-only-quality-gate-20261010/r1-live/live-run-summary.json`（run-1 失效记录）
- `../evidence/28-items-only-quality-gate-20261010/r1-live/live-store/`（run-1 全量尝试与诊断）
- `../evidence/28-items-only-quality-gate-20261010/r1-live/run1-protocol-compliance.json`（run-1 响应合规复扫与跨模型对照）
- `../evidence/28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate.json`（rev 3/4）
- `../evidence/28-items-only-quality-gate-20261010/r2-live/replan-manifest.json`
- `../evidence/28-items-only-quality-gate-20261010/r2-live/pre-execution-verification.json`
- `../evidence/28-items-only-quality-gate-20261010/r2-live/live-run-summary.json`（run-2 结果）
- `../evidence/28-items-only-quality-gate-20261010/r2-live/post-run-check.json`（后置核查）
- `../evidence/28-items-only-quality-gate-20261010/r2-live/run2-protocol-violations.json`（违规分类）
- `../evidence/28-items-only-quality-gate-20261010/r2-live/run2-final-decision.json`（终态与哈希）

## 下一步

- [x] 执行 run-2（完成，结构性未过门）
- [x] run-2 运行后零调用核查（post-run-check + 候选清单 + 违规分类）
- [x] 门判定与终态登记（用户确认关闭本路线；Issue 28 已同步终结）
