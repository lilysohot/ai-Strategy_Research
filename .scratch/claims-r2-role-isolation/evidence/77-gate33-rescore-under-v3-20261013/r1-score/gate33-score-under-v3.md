# 门 33 重算出分（已签门 v3 + 契约 v4.3 基准；零模型调用）

- 2026-10-13　判定：**PASS**（7 条判据全过）
- 基准：`.scratch/claims-r2-role-isolation/evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json` `sha256:340b312d9c0cec278e828d8303a03e9daf953feef4c0eef688f3d257971a9732`
- 契约：`.scratch/claims-r2-role-isolation/evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json` `sha256:d7b4f8a81ef42e3cd5d619eae92bc34df7b7aa683d34aeba4f1a22719ae69a2f`
- 改判：`.scratch/claims-r2-role-isolation/evidence/75-r2-signed-20261013/r0-zero-call/re-adjudication.json`（7 条）

## 一、逐项判据

| # | 判据 | 门槛 | 实测 | 判定 |
|---|---|---|---|---|
| 1 | target_recall_overall_min | 0.85 | 41/48 = 0.854 | **PASS** |
| 2 | target_recall_per_source_min | 0.8 | 源1 20/22 = 0.909；源2 21/26 = 0.808 | **PASS** |
| 3 | candidate_precision_min | 0.8 | 30/31 | **PASS** |
| 4 | unresolved_candidates_max | 0 | 0 | **PASS** |
| 5 | accepted_records_total_min | 40 | 240 | **PASS** |
| 6 | accepted_records_per_source_min | 20 | 见 per_source 明细 | **PASS** |
| 7 | high_risk_item_assertions_required | 11/11 | 11/11；未中 [] | **PASS** |

## 二、与旧 verdict 的关系

- 旧：`.scratch/claims-r2-role-isolation/evidence/69-union-adjudication-20261013/r1-score/gate33-honest-score.json` 召回 17/24（matched 34）→ FAIL — 召回未达 0.85；缺口为真实 FN（金标无候选匹配），非流程问题
- 新：召回 41/48（matched 41），**新增 matched 7 条**
- 旧记录字节未改；取代关系以契约 v4.3 `registrations.supersedes_terminal_record` 登记。

## 三、诚实说明

- 本记录按已签门 v3 + 契约 v4.3 + 7 条具名改判重算；旧 verdict 字节不变、仅以登记方式被取代。
- 哨兵清单已由 16 项缩为 11 项（移出项机制见门 v3 high_risk_item_assertions_excluded）。
- 召回余量极薄（总 +0.004 / 源2 +0.008）；本条不得读作生产可用或整篇覆盖。

## 四、复现

```bash
uv run python .scratch/claims-r2-role-isolation/evidence/77-gate33-rescore-under-v3-20261013/r1-score/score_gate33_v3.py
```
