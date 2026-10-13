# R2 三项签认件（待签）

- 本件：`/home/administrator/FrontierAgent/.scratch/claims-r2-role-isolation/evidence/74-r2-gate-v3-contract-v43-draft-20261013/r0-zero-call/r2-signoff-review.md`
- 状态：**draft_pending_human_signature**（签认前不生效；门 v2 与契约 v4.2 字节不变）
- 依据：U 2026-10-13「先走 R2」
- 手续：沿用 v4.1 → v4.2 的「新版本记录 + 旧哈希留存」；本件是**唯一可签件**（并行会话若再出第二份 v3，必须先收敛为一份）

## 一、这份签下去等于什么（一句话）

在**不改任何阈值、不改冻结金标、不改样本、不改代码**的前提下：把高风险哨兵清单 **16 → 11**；给契约增补**「上下文唯一可恢复」**这一条读法；并对 **7 条**已抽出、曾被判 `correct_extra` 的候选**重新裁定**。

## 二、必读的三条边界

1. 六项阈值 `0.85 / 0.80 / 0.80 / 40 / 20 / 0` **逐字不变**；门的
   `scope_constraints.threshold_relaxation_after_execution_allowed` 仍为 `false`
   —— R2 之所以合规，正因为它**不动阈值**，只调整「必须覆盖」的哨兵范围与一条读法。
2. **签认只签条款**：不等于出分、不等于复验通过、不等于发布或语境完整。
3. **旧 verdict（门 33 = FAIL）不改写**；新出分必须在三项签认完成后另行据实生成，形成新记录。

## 三、修改清单（机器 diff 摘要）

| 对象 | 草案路径 | sha256 | 关键改动 |
|---|---|---|---|
| 门 v3 | `gate-v3.proposed.json` | `sha256:6a657fe8351b8c45ec4d30e3e97e9caa4fa41ac73c2d2c8ba45886fb99982705` | 哨兵 16→11（移出 NT-I09/I19/I45/I46/I47，逐条机制见 `high_risk_item_assertions_excluded`）；门内部 revision 6；`metric_basis` 与 `gold.scoring_contract_sha256` 推进一档至**已签** v4.2；新增 `contract_version_chase` 登记；阈值、执行要求、授权四项、scope_constraints 全部不变 |
| 契约 v4.3 | `scoring-contract-v4.3.proposed.json` | `sha256:c86660156476df5e928512b967689354afbe3b290bd20c2ff2557497fb5e9ded` | `matching.items` 增补「上下文唯一可恢复」条款及两项不适用情形；`review_assertions` 移出 5 条并移入 `review_assertions_excluded`；改钉门 v3（标 `provisional`，签认后回填）；新增 `registrations`（版本追逐 / 冻结金标侧绑定例外 / 取代 evidence/72 终态） |
| 改判草案 | `re-adjudication-draft.json` | `sha256:c4043b92219876bfced2d1505a5ad8155154ceff498499421b60be309b4c84a2` | **11 条契约形态裁定桩**（5 必需 + I23/I24 二选一 + 第 7 条四候选），落地时按勾选收敛为 **7 条** |

- 叶子 diff 件：`diffs.json`；机器校验件：`checks.json`（**18 项全部 PASS**，含「改判记录齐备契约 11 字段」「候选不得重复使用」「阈值逐字不变」「三处新签认字段留空」）
- 补充说明：契约侧的 `contract_version_chase` 与冻结金标侧绑定例外见件内 `registrations`

## 四、7 条改判（签这张 = 逐条认可）

**必需 5 条**

| gold | 源 | 候选 | 原裁定 → 拟裁定 | 恢复依据 |
|---|---|---|---|---|
| NT-I38 | 源2 | `itm_bf5fa66fb7be5a02` | correct_extra → matched | 金标把前半+后半并为一条，候选正确拆成两条；本候选承载前半 |
| NT-I39 | 源2 | `itm_a79b0be05f3456c3` | correct_extra → matched | 未提「海外产能」，但由同一证据包上下文唯一可恢复 |
| NT-I48 | 源2 | `itm_d96a4e7b052a89c7` | correct_extra → matched | 金标合并两半，本候选承载「税负可转嫁」半句 |
| NT-I26 | 源2 | `itm_a41addfcb6696346` | correct_extra → matched | 文本与金标逐字相同；承载主体「128 端口光波导」由上下文唯一恢复 |
| NT-I34 | 源2 | `itm_15c17f04855a28b3` | correct_extra → matched | 缺「2029—2030 年」与「材料未突破」，均可由同一证据包唯一恢复 |

**二选一：NT-I23 或 NT-I24**（二者共享同一候选 `itm_703720fdd5630e8b`，按一对一映射只能保留一条）

- NT-I23（`尚无固定的客户`）
- NT-I24（`德科立将其视为一个过渡型的产品`）

**第 7 条：必须且只能勾选一项**

- 选项甲：`I36_question_form` —— 需承认疑问句形态可承载该金标命题（候选 `itm_ec18c38405c7e17f`）
- 选项乙：`one_of_u_calibration_revoked` —— 需撤销你 2026-10-12 校准中的 **1 条**，四选一：
  NT-I45（`itm_42ffb8cedfa8d7ff`）/ NT-I46（`itm_09fc1a90e71fe5bf`）/ NT-I47（`itm_f2e29952886293c0`），
  三者候选与金标**逐字相同**，差别在 `source_stance`
- 选项丙（I23 与 I24 同时判 matched）：**契约无效** —— 一条候选抵扣两条金标，违反 `one_to_one_mapping`
  与契约 §8.1，故**不列入勾选**，本件不提供该情形下的通过

**明确不动**：`NT-I31`（候选已被 NT-I32 占用，与 I09/I19 同机制）；未被勾选的那些候选一律保持原裁定。

## 五、投影（**未签认投影，不是 verdict**）

| 第 7 条选项 | 总召回 | 源1 | 源2 | 哨兵 | 投影判定 |
|---|---|---|---|---|---|
| 选项甲 `I36_question_form` | 41/48 = 0.854 | 0.909 | 0.808 | 11/11 | PASS |
| 选项乙 `one_of_u_calibration_revoked` | 41/48 = 0.854 | 0.909 | 0.808 | 11/11 | PASS |

**签认时须一并知悉的代价**：余量极薄 —— 总召回余量 **+0.004**、源2 余量 **+0.008**。
另：改判只在 `matched` 与 `correct_extra` 之间搬移标签，**精确率、接受数（判据 3/5/6）不变**。

## 六、签认栏（三处都要填，第 7 条与二选一必须各勾一项）

- 复核人：　　xyl　　　　日期： 2026-10-13
- 结论：x 认可并签认 门 v3 + 契约 v4.3 + 7 条改判　　☐ 退回修改
- 二选一（I23/I24，必勾一项）：x `NT-I23`　　☐ `NT-I24`
- 第 7 条选择（必勾一项）：☐ 选项甲 `I36_question_form`　　x 选项乙 `one_of_u_calibration_revoked`
- 仅当选「选项乙」时填（三选一，必勾一项；选「选项甲」则全部留空）：x `NT-I45`　　☐ `NT-I46`　　☐ `NT-I47`
- 备注：

> 签认后由 `75-r2-signed-20261013/r0-zero-call/apply_r2_signoff.py` 落地到**新目录**；
> 门 v2 与契约 v4.2 字节不变，旧哈希在新版本记录中留痕。该脚本会：核对本件嵌入的三份草案 sha256；
> 要求「二选一」与「第 7 条」各恰好勾一项；把 11 条裁定桩收敛为 7 条并校验候选互不重复；
> 任一不满足即拒绝落地（不代签、不预填）。
