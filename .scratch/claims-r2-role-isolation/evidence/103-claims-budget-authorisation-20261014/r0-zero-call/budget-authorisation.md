# 治疗臂实跑预算授权（103 号）· 填写件

状态：**已由 U 给出数字，待具名**。`status = stated_effective_pending_countersignature`。
本件只做一件事：把 95/99 号 `budget_request.stage_1_live_run.requested_ceiling` 这一格（签认时留空、`filled_by: U`）的数字落成可核记录，供唯一活跑入口读取。

## 一、授权内容

| 项 | 值 |
|---|---|
| 上限 | **1,000,000 token** |
| 口径 | token（`total_tokens`，即 `prompt + completion`，与 ledger `attempts.usage` 同源） |
| 给出人 | U |
| 给出时间 | 2026-10-14（会话中给出） |
| 适用 | 仅 95/99 号治疗臂的阶段 1 实跑（两源一次全量抽取），不得挪作他轮 |

## 二、与签认件的关系

- 位置：99 号 `budget_request.stage_1_live_run.requested_ceiling`（现为 `null`，`filled_by: "U"`）；99 号 `a2d17440…` **字节不改**——已签件不得就地改，本件是它的落地记录。
- 逐 run 的 attempt 上限仍**逐字取自签认件**的 `historical_reference`：`claims-industrial-fulian` 10 次、`claims-optical-module` 14 次，合计 ≤ 24 次调用（本次冻结计划 scoped units 9 + 10）。
- 四条 hard_limits（签认件原文）：不得超 attempt ceiling 自动重试；不得换模型或换提供方；不得在运行中改判据或改提示词；不得跑第二个臂。

## 三、额度是否够（实测参照）

真实调用单次账（p1r3 live delta 两次调用，1 unit/次）：`total_tokens` = 4,698 / 4,798（其中 `reasoning_tokens` ≈ 2,655）。
本轮 19 个 unit ⇒ 约 19 次调用；按单次 5k–20k 估，约 **0.1M–0.38M token**，故 100 万 token 相对 24 次调用上限有 3–10 倍余量。
（历史 `p1-claims-gate-result.json` 只记 `model_calls = 17`，没有 token 账 ⇒ 本轮是第一次给出 token 口径授权。）

## 四、执行与判罚

- 执行入口在起跑前核验：签认件冻结 + 四条治疗规则齐 + 本件存在且 `ceiling_tokens > 0` + 冻结计划哈希 + profile 指纹 + `--allow-model`；
- 跑完后由 ledger `attempts.usage` 汇总 `total_tokens` 并与本上限对账，超限即判该轮无效并登记（不做自动重试）。

## 五、具名（可选；不签也按"已给出数字"执行）

若要以具名件形式落档，请在下面签署；签后由 `apply_budget_authorisation.py`（待建）把本件翻成已签记录并推进执行者的读取指针。

```
授权人（reviewer）：____________    核准人（adjudicator）：____________    日期：____________
```
