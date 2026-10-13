# R2 链回溯审计（相位：initial；零模型调用，只读）

- 审计范围：71 FN 归因 → 72 终态记录 → 74 草案包 → 75 落地脚本
- 未审计：发布路线 O1 的代码面（另见 evidence/73）；评分器读契约的代码改动（未实施）
- 谓词：`blocking_target` 目标达不成 ｜ `blocking_signoff` 签认会落地不可消费记录或代签 ｜ `registration` 须登记 ｜ `cosmetic` 措辞

## 一、汇总

检查 23 项；**未通过 7 项**（blocking_target 1、blocking_signoff 4、registration 1、cosmetic 1）

## 二、逐项结果

| 检查 | 谓词 | 结果 | 级别 | 说明 |
|---|---|---|---|---|
| `sentinel_equals_contract_items` | 门 v3 哨兵清单 == 契约 v4.3 的 NT-I* 断言子集 | PASS | — | 二者不一致会让门与契约各说一套 |
| `excluded_subset_of_v2_sentinel` | 被移出 5 项 ⊂ 门 v2 的 16 项 | PASS | — | 移出项必须原本在清单内 |
| `excluded_all_annotated` | 每个被移出项都有 mechanism 与 reason | PASS | — | 无理由的移出等于事后删项 |
| `sentinel_subset_of_gold` | 哨兵清单 ⊂ 48 条冻结金标 | PASS | — |  |
| `flip_count` | 改判集 = 必需 5 + 二选一 2（共享候选，只取一）+ 第 7 条 1 = 7 条 | FAIL | blocking_target | 少于 7 条算术上无法在未改阈值下达标 |
| `required_flip_candidates_distinct` | 必需 5 条的候选互不重复 | PASS | — | 一条候选不得抵扣多条金标（one_to_one_mapping） |
| `pair_share_one_candidate` | 二选一两项共享同一候选（因此只能取一） | PASS | — | 若为 2 则二选一前提不成立，需重算 |
| `no_required_flip_candidate_is_occupied` | 必需 5 条的候选此前均未被其他金标占用 | PASS | — | 若某条候选已被占用，该条改判会违反一对一 |
| `flip_golds_not_already_matched` | 改判目标 ⊄ 现有 matched 集合 | PASS | — | 已是 matched 的条目不得重复计入增量 |
| `projection_arithmetic` | 未改阈值下投影达标记（≥41/48、每源 ≥0.80、哨兵全覆盖） | PASS | — | 算术不过则 R2 不成立 |
| `precision_invariant_under_flip` | ce→matched 改判不改变精确率分子/分母（同一候选换了标签） | PASS | — | 改判只在 matched 与 correct_extra 之间搬移，判据 3/5/6 不受影响 |
| `accepted_total_invariant` | 接受数 = matched + correct_extra 恒定 | PASS | — | 判据 5（≥40）与判据 6（≥20/源）不变 |
| `thresholds_byte_identical` | 六项阈值 与门 v2 逐字相同 | PASS | — | 阈值一变即触发门自身的 threshold_relaxation 禁令 |
| `signed_v42_pin_matches_gate_v2` | 已签 v4.2 对门 v2 的绑定与现盘一致（扩展链条的前提） | PASS | — | 若已不一致，说明旧链条本身已断，R2 不能默认继承 |
| `gate_rebinds_contract_hash` | 门 v3 的 gold.scoring_contract_sha256 必须再绑定到契约 v4.3 | FAIL | blocking_signoff | 门 revision 5 的先例要求 metric_basis 与 scoring_contract_sha256 两处同步改 |
| `readjudication_carries_contract_fields` | 改判记录须齐备契约 candidate_adjudication_fields（评分器消费前提） | FAIL | blocking_signoff | 缺失字段：['stage', 'role', 'source_id', 'original_candidate', 'judgement', 'matched_gold_id', 'canonical_observed_fields', 'reason', 'evidence']；score_structured_quality 只消费契约形态裁定 |
| `readjudication_has_verbatim_evidence` | 每条改判须附逐字引文或原文定位（locator + 区间） | FAIL | blocking_signoff | adjudication_clause.evidence_required |
| `single_signable_instrument` | 只存在一份可签件 | PASS | — | 并行会话若再出第二份 v3 会产生多份真相 |
| `no_prefilled_pair_decision` | 二选一（I23/I24）不得由脚本预填，必须有勾选位并逐字读取 | FAIL | blocking_signoff | 脚本硬编码 pairs_resolved=NT-I23 属于代签 U 未做的选择 |
| `terminal_record_is_the_fail_state_being_superseded` | 被取代的 evidence/72 记录的终态确为 FAIL（否则『取代』一说不成立） | PASS | — | 确认取代的对象正确 |
| `terminal_record_supersession_declared` | R2 落地后取代 evidence/72 的『不可达』结论，须显式登记 | PASS | — | 否则 72 的终态与 R2 的 PASS 会同时挂在案上 |
| `frozen_gold_side_binding_registered` | 已知的 frozen-gold 侧契约绑定过期须在 R2 轮内登记（金标不可改，只能登记为例外） | FAIL | registration | 契约 bookkeeping_requirements 已记 match=False，R2 不得再加一层未登记的不一致 |
| `quality_gate_wording_current` | 契约 metrics.quality_gate 不得仍指向被取代的 v3 | FAIL | cosmetic | 不影响判定，但会造成版本误读 |

## 三、未通过项的实际值

### `flip_count`（blocking_target）

- 应然：`["NT-I38", "NT-I39", "NT-I48", "NT-I26", "NT-I34", "NT-I23", "NT-I24", "<第7条待选>"]`
- 实然：`8`
- 说明：少于 7 条算术上无法在未改阈值下达标

### `gate_rebinds_contract_hash`（blocking_signoff）

- 应然：`"sha256:9367a285844ff12df8f3f2356fc41225a06f3bec17b7e249599c1ccdc3dc8269"`
- 实然：`"sha256:c76ac13ec0a109074775a2b5e1c8cc170da955847638d6ea7f5778988238781b"`
- 说明：门 revision 5 的先例要求 metric_basis 与 scoring_contract_sha256 两处同步改

### `readjudication_carries_contract_fields`（blocking_signoff）

- 应然：`["candidate_id", "stage", "role", "source_id", "original_candidate", "judgement", "matched_gold_id", "canonical_observed_fields", "reviewer", "reason", "evidence"]`
- 实然：`["basis_clause", "candidate_id", "candidate_text", "gold_id", "gold_proposition", "gold_quote", "locator", "previous_judgement", "previous_matched_gold_id", "previous_reason", "proposed_judgement", "recovery_context_note", "reviewer", "signed_on", "source", "status"]`
- 说明：缺失字段：['stage', 'role', 'source_id', 'original_candidate', 'judgement', 'matched_gold_id', 'canonical_observed_fields', 'reason', 'evidence']；score_structured_quality 只消费契约形态裁定

### `readjudication_has_verbatim_evidence`（blocking_signoff）

- 应然：`"locator + 区间"`
- 实然：`["gold_quote", "locator"]`
- 说明：adjudication_clause.evidence_required

### `no_prefilled_pair_decision`（blocking_signoff）

- 应然：`"签认件含 I23/I24 勾选位 + 脚本读取它"`
- 实然：`{"sheet_has_pair_box": false, "apply_prefills_pair": true}`
- 说明：脚本硬编码 pairs_resolved=NT-I23 属于代签 U 未做的选择

### `frozen_gold_side_binding_registered`（registration）

- 应然：`"R2 记录中出现该绑定例外"`
- 实然：`false`
- 说明：契约 bookkeeping_requirements 已记 match=False，R2 不得再加一层未登记的不一致

### `quality_gate_wording_current`（cosmetic）

- 应然：`"引用当前版本"`
- 实然：`"仍含『本契约 v3』字样"`
- 说明：不影响判定，但会造成版本误读
