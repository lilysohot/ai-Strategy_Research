# Claims 预注册判据 v4 修订（104 号）· 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`。
本件只做一件事：把阶段 2 止损项 `unbound_union` 从**闸门**改为**诊断**（只报告，不阻断）。
零模型调用；不改 95 / 99 / 101 号任何字节（99 号保留为其自身的已签记录）。

## 一、改了什么（仅此一项）

| 位置 | v3（99 号，现行） | v4（本件） |
|---|---|---|
| `stage2_proxies` | 4 项：角色外候选 = 0 / **未绑并集 ≤ 54 × 0.5** / 冗余渲染 = 0 / 缺字段无码 = 0 | **3 项**：角色外候选 = 0 / 冗余渲染 = 0 / 缺字段无码 = 0 |
| `unbound_union` | 闸门（quality proxy） | **诊断**（`report_only_proxies`，`gating=false`，baseline 54 与谓词原样保留） |
| `coverage_rule` | 四条治疗规则 ↔ 四个止损项一一对账 | 对账要求限定为仍在 `stage2_proxies` 中的代理；T2 保留为诊断读数的 owner |

## 二、为什么改（101 号零调用实测）

- 冻结池上 `unbound_union` 实测 **54 → 52**，达不到预注册的 **≤ 27**（T2 的确定性部分只补到 4 条）。
- 并集构成里 `matched / correct_extra` 占多数 ⇒ 它量的是**标注覆盖率**，不是精度代理：减半它
  **既不是过放行线的必要条件，也不是充分条件**（决定去留的是 FP / `incorrect` 那一支）。
- 它是阶段 2 四项里**唯一还亮红**的一项，因而单点阻断唯一实跑；其余三项已由 T1/T3/T4 落地回放达成。

U 于 2026-10-14 裁示：改为诊断项。以下为随之生效的读法变更登记。

## 三、没改什么（逐条冻结）

- A/B/C 三档的线值 **0.80 / 0.60** 与质量护栏条款；
- 读数轴 4 项与主指标分子/分母定义（分子 = matched + correct_extra，与已签 C2 同源）；
- 治疗规则 T1 / T3 / T4 及其闸门；
- 预算请求形态（ceiling 仍为 null；预算落在 103 号）、金标冻结、判据数值；
- `evidence_chain.proxies` 的基线计数（**54 仍是基线**，改的是用法不是值）。

## 四、生效方式（避免纸面生效）

1. U 在本件末尾签署（`reviewer` / `adjudicator` / `signed_on`）；
2. `apply_prereg_v4_signoff.py` 生成生效件 `claims-preregistration-v4.json`
   （`status=frozen_before_execution`，签认块指向本签认件哈希；**未签一律拒绝**，且不代填任何签名字段）；
3. 阶段 2 由 `stage2_under_v4.py` 执行：它以生效件为判据、委托 102 号的阶段 2/3 逻辑
   ⇒ 行为跟随 v4，**102 号字节不动**。

## 五、登记的对既有记录的取代读法

| 被取代的读法 | 记录 | 取代后读法 | 记录字节 |
|---|---|---|---|
| `targets.unbound_union = ≤ 27` 且 `unbound_union_passed = false` | 101 号 landing-record | 诊断读数：仍测量、仍报告，但不作为进入阶段 3 的条件 | **不改** |

## 签名

reviewer:    xyl        adjudicator:   xyl         signed_on: 2026-10-14
