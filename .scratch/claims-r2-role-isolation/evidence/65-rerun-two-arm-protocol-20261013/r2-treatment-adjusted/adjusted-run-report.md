# Treatment 臂调参补跑报告（r2）与 A/B 对比 — 2026-10-13

## 〇、授权与参数变更声明

- **授权**：U（xyl）2026-10-13 口头指示「当前出现的情况自己去调整一下，token 可以放大限制。doubao 做一次补跑，DEEPSEEK 来一次，做一次 AB 测试」。
- **声明式偏差（第二变量）**：treatment 臂在「单变量=模型」之外新增 `thinking=disabled`（Ark 原生开关，adapter 原生支持该形状）。control 臂若执行，将**逐字沿用** gate-28 冻结参数（`max_output_tokens 262144 / reasoning_effort minimal / timeout 300`），不带 thinking 参数。
- **动机**：r1（未调参）三包中 base 协议违规、NT-I06 传输结局未知；usage 显示 doubao 每包烧 3.5k–12k reasoning tokens，疑似把 8192 输出预算吃光导致正文截断。

## 一、参数验证探针（1 次调用）

`RequestOptions(max_output_tokens=64, thinking="disabled")` → Ark 接受：`reasoning_tokens: 0`（此前 117–3536）、**`finish_reason: "stop"`**（此前恒为 `"length"`）。

**截断假说成立**：r1 的失败机制确认为「推理 token 挤占输出预算」。

## 二、A/B 结果（同包同协议，仅参数不同）

| 包 | r1（8192 + 思考开） | r2（262144 + 思考关） | 变化 |
|---|---|---|---|
| base-7critical（7 槽） | `succeeded/invalid/unpublished`，completion 14907 | `succeeded/invalid/unpublished`，completion 2573 | **仍 invalid**，但原因已变（见三） |
| NT-I06（11 槽） | `outcome_unknown/unpublished`（attempt2 传输死亡） | **`succeeded/valid/accepted/candidate`**，completion 2488 | 修复 |
| NT-I41（1 槽） | `accepted/candidate`，completion 3724 | `accepted/candidate`，completion 194 | token −95% |

- r2 调用：4 次（base 1 + I06 2 + I41 1）；treatment 臂累计 8 次（上限 30）。
- 附带说明：NT-I06/base 计划里各有一个 `claims` 任务显示 `blocked/CS_BUDGET_EXHAUSTED`——这是 claims 角色 `max_attempts=0` 的正常表示（角色禁用），`plan_consistent=true`，非缺陷。

## 三、base 包残余 invalid 的定性（关键）

拒收细节（store 拒收记录）：`reason_codes = ["relations_not_requested", "atomic_obligations_incomplete", "role_scope_not_fully_covered"]`。

- r1 的 invalid 可疑归因于**截断**（14907 completion、finish=length）；
- r2 在**无截断**（finish=stop、2573 completion、0 reasoning）下**仍然 invalid**，且拒收码指向**覆盖不全**（原子义务不完整、角色范围未全覆盖）——
- ⇒ **这是模型能力信号，不是参数问题**：doubao-seed-2.1-lite 对该 7 槽片段无法产出覆盖完整的 material-atomic-jsonl-v5。与 22-run「failed_protocol 路线闭合」结论一致。

## 四、对 control 臂（deepseek）的意义

1. run-1 的 deepseek 输出本就协议有效（丢包纯因传输 retries=0），gate-28 冻结参数（262144/minimal）无需调整；
2. control 臂预期：三包 → accepted/candidate → **可与原 222 条合并** → P01 装配 → 人裁定 → 进出分（这是唯一能抬召回天花板 0.542 → ≤0.833 的路径）；
3. treatment 产出（含 r2 的 NT-I06/NT-I41 两条 accepted）**依旧不进出分**。

## 五、执行台账

| 项 | 值 |
|---|---|
| r2 调用 | 4（+1 参数探针） |
| treatment 臂累计 | 8 + 探针 3 = 11（上限 30） |
| control 臂 | 0（30 未动用，待 U 确认） |
| in_place_edits | 0 |
| 产物 | `r2-treatment-adjusted/{base-7critical,NT-I06,NT-I41}/{snapshot,plan,freeze,summary}.json`、`arm-run.json`、本报告 |
