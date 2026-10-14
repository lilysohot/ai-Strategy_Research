# Claims 契约 v4.4 签认落地记录（机器生成）

日期 2026-10-14；零模型调用；冻结件全部未变：True；验证命令全绿：True。

## 一、已签契约

- `evidence/88-claims-contract-v44-signed-20261014/r0-zero-call/scoring-contract-v4.4.json`（status=`frozen_signed`，signed_by=xyl，signed_on=2026-10-14）
- 签署工具：`evidence/86-claims-contract-v44-draft-20261014/r0-zero-call/claims-contract-v4.4-signoff.md` `sha256:2b9636559896…`
- claims 哨兵 ['NT-C11', 'NT-C12', 'NT-C13']，target_total=20，C2 更正已附：True

## 二、验证命令

| 命令 | 退出码 | 判定 |
|---|---|---|
| `ruff_check_changed` | 0 | ok |
| `focused_tests` | 0 | ok |
| `import_smoke_stage1` | 0 | ok |
| `check_symbols` | 0 | ok |
| `p03_binding_verifier` | 0 | ok |
| `claims_gate_checker` | 0 | ok |
| `c2_duplicate_accounting` | 0 | ok |

## 三、更正登记（取代关系，旧字节未改）

| 编号 | 被取代的表述 | 取代为 | 依据 |
|---|---|---|---|
| C-1 | D1 记录『评分器实现公式 56/107 = 0.5234』 | 评分器实现 = 56/110 = 0.5091，与契约文字公式同源 | 88 号 verify_c2_duplicate_accounting.py（ledger: tp 20 / ce 36 / fp 54 / duplicate_fp 3 / fn 0） |
| C-2 | 『契约文字公式与评分器实现不同源』的分歧判定 | 同源；新审核项 duplicate-accounting-single-source（blocking）+ gate-recorded-implemented-formula（记录 84 号残留读数） | tools/check_claims_gate.py 现版本；tests/test_claims_gate_invariants.py |
| C-3 | 『须改 RoleMetrics.precision 计入 duplicate_fp』 | 单一口径 = 含 duplicate 的契约公式（已满足）；该实现改动作废 | 88 号 scoring-contract-v4.4.json 的 claims_precision_single_source.correction |
| C-4 | 87 号记录的改动文件快照哈希（C2 更正与 C3 接线前的字节） | 本记录 changed_files 为当前字节；87 号作为上一轮快照保留 | 本记录 changed_files |

## 四、状态变化（相对 87 号）

| 组件 | 87 号时 | 现在 | 说明 |
|---|---|---|---|
| C1-claims 角色范围 | 待签（agent 提案） | **已签（契约 v4.4 claims_scope）** | 分母口径取值已定；候选池分类的移出仍需在 items/relations 侧登记覆盖（未做） |
| C2-精度单一口径 | 待签（前提有误） | **已签 + 具名更正** | 契约文字与实现本就同源；实现改动作废，禁止补加 duplicate_fp |
| C3-claims 读路径 | 待签（只提案） | **已签 + 代码接线完成** | adjudication_assembly 惰性读取 read_path.roles_proposed.claims.carriers；实测 11 字段、一条真实裁定行进装配成功（matching basis 10 项、absent 4 项） |
| C4-用途分级 | 待签 | **已签，**未实现**** | 须先拆 reason_codes 为『阻断匹配』与『阻断用途』两类；属改默认行为 |
| C5/C6-双线阈值 + 不可达登记 | 待签 | **已签（契约 claims_thresholds）** | 目标线不动；放行线 0.60 / 分源 0.55；冻结池不可达已登记 |
| claims 门 artifact | 84 号草案（D4 行不完整 + 实现公式读数错误） | **仍为 84 号；须出 gate v3（补 D4 行、改读数、钉已签契约）** | 门与契约互钉：契约已签，门待生成并签 |
| claims 全量实跑（110 条） | 未做 | **未做** | 前置已解除（读路径可用），仍缺 doc→source_id 映射（P1R5 行无 source_id 字段，且 stage 词表为 human_adjudicated_candidate） |

## 五、仍未完成

- claims 门 v3（补 D4 行、改正读数、钉已签契约）并具名签认
- claims 全量实跑：需先建 doc→source_id 映射与 stage 词表适配，再出分
- C4 用途分级实现（改默认行为，已签待落地）
- C1 移出项的 items/relations 侧覆盖登记
- F6：是否授权重跑产出新池

## 六、未覆盖范围

- 未做 claims 池的 110 条全量评分（只做了 1 条装配冒烟）
- 未复核 .scratch/evidence/01–82 全部内容
- 未执行任何模型调用、发布、query/delivery/context_use、M_main 消费

## 七、冻结件逐条哈希

| 文件 | 未变 |
|---|---|
| `evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json` | True |
| `evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json` | True |
| `evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json` | True |
| `evidence/17-structured-extraction-convergence-closure-20261009/p1r5-claims-adjudication-v2/candidate-adjudications.signed.json` | True |
| `evidence/86-claims-contract-v44-draft-20261014/r0-zero-call/scoring-contract-v4.4.proposed.json` | True |
