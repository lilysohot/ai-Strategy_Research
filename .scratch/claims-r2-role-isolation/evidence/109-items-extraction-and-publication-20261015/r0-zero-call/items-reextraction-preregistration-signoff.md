# items 重抽预注册件（109 号 P1）· 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`。
零模型调用。P2（活跑重抽）在本件签认（`frozen_before_execution`）前禁止起跑。

## 一、本件写死了什么

判据取值**全部锚定已签件**，本件只做引用 + 复述 + 新增两格执行有效性止损：

- 阈值六项：0.85 / 0.80 / 0.80 / 0 + accepted 40/20，target 48
  ← `evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json`（`340b312d…`）
- 哨兵 11 条：NT-I13/15/17/29/35/37/38/39/42/43/48 ← 同上（r2 修订版 16→11）
- 评分轴 = 现行 `SIGNED_SCORING_CONTRACT_PATH`（契约 v4.3，`d7b4f8a8…`）；
  ADJUDICATED 模式、零金标注入。
- relations 不抽不评（OPEN-2=C 已签）。

## 二、新增格（assistant 采择，签认时可否决）

1. **阶段止损只含执行有效性两闸**：两源各有 ≥1 候选（空池 = 结构失败）、
   material_items 任务零失败。模型质量量（候选多寡、槽位覆盖等）全部 report-only——
   claims 101 号教训：对代码确定性修不到的量设闸会恒挂。
2. Stage-1 建议器证据链权重固定（0.45/0.35/0.1/0.1/0.05，42 号同款），禁金标注入。
3. 92 号 29 条 pending_coverage 逐条入工作表 checklist，有候选入裁定、无候选记
   no_candidate，不就地丢弃。
4. 预算：本件 ceiling 叶**保持空白**（已签件不回填）；数值在 109 号预算授权件
   （1,000,000 total_tokens，`96949b73…`，stated_effective_pending_countersignature）。
5. attempts 历史参照 md 10 + docx 14（门 32 冻结计划）；重排批次超出该参照时
   冻结件拒绝生成、须 U 另裁。

## 三、签认效力

- 本件签认 → `frozen_before_execution`，prepare（冻结计划）可写、P2 可在预算闸门下起跑；
- 线值/哨兵/止损规则在执行后不得放宽（`scope_constraints`）；
- 阈值与已签件逐字不一致时本件不得签认（复述核对义务在签认动作本身）。

## 签名

reviewer:    xyl      adjudicator:     xyl     signed_on: 2026-10-15
