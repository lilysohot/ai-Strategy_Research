# 真实质量门冻结审阅

日期：2026-10-08  
状态：已签认部分关键检查点与阈值；已运行 seen-development 诊断评分；未通过正式质量门

## 1. 当前可冻结的依据

材料为华创证券《贵州茅台（600519）2026年中报点评》，SHA256：
`6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11`。

候选生成前，许永立已于 2026-10-05 确认 E01—E12 关键证据检查点。该审阅稿位于：

`../11-live-20261004-r1/research-scope-review.md`

E01—E12 可冻结为“预候选人工确认的关键检查点”，但原审阅稿明确说明它们不是完整
Claims/items/relations 金标，不能扩写成未曾人工确认的 TP/FP/FN 分母。

当前候选位于 `../11-live-20261008-optimized/aggregate.json`，包含 48 items 和 5 relations。
完整金标尚未冻结时候选已经可见，因此本材料只能作为 `seen-development` 诊断样本，不能再声明
`gold_frozen_before_candidates=true`。

## 2. 已签认阈值

| 角色/指标 | 候选阈值 |
| --- | ---: |
| Claims precision | ≥ 98%（49/50） |
| Claims recall | ≥ 95%（19/20） |
| material_items precision | ≥ 95%（19/20） |
| material_items recall | ≥ 90%（9/10） |
| material_relations precision | ≥ 95%（19/20） |
| material_relations recall | ≥ 85%（17/20） |
| 风险/条件 recall | ≥ 95%（19/20） |
| 报告支持率 | ≥ 95%（19/20） |
| 每角色最小人工金标 | 20 条 |

绝对否决项：错主体、错年份、错单位量级、事实/预测混淆、否定反转、条件反转、错归属、
伪造引文、关键报告结论失败。任一命中即不通过。

## 3. 当前数据充分性

| 项目 | 当前状态 |
| --- | --- |
| 预候选人工确认 | E01—E12，共 12 个关键检查点 |
| 完整 Claims 金标 | 未冻结；不足 20 条 |
| 完整 material_items 金标 | 未冻结；候选已见，不可作为盲金标 |
| 完整 material_relations 金标 | 未冻结；当前候选仅 5 条，不足 20 条 |
| 真实 delivery/context_use 观察 | 0；M_main 尚未运行 |
| 独立留出 | 未访问 |

因此，即使现在运行诊断评分，`live_trial_ready` 也必须为 false；不得降低最小样本数或把零分母
解释为通过。

## 4. 人工选择与签认

用户于 2026-10-08 在对话中明确确认：

> 我确认阈值、E01—E12 部分冻结及 seen-development 诊断范围；审核人与裁定人均为许永立。

- [x] 接受第 2 节阈值及绝对否决项，不作下调。
- [x] 同意将 E01—E12 冻结为“预候选关键检查点”，但不冒充完整三角色金标。
- [x] 同意当前贵州茅台材料仅作为 `seen-development` 诊断样本；评分结果不得用于质量放行。
- [ ] 提供或批准新增未见候选的开发材料，使 Claims/items/relations 各至少达到 20 条人工金标。
- [x] 指定人工审核人和争议裁定人；二者可以是同一人，但必须留名。

审核人：许永立  
争议裁定人：许永立  
签认日期：2026-10-08

## 5. 冻结与评分边界

机读冻结记录为 `critical-check-gold.json`。E01—E12 被映射为 13 个可评分记录：10 个
Claims 检查、2 个 material_items 检查和 1 个 material_relations 检查；E11 另作为解析覆盖缺口，
不伪装成语义记录。映射只衡量这些预先确认的关键点是否在当前 aggregate 中成立，不把 aggregate
的其余输出纳入 FP 分母，因此其 precision 是“检查点投影 precision”，不是完整抽取 precision。

本次 `EvaluationReadiness` 的四个布尔项只对“部分关键检查点诊断”成立：检查点在候选生成前确认、
阈值与裁定人现已签认。完整三角色金标仍未冻结，当前候选也已被看到；每角色 20 条最低分母、
独立未见开发材料以及真实 delivery/context_use 仍然缺失。因此无论诊断百分比为何，均不得据此
放行真实试验、发布候选或解除 M_main 的质量前置门。
