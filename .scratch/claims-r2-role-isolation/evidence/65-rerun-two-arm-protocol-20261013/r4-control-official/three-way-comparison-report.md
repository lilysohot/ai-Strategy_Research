# 三臂对比报告：doubao（调参）vs deepseek-Ark vs deepseek-官方 — 2026-10-13

## 〇、设定

同样本三包、同协议（material-atomic-jsonl-v5）、同代码路径、attempts ≤2、节流 20s。

| 臂 | 模型（响应名） | 端点 | 参数 |
|---|---|---|---|
| r2 treatment | doubao-seed-2-1-lite-260915 | Ark /api/plan/v3 | 262144 + thinking=disabled（U 授权调参） |
| r3 control | deepseek-v4-flash-ga-260731 | Ark /api/plan/v3 | gate-28 冻结值逐字沿用 |
| r4 control-official | deepseek-flash | **官方 api.deepseek.com** | gate-28 冻结值逐字沿用 |

**模型名偏差记录**：gate-28 冻结名 `deepseek-v4-flash`；U 官方配置为 `deepseek-flash`（且为重推理模型——ping 即带 reasoning tokens）。按 U 授权执行，偏差如实记录。

## 一、结果矩阵（含 r1 历史）

| 包 | r1 doubao(8192,思考开) | r2 doubao(调参) | r3 ds-Ark | r4 ds-官方 |
|---|---|---|---|---|
| base-7critical | ❌ invalid | ❌ invalid | ❌ invalid | ❌ invalid |
| NT-I06 | ❌ 传输未知 | ✅ | ✅ | ✅ |
| NT-I41 | ✅ | ✅ | ✅ | ✅ |
| base completion | 14907 | 2573 | 2416 | **11697** |
| I06 completion | 14038 | 2488 | 2070 | **22381** |
| I41 completion | 3724 | 194 | 171 | 2363 |

## 二、三个硬结论

**1. base 包阻塞被四重独立配置证实为「模型无关 + 参数无关」。**
doubao×2 种参数 + deepseek×2 个 host，全部以同一拒收码失败（`atomic_obligations_incomplete` / `role_scope_not_fully_covered`）。继续换模型或调 token 都无意义——必须走协议层变更（拆包/累积覆盖/单响应覆盖要求修订），且需具名签认。

**2. I06/I41 在所有完成传输的配置下全部 accepted。**
这两包的候选获取是稳定可复现的：doubao、deepseek-Ark、deepseek-官方三臂结论一致。

**3. 官方 deepseek-flash 成本高出约 10 倍。**
它是重推理模型（`reasoning_effort=minimal` 仍烧 2k+ reasoning tokens/包）：base 11697 vs Ark 2416、I06 22381 vs 2070。**产出质量未见差异，成本差一个量级**——若只为产出候选，Ark 托管的 deepseek-v4-flash 是更优选择；gate-28 冻结 profile 本就是该模型。

## 三、执行台账

| 臂 | 本次调用 | 累计/上限 |
|---|---|---|
| r4 官方 | 4（+1 探针） | 5 |
| control 合计（r3+r4） | 9 | 9/30 |
| treatment 合计（r1+r2+探针） | — | 12/30 |

- r4 产物：`r4-control-official/`（`output_enters_scoring=True`，I06/I41 候选在 store）。
- in_place_edits：0（全部新目录）。
