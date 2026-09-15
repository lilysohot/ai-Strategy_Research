# R2 P4 有限 item 字段填写试验报告

日期：2026-09-14  
状态：**P4 未通过；单批 fail-stop 生效；P5/关系继续冻结**

## 1. 前置条件与冻结范围

P3-I 人工完成件 `r2-p3i-field-review-completed.json` 已通过严格校验：全局规则、8 个
speaker 映射及 8 条 value/unit 决策全部 approve；文件 SHA-256 为
`867124cbc515b9b529eeded959329c31e50e69c18d0ad51b95ab50cb83b1a587`。

P4 只在 scratch 中建立 source-only 请求、真实/回放/fake adapter、严格 JSONL 解析器、评分器与
SQLite 审计。生产 `_r2_*`、公共 parser、旧材料流程、PostgreSQL、入库、holdout 和关系均未接线。
模型请求不包含 `projected_fields`、target ID、人工决定或逐项期望值；只提供来源文本、上下文、有限
字段枚举及经批准的全局 unknown 轴词表。

执行前结果：

- P4 正反例 27 项通过；P3-H/P3-I/P4 组合 66 项通过；Ruff、Pyright 通过。
- P2 保护门通过：2336 个旧保护文件未变，3 个冻结私有模块哈希匹配。
- 计划固定为 35 个 item、5 批、最大批次 8；计划 ID
  `8aef4c029076e0bf0d59c30bf8999d6517c2b71cc3d7262537d39efca846f247`。
- 预算 SHA-256 为 `10f62bd209be9d16bba364370bb304deec01d10f8942b5ef98ddad81615550cb`：
  development-only、最多 5 调用、0 重试、1 轮、并发 1、每次最多 4096 输出 token；第一批兼作
  provider 检查。关系、holdout、PG、入库额度均为 0。

## 2. 真实执行结果

启动时首次命令因授权运行目录的父目录尚不存在，在 adapter 创建和模型发送前失败；该次没有建立
attempt、没有模型调用，也没有消耗预算。创建限定的 `p4-runs` 容器目录后，用同一冻结预算重新启动。

真实轮只发送第 1 批，收到响应并完整持久化后，由严格批级校验触发
`invalid_batch_response`，剩余 4 批没有发送：

| 项 | 结果 |
|---|---:|
| 实际模型调用 | 1 / 5 |
| 自动重试 | 0 |
| 首批义务 / 模型返回行 | 8 / 8 |
| 严格协议可接受行 | 4 / 8 |
| prompt / completion token | 2550 / 1564 |
| 响应耗时 | 11052 ms |
| finish reason | `stop` |
| 审计状态 | `halted=true`, `halt_reason=invalid_batch_response` |

正式结果：G0、G1、G2、G3、G6 均失败；G4 关系、G7 CLI 未评估；G5 随后再次由外部保护门确认
通过。结果文件 SHA-256 为
`f6c3b70b3cf4742bfda60bc546cab728bfdfb0cbe34b21743ff835093ff4db30`，审计导出 SHA-256 为
`0bcd1497e74195b6c44ec487794266fdd0749ebeb1547ee59ad093d63c883966`。

`protocol_errors=35` 的含义不是 35 条均已调用失败，而是首批 4 条非法记录，加上 fail-stop 后没有
产生的 31 条唯一终态。不得把该值解释为 35 次模型错误。

## 3. 字段级归因

首批 8 行均有合法 JSON、正确 plan/obligation ID 和 `extracted` 终态，但存在以下差异：

| 差异 | 首批数量 | 归因 |
|---|---:|---|
| `semantic_type=risk` 3 条、`question` 1 条，超出冻结枚举 | 4/8 | 模型违反显式枚举；同时 `semantic_type` 与 `statement_role` 的相邻标签容易混用，接口可用性不足 |
| 非行为陈述将 `behavior_status` 写成 `unknown`，目标为不适用 `null` | 8/8 | 协议未给出 applicability/invariant，属于结构契约遗漏 |
| speaker identity 写为 unknown，而系统目标为已批准的 explicit | 7/8 | 请求未携带系统已知的 speaker registry 事实；仅凭 source-only 输入不可稳定推出，属于不可观测目标 |
| 因 speaker 不可观测而额外写入 `author_identity` unknown | 7/8 | 上一问题的连锁结果，不应靠降低分数掩盖 |
| 复合 value 被规范化、裁掉期间或单位文本 | 2/3 个非空 value | “保留来源完整表达”未被实现成 span/transform 协议；自由字符串仍允许隐式规范化 |
| 风险陈述 polarity 写 unknown，目标为 affirmed | 3/8 | semantic type、statement role 与 polarity 的跨轴规则未显式化 |
| question 的 temporal frame 与目标不同 | 1/8 | 语义规则不足，需字段级有限义务或系统推导 |

因此本轮是**混合失败，但主要卡点仍在接口设计**：模型确实没有遵守已提供的 semantic 枚举；然而即使
把 4 个非法枚举机械修正，speaker、applicability、value 保真和跨轴一致性仍无法通过。当前证据不支持
继续微调提示词或扩大调用次数，也不支持把 `risk/question` 临时加入 semantic 枚举、把 `unknown`
等同 `null`、或回改金标制造通过。

## 4. 下一步：P4-A 零模型局部接口修订

维持生产与旧流程冻结，在 scratch 中先完成以下零模型工作：

1. 明确系统所有权：speaker registry/identity、批准的 item text、source span、非行为字段的
   applicability、命名 value transform 由系统注入或确定性计算，不再要求模型猜测。
2. 把剩余模型判断改成字段级有限义务；每个义务给出单一轴、有限选项、字段定义和证据 span 要求，
   批量传输但逐义务唯一终态，避免一行同时自由填写 12 个耦合字段。
3. value 只允许返回来源子串/span；复合表达由系统原样保留，已批准 transform 由命名规则执行，unit
   从同一来源 span 绑定，不接受模型静默标准化。
4. 冻结跨轴不变量，例如非 behavior 时 `behavior_status=null`，风险是 `statement_role` 而不是新的
   semantic type；用反例证明矛盾组合必败。
5. 用本轮原始响应做零调用 replay，分别报告“系统可确定字段”“模型有限判断字段”和“仍需人工字段”；
   不用本轮结果改写 evaluation target。
6. 对六个 scope 逐类跑非回归，`micro-copper-audio` 继续保持人工批准的
   `not_applicable_approved_exclusion`；再次通过 2336+3 保护门。

只有 P4-A 的零模型 replay、反例、目标无泄漏和旧流程隔离全部通过后，才可提出新的、另行冻结的模型
预算。P4 当前未验收，P5 关系、CLI 正式接线、PostgreSQL 与入库均不得启动。

