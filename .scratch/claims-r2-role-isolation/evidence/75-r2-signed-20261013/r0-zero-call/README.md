# R2 · 已签认版（门 v3 + 契约 v4.3 + 7 条改判）

- 签署人：**xyl**　日期：**2026-10-13**
- 签署工具：`.scratch/claims-r2-role-isolation/evidence/74-r2-gate-v3-contract-v43-draft-20261013/r0-zero-call/r2-signoff-review.md` `sha256:b02dadc20189133ae0e717826ec928b86a669a967dec74e63911a34498df3d3f`
- 二选一：**NT-I23**（未选：['NT-I24']）
- 第 7 条：**one_of_u_calibration_revoked**（具体条目 NT-I45）
- 门 v3：`gate-v3.json` `sha256:340b312d9c0cec278e828d8303a03e9daf953feef4c0eef688f3d257971a9732`
- 契约 v4.3：`scoring-contract-v4.3.json`（`frozen_signed`）
- 改判：`re-adjudication.json`（`named_signed`，7 条）

## 阈值确认（逐字未改）

- `target_recall_overall_min` = `0.85`
- `target_recall_per_source_min` = `0.8`
- `candidate_precision_min` = `0.8`
- `accepted_records_total_min` = `40`
- `accepted_records_per_source_min` = `20`
- `unresolved_candidates_max` = `0`
- `threshold_relaxation_after_execution_allowed` = `False`

## 签认之后仍未完成（不得读成已过门）

- 据实重算门 33 出分并形成**新 verdict**；旧 verdict（FAIL）不改写
- 评分器按契约读阈值（OPEN-1=A 的兑现）——本条独立于本签认
- 发布路径（O1『显式缺口』）仍待单独裁定与实施
- 本签认不授权任何模型调用、发布、查询、delivery 或 context_use

> 签认只签条款：不等于出分、不等于复验通过、不等于可发布。
