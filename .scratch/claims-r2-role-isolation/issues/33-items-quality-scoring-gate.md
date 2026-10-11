# 33 · items-only 质量评分门（门 32 产物的诊断口径评分）

Status: preregistered_zero_call（Stage 1 工作台已产出；Stage 2 待人工裁定）
Type: gate task
Parent: [32 · items selector v6 与执行配置重冻结](32-items-v6-and-reasoning-refreeze-gate.md)
Model attempts: 0（本门全程零调用）
Production database access: 0

## 1. 目的

对门 32 **treatment 臂**（v6 提示词 + 关闭思考）产出的 items 做质量评分，回答"这批数据能不能用"。
分母是 Issue 10 冻结的 48-item 非表格金标；判据全部取自已签认的
`non-table-selected-target-scoring-contract-v3`（`scoring-contract.json`，xyl 2026-10-11 签认）。

本门**不**评价协议、不重跑模型、不修改任何既有冻结物。

## 2. 输入（全部只读）

| 输入 | 路径 | 说明 |
| --- | --- | --- |
| 候选 | `../evidence/32-items-v6-reasoning-refreeze-20261011/live/candidates.json` | treatment 两源产出，md 88 + docx 134 = 222 条 |
| 金标 | `../evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json` | `role=material_items` 共 48 条 |
| 契约 | `../evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json` | schema `non-table-selected-target-scoring-contract-v3` |
| 覆盖披露 | `../evidence/32-…/live/residual-attribution.json` | 9 个未产出槽位：7 基础设施 + 2 我方信号标注过强（含 2 条连带丢失） |
| 评分器 | `plugins/corpus/structured_scoring.py` | `score_structured_quality`（严格 identity 一对一匹配） |

## 3. 流程（三步，严格顺序）

**Stage 1 · 裁定工作台（零调用，已完成）**
导出 222 条候选与 48 条金标的完整对照、自动对齐**建议**、以及契约 `candidate_adjudication_fields`
要求的 11 字段裁定骨架。建议值只是降低人工工作量的辅助，**不是评分输入**。

**Stage 2 · 人工逐条裁定（xyl；不可省略）**
契约 `matching.mode = human_adjudicated_semantic_equivalence_then_one_to_one_mapping`，且
`matching.projection` 明确禁止"把目标字符串直接赋给候选并宣称自动语义评分"。因此每条候选必须由人给出
`judgement`（`accepted` / `edited` / `rejected` / `pending`）与 `matched_gold_id`，并保留原始候选字段、
裁定人、理由与依据。

**Stage 3 · 严格评分（零调用）**
把裁定结果规范化后送入 `score_structured_quality`（raw 与 validated 两份分别裁定与计分），输出
target recall / candidate precision / duplicates / origin 切片 / 覆盖率 / 报告支撑 / 门槛。

## 4. 报分口径（契约 v3）

- scope：`selected_target_recall_not_exhaustive_document_gold`——分母只有人工接受的 48 条目标，
  **不宣称**覆盖两份材料的全部命题。
- `target_recall` = 已匹配接受金标 / 接受金标总数（48）。
- `candidate_precision` = (matched + correct_extra) / (matched + correct_extra + incorrect + duplicate)；
  **存在 `unresolved` 候选时记 N/A 并如实披露，不得排除后报告通过**。
- 同义重复只计第一条，其余记 duplicate FP。
- 额外正确输出单列 `correct_extra`，不回填召回分母。
- `minimum_accepted_records_per_role = 20`。
- 16 条高风险断言（NT-I09/13/15/17/19/29/35/37/38/39/42/43/45/46/47/48）逐条人工判定；
  断言是回归防退化项，不自动证明语义正确。

## 5. 范围外／不做

- 不做 publication、positive_query / delivery / context_use / report_reference；
- 不改金标、不改阈值、不改评分契约、不新增金标（`new_gold_allowed=false`）；
- 不重跑模型、不改提示词、不放宽任何 fail-closed 规则；
- 不把本门结果表述为"生产默认口径"或"完整文档覆盖"。

## 6. 待披露项（必须随报分一并给出）

1. 9 个未产出槽位：7 个基础设施（md 一次传输未知）+ 2 个我方信号标注过强（docx；其中 1 个连带丢失
   2 条模型已产出内容）——**这 2 条不计入模型漏抽**；
2. docx 1 次请求内 2 个槽位被判失败的口径分歧（已在 `residual-attribution.json` 记录并保留
   "自动判定 / 人工裁定"两栏）；
3. precision 若因 unresolved 记 N/A，须同时给出 unresolved 明细。

## 7. 授权待填项

| 项 | 授权人 | 日期 | 参数 |
| --- | --- | --- | --- |
| `gold_consumption_and_scoring` |  |  | 只读金标 + 报诊断口径；不改金标 |
| `publication` |  |  | —（默认 false） |
| `production_database_access` |  |  | —（默认 false） |

## 8. 交付物

- `../evidence/33-items-quality-scoring-20261011/r0-zero-call/workbench.json`（候选 × 金标对照 + 建议 + 裁定骨架）
- `../evidence/33-items-quality-scoring-20261011/r0-zero-call/workbench.md`（人工裁定的可读清单）
- `../evidence/33-items-quality-scoring-20261011/r0-zero-call/adjudications.json`（Stage 2 产出，人工填写）
- `../evidence/33-items-quality-scoring-20261011/r1-score/score-report.json`（Stage 3 产出）

## 9. 签认栏

- 复核人：xyl　日期：2026-10-11
- 结论： 准予执行（按 §7 填授权）　☐ 退回修改
