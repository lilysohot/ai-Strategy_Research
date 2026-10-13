# 补跑 · 双臂实验授权文书（待 U 批准）

- 起草：2026-10-13　零调用起草；**执行阶段含真实模型调用** ⇒ 必须 U 具名授权
- 状态：**批准**（未执行任何调用，未跑探针）
- 取代：`63-rerun-authorization-20261012/r0-zero-call/rerun-authorization.md` 的**单一模型补跑**定位
- 依据：`22-doubao-lite-provider-ceiling-20261010`（终态 `route_closed`、items `attempts=0`）、
  门 28 授权四项（含模型项）、Issue 34/41 的「跨臂不可比」纪律

## 〇、性质变更（必须先看）

单次补跑的目的是**救回丢失的 7 条候选**，前提是**与原运行同源**（模型 `deepseek-v4-flash`、同协议），
否则产出无法与原 222 条合并出分。改用 doubao 后，它不再是"补跑"，而是**一次模型对比实验**。

故拆为两臂：

| 臂 | 模型 | 性质 | 产出能否并入本次出分 |
|---|---|---|---|
| **control** | `deepseek-v4-flash`（门 28 已授权值） | **这才是补跑** | **可以**（与原 222 条同源） |
| **treatment** | `doubao-seed-2.1-lite`（U 指定） | 模型能力实验 | **不可以**，只出对比报告 |

⇒ **要救回那 7 条，靠的是 control 臂。** treatment 臂回答的是"doubao 能不能用"，不参与出分。

## 一、为什么不能单臂用 doubao 补跑（三条）

1. **前科**：22 号实测 doubao-seed-2.1-lite 终态 `failed_protocol_and_signed_semantic_gate_route_closed`，
   **items 角色 `attempts = 0`**（一次都没跑成）、relation 4 次尝试中 2 包 failed、签认用例 37 < 40。
2. **纪律**：换模型 ⇒ 跨臂数据不可比；把 doubao 产出混进原链路出分，26/48 这个数会变成混合体，无法归因。
3. **授权**：门 28 授权四项含"模型"项，原授权是 `deepseek-v4-flash`；doubao 是**新的授权事项**。

## 二、探针（Step 0，先于一切预算）

`.env` 已被改动、且并行会话仍会改 ⇒ **两臂开跑前各做一次探针**，失败即中止，不投预算。

| 步骤 | 内容 | 成本 |
|---|---|---|
| **0a 配置核对** | 打印 resolved `STRUCTURED_EXTRACTION_{PROVIDER,MODEL,BASE_URL}` 与 key 是否设置（不打印密钥） | **0 调用** |
| **0b 端点探针** | 经同一条抽取代码路径发 **1 次 1-token 调用**，记录 `request_model` / `response_model` / 错误码 | 每臂 1 次 |

命令（0a / 0b 由 `probe_extraction_endpoint.py` 提供；`--no-call` 只做 0a）：

```bash
uv run python <本目录>/probe_extraction_endpoint.py --no-call     # 0a，零调用
uv run python <本目录>/probe_extraction_endpoint.py --arm control  # 0b，1 次调用
```

**逐臂记录**：端点 host、模型名、`request_model`、`response_model`、探针时间戳。
任一端点 401/404 ⇒ 该臂中止（2026-10-12 该 ark key 曾 401，不要凭"上次能用"推断）。

## 三、执行参数（两臂共用，除模型外单变量）

| 参数 | 值 | 依据 |
|---|---|---|
| 授权人 | **U（xyl）** | 门 28 授权四项 |
| 日期 | 2026-10-13 | |
| packet 集合 | 丢包区 `industrial-fulian-md char:5246–5537`；**+I06/I41 与否取决于 B-1 裁定** | 32 号 residual-attribution |
| `attempts_max` | 沿用门 28 `execution_requirements`，**不得自行放宽** | 门 28 |
| **自动重试** | **必须 ≥1**（原失败根因是 `automatic_retries=0`） | 63 号退出判据 1 |
| 节流 | 间隔 **20s** | run-2 授权（run-1 因突增流量 429 失败） |
| 幂等 | 同一 packet 重复执行不产生重复计数 | 63 号退出判据 1 |
| 输入隔离 | 只给原文单元＋来源元信息＋角色提示；**不输入金标、目标 ID、标注结果** | 63 号退出判据 3 |
| 输出落位 | **新目录**，不覆盖 run-1/run-2/v6（write-once） | 63 号退出判据 2 |
| 预算上限 | **待你填**（建议：每臂 = 包数 × 3 次调用；总 = 2 × 每臂） | — |

## 四、退出判据（预注册，先于执行）

1. 两臂探针各自通过（0b 成功，逐臂记录端点与模型名）。
2. 自动重试开启且同一 packet 重复执行幂等（不重复计数）。
3. 成功产出目标 packet 的候选；产出落新证据目录，原产物字节不变。
4. 输入隔离成立（无金标输入）。
5. 失败仍记录为失败，并区分 **基础设施／模型行为／我方契约信号** 三类，不静默。
6. 产出后重跑 `tools/check_freeze_chain.py` 与装配器自检，保持 exit 0。
7. **control 臂候选进入装配与出分**；**treatment 臂候选一律不进装配**。
8. treatment 臂若 `items attempts` 成功 = **0**，直接判"该模型在本链路不可用"，**不再追投预算、不重试**。
9. 两臂指标按**同一组指标**输出，逐臂记录，不做跨臂合并。
10. 分源（md/docx）分别统计，不合并表述。

## 五、treatment 臂的对比指标（只出报告）

沿用 40 号 `route-b-experiment-protocol.json` 的指标族：

- items 角色成功 attempt 数、协议违规批次数（control vs treatment）
- `quoted_other` / `condition` / `behavior` / `speech_role` 的产出率
- 逐字引文可达率（`evidence_quote` 是否能在原文片段中命中）
- fail-closed 是否被放大

## 六、不做（范围外）

- 不改金标、不改契约、不改阈值、不改提示词（**唯一变量是模型**）；
- 不放宽 fail-closed；不启用 `response_format`；
- 不把 treatment 臂产出并入本次出分；
- 不代做人工裁定；未获授权前不发起任何调用。

## 七、签认栏

- 授权人：　　　xyl　　　日期：2026-10-13
- 预算上限：control 30 次调用　／　treatment 30 次调用
- B-1 裁定（I06/I41：x 纳入补跑　☐ 判 `no_supported_item`　☐ 关联方法差异）
- 结论：x批准双臂执行（先跑探针）　☐ 仅批准 control 臂补跑　☐ 仅批准探针　☐ 退回修改
- 备注：模型使用 doubao-seed-2.1-lite 替换 deepseek-v4-flash

> 批准后执行序：**探针 → control 臂 → treatment 臂 → 对比报告**；
> control 产出交你裁定 → 装配 → 出分（标注结构性缺口 N 条）。
