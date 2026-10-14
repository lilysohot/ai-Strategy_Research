# Claims 治理层方案（93 号）· 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`。
本件只做三件事：把判据的**载体**拆出来单独裁、登记 91 号那处更正、给出治理服务执行的四条规则。
不改 83/84/88/90/91/92 号或任何冻结件的字节；零模型调用。

## 一、为什么要单独做这一件

判据的「取值」签了，判据的「载体」没签 —— 于是每遇到一个新数值或新词，就回到同一个问题：

| 概念（同一件事） | 第一次 | 第二次 | 第三次 |
|---|---|---|---|
| claims 能否借 items 的数值 | OPEN-A：40/20 平移？ | C5：目标线「逐字恒等」 | **M1** |
| 分源精度轴是否存在 | C5：放行线加 0.55 | D-2：契约六项无该字段 | **M2** |
| 缺字段时撤什么用途 | OPEN-C：四零载体字段 | C4：按轴撤用途 | **M3** |

## 二、三格（请逐格填值并签名；实测后果见 `claims-governance-plan.json` 的 `cells[].options`）

**填法：只在下面三行等号右侧写枚举值（原样照抄，不要改写其它文字；不要留 `____`）。**

```
M1 = ____            # a_transplant | b_scaled_floor | b_scaled_ceil | c_diagnostic
M2 = ____            # exists | report_only
M3 = ____            # O1_status_quo | O2_remap_two_codes | O3_extend_vocabulary
```

| 编号 | 待裁（载体问题） | 选项与实测后果 | 我的建议 |
|---|---|---|---|
| M1 | 两个 accepted 条数下限如何派生 | `a_transplant` 平移 40/20（池只有 20/10 ⇒ 算术不可满足，放行线多 3 项阻断）／ `b_scaled_floor` 17/8 ／ `b_scaled_ceil` 17/9 ／ `c_diagnostic` 仅诊断（须契约语义变更） | b_scaled_floor（并在同格定死取整方向） |
| M2 | 分源精度轴是否存在 | `exists` 进 gating（须契约加字段 + 新 P03 绑定记录）／ `report_only` 只报告 | report_only |
| M3 | C4 的 cite 侧轴如何落地 | `O1_status_quo` 现状 11/56 ／ `O2_remap_two_codes` 改挂 attribution → 26/56（+15，风险：条件/否定语境断言变可算）／ `O3_extend_vocabulary` 扩下游词表（可表达 cite 侧轴，不放行计算） | O1 或 O3；O2 不建议 |

## 三、四条规则（治理服务执行层）

- **R1** 治理只阻断「断言」，不阻断「动作」：执行可继续，带未裁轴的结论须标 `pending_caliber`。
- **R2** 未裁轴 fail-closed = 拒绝正面断言，**不是**强取最严值去阻断执行。
- **R3** 回填必须重算：轴裁完后受影响的结论必须用新口径重算并重签，旧分只作历史证据。
- **R4** 到期即转报告项：登记 `owner` + `decide_by`，到期未裁 ⇒ 转 `expired_to_report_only`，不自动放行。

## 四、91 号更正登记（不改其字节）

`evidence/91-.../claims-gate-v3.json` 的 `verdict.release_line`：

- 现状：`verdict = PASS`，`precondition = "D-1 ≠ a"` ⇒ 已签结论以未裁轴为前提。
- 更正读法（R1/R2）：`D-1` 裁定前，该行读作 **`pending_caliber`**，不得读作 PASS。
- 不变项：`measured` 值（0.6296 / 0.5893 / 0.7200）与目标线 FAIL 终态一律不变。
- 更正记录见 `governance-corrections.json`（含 91 号 sha256 绑定）。

## 五、硬约束（不属于待裁）

- 例外登记只能豁免「已登记且规则已生效」的产物；R1/R2 未签认前，校验器只检出、不阻塞。
- 三格 `value` 一律为 `null`；本件不代填、不预填、不代签。

## 签名

reviewer: ____________    adjudicator: ____________    signed_on: ____________
