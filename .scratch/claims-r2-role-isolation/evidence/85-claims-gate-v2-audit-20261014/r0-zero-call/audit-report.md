> 对象：84 号 claims 门 v2 草案。本件是对它的机器可核验回溯审核 + 可行性分层。
> 零模型调用；不修改 84/83/P1R5/门 v3/契约 v4.3 的任何字节。
> 审核谓词：按【层级 × 性质 × 是否阻塞】计数；**阻塞** = 该项失败会使门不可签认；
> 口径与记账分歧一律记为 `divergence`（检出并登记，不代替人裁）。

# Claims 门 v2 回溯审核（机器生成）

审核项 26 条；阻塞项失败 0 条；口径/记账分歧 3 条；仅记录 2 条。

谓词声明：审核项按【层级 × 性质 × 是否阻塞】计数。层级 ∈ {frozen, pool, metric, invariant, caliber, bookkeeping}；性质 ∈ {integrity, reproducibility, identity, coverage, consistency, completeness, caliber_divergence, feasibility}；阻塞 = 该项失败会使门不可签认。

| 审核项 | 层级 | 性质 | 阻塞 | 判定 | 主张 |
|---|---|---|---|---|---|
| `inputs-stable` | frozen | integrity | 是 | **pass** | 门/清单引用的全部冻结输入与磁盘字节一致 |
| `pool-ledger-closed` | pool | integrity | 是 | **pass** | 候选池裁定账闭合：四类之和 == 池容量，unresolved == 0 |
| `caliber-reproducible:D1_all_candidates` | metric | reproducibility | 是 | **pass** | D1_all_candidates 的候选数/分子/分母/显示值可由冻结池复算 |
| `caliber-row-complete:D1_all_candidates` | metric | completeness | 否 | **pass** | D1_all_candidates 行记录了候选数/裁定分布/召回（不得只留精度一个数） |
| `caliber-recall:D1_all_candidates` | metric | reproducibility | 是 | **pass** | D1_all_candidates 的召回/分源精度可由冻结池复算 |
| `caliber-reproducible:D2_in_role_only` | metric | reproducibility | 是 | **pass** | D2_in_role_only 的候选数/分子/分母/显示值可由冻结池复算 |
| `caliber-row-complete:D2_in_role_only` | metric | completeness | 否 | **pass** | D2_in_role_only 行记录了候选数/裁定分布/召回（不得只留精度一个数） |
| `caliber-recall:D2_in_role_only` | metric | reproducibility | 是 | **pass** | D2_in_role_only 的召回/分源精度可由冻结池复算 |
| `caliber-reproducible:D3_in_role_and_coordinate_complete` | metric | reproducibility | 是 | **pass** | D3_in_role_and_coordinate_complete 的候选数/分子/分母/显示值可由冻结池复算 |
| `caliber-row-complete:D3_in_role_and_coordinate_complete` | metric | completeness | 否 | **pass** | D3_in_role_and_coordinate_complete 行记录了候选数/裁定分布/召回（不得只留精度一个数） |
| `caliber-recall:D3_in_role_and_coordinate_complete` | metric | reproducibility | 是 | **pass** | D3_in_role_and_coordinate_complete 的召回/分源精度可由冻结池复算 |
| `caliber-reproducible:D4_similarity_scoped_v1_draft_option` | metric | reproducibility | 是 | **pass** | D4_similarity_scoped_v1_draft_option 的候选数/分子/分母/显示值可由冻结池复算 |
| `caliber-row-complete:D4_similarity_scoped_v1_draft_option` | metric | completeness | 否 | **divergence** | D4_similarity_scoped_v1_draft_option 行记录了候选数/裁定分布/召回（不得只留精度一个数） |
| `caliber-recall:D4_similarity_scoped_v1_draft_option` | metric | reproducibility | 否 | **note** | D4_similarity_scoped_v1_draft_option 的召回/分源精度可由冻结池复算 |
| `caliber-divergence:duplicate` | caliber | caliber_divergence | 否 | **divergence** | 契约文字公式（分母含 duplicate）与评分器实现公式（分母不含）不同源 |
| `sentinel-contract-subset` | invariant | identity | 是 | **pass** | 哨兵清单 == 已签契约 review_assertions 的 NT-C* 子集 |
| `sentinel-required-hit` | invariant | coverage | 是 | **pass** | 契约要求的每条 claims 哨兵在冻结池中被命中 |
| `sentinel-no-foreign` | invariant | identity | 否 | **pass** | 门不得携带契约之外的哨兵（v1 自造的 3 条须登记为作废而非保留） |
| `field-carriers-reproducible` | metric | reproducibility | 是 | **pass** | 11 个 claims 必需字段的载体普查可复算，且零载体字段被显式登记 |
| `field-carriers-no-carrier-listed` | caliber | completeness | 否 | **pass** | 四个零载体必需字段（承载问题）在门里留有未决格 |
| `fp-decomposition-sums` | metric | reproducibility | 是 | **pass** | 假阳性三分（角色外/坐标未绑/齐备不匹配）之和 == 裁定的 incorrect 总数 |
| `release-tolerance-reproducible` | metric | reproducibility | 是 | **pass** | 放行线容忍度表（每条线可再容忍的新增假阳性数）可复算 |
| `release-candidates-consistent` | metric | consistency | 否 | **pass** | 放行线候选值与口径测量值一致（不得出现未被测量的线值） |
| `superseded-artifact-drift` | bookkeeping | integrity | 否 | **divergence** | 被取代的 83 号产物未在草案态被改动（md 漂移须登记） |
| `superseded-signoff-consistency` | bookkeeping | consistency | 否 | **pass** | 83 号 signoff md 的签署栏与其 JSON 签认状态一致 |
| `target-line-reachability` | metric | feasibility | 否 | **note** | 目标线（精度 0.80）在冻结池上的可达性被显式记录 |

## 逐项证据

### inputs-stable — pass

- 方法：逐条 sha256（gate.frozen_inputs ∪ manifest.inputs）
- 期望：`{"mismatched": {}, "missing": []}`
- 实测：`{"mismatched": {}, "missing": []}`

### pool-ledger-closed — pass

- 方法：Counter(judgement) 求和 + unresolved_count
- 期望：`{"total": 110, "ledger": {"matched": 20, "correct_extra": 36, "incorrect": 51, "duplicate": 3}, "unresolved": 0}`
- 实测：`{"total": 110, "ledger": {"matched": 20, "correct_extra": 36, "incorrect": 51, "duplicate": 3}, "unresolved": 0}`

### caliber-reproducible:D1_all_candidates — pass

- 方法：独立实现按 gate 的 rule 字符串重算，逐字段比对
- 期望：`{"kept_candidates": 110, "precision_contract_formula": {"numerator": 56, "denominator": 110, "value": 0.5091, "display": "56/110 = 0.5091"}, "precision_scorer_implemented_formula": {"numerator": 56, "denominator": 107, "value": 0.5234, "display": "56/107 = 0.5234"}}`
- 实测：`{"kept_candidates": 110, "precision_contract_formula": {"numerator": 56, "denominator": 110, "value": 0.5091, "display": "56/110 = 0.5091"}, "precision_scorer_implemented_formula": {"numerator": 56, "denominator": 107, "value": 0.5234, "display": "56/107 = 0.5234"}}`

### caliber-row-complete:D1_all_candidates — pass

- 方法：必需键存在性检查
- 期望：`{"kept_candidates": "<present>", "judgements": "<present>", "target_recall": "<present>", "per_source_precision": "<present>"}`
- 实测：`{}`

### caliber-recall:D1_all_candidates — pass

- 方法：候选 matched 去重计数 / 按源分组重算
- 期望：`{"target_recall": {"numerator": 20, "denominator": 20, "value": 1.0, "display": "20/20 = 1.0000"}, "per_source_precision": {"dca4bad7f85b": {"numerator": 21, "denominator": 34, "value": 0.6176, "display": "21/34 = 0.6176"}, "f16e7fde9553": {"numerator": 35, "denominator": 76, "value": 0.4605, "display": "35/76 = 0.4605"}}}`
- 实测：`{"target_recall": {"numerator": 20, "denominator": 20, "value": 1.0, "display": "20/20 = 1.0000"}, "per_source_precision": {"dca4bad7f85b": {"numerator": 21, "denominator": 34, "value": 0.6176, "display": "21/34 = 0.6176"}, "f16e7fde9553": {"numerator": 35, "denominator": 76, "value": 0.4605, "display": "35/76 = 0.4605"}}}`

### caliber-reproducible:D2_in_role_only — pass

- 方法：独立实现按 gate 的 rule 字符串重算，逐字段比对
- 期望：`{"kept_candidates": 81, "precision_contract_formula": {"numerator": 51, "denominator": 81, "value": 0.6296, "display": "51/81 = 0.6296"}, "precision_scorer_implemented_formula": {"numerator": 51, "denominator": 78, "value": 0.6538, "display": "51/78 = 0.6538"}}`
- 实测：`{"kept_candidates": 81, "precision_contract_formula": {"numerator": 51, "denominator": 81, "value": 0.6296, "display": "51/81 = 0.6296"}, "precision_scorer_implemented_formula": {"numerator": 51, "denominator": 78, "value": 0.6538, "display": "51/78 = 0.6538"}}`

### caliber-row-complete:D2_in_role_only — pass

- 方法：必需键存在性检查
- 期望：`{"kept_candidates": "<present>", "judgements": "<present>", "target_recall": "<present>", "per_source_precision": "<present>"}`
- 实测：`{}`

### caliber-recall:D2_in_role_only — pass

- 方法：候选 matched 去重计数 / 按源分组重算
- 期望：`{"target_recall": {"numerator": 20, "denominator": 20, "value": 1.0, "display": "20/20 = 1.0000"}, "per_source_precision": {"dca4bad7f85b": {"numerator": 18, "denominator": 25, "value": 0.72, "display": "18/25 = 0.7200"}, "f16e7fde9553": {"numerator": 33, "denominator": 56, "value": 0.5893, "display": "33/56 = 0.5893"}}}`
- 实测：`{"target_recall": {"numerator": 20, "denominator": 20, "value": 1.0, "display": "20/20 = 1.0000"}, "per_source_precision": {"dca4bad7f85b": {"numerator": 18, "denominator": 25, "value": 0.72, "display": "18/25 = 0.7200"}, "f16e7fde9553": {"numerator": 33, "denominator": 56, "value": 0.5893, "display": "33/56 = 0.5893"}}}`

### caliber-reproducible:D3_in_role_and_coordinate_complete — pass

- 方法：独立实现按 gate 的 rule 字符串重算，逐字段比对
- 期望：`{"kept_candidates": 36, "precision_contract_formula": {"numerator": 26, "denominator": 36, "value": 0.7222, "display": "26/36 = 0.7222"}, "precision_scorer_implemented_formula": {"numerator": 26, "denominator": 33, "value": 0.7879, "display": "26/33 = 0.7879"}}`
- 实测：`{"kept_candidates": 36, "precision_contract_formula": {"numerator": 26, "denominator": 36, "value": 0.7222, "display": "26/36 = 0.7222"}, "precision_scorer_implemented_formula": {"numerator": 26, "denominator": 33, "value": 0.7879, "display": "26/33 = 0.7879"}}`

### caliber-row-complete:D3_in_role_and_coordinate_complete — pass

- 方法：必需键存在性检查
- 期望：`{"kept_candidates": "<present>", "judgements": "<present>", "target_recall": "<present>", "per_source_precision": "<present>"}`
- 实测：`{}`

### caliber-recall:D3_in_role_and_coordinate_complete — pass

- 方法：候选 matched 去重计数 / 按源分组重算
- 期望：`{"target_recall": {"numerator": 12, "denominator": 20, "value": 0.6, "display": "12/20 = 0.6000"}, "per_source_precision": {"dca4bad7f85b": {"numerator": 13, "denominator": 13, "value": 1.0, "display": "13/13 = 1.0000"}, "f16e7fde9553": {"numerator": 13, "denominator": 23, "value": 0.5652, "display": "13/23 = 0.5652"}}}`
- 实测：`{"target_recall": {"numerator": 12, "denominator": 20, "value": 0.6, "display": "12/20 = 0.6000"}, "per_source_precision": {"dca4bad7f85b": {"numerator": 13, "denominator": 13, "value": 1.0, "display": "13/13 = 1.0000"}, "f16e7fde9553": {"numerator": 13, "denominator": 23, "value": 0.5652, "display": "13/23 = 0.5652"}}}`

### caliber-reproducible:D4_similarity_scoped_v1_draft_option — pass

- 方法：独立实现按 gate 的 rule 字符串重算，逐字段比对
- 期望：`{"precision_contract_formula": {"numerator": 56, "denominator": 65, "value": 0.8615, "display": "56/65 = 0.8615"}, "precision_scorer_implemented_formula": {"numerator": 56, "denominator": 62, "value": 0.9032, "display": "56/62 = 0.9032"}}`
- 实测：`{"precision_contract_formula": {"numerator": 56, "denominator": 65, "value": 0.8615, "display": "56/65 = 0.8615"}, "precision_scorer_implemented_formula": {"numerator": 56, "denominator": 62, "value": 0.9032, "display": "56/62 = 0.9032"}, "_keys_absent_in_record": ["kept_candidates"]}`

### caliber-row-complete:D4_similarity_scoped_v1_draft_option — divergence

- 方法：必需键存在性检查
- 期望：`{"kept_candidates": "<present>", "judgements": "<present>", "target_recall": "<present>", "per_source_precision": "<present>"}`
- 实测：`{"kept_candidates": "<missing>", "judgements": "<missing>", "target_recall": "<missing>", "per_source_precision": "<missing>"}`

### caliber-recall:D4_similarity_scoped_v1_draft_option — note

- 方法：候选 matched 去重计数 / 按源分组重算
- 期望：`{"target_recall": null, "per_source_precision": null}`
- 实测：`{"target_recall": {}, "per_source_precision": {}}`

### caliber-divergence:duplicate — divergence

- 方法：比较同一候选池上两个公式的分母
- 期望：`"单一口径（两式相等或其中一处被具名取代）"`
- 实测：`{"contract_formula": "56/110 = 0.5091", "implemented": "56/107 = 0.5234"}`

### sentinel-contract-subset — pass

- 方法：契约键前缀枚举 vs 门记录值
- 期望：`["NT-C11", "NT-C12", "NT-C13"]`
- 实测：`["NT-C11", "NT-C12", "NT-C13"]`

### sentinel-required-hit — pass

- 方法：matched_gold_id 集合成员判定
- 期望：`{"NT-C11": true, "NT-C12": true, "NT-C13": true}`
- 实测：`{"NT-C11": true, "NT-C12": true, "NT-C13": true}`

### sentinel-no-foreign — pass

- 方法：v1 提案集合 − 契约子集
- 期望：`["NT-C01", "NT-C03", "NT-C08"]`
- 实测：`["NT-C01", "NT-C03", "NT-C08"]`

### field-carriers-reproducible — pass

- 方法：逐字段非空载体计数 vs 门记录值
- 期望：`{"subject": 108, "metric": 102, "period": 74, "unit": 80, "value": 97, "factuality": 110, "attribution": 0, "perspective": 0, "source_stance": 0, "estimate_status": 0, "qualifier": 109}`
- 实测：`{"subject": 108, "metric": 102, "period": 74, "unit": 80, "value": 97, "factuality": 110, "attribution": 0, "perspective": 0, "source_stance": 0, "estimate_status": 0, "qualifier": 109}`

### field-carriers-no-carrier-listed — pass

- 方法：no_carrier 集合 vs 门的 open_decisions
- 期望：`["attribution", "estimate_status", "perspective", "source_stance"]`
- 实测：`{"no_carrier_fields": ["attribution", "perspective", "source_stance", "estimate_status"], "has_open_decision_C3": true}`

### fp-decomposition-sums — pass

- 方法：按判定与 reason_codes 分类求和，逐类比对记录值
- 期望：`{"incorrect_total": 51, "role_external": 24, "coordinate_unbound": 20, "structurally_complete_nonmatch": 7}`
- 实测：`{"incorrect_total": 51, "role_external": 24, "coordinate_unbound": 20, "structurally_complete_nonmatch": 7}`

### release-tolerance-reproducible — pass

- 方法：按 gates 记录的分母与线值重算整数容忍度
- 期望：`{"D2_line_0.60": 4, "D2_line_0.55": 11, "D1_line_0.50": 2}`
- 实测：`{"D2_line_0.60": 4, "D2_line_0.55": 11, "D1_line_0.50": 2}`

### release-candidates-consistent — pass

- 方法：release candidates vs 同口径 precision 值（契约式公式）
- 期望：`{"D2_basis_0.60": 0.6296, "D1_basis_0.50": 0.5091}`
- 实测：`{"D1_basis_0.50": 0.5091, "D2_basis_0.60": 0.6296}`

### superseded-artifact-drift — divergence

- 方法：83 MANIFEST 记录的产物哈希 vs 磁盘现值
- 期望：`{}`
- 实测：`{"claims-gate-v1-signoff.md": {"recorded": "c3f212032ef59d642d0344fe42c88d8df20f832ebbba6035e655339363b36d42", "on_disk": "7403d1dc754dc439b739f899ce804c3611190fd53f3b16b7c83f965f67d5ec7e"}}`

### superseded-signoff-consistency — pass

- 方法：md 签署栏文本 vs gate_v1.signoff（残留时间戳也算不一致）
- 期望：`{"json_signoff_null": true, "md_residual_signed_on": false}`
- 实测：`{"json_status": "draft_pending_human_signature", "json_signoff_null": true, "md_residual_signed_on": false, "md_carries_reviewer_name": false}`

### target-line-reachability — note

- 方法：各口径分子/分母上限 vs target_line
- 期望：`{"D1_all_candidates": {"max_achievable_precision": 0.5091, "note": "分子已固定（matched+correct_extra 不可增），分母不再增大的前提下这是上限"}, "D2_in_role_only": {"max_achievable_precision": 0.6296, "note": "分子已固定（matched+correct_extra 不可增），分母不再增大的前提下这是上限"}, "D3_in_role_and_coordinate_complete": {"max_achievable_precision": 0.7222, "note": "分子已固定（matched+correct_extra 不可增），分母不再增大的前提下这是上限"}}`
- 实测：`{"D1_all_candidates": {"max_achievable_precision": 0.5091, "recomputed": 0.5091, "target_line": 0.8, "reachable": false}, "D2_in_role_only": {"max_achievable_precision": 0.6296, "recomputed": 0.6296, "target_line": 0.8, "reachable": false}, "D3_in_role_and_coordinate_complete": {"max_achievable_precision": 0.7222, "recomputed": 0.7222, "target_line": 0.8, "reachable": false}}`


## 可行性分层（谓词：组件 × 类别 × 是否阻塞当前签认）

类别 ∈ {landed_now, needs_human_decision, needs_call_budget, not_executable_this_round}。

| 编号 | 组件 | 类别 | 前置 | 依据 | 阻塞当前 |
|---|---|---|---|---|---|
| F1-分母口径（C1） | 候选范围：材料范围（D1）还是 claims 角色范围（D2） | **needs_human_decision** | U 具名裁定 + （若取 D2）把 45 条 in-scope 候选的分类改写为可核验记录 | 候选池与金标均冻结；契约 scope_rules 规定范围内输出必须裁定、不得自动排除 | 是 |
| F2-duplicate 单源化（C2） | 契约文字公式（分母含 duplicate）vs 评分器实现（分母不含） | **needs_human_decision** | U 选一个源；改另一处须具名并留差异记录 | audit check `caliber-divergence:duplicate` 检出：56/110 vs 56/107 | 是 |
| F3-无载体字段读路径（C3） | attribution/perspective/source_stance/estimate_status 的 carrier/handling | **needs_human_decision** | 契约新版本（只增不删，沿 items 先例）；机制已在 v4.3 read_path 中存在但 applies_to 仅 material_items | 11 字段实测：四字段 0/110 载体；契约 read_path.roles.claims.implemented_in_this_revision=false | 是 |
| F4-用途分级（C4） | compare/calculate 由『零 reason 全或无』改为按受影响用途分级 | **needs_human_decision** | U 裁定（属改默认行为类） | 45/56 条正确记录带 reason ⇒ 现规则下仅 11 条可算；reason 当硬门会使召回掉到 12/20 | 是 |
| F5-阈值双线（C5/C6） | 目标线不动 + 新增放行线（功能线）与分源下限 | **needs_human_decision** | U 具名登记；禁止看到分数后再定值 | 容忍度表可复算：0.60⇒再容忍 4 条 FP；D2 上限 0.630<0.80 | 是 |
| F6-重跑产出新池 | 在冻结金标与同一口径下用新配置重跑 claims 抽取 | **needs_call_budget** | U 明确授权调用额度与计划冻结 | 冻结池上 0.80 不可达（D2 分子上限即 0.630）；这是唯一能让目标线可达的动作 | 否 |
| F7-一致性校验器 + 复算回归 | 哨兵恒等、口径可复算、分歧检出（工具 + 常驻测试） | **landed_now** | 无（零调用、只读、不改默认行为） | tools/check_claims_gate.py；27 项审核，阻塞失败 0 | 否 |
| F8-契约读取器按角色参数化 | load_contract_gate_requirements 支持 claims 角色（role_scope/target_total/哨兵子集） | **needs_human_decision** | claim 专属契约字段（target_total=20、NT-C 哨兵子集）须先由 C1/C3 定值并进契约新版本 | structured_scoring.py:435-525 硬编码 role_scope=MATERIAL_ITEMS 且要求恰 11 条 NT-I*；tests/test_corpus_contract_gate.py:177-217 断言该形态 | 是 |
| F9-生产侧接缝（角色边界/坐标绑定/去冗余） | claims 只产指标断言、坐标绑定、同坐标不重复渲染 | **not_executable_this_round** | 需要新池（F6）才能体现效果；在冻结池上只能做反事实上界 | D2 上限 0.630、D3 召回 12/20 ⇒ 反事实口径无法同时保住两轴 | 否 |

计数：{"needs_human_decision": 6, "needs_call_budget": 1, "landed_now": 1, "not_executable_this_round": 1}

## 未覆盖范围（显式声明）

- 本轮未核验：`.scratch` 下 evidence/01–82 的全部内容（未逐件复核）
- 本轮未核验：benchmarks/、workflows/、plugins/ 除 structured_scoring.py 与 claims_* 之外的行为
- 本轮未核验：冻结金标 20 条 claims 记录的语义正确性（沿用已签 Issue 29/30 结论，未重做审计）
- 本轮未执行：任何模型调用、生产 PG 访问、发布、query/delivery/context_use、M_main 消费
- 本轮未裁定：C1–C6 六格判据（全部保持 pending_human_decision）

## 结论

- 方案作为**口径与登记**方案可行：全部数字可由冻结输入复算，哨兵与契约恒等，分歧项可检出。
- 方案作为**不改判定即可过目标线**不可行：D2 分子上限 0.630 < 0.80，且该上限不依赖任何未定判据。
- 本轮已落地的只有 F7（校验器 + 复算回归）；F1–F5、F8 卡在 U 的六格判据，F6 卡在调用额度，F9 在候选冻结下无法执行。

