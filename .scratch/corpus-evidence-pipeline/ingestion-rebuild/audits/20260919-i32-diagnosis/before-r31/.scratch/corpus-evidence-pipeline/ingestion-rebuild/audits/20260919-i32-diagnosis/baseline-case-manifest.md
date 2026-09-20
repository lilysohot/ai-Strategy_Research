# 7 类旧基线用例清单（步骤 3，草稿·未冻结）

- 生成：2026-09-19T17:40:54+08:00；状态：**frozen_r27**
- 用例合计 **87**；待你定/待补 **0** 项
- 范围原则：I3-2 只冻结『将来用哪些用例、按什么预期比较』；运行状态保持 not_run；I3-5/I3-7 才执行。

| 类别 | 用例数 | 预期资产 | 历史状态 | 重跑入口 | 验证阶段 | 待办 |
|---|---|---|---|---|---|---|
| legacy_retrieval_golden | 19 | `golden.py` | 2026-09-08 语料 17 份时 Recall@5 = 100%（逐题通过口径，含 req | **not_run** | I3-5（旧检索能力不退化，19 题口径） | **confirmed**：适用题目范围；**to_be_resolved**：旧锚点→新 locator 映射 |
| old_doc_kind_review_export | None | `c1_full84_doc_kind_review_20260912.csv` | 旧人工审核导出权威版本已由 U 确认（2026-09-19）并冻结；review_decisio | **not_run** | I3-2 冻结身份；无需重跑 | **confirmed**：权威版本确认 |
| financial_controlled_recalc_57 | 57 | `pilot_manifest.json` | 57/57 字段通过（历史 run：maotai 32／guangli 15／guosen 10 | **not_run** | I3-5（非回归重验，需单独授权）；I3-2 只冻结预期与契约 | **confirmed**：字段容差（tolerance）；**confirmed**：范围：guosen_maotai_holdout（10 格）与留出的关系 |
| formula_7 | 7 | `claims-entry-27dfab4cb9a97cf8ad72d269039d822afc3f39631601d76c0bed1b87645c0cb3.json` | 7/7 复算通过（父项 financial_controlled_recalc_57 的子节点） | **not_run** | I3-5（随父项） | **ok**：7 条公式 case_id/预期/容差/formula 名；**needs_definition**：输入字段（每公式依赖哪些冻结字段） |
| customer_table_12 | 0 | `None`（缺） | 贝特利客户表冻结单元格召回 0/12 → 12/12（semantic-repair-repor | **not_run** | I3-5（非回归）；范围冲突需先裁定 | **confirmed**：12 个单元格预期（材料）+ 冻结 run 记录；**confirmed**：留出范围冲突 |
| prose_numbers_3 | 2 | `pilot_manifest.json` | 华泰/中银正文目标数字 2/3 → 3/3（semantic-repair-report）；非农 | **not_run** | I3-5（且需预算授权） | **confirmed**：第 3 个用例身份；**confirmed**：历史 2/2 与最终 3/3 的集合关系 |
| macro_legacy_fields_0_of_3 | 2 | `claims-entry-27dfab4cb9a97cf8ad72d269039d822afc3f39631601d76c0bed1b87645c0cb3.json` | 0/3 单列、不伪装通过（spec.md L87） | **not_run** | I3-5（保留为历史失败用例，不并入开发分母） | **confirmed**：失败用例的机器可读身份（3 字段 vs 记录里的 2 targets）；**noted**：留出关系 |

## 需要你确认/补充的项（已停止执行的部分）

## 统一记录字段

`case_id / category / expected_asset(path, sha256, selector) / source_id / old_anchor / new_locator_or_mapping_rule / historical_status / historical_record_ref / applicability / rerun_contract(entry, params, side_effects, required_environment) / validation_stage`
