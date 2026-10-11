# 现状基线（control 臂）

- 口径：control arm: current scorer, native candidate shape, frozen gold 48
- 匹配模式：`strict identity equality on (role, source_id, origin, semantic_fields)`
- 评分器策略：`PILOT_CANDIDATE_POLICY (hardcoded; 0.95/0.90)`

## A 臂结果（MATERIAL_ITEMS）

- tp=0 fp=222 fn=48 precision=0 recall=0
- 命中金标：0；未命中：48
- `rate_gate_passed`=False；`live_trial_ready`=False
- `risk_condition_recall`=0

## 门 28 权威阈值对照（诊断口径）

- precision_min=0.80（实测 0）
- target_recall_overall_min=0.85（实测 0）
- risk/condition recall 门槛 0.95（实测 0）
- critical 缺失条数：12
- 分源接受数门槛 20：N/A (requires Stage 2 adjudication)

## 评分器硬编码策略下的 blockers（原样）

- `zero_denominator:claims:precision`
- `zero_denominator:claims:recall`
- `below_threshold:material_items:precision:0<19/20`
- `below_threshold:material_items:recall:0<9/10`
- `zero_denominator:material_relations:precision`
- `zero_denominator:material_relations:recall`
- `below_threshold:risk_or_condition:recall:0<19/20`
- `zero_denominator:report_support`
- `critical_gold_missing:NT-I13`
- `critical_gold_missing:NT-I14`
- `critical_gold_missing:NT-I15`
- `critical_gold_missing:NT-I16`
- `critical_gold_missing:NT-I17`
- `critical_gold_missing:NT-I19`
- `critical_gold_missing:NT-I20`
- `critical_gold_missing:NT-I34`
- `critical_gold_missing:NT-I40`
- `critical_gold_missing:NT-I42`
- `critical_gold_missing:NT-I43`
- `critical_gold_missing:NT-I44`

## readiness blockers（原样）

- `insufficient_sample:claims:0/20`
- `insufficient_sample:material_relations:0/20`
- `development_gold_not_frozen`
- `gold_not_frozen_before_candidates`
- `adjudications_unresolved`
- `thresholds_not_signed_off`

> 本文件是诊断口径。不得表述为「门 28 通过／未通过」。
