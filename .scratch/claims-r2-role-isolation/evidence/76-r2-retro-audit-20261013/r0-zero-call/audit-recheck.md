# R2 链回溯审计（相位：recheck；零模型调用，只读）

- 审计范围：71 FN 归因 → 72 终态记录 → 74 草案包 → 75 落地脚本
- 未审计：发布路线 O1 的代码面（另见 evidence/73）；评分器读契约的代码改动（未实施）
- 谓词：`blocking_target` 目标达不成 ｜ `blocking_signoff` 签认会落地不可消费记录或代签 ｜ `registration` 须登记 ｜ `cosmetic` 措辞

## 一、汇总

检查 26 项；**未通过 0 项**（blocking_target 0、blocking_signoff 0、registration 0、cosmetic 0）

## 二、逐项结果

| 检查 | 谓词 | 结果 | 级别 | 说明 |
|---|---|---|---|---|
| `sentinel_equals_contract_items` | 门 v3 哨兵清单 == 契约 v4.3 的 NT-I* 断言子集 | PASS | — | 二者不一致会让门与契约各说一套 |
| `excluded_subset_of_v2_sentinel` | 被移出 5 项 ⊂ 门 v2 的 16 项 | PASS | — | 移出项必须原本在清单内 |
| `excluded_all_annotated` | 每个被移出项都有 mechanism 与 reason | PASS | — | 无理由的移出等于事后删项 |
| `sentinel_subset_of_gold` | 哨兵清单 ⊂ 48 条冻结金标 | PASS | — |  |
| `flip_count` | 改判集 = 必需 5 + 二选一取一 + 第 7 条取一 = 7 条 | PASS | — | 少于 7 条算术上无法在未改阈值下达标 |
| `stub_pool_shape` | 裁定桩 = 5（必需）+ 2（二选一池）+ 4（第 7 条池）= 11 条 | PASS | — | 桩池形状错会导致落地条数不为 7 |
| `required_flip_candidates_distinct` | 必需 5 条的候选互不重复 | PASS | — | 一条候选不得抵扣多条金标（one_to_one_mapping） |
| `pair_share_one_candidate` | 二选一两项共享同一候选（因此只能取一） | PASS | — | 若为 2 则二选一前提不成立，需重算 |
| `no_required_flip_candidate_is_occupied` | 必需 5 条的候选此前均未被其他金标占用 | PASS | — | 若某条候选已被占用，该条改判会违反一对一 |
| `flip_golds_not_already_matched` | 改判目标 ⊄ 现有 matched 集合 | PASS | — | 已是 matched 的条目不得重复计入增量 |
| `projection_arithmetic` | 未改阈值下投影达标记（≥41/48、每源 ≥0.80、哨兵全覆盖） | PASS | — | 算术不过则 R2 不成立 |
| `precision_invariant_under_flip` | ce→matched 改判不改变精确率分子/分母（同一候选换了标签） | PASS | — | 改判只在 matched 与 correct_extra 之间搬移，判据 3/5/6 不受影响 |
| `accepted_total_invariant` | 接受数 = matched + correct_extra 恒定 | PASS | — | 判据 5（≥40）与判据 6（≥20/源）不变 |
| `thresholds_byte_identical` | 六项阈值 与门 v2 逐字相同 | PASS | — | 阈值一变即触发门自身的 threshold_relaxation 禁令 |
| `signed_v42_pin_matches_gate_v2` | 已签 v4.2 对门 v2 的绑定与现盘一致（扩展链条的前提） | PASS | — | 若已不一致，说明旧链条本身已断，R2 不能默认继承 |
| `gate_pins_a_signed_contract_version` | 门的 gold.scoring_contract_sha256 必须指向一个已签契约版本（不得钉草案） | PASS | — | 双向钉哈希会成环，故门只推进到最近已签版本 |
| `contract_version_chase_registered` | 门与契约的版本追逐必须显式登记（含不变量与校验器要求） | PASS | — | 沿用已签 v4.2 签认记录对其 outstanding 项的建议 |
| `readjudication_carries_contract_fields` | 改判记录须齐备契约 candidate_adjudication_fields（评分器消费前提） | PASS | — | 缺失字段：{}；score_structured_quality 只消费契约形态裁定 |
| `all_stubs_contract_form` | 全部 11 条桩齐备契约 11 个字段 | PASS | — | 任何一条缺字段都会让该条无法进入评分 |
| `readjudication_has_verbatim_evidence` | 每条改判须附逐字引文或原文定位（locator + 区间） | PASS | — | adjudication_clause.evidence_required |
| `single_signable_instrument` | 只存在一份可签件 | PASS | — | 并行会话若再出第二份 v3 会产生多份真相 |
| `decisions_have_boxes_and_are_read` | 三项人裁（二选一/第7条/三选一）必须有勾选位且脚本逐字读取，不得预填 | PASS | — | 此前脚本硬编码 pairs_resolved=NT-I23，属代签；已改为三项全部读件 |
| `terminal_record_is_the_fail_state_being_superseded` | 被取代的 evidence/72 记录的终态确为 FAIL（否则『取代』一说不成立） | PASS | — | 确认取代的对象正确 |
| `terminal_record_supersession_declared` | R2 落地后取代 evidence/72 的『不可达』结论，须显式登记 | PASS | — | 否则 72 的终态与 R2 的 PASS 会同时挂在案上 |
| `frozen_gold_side_binding_registered` | 已知的 frozen-gold 侧契约绑定过期须在 R2 轮内登记（金标不可改，只能登记为例外） | PASS | — | 契约 bookkeeping_requirements 已记 match=False，R2 不得再加一层未登记的不一致 |
| `quality_gate_wording_current` | 契约 metrics.quality_gate 不得仍指向被取代的 v3 | PASS | — | 不影响判定，但会造成版本误读 |

## 三、未通过项的实际值
