# A/B 对比报告：doubao-seed-2.1-lite（调参）vs deepseek-v4-flash（control）— 2026-10-13

## 〇、设定

- 同样本（三包：base-7critical / NT-I06 / NT-I41）、同协议（material-atomic-jsonl-v5）、同代码路径、同 attempts（≤2）、同节流 20s。
- doubao 臂：Ark `/api/plan/v3`，`max_output_tokens 262144 + thinking=disabled`（U 授权的声明式第二变量）。
- deepseek 臂：Ark `/api/plan/v3`，`deepseek-v4-flash` + gate-28 冻结参数逐字沿用（`262144 / reasoning_effort=minimal / timeout 300`）。
  - **host 偏差记录**：gate-28 冻结 profile 为 `api.deepseek.com`；本次为 U 改置的 Ark 托管同名模型（响应 `deepseek-v4-flash-ga-260731`）。
- control 产出**可进出分**（这是 control 臂存在的意义）；treatment 产出不进出分。

## 一、结果矩阵

| 包 | deepseek-v4-flash | doubao-seed-2.1-lite（调参） |
|---|---|---|
| base-7critical（7 槽） | `invalid`（att=1，comp 2416） | `invalid`（att=1，comp 2573） |
| NT-I06（11 槽） | **`valid/accepted/candidate`**（att=2，comp 2070） | **`valid/accepted/candidate`**（att=2，comp 2488） |
| NT-I41（1 槽） | **`valid/accepted/candidate`**（att=1，comp 171） | **`valid/accepted/candidate`**（att=1，comp 194） |

**两臂接受/拒绝模式完全一致，token 成本同量级（deepseek 略省 8–12%）。**

## 二、核心发现：base 包的阻塞是「模型无关」的（修正此前判断）

两个模型在 base 包以**逐字相同的拒收码**失败：
`["relations_not_requested", "atomic_obligations_incomplete", "role_scope_not_fully_covered"]`

- 这**推翻**了 r2 报告里「doubao 对该片段能力不足」的定性——gate-28 授权的同族模型 deepseek-v4-flash 同样失败；
- 失败的公共因子是**包/协议设置**：质量门要求对单元的原子义务**完整覆盖**，而两个模型单次响应都做不到；
- 另一个一致点：两臂 base 都只跑了 1 次尝试——协议违规是终态（fail-closed 不重试），重试只对传输类失败生效（NT-I06 的 attempt2 即传输重试）。

## 三、对项目的三条推论

1. **换模型解决不了 base 包**：7 条 critical 的抽取缺口不是模型选型问题，需要协议层动作（拆包/降低单响应覆盖要求/累积式尝试等），且必须走具名协议变更，不得放松 fail-closed。
2. **NT-I06 + NT-I41 的 control 候选已产出**（deepseek，`output_enters_scoring=True`）：可进入装配与人裁定的下一环。
3. **模型选型结论**：在同等参数预算下 doubao 与 deepseek 表现等价；doubao 需 `thinking=disabled` 才能对齐（否则推理 token 挤占输出导致截断，见 r2 报告）。

## 四、执行台账

| 项 | deepseek（control） | doubao（treatment） |
|---|---|---|
| 本次调用 | 4 + 1 参数探针 | 4（r2） |
| 累计 | 5 / 30 | 8 + 探针 4 = 12 / 30 |
| 产物目录 | `r3-control-live/` | `r2-treatment-adjusted/` |
