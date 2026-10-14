# Claims 发布/消费闭环立项（106 号）· 签认件

状态：草稿，**未签认**。`status = draft_pending_human_signature`。零模型调用；不改 95–105 号任何已落地产物。

## 一、题目

把 105 号 A 档产出的 **93 条签认裁定**（matched 20 / correct_extra 64 / incorrect 3 / duplicate 6，精度 0.9032、召回 20/20）接入本仓的发布/消费闭环：**裁定工件进 ledger → 发布为 semantic publication → cite / compare / calculate 三用途各完成一次真实消费验收**。

## 二、现状（零调用探查结论）

- **代码层已齐平**：`publish_semantic` 全链（绑定校验/协议白名单/双模式）、查询用途 gate（compare/calculate 只认 claims 且有双重依赖门）、抽取侧用途撤除（claim_use_axes）、交付验证（verify_reference）都已存在并有测试。
- **真正的缺口四个**：①裁定工件 → ledger 的 claims 导入桥（items 有先例，claims 没有）；②受控发布入口（现在只能 Python 直调）；③compare/calculate 消费从未实测（81 号只验过 cite）；④生产 PG/web 读链（属生产放行，另立）。
- 新池可用度：**10 条可 compare/calculate**（matched 4 + correct_extra 6），83 条 cite-only；93 条 reason_codes 全部非空。

## 三、计划（S1–S5，全程零模型调用）

| 步 | 内容 |
|---|---|
| S1 | 新增 AcceptedClaims 裁定桥（对齐 items 先例 `AcceptedMaterialItems`；protocol 差异逐条登记，不得放宽机器门） |
| S2 | `publish_semantic` 发布（candidate 模式）；遇 quality 门受阻**停下报裁**，不自行放宽 |
| S3 | `structured/cli.py` 增受约束 publish 子命令（默认拒绝、显式授权） |
| S4 | 三用途消费验收：cite 回归 + compare + calculate 各 ≥1 条真实 `delivery → context_use → report_reference` 且 verify_reference 通过 |
| S5 | 落地记录 + 常驻测试；`--no-write`、幂等；items 链路回归不破 |

## 四、验收判据（执行前写死）

1. 93 条裁定全部入账，judgement 与 signed 件**差集为空**；
2. claims 发布成功（`semantic_publications` 落盘、`publication_status=published`、manifest 哈希登记）；
3. 三用途各 ≥1 条消费验收通过，无未登记例外；
4. 零模型调用；95–105 号与金标字节未动；`pytest -k corpus` 回归全绿；
5. 每个缺口的处置可查，无静默放宽。

## 五、待 U 裁（D1–D3）

- **D1 范围**：S1–S5 全做（推荐，闭环才算走通）？还是先只做 cite 部分？
- **D2 生产 PG/web 读链**：确认出范围（推荐，另行立项）？
- **D3 S2 遇阻的处置**：执行时按预设优先级处理，还是一律停下报裁（推荐）？

## 签名

reviewer:     xyl       adjudicator:     xyl       signed_on:2026-10-15
