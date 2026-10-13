# R2 草案包：门 v3 + 契约 v4.3 + 7 条改判草案（零模型调用）

- 2026-10-13　依据：U「先走 R2」；不删改任何既有文件，旧件哈希留存在 revision_history
- **全部为草案**：门 countersignature、契约 signoff、改判 reviewer 三处均留空，不代签

## 一、R2 改了什么（三处）

| # | 项 | 变化 |
|---|---|---|
| 1 | 高风险哨兵清单 | 16 → **11** 项，移出 NT-I09/I19/I45/I46/I47（逐条机制见 `high_risk_item_assertions_excluded`） |
| 2 | 契约口径 | `matching.items` 增补「上下文唯一可恢复」条款及其两项不适用情形 |
| 3 | 门/契约绑定 | 门 revision 6；契约 v4.3 改钉门 v3（**provisional**，签认后回填） |

**未改**：六项阈值（0.85/0.80/0.80/40/20/0 逐字不变）、`scope_constraints.threshold_relaxation_after_execution_allowed=false`、冻结金标字节、样本、代码。

## 二、哨兵清单移出项（逐条机制）

| gold | 机制 | 依据 |
|---|---|---|
| NT-I09 | `gold_split_finer_than_candidate` | 金标把同一原文句拆成『条件(I09)+结论(I10)』两条，候选侧只产出整句一条且已被 NT-I10 占用；在 one_to_one_mapping 下必有一条落空（契约 §8.1：一条混合输出不能抵扣多个金标命题）。 |
| NT-I19 | `gold_split_finer_than_candidate` | 同 NT-I09：I19 与 I20 为同一句的两种切分，候选整句被 NT-I20 占用。 |
| NT-I45 | `candidate_side_cannot_carry_axis` | U 2026-10-12 校准撤销 matched：金标属被转述且被质疑的预测(perspective=quoted_other, source_stance=challenged)，而契约 caliber_rules 记明 source_stance 生产端无载体、必须人工判定 ⇒ 候选侧结构上不承载该轴。 |
| NT-I46 | `candidate_side_cannot_carry_axis` | 同 NT-I45。 |
| NT-I47 | `candidate_side_cannot_carry_axis` | 同 NT-I45。 |

## 三、改判草案（7 条）

### 3.1 必需 5 条

| gold | 源 | 候选 | 原裁定 | 拟裁定 |
|---|---|---|---|---|
| NT-I38 | 源2 | `itm_bf5fa66fb7be5a02` | correct_extra | matched |
| NT-I39 | 源2 | `itm_a79b0be05f3456c3` | correct_extra | matched |
| NT-I48 | 源2 | `itm_d96a4e7b052a89c7` | correct_extra | matched |
| NT-I26 | 源2 | `itm_a41addfcb6696346` | correct_extra | matched |
| NT-I34 | 源2 | `itm_15c17f04855a28b3` | correct_extra | matched |

### 3.2 二选一（共享同一候选，只能取一条）

| gold | 候选 | 原裁定 |
|---|---|---|
| NT-I23 | `itm_703720fdd5630e8b` | correct_extra |
| NT-I24 | `itm_703720fdd5630e8b` | correct_extra |

**二选一勾选（签认件第六节）**：第 7 条下方另有 `NT-I23 / NT-I24` 勾选栏，必须且只能勾一项。

### 3.3 第 7 条：三选一（**待 U 决定**）

| 选项 | 涉及 gold | 代价 |
|---|---|---|
| `I36_question_form` | NT-I36 | 需承认疑问句可承载该金标命题（原裁定理由为『类比式问句，非金标肯定断言』） |
| `I23_or_I24_double_assignment` | NT-I23+NT-I24 | 需承认一条候选可抵扣两条金标命题 —— 与 one_to_one_mapping / 契约 §8.1 冲突，不推荐 |
| `one_of_u_calibration_revoked` | NT-I45|NT-I46|NT-I47 | 需推翻 U 2026-10-12 校准中的 1 条（候选与金标逐字相同，但 source_stance 口径相反） |

## 四、投影（**未签认投影，不是 verdict**）

本块是**未签认投影**，不是 verdict。只有门 v3 与契约 v4.3 具名签认、且 7 条改判由 xyl 具名确认之后，才可据实重算出分并形成新 verdict。

| 第 7 条选项 | 总召回 | 源1 | 源2 | 哨兵 | 投影判定 |
|---|---|---|---|---|---|
| `I36_question_form` | 0.854 | 0.909 | 0.808 | 11/11 | **PASS** |
| `one_of_u_calibration_revoked` | 0.854 | 0.909 | 0.808 | 11/11 | **PASS** |

> 契约无效选项：`I23_or_I24_double_assignment` —— 一条候选抵扣两条金标，违反 one_to_one_mapping 与契约 §8.1；本草案不提供该情形下的 PASS。

## 五、机器校验

通过 18 项，失败 0 项。

| 检查 | 结果 | 说明 |
|---|---|---|
| `thresholds_unchanged` | PASS | 六项阈值逐字沿用门 v2（0.85/0.80/0.80/40/20/0） |
| `threshold_relaxation_flag_still_false` | PASS | scope_constraints.threshold_relaxation_after_execution_allowed 保持 false |
| `sentinel_matches_contract_items_subset` | PASS | 门 v3 哨兵清单 == 契约 v4.3 review_assertions 的 NT-I* 子集 |
| `exclusions_all_annotated` | PASS | 每个被移出哨兵项都带 mechanism 与 reason |
| `exclusions_were_in_v2_sentinel` | PASS | 被移出项原本都在门 v2 哨兵清单内 |
| `sentinel_subset_of_gold` | PASS | 哨兵清单全部属于 48 条冻结金标 |
| `no_candidate_used_twice` | PASS | 改判草案中候选互不重复：['itm_bf5fa66fb7be5a02', 'itm_a79b0be05f3456c3', 'itm_d96a4e7b052a89c7', 'itm_a41addfcb6696346', 'itm_15c17f04855a28b3'] |
| `required_flips_are_distinct_candidates` | PASS | I23/I24 共享同一候选（-1），其余互不重复 |
| `old_hashes_retained` | PASS | 门 v2 与契约 v4.2 的旧哈希已留存于新版本记录 |
| `contract_pin_provisional_not_faked` | PASS | 契约对门 v3 的绑定标记为 provisional，未伪造已签哈希 |
| `signoff_fields_empty` | PASS | 门/契约/改判三处新签认字段全部留空，不代签（旧裁定人原样留档） |
| `adjudications_carry_contract_fields` | PASS | 改判记录齐备契约 11 个 candidate_adjudication_fields |
| `adjudications_have_verbatim_evidence` | PASS | 每条改判都带候选原文 evidence 与金标 locator |
| `pair_stubs_share_one_candidate` | PASS | 二选一两条共享同一候选（apply 落地时只保留一条） |
| `seventh_stubs_cover_all_options` | PASS | 第 7 条四个候选桩齐备：['NT-I36', 'NT-I45', 'NT-I46', 'NT-I47'] |
| `landed_adjudication_count_is_seven` | PASS | 落地后应为 5（always）+ 1（pair）+ 1（seventh）= 7 条 |
| `all_projection_options_pass_or_flagged` | PASS | 两个合法第七项选项在未改阈值下均投影为 PASS |
| `attribution_propositions_match_gate33_gold` | PASS | 归因表的金标命题与门 33 gold_reference 逐条一致 |

## 六、签认前还缺什么

1. **U 的第 7 条选择**（`I36_question_form` / `one_of_u_calibration_revoked`；双抵扣项契约无效）
2. 门 v3 具名签认（`countersignature`）
3. 契约 v4.3 具名签认（`signoff`），签认后回填门 v3 最终哈希并移除 `pin_status`
4. 7 条改判由 xyl 具名确认（`re-adjudication-draft.json`）
5. 以上完成后才可据实重算出分，形成**新 verdict**；旧 verdict 保持 FAIL 不改写

## 七、复现

```bash
uv run python .scratch/claims-r2-role-isolation/evidence/74-r2-gate-v3-contract-v43-draft-20261013/r0-zero-call/build_r2_drafts.py
```
