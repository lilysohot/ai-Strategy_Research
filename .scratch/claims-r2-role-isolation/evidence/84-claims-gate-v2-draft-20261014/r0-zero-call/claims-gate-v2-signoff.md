# Claims 门 v2 草案 · 签认件（口径先行稿）

状态：草稿，**未签认**。`status = draft_pending_human_signature`，`reviewer/signed_on` 留空。

取代 83 号 v1 草案。本件同 v1 一样不改任何冻结字节；差别是**先定口径、再谈数值**，
并且把不可恢复样本的处置写成分类登记，而不是把它们硬判通过。

## 一、本件主张的三件事

1. **回召侧没有可放宽的空间**：claims 在冻结池上 target_recall = 20/20 = 1.000。
   精度侧 51 条 `incorrect` 是**被具名裁定为错**的产出（不是"措辞不同但正确"，后者已入
   `correct_extra` 36 条），所以放宽等价性判定只会把错判成对，不能当修复。
2. **冻结池上目标线不可达**：保持召回的口径（D2）下分子上限 = 51/81 = 0.630，
   分源更差（源1 0.589）。因此 0.80 / 源 0.80 在本池上要么靠 D4（按与金标相似度删负例）
   拿到纸面 0.86，要么就是不可达。
3. **因此"放宽"必须放宽在正确的位置**：不动目标线，另立**放行线（功能线）**并预先具名登记；
   目标线继续如实报 FAIL 与余量。二者并列，禁止用放行线通过宣称质量达标。

## 二、待裁项（每格附实测候选值，不预填结论）

| 编号 | 待裁 | 实测候选 | U 裁定 |
|---|---|---|---|
| C1 | 分母取材料范围还是 claims 角色范围 | D1 = 见 JSON `calibers.D1_all_candidates`；D2 = 见 `calibers.D2_in_role_only` | |
| C2 | duplicate 是否计入分母（契约文字 vs 评分器实现不一致） | 两个公式值见 `calibers.D1_all_candidates` | |
| C3 | 四个零载体字段：补载体还是登记读路径 | `field_carriers` 中 status=no_carrier 的 4 项 | |
| C4 | compare/calculate 是否仍全或无 | 45/56 正确记录带 reason；当硬门则召回 12/20 | |
| C5 | 放行线数值与分源下限 | `thresholds.release_line`（含容忍度表） | |
| C6 | 目标线不可达的登记方式 | `thresholds.reachability_on_frozen_pool` | |

## 三、硬约束（不属于待裁）

- 哨兵清单 = 已签契约 `review_assertions` 的 NT-C* 子集（= 3 条）；83 号 v1 额外自造的
  NT-C01/C03/C08 属第二份哨兵源，本件不再保留。
- 不改金标、不改 P1R5 已签裁定、不改 items 门 v3 / 契约 v4.3 字节；零模型调用。
- 角色外候选移出 claims 判据时，必须在 material_items/relations 侧登记为待覆盖。

## 签名

reviewer: ____________    adjudicator: ____________    signed_on: ____________
