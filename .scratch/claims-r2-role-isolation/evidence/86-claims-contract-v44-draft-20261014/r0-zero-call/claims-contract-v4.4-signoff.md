# Claims 契约 v4.4 草案 · 签认件（六格提案）

状态：草稿，**未签认**。`status = draft_pending_human_signature`，`signoff` 三项为 null。
以已签 `scoring-contract-v4.3.json`（sha256:d7b4f8a81ef42e3cd5d619eae92bc34df7b7aa683d34aeba4f1a22719ae69a2f）为基，**只增叶子**；六项阈值逐字不变；
不改 frozen-gold / P1R5 已签裁定 / items 门 v3 的任何字节。

## 一、机检结论（可复跑本目录 `build_claims_contract_v44_draft.py`）

| 检查 | 结果 |
|---|---|
| 删除叶子 | 无 |
| 计划外改动叶子 | 无 |
| 六项阈值逐字不变 | 是 |
| role_sections.claims.target_total == 冻结金标 claims 目标数 | 是 |
| 载入器验证（临时副本置 frozen_signed） | claims scope=claims、哨兵 3 条、target_total=20；v4.3 上 claims 载入被拒：contract_role_section_missing:claims |

## 二、六格提案（请逐格签认或改写）

| 编号 | 提案 | 实测依据 |
|---|---|---|
| C1 | claims 角色范围 = 指标断言（`kind != opinion` 且 value 非空）；剔出项须在 items/relations 侧登记覆盖 | D1 56/110 = 0.5091 → D2 51/81 = 0.6296；分源 源1 0.5893 / 源2 0.7200；召回 20/20 = 1.0000 |
| C2 | 精度分母单一源 = 含 duplicate（与已签 P1R5 的 56/110 = 0.5091 一致）；评分器 `RoleMetrics.precision` 计入 duplicate_fp | 契约文字 56/110 = 0.5091 vs 实现 56/107 = 0.5234 |
| C3 | claims 读路径：六字段有载体；attribution 移出匹配基；perspective/source_stance/estimate_status 记 human_only | 11 字段载体实测（四字段 0/110） |
| C4 | compare/calculate 由全或无改为按受影响轴撤去 | 现规则下仅 11/56 条可用；reason 当硬门召回掉到 12/20 |
| C5 | 目标线不动（0.85/0.80/0.80/0 + 哨兵 NT-C11/C12/C13）；新增放行线 0.60 / 分源 0.55 | 容忍度：再容忍 4 条新增假阳性 |
| C6 | 登记「目标线在冻结池不可达」，要达标须另立授权的重跑 | D2 分子上限 51/81 = 0.6296 < 0.80 |

## 三、硬约束（不属于待裁）

- 签发后 `role_sections.claims` 才生效；未签认时 `load_contract_gate_requirements(..., role=claims)`
  以 `contract_role_section_missing:claims` 失败关闭（已实测）。
- C3/C4 本草案**只提案、未实施**；未签认前不改任何默认行为。

## 签名

reviewer: xyl    adjudicator: xyl    signed_on: 2026-10-14
