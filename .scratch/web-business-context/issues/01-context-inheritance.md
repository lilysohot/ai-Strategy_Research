# 01 上下文继承（含 KV cache 约束）

Type: task
Status: draft
Blocked by: —
Spec: [../spec.md](../spec.md)

## 目标

同一会话内，每一次对话都继承上一轮的对话内容；**且不破坏上游 KV cache**。

两个目标会互相拉扯：能把历史带给模型的最省事做法（每轮重新渲染一段"信封"）恰好是最毁缓存的。本计划的主线就是找一条同时满足两者的形态。

## 1. 现状

### 1.1 继承链路：铺到最后一步断掉

```
orchestrator 渲染 prior turns ──→ run_dir/history.txt        ✅ 写了
worker 读回 ──→ extra_input["conversation_history"]          ✅ 传了
kernel_adapter ──→ input_data.update(extra_input)            ✅ 进 state
                                                            ✗ 无任何消费方
节点只读 state["original_question"]（= 本轮 instruction）    ✗ 模型只见本轮
```

`conversation_history` 全仓库只有三处命中：`server/worker.py` 写、`tests/` 断言、`docs/` 提及。

### 1.2 缓存现状（Run `c3ec40b4-ed23-4c16-87ac-e29c15aec211` 实测）

| 指标 | 值 | 含义 |
|---|---|---|
| `prompt_tokens` | 1,198,611 | 整个 Run 的输入总量 |
| `cache_read_tokens` | 1,027,072 | **85.7% 命中缓存** |
| `llm_calls` | 28 | 同一 Run 内 28 次调用 |

结论：**轮内缓存已经在工作**（同一 Run 内 messages 是追加的，前缀稳定）。所以上游确实支持前缀缓存，问题只在跨轮。

注意归因：这 85.7% 来自**前缀稳定 + 上游自身的自动前缀缓存**，**不是**"路由亲和"的功劳（见 §2——当前 provider 不在 EAS 白名单里）。这一点很重要：它意味着**缓存收益只依赖我们能控制的那一半**。

### 1.3 跨轮为什么没有缓存

每轮是一个**独立 Run**、state 从零构造，messages 起点是 `[system, question]`。即便轮 2 的内容与轮 1 有重合，前缀也对不齐 —— 缓存无法命中。

## 2. KV cache 的两个必要条件

| 条件 | 现状 | 落点 |
|---|---|---|
| **路由亲和**：同一会话路由到同一后端 worker | ⚠️ **代码具备，但当前 provider 大概率不生效** | `_bind.py:180-184` 按调用注入 `x-upstream-session-id`（不检查 provider）；`session_context.py:17-21,35-38` 的 EAS 亲和链**只对白名单 provider**（`apodex`/`aliyun_pai_eas`/`aliyun_pai_eas_35b`）生效，而本 Run 的 provider 是 `openai`（火山方舟）；`_sticky_session_enabled()` 默认开（`FRONTIER_AGENT_LLM_STICKY_SESSION`）。**结论：不把缓存收益建立在它上面** |
| **前缀字节稳定**：请求的公共前缀逐字节相同、只追加不改写 | ❌ **没有** | 见 §3 |

已有那半的实现意图写得很明确：

```168:171:frontier_agent/core/runtime/loop/_bind.py
    Why it matters: EAS-backed gateways use this header for **session
    affinity** — the same session-id consistently
    routes to the same backend worker, preserving KV-cache across a task's
    turns.
```

所以**不要动路由层**，要解决的是内容层。

## 3. 三种继承形态对缓存的影响

### A. 信封重渲染（CLI 做法）

每轮把历史渲染成一段文本，作为本轮问题一起传。

```
轮1 prompt: [sys] "[Current user query]\nQ1"
轮2 prompt: [sys] "[Earlier turn 1]\nUser: Q1\nAssistant: A1\n\n[Current user query]\nQ2"
轮3 prompt: [sys] "[Earlier turn 1]…[Earlier turn 2]…\n[Current user query]\nQ3"
```

Q1 在轮 1 里写作 `[Current user query]\nQ1`，在轮 2 里写作 `[Earlier turn 1]\nUser: Q1` —— **同一内容两次呈现字节不同** ⇒ 前缀不匹配 ⇒ 每轮全量 prefill。n 轮总成本 **O(n²)**。

### B. messages 累积（追加式）

```
轮1: [sys][Q1]            → [sys][Q1][A1]
轮2: [sys][Q1][A1][Q2]    → …
轮3: [sys][Q1][A1][Q2][A2][Q3]
```

前缀严格逐字节稳定、只追加 ⇒ 每轮只 prefill 新增部分 ⇒ 总成本 **O(n)**。

这就是 `agent_loop` 已有的 `initial_messages` 通道：

```184:188:frontier_agent/core/runtime/loop/agent_loop.py
    # Empty user input resumes the supplied history without adding a turn.
    if initial_messages is not None:
        messages: list[Message] = list(initial_messages)
        if user_message:
            messages.append(user_msg(user_message))
```

### C. 混合（稳定前缀 + 易变尾部）

本质上仍是 B，只是额外要求：**易变内容一律放尾部**（本轮问题、本轮业务上下文），稳定内容（system、工具 schema、历史）放前面。作为 B 的排序原则，不单列。

### 对比

| | A 信封 | B 累积 |
|---|---|---|
| 继承能力 | ✅ | ✅ |
| 跨轮缓存 | ❌ 全失效 | ✅ 命中 |
| n 轮总 prefill | O(n²) | O(n) |
| 实现改动 | 小（server 侧拼接） | 中（workflow 需接受 `initial_messages`） |
| 与压缩的关系 | 压缩必然失效 | 按需压缩时才失效 |

## 4. 一个反直觉的事实：CLI 也不能照搬

CLI 的 `react` / `agent_team` 两个 mode **都**走 workflow 分派：

```40:40:apodex/profiles/__init__.py
_TERMINAL_WORKFLOW_MODES = ("react", "agent_team")
```

而 workflow 路径每轮都是 `render_session_history(...)` 重渲染（`task_runner.py:513-524`）——**就是形态 A**。CLI 里唯一用 `initial_messages`（形态 B）的是 generic loop（`task_runner.py:295-336`），而那条路在产品里不跑（没有 `workflow:` 的 profile 才会走）。

所以：**"从 CLI 集成"能拿到的是继承机制本身，拿不到缓存友好的继承。** 缓存友好需要我们自己在 workflow 路径上补 `initial_messages`。

## 5. 前缀稳定的三个前提（缺一即全失效）

1. **重放完整 messages，不能只重放问答文本。**
   轮 1 实际发送的序列是 `[Q1][A1+tool_calls][T1][A2]…`（含工具往返）；如果轮 2 只重放 `[Q1][A1_final]`，前缀与轮 1 不一致 ⇒ 失效。
   ⇒ 必须持久化并重放**完整消息序列（含 tool 调用与结果）**。CLI 的 `display_history`（`apodex/session.py:157-159`，注释明确说保留 "complete visible conversation and tool protocol"）就是为此存在的；Web 的 `turns` 表目前只有 `role/content`，**不够**。
   ⇒ **已确认有现成来源**：上一轮 Run 的轨迹 `run/agent/trajectories/react_agent.jsonl` 逐事件记录了 `start.system_prompt` / `start.user_message` / `start.tool_names` / `llm.tool_calls` / `result.tool_call_id`，足以重建 system / user / assistant / tool 四类消息，并按 `tool_call_id` 正确配对（避免孤儿 tool 消息）。**阶段 1 因此不必先改表结构。**
   ⇒ 重建时必须一并带上 assistant 的 `thinking`（轨迹里的 `llm.thinking`）——`tui` profile 是 `thinking_in_history: true`，漏掉即前缀不一致。

2. **system prompt 必须逐轮稳定。**
   现在 `_sys_prompt_addendum` 依 `has_investment_context` 变化（`worker.py:493-500`：有上下文才追加 `BUSINESS_CONTEXT_POLICY`）——同一会话里有的轮有、有的轮没有 ⇒ system 变 ⇒ 缓存全失效。需要改为**恒定**（策略常驻，数据按需）。

3. **工具 schema 必须逐轮稳定。**
   `build_profile_overrides` 同样按 `has_investment_context` 分支给不同 `agent_tools`（`server/profile.py:88-97`）。工具列表在请求前部，变化即失效。同样需要恒定。

## 6. 分阶段执行计划

### 阶段 1：缓存友好的继承主链路

- **形态**：B（messages 累积）。历史以 `initial_messages` 进入 `run_agent_loop`。
- **数据源**：从**上一轮 Run 的轨迹**重建完整消息序列（`run/agent/trajectories/react_agent.jsonl`，见 §5.1）；worker 无状态，不依赖进程内状态。长期可改为从数据库直读（更干净），但不作为阶段 1 的前置条件。
- **落点**：
  - workflow 节点接受并转发 `initial_messages`（`workflows/stateful_react_agent/nodes/main_agent.py` 的 loop 调用处，以及 `agent_team` 对应处）；
  - server 侧构造历史序列（`server/history.py` 或新模块），与 `history.txt` 的渲染并行存在、逐步替代；
  - 保持 `extra_input["current_query"]` 语义（干净的本轮问题）。
- **同时落地 §5 的 2、3 两条**（system / tools 恒定），否则阶段 1 的缓存收益会被抵消。
- **验收**：同一会话连跑 3 轮，轮 2 的 `cache_read_tokens` 明显覆盖轮 1 的 `prompt_tokens`；轮 3 覆盖轮 1+2 的大部分。

### 阶段 2：完整消息序列 + 按需压缩

- **完整序列**：让 `turns` 侧能保存含 tool 调用/结果的完整消息（或以 run 产物为准做重放）。这是前缀稳定的必要条件（§5.1）。
- **按需压缩**：复用 CLI 的 `SessionHistoryCompactor` 思路（超预算才压，六级阶梯；`session_history.py:236-316`）。压缩会让前缀失效**一次**，之后重新累积——这是可接受的代价，前提是"不超限就不动"。
- **验收**：长会话下总 prefill 仍近似线性；单次压缩后缓存能重建。

### 阶段 3：观测与调优

- 把每轮的 `cache_read_tokens / prompt_tokens` 记为常驻指标，跨轮对比。
- 用 §1.2 的同一口径（`runs.usage_json`）做回归。

## 7. 风险与不变量

| 风险 | 后果 | 对策 |
|---|---|---|
| 历史里插入任何"每轮不同"的内容（如现在的 `turn_index`、动态策略文本） | 前缀失效，缓存归零 | 不变量：**前缀区只放跨轮不变的内容**；易变内容一律放尾部 |
| 工具集/system 随上下文有无而变 | 同上 | §5.2、§5.3 |
| 压缩策略与缓存打架 | 每轮都压 ⇒ 每轮都失效 | 只在超预算时压；压缩阈值要显著高于实际常见长度 |
| 薄历史（只有问答） | 继承可用，但上一轮查到的事实丢失 | 明确列为阶段 1 的已知边界，阶段 2 解决 |

## 8. 待决策

1. **阶段 1 是否接受"从轨迹文件解析"作为完整消息来源**？它让阶段 1 不必先改表结构，代价是每轮多解析一个 JSONL（本轮实测 120 行 / 227KB）。若不可接受，则先做 `turns` 侧扩容，阶段 1 相应后移。
2. **压缩放在阶段 1 还是阶段 2**？建议阶段 2——阶段 1 先用一个"最近 N 轮"的硬上限顶住，避免压缩逻辑污染缓存收益的测量。
3. **`history.txt` 是保留还是废弃**？缓存友好形态下不再需要"渲染成文本"这条路径，但它目前是补数续接等链路的既有产物，需要确认没有别的消费方后再退场。

## Comments

2026-10-10：依据 Run `c3ec40b4…` 的 usage 实测（cache_read 85.7%）与 `_bind.py` 的会话亲和实现建立。核心判断：CLI 的 workflow 路径同样是信封重渲染，不可照搬；缓存友好需要 messages 累积。
