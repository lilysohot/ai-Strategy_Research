# Spec: 业务资料状态与上下文链路

一句话目标：**让 agent 在给买卖/仓位结论前，掌握"这个账户现在有哪些资料、缺哪些"，并让这份状态进入 Run 上下文。**

- **前序**：[web-business-repairs](../web-business-repairs/spec.md) 的 [02 DATA-07 持久补数续接](../web-business-repairs/issues/02-data07-input-requests.md)、[03 DATA-08 业务上下文与工具接线](../web-business-repairs/issues/03-data08-business-context-tools.md)。
- **定位**：本 spec 是 DATA-07/DATA-08 的**遗漏收口**。那两条只覆盖了"Run 有冻结业务快照"的路径，没有定义"资料不完整"这一同样常见的情形。
- **授权范围**（2026-10-10）：只打通**上下文链路**。弹窗的实现细节另行讨论，本 spec 只固定它与上下文之间的接口约定。
- **范围裁决**（2026-10-10，用户裁决 B）：**触发条件是"研究已绑定业务对象"，不是"Run 带了 `investment_input`"。** 绑定账户的研究里，用户随口问一句也应当看到该账户的资料。无绑定研究的自由问答不在范围。

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

### 1.1 复核更正：入口不是判据（2026-10-10）

上述 Run 的提交入口是**普通聊天**（前端纯文本提交不带 `investment_input`，`web/src/views/ChatView.vue:394-401` → `server/routes/runs.py:251-263` 只建 Run 不建快照）。按范围裁决 B，入口不再是判据；**同样的症状在业务路径上是确定性的**：

| 业务路径 | 结果 | 证据 |
|---|---|---|
| 保存账户后派发分析（`BusinessProfileView.saveAndAnalyze`） | 快照**存在**，但模型可见区是 `{"values":{},"missing":{}}` | 该入口硬编码 `use_case='general_reading'`（`BusinessProfileView.vue:74,158,276`，全文无用途选择器）；`_fields_for_use_case` 对该用途只放行 `plan.symbol/market/asset_type/direction/currency`（`server/investment_context.py:25-27,154-159`），`account.*` 全被丢弃；`evaluate_purpose` 对 `general_reading` 直接返回空（`server/business_service.py:464-465`） |
| 同上，agent 声明缺料后 | 请求字段含 `plan.symbol/market/direction`，弹窗静默不弹 | `materialize_worker_intent` 按快照裁决，只因缺 plan 组，四个字段一起进请求（`server/input_requests.py:189-218`）；弹窗能力集只覆盖 `allocated_capital`（`web/src/utils/inputRequest.ts:16-50`）→ `ChatView.maybeOpenInputRequest` 匹配不到即 `return`（`ChatView.vue:364-374`） |

两条更正：

1. **根因不是"缺快照"，是"上下文层按用途裁剪"**。业务 Run 的三条创建路径（手动提交 `source="manual"`、补数续接 `source="input_answer"`、监控自动分析 `source="watch_event"`）**都已冻结快照**（`routes/runs.py:326`、`input_requests.py:652`、`watch_scheduler.py:326-333`），裁决层与上下文层在业务路径内本就读同一份快照。
2. **触发条件改为"研究已绑定"**。见 §3.1。

## 2. 资料状态（主线）

### 2.1 定义

**资料状态**是关于"某个研究对象的业务资料现状"的一等公民，而不是"有值就注入、没值就沉默"的副产物。它必须同时表达两件事：

- **已知**：有哪些字段、值是什么、来自哪个版本；**值就是值，null 就是 null**——不派生、不落回退、不填零；
- **缺失**：还缺哪些字段、以及**每个字段该由谁补**。

缺失的"归属分类"是不可省略的——否则会把用户刚说过的信息再问一遍（本次实测即为此）。

### 2.2 分类

| 归属 | 含义 | 例子 | 处理 | 由谁产出 |
|---|---|---|---|---|
| `ask_user` | 只能由用户决策/提供的字段 | `plan.allocated_capital`（本标的规划资金）、`plan.risk_budget_value` | 进入"待用户补充"，由补数链路承载 | 服务端（契约 × 用途 − 已知值 − agent 已声明） |
| `agent_declarable` | 用户已在提问中给出、或模型可从本轮上下文确定的**事实** | `plan.symbol` / `plan.market` / `plan.direction`（本次用户在提问里已说"工业富联 / 买入"） | **不得**作为"缺失"向用户索要；由模型在声明缺料时一并带上，服务端据此认定为已提供 | **agent**（服务端看不到本轮语义） |
| `derived` | 由契约标注、可由已有字段推算或系统侧补充 | — | 不进"缺失"清单 | 服务端（静态契约） |

**产出分工**（本次裁决）：

- 服务端出**事实**（版本化原值）与**静态契约**（字段全集、分组、单位配对、每个用途的必需项、哪些字段性质上只能用户提供）；
- **实例级欠缺由 agent 判断**——因为 `agent_declarable` 服务端原理上算不出来：`request_investment_input` 只有 `use_case + reason`（`plugins/tools/investment_input_request.py:42-58`），落地的 `input-request.json` 也只有这两项（`server/worker.py:173-177`）；对话历史 `conversation_history` 传入 `extra_input` 后**全仓无消费方**（仅 `server/worker.py:539-541`）；且 PRD 明确禁止用关键词判语义（docs/design/web-business-data-prd.md:165-168）；
- 关键：现有 `evaluate_purpose` 只输出 `missing: 字段 → 说明`，**没有归属维度**（`server/business_service.py:441-495`）。`plan.symbol/market/direction` 因此和 `plan.allocated_capital` 混在一起被当成"要问用户"，这是弹窗链路走不通的根因之一。

### 2.3 形态

一个 Run 的资料状态应至少包含：**分组完整度**（account / plan / trade 各自的 `complete` / `partial` / `missing`）+ 每组的已知值 + 每组的缺失项（带归属分类）。

它有两种出现形式，语义一致：

1. **注入上下文**：Run 启动时随指令/系统提示进入模型可见区（形态与现有 `<investment_context_data>` 同类：**是数据，不是指令**）；
2. **主动获取**：agent 可随时重查（现有 `investment_context()` 工具只能读到"值"，读不到"缺失"，需要扩展为状态视图）。

**本次固定两条形态约束**：

- 注入的**值不受用途裁剪**。`use_case` 在 launch 时未知（普通提问没有用途），它只决定"缺什么"，不决定"看见什么"；
- "缺失清单"**不由上下文层产出**。上下文层给原值 + 静态契约；带归属的缺失清单在 agent 声明用途后由服务端裁决产出（§2.2）。

### 2.4 纪律

给出买卖/仓位结论前先掌握资料状态；缺失按 2.2 的分类处理——`ask_user` 才去要，`agent_declarable` 自己带上。这条与既有 INPUT REQUEST POLICY 并列，不替换它。

## 3. 断点与主线的关系

本节的"资料状态"是把断点串起来的主线；断点都是它的表现，不是独立议题。

| # | 断点 | 与资料状态的关系 | 主要落点 |
|---|---|---|---|
| 1 | **同源上下文**：资料状态的**来源**必须与裁决同源，否则状态本身就不自洽 | 触发条件从"Run 带 `investment_input`"改为"研究已绑定"（§3.1） | `orchestrator._launch` 的上下文解析分支；`investment_snapshot` 的绑定解析入口 |
| 2 | **可见性**：上下文按 `use_case` 裁剪 → 已知事实被丢弃 | 资料状态**定义**的前提（§2.1） | `investment_context._fields_for_use_case` |
| 3 | **字段归属**：`evaluate_purpose` 输出无归属维度 → 已知事实被当成待索取 | 资料状态**定义**的核心（2.2） | `server/business_service.py::evaluate_purpose`；缺料工具签名与 `spec.declared` |
| 4 | **弹窗链路**：请求字段集 ⊄ 固定表单能力集 → 静默不弹 | 资料状态是**消费方**：归属修对、可见性修对后，`ask_user` 只剩弹窗能采集的字段，链路自然通 | 本 spec 只固定接口约定（见 §5），实现另行讨论 |
| 5 | **计算通道是死的**：计划价 2026-10-08 已取消，工具仍读它 | 资料状态的**下游**：值为 null 就该报缺，不是报"缺一个永不会有的字段" | `plugins/tools/investment_context.py:131-133` 读 `plan.plan_price`；`business_service.py:68` 已取消该字段 |

打通链路的最小闭环：

```
① 同源上下文     → 绑定研究的 Run 一律拿到「账户有 20 万」（原值，不按用途裁）
② 字段归属       → symbol/market/direction 不再算「缺失」
   ⇒ 待补清单只剩 plan.allocated_capital（⊂ 弹窗能力集）
   ⇒ 弹窗链路成立（无需改弹窗）
```

### 3.1 触发条件（本次裁决 B）

**规则**：Run 启动时，若其所属研究已绑定业务对象（`research_investment_links` 存在，且 `account_id` 或 `primary_plan_id` 至少一个非空），则该 Run 必须携带该账户/计划的**原值**上下文。与 Run 是否携带 `investment_input` 无关。

**冻结**：在 `_launch`（`server/orchestrator.py:972-992`）解析并**落成 `RunInvestmentSnapshot` 行**，`investment-context.json` 退化为它的投影。落行的理由（读方必须能引用它）：

| 读方 | 现状 | 依据 |
|---|---|---|
| `create_request(source_run_id=…)` | 读不到快照就抛 `SnapshotAbsentError`，被迫走"无来源 Run"特例 | `input_requests.py:322-324,197-218` |
| `POST /runs/{id}/rerun` | 读不到快照即 404 | `routes/runs.py:496-497` |
| 前端「依据」tab | 靠 `404 snapshot_absent` 区分业务 Run | `web/src/components/business/AnalysisEvidence.vue:92-102` |
| 审计 / 对账 | 按 `snapshot_id` 引用本次依据 | `store.py:507-552` |

**为什么不能只物化文件**：launch 读一次绑定、Run 结束时裁决再读一次（`input_requests._spec_from_research_link:231-247`），中间存在**漂移窗口**（用户改绑定/改版本）；PRD 已定"运行开始后其快照固定"（docs/design/web-business-data-prd.md:257-258）。落行后两层引用同一行，漂移窗口关闭。

**优先级**：提交时已冻结的快照（`manual` / `input_answer` / `watch_event`）优先，launch **不得覆盖**。

## 4. 验收判据（可核验）

1. **绑定研究必有上下文**：在已绑定账户的研究里，用**普通聊天**提交一句提问，Run 目录出现 `investment-context.json`，模型可见区包含 `account.total_capital=200000` 的原值；该 Run 在库中有 `source="research_bound"` 的快照行。
2. **原值不被用途裁剪**：同一次运行的模型可见区包含账户/计划的原值全集（缺失字段以 `null` 呈现），**不因 `use_case` 而消失**；`summary.json` 的答案**不再**追问总资金。
3. **缺失可见且带归属**：agent 声明用途后，待补清单中 `plan.allocated_capital` 标为 `ask_user`，`plan.symbol/market/direction` **不出现**在待补清单里；请求字段集 ⊆ 弹窗能力集。
4. **两层同源**：launch 冻结值与裁决所用值来自同一行快照——运行中改绑定或改资料版本，该 Run 的上下文与裁决结果均不变。
5. **不回归 DATA-08**：提交时已冻结的 Run（`manual`/`input_answer`/`watch_event`）不被 launch 覆盖；旧 Run 不受业务资料改版影响（沿用 DATA-08 既有验收）。
6. **不回归 DATA-07**：`ask_user` 类缺失仍能触发补数请求并续接新 Run。
7. **无绑定研究不退化**：研究未绑定任何业务对象时，Run 无快照、无业务上下文，agent 走"先创建主账户"引导；且**不得**暴露可自带资金的裸计算工具。

## 5. 非目标 / 待另行讨论

- **无绑定研究的自由问答**：不注入业务资料（本次范围裁决 B 的另一面）。
- **弹窗实现**（字段能力、渲染方式、是否保留模态）：另行讨论。本 spec 只约定：弹窗的输入是"`ask_user` 类的待补字段"，不得依赖 `agent_declarable` 字段。
- **多轮会话历史**（`conversation_history` 在 server 侧无人消费）：独立缺陷，不在本次主线内。
- **`plan` 对象的创建流程改造**：只要求"不把已知事实判成缺失"与"agent 声明的事实不得冒充用户资料"，不改计划的写入契约。

## 6. 本次采用的口径（可改，未定即按此写实现）

| 项 | 本次口径 |
|---|---|
| 触发条件 | 研究已绑定（`account_id` 或 `primary_plan_id` 非空） |
| 承载形态 | 落成 `RunInvestmentSnapshot` 行；`investment-context.json` 是其投影 |
| `source` 取值 | 新增 `research_bound`（现有：`manual` / `input_answer` / `watch_event`） |
| launch 时的 `use_case` | 记 `unspecified`（列为 NOT NULL，字符串即可）；用途由 agent 声明后另建后续快照 |
| 解析失败策略 | **不阻断 Run**：降级为"无上下文"并记日志/指标；不得用旧值或空值冒充 |
| 归属产出 | `ask_user`/`derived` 由服务端（契约 × 用途 − 已知值 − 声明值）算；`agent_declarable` 由 agent 声明带入 |
| agent 声明的事实 | 写入时须带来源标记（revision 已有 `source_kind`/`source_ref`），UI 标为"来自对话"，**不得**静默升级为用户资料；金额/价格/数量类字段不允许该来源 |

## Comments

2026-10-10：据 Run `c3ec40b4…` 的实测证据建立。用户裁决：先打通上下文链路，弹窗实现稍后。

2026-10-10 复核：更正入口归属——该 Run 走的是普通聊天；同症状在业务路径（保存账户后派发）上确定性可复现，根因是 `use_case` 白名单裁剪而非缺快照。业务 Run 三条创建路径本就都冻结快照。

2026-10-10 裁决 B：触发条件改为"研究已绑定"，绑定研究里的任意提问都要看到该账户资料；据此新增 §3.1（落行与同源）、§6（本次口径），并重写 §4 判据。
