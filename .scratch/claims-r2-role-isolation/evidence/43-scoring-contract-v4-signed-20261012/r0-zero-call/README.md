# 契约 v4 · 已签认版（Issue 34 §7-11/§7-3/§7-6/§7-7/§7-12）

- 签署人：**xyl**　日期：**2026-10-12**
- 签署工具：`.scratch/claims-r2-role-isolation/evidence/45-contract-v4-draft-20261012/r0-zero-call/contract-v4-review.md` `sha256:753532e8074aa0bf8a9f9cddf2b0e97b9b19519ed95b154407fdfac2e6c0ccd7`
- 产物：`scoring-contract-v4.json`（`status = frozen_signed`）
- 取代：契约 v3 `d9bc51f2…`（v3 字节不变，留存可追溯）

## 已签的裁定

| 项 | 选择 | 效果 |
|---|---|---|
| OPEN-1 | **A** | 门 28 为单一口径；评分器须改为读契约（未执行） |
| OPEN-2 | **C** | material_relations 本轮不纳入评分（显式披露） |
| FORCED-1 | **以金标口径为准、读时归一化（由 §8 硬约束推定）** | 由 §8 硬约束推定 |

## 与并行草案的关系

- 并行草案：`.scratch/claims-r2-role-isolation/evidence/41-items-chain-accounting-20261012/r3-signoff-apply/scoring-contract-v4.proposed.json`（`sha256:b3f88649e9eca70cf21b95c466ea4a4950ef6a316aa521e2b42822c4eae7818f`，状态 `proposed_pending_signoff`）
- 关系：superseded_by this signed contract（其签认栏为空，从未签认）

| 并行节 | 映射到 | 未对账叶子路径 | 结论 |
|---|---|---|---|
| `items_field_carrier_read_path` | `read_path` | 14 | UNRECONCILED_CONTENT_PRESENT |
| `threshold_single_source` | `threshold_source` | 9 | UNRECONCILED_CONTENT_PRESENT |

## 签认之后仍未完成的（不得读成已过门）

- 评分器读契约/阈值对齐（§7-6 C3）：代码改动，未执行
- 金标冻结链契约绑定再绑定（v2→v3→v4）：须与本次签认同轮落地
- 口径归一化（caliber_rules）的实现与回归测试（§7-7 A1/A2）：未执行
- route a/b 边际裁定与缺口 1/2：仍缺（§5.12）

> 本次签认只签契约条款；**不等于** items-only 真实复验通过，也不等于门 33 出分。
