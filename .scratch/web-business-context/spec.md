# Spec: 业务资料状态与上下文链路

一句话目标：**让 agent 在给买卖/仓位结论前，掌握"这个账户现在有哪些资料、缺哪些"，并让这份状态进入 Run 上下文。**

- **前序**：[web-business-repairs](../web-business-repairs/spec.md) 的 [02 DATA-07 持久补数续接](../web-business-repairs/issues/02-data07-input-requests.md)、[03 DATA-08 业务上下文与工具接线](../web-business-repairs/issues/03-data08-business-context-tools.md)。
- **定位**：本 spec 是 DATA-07/DATA-08 的**遗漏收口**。那两条只覆盖了"Run 有冻结业务快照"的路径，没有定义"没有快照"和"资料不完整"这两种同样常见的情形。
- **授权范围**（2026-10-10）：只打通**上下文链路**。弹窗的实现细节另行讨论，本 spec 只固定它与上下文之间的接口约定。

## 1. 触发实测（2026-10-10）

Run `c3ec40b4-ed23-4c16-87ac-e29c15aec211`（研究 `c3646e12-cb2b-4756-988c-2e1584010ada`），用户在对话里直接提问「准备购买工业富联300股，你觉得合适吗」。

| 层 | 实际看到 | 证据 |
|---|---|---|
| 结构化存储 | 账户已登记且**有值** | `investment_accounts`/`investment_account_revisions`：`total_capital=200000`、`currency=CNY`、`capital_basis=tradable_assets`、`as_of=2026-10-09`，`revision=1` |
| 研究绑定 | 账户**已绑定**该研究 | `research_investment_links.account_id=c2bf8670-…`（`primary_plan_id=None`） |
| 服务端裁决 | **认可**该账户 | `evaluate_purpose` 未报任何 `account.*` 缺失；请求字段只剩 `plan.*` |
| **agent 上下文** | **一个业务字段都没有** | Run 目录**无** `investment-context.json`；worker `_load_investment_context` 返回 `None` |
| agent 行为 | 回头追问用户已知信息 | `summary.json` 的 `final_answer`：「您为这笔投资规划的总资金（300 股 1.68 万占您总资金/该标的规划资金的比重？）」 |

结论：**同一份资料在"结构化存储"里有、在"agent 上下文"里没有**，且"缺什么"这一半从未进入模型视野。

## 2. 资料状态（主线）

### 2.1 定义

**资料状态**是关于"某个研究对象的业务资料现状"的一等公民，而不是"有值就注入、没值就沉默"的副产物。它必须同时表达两件事：

- **已知**：有哪些字段、值是什么、来自哪个版本；
- **缺失**：还缺哪些字段、以及**每个字段该由谁补**。

缺失的"归属分类"是不可省略的——否则会把用户刚说过的信息再问一遍（本次实测即为此）。

### 2.2 分类

| 归属 | 含义 | 例子 | 处理 |
|---|---|---|---|
| `ask_user` | 只能由用户决策/提供的字段 | `plan.allocated_capital`（本标的规划资金）、`plan.risk_budget_value` | 进入"待用户补充"，由补数链路承载 |
| `agent_declarable` | 用户已在提问中给出、或模型可从本轮上下文确定的**事实** | `plan.symbol` / `plan.market` / `plan.direction`（本次用户在提问里已说"工业富联 / 买入"） | **不得**作为"缺失"向用户索要；由模型在声明缺料时一并带上，服务端据此认定为已提供 |
| `derived` | 可由已有字段推算，或系统侧补充 | — | 不进"缺失"清单 |

关键：现有 `evaluate_purpose` 只输出 `missing: 字段 → 说明`，**没有归属维度**。`plan.symbol/market/direction` 因此和 `plan.allocated_capital` 混在一起被当成"要问用户"，这是弹窗链路走不通的根因之一。

### 2.3 形态

一个 Run 的资料状态应至少包含：**分组完整度**（account / plan / trade 各自的 `complete` / `partial` / `missing`）+ 每组的已知值 + 每组的缺失项（带归属分类）。

它有两种出现形式，语义一致：

1. **注入上下文**：Run 启动时随指令/系统提示进入模型可见区（形态与现有 `<investment_context_data>` 同类：**是数据，不是指令**）；
2. **主动获取**：agent 可随时重查（现有 `investment_context()` 工具只能读到"值"，读不到"缺失"，需要扩展为状态视图）。

### 2.4 纪律

给出买卖/仓位结论前先掌握资料状态；缺失按 2.2 的分类处理——`ask_user` 才去要，`agent_declarable` 自己带上。这条与既有 INPUT REQUEST POLICY 并列，不替换它。

## 3. 三处断点与主线的关系

本节的"资料状态"是把三处串起来的主线；三处都是它的表现，不是独立议题。

| # | 断点 | 与资料状态的关系 | 主要落点 |
|---|---|---|---|
| 1 | **同源上下文**：上下文层只认"Run 的业务快照"，裁决层却会回退到"研究当前绑定" → 两层口径不一致 | 资料状态的**来源**必须与裁决同源，否则状态本身就不自洽 | `orchestrator._launch` 的上下文解析分支；`investment_context` 解析器 |
| 2 | **字段归属**：`evaluate_purpose` 输出无归属维度 → 已知事实被当成待索取 | 资料状态**定义**的核心（2.2） | `server/business_service.py::evaluate_purpose`；缺料工具签名与 `spec.declared` |
| 3 | **弹窗链路**：请求字段集 ⊄ 固定表单能力集 → 静默不弹 | 资料状态是**消费方**：归属修对后，`ask_user` 只剩弹窗能采集的字段，链路自然通 | 本 spec 只固定接口约定（见 §5），实现另行讨论 |

打通链路的最小闭环：

```
① 同源上下文     → agent 拿到「账户有 20 万」
② 字段归属       → symbol/market/direction 不再算「缺失」
   ⇒ 待补清单只剩 plan.allocated_capital（⊂ 弹窗能力集）
   ⇒ 弹窗链路成立（无需改弹窗）
```

## 4. 验收判据（可核验）

1. **已知值进上下文**：以 §1 的同一场景（无快照 + 研究已绑定账户 + 账户有值）重跑，Run 目录出现上下文物化，且模型可见区包含 `total_capital=200000`；`summary.json` 的答案**不再**追问总资金。
2. **缺失可见且带归属**：同一次运行的模型可见区包含待补清单，其中 `plan.allocated_capital` 标为 `ask_user`，`plan.symbol/market/direction` **不出现**在待补清单里。
3. **两层同源**：对"无快照 + 已绑定"这一情形，裁决层与上下文层基于同一份资料得出同一结论（可用同一 Run 的两处产物对照）。
4. **不回归 DATA-08**：有快照路径的冻结语义不变——旧 Run 不受业务资料改版影响（沿用 DATA-08 既有验收）。
5. **不回归 DATA-07**：`ask_user` 类缺失仍能触发补数请求并续接新 Run。

## 5. 非目标 / 待另行讨论

- **弹窗实现**（字段能力、渲染方式、是否保留模态）：另行讨论。本 spec 只约定：弹窗的输入是"`ask_user` 类的待补字段"，不得依赖 `agent_declarable` 字段。
- **多轮会话历史**（`conversation_history` 在 server 侧无人消费）：独立缺陷，不在本次主线内。
- **`plan` 对象的创建流程改造**：只要求"不把已知事实判成缺失"，不改计划的写入契约。

## Comments

2026-10-10：据 Run `c3ec40b4…` 的实测证据建立。用户裁决：先打通上下文链路，弹窗实现稍后。
