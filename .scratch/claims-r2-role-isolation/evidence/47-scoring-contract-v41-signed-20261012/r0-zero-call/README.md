# 契约 v4.1 · 已签认版

- 签署人：**xyl**　日期：**2026-10-12**
- 签署工具：`.scratch/claims-r2-role-isolation/evidence/46-contract-v41-draft-20261012/r0-zero-call/contract-v4.1-review.md` `sha256:1d01218210388acf49f7c15a41301631d0631db6b1cf5e6e87ecc1ccf3b94bdc`
- 产物：`scoring-contract-v4.1.json`（`status = frozen_signed`）
- 取代：已签 v4 `sha256:6806f1399e3bbf5ace41264598f6228998f706dd082f20d580d5303a48ab712d`（字节不变，留存可追溯）

## 已签的裁定（沿用）

| 项 | 选择 |
|---|---|
| OPEN-1 | A（门 28 为单一口径 0.85/0.80/20；评分器须改为读契约——代码未改） |
| OPEN-2 | C（material_relations 本轮不纳入评分） |
| FORCED-1 | 以金标口径为准、读时归一化（由 §8 硬约束推定） |

## 备注为空的处理（显式记录）

- 备注为空。两处 open_for_reviewer 项（R-1/R-2）因此按**原样接受**处理；这是对空备注的解释，已显式记录，不视为对具体条文的逐条确认。

| ID | 项 | 处置 |
|---|---|---|
| R-1 | `threshold_source.decision_history` | as_is_accepted（签署件备注为空 ⇒ 按原样接受（未提出修改）） |
| R-2 | `read_path.absent_required_fields.alignment_with_caliber_rules` | as_is_accepted（签署件备注为空 ⇒ 按原样接受（未提出修改）） |

## 取代关系

- 已签 v4：`sha256:6806f1399e3bbf5ace41264598f6228998f706dd082f20d580d5303a48ab712d` —— 已签 v4：其内容被 v4.1 只增不删地包含；v4 字节不变、留存可追溯。
- 并行草案：`.scratch/claims-r2-role-isolation/evidence/41-items-chain-accounting-20261012/r3-signoff-apply/scoring-contract-v4.proposed.json`（`sha256:b3f88649e9eca70cf21b95c466ea4a4950ef6a316aa521e2b42822c4eae7818f`）—— superseded_by v4.1（该草案从未签认；其独有叶子已并入 v4.1）

## 签认之后仍未完成（不得读成已过门）

- 评分器读契约/阈值对齐（P03/§7-6）：代码未改，OPEN-1=A 尚无实现
- 评分器匹配机制不得以身份相等为前提（P02）：代码未改
- 裁定→评分输入装配器（P01）：代码不存在
- 契约绑定再绑定 v2→v3→v4.1（P12）：待落记录
- 门 28 metric_basis 推进至 v4.1（P13）：待提案（不得就地改）
- 口径归一化实现与回归（P04/P05）：未实施
- route a/b 边际裁定与缺口 1/2（§5.12）：仍缺

## 当前记账漂移（须按 P12/P13 出新版本记录，不得就地改）

- 金标冻结链记录的契约：`2eb24be7e74f9e6003ca623487…`（实为 v2）
- 门 28 `metric_basis`：`None`

> 签认只签契约条款；不等于 items-only 真实复验通过，也不等于门 33 出分。
