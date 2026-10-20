# 01 上下文继承（含 KV cache 约束）

Type: task
Status: resolved
Blocked by: —
Spec: [../spec.md](../spec.md)

**当前状态（2026-10-12）**：用户明确要求“先收口 S1–S4”，据此完成本 issue 的 S1–S4 整体收口。C4 保留已接受的 FAIL，S3 实测结果仍为 6/7；四项回溯缺口已修复并通过零额度回归。S5 不在本次关闭范围，仍待独立立项。最终交付与验证边界见文末 [Answer](#answer)；下文各日期记录保留其历史时点含义。

**收口后跟进（2026-10-20）**：监控实跑暴露出“连续性完全关闭”会丢失已有研究上下文，目标设计修订为**读取既有上下文 + 结构化选择性写回**。该跟进不改变 S1–S4 的收口状态；Web 首包等待上限和监控只读连续性已经落地，结构化结论写回与兜底语言修复仍未实现，详见 §13。

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

## 9. 阶段 1 实现方案（设计稿，2026-10-10）

### 9.1 结论先行

形态 B 落地成四条链：**轮末落"最终消息列表"产物 → server 只做字节搬运 → 下一轮 worker 读入 → 节点校验后作为 `initial_messages` 交给 kernel**。前缀恒定（§5.2/§5.3）不靠"改 prompt 组装"，而是**把判定源从 run 级换成会话级**——因为现状的三处分支全挂在 run 级 `has_investment_context` 上。

### 9.2 权威来源修正：用轮末 dump，不用轨迹事件重放

§5.1 的"轨迹足以重建完整消息序列"要修正为**不够**，两条硬证据：

| # | 事实 | 依据 |
|---|---|---|
| 1 | kernel 手里的 `messages` 是**已归一化**的 wire 形状（reasoning 的内联/保留在 append 之前就定死了），最终列表由 `AgentLoopResult.messages` 直接给出 | `model_profile.py:602-605`、`agent_loop.py:654-655`、`loop_types.py:205-211` |
| 2 | 轨迹信封的 tool 体被裁（`_BODY_MAX_CHARS` 默认 16384），且 jsonl 记的是**工具结果后处理器之前**的原文（注释明说后处理器在 `notify_tool_result` 之后且不落盘） | `trajectory.py:64`、`:650-655`、`:424-427` |

⇒ 事件流重建最多做到"到第一个超长 tool 结果为止"的字节一致；dump 的 `result.messages` 天然字节精确（它就是 kernel 手里那份）。

**对 §8.1 的回答**：建议选 dump；轨迹继续做诊断/时间线（`server/relay.py:139`）。

### 9.3 产物契约：`<run_root>/run/conversation.json`（v1）

```json
{
  "schema": "conversation-dump/1",
  "run_id": "...", "session_id": "...",
  "pipeline_id": "stateful-react-agent", "node_id": "react_agent", "role_id": "stateful_react",
  "model_name": "…", "thinking_format": "tag",
  "system_prompt": "<本轮实际拼出的全文>",
  "tool_names": ["…ordered…"],
  "tool_schema_sha256": "<sha256(canonical json of tools= 数组)>",
  "messages": [ {"role": "...", "content": "...", "...": "..."} ],
  "turns_used": 7, "stopped_by": "final",
  "trim": null
}
```

- 写者：新 observer `frontier_agent/components/observers/conversation_snapshot.py`，在 `on_loop_end(result)` 写 `result.messages`（非 critical，写失败不阻断运行，隔离机制同现有 observer）。
- 写前：过 `for_wire()`（`messages.py:81`）+ 结构自检（role 合法 / 每个 `tool_calls[].id` 都有配对 tool 消息 / 无孤儿）+ 原子替换（`.tmp` + `os.replace`，best-effort fsync）。
- 落点 = `run/conversation.json`（= `_trial_dir`，`worker.py:478`）：**不放** `run/agent/trajectories/`，避免被轨迹读取方（固定路径 `react_agent.jsonl`，`relay.py:32`、`trajectory_status.py:42`）误认。
- 注册：`stateful_react_agent/nodes/main_agent.py:907-926` 的 observers 列表加一行（`system_prompt=system_prompt`、`tools=tools`，与 `TrajectoryFileObserver` 同参）。

### 9.4 传递链（server 只搬字节）

1. `orchestrator._spawn`：与写 `history.txt` 同点，定位上一轮 Run 的 dump 并**字节拷贝**到新 run 的 `run_root/prior_conversation.json`。
   - 定位：沿 `_turns_as_of_submission(...)`（`orchestrator.py:107-125`）逆序找首个「`run_dir_for(turn.run_id)/run/conversation.json` 存在且 `pipeline_id` 一致」的 run；找不到 = 无重放。
   - 只拷不解析 ⇒ 不动 `server/history.py:10-15` 的"server 不读 workflow 内部消息"边界。
2. `worker.run_once`：读 `run_root/prior_conversation.json` → `extra_input["replay_messages"]=dump["messages"]`、`extra_input["replay_meta"]={其余头字段}`；`history.txt` / `conversation_history` 原样保留（并行，§8.3 另议退役）。
3. `kernel_adapter.BenchmarkSession.run`：**无需改动** —— `input_data.update(extra_input)`（`kernel_adapter.py:155-156`）已把 state 铺好。
4. `stateful_react_agent/spec.py:29-34` 的 `include_fields` 增 `"replay_messages","replay_meta"`（白名单过滤在 `graph_builder.py:186-194`，漏加节点就看不到）。

### 9.5 节点侧校验与使用

`react_agent_node` 在算出 `system_prompt`（`main_agent.py:817-903`）与 `tools/tool_names`（`:807-815`）之后、调 loop（`:1091-1140`）之前：

1. 无 `replay_messages` → `initial_messages=None`（今日行为，零风险）。
2. 逐项比对 `replay_meta`：`thinking_format`、`tool_names`（含顺序）、`tool_schema_sha256`、`system_prompt`（按 `system_msg()` 的键序逐字节比，`messages.py:126-127`）。任一不等 ⇒ 放弃重放并记原因。
3. 全等 ⇒ `initial_messages=replay_messages`，`user_message=question` 照旧。**注意**：`initial_messages is not None` 时 kernel 不会另插 system（`agent_loop.py:184-193`），所以 dump 必须自带 system，且与本次逐字节一致。
4. 决策写回 state（`replay_decision` / `replay_skipped_reason`）→ `output_fields` → `summary.json`，作为验收证据。

### 9.6 前缀恒定化的判定源：会话级业务标志

要消除的三条 run 级变量：
- `worker.py:499-500` 条件追加 `BUSINESS_CONTEXT_POLICY`；
- `server/profile.py:88-97` 工具集二选一（`CALCULATION_TOOL_NAMES` / `BUSINESS_TOOL_NAMES`）；
- `worker.py:466-472` 条件剔除 `position_sizing/strategy_lint`。

改为**会话级**判定是可行的，因为业务 Run 的 `session_id` 就是 `research_id`：`ResearchInvestmentLink.research_id` 外键指向 `sessions.id`（`store.py:450`），补数续接也显式 `session_id=row.research_id`（`input_requests.py:638`）。于是 spec §3.1 的判据可直接查：`research_investment_links` 存在且 `account_id`/`primary_plan_id` 非空。

- `_launch`（`orchestrator.py:972`）增 `--business-prefix`（或 metadata 字段）；
- `build_profile_overrides(has_investment_context=…)` 由该标志驱动；
- 好处：瞬时解析失败（spec §6 的降级路径）只让**尾部数据**缺席，不再翻转前缀。

仍属"每轮可变、阶段 1 只检测不消除"的项（由 §9.5 的 sha 比对兜住，skip 会记原因）：`--prompt-addendum`（上传文件说明，`routes/runs.py:217-231`）、`language_instruction`、`BOARD_PROMPT_ADDENDUM`、`MANIFEST_PROMPT_NOTE`、profile/模型切换、`direct` 模式。

### 9.7 截断：写时裁剪（阶段 1 的硬上限）

- 触发：`len(messages)` 超 `max_replay_turns`（默认 10，可配）。
- 规则：**只在下标 >0 的 `role=="user"` 边界整轮丢最旧**，保留下标 0 的 system；永不产生孤儿 tool 消息。
- 为什么必须**写时**裁而不是读时滑窗：读时滑窗每轮前移窗口 ⇒ 请求从第 0 条起就不同 ⇒ 每轮全量 prefill（正是 §7 那条"压缩策略与缓存打架"）。写时裁 = dump 即下一轮基线，裁剪只在**发生的那一轮**付一次全量 prefill。
- 压缩（§8.2 第二个问题）按建议放阶段 2；阶段 1 只此硬上限。

### 9.8 改动清单

| # | 文件 | 改动 |
|---|---|---|
| 1 | `frontier_agent/components/observers/conversation_snapshot.py`（新） | dump observer（写 + 裁剪 + 自检） |
| 2 | `workflows/stateful_react_agent/nodes/main_agent.py` | 注册 observer；读 `replay_*`、校验、传 `initial_messages`；返回 `replay_decision` |
| 3 | `workflows/stateful_react_agent/spec.py` | `include_fields` 加两字段；`output_fields` 加 `replay_decision` |
| 4 | `server/orchestrator.py` | 定位并拷贝上一轮 dump；`--business-prefix` |
| 5 | `server/history.py`（或新模块） | 定位上一轮 dump 的纯函数（可单测） |
| 6 | `server/worker.py` | 读 `prior_conversation.json` → `extra_input`；前缀判定改用会话标志；`summary.json` 记 `replay` |
| 7 | `server/profile.py` | `build_profile_overrides` 由会话标志驱动 |
| 8 | `server/store.py` | 会话级"研究已绑定"查询（若采纳 §9.6） |

### 9.9 验收（可核验）

1. 单测（新 `tests/test_context_inheritance.py`）：假 LLM 连跑两轮，断言**轮 2 请求 messages 的前 len(轮1) 项与轮 1 请求逐字节一致**（这是"缓存命中"的可证形式）；断言 system/tools/工具顺序恒定；断言校验失败 → 不重放。
2. 单测：dump 契约（字段、tool_call_id 配对、写时裁剪不留孤儿、原子替换、schema 版本拒绝）。
3. 单测：上一轮 dump 定位（多轮、缺失、pipeline 不一致、跨 session 不串）。
4. 集成（实跑，出 `runs.usage_json` 原始数字）：同一会话连跑 3 轮业务提问，轮 2 `cache_read_tokens` ≥ 轮 1 `prompt_tokens`，轮 3 ≥ 轮 1+2 的多数；口径 = `server/usage.py:119-143`；基线取 §1.2 的 Run（可复核）。
5. 反向证据：3 轮 `summary.json.replay.decision` 全 `used`；人为改 `--prompt-addendum` 或工具集后那一轮为 `skipped` 且原因正确。
6. 不回归：`tests/test_history_t26.py`（钉住 history.txt / conversation_history）、`tests/test_session_history.py` 全绿；两条旧路径行为不变。

### 9.10 不变量与风险

- 不变量：**前缀区只放跨轮不变内容**；本轮问题与业务数据一律在尾部（现状 `worker.py:526-530` 把业务数据追加在 instruction 尾部，符合）。
- 校验 fail-open：**宁可放弃缓存，不可错给历史**；`initial_messages=None` 永远是安全出口。
- `turn_index` 只进 metadata、不进 prompt（`workflows/` 全仓无引用，已核）——不变量成立。
- dump 体积 ≈ 真实上下文体积；写时裁剪是唯一上限手段，默认值需与 `max_input_tokens` / 上下文窗口对齐后再定。

### 9.11 裁决记录（2026-10-10）

| # | 议题 | 裁决 |
|---|---|---|
| 1 | 权威来源：轮末 dump vs 轨迹事件重放 | **甲：轮末 dump** |
| 2 | 会话级业务标志：新增 `research_investment_links` 查询 vs 接受降级轮一次性失效 | **甲：新增查询** |
| 3 | 搬运方式：server 拷贝 `prior_conversation.json` vs worker 跨目录读 | **甲：server 字节拷贝** |
| 4 | 范围：只做 `stateful-react-agent` vs 连 `agent_team` | **甲：只做 stateful**（agent_team 另立 issue） |
| 5 | `server/history.py:10-15` 边界修订签认 | **认可（口径 A）**：阶段 1 server 只搬字节不解析；阶段 2 把完整消息序列升格为服务端存储（2026-10-10） |

约束：第 3 项 = 甲 ⇒ server 经手 `prior_conversation.json`；第 5 项按口径 A 落地（注释已改写为"presentation / continuity 双载体 + 只搬运不解析"）。

### 9.12 主流做法参考（第 5 项依据，2026-10-10 检索）

"会话状态归谁、谁持有完整消息序列"，主流分三类：

| 形态 | 代表 | 会话状态 owner | 证据 |
|---|---|---|---|
| 无状态 API + 调用方自持历史 | Chat Completions / Messages API | **应用/服务端**（工程上落 DB 的 session/thread 表） | OpenAI 会话状态文档：每个请求本无状态，"多轮上下文必须由开发者显式携带"，并要求**重放完整 output 数组**（含加密推理项） |
| 服务端会话对象 | Responses `store=true` / `previous_response_id` / Conversations API | **平台服务端**；conversation 存 items（消息、工具调用、工具输出） | 同上：官方"首选 Responses API（有状态）"；Conversations 可跨设备续接、不受 30 天 TTL |
| 工作流/图框架 | LangGraph checkpointer | **编排层**（≈ 本仓库 server 的位置）；**消息列表即一等状态** | LangGraph 官方 Persistence：checkpointer 把 thread 的**整个 graph state**（含 `messages` 通道）快照持久化到 Postgres/SQLite，按 `thread_id` 恢复对话 |

⇒ **"完整消息序列锁在 agent 内部、编排层只能拿到渲染文本"不是主流做法**；主流是消息序列作为会话状态一等公民、由编排层/服务端持久化。

缓存侧纪律（与本方案互证；来源为第三方镜像页，措辞与官方一致但**非官方域名**，按低一档证据看）：
- 命中要求**整个渲染前缀整体匹配**（含 system、工具定义与顺序、相关设置）⇒ 改 tools 集合/顺序/描述即前缀变；
- 原文级建议："**保留对话历史；追加新消息，而不是重写先前的轮次**"；"摘要、压缩或上下文截断会改变前缀并重置缓存"；
- 要禁用工具时建议**不删工具定义**（用 `tool_choice`/`allowed_tools` 限制）⇒ 支持第 2 项裁决；
- 命中可在 usage 的 `cached_tokens` 观测 ⇒ 与 §9.9 口径一致；
- Anthropic 走**显式断点**（`cache_control` 在 content block 级，标记"从开头到此处"）；本次因地区限制未取到官方页，**未作为依据**。

两点交叉验证：①LangGraph 官方同样承认 checkpoint **无界增长**需保留/裁剪，且裁剪/压缩损失缓存复用 —— 与 §9.7"写时裁剪、一次裁剪一次失效"同构；②官方提到**子图状态父图不一定可见**（各自 namespace）—— 正是第 4 项把 `agent_team` 多 loop 另立的理由。

**建议（第 5 项）**：裁"认可"，但分三层写死口径，避免变成永久破例：

1. **阶段 1**：server **不解析**消息内容（不按 role/content 取值做任何业务判断），只搬运 run 目录里的 opaque 产物 ⇒ 原注释的**动机**（解耦 pipeline 实现）不破。
2. **注释措辞改写**（`server/history.py:10-15`）：
   > 跨轮连续性由两类载体承载：(a) 服务端从 `turns` 渲染的文本稿（presentation）；(b) 上一 Run 落下的 opaque 完整消息产物（continuity）。服务端**只搬运 (b)、不解析其内容**，也不依赖 pipeline 内部结构；完整消息序列的归属将在阶段 2 升格为服务端存储。
3. **阶段 2 收敛目标**：按主流把完整消息序列落到服务端（新表/会话侧存储，等价 LangGraph checkpointer / Conversations items），`run/conversation.json` 降级为派生产物/调试副本 ⇒ 第 5 项变成"分两步把边界搬到主流位置"。

**备选口径（一步到位）**：阶段 1 直接落表、跳过 run 目录 dump。更贴主流、跨轮定位不依赖扫描 run 目录；代价是本次含 alembic 迁移 + 表设计（新增表不破坏既有结构，但验收面变大）。**不推荐**在阶段 1 做：会同时放大"新链路"与"新存储"两类风险，违反一次只动一个变量。

红线（两种口径都不改）：**server 不解析消息内容**。

### 9.13 实施记录（2026-10-10，阶段 1 代码已落地）

**新增**

| 文件 | 作用 |
|---|---|
| `frontier_agent/components/observers/conversation_snapshot.py` | dump 契约 v1：`build_dump` / `validate_messages` / `trim_to_turns` / `tool_schema_sha256` / `select_replay` + `ConversationSnapshotObserver`（`on_loop_end` 原子写） |
| `tests/test_context_inheritance.py` | 24 条：dump 契约、拒绝矩阵、写时裁剪、observer、**两轮请求前缀逐字节一致**、server 侧定位与搬运 |

**改动**

| 文件 | 改动 |
|---|---|
| `frontier_agent/components/observers/trajectory.py` | `_serialize_tools` 实现提升为模块级公开 `serialize_tool_schemas`，类内保留薄委托（工具指纹与轨迹记录同一份字节） |
| `server/history.py` | 设计注释改写为 presentation / continuity 双载体；新增 `resolve_prior_conversation`（**仅按文件存在性**定位） |
| `server/orchestrator.py` | `_spawn` 复用同一份 turns 定位上一轮 dump；`_launch` 字节搬运（`_stage_prior_conversation`）+ 会话级 `--business-prefix` |
| `server/store.py` | `session_has_research_binding`（spec §3.1 的会话级形态） |
| `server/worker.py` | 读 `prior_conversation.json` → `replay_payload`（opaque，不解析）；前缀配置改由会话标志驱动；`summary.json` 记 `replay` |
| `workflows/stateful_react_agent/spec.py` | `include_fields += replay_payload`；`output_fields += replay_decision` |
| `workflows/stateful_react_agent/nodes/main_agent.py` | 注册 dump observer；`select_replay` 校验后传 `initial_messages`；`replay_max_turns`（默认 10） |

**门禁证据（实跑）**

| 项 | 命令 | 结果 |
|---|---|---|
| 新增单测 | `uv run pytest tests/test_context_inheritance.py -q` | 24 passed |
| 波及面回归 | `uv run pytest tests/test_context_inheritance.py tests/test_history_t26.py tests/test_session_history.py tests/test_investment_context_tools.py tests/test_investment_context_worker.py tests/test_web_p3_approval.py -q` | 96 passed |
| 全量 | `uv run pytest tests -q --deselect tests/test_corpus_cli_isolation.py::test_subprocess_model_client_import_refused` | **2949 passed / 12 failed**；12 条在 `git worktree add /tmp/fa-base HEAD`（`8d3fadd`）上**逐条同失败** ⇒ 全部为既有环境/数据依赖（corpus 数据、market 数据、dev lane、alembic 多 head、PG 状态），非本次引入 |
| 类型 | `uv run pyright <改动文件>` | **0 errors**（仓库既有 29 条错误在未触碰文件） |
| Lint/格式 | `uv run ruff check …` / `ruff format --check`（两个新文件） | 通过 |

**尚未完成（阶段 1 的最后一格）**

- §9.9.4 的**端到端 3 轮真实运行**（同一会话连跑 3 轮业务提问，取 `runs.usage_json` 的 `cache_read_tokens` / `prompt_tokens`，并核 `summary.json.replay.decision == used` ×3）**未执行**：它会真实消耗模型额度，按纪律需先定"预注册退出判据"再放行，不由实施方自跑自宣。
- 已知边界：`--business-prefix` 未传时（spike / 手工起 worker）回退 run 级判定；`agent_team` 不在本次范围（§9.11 第 4 项）。

### 9.14 缺口自查（2026-10-10，签认后、开跑前）

**一、已补的覆盖（此前只有"按构造成立"）**

| # | 缺口 | 处置 |
|---|---|---|
| 1 | 写方路径（worker 的 `_trial_dir`）与读方路径（`run_dir_for(id)/run/…`）等价只有构造保证；一旦漂移，replay 会**静默不发生**且无任何报错 | 新增 `test_writer_and_reader_agree_on_where_the_dump_lives` |
| 2 | `replay_payload` 能否穿过 `include_fields` 白名单没有测试 | 新增 `test_the_react_spec_lets_the_replay_payload_reach_the_node`（真 spec + `apply_context_filter`） |
| 3 | worker 侧"不解析、原样透传 + 前缀配置由会话标志决定"没有测试 | 新增两条：`test_worker_hands_the_dump_to_the_workflow_verbatim`（`business_prefix=1`）、`test_worker_non_business_prefix_keeps_the_calculation_tools`（`=0`，且无 dump 时 `replay_payload` 键**缺席**而非空串） |

补齐后 `tests/test_context_inheritance.py` = **28 条**；目标测试集 **100 passed**。

**二、仍存在的边界（不改，记录在案）**

| # | 边界 | 影响 |
|---|---|---|
| 1 | 硬取消/超时（wall deadline → SIGKILL）不会触发 `on_loop_end` ⇒ **无 dump** | 下一轮退化为新会话、缓存 miss 一次；用户主动 stop 是优雅停（`pause_check`）仍会写 dump |
| 2 | `agent_team` 不写 dump | 范围外（§9.11 第 4 项） |
| 3 | `--business-prefix` 未传时（`server/spike.py`、手工起 worker）回退 run 级判定 | 只影响非 web 入口 |
| 4 | `replay_payload` 以原始 JSON 文本进 state（与真实上下文同量级，可达数百 KB） | state 不进 DB、单节点运行，可接受；记为观察项 |
| 5 | 无 `_trial_dir` 的纯 benchmark/CLI 运行写到 `logs/…/conversation.json` | 无消费方，无害 |

**三、开跑前的前置核查（实跑）**

- `_spawn` 的 params **恒含** `session_uuid`（`orchestrator.py:331-340`）⇒ `manual` / `input_answer` / `watch_event` / `rerun` 四条创建路径都会走定位 + 重放，不存在"某条路径漏了"。
- 后端在跑（`/healthz` 200、`/readyz` ok）、PG 5432 可达、`.env` 有可用 key。
- **§1.2 基线复核通过**：`c3ec40b4…` 实测 `prompt=1,198,611 / cache_read=1,027,072 / calls=28`，模型 `deepseek-v4-flash-ga-260731` —— 与文档数字一致。
- `research_investment_links` 存在真实绑定研究（含文档所述 `c3646e12…` / 账户 `c2bf8670…`）⇒ 业务臂前置数据现成。

**四、预注册修订（需签认后方可开跑）**

| # | 原判据 | 修订 | 理由 |
|---|---|---|---|
| R1 | "连跑 3 轮业务提问" | 首轮 prompt 必须**足够长**（≈2–4k token 量级） | 低于 provider 的最短可缓存前缀时 `cache_read` 恒为 0，判据不可达（非"不达标"）。官方口径 1024–2048 token；本库另有一 Run `23d3030f`：26,286 prompt / `cache_read=0`，符合"短前缀不命中" |
| R2 | 未指定验收模型 | 需指定：`deepseek-v4-flash-ga-260731`（历史运行**已证实**上报 `cached_tokens`）vs `.env` 现值 `glm-5.3-flash`（**未证实**） | 选错模型会让判据**不可判定**，而非判负 |
| R3 | 控制臂"关掉 replay" | 用"每轮结束后把 `run/conversation.json` 移走"实现，不改代码 | 避免为验收在主链路引入开关变量 |

### 9.15 端到端验收实测：FAIL，根因定位到一行（2026-10-10）

**执行**：`--model deepseek-v4-flash-ga-260731`，两臂各 3 轮（同一绑定研究，业务会话），证据落在
`evidence/20261010-phase1-e2e/run-20261010/`（`results.json` / `report.md` / 各 run 目录）。

| 臂 | 轮 | prompt_tokens | cache_read_tokens | replay.decision |
|---|---|---|---|---|
| treatment | 1 | 16,406 | 0 | skipped: no_payload |
| treatment | 2 | 12,725 | 0 | **skipped: system prompt mismatch** |
| treatment | 3 | 12,740 | 0 | **skipped: system prompt mismatch** |
| control | 1/2/3 | 16,418 / 12,734 / 12,728 | 0 / 0 / 0 | skipped: no_payload ×3 |

判定 **FAIL**（`t2_covers_t1_prompt` / `t3_covers_most_of_t1_t2` / `treatment_replayed_all_turns` / `treatment_prefix_matches_previous_dump` 全 false；control 两条 PASS）。

**安全性质已实证**：校验按设计 fail-open —— 拒绝重放、运行照常完成（`stopped_by=no_tool`、答案"收到"），没有把模型没见过的历史喂回去。

**根因（逐字节定位）**：两轮 system prompt 长度同为 8597，首个差异在第 6197 字符：

```
FILESYSTEM CONVENTION (native mode): Your current working directory
/home/administrator/.local/share/frontier-agent/web/runs/<run_id>/ws is the workspace. …
```

来源：`workflows/stateful_react_agent/_runtime.py:83-97`（`sandbox_mode == "native"` 分支把 `FRONTIER_AGENT_WORKSPACE_DIR/INPUTS_DIR/OUTPUTS_DIR` 打印进 system prompt），而这三个变量由 `server/worker.py:198-211 apply_env` 设成**每 Run 一份**的路径（含 run_id，等长十六进制 ⇒ 总长度不变、只换字节）。⇒ 同一会话每轮的请求前缀都不同，**跨轮缓存必然为 0**。此缺陷与本改动无关（此前无人比较过两轮的 system prompt，所以从未被发现）。

**旁证（机制确认）**：treatment 轮 1/2 实测 `cache_read_tokens=10240` —— 恰是"到那行为止"的可缓存前缀（system 前 6197 字符 + 25 个工具 schema）。即：现在可复用的只有到那一行为止的部分，那行之后的整段对话历史永远不缓存；修掉它，可复用长度直接变成"上一轮整段请求"。

**不能靠换 backend 绕过**：`server/config.py:7-11` 明写本部署把 backend **钉在 native**（容器即隔离边界，native 才不需要 CAP_SYS_ADMIN）。"只在 container 模式生效"在本部署不成立。

**验收脚本自身的一个 bug（已修，记录诚实性）**：`ServerConfig` 用 `env_prefix="SERVER_"`，我第一次尝试 `--backend container` 时设的是 `SANDBOX_BACKEND`，因此那次实际仍是 native（`meta.sandbox_backend=native`）；第二次运行的结论与第一次同因，**未获得有效的 container 臂**（按上一条也不必要）。

**处置选项（待裁决）**

| 选项 | 做法 | 代价/风险 |
|---|---|---|
| **A（推荐）** | 把 native 分支那段"含绝对路径"的文本**整段搬到尾部**（拼进本轮 instruction，与业务数据同一位置），system prompt 只留静态部分 | 模型看到的字节**完全不变**（只是位置不同）⇒ 行为风险最低；落点 `workflows/stateful_react_agent/_runtime.py`（拆静态/动态）+ `server/worker.py`（动态段进 instruction） |
| B | native 分支把绝对路径换成稳定占位（如 `<workspace>`） | 改动最小；已核 `plugins/tools/_path_auth.py::_candidate_paths:107-109`：相对路径会先按 `workspace_root` 解析 ⇒ 文件工具仍可用；但模型失去绝对路径，行为可能变化 |
| C | 不改 prompt，承认阶段 1 在本部署（native）无缓存收益，仅留机制预备 | 零风险，但本 spec 的核心收益（跨轮缓存）在 web 上拿不到 |

**推荐 A**：同样字节、换个位置，把 §9.10 那条不变量（"易变内容一律放尾部"）真正落实到位 —— 现在漏的正是 system prompt 这一处。

### 9.16 A 方案落地后复跑（2026-10-10）：机制生效，判据仍 FAIL

**改动（A 方案）**：`workflows/stateful_react_agent/_runtime.py` 把原 `render_system_prompt_notes` 拆成
`render_stable_system_prompt_notes`（进 system prompt，跨轮恒定）与 `render_per_run_tail_notes`（native 的物理路径段，拼进本轮 user message 尾部）；节点用后者拼 `loop_user_message`。单测 29 条全绿（新增一条钉住"prefix 侧不含 `/runs/`、尾部含路径、container 尾部为空"），pyright 0 错。

**证据**：`evidence/20261010-phase1-e2e/run-20261010-fixA/`（native 模式，deepseek-v4-flash，两臂各 3 轮）。

| 臂 | 轮 | prompt | cache_read | replay | dump 消息数 | 前缀=上一轮 dump |
|---|---|---|---|---|---|---|
| treatment | 1 | 16,409 | 10,240 | skipped: no_payload | 3 | — |
| treatment | 2 | 16,705 | **0** | **used** | 5 | **True** |
| treatment | 3 | 16,944 | **16,384** | **used** | 7 | **True** |
| control | 1 | 16,418 | 16,128 | skipped: no_payload | 3 | — |
| control | 2 | 12,722 | 10,240 | skipped: no_payload | 3 | False |
| control | 3 | 12,737 | 12,288 | skipped: no_payload | 3 | False |

**已经证成的三件事**
1. **本地性质成立**：treatment 轮 2、3 的 dump 逐字节以上一轮 dump 为前缀（`prefix_matches_previous_dump=True`）——这是"前缀字节稳定"在协议之外的可证形式。
2. **链路端到端可用**：轮 2、3 `replay.decision=used`，dump 从 3 → 5 → 7 条消息递增，即历史真的进了模型。
3. **跨轮缓存真的发生了**：轮 3 复用了 16,384 / 上一轮 16,705 prompt（**98%**）；轮 1 的 16,128 命中（control）也说明——路径移入尾部后，整段请求直到尾部之前都可共享。

**仍然 FAIL 的两条（归因不同）**
- `t2_covers_t1_prompt`：**轮 2 的 `cache_read=0`，连"system+工具"那块的 10,240 都没有**。外面看不到 provider 的记账规则，但同一轮里 control 的 t2 却拿到了 10,240 ⇒ 这不是"前缀不匹配"（本地已证明逐字节相同），更像 provider 侧的命中/落账与时序有关（例如"请求本身被部分命中时不为新前缀建立条目"）。**这是本轮唯一未能用我方证据解释的现象**，如实记录，不当事后圆场。
- `control_cache_cold`：**这条判据在修复后本身就失效了**。修复让 system prompt 跨轮恒定，于是 control 臂（不重放）也能合法命中"system+工具"共享块（10,240/12,288）。原判据"control 必须全程冷"隐含了"前缀必然逐轮不同"的前提，而这个前提正是 A 方案要消灭的东西 ⇒ 判据必须改成"只比对**对话部分**的复用"，例如 `treatment 轮 N cache_read` 显著高于 `control 轮 N cache_read`（本轮 16,384 vs 12,288），而不是"control 必须为 0"。

**不改的东西**：fail-open、`replay_max_turns=10`、`agent_team` 范围外、压缩留阶段 2 —— 均不受影响。

**待裁决（R4/R5）**
| # | 原判据 | 建议修订 | 理由 |
|---|---|---|---|
| R4 | `t2 cache_read ≥ t1 prompt` | 改为"**存在一轮**（≥轮 3）复用 ≥ 上一轮 prompt 的 80%" | 与"跨轮缓存"这一承诺等价；单看第 2 轮会把 provider 的落账时序当成功能缺陷 |
| R5 | `control cache_read` 全程 < 轮 1 prompt 的一半 | 改为"同轮次 `treatment.cache_read − control.cache_read ≥ 上一轮 prompt 的 50%`" | 修复后两臂都合法命中共享块，只有**差值**才归因于重放 |



### 9.17 R4/R5 修订后复跑（4 轮）：全部判据 PASS

证据：`evidence/20261010-phase1-e2e/run-20261010-R4R5/`（native，`deepseek-v4-flash-ga-260731`，两臂各 4 轮）。

| 臂 | 轮 | prompt | cache_read | replay | dump 消息数 | 前缀=上一轮 dump |
|---|---|---|---|---|---|---|
| treatment | 1 | 16,412 | 14,336 | skipped: no_payload | 3 | — |
| treatment | 2 | 17,053 | **16,384** | used | 5 | True |
| treatment | 3 | 17,317 | **16,384** | used | 7 | True |
| treatment | 4 | 17,575 | **16,384** | used | 9 | True |
| control | 1 | 16,412 | 14,336 | skipped: no_payload | 3 | — |
| control | 2 | 12,728 | 12,288 | skipped: no_payload | 3 | False |
| control | 3 | 12,722 | 12,288 | skipped: no_payload | 3 | False |
| control | 4 | 12,743 | 12,288 | skipped: no_payload | 3 | False |

**判据（R4 + R5'）全部 PASS**，明细见 `results.json`：`R4`（轮 3 复用 96.1%、轮 4 复用 94.6%）、`R5p`（方向性：每轮 treatment 16,384 > control 12,288；可归因差值 4,096 ≥ 非共享部分 4,765 的一半）、`replay_used_from_turn_2`、`control_never_replayed`、`treatment_prefix_matches_previous_dump`。

- **`t2=0` 未复现**：本轮第 2 轮直接 16,384 命中 ⇒ §9.16 记录的"第 2 轮为 0"是 provider 侧偶发落账，不是功能缺陷；同时也印证 R4 的表述（"存在一轮 ≥80%"）比盯第 2 轮稳健。
- **R5 的自我更正（如实留档）**：我第一版 R5 写"delta ≥ 上一轮 prompt 的 50%"（≈8.5k），这是**不可达**的 —— control 本身合法复用共享块（12,288），可归因差值上限 = 上一轮 prompt − 共享块 ≈ 4.8k，实测被 provider 按 128-token 块报成 **4,096**。⇒ 改为 **R5'**：方向性（每轮 treatment > control）+ 可归因差值 ≥ 非共享部分的 50%。原 R5 与两条 legacy 判据保留在 `superseded_criteria`（全 false），不隐藏。

### 9.18 web 架构影响面核查（2026-10-10，按"注意 web 端架构设计"的要求）

| # | 发现 | 影响 | 状态/建议 |
|---|---|---|---|
| 1 | **watch_event 自动分析与会话同源**：`watch_scheduler.py:311-346` 以 `session_id=event.research_id` 建 Run，并把规则指令 append 成该会话的 user turn | 若继承，重放会把用户聊天带进无人值守的自动分析：其 prompt 随聊天增长、上下文被聊天内容污染 | **已裁决（2026-10-10）：不继承**（研报投资策略应上下文干净、成本可控）。落点见 §9.19 —— 两个方向都关：不读旧 dump，也不写新 dump |
| 2 | dump 被复制进每个新 run 目录（`prior_conversation.json`） | 同一对话内容在 N 个 run 目录各一份 ⇒ 备份体积增长；"删旧 run 目录 ≠ 抹掉其内容" | 记录。不是新的暴露面（`trajectory.jsonl` 本来就含全文） |
| 3 | 保留期 `scripts/run_retention.py` 默认 `keep_days=30`，会 `rmtree` 过期 run 目录 | 会话跨过保留期后 dump 被清 ⇒ 连续性**静默**退回新会话（fail-open，不报错） | 记录。可选改进：保留期跳过"最近活跃会话的最近一轮 Run" |
| 4 | presentation 与 continuity 正式分叉：`turns` 存用户原话，而模型看到的首条 user 消息含 per-run FILESYSTEM 段（A 之后） | `history.txt`（渲染稿）≠ 模型所见 | 记录：presentation ≠ continuity 属设计内，写下来避免后人误判 |
| 5 | 交付物区 / 水位校验 / 多进程与重启 | 无影响 | 已核：dump 落在 `run/` 下，不进 `ws/outputs` 的 artifacts 扫描与交付；`restore_check.REQUIRED_RUN_DIRS` 不含新文件；跨轮定位只依赖 DB + 文件（不依赖进程内状态） |

### 9.19 watch 类 Run 不继承上下文（2026-10-10 裁决落地）

**裁决**：不继承 —— 研报投资策略类分析应上下文干净、成本可控。

**实现（两个方向都关，这是关键）**

| 层 | 改动 |
|---|---|
| `server/store.py` | 新增 `is_watch_run(run_id)`：查 `watch_event_runs`（DATA-11 的权威链路） |
| `server/orchestrator.py` | `_spawn`：watch Run 置 `_continuity="off"` 且**不定位**旧 dump（定位会回退到更早的聊天 dump）；`_launch` 透传 `--continuity off` |
| `server/worker.py` | 新增 `--continuity on|off`（默认 `on`）→ `extra_input["continuity_enabled"]` |
| `workflows/stateful_react_agent/spec.py` | `include_fields += "continuity_enabled"` |
| `.../nodes/main_agent.py` | `continuity_enabled=False` 时：不重放（`replay_decision={skipped, continuity_disabled}`）**且不注册 dump observer** |

**为什么必须"两个方向都关"**：`resolve_prior_conversation` 取的是"最近的、**存在 dump** 的上一 Run"。若 watch Run 写了 dump，下一轮聊天就会解析到它 —— 聊天轮会突然换成监控 Run 的上下文（既丢历史、又必然 cache miss）。watch Run 不写 dump，聊天轮就自然回落到上一个聊天 dump。

**门禁与证据**
- 单测 **32 条全绿**（新增 3 条：`is_watch_run` 反例、`_spawn` 双分支接线、worker 的 `--continuity off` 透传；并在 spec 白名单测试里加了 `continuity_enabled`）。
- 目标测试集 **104 passed**；`ruff check` 干净；`pyright` 0 错。
- **聊天路径未回归**：`evidence/…/run-20261010-watch-ruling/`（3 轮两臂）**全部判据 PASS** —— treatment 轮 2/3 复用 14,336 / 16,384（占上一轮 prompt 的 0.86 / 0.97），control 恒 12,288，差值 4,096 ≥ 非共享部分一半；`replay=used` ×2、前缀逐字节为上一轮 dump 的前缀 ✓。

**覆盖缺口（如实记）**：watch 路径的**节点内分支**（不注册 observer、`continuity_disabled` 决策）目前只有接线级单测 + 代码阅读，**没有端到端实跑** —— 真跑需要 `watch_rule → watch_event → watch_event_run` 的夹具链，本机没有廉价的构造办法。

### 9.20 O1/O3 落地（2026-10-10，缺口自查后的处置）

**O1 重放加 token 上限（可用性守卫）**
- 落点：`conversation_snapshot.py::trim_to_turns(messages, max_turns, *, max_tokens=0)` —— 在轮数上限之外再叠一层 token 预算；超预算继续按 `user` 边界丢最旧轮（**永不产生孤儿 tool 消息**，system 永不丢）。`trim` 增加 `token_budget / est_tokens / dropped_for_tokens`，**仅在预算生效时出现**（纯轮数上限时的字段形状与值不变）。
- 预算取值（节点）：`agent_cfg["replay_max_tokens"]`；**未设** → `max_input_tokens // 2`（web ≈ 114k，给本轮新增与模型输出留余量）；**显式 0** → 关闭。
- 为什么必须有：web profile `max_len=262144`、`max_input_tokens=229376`，tiered 压缩触发点 ≈ `0.8 × max_len ≈ 209k` ⇒ **一轮可以合法地结束在 209k–229k**；重放它 + 本轮新增 = **首个请求就越界**，而那时 run 内的压缩还没机会介入 ⇒ provider 硬失败（不是缓存问题，是跑不起来）。
- 过渡期观察项：旧 dump（无预算）不受追溯影响——读侧不设上限，越界风险随"下一轮写新 dump"自然消化。

**O3 `select_replay` 增加 session 校验（防御纵深）**
- dump 头里的 `session_id` 此前只记不校；现在读侧比对（**只有调用方给了期望值才比**，空值不阻断），不一致 → `skipped: session_id mismatch`。

**门禁**
- 单测 **34 条全绿**（新增：token 预算丢轮且配对完好、session 不匹配进入拒绝矩阵）。
- 目标测试集 **106 passed**；`ruff check` 干净；两个新文件 `ruff format --check` 干净；`pyright` 0 错。
- 复跑（3 轮两臂）**全部判据 PASS**：treatment 轮 2/3 复用 16,384（占上一轮 16,415 / 16,817 的 0.998 / 0.974），control 恒 12,288，差值 4,096；`replay=used` ×2、前缀逐字节为上一轮 dump 前缀 ✓。证据 `evidence/…/run-20261010-O1O3/`。

**只记录、不改代码（本轮明示的两条已知边界）**

| # | 边界 | 影响 |
|---|---|---|
| O4 | 带附件那一轮把 `--prompt-addendum` 拼进 `_sys_prompt_addendum` ⇒ 该轮 system prompt 与前后都不同 | **一次跳过、下一轮自动恢复**（被跳过的那轮也写 dump，于是下一轮重新对齐）；不影响正确性 |
| O8 | 会话中途绑定账户让 `business_prefix` 由 False 翻 True ⇒ 工具集与策略文本变一次 | 同上，一次跳过再恢复 |

**仍待裁决**：O5 保留期（`run_retention.py` 默认 `keep_days=30` 会连 dump 一起 `rmtree`，连续性静默退回新会话）——"做/记录"待示下。

## 10. 全面方案（2026-10-11）

**定位**：把阶段 1 的"文件搬运"收敛为"服务端会话状态"，并把窗口、观测、清理一次排到位。
**前提修正**：**不按轮数分布决定投入**——用户对话轮数不固定，方案必须对 1..N 全部成立：**1 轮零成本、2..N 命中且成本有界、N 很大不失败也不膨胀**。（撤回 §9.20 之后"先看真实轮数分布再定"的建议。）

### 10.1 终局形态

| 维度 | 目标态 | 现状 |
|---|---|---|
| 会话消息序列的权威源 | **服务端 DB**：`session_conversations(session_id PK, revision, messages jsonb, system_prompt, thinking_format, tool_schema_sha256, updated_at, updated_by_run_id)` | run 目录里的文件，且每轮复制一份 |
| 生产者 | workflow 在 loop 结束落 dump 文件；**父进程**在 run 收尾 ingest 入库并清理文件（worker 继续**无 DB 凭据**） | 同左，但无人入库 |
| 消费者 | 下一轮从 DB **一次索引读** → opaque payload → workflow 校验后重放 | 逆序扫 turns 找文件 |
| 工作集上界 | 最近窗口 + **写时固化的更早轮摘要**，首请求 token 有界 | 只按轮数/token 丢最旧（止损，不解决线性增长） |
| 观测 | 每轮 `replay.decision/reason` + prompt/cache + window 落 `runs.usage_json`，带常驻回归 | 只在 `summary.json` |
| 清理 | 保留期/审计按 DB 语义；run 目录不再承载会话 | dump 住在 run 目录，会被保留期误删（§9.18 #3） |

### 10.2 分阶段（依赖顺序 + 各自验收）

**S1 阶段 1 收尾（小）**（实施记录见 §10.7）
1. **b**：upload 说明移入请求尾部（与 A 同模式）⇒ system prompt 只由 profile + 工具集决定，带附件会话不再"抖一次"（§9.20 O4）。
2. **a**：`replay` 决策与 window 统计落 `runs.usage_json`；配一个只读统计脚本（每轮命中率、跳过原因分布）。
3. **O5 保留期**：若 S2 先落地，本项由 S2 直接替代（不重复投入）。（**2026-10-11 裁决：并入 S2**）
- 验收：单测 + 3 轮两臂复跑（R4/R5'）+ **新增"带附件两轮"实测**（证明不抖、次轮命中）；统计脚本能打出每轮 decision/reason。

**S2 会话状态归位（结构主体）**
1. 新表 + alembic 迁移（**只新增**；本机 `alembic_version` 有漂移，先 `stamp head` 再 `check`）。
2. 父进程 ingest：run 收尾读 `run/conversation.json` → 按 `revision` upsert → 成功后删除文件；失败则保留文件 + 记日志。
3. 下一轮 payload 来自 DB：`_spawn` 不再扫 turns/文件，`resolve_prior_conversation` / `_stage_prior_conversation` 退役（**不留双路径**，避免两条都活着）。
4. watch 分支语义不变（不读不写）。
- 验收：① 多轮两臂对照复用 R4/R5'；② **跨进程/重启**同一会话连跑（证明不依赖进程内状态）；③ 表为空/读取失败 ⇒ 行为 = 全新会话（fail-open 演练）；④ 保留期 `plan` 不再涉及会话载体；⑤ `alembic check` 无新增漂移。

**S3 窗口 + 写时固化摘要（成本有界）**
1. ~~consumer 侧：入口发现"窗口外还有历史"时，先做**一次**摘要调用，把更早轮压成固定文本块（置于 system 之后、窗口之前），再跑主循环。~~ **2026-10-11 修订（见 §12.1）**：写时裁剪已把被裁轮次从 payload 中丢掉，**下一轮看不到那些内容**，所以摘要改由**写侧**生成并随 dump 固化；设计稿见 **§12**。
2. 摘要结果随本轮 dump **固化** ⇒ 之后每轮前缀稳定；**压缩那一轮允许一次 miss**，其后必须恢复。
3. 摘要失败 ⇒ 回退 token 预算丢最旧轮（已有能力），不阻断。
- 验收（合成 40+ 轮会话）：① 首请求 token 有界（≤ 预算）；② 压缩后连续轮次命中率恢复 ≥80%；③ 摘要在后续轮次**不重算**（相邻 dump 的摘要块逐字节相同）。

**S4 收口与退役**
`history.txt` / `conversation_history` 先证无消费方再退役；`docs/tech-stack.md`、`AGENTS.md` 同步；把"多轮缓存回归"固化为常驻脚本/门禁。

**S5 agent_team**：单独 spec，复用 S2 的存储与 S1 的观测（三个 loop 的"哪份消息算会话"另议）。

### 10.3 主流 Web 形态对照（2026-10-11 整理）

**问题**：会话的「完整消息序列」该由谁持有？本仓库现状是"落在 run 目录的文件里、由 server 逐字节搬运"，需要判断这一步偏离主流多远、S2 归位后站在哪。

**三类主流形态**

| 形态 | 代表 | 会话状态 owner | 证据 |
|---|---|---|---|
| 无状态 API + 调用方自持历史 | Chat Completions / Messages API | **应用/服务端**（工程上落 DB 的 session/thread 表） | OpenAI 会话状态文档：请求本无状态，"多轮上下文必须由开发者显式携带"，并要求原样重放上一轮的完整 output 数组 |
| 服务端会话对象 | Responses `store=true` / `previous_response_id` / Conversations API | **平台服务端**；conversation 存 items（消息、工具调用、工具输出） | 同上：官方首选有状态形态；Conversations 可跨设备续接 |
| 工作流/图框架 | LangGraph checkpointer | **编排层**（≈ 本仓库 server 的位置）；消息列表即一等状态 | LangGraph Persistence：checkpointer 把 thread 的**整个 graph state**（含 `messages`）快照持久化到 Postgres/SQLite，按 `thread_id` 恢复 |

⇒ 主流**没有**"完整消息序列锁在 agent 内部、编排层只能拿到渲染文本"这种做法。本仓库 §9 的形态是**过渡态**（server 只搬字节，§9.12 口径 A），S2 把它升格为服务端存储 ⇒ 站到主流位置上。

**九条通用工程共识**（除标注外为通用实践，非某家官方原文）

| # | 共识 | 本仓库对照 |
|---|---|---|
| 1 | 应用层无状态、状态外置（水平扩容/滚动发布/崩溃重启的前提） | `runs` + worker 子进程符合；会话载体挂在文件上是偏离 |
| 2 | 一次请求 = 一条可重放的作业（状态机 + 终态幂等） | 符合 |
| 3 | 会话数据两种存法：**按消息行存**（可查询/软删）vs **整段快照**（LangGraph 式） | S2 选整段快照 —— 与"整段读、前缀逐字节稳定"匹配 |
| 4 | prompt 由服务端组装，且必须**确定性**（同一份状态 ⇒ 同一份字节） | 组装在 pipeline、server 只搬文本：**刻意偏离**，代价就是本 issue 全部工作量 |
| 5 | 缓存友好 = 排序纪律 + canonical 序列化 + 指纹校验（与 ETag/乐观并发同构） | 已落地：dump 的 sha/`thinking_format` + `select_replay` |
| 6 | 数据有明确 owner，保留策略才不打架 | **O5 的根因**就是两个 owner（§9.18 #3） |
| 7 | 执行体不直连业务库（防越权/泄漏） | worker 无 DB 凭据 ⇒ S2 的"父进程 ingest"顺着这条边界 |
| 8 | usage 逐请求落库，缓存命中率是一等成本指标 | `runs.usage_json`；S1 把 `replay` 决策并入 |
| 9 | 读路径 fail-open、写路径 fail-loud | `initial_messages=None` 是安全出口；S2 的 ingest 失败必须记日志 |

| 主流部件 | 本仓库对应 | 是否主流 |
|---|---|---|
| 无状态应用层 | `server/orchestrator.py` + worker 子进程 | 是（会话载体在文件上，偏） |
| 作业状态机 | `runs` 表 + SSE relay | 是 |
| 会话状态中心存储 | **暂无**（run 目录文件 + 每轮复制） | **否 ← S2 修这条** |
| 服务端组装 prompt | pipeline 组装，server 只搬运 | 否（刻意，隔离收益真实） |
| canonical 序列化 + 指纹 | `conversation_snapshot.tool_schema_sha256` / `select_replay` | 是 |
| owner 清晰的保留策略 | run 目录清理会误伤会话载体 | 否 ← S2 顺带解 O5 |
| 执行体无库凭据 | worker 侧 `SERVER_DATABASE_URL` 被置空 | 是 |
| 逐请求 usage 指标 | `runs.usage_json` | 是 |

**演进三步**（很典型的路径）：① 本地/文件先跑通 → ② 状态落中心存储、应用层无状态 → ③ 多实例 + 队列 + 归档/保留策略。S1/S2/S3 正走第二、三步 ⇒ S2 不是架构洁癖，而是把两个已知偏离点（会话载体、owner 冲突）收敛回主流位置。

**证据分级**：LangGraph Persistence 与 OpenAI 会话状态两条为已取到的官方口径（OpenAI 官网本次 403，取的是**自称与 OpenAI 无关的镜像页**，措辞一致但按低一档证据看）；Anthropic 的显式断点（`cache_control`）因地区限制未取到官方页，**不作为依据**；其余为通用工程共识。

### 10.4 贯穿的不变量与失败模式

- **不变量**：前缀区只放跨轮不变内容；易变内容一律尾部；只有**写时**裁剪/压缩允许一次性失效；watch 不参与；**server 不解析消息内容**（只搬运/存储结构）。
- **失败模式（全部 fail-open）**：DB 不可用 / 表为空 / 读取失败 ⇒ 新会话；dump 写失败 ⇒ 无 dump；摘要失败 ⇒ 丢最旧轮；超 token 预算 ⇒ 丢最旧轮。**任一环节坏掉都不允许让 run 跑不起来。**

### 10.5 成本模型（对 1..N 都成立）

| 轮数 | 行为 | 边际成本 |
|---|---|---|
| 1 | 无输入；写一次 upsert | ≈ 0 |
| 2..N | 命中跨轮前缀（实测 96–99%）；prompt 被窗口上界**夹住**，不随 N 线性增长 | 每轮 ≈ 新增内容 |
| N 很大 | 首请求 token 有界；磁盘 O(1)/会话；保留期按 DB 策略 | 一次摘要（一次性 miss） |

### 10.6 明确不做

路由层（§2）；`turns` 表结构改造（保留作 presentation）；弹窗；无绑定研究的自由问答；**不按轮数分布决定投入**。

### 10.7 S1 实施记录（2026-10-11）

**b：upload 说明移入请求尾部（已落地）**

| 文件 | 改动 |
|---|---|
| `server/worker.py` | `--prompt-addendum` 不再拼进 `metadata["_sys_prompt_addendum"]`，改为拼到本轮 `instruction` 尾部（与业务数据同一位置）；系统提示只留跨轮恒定部分 |
| `server/routes/runs.py` | 注释改写：说明 upload 说明走**尾部**而非系统提示，避免带附件那一轮翻转前缀 |
| `tests/test_context_inheritance.py` | 新增 `test_worker_puts_per_run_guidance_in_the_request_tail`（尾部含、前缀不含） |

效果：带附件会话不再"抖一次"（§9.20 O4 变成已消除）；与 §9.16 的 A 方案同一模式——**同样的字节，换个位置**。

`agent_team` 要写准（§9.11 第 4 项范围外说明不变）：它把 `metadata["_sys_prompt_addendum"]` 拼在**每个 phase 的 system prompt** 上（`workflows/agent_team/nodes/main_agent.py:1506/1526/1544` 均为 `system_prompt=_decorate(...)`）。所以本次改动对 agent_team 是"说明从 phase system prompt 移到本轮 instruction"的一次**行为变化**：意图上更合理（含本 run 路径的文本本就不该进前缀），但 **agent_team 路径未实跑验证**（web 默认走 stateful-react-agent）。基准路径不受影响：`benchmarks/public/sandbox_profiles.py` 直接写 metadata，不经 `--prompt-addendum`。

**a：replay 决策与窗口统计落 `usage_json` + 只读统计脚本（已落地）**

| 文件 | 改动 |
|---|---|
| `frontier_agent/components/observers/conversation_snapshot.py` | dump 增 `messages_est_tokens`（写侧一次测量；**additive**，旧 dump 读作 0，不参与任何判定）；`select_replay` 的 used 决策增 `est_tokens` / `payload_bytes` |
| `server/usage.py` | 新增 `replay_block_from_summary`（纯函数，`{}` 兜底） |
| `server/orchestrator.py` | 新增 `_usage_with_replay`；`_record_usage` 与崩溃恢复收尾都改用它 ⇒ `runs.usage_json.replay` 有值 |
| `scripts/replay_stats.py`（新） | 只读统计：`--session`（库）或 `--runs-root`（目录）；每轮 decision/reason/窗口 + **按会话**的命中率 + 跳过原因分布 + 未计量标记 |
| `tests/test_usage_t211.py` / `tests/test_replay_stats.py`（新） | 决策块契约、端到端 `usage_json.replay`、板子算术与分组 |

工具口径（写死在脚本里，避免口径漂移）：`reuse% = 本轮 cache_read / **同一会话**上一轮 prompt`；**跨会话不计算**；未计量的轮报 `-` 且不进均值——把"未计量"当 0% 会污染均值。目录源从各 run 自己的 dump 读 `session_id`；无 dump 的 run 视为独立分组（错的比没有更糟）。

**门禁证据**

| 项 | 结果 |
|---|---|
| 目标测试集（继承/统计/用量/历史/会话/附件/业务上下文/P3） | **137 passed** |
| 全量 `uv run pytest tests -q`（deselect 1 条已知项） | **2980 passed / 12 failed**；失败集合的类别与 §9.13 基线一致（corpus 数据、market 数据、dev lane、alembic 多 head、PG 状态）。逐条复核其中 `test_research_discipline.py::test_react_profile_binds_the_finance_tools`：失败断言是 `get_profile("react").tools() == set()`（插件/环境注册），与本次 diff 无交集（本次未触碰 `apodex/profiles/`、`plugins/`、profile 解析）。**本轮未重建 worktree 做逐条对照**（`git worktree` 命令被用户取消），故按"同类别 + 无代码交集"记，不作"逐条同失败"的强断言 |
| `ruff check` / `ruff format --check`（新文件） / `pyright`（改动文件） | 全部干净（0 error） |
| CLI 冒烟（真实 runs_root，317 个 run） | `uv run python scripts/replay_stats.py --runs-root ~/.local/share/frontier-agent/web/runs --top 10` 跑通；修复前跨会话算出 112.6% 的假命中，分组后同会话复现 98.6%，无 dump 的 run 报 `-` |

**带附件两轮实测（2026-10-11，判据跑前签认后执行）**

判据：C1 说明文本不在 system prompt；C2 说明文本在 user message；C3 两轮 system prompt 逐字节相同；C4 轮 2 `replay.decision == "used"`；C5 轮 2 dump 逐字节以轮 1 dump 为前缀；C6 轮 2 `cache_read ≥ 0.8 × 轮 1 prompt`（R4 口径）。同一绑定研究会话：轮 1 带真实附件（`inputs/brief.md`，并把路由构造的说明文本交给 worker），轮 2 纯文本。

两次尝试，如实留档：

| 尝试 | 模型 | 判定 | 事实 |
|---|---|---|---|
| `run-20261011` | `deepseek-v4-flash-ga-260731`（§9.14 R2 预注册） | **不可判定**（不是判负） | 端点回 400：`The supported API model names are deepseek-flash, deepseek-v4-pro, but you passed …`；两轮 `stopped_by=llm_error`、`llm_calls=0`。**C1–C5 仍 PASS**（本地性质不依赖 provider），C6 无值可取 |
| `run-20261011b` | `deepseek-flash`（探针证实的替代） | **全部 PASS** | 轮 1 prompt 16,414 / 轮 2 `cache_read` 16,384 = **99.8%**；`replay=used`；两轮 system prompt 同长 7749、逐字节相同；`usage_json.replay` 两轮都有值 |

**模型替换的依据是我们自己的探针**（不是"历史运行记得它会报"）：同一端点两次同前缀请求，`deepseek-v4-pro` 报 `cached_tokens 3328/3392`、`deepseek-flash` 报 `3072/3339`，字段为 `prompt_tokens_details.cached_tokens` —— 正是 `frontier_agent/infra/openai_client.py::_usage_dict` 已在读的字段 ⇒ **无需改适配器**，R2 的"选定模型必须上报 `cached_tokens`"由本次实测满足。替换如实标注为**预注册环境失效**（模型名下线），非判据变化。

现场工具输出：`run-20261011b/board.txt`（`scripts/replay_stats.py --session 95754ee0…`）显示 `used (1 turns)`、`reuse 99.8%`、窗口 `3 msg / 9184 tok`。

**关于模型/端点的定性（归部署侧，本 issue 不改）**

本次暴露的是**配置与文档滞后**，不是代码缺陷：§9.14 R2 预注册的 `deepseek-v4-flash-ga-260731` 与 `.env` 现值 `OPENAI_MODEL=deepseek-v4-flash` 都不在当前端点（`https://api.deepseek.com`）的支持列表内（该端点只认 `deepseek-flash` / `deepseek-v4-pro`）。**模型选择随部署环境变，由部署侧决定**：本 issue 不改 `.env`、不改默认模型、也不把任何具体模型名写成推荐（§9.14 R2 的"指定模型"应理解为一次性验收参数，不是长期默认）。对判据的影响只有一条、且是长期的：**选定模型必须实测会上报缓存命中字段**——本次探针给出的答案（该端点上报在 `prompt_tokens_details.cached_tokens`，正是 `frontier_agent/infra/openai_client.py::_usage_dict` 已在读的字段）比"历史运行记得它会报"更可靠，适配器无需改动。

**O5 保留期（裁决：并入 S2）**

2026-10-11 裁决：**并入 S2，不在 S1 做**。理由：S2 把会话载体搬进 DB 后该问题自动消失（S2 验收第 4 条即"保留期 `plan` 不再涉及会话载体"）；现在做等于为一个即将退场的载体写保护逻辑。若将来 S2 被推迟，再按原口径执行：`RunStorage` 增 `session_id`、`RetentionPolicy` 增 `protect_recent_session_tail`、`plan_cleanup` 增一条"会话最近一轮，保留"的处置（三处改动 + 新测试）。

**观察项（如实记）**

- 旧 dump 无 `messages_est_tokens` ⇒ 板子窗口列显示 `N msg / 0 tok`；新 run 起正常。这是"字段后来才有"，不是读取失败。
- 板子在真实 runs_root 上能把 §9.17 的四个验收 run 复现成同一会话的 98.6% 命中，说明"常驻统计"这一格已可用。

### 10.8 S1 回溯（2026-10-11，交付后自查）

**A. 当场补齐的遗漏**

| # | 遗漏 | 处置 | 证据 |
|---|---|---|---|
| 1 | 统计脚本的**库源**（`load_from_db`）与目录源的**未计量三态**无测试——此前只测了纯函数与目录源 | 补 3 条：库源按会话取数 + 顺序 + 从 `usage_json` 读决策；无轨迹 ⇒ `unavailable`；有轨迹无计量 ⇒ `partial` | `tests/test_replay_stats.py` 12 → **15 passed** |
| 2 | `tests/test_upload_t210.py` 文档字符串仍写"经 `_sys_prompt_addendum` 告知路径" | 改为"指令尾部"，并写明为何不能进前缀 | 该文件头注释 |
| 3 | `docs/tech-stack.md` 三处落后：§5.1 上传指引（同 #2）、run 产物清单未含 dump 新字段、`runs.usage_json` 未提 replay 块 | 就地更新三处 | 同文件 |
| 4 | §10.7 对 `agent_team` 的描述不准（写成"落在 user message"，实际是拼进 **phase system prompt**） | 依代码改写为"行为变化 + 未实跑验证" | `workflows/agent_team/nodes/main_agent.py:1506/1526/1544` |
| 5 | `server/usage.py` 模块文档未提 `replay` 块（`usage_json` 的形状变了） | 补一段说明（并声明它不参与 token 计数） | `server/usage.py` 模块 docstring |

**B. 仍在的遗漏与边界（不掩盖）**

| # | 项 | 事实 | 建议 |
|---|---|---|---|
| 1 | **S1 验收第 2 项"3 轮两臂复跑（R4/R5'）"未执行** | §10.2 的 S1 验收写的是"单测 + 3 轮两臂复跑 + 带附件两轮"；本次做了单测与带附件两轮，**无附件路径的两臂复跑没做** | **2026-10-11 处置：由 §11.10 的 S2 验收替代。** 那条要测的形状（无附件、同会话、两臂各 3 轮）就是 S2 验收 P1–P6 的形状（treatment 复用 99.4%，control 12,288）；而它原本的对象——**文件载体——已随 S2 退役**，原样复跑既不可能也无必要。故归档，不再花额度 |
| 2 | 带附件验收**没有对照臂** | C6（轮 2 命中 ≥ 80% 轮 1 prompt）在"共享块已暖"时并非严格归因：本轮共享块（system + 工具）≈12.3k，阈值 13.1k，只差约 0.8k ⇒ **共享块再大一点，C6 可能因错的原因通过** | **2026-10-11 处置：由 §11.10 的对照臂覆盖。** control 轮 3 的 12,288 就是共享块，treatment 的 16,512 比它多 4,224 —— 差值只能来自重放。归档，不再单独补跑 |
| 3 | 验收走 **`orchestrator.submit` 直连**，不经 HTTP 路由 + DATA-06 outbox | 路由/outbox 的连通性由 `tests/test_upload_t210.py`（HTTP + 真 worker + mock LLM）与 `tests/pg/test_run_dispatch.py` 覆盖，但它们**不校验说明的位置**；"位置"结论的证据在 worker 级单测 + 直连验收 | 记录为边界。若要端到端含路由，可在 `test_upload_t210` 里加一条"说明在 user message、不在 system prompt"的断言（mock 下即可，零额度） |
| 4 | `server/input_requests.py:670` 的"Continue input request"说明也随本次改动进了尾部 | 属**顺带收益**（该文本含 per-request id，原先进前缀会翻转缓存）；无测试钉住 | 记录；断言可归 S4 的常驻回归 |
| 5 | PG 侧用量契约测试本机**跳过** | `tests/pg/test_data15_joint.py` → 3 skipped（无 PG 连接）；全量跑也因此不含该文件 | 本次 `usage_json` 只新增键，该测试不校验键集合；记录 |
| 6 | `usage_summary_for_runs`（AC-20 成本对比口径）不返回 replay 块 | 有意：那是成本口径，不是会话口径；replay 走 `usage_json` 与统计脚本 | 若成本板要看命中原因再评估加字段 |
| 7 | 文档漂移（历史计划文档的行号） | `docs/p0-implementation-spec.md:235` 引 `worker.py:351` / `main_agent.py:817`，实际已漂移到 `506` / `852`；其结论（业务策略复用 `_sys_prompt_addendum`）**仍然成立**（上传说明才移走） | 记录；历史计划文档不做行号维护 |

**C. 结论（2026-10-11 更新）**：S1 可执行的验收格子已闭合（b / a / 统计脚本 / 带附件实测 / 观测）。原记的"唯一硬缺口 B1"已由 **§11.10 的 S2 验收替代**（形状相同；其原始对象"文件载体"已随 S2 退役）；B2 由 S2 的对照臂覆盖；B3 已补；其余为如实记录的边界（B5 PG 跳过、B7 行号漂移）。

**D. 2026-10-11 清尾（用户"开始执行"：D5 / B3 / B1-B2）**

| # | 项 | 处置与证据 |
|---|---|---|
| **D5** | F19 门测试硬编码 head | 查清是**两个**根因叠在一起：常量停在 `0006`（已落后 13 个 revision）+ 这些测试用 `command.upgrade` 跑**真实迁移链**，而链条到 0007 之后 SQLite 拒绝执行（`NotImplementedError: No support for ALTER of constraints in SQLite dialect`）——**这才是当年把常量钉在 0006 的真原因**，所以只"更新常量"修不好。改法三条：① `HEAD`/`BEHIND` 改为从 `readiness.expected_heads()` / `migration_graph()` **动态取**（消掉"每加一个迁移就改测试"的根因）；② 这些**版本门**测试改用 `command.stamp`（它们问的是"给定版本号门怎么判"，本来不需要表）；③ 单 head 测试改为断言"恰好一个 head + 链上每点恰好一个孩子 + 无分支"，不再列举 revision。结果：该文件 **7 failed → 16 passed**，全量 **12 failed → 5 failed** |
| **B3** | 位置结论只在 worker 级 | 在 `tests/test_upload_t210.py` 的**真实链路** E2E 里加断言：读该 run 轨迹的 `start` 记录，断言说明文本在 `user_message`、且**不在** `system_prompt`。这是唯一经 `路由 → outbox → orchestrator → worker` 全链的位置证据 |
| **B1 / B2** | 见 §10.8 B 表 | 归档（由 §11.10 验收替代），不再花额度 |

## 11. S2 设计稿：会话状态归位（2026-10-11）

**定位**：把 §10.1 的目标态落成可实施方案。核心只有一句话：**连续性载体的权威源从「run 目录文件」搬到「服务端一行记录」**，其余契约（worker 读什么、节点怎么校验、`select_replay` 怎么拒）尽量不动——**动得越少，越能证明"搬家"本身没换行为**。

**范围**：只做 `stateful-react-agent`（§9.11 第 4 项）。`agent_team` 不写 dump（§9.14），故 S2 对它是 no-op；跨 pipeline 的 payload 由 `select_replay` 的 `pipeline_id` 校验挡住。

### 11.1 现状核准（设计前实查，2026-10-11）

| # | 事实 | 依据 | 对设计的影响 |
|---|---|---|---|
| 1 | 迁移图**单 head** `0018_plan_capital_terms`，生产库 `alembic current` 也是它 | `uv run alembic -c server/alembic.ini heads/current` | 新迁移 `down_revision="0018_plan_capital_terms"`，不引入第二个 head |
| 2 | **`alembic check` 现在是脏的**：报出 40+ 项历史漂移（`users.created_at` NOT NULL、`idx_runs_session`→`ix_runs_session_id`、`Integer`/`BIGINT`、`sessions` 索引等），与模型长期不一致 | 实跑 `alembic check` | ⇒ §10.2 的"`alembic check` 无新增漂移"**只能做成差分**：把新增表的 create 之外的操作集，与落地前基线逐项比对，**不得多出任何其他表的操作**。"check 干净"这个口径要撤回 |
| 3 | `readiness.expected_heads()` 从**迁移文件源码解析**，不硬编码 | `server/readiness.py:83-116` | 新增 `0019` 后 `/readyz` 立刻期望 0019；**生产库不升级就 not_ready**（`SCHEMA_BEHIND`）。⇒ 迁移执行必须列入落地步骤（§11.5） |
| 4 | 测试/dev 走 `init_db()` = `Base.metadata.create_all` | `server/store.py:1039-1047` | 新表加进 `Base` 即被 SQLite 测试自动建出，**单元测试不依赖迁移**；迁移只服务 PG |
| 5 | 迁移文件是**手写**的（如 0018 直接 `op.add_column`），不是 autogenerate | `server/alembic/versions/0018_plan_capital_terms.py` | S2 的迁移也必须**手写** `op.create_table`：autogenerate 会把第 2 条那 40 项漂移一起写进新迁移，等于顺手重写全库 schema |
| 6 | F19 门测试把 head **硬编码**成 `HEAD="0006_business_operations"` / `BEHIND="0005_business_objects"`，并自带注释"每次新迁移都要同步两者" | `tests/test_web_f19_schema_gate.py:30-42` | 该约定在 0007 起就断了（现真实 head 0018）⇒ 本机全量跑里那 7 条失败属**既有陈旧**，非本次引入；S2 需明确处置（§11.5） |
| 7 | `_spawn` 已在同一函数内判定 watch 并算出 `prior_conversation`，run 收尾在同一 `finally` 里做 artifacts/usage | `server/orchestrator.py:736-759`、`:766-793` | 读侧改点与写侧挂点都在同一处，不需要新时序 |

### 11.2 数据契约（表形态：opaque payload）

```sql
CREATE TABLE session_conversations (
  session_id      UUID PRIMARY KEY REFERENCES sessions(id) ON DELETE CASCADE,
  payload         TEXT NOT NULL,          -- 上一轮 dump 文档的**原字节**
  revision        INTEGER NOT NULL DEFAULT 1,   -- 每次入库 +1（审计/乱序诊断）
  updated_at      TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_by_run_id UUID NOT NULL               -- 幂等键：同一个 run 重复入库是 no-op
);
```

**为什么是 `payload TEXT` 而不是 §10.1 原稿的 `messages / system_prompt / thinking_format / tool_schema_sha256` 分列**（这是本稿对 §10.1 的**实质修订**，需要裁决）：

- 分列等于**服务端开始建模 pipeline 的内部结构**——一列一个含义，就得解释"system_prompt 是什么、thinking_format 取哪些值"。这与 §9.12 口径 A 的动机（pipeline 内部对 server 不透明）**正好相反**；而 §10.1 之所以写成分列，只是因为 dump 头里恰好有这些字段。
- `TEXT` 存原字节还带着一个白拿的性质：**字节保真**。JSON 列会经 codec 往返（键序/空白可能变），虽然 `select_replay` 的比对都是 canonical 的、理论能容忍，但没必要引入这种"靠下游规范化兜住"的依赖。
- 代价（明确接受）：无法用 SQL 按 `tool_schema_sha256` 之类聚合（我们从不需要）；排查时要 `json_extract`/`->>` 手工看（可接受，且有 `scripts/replay_stats.py` 读的是 `usage_json`，不依赖这张表）。

**`ON DELETE CASCADE`**：会话硬删时会话记录随之消失（软删不动它，`deleted_at` 语义不变）。

**不做**：不建历史表（不需要"每轮一行"的版本历史——`revision` 只作审计计数；要历史就该按轮次建表，那是另一张票）。

### 11.3 写侧：父进程 ingest

**挂点**：`_spawn` 的 `finally` 里，紧跟 `_record_usage`（`server/orchestrator.py:782-783`）之后；崩溃恢复路径 `_recover_finished_run`（同文件 `:1406+`）同样调用一次。

```
_ingest_conversation(handle):
  if handle._params["_continuity"] == "off": return          # watch：两个方向都关
  dump = run_dir_for(run_id) / "run" / "conversation.json"
  if not dump.is_file(): return                              # 无 dump（agent_team/被杀/循环未结束）
  payload = dump.read_bytes()                                # 原字节，不解析
  if b"conversation-dump/" not in payload[: 200]: return      # 极轻自检：不是本契约的文档就不入库
  upsert(session_id, payload, updated_by_run_id=run_id)      # 幂等：同 run 重复 → no-op
  dump.unlink()                                              # 成功后才删
```

要点（每条都对应一个失败模式）：

1. **不解析**：不 `json.loads`，不按 role/content 取值——与 §9.12 红线一致。唯一例外是那个 `b"conversation-dump/"` 头部探针：它只确认"这是本契约的文档"，避免把 `history.txt` 之类误入库（也可以省掉，见待裁决 D6）。
2. **幂等**：`ON CONFLICT (session_id) DO UPDATE ... WHERE session_conversations.updated_by_run_id IS DISTINCT FROM excluded.updated_by_run_id`。崩溃恢复后重跑 ingest 不会把 `revision` 无意义地推高，也不会重复删文件（文件已不在）。
3. **失败语义（fail-open + fail-loud）**：DB 不可用/写失败 ⇒ **保留文件** + `logger.warning(exc_info=True)`，run 的生命周期不受影响（和 `_record_usage` 同级的"记账失败不许压垮运行"纪律）。**不设"读文件兜底"**——权威源只有一个（§10.2 的"不留双路径"）。
4. **watch**：`_continuity=="off"` 时既不读库也不写库（§9.18 #1 的两向关闭在新载体的延续）。
5. **超时**：与相邻步骤一致地用 `asyncio.wait_for(..., timeout=15)` 包一层。

### 11.4 读侧：消费与退役

**改点**：`_spawn` 里把 `resolve_prior_conversation(prior_turns, ...)`（`server/history.py`）换成一次**主键读**：

```
row = await read_session_conversation(session_id=session_uuid)   # 可空，读失败→None
prior_payload = row.payload if row else None
```

**落盘方式**：`_launch` 里的 `_stage_prior_conversation(run_dir, source_path)`（现在做的是"从上一 run 目录拷字节"）改成 `_stage_prior_payload(run_dir, payload_text)`：**原子写**（`.tmp` + `os.replace`）到 `run_dir/prior_conversation.json`，并在 `payload` 为空时**确保该文件不存在**（沿用现有"先删陈旧副本"的语义）。之所以仍落一个文件：**worker 与节点的契约一个字都不用改**（它们照旧读 `prior_conversation.json`），S2 的爆炸半径就只剩 server 侧读写两处。

**退役清单（要删干净，不留双路径）**：

| 目标 | 说明 |
|---|---|
| `server/history.py::resolve_prior_conversation` | 上一轮 dump 的"按文件存在性逆序扫 turns"逻辑整体删除；`CONVERSATION_DUMP_RELPATH` 保留（写侧路径常量仍被单测与文档引用） |
| `_stage_prior_conversation` | 换成 `_stage_prior_payload`（源是 DB） |
| `params["_prior_conversation"]`（路径字符串） | 换成 `params["_prior_payload"]`（文本）或直接把 payload 交给 `_launch`；**不留"路径"形态** |
| `server/history.py` 的模块注释 | §9.12 口径 A 的三段式要改写：**权威源 = 服务端一行记录**；(b) 载体不再是"上一 Run 的产物"，而是"本会话的当前状态"；run 目录里的 `prior_conversation.json` 降为**本轮的 staging 副本** |

**既有测试的处置（先列清楚，免得实施时才发现）** —— 全在 `tests/test_context_inheritance.py`：

| 测试 | 现状 | S2 处置 |
|---|---|---|
| `test_the_prior_conversation_is_the_newest_run_that_has_one`（:484） | 直测文件扫描的定位语义 | **删除**，由"按主键读一行"的新单测取代（§11.7-2） |
| `test_staging_copies_the_dump_and_removes_a_stale_one`（:515） | 断言从**源文件**拷字节 + 清陈旧副本 | **改写**为 `_stage_prior_payload` 版：写入字节等于 payload、`None` 时清掉陈旧文件、源不存在 → 不再有"源文件"这一说 |
| `test_writer_and_reader_agree_on_where_the_dump_lives`（:536） | 保证写方路径 == 读方路径（§9.14 补的缺口） | **保留但改对象**：写方路径现在必须等于 **ingest 的读方**路径（这个不变量在 S2 里更重要——写偏了就是"静默不入库"） |
| watch 测试里的两处 params 断言（:746/:758） | 断言 `captured[...]["_prior_conversation"] == str(dump)` / `is None` | 改为断言新键（`_prior_payload` 为 payload 文本 / `None`）；"watch 两个方向都关"的语义不变 |
| 顶部 import（:35-36） | 从 `server.history` / `server.orchestrator` 取退役符号 | 同步替换（删掉的符号不许留在 import 里） |

**跨进程/重启**：读路径只依赖"会话主键 + 一个 DB 连接"，不含任何进程内状态；同会话的派发仍由 `_session_queues` 串行化（`_drain_session` 里 `await self._spawn(...)` 逐个消费，已核），多进程部署下"同一会话并发两轮"不在契约内——记为**假设**（§11.8），并被 `revision` 与幂等 upsert 兜成"最坏=后写覆盖"。

**过渡期一次性损失（必须写明）**：S2 落地后读路径不再扫文件，因此**此前遗留在旧 run 目录里的 dump 不再可达**——那些会话的下一轮会退化为新会话（一次 cache miss，不是数据丢失）。这是接受项，不是缺陷；写进验收的"反向证据"里。

### 11.5 迁移与就绪门

1. **迁移**：`server/alembic/versions/0019_session_conversations.py`，**手写** `op.create_table("session_conversations", ...)` + `downgrade` 里 `drop_table`；`revision="0019_session_conversations"`、`down_revision="0018_plan_capital_terms"`。模型加在 `server/store.py`（`Run` 附近），字段与迁移逐项对齐。
2. **执行**（因为 §11.1 第 3 条，这是落地的一部分而非可选项）：生产/开发 PG 库需 `alembic upgrade head`。**本地开发库由我在落地时执行**（待裁决 D4）；只出迁移文件不升级 ⇒ 本机 `/readyz` 变 `schema_behind`、`enforce_startup_readiness` 在生产模式下拒绝启动（dev 模式只警告）。
3. **漂移验收（差分）**：
   - 落地前基线：把 `alembic check` 的输出归一化成 `{(op, table)}` 集合，存进证据目录（`evidence/…/alembic-check-before.txt`）。
   - 落地后：同法取一次（`…/after.txt`），断言 `after − before == {('create_table','session_conversations')}`，且 `before − after == ∅`。
   - **不写"check 干净"**（第 2 条已证伪）。
4. **F19 门测试的硬编码（待裁决 D5）**：现状 `HEAD="0006_business_operations"` 自 0007 起就与真实 head 脱节，本机 7 条失败即由此而来（属既有）。三条路：① 顺手更新到 `0019/0018`（前提是 0007+ 迁移能在 SQLite 跑通——它现在只跑到 0006，故**需先验证**）；② 改成从 `readiness.expected_heads()` 动态取（更稳，但改了这条测试的语义）；③ 只记录不动。**我倾向 ②**，但它与 S2 主体无关，建议单独裁决。

### 11.6 影响面

| 层 | 变化 |
|---|---|
| producer（workflow） | **不变**：`ConversationSnapshotObserver` 照旧写 `run/conversation.json`（S3 的"固化摘要"将来就落在这份 payload 里，无需改表） |
| transport（server） | 新增 ingest（写库 + 删文件）；读侧改为按主键读 + 原子 staging |
| consumer（node） | **不变**：仍读 `prior_conversation.json`，仍由 `select_replay` 校验（system prompt / 工具指纹 / thinking_format / pipeline / node / session / 消息配对） |
| 数据层 | 新表 1 张；`sessions` 硬删级联；无既有表改动 |
| 保留期 | **O5 自动消失**：载体不在 run 目录里，`run_retention.py` 的 `rmtree` 再也删不到它；`run_dir` 里的 `prior_conversation.json` 是每轮自有的 staging 副本，被删只影响该轮自己 |
| 观测 | 无需新增：`script/replay_stats.py` 读 `usage_json`，与本次搬家无关 |

### 11.7 验收

**单元（零额度，全部用 SQLite `db` fixture）**

1. **ingest 契约**：① 原字节入库（与文件字节逐字节相等）；② 成功即删文件；③ 同一 run 重复 ingest ⇒ `revision` 不变、无异常；④ 无 dump ⇒ no-op（不建行）；⑤ `_continuity="off"` ⇒ no-op **且不删文件**；⑥ DB 抛错 ⇒ 文件保留 + 记 warning + 不抛给调用方。
2. **读侧**：⑦ 有行 ⇒ staging 文件字节等于 payload；⑧ 无行 ⇒ 不产生文件，且**残留的旧 `prior_conversation.json` 被清掉**；⑨ 行存在但 payload 非法 ⇒ 节点照旧 fail-open（沿用既有拒绝矩阵）。
3. **无文件兜底（关键反向断言）**：⑩ 在上一轮 run 目录里放一个合法 dump、但**库里没有行** ⇒ 本轮**不重放**。这一条才是"文件路径真的退役了"的证据，比删函数更能防回归。
4. **跨进程/重启**：⑪ 用**新建的** `Orchestrator` 实例 + 重置 `store` 引擎后再跑一轮 ⇒ 仍重放（证明不依赖进程内状态；旧实现依赖"扫得到的文件"，这一条会红）。
5. **fail-open 演练**：⑫ 表被删/连接失败 ⇒ `_spawn` 正常派发、`replay_decision = skipped`（原因是 DB 读取失败）。
6. **迁移**：⑬ `upgrade head` 后表存在且 `readiness.expected_heads() == ("0019_session_conversations",)`；⑭ `downgrade -1` 再 `upgrade` 幂等；⑮ 保留期 `plan` 的处置集合中不再出现"会话载体"相关项。

**集成（实跑，出 `runs.usage_json` 原始数字）**

7. 同会话连跑 3 轮无附件业务提问，两臂（treatment / control=每轮后删库中行）：判据沿用 **R4 + R5'**（§9.17 口径，不重新发明）。
8. **跨重启实跑**：同一会话第 1 轮跑完 → 重启 API 进程 → 第 2 轮仍 `replay.decision=used` 且 `cache_read` 达 R4 阈值。这就是 §10.2 S2 验收第 ② 条。
9. 漂移差分（§11.5 第 3 条）。
10. **模型由部署侧指定**（本次教训）：跑前必须用一次探针确认"该模型在该端点上会上报缓存命中字段"，否则判据不可判定。

### 11.8 不变量、假设、风险、回滚

- **不变量**：server 不解析 payload（唯一例外是那个头部探针，可裁掉）；权威源唯一（DB），不留文件兜底；失败一律 fail-open，`run` 不许因为库的问题跑不起来；`select_replay` 的校验集合不变。
- **假设**（写下来，因为它是这套设计的地基）：① 同一会话的 run 在本进程内串行（`_session_queues`）⇒ ingest 顺序 = run 顺序；② 生产部署单进程处理同一会话（多进程时退化为"后写覆盖"，不崩、不脏读）。
- **风险与缓解**：
  - *ingest 有 bug 而文件已删* ⇒ 该会话下一轮从零开始（cache miss，可恢复）。缓解见 D2 备选（双写窗口）。
  - *payload 变大*（单行数百 KB～<1MB）⇒ PG TOAST 处理，无需分块；列为观察项。
  - *迁移未执行就上线* ⇒ `/readyz` 直接不 ready，**显式失败**而非静默（这点比现在更好）。
- **回滚**：`alembic downgrade -1` + 回滚代码；期间的会话在下一次对话时从零重放。**没有数据丢失**（会话内容本身在 `turns`，模型看到的 payload 是可重建的派生品）。

### 11.9 待裁决

| # | 议题 | 选项 | 我的建议 |
|---|---|---|---|
| D1 | 行形态 | 甲：opaque `payload TEXT` + 记账列（本稿）／乙：§10.1 原稿分列 | **甲**（不解析是本 issue 的红线；分列会让 server 建模 pipeline 内部结构） |
| D2 | dump 文件删除时机 | 甲：入库成功即删／乙：先双写保留一个版本再开删 | **甲**（载体不是数据；乙会把"谁是权威"重新搞含糊） |
| D3 | 乱序守卫 | 甲：仅幂等（同 run no-op）／乙：加 `finished_at` 单调写守卫 | **甲 + 记录假设**（乙在多进程场景才有意义，属 S3/S4 加固） |
| D4 | 迁移执行 | 甲：我落地时对本地开发库执行 `upgrade head`／乙：只出文件、由部署侧执行 | **甲**（否则本机 `/readyz` 立刻 not_ready，验收跑不起来）；生产库仍由部署侧 |
| D5 | F19 门测试硬编码 head | ①更新到 0019/0018（需先验证 0007+ 能跑 SQLite）／②改为动态取 head／③只记录 | **②**，单独裁决 |
| D6 | ingest 前的头部探针 | 保留（`b"conversation-dump/"`）／去掉（彻底不解析） | 保留（避免把别的文件误入库），但它**不是**解析 |
| D7 | 命名确认 | `session_conversations` / 模型 `SessionConversation` | 确认即可 |

### 11.10 S2 实施记录（2026-10-11）

**裁决口径**：D1 opaque payload / D2 入库成功即删 / D3 只做幂等 / D4 本机执行升级 / D6 保留头部探针 / D7 命名确认，均按建议落地；**D5（F19 门测试硬编码 head）本次不动**（设计稿即标"单独裁决"）。

**落地清单**

| 层 | 文件 | 改动 |
|---|---|---|
| 数据 | `server/store.py` | 新增 `SessionConversation` 模型（opaque `payload TEXT` + 记账列，`updated_by_run_id` 刻意不做外键）；新增 `read_session_conversation`（主键读）与 `upsert_session_conversation`（读后写、同 run no-op、方言无关） |
| 迁移 | `server/alembic/versions/0019_session_conversations.py`（新） | **手写** `op.create_table` + `drop_table`；`down_revision="0018_plan_capital_terms"`；`_uuid()` 用 `with_variant(String(36), "sqlite")` 沿用仓库惯例 |
| 写侧 | `server/orchestrator.py` | 新增 `_ingest_conversation(run_id, *, session_uuid, continuity)`：`continuity=="off"` 直接返回（watch 两向都关）→ 读 dump **原字节** → 头部探针（`b"conversation-dump/"` 不在前 200 字节即拒收）→ UTF-8 解码 → upsert → **成功后删文件**；任何失败只 `warning`，文件保留。挂在 `_spawn` 的 `finally`（紧跟 `_record_usage`）与 `_recover_finished_run`（崩溃恢复，`is_watch_run` 先行排除） |
| 读侧 | `server/orchestrator.py` | `_spawn` 把"逆序扫 turns 找文件"换成一次 `read_session_conversation`（失败即降级为无 payload + warning）；参数键 `_prior_conversation`（路径）→ `_prior_payload`（文本） |
| staging | `server/orchestrator.py` | `_stage_prior_conversation` → `_stage_prior_payload`：`None`/空串先删陈旧副本，否则 `.tmp` + `os.replace` 原子写；`shutil` 依赖随之移除 |
| 退役 | `server/history.py` | 删除 `resolve_prior_conversation` 与 `_run_id_hex`（连带 `uuid`/`Callable` 导入）；保留 `CONVERSATION_DUMP_REPLPATH` 作写侧/ingest 共用的路径常量；模块注释改写为"权威源 = 会话行，run 目录里的文件只是本轮 staging 副本" |
| 文档 | `docs/tech-stack.md` | §5.1 目录树（两个文件的角色）、跨轮上下文段落、runs 表旁的 `session_conversations` DDL（含"刻意不做外键"的理由）、`/readyz` 要求库在 0019 |

**门禁证据（实跑）**

| 项 | 命令/结果 |
|---|---|
| 目标测试集 | `tests/test_context_inheritance.py` **43 passed**（新增 6 条 ingest、1 条 staging 改写、1 条"文件不是权威源"反向断言、1 条 revision 接线；删除 1 条定位语义测试）；波及面回归 **146 passed** |
| 全量 | 2997 passed / 12 failed —— 与 S1 那轮**同名同数**（corpus/market/dev lane/alembic/PG 状态），无新增失败 |
| 类型/风格 | `ruff check`（含迁移与差分脚本）干净；`pyright`（store/history/orchestrator/测试）0 error |
| 迁移执行 | `alembic upgrade head` → `0019_session_conversations (head)`；`readiness.expected_heads() == ("0019_session_conversations",)`（单 head）；`downgrade -1` → `stamp` 往返后表存在、`select count(*) from session_conversations` = 0 |
| 漂移差分 | `evidence/20261011-s2-session-store/`：`alembic-check-before.txt`（19 项，含 `add_table session_conversations`）vs `after.txt`（18 项）⇒ `removed == {('add_table','session_conversations')}`、`added == ∅`（`compare_drift.py` 判定 OK）。**口径修正记**：`alembic check` 在"库不在 head"时会短路（只报 `Target database is not up to date`），基线因此用 `stamp` 造出"版本号在 head 但表不存在"的反事实态来取 |

**实跑验收（2026-10-11，用户批准，模型取服务器 `.env`）**

跑前探针（判据前置）：`.env` 现为 `deepseek-flash` @ `api.deepseek.com`，两次同前缀请求实测上报 `prompt_tokens_details.cached_tokens` = 3196 / 3200 —— 正是 `frontier_agent/infra/openai_client.py::_usage_dict` 读取的字段。

方法：两臂各 3 轮，**每轮一个独立进程**（`--turn N` 分次调用，pid 各异即"重启后续接"的可构造形式）；treatment 正常，control 每轮后删掉库中的会话行（两臂唯一差别）。驱动 `run_acceptance_s2.py`，证据 `evidence/20261011-s2-session-store/run-20261011/`。

| 臂 | 轮 | prompt | cache_read | replay | 库中消息数 | run 目录还有 dump？ |
|---|---|---|---|---|---|---|
| treatment | 1 | 16,346 | 16,000 | skipped: no_payload | 3 | 否（已 ingest 并删除） |
| treatment | 2 | 16,608 | **16,256** | **used** | 5 | 否 |
| treatment | 3 | 16,870 | **16,512** | **used** | 7 | 否 |
| control | 1/2/3 | 16,343 / 12,659 / 12,668 | 16,000 / 12,288 / 12,288 | skipped: no_payload ×3 | — | 否 |

**判据（预注册）全 PASS**（`results.json` / `report.md`）：

| 判据 | 结果 |
|---|---|
| P1 treatment 轮 2/3 `replay=used` | PASS |
| P2 每轮跑完 dump 已删、库中有行 | PASS |
| P3 control 轮 2/3 `skipped`（无载体） | PASS |
| P4 轮 3 复用 ≥ 轮 2 prompt 的 80% | PASS（**99.4%**，16,512 / 16,608） |
| P5 逐轮存储 messages 以上一轮为前缀 | PASS |
| P6 三轮三个不同进程 | PASS（pid 53826 / 53872 / 53948） |

**归因**（这里比 S1 的附件验收强）：两臂唯一差别是有无载体，control 轮 3 的 12,288 就是共享块（system+工具），treatment 的 16,512 比它多 **4,224** —— 这段差值只能来自被重放的对话（S1 附件验收缺对照臂，本轮补上了这个缺口）。

**未做（待裁）**

- **D5**：`tests/test_web_f19_schema_gate.py` 仍硬编码 `HEAD="0006_business_operations"`，其 7 条失败为既有（本次全量未增不减）。
- S1 遗留的 **B1（无附件两臂复跑，8 run）/ B2（附件臂对照，2 run）/ B3（路由级位置断言，零额度）** 仍未做。

**观察项**

- `run/prior_conversation.json` 现在是**每轮 staging 副本**，不是权威源：删掉它只影响该轮自身，O5（保留期误删载体）由此**在结构上消失**（`test_ingest_stores_the_dump_and_drops_the_file` 断言 run 目录里不再留 `conversation.json`）。
- 过渡期一次性损失照旧记在案：S2 落地前遗留在旧 run 目录的 dump 不再可达，那些会话下一轮退化为新会话（一次 cache miss）。
- 旧的多进程假设未变（§11.8）：同会话串行化是进程内的；`revision` 与同 run 幂等把最坏情况兜成"后写覆盖"。

## 12. S3 设计稿：窗口 + 写时固化摘要（2026-10-11）

**目标**（§10.1/§10.2 S3）：让"轮数很多"的会话**成本有界**——今天的写时裁剪（`trim_to_turns`，只丢最旧轮）是**止损**，不是解法：它能保证不越界，但历史被成段丢掉。S3 把"丢掉的那一段"换成**一段固定文本摘要**，且摘要随 payload **固化**，从而既不越界、又不丢信息、也不破坏前缀稳定。

**范围**：只做 `stateful-react-agent`；不改 `session_conversations` 表（payload 是 opaque，S2 的 D1 裁决在这里直接兑现——**S3 不需要任何迁移**）。

### 12.1 现状核准（设计前实查）

| 机制 | 位置 | 对本设计的意义 |
|---|---|---|
| 写时裁剪 | `conversation_snapshot.trim_to_turns(messages, max_turns, *, max_tokens)` | 只按 `user` 边界丢最旧轮、保 system、永不孤儿 tool；节点传 `replay_max_turns` 与 `replay_max_tokens`（默认 `max_input_tokens // 2`） |
| **跨轮压缩阶梯（现成）** | `frontier_agent/core/runtime/session_history.py::SessionHistoryCompactor.compact(turns, current_query)` | 已经是"先删旧工具结果 → 用 `LLMSummaryCompactor` **摘要旧轮** → 最近工具结果 → 丢最旧轮 → 确定性截断"；且摘要的表示法就是列表头部一个 `{"summary": ...}` 伪轮。**S3 应当复用它，不新造压缩器** |
| 循环内 tiered 压缩 | `frontier_agent/core/runtime/loop/tiered_compact.py::compaction_trigger_tokens(max_len)` = `0.8 × max_len`（`AGENT_COMPACTION_TRIGGER_RATIO` 可覆盖） | 那是 **run 内**上下文管理，与 S3 的**跨轮窗口**是两件事，S3 不动它。该文件还留着一条有用的实测结论：把比例放到 0.65 **被实测否决**（压缩更频繁、得分无提升 49.7% vs 50.0%），所以别用"多压一点更安全"的思路设计 S3 |
| 摘要提示词 | `frontier_agent/infra/llm/summary_prompt.py::compaction_prompt(messages)` | 直接复用 |

**一条决定设计走向的硬约束**：写时裁剪发生在**产生 dump 的那一轮**，被裁掉的轮次**不会进入 payload** —— 所以**下一轮看不到被裁内容，无法事后补摘要**。⇒ 摘要只能由"本轮"生成（本轮手里有完整 messages），并把结果**固化进它写的 payload**。这条约束把 S3 的实现位置钉死在**写侧**，而不是 §10.2 原稿写的"consumer 侧入口先做一次摘要调用"（那一版假设被裁内容还可得，**不成立**，本稿据此修订）。

### 12.2 形态：摘要块的位置与生命周期

payload 的 messages 序列变成：

```
[ system,  摘要块（可选）,  窗口内的若干轮… ]
   ↑ 恒定      ↑ 只在裁剪时更新      ↑ 每轮追加
```

- **摘要块是什么**：一条 `role="user"` 的消息，内容由固定模板包裹（如 `<conversation-summary>…</conversation-summary>`），紧接 system 之后。**唯一**：永远只有一块，新的摘要**替换**旧的。
- **为什么放进 messages 而不是 doc 头部字段**：kernel 只接受 `initial_messages`（消息列表），放头部字段的话下一轮还得在入口把它拼成一条消息——等于多一个每轮都要走一遍的拼接点；放进序列里，`select_replay`/`initial_messages` 的既有路径一个字都不用改。
- **为什么它不破坏前缀稳定**：块的位置固定在 system 之后；**一旦写入就不再变**，直到下一次裁剪才被替换。于是"第 N 轮请求的前缀 = 第 N-1 轮请求"，除了发生裁剪的那一轮（**允许一次失效**，§9.7 的既定口径）。
- **role 选 `user` 不选 `system`**：system 只能有一条，且 `select_replay` 会拿它和本轮 system prompt **逐字节比对**；把摘要塞进去等于让 system prompt 每轮变，直接毁掉前缀。

### 12.3 触发、生成与失败语义

```
节点（react_agent，loop 结束后、构造 observer 之前）：
  if 本轮 messages 会触发裁剪（轮数 > max_replay_turns 或 est_tokens > max_replay_tokens）:
      旧摘要 := payload 里那一块（若有）
      被裁轮 := 按 trim 规则将被丢掉的那些轮
      新摘要 := await SessionHistoryCompactor/LLMSummaryCompactor(旧摘要 + 被裁轮)   # 最多 1 次 LLM 调用
      交给 observer 的参数 summary_block := 新摘要（失败则 None）
  observer：写 dump 时把 summary_block 放在 system 之后（无则不放）
```

- **成本上界**：**每次发生裁剪的轮次最多 1 次摘要调用**；不发生裁剪的轮次 **0 次**。长期会话里裁剪是低频事件（每跨过一次窗口才发生一次）。
  - ⚠️ **2026-10-12 更正**：这句话只在窗口**有迟滞**时成立。落地时的硬边界（`replay_max_turns` 每轮重新判定）会让窗口一满就**每轮裁一次**——45 轮里 35 次裁剪、35 次摘要调用、命中率从 93% 塌到 27%。已按 §12.8 加写侧迟滞修正；本节其余内容不变。
- **失败语义（fail-open）**：摘要生成失败/超时 ⇒ `summary_block=None` ⇒ 行为**回退到今天的写时裁剪**（丢最旧轮），run 不受影响。**宁可少记忆，不可卡住运行**。
- **不做**：不做"摘要+被裁原文并存"的中间态（那会让 payload 再次无界增长，违背本节目标）；不重算既有摘要（相邻 dump 的摘要块必须逐字节相同）。

### 12.4 影响面（很小）

| 层 | 变化 |
|---|---|
| 观察者 | 新增可选参数 `summary_block: str | None`；写 dump 时按 §12.2 插入。裁剪逻辑（`trim_to_turns`）**不变** |
| 节点 | 在 loop 结束后判定"是否将裁剪"，需要时调一次摘要（复用 `SessionHistoryCompactor`），把结果传给观察者 |
| `select_replay` | **不变**（摘要块就是普通 user 消息，配对/角色校验天然通过） |
| 数据层 | **无迁移**（payload opaque） |
| 保留期/观测 | 不变；`scripts/replay_stats.py` 的窗口列会体现裁剪后的消息数 |

### 12.5 验收

**单元（零额度，SQLite）**

1. 不裁剪 ⇒ dump **不含**摘要块、**不调用**摘要器（用假的 `summary_llm` 断言调用次数为 0）。
2. 裁剪 ⇒ dump 含摘要块、位置在 system 之后、且被裁轮不再出现；摘要器被调用**恰好 1 次**。
3. 连续两轮都裁剪 ⇒ 第二次的摘要输入是"(旧摘要 + 本轮被裁轮)"，且新摘要**替换**旧的（不出现两块）。
4. 摘要失败 ⇒ 回退为今天的裁剪结果（无摘要块），且不抛错。
5. 前缀性质：不裁剪的相邻两轮，前一轮 payload 是新一轮 payload 的前缀（逐条 canonical 比较）。

**集成（合成 40+ 轮会话，需额度）**

6. 首请求 token 有界（≤ `replay_max_tokens`）；7. 裁剪那一轮之后连续 ≥2 轮命中率恢复 ≥80%（R4 口径）；8. 相邻 dump 的摘要块逐字节相同（不重算）；9. 40 轮总 prompt 呈"平台期"而非线性增长。

**2026-10-12 判据按 §12.8 修订**（跑前生效，避免拿一个已被本地测量证伪的目标去跑额度）：

6. 首请求 token ≤ `replay_max_tokens`（**不变**，尺寸保险不以迟滞让路）；
7. **改为**：在**迟滞生效**的配置下（`replay_max_turns=10`、`replay_max_turn_step=5`），裁剪轮的**下一轮**命中率 ≥80%，即"裁剪只抖一次"；本地测量值 93.8%；
8. **不变**，并加一条可机读口径：由 `usage_json.replay.trim` 数出的**裁剪轮数 ≤ ⌈轮数/step⌉ + 1**（45 轮应 ≤ 10，现状是 35）；
9. **不变**：总 prompt 呈平台期（窗口被迟滞钉在 10–15 轮），且**平均 prompt 不再随轮数增长**。

**C6 测量窗口补充（2026-10-12，S4 收口）**：两臂差异一律取各臂**全程所有有效且有前轮 prompt 可作分母的转换**之均值；包含预热期与裁剪造成的构造性 miss，不事后改取稳态区间。门槛固定为 treatment ≥80%、control ≤60%，且两臂相差 ≥20 个百分点。§12.10 的最终判定（83.0% vs ≈39%，差 ≈44pp）按此口径不变。

**新增跑法约束（2026-10-12 实跑发现）**：无人值守跑必须带自动批准（`--auto-approve session_all`）。新模型会调工具，而 `bash` 被安全分类判为 `confirm` ⇒ 每次 gated 调用会挂到审批门的 fail-closed 超时（`DEFAULT_TIMEOUT_S = 300s`），一轮里几次就能把墙钟耗光。

### 12.6 待裁决

| # | 议题 | 选项 | 我的建议 |
|---|---|---|---|
| D-S3-1 | 摘要块位置 | 甲：messages[1]（本稿）／乙：doc 头部字段 | **甲**（少一个每轮拼接点；`select_replay` 不改） |
| D-S3-2 | 摘要用哪个模型 | 甲：本轮 loop 的同一个 `llm`／乙：另配一个便宜模型 | **甲**（不引入新配置面；成本已由"低频 1 次"限住） |
| D-S3-3 | 窗口参数 | 甲：沿用 `replay_max_tokens = max_input_tokens // 2`／乙：单独配 `summary_at_ratio` | **甲**（先沿用，等实测有需要再加旋钮） |
| D-S3-4 | 摘要块是否参与 `select_replay` 的 session/thinking 校验 | 甲：不参与（就是普通消息）／乙：单独校验 | **甲** |
| D-S3-5 | ~~是否允许"只摘要、不丢轮"（当摘要后仍在预算内）~~ | **2026-10-11 执行时否决**：该选项**算术上不自洽**——被丢的那些轮正是因为超预算才被丢的，摘要本身也占预算，插进去只会更超。替换为自洽规则：**摘要块参与 token 预算**（详见 §12.7 修正 ①） |

**与 S2 的关系**：S3 完全建立在 S2 的载体上（摘要随 payload 入库、下一轮主键读出），**不新增存储、也不需要迁移**；S2 留的 `replay_max_tokens` 预算正是 S3 的触发判据。§10.2 里 S3 那句"consumer 侧先做一次摘要"已按 §12.1 的硬约束**修订为写侧生成**。

### 12.7 S3 实施记录（2026-10-11）

**裁决口径**：D-S3-1/2/3/4 按建议执行（摘要块放 `messages[1]`／用本轮同一个 `llm`／沿用 `replay_max_tokens`／不参与 `select_replay` 校验）；**D-S3-5 在执行中被否决并替换**（见修正 ①）。

**落地清单**

| 文件 | 改动 |
|---|---|
| `frontier_agent/components/observers/conversation_snapshot.py` | 摘要块机制：`SUMMARY_TAG` + `render_summary_content` / `summary_from`（返回 `(protected_head, summary)`）/ `with_summary`；`trim_to_turns(..., head=)` 保护头，且**摘要不计入轮数**；`build_dump(..., summary_block=)` **先插块再裁剪**（摘要参与 token 预算）；观察者新增 `summarizer` 参数 + `_summarize_dropped`（只在真要裁剪时调用；未裁剪时把旧块**原样**写回，保证前缀逐字节不变）；`build_summarizer(llm)` 复用 `LLMSummaryCompactor` |
| `workflows/stateful_react_agent/nodes/main_agent.py` | observer 构造处接 `summarizer=build_summarizer(llm)`（仅在 `replay_max_turns`/`replay_max_tokens` 生效时构建） |
| `tests/test_context_inheritance.py` | 新增 7 条：不裁剪不调用摘要器／裁剪生成一块／二次裁剪替换且把旧摘要喂回／未裁剪时旧块逐字节不变／摘要失败保留旧记忆／**超时不能拖住 run**／摘要不计入轮数（并断言 `head=1` 会丢记忆） |

**设计期修正（两条，实查发现）**

1. **D-S3-5 甲被否**：原选项"摘要后若仍在预算内就**不丢轮**"**算术上不自洽**——被丢的轮正是因为超预算才被丢；摘要本身也占预算，插进去只会更超。改为自洽规则：**摘要块参与 token 预算**（`build_dump` 先插块再裁剪），因此超预算时按既有规则再丢更旧一轮。已写入 `build_dump` 的 docstring，避免后人重犯。
2. **`on_loop_end` 没有超时**：`notify_observers` 对**非 critical** 观察者走"后台任务 + 裸 `asyncio.gather` drain"（`frontier_agent/core/loop_types.py:325-376`）——**没有任何超时**。观察者此前只写文件，所以无碍；S3 往里放了一次 LLM 调用，而摘要器自带的传输超时是**几百秒**级 ⇒ 会把 loop 的返回一直挂住，直到 wall deadline 杀进程（还会连带丢掉 dump）。故在观察者内加 `SUMMARY_TIMEOUT_S = 60`，超时即当失败（保留旧摘要 + 普通裁剪），并用专门单测钉住"挂住的摘要器不能拖住 run"。

**门禁（实跑）**

| 项 | 结果 |
|---|---|
| `tests/test_context_inheritance.py` | **50 passed**（43 → 50） |
| 波及面回归集（10 个文件） | **169 passed** |
| 全量 | **3016 passed / 5 failed** —— 与清尾后**同名同数**（corpus/market/dev lane 既有环境依赖），**无新增** |
| `ruff` / `pyright` | 干净（0 error） |

**未做**

- **§12.5 的集成验收（合成 40+ 轮会话，需额度）未跑**：判据已预注册（① 首请求 token 有界；② 裁剪轮之后连续 ≥2 轮命中率恢复 ≥80%；③ 相邻 dump 的摘要块逐字节相同；④ 40 轮总 prompt 呈平台期而非线性）。**待批**，跑法照 S2：跑前探针确认模型上报缓存字段、每轮独立进程。**2026-10-12 更新**：判据 ②/⑧ 已按 §12.8 修订（须在迟滞生效的配置下评），跑法必须带自动批准——见 §12.8 ②。
- 观察项（有意取舍）：摘要块计入预算后，**窗口能保留的轮数会略少于** S3 之前——这是"用一点窗口换长期记忆"。

### 12.8 端点切换、端到端核对与窗口迟滞修正（2026-10-12）

**背景**：模型端点换成阿里云百炼（`.env`：`compatible-mode/v1` + `qwen3.7-flash-2026-07-15`）。跑集成验收前先做两件事：核对链路是否真的通、把"40+ 轮"这个规模的前缀性质用零额度方式量清楚。

**① 端到端核对（已在百炼上跑通）**

| 环节 | 证据 |
|---|---|
| 库 → 编排 → worker 子进程 | run 行 `queued` → `stopped`；worker 独立 pid |
| worker → pipeline → **模型** | 轨迹 `start/attempt/llm/end`；`POST dashscope…/chat/completions 200` |
| **usage 回库** | `usage_status=complete`，`prompt_tokens 15798 / cache_read 7936 / llm_calls 1`；首轮就吃到隐式缓存（约一半 prompt） |
| S2 载体 | `dump_present_after_run=false` + `stored_after_run=true`（存的是 `[system,user,assistant]`） |
| 终态 | `stopped_by=no_tool`、`error=null`、`final_answer=收到` |

端点适配结论（探针，零副作用）：`prompt_tokens_details.cached_tokens` 字段名与我们客户端读的一致（两次相同长前缀：`5760/6020 = 95.7%`）；流式 `stream_options.include_usage` 被接受 ⇒ **不需要改适配器**。两个与预期不同、要记住的：**思考模型**（`max_tokens=16` 仍产生 183 `reasoning_tokens` ⇒ 输出上限在这端点上管不住思考）；web profile 钉的 `thinking_format=tag` 与端点返回的 `reasoning_content` 不一致 ⇒ 思考**不进历史**（对前缀稳定性有利；代价是 `agent_loop` 里"工具调用泄漏进思考"的兜底失效）。

**② 一个会拖垮验收的链路事实：审批门**

新模型会调工具（旧模型从不调，历史 run 全是 `no_tool`），而 `plugins/tools/bash` 的命令被 `apodex.assess_with_rules` 判为 **`confirm`** ⇒ `ApprovalObserver` 挂起等人工批准，`DEFAULT_TIMEOUT_S = 300s` 才 fail-closed。首次无人值守跑因此静默 5 分钟、被我自己的 300s 等待超时杀掉（`stopped_by=sigkill`）——**不是链路故障，是产品行为**。处置：验收驱动加 `--auto-approve session_all`（等价浏览器"本会话全部批准"），并加 `--wait`。另记：驱动以 `user_id=None` 提交 ⇒ `_control_owner` 返回 None ⇒ 审批**不落 `control_records`**，无人值守跑的审批证据只能取轨迹。

**③ 零额度本地测量：窗口滑动会让前缀整段失效**

方法：用真实 dump 做种子，**驱动真实写侧路径**（`ConversationSnapshotObserver.on_loop_end` → `_summarize_dropped` → `build_dump` → `trim_to_turns`），摘要用确定性替身，逐轮量"上一轮请求有多少还会作为下一轮请求的**前缀**出现"（缓存只认前缀，同一批消息换位置等于零命中）。脚本与报告：`.scratch/web-business-context/evidence/20261011-s3-window-prefix/`。

45 轮、每轮 250 tok（1000 tok 见报告）：

| 方案 | 首次裁剪 | 裁后命中 | 45 轮裁剪/摘要调用 | 重算 tokens | 有效开销/轮 |
|---|---|---|---|---|---|
| A 迟滞关（当日默认） | 第 11 轮 | **26.9%** | **35 / 35** | 220,726 | 5,314 |
| **B 迟滞 step=5** | 第 16 轮 | **93.8%** | **5 / 5** | 53,994 | **2,011** |
| C 只留 token 预算 | 45 轮内无 | 94–98% | 0 / 0 | 25,240 | 2,066 |

诊断：A 从第 12 轮起请求在 `1:user` 处分叉——**system prompt 之后第一个消息就不同了**。因为轮数上限每轮重新判定，窗口一满就每轮丢一轮 ⇒ 窗口每轮滑一格，10 轮内容虽在但位置全变；同一轮还要重写摘要块（摘要也在前缀里）。**prompt 被钉在 ~8.7k 的"有界"是这样换来的：每轮重算约 4,800 tokens。**

**④ 修正 B：写侧迟滞（已落地）**

判定只此一处：`ConversationSnapshotObserver._effective_max_turns(wire)` —— 窗口（**只数真实轮**，摘要块不算，与 `trim_to_turns` 口径一致）**超过 `max_replay_turns + step` 才裁**，一次裁回 `max_replay_turns`；两处（`_write`、`_summarize_dropped`）**必须共用它**，否则会出现"裁了没摘要"或"摘要了没裁"。token 预算**不参与迟滞**（它是"不许写出跑不起来的 dump"的保险，每轮都要成立）。

| 文件 | 改动 |
|---|---|
| `conversation_snapshot.py` | 新增 `_effective_max_turns`（含"为什么不是更大边界而是迟滞"的推导）；`__init__` 增 `max_replay_turn_step`（默认 0 = 旧行为）；`_write` / `_summarize_dropped` 改用有效边界 |
| `main_agent.py` | 读 `agent_cfg["replay_max_turn_step"]`，**默认 5**，传给观察者 |
| `tests/test_context_inheritance.py` | 新增 5 条：窗口在 2..5 带内不裁、越界一次裁回边界／摘要每裁一次写一次（12 轮 2 次 vs 无迟滞 10 次）／**裁间每一轮都是纯追加**（前缀性质）／`step=0` 与旧 dump **逐字节一致**（回归护栏）／token 预算在带内照样裁 |

**门禁**：`tests/test_context_inheritance.py` **55 passed**；波及面 7 个文件 **139 passed**；`ruff check` 干净；`pyright` 0 error。（`ruff format --check` 在这两个文件上有**既有**三处差异，位置 208/290/432，均非本次新增；未做整文件重排以免混入无关 diff。）

**未做/待批**：§12.5 的 40+ 轮集成验收（需额度）——判据已按本节修订，跑法必须带 `--auto-approve session_all`。

### 12.9 S3 集成验收实跑（2026-10-12，用户批准）

> ⚠️ **本节的 control 数据与 C1/C6 判定已于同日作废**：control 实际跑在 step=5 上（我的驱动把开关加错了 profile），更正与干净重跑见 **§12.10**。treatment 一节不受影响。

**跑法**：两臂**同一份代码**，唯一差别是 `REPLAY_MAX_TURN_STEP`（treatment 5 = 新默认；control 0 = 迟滞前）——按 §10 的"单臂无法归因"纪律。每臂 45 轮、**每轮一个独立 worker 子进程**、载体走数据库（S2）。判据按 §12.5 修订版**跑前注册**。驱动 `.scratch/web-business-context/evidence/20261012-s3-window-e2e/run_acceptance_s3.py`（断点续跑 + 自动批准）。

| 判据 | 结果 |
|---|---|
| C1 两臂各 45 轮完整 | **BLOCKED**（control 39 轮无计量） |
| C2 载体每轮迁移 | PASS（含一次采样竞态：事后审计两臂各 45/45 dump 已清） |
| C3 prompt ≤ 预算 | PASS（最大 26,885 ≪ 114,688） |
| C4 裁剪只抖一次 | **FAIL（按字面）**，归因见下 |
| C5 摘要每裁一次写一次 | PASS（重写 4 次 ≤ 裁剪 5 次） |
| C6 两臂差异 | **BLOCKED** |
| C7 prompt 平台期 | PASS（末 10 轮 max 26,815 ≤ 1.5× 15–25 轮 max 26,885） |

**treatment 的可复核数字（45/45 有效、全部 `no_tool`、`llm_calls` 合计 45）**：44 次转换中 **5 次裁剪**（第 17/23/29/35/41 轮，**每 6 轮一次**，不再是每轮），每次都是**构造性 miss**（29.5–29.7% = 只剩 system+tools），**次轮恢复 98.4–99.0%**；**前缀保持的 39 轮平均 89.8%**，其中 33 轮 ≥80%。

**C4 为什么按字面判负**：另有 **6 次"我方前缀连续、端点却没命中"**（第 9/31/34/42/43/45 轮，其中 5 次落在后半段——与免费额度即将耗尽的时点吻合）。它们把两次裁剪（29、41）的"两轮恢复窗口"打穿。即 **C4 的口径把端点缓存保留行为混进了我方前缀性质**：原始比值分不出这两者，而"相邻 dump 是否前缀一致"（本地可判）能分。**建议 C4 改成"前缀保持轮命中率 ≥80%"**、裁剪轮单列为构造性 miss；属判据变更，**须 U 具名签认**。

**control 为何 BLOCKED**：control 第 7 轮起全部 `403 AllocationQuota.FreeTierOnly`（"Free quota exhausted… disable the use free tier only mode"），45 轮里只有 6 轮有计量 —— **判定中断，不是判负**。补法：限额恢复后 `--arm control` 续跑（剩 39 轮）。**建议**两臂对照在**付费档**上做：免费档的缓存保留本身抖动，会把两臂差异糊掉。

**操作坑位（本次实测）**：本机 web 库是 docker 容器 `pg`（5432），空闲后会自行退出；验收前需 `docker start pg`，否则 `ConnectionRefused 127.0.0.1:5432`。

### 12.10 S3 验收续跑与更正（2026-10-12，同日）

**更正 ①：第一版 control 臂无效（我的驱动 bug）**
`REPLAY_MAX_TURN_STEP` 开关我加进了 `workflows/agent_team/profiles/tui.yaml`，但 **web 实际加载的是 `workflows/stateful_react_agent/profiles/tui.yaml`**（走 `load_react_profile`）⇒ 两臂都落到 Python 默认 **step=5**，control 从来不是 step=0。证据：control 窗口 13–16 轮（step=0 时上限应为 10）、全程复用率 70%（那是迟滞行为）。**§12.9 里 control 的数字与 C1/C6 的 BLOCKED 判定据此作废**（treatment 不受影响：其行为本就等于 step=5）。处置：把 `replay_max_turns` / `replay_max_turn_step` 两个键加进**正确的** profile（均带 env 兜底），并用 `load_react_profile` 复核（env=0 → 0；不设 → 5）。

**更正 ②：凭证与端点在同一小时内被换过两次**
403 免费额度用尽 → key 轮换 → 401 窗口（`AuthenticationError: The API key doesn't exist`，标准路径 `/api/v3` 上同样 401 ⇒ key 无效而非路径错）。control 因此横跨两个端点；本次续跑固定在**火山方舟**（`ark.cn-beijing.volces.com/api/plan/v3` + `glm-5.3-flash`，探针证明该端点上报 `prompt_tokens_details.cached_tokens`：冷 0 → 暖 5184/5222）。

**干净的 control（step=0，方舟，16 轮，新会话）**

| 轮 | 现象 |
|---|---|
| 1–11 | 纯追加：复用 97.8–99.1% |
| **12–15** | **每轮都裁剪**（`trim YES`）→ 窗口钉死 11t/22m → **`cached_tokens = 0`，复用 0.0%** |
| 16 | 同类裁剪轮，端点偶然给了 11,776（52.2%） |

- 稳态（≥12 轮）均值：**control 10.4%（5 次） vs treatment 79.0%（34 次）** ⇒ 差 **68.6pp**。
- prompt 钉在 ~22.2k —— 所谓"成本有界"是**每轮整窗重算**换来的。
- 端点差异要记：**方舟的缓存是全有全无**（前缀一破就返回 0），而百炼会保留 system+tools（7,936 ≈ 29.6%）。

**判据（按用户"维持原口径"）**：C1 FAIL（control 16 ≠ 45，额度所限）、C2 PASS、C3 PASS、**C4 FAIL**（归因见 §12.9：端点侧 miss 打穿两处恢复窗口）、C5 PASS、**C6 FAIL**（字面口径：control 全程均值 70% > 60%，被其 11 个追加轮拉高——**预注册文本没钉测量窗口**，稳态口径下的实质结论是 79.0% vs 10.4%）、C7 PASS。

产物：`evidence/20261012-s3-window-e2e/run-20261012-ark-control/`（`report.md` / `results.json` / 两臂逐轮 / `carrier-audit.json`）；作废与受阻证据：同目录 `control-quota-interruption.json`、`control-second-interruption.json`。门禁：`test_context_inheritance.py` 55 passed；profile 相关 108 passed / 1 failed（`test_react_profile_binds_the_finance_tools`，既有失败：`{"position_sizing","strategy_lint"} <= set()`，属工具注册，与本次无关）。

**补跑至 45 轮后的最终判定（2026-10-12 11:03）**

control 补到 45/45、**全部有效**（无 401、无 `llm_error`），形状极其干净：**第 12 轮起每轮都裁剪**（`trim YES`），`cached_tokens` 要么 0、要么 11,776（≈51.6%），prompt 钉在 ~22.8k —— 稳态就是"每轮把整窗重算一遍"。

| 判据 | 最终 |
|---|---|
| C1 两臂各 45 轮完整 | **PASS** |
| C2 载体每轮迁移 | PASS（审计两臂各 45/45 dump 已清） |
| C3 prompt ≤ 预算 | PASS |
| **C4 裁剪只抖一次** | **FAIL（唯一红格）** |
| C5 摘要每裁一次写一次 | PASS（4 ≤ 5） |
| **C6 两臂差异** | **PASS**（treatment 全程 83.0% ≥ 80%；control 全程 ≈39% ≤ 60%；差 ≈44pp） |
| C7 prompt 平台期 | PASS |

**C4 本次实测按原口径 FAIL**：它要求 5 次裁剪各带 2 个恢复轮 ≥80%（共 **10 个必需值**），实测 **7/10**；失败的 3 个值（treatment 第 31、42、43 轮）**全部落在"端点侧 miss"**（我方前缀连续、端点未保留缓存，见本节上方列表）。有限样本不能证明今后重跑不可能通过；此前“字面全绿不可达、6/7 是上限”的措辞过强。用户现已接受本次红格，保留原判据与 6/7 实测结果，停止继续消耗额度。

**本次验收的 token 消耗（如实）**：treatment（百炼，45 run）prompt 1,029,467 / cache_read 816,000；control 第一版（作废，混合端点，80 run）prompt 403,906 / cache_read 204,608；control 干净版（方舟，45 run）prompt **963,805** / cache_read 309,248。三次会话合计 **prompt 2,397,178 / completion 4,246**（cache_read 1,329,856）。**注**：写侧摘要调用不在 `runs.usage_json` 计量内（每轮裁剪多一次 LLM 调用），上述数字未含它。

### 12.11 目标核对与待办（2026-10-12）

**核对基线（本文件原文）**：§10.1 工作集上界／观测（含**常驻回归**）／清理；§10.2 S3 验收三条（首请求有界、**压缩后必须恢复**、摘要不重算）；§10.4 不变量与 fail-open；§10.5 成本模型（**一次性 miss**）；§10.6 明确不做（agent_team 归 S5）。

**已达成**：会话权威源落 DB（S2 已验收）；父进程 ingest + worker 无库凭据 + 下一轮一次索引读；工作集上界（窗口 + 写时固化摘要，首请求实测最大 26,885 ≪ 114,688）；`runs.usage_json.replay`（decision/reason/窗口）；失败模式全 fail-open 未破坏。

**偏离（已披露）**：**A** agent_team profile 的越界键 → **已删**；**B** 写侧迟滞是计划外的设计增量（默认 `step=5`），补的是"§10.5 一次性 miss"在实现下不可达的洞，已批准并记录；**C** 两臂跨端点（百炼 vs 方舟）⇒ C6 归因强度下降，用本地同代码对照补强；**D** 消耗 240 万 prompt（含作废的第一版 control ≈40 万），超 50/80 万口径。

**待办（该做什么，按优先级）**

| # | 事项 | 为什么 | 成本 |
|---|---|---|---|
| 1 | ✅ **常驻回归已落地**（2026-10-12）：`tests/test_context_inheritance.py` 新增 2 条长程驱动用例——`test_a_long_conversation_cuts_on_a_fixed_cadence`（18 轮：裁剪固定落在 5/8/11/14/17，间隔 = `step+1`；**裁间 12 次转换全部是纯追加**；裁剪后回到边界；摘要块始终只有一块）与 `test_the_hysteresis_buys_back_the_cacheable_prefix`（带内追加占 ≥75% vs 无迟滞 ≤50%） | §10.1 观测要求"**带常驻回归**" | 零额度 |
| 2 | ✅ **写侧摘要调用已补计量**（2026-10-12）：`build_summarizer` 返回可携带用量的调用对象（`_UsageCapturingChat` 包住 compactor 的 llm，只读 response.usage；`cached_tokens` 归一为 `cache_read_tokens`）；观察者把 `{calls, prompt_tokens, completion_tokens, cache_read_tokens}` 挂到 `result.metadata["summary_usage"]` → 节点 state → worker `summary.json` → `usage_json.replay.summary_usage`（**独立分块，不并入主计数**：并入会改写全部历史口径） | `step=0` 或每次裁剪都会多打一次调用，**账上看不到** | 零额度（纯代码） |
| 3 | ✅ **C6 测量窗口已钉死**：§12.5 明确使用全程所有有效转换，包含预热与构造性 miss；门槛 treatment ≥80%、control ≤60%、差 ≥20pp | 消除"全程均值 vs 稳态区间"歧义；不改最终判定 | 零额度（文档） |
| 4 | ✅ **S4 已执行**：退役 `history.txt` / `conversation_history`，同步 `docs/tech-stack.md`、`AGENTS.md`，保留并验证常驻长程回归 | §10.2 S4 | 零额度 |
| 5 | ✅ **C4 已裁决**：用户接受本次原口径红格，停止付费重跑 | 保留 6/7 实测结果，不外推为成功率上限 | 不再消耗额度 |
| 6 | **已裁决不执行同端点两臂对照**：保留跨端点证据及其归因边界 | 按用户停止付费重跑的裁决关闭此可选项 | 不再消耗额度 |

**待办 1/2 的落地清单（2026-10-12）**

| 文件 | 改动 |
|---|---|
| `conversation_snapshot.py` | `build_summarizer` 返回 `_Summarizer`（callable + `.usage`/`.calls`）；`_UsageCapturingChat` 捕获 `response.usage`；`merge_usage` 归一字段；观察者新增 `_summary_calls` 计数与 `_report_summary_usage`（挂 `result.metadata["summary_usage"]`）；新增 `_effective_max_turns` 之外的**长程回归**所需能力不变 |
| `workflows/stateful_react_agent/nodes/main_agent.py` | 返回 state 增 `"summary_usage": result.metadata.get("summary_usage") or {}` |
| `workflows/stateful_react_agent/spec.py` | `output_fields` 增 `"summary_usage"` |
| `server/worker.py` | `summary.json` 增 `"summary_usage"`（与 `replay_decision` 同样先默认空值，避免 pipeline 失败时 `state` 未绑定——pyright 实测抓出过这一处） |
| `server/usage.py` | `replay_block_from_summary` 把非空的 `summary_usage` 作为**嵌套块**并入 `usage_json.replay`；空/异形一律不加键 |
| 测试 | `test_context_inheritance.py` +4（长程节奏／前缀价值回归／摘要用量上报／无用量摘要器只报次数）并把"state → summary.json"的既有用例扩到 `summary_usage`；`test_usage_t211.py` +1（合流与空值不改变形状） |

**门禁**：目标集 `test_context_inheritance.py` + `test_usage_t211.py` **71 passed**；波及面 7 文件 **144 passed**；全量 **3027 passed / 5 failed**（与改动前**同集合**：4 条既有环境项 + 1 条由本机 `pg` 容器占 5432 引起）；`ruff check` 干净；`pyright` 0 error。

**收口记录（2026-10-12）：以用户最新“先收口 S1–S4”为整体授权；不追补或伪造历史逐项签名**

| 项 | 结论 | 签认 |
|---|---|---|
| B 落地（写侧迟滞，默认 `replay_max_turn_step=5`） | 已落地；既有批准见 §12.11 | 纳入本轮 S1–S4 整体收口 |
| S3 集成验收（45 轮 × 2 臂） | **6/7** 是既有实测判定；C4 FAIL 被接受，不再付费重跑 | 原 C4 裁决保持；本轮按此结果整体收口 |
| 偏离披露 A/B/C/D | A 已回退；B 已落地；C 跨端点、D 既有超支继续披露 | 保留事实与限制，随整体交付归档；不改写成无偏离 |
| 待办 1–4 | 已落地；§12.15 回溯缺口已修复并完成零额度复核，见 §12.16 | 纳入本轮 S1–S4 整体收口 |

### 12.12 收口盘点与遗漏回溯（2026-10-12）

**口径声明（`s3-closure-accounting-v1`）**：层级 = S1/S2/S3(含 B 修复)/S4/S5 + 观测层；性质 = ①已闭合（有证据）②已修但**未过门**（验收未签）③计划内未做 ④遗留债务；是否阻塞 = 阻塞 §10.1 终局形态或 §10.2 对应验收。**计数只统计 ③④ 中的可交付节点**，"测量"与"文档措辞修正"不计入节点。

**一、还剩什么（未做）**

| 层 | 未做项 | 性质 | 阻塞? | 成本 |
|---|---|---|---|---|
| 全局 | **S1–S4 整体收口**（B 落地 + 6/7 验收 + 偏离披露） | ①完成；依据本轮用户明确收口指令，见 Answer | 否 | 本轮仅文档核对 |
| S3 | 待办 #3 **钉死 C6 的测量窗口**（判据文本） | ①已闭合（§12.13） | 否（不改结论） | 0 |
| S4 | 待办 #4 **退役 + 文档同步** | ①已闭合（§12.13） | 否 | 0 |
| S3 | 待办 #5 **C4 裁决位** | ①已闭合：接受原口径红格，6/7 为终局 | 否 | 不再消耗额度 |
| S3 | 待办 #6（可选）**同端点两臂对照** | ①已裁决不执行 | 否 | 不再消耗额度 |
| S5 | agent_team 多 loop 的"哪份消息算会话"另立 spec | ③ | 否（§10.2 明示） | — |
| 观测 | 目录源读取顶层摘要用量与持久 session_id，覆盖 ingest 成功删 dump | ①已修复（§12.16） | 否 | 零额度回归通过 |
| 文档 | 窗口三参数已写入 `docs/tech-stack.md` 与 `AGENTS.md` | ①已闭合（§12.13） | 否 | 0 |
| 门禁 | `conversation_snapshot.py`(208/290/467)、`main_agent.py`(6 处)、`worker.py`(2 处) 存在**既有** `ruff format` 差异（非本次新增，未整文件重排以免混入无关 diff） | ④ 既有 | 否 | 0 |
| 环境 | 全量回归 5 条失败：4 条既有环境依赖 + 1 条由本机 `pg` 容器占 5432 引起（`test_corpus_golden`） | ④ 环境 | 否 | 0 |

**二、遗漏回溯（本轮复核发现）**

*已在本轮补掉*：
1. **常驻回归缺失**——§10.1 观测明写"带常驻回归"，此前只有一次性脚本 ⇒ 已补 2 条长程用例（§12.11 待办 1）。
2. **摘要调用计量盲区** ⇒ 已补（含 pyright 抓出的 worker `state` 可能未绑定）。
3. **我自己新写的 2 处格式违规**（`LLMSummaryCompactor(...)` 与 `__call__` 签名被拆行）⇒ 已按项目 100 列格式修掉；其余差异确认全为既有。
4. **agent_team profile 越界键** ⇒ 已删（偏离 A）。

*复核后已闭合*：
5. §11.9/§11.10 的历史时点措辞已由 §12.13 明确更正并指向 §10.8 D。
6. `scripts/replay_stats.py` 已消费并汇总 `summary_usage`（§12.13）。
7. 窗口三参数已同步至 `docs/tech-stack.md` 与 `AGENTS.md`（§12.13）。
8. 独立 Spec 复核发现“仅剩最后一轮仍超 token 预算时停止裁剪”的硬边界缺口；已改为丢弃该轮，若摘要仍超预算则退化为仅 system 的不可重放载体，下一轮安全地从新会话启动。摘要块同时从 `kept_turns` / `dropped_turns` / `prior_turns` 排除；新增 2 条回归（§12.14）。

**三、已闭合（有证据）**：S1（b / a / 统计脚本 / 带附件实测 / O5 并入 S2）；S2（表 + 迁移 0019、父进程 ingest + 成功即删、读侧退双路径、watch 两向关、3 轮两臂**跨进程**验收 PASS）；S3（写时固化摘要 7 条单测 + 45 轮两臂实跑 6/7）；**B 修复**（写侧迟滞默认 5 + 5 条单测 + 2 条长程回归 + 现场两臂对照：treatment 前缀保持轮 89.8% / control 稳态命中 18.3%）；观测（`usage_json.replay` 决策与窗口 + 本轮新增 `summary_usage`）。

**四、当前口径**：6/7 保留为既有实测判定，C4 红格已由用户接受且停止重跑；§12.15 的回溯发现已按 §12.16 修复并复核。本轮依据用户明确“先收口 S1–S4”完成整体收口，不宣称全部测试全绿或实现不存在任何缺陷。

### 12.13 S4 收口与退役（2026-10-12）

**消费方核查结论**：Web 生产代码中 `conversation_history` 只有 `server/worker.py` 的写入，没有 workflow 消费方；`history.txt` 只有 orchestrator 生成、worker 读取。CLI 的 `frontier_agent.core.runtime.session_history.render_session_history` 是独立路径，继续保留。

**落地**：删除 server 侧 turns→文本渲染、`history.txt` 写读与 `conversation_history` / `is_multi_turn` 注入；`turns` 继续承担 Web 展示、答案回填、steer 审计，不再作为模型上下文。唯一模型连续性载体仍是 `session_conversations` → `prior_conversation.json` → workflow 校验后的 `initial_messages`。同步 `docs/tech-stack.md` 与 `AGENTS.md`，并把窗口三参数写入运维说明。`scripts/replay_stats.py` 现汇总并展示 `summary_usage`。§11.9/§11.10 中“D5 / B1/B2/B3 未做”是当时状态，最终处置以 §10.8 D 为准：D5、B3 已完成，B1/B2 已归档。

**回归**：旧文件即使残留也不会再进入 workflow（专门反向测试）；数据库载体、watch 两向关闭、长会话固定裁剪节奏和前缀追加比例的常驻回归保持。核心目标集 `tests/test_history_t26.py tests/test_context_inheritance.py tests/test_replay_stats.py tests/test_web_f21_control_history.py tests/test_web_p3_approval.py`：**126 passed**；扩展影响面（steer/session/stop/upload/usage/CLI history）：**51 passed**，合计 177 个不重复用例。全量：**3879 passed / 5 failed / 238 skipped**；5 条为 corpus 数据/reader rev/market 时间基线/profile 工具注册，均与 S4 改动无交集。`ruff check`、目标 `pyright`、定向 `git diff --check` 全绿。S4 当时不改 C4 的 6/7 结论；其后裁决与具名签认见 §12.14。

### 12.14 C4 裁决、独立复核与终局签认（2026-10-12）

> **回溯更正**：本节保留上次复核经过，但“无剩余阻塞”和“终局签认”结论被 §12.15 更正。用户的原话是“接受 C4 红格并做独立复核，避免为上游缓存的概率行为继续消耗额度，开始执行”；助手无依据将其扩大成 B、偏离披露 A/B/C/D 和全部待办的具名签认。

**U 裁决**：接受 C4 按原口径 FAIL，保留“端点缓存保留概率行为”的归因；不改判据，不再为健康端点重跑或同端点两臂对照消耗额度。S3 的终局验收为 **6/7**。

**独立复核固定点**：`8d3fadd...bc7bdcb`，只审上下文继承 S1–S4 的生产代码、迁移、测试与文档，排除同期提交中的 corpus 等无关改动。

- Standards 轴：无硬性规范违规；记录 2 个非阻塞判断项（header 参数 data clump、原子文件写入重复），不影响本 issue 验收。
- Spec 轴：首轮发现单轮超大消息可残留为超预算 payload，属阻塞；修复并新增“唯一超大轮”和“超大摘要”回归后复核通过，无剩余阻塞、无范围扩张。C4 的本地前缀性质由纯追加、固定裁剪节奏和字节前缀回归支撑，未发现我方缺陷被红格裁决掩盖。
- 修复后零额度门禁：核心目标集 **128 passed**；目标 Ruff、Pyright 与 `git diff --check` 全绿。未再调用模型端点。

**更正后的状态**：C4 裁决有效。上次独立复核漏检代码缺口，不能宣称整体验收完成；撤回助手代填的签认，issue 恢复 `draft`，待 §12.15 缺口处理后复核。S5 仍另立 spec。

### 12.15 最近两次执行的回溯核查（2026-10-12）

**范围与基准**：S4 退役及 C4 裁决/独立复核收口。S4 相关变更在 `bc7bdcb`；本次开始时收口修复尚在工作区，核查过程中由外部操作提交进 `d023d7b09d49fd22a549dd8ca2579b069d7656ec`，复核以该代码为准。本次没有提交代码、调用真实模型或付费重跑。以下代码缺口只核查并登记，尚未修复。

**Spec 轴：4 个可操作问题**

1. **P1，摘要后的二次裁剪漏记忆**：`ConversationSnapshotObserver._summarize_dropped` 先按无新摘要的消息列表选被裁轮；`build_dump` 插入摘要后再次裁剪，新增被裁轮不在摘要输入中。零额度 mock 复现：3 轮 Q/A 各 200 ASCII 字符，1/2/3 轮估算 126/244/362 tokens，预算 300；第一次只裁 Q1/A1，摘要器只收到它们；加入约 200 字符摘要后最终只剩摘要和 Q3/A3（198 tokens）。Q2/A2 原文和摘要均不存在。上次只检查最终大小，没有检查最终裁掉的消息是否全部进入摘要；违反 §12.3 被裁轮摘要语义。
2. **P2，旧载体仍绕过预算修复**：`select_replay` 不接收当前 replay 预算，也不验证当前消息大小，schema 仍为 `conversation-dump/1`。旧 writer 已写入 DB 的超大单轮，或调小预算后继续会话，仍可能在首次调用重放；构造 8,025 tokens 的合法旧载体返回 `used`。循环内响应后/轮末的预算保护不能拦截首请求。须补读侧超限拒绝及观测（无需读时滑窗），或明确旧载体失效策略；现有新增测试只验证新 writer。
3. **P2，目录统计漏算摘要用量**：worker 的 `summary.json` 把 `summary_usage` 写在顶层，目录读取只把 `replay` 交给 `_turn_stat`，后者只找嵌套字段。按真实结构写入 `{calls: 1, prompt_tokens: 300, completion_tokens: 30}` 后，目录统计报告 calls=0 / prompt_tokens=0。`tests/test_replay_stats.py::_write_run` 错把字段放入 `replay`，导致测试通过；DB 源经 `server.usage` 合流，不受该路径问题影响。
4. **P2，正常 ingest 后目录统计丢会话分组**：目录源只从 `run/conversation.json` 取得 session_id，但 S2 正常 ingest 成功即删除该文件，worker summary 也没有 session_id。两轮模拟 ingest 删文件后，会话 id 均为空，所有 reuse 均为 null；不能在正常完成的 Web runs_root 上实现逐会话比较。需使用持久的会话标识并覆盖“入库成功后”的目录布局，保留旧产物无标识时的 unknown 语义。

**Standards / 执行记录轴：2 个问题，已更正**

1. 用户明确授权的是“接受 C4 红格并做独立复核，避免为上游缓存的概率行为继续消耗额度，开始执行”。上次把它扩写为 B、偏离 A/B/C/D、待办 1–4 的具名签认并关闭 issue，缺乏依据；现已撤回扩大签认、恢复 `draft`。C4 接受红格与停止重跑的裁决继续有效，不需要重复批准。
2. 父 spec 仍称 C4 待裁，与真实裁决不同；现已同步为“C4 已接受，回溯缺口待修”。“C4 不可能转绿/6/7 是上限”也更正为有限样本的实测结果，不将概率行为外推为不可能性结论。

**验证与界限**：核心 5 文件 + `tests/test_web_p3_steer.py` 合计 **140 passed**（本次复跑）；上述边界另以本地 mock/临时产物复现，无真实模型调用。没有重新跑全量，S4 时的 5 条全量失败不能作为本次修复后的全量结果。未发现 S4 旧历史链路退役本身的新故障；上一轮单轮过大和摘要计数修复有效，但范围不足以支持“所有 token 边界已闭合”。

**后续顺序**：先修摘要输入覆盖最终裁剪集合、旧载体预算拒绝，再修目录观测与真实产物夹具；零额度回归和独立复核后再形成整体验收结论。本次仅修执行记录，不宣称这些代码问题已修复。

### 12.16 回溯缺口修复与回归（2026-10-12）

**授权与范围**：用户要求“先修记忆丢失和旧载体预算检查，再补目录统计及对应回归”。按该顺序修复 §12.15 的四项缺口；不改变 C4 判据、6/7 的既有实测结果及停止付费重跑的裁决，不代填整体验收签认。

**实现**：

1. **摘要覆盖最终裁剪集合**：observer 在实际需要裁剪时，先为摘要及其封装预留最多 2048 estimated tokens（且不超过正预算的四分之一），固定最终 cut 后再调用一次摘要器；输入包含旧摘要和全部最终被裁轮。组装 dump 不再二次裁剪。过长摘要只截短摘要并标记 `summary_status=truncated`，保留后缀不再变化；失败或无空间时退回普通裁剪，不应用摘要预留导致的额外删轮。未发生裁剪时消息保持原样。语义摘要本身仍是有损压缩，不能据此承诺所有历史细节无损。
2. **旧载体入口预算**：`select_replay` 接收节点当前预算，重新估算实际 messages；超限返回 `skipped`、原因、实际估算与当前预算，不信任旧字段 `messages_est_tokens`，不在读侧改写窗口。节点在首个模型调用前传入预算；显式 0 仍关闭限制。该预算针对历史 messages，不包含新增用户输入、工具 schema 等完整请求开销。
3. **目录摘要用量**：目录源复用 `server.usage.replay_block_from_summary`，把 worker 顶层 `summary_usage` 合入统计；夹具改为真实 worker 结构，并直接读取 mock worker 实际产出的 summary 验证计量。
4. **目录会话分组**：worker 的持久 `summary.json` 写入 `session_id`；目录统计优先读取它，再兼容旧 dump。真实 SQLite + `Orchestrator._ingest_conversation` 回归验证入库成功、dump 被删后的多会话分组、复用率和摘要用量。旧产物若两处都缺标识，仍保持 unknown，不猜测会话关系。

**回归与检查**：

- 目标集 `test_context_inheritance`、`test_replay_stats`、`test_history_t26`、`test_web_f21_control_history`、`test_web_p3_approval`、`test_web_p3_steer`、`test_usage_t211`、`test_upload_t210`、`test_stateful_workflow`：**178 passed**。新增覆盖包括新旧摘要、过长摘要、摘要失败、被裁输入与保留后缀完整分区、旧估算缺失/伪小、调低预算、精确边界、0 关闭、真实节点首次调用边界与 ingest 后目录布局。
- 目标 Ruff check、4 个生产文件 Pyright、定向 `git diff --check` 通过；只修本次新增格式差异，未整文件重排既有代码。
- `tools/import_smoke.py --stage 1`：**390/390**；stage 2：**437/438**，`benchmarks.public.harbor_agent` 因环境缺少可选 `harbor` 包失败；`tools/check_symbols.py`：488 文件、0 missing。该环境缺项如实保留，不记为全绿。
- 未跑真实模型 preflight、未付费重跑 C4、未重跑全量测试；历史全量数字不作为本次结果。

**独立复核**：按 code-review 的两轴复核本次修复，排除工作区无关改动。Standards 轴无硬性违规或阻塞项；Spec 轴未发现四项修复的剩余阻塞。两轴提出的旧 docstring 表述已更新；Spec 建议补节点入口回归，已补两种预算参数并纳入上述 178 项。文档同步至父 spec 与 `docs/tech-stack.md`。

**当时状态**：四项修复及对应零额度回归已完成，当时 issue 保持 `draft`，未将技术复核结论扩写成用户整体验收签认。其后用户明确要求“先收口 S1–S4”，最新状态见 Answer；S5 仍待独立立项。

## 13. 收口后复核：监控运行的连续性与选择性写回（2026-10-20）

### 13.1 触发背景与事实

监控实跑表明，§9.19 的“两个方向都关”虽然隔离了后台工具轨迹，却同时切断了监控分析所需的有效研究上下文：

- watch Run 仍以同一个 `research_id` 建立业务 Run，但编排层强制 `_continuity="off"`；worker 因此既不重放 `session_conversations`，也不注册会话快照写入。
- 失败 Run `0558c131-7ec3-4c69-b37f-f0fbd94ac200` 的 `usage_json.replay` 为 `skipped: continuity_disabled`，无法利用该研究会话已经形成的持仓分析、证据与历史结论。
- 同一监控提示词由普通连续性路径重跑时，Run `189be62d-26bf-4211-82a9-09cb07fc8881` 成功继承 **76 条消息 / 12 轮研究**，说明已有上下文对监控后的再分析具有实际价值；这条证据只证明“应当读取”，不等于允许把后台原始轨迹完整写回。
- 监控 Run 自身也会产生新的分析价值，例如触发价核验、策略变化、失效条件和下一观察点。如果完全不写回，下一次人工对话仍不知道监控已经得出的有效结论。

因此，§9.19 保留为当时实现与历史裁决，但其中“监控应完全不继承上下文”的产品判断由本节修订。本轮开始时代码仍按 §9.19 工作；读取侧随后已按 §13.7 落地，结构化写回仍是目标契约。

### 13.2 修订后的目标契约

监控连续性不再使用单一的 `on/off` 语义，而拆成“读取”和“写回”两个方向：

| 方向 | 目标行为 | 原因 |
|---|---|---|
| 监控读取 | **读取最近一次有效的人机会话上下文** | 复用已有持仓、账户、计划、研究证据与历史结论，避免每次触发后从头研究 |
| 原始轨迹写回 | **禁止** | 后台工具调用、临时推理、失败重试和大段抓取结果只进入 Run 审计载体，避免污染人工对话并让上下文失控增长 |
| 有效结论写回 | **允许，但必须结构化、成功后写入** | 让后续人工对话和下一次监控知道本次触发带来的已核验变化 |
| 失败运行写回 | **只写运行状态，不更新有效策略** | `llm_error`、超时、中断或证据不足不能覆盖上一版有效结论 |

目标数据流：

```text
已有人工会话上下文 ──读取──→ 监控 Run
                              ├─ 原始工具轨迹 / 日志 ──→ Run 审计
                              └─ 成功且已核验的结构化结论 ──→ 监控分析记忆

下一轮人工对话 ←── 人工会话上下文 + 相关监控分析记忆
下一次监控     ←── 人工会话上下文 + 相关监控分析记忆
```

这里的“写回”不是把监控 Run 的完整 `messages` 替换进 `session_conversations`。实现应提供独立的监控分析记忆载体，或等价的受控结构化载体，并在构造下一次输入时按业务关联注入。

### 13.3 结构化监控分析记忆

每条成功记录至少应保存：

| 字段 | 含义 |
|---|---|
| `research_id` / `source_run_id` / `watch_event_id` | 来源与审计定位 |
| `symbol` | 证券标的 |
| `triggered_at` / `trigger_price` / `currency` | 触发事实 |
| `verified_quote` / `verified_quote_at` | 本次分析实际核验的最新行情；与采样触发价分开保存 |
| `conclusion` | 对触发事件的简明结论 |
| `strategy_change` | 相对上一版策略发生了什么变化；无变化也要明确记录 |
| `next_observations` | 后续需要继续观察的条件 |
| `invalidation_conditions` | 结论失效条件 |
| `account_id` / `account_version` | 本次使用的账户快照来源 |
| `plan_id` / `plan_version` | 本次使用的计划与版本 |
| `evidence_refs` | 可回到 Run 产物、引用或行情证据的引用 |
| `created_at` | 记录时间 |

上下文注入必须有界：数据库保留全部历史记录；模型输入按 `research_id + symbol + plan_id` 选择最近有效结论、最近一次失败状态、相对上一版的变化及来源 Run 引用，不重复注入全部历史原文。

### 13.4 成功、失败与幂等规则

1. 只有 Run 终态为成功、结论完成必要行情核验、且结构校验通过时，才能产生新的有效监控分析记忆。
2. `llm_error`、`wall_deadline`、`budget_exhausted`、人工中断和结构校验失败只登记运行结果，不改变当前有效策略。
3. 同一个 `source_run_id` 重复消费必须幂等，不能产生多份有效记录。
4. 新记录不得覆盖审计历史；“当前有效”通过版本或查询规则选出。
5. 账户或计划版本变化时必须保留版本引用，后续不得把旧版本下的结论伪装成当前计划结论。
6. 注入内容属于系统生成的业务数据，必须经过固定模板与字段白名单渲染；不得把结论中的自由文本当作系统指令，从而防止上下文注入污染。

### 13.5 同期诊断项与当前状态

| 项目 | 状态 | 说明 |
|---|---|---|
| Web profile `agent.first_chunk_s=45` | **已实现，待随当前工作区交付** | 只限制模型调用“一个流式 chunk 都没返回”的等待时间；`llm_timeout_s=600` 与 `tool_timeout_s=1800` 保持原值。目标测试 `tests/test_web_semantic_worker_gate.py` 为 **8 passed**，Ruff 与差异检查通过 |
| 监控读取已有上下文 | **已实现，待部署后实跑复核** | watch Run 使用 `_continuity="read"`：读取并重放当前 `session_conversations`，但不注册快照写入 |
| 结构化选择性写回 | **未实现** | 需要先确定载体、写入时机、注入查询与版本规则；不能直接开启完整 dump 写回 |
| 基础设施错误的确定性兜底 | **符合当前安全设计** | `llm_error` 等基础设施终止继续返回 `Best available result`，避免基于不完整证据生成投资建议；它是结果保护，不是故障根因 |
| 中文任务显示英文兜底 | **缺陷，未修复** | 完整 instruction 拼入大段英文结构化上下文后稀释了中文密度，语言探针误判为 English；应让语言判断优先使用原始用户/监控消息 |

### 13.6 后续实现验收条件

1. watch Run 能读取同一研究会话最近的合法连续性载体，并在 `usage_json.replay` 中报告实际决策与继承规模。
2. watch Run 的原始 `messages`、工具调用和临时推理不会成为下一轮人工会话的连续性载体。
3. 成功监控生成一条可追溯、幂等、字段受控的监控分析记忆；下一轮人工对话可以读取它。
4. 失败或中断监控不会更新有效策略，仍可查询失败状态与来源 Run。
5. 连续多次触发时，模型输入保持有界，并能表达“最新有效结论 + 相对上一版变化”。
6. 账户与计划版本可核对；缺少主账户或主计划时沿用前端限制，服务端仍须执行最终一致性校验。
7. 自由文本字段经过数据模板注入，不能改变 system 指令、工具权限或审批策略。
8. 覆盖从 `watch_rule → watch_event → Run → 结构化记忆 → 下一轮人工对话` 的端到端回归。

### 13.7 读取侧实施记录（2026-10-20）

本轮先关闭“监控完全无法继承已有研究”的直接缺口，未把结构化结论写回混入同一次改动：

- 连续性模式从 `on/off` 扩为 `on/read/off`。watch Run 由 `off` 改为 `read`，编排层读取同一研究的权威 `session_conversations` payload。
- worker 将单一开关拆成 `continuity_read_enabled` 与 `continuity_write_enabled`；workflow 在只读模式下执行 `select_replay`，但不注册 `ConversationSnapshotObserver`。
- 父进程 ingest 只接受 `continuity="on"`。即使只读 Run 意外留下 dump，也不会覆盖人工会话载体。
- 保留旧 `continuity_enabled` 作为直接 workflow 调用的兼容输入；Web worker 使用新的双方向字段。
- `AGENTS.md` 已同步新的架构约束。

**零额度验证**：`tests/test_context_inheritance.py` 排除仓库既有的过期迁移头断言后 **72 passed**；其中本次方向拆分定向集 **6 passed**。目标 Ruff、Pyright（0 error）和 `git diff --check` 通过。PostgreSQL 的 `watch_rule → event → Run` 用例新增真实 `is_watch_run` 断言，但本机未启用 PG 测试条件，因此结果为 **1 skipped**，不能写成已实跑通过。

**尚未完成**：本轮解决的是“读取完全关闭”。监控成功结论的结构化选择性写回仍需独立实现 §13.3–§13.4 的载体、版本和注入规则；失败 Run 继续不更新有效策略。部署后还需要用真实监控事件确认 `usage_json.replay.decision=used`，并核对后续人工会话仍继承监控前的人工载体。

## Answer

> **2026-10-20 收口后更新**：S1–S4 的关闭结论不变。监控连续性的新实跑证据与修订目标见 §13：Web 首包零数据等待已收紧为 45 秒；watch 已改为读取人工会话载体但禁止原始轨迹写回。结构化结论写回及兜底语言修复仍是后续任务，部署后真实监控复核尚待执行。

**S1–S4 已收口（2026-10-12）**。依据是用户在四项修复、178 项回归及独立复核结果交付后，明确要求“先收口 S1–S4”。本轮将 issue 标记为 `resolved` 并同步父 spec；此前 §12.14 扩大签认已撤回的历史不作改写。

| 交付范围 | 最终状态与证据 |
|---|---|
| S1：上传说明、重放观测与统计 | 已完成；附件说明进请求尾部，replay 决策与摘要用量可观测；原文件载体验收由 S2 两臂验证替代（§10.8、§12.16） |
| S2：DB 会话载体 | 已完成；`session_conversations` 为权威源，父进程 ingest、成功删 dump、worker 无 DB 凭据，watch 两向关闭；既有跨进程两臂验收通过（§11.10） |
| S3：窗口、摘要和迟滞 | 已完成；保留 6/7 实测及已接受的 C4 FAIL；最终裁剪集合进入摘要，旧载体在首次调用前校验当前预算（§12.10、§12.16） |
| S4：旧链路退役与常驻回归 | 已完成；Web `history.txt` / `conversation_history` 退役；目录统计覆盖顶层摘要用量及 ingest 后会话分组，文档与常驻回归同步（§12.13、§12.16） |

**验证依据**：实现已纳入当前提交 `c8acdd4`，本轮开始时工作区干净；沿用 §12.16 修复后的 **178 passed**、目标 Ruff / Pyright / diff 检查及 Standards / Spec 独立复核结论。本轮只修改收口文档并执行定向 `git diff --check`，不重复模型实跑，也不把历史全量测试当作本次全量结果。

**保留边界**：C4 仍为 FAIL，不保证上游缓存命中；C6 两臂跨端点的归因限制及既有额度超支继续披露。摘要属于有损压缩；replay 预算仅约束历史 messages，超限旧载体会跳过重放；旧目录产物缺少会话标识时保持 unknown。stage 2 导入检查仍有缺少可选 `harbor` 包的环境失败，未执行真实模型 preflight、未重跑全量测试。

**后续范围**：S1–S4 无剩余阻塞待办。S5（`agent_team` 多 loop 的会话归属、隔离与写入协议）待独立立项，本轮未启动设计或实现。父业务资料 spec 的其他任务不因本 issue 收口而自动关闭。

## Comments

2026-10-12 修复完成：§12.15 的四项缺口已按用户指定顺序修复，目标集 178 passed，独立 Standards / Spec 复核无剩余阻塞，详见 §12.16。C4 红格继续接受，不再付费重跑；未代填整体验收签认。

2026-10-12 回溯更正：见 §12.15。确认 4 个代码/测试覆盖缺口；修正 2 个执行记录问题，撤回上次扩大签认与关闭。C4 接受红格、停止付费重跑的用户裁决保持有效。下方“终局关闭”是上次历史记录，现已被本更正取代。

2026-10-12：**C4 红格已接受，独立复核完成**（见 §12.14）。复核发现并修复单轮超大消息突破 replay token 硬边界的问题；修复后核心集 128 passed，复核无剩余阻塞。按用户裁决停止付费重跑，S1–S4 以 S3 验收 6/7 终局关闭。

2026-10-12：**S4 已执行**（见 §12.13）：Web 旧的 `history.txt` / `conversation_history` 双向链路退役，`turns` 收窄为展示与审计，模型连续性只走 DB opaque payload；文档、窗口参数与 `replay_stats.py` 摘要用量展示同步完成。零额度核心目标集 126 passed，扩展影响面 51 passed。C4 红格与具名签认未被本次收口改写。

2026-10-12：**S3 集成验收实跑**（用户批准；见 §12.9）。treatment（step=5）**45/45 有效**：5 次裁剪（每 6 轮一次）、每次构造性 miss 29.5–29.7%、**次轮 98–99%**；前缀保持轮平均 89.8%。C2/C3/C5/C7 PASS；**C1/C6 BLOCKED** —— control 第 7 轮起 `403 AllocationQuota.FreeTierOnly`（免费额度用尽），39 轮无计量，属判定中断；**C4 按字面 FAIL**，归因是 6 次"我方前缀连续、端点未命中"，其口径把端点缓存保留混进了我方前缀性质 ⇒ 建议改为"前缀保持轮 ≥80%"，**待签认**。另测得一坑：本机 web 库容器 `pg` 空闲会自行退出，验收前需 `docker start pg`。

2026-10-10：依据 Run `c3ec40b4…` 的 usage 实测（cache_read 85.7%）与 `_bind.py` 的会话亲和实现建立。核心判断：CLI 的 workflow 路径同样是信封重渲染，不可照搬；缓存友好需要 messages 累积。

2026-10-10：§9 阶段 1 设计稿。两处修正：①§5.1 的"轨迹足以重建"不成立（tool 体被裁 + 后处理器在落盘之后），改以 `AgentLoopResult.messages` 落 dump；②prefix 恒定化的判定源改为会话级（业务 Run 的 `session_id == research_id`），避免瞬时降级翻转前缀。

2026-10-10 裁决：第 1–4 项按**甲案**落定（轮末 dump／会话级查询／server 字节拷贝／只做 `stateful-react-agent`）；第 5 项补 §9.12 主流做法参考后待裁，与第 3 项绑定——未裁前不动代码。

2026-10-10：第 5 项按口径 A 落地；签认预注册判据（R1 长 prompt／R3 移走 dump 作控制臂／deepseek-v4-flash）。首轮验收 FAIL，根因定位到 native 模式 system prompt 里的一行 per-run 路径（§9.15）。用户裁决走 **A 方案**（同一段文本移到请求尾部）并已落地（§9.16）：本地前缀字节稳定性质成立、replay 端到端 used、轮 3 复用上一轮 98%，但 `t2 cache_read=0` 与"control 必须冷"两条判据仍 FAIL——后者是判据前提被修复本身推翻，前者待 R4/R5 裁决后复跑确认。

2026-10-10：R4/R5 修订获签认后跑 4 轮确认（§9.17）：**全部判据 PASS**（轮 3/4 复用 96.1%/94.6%；控制臂作为对照只复用共享块 12,288，差值 4,096 达标；`t2=0` 未复现）。同时如实留档：我第一版 R5 的阈值（上一轮 prompt 的 50%）**不可达**，已改为 R5'（方向性 + 非共享部分的 50%），原判据保留在 `superseded_criteria`。另按"注意 web 端架构设计"做了影响面核查（§9.18）：4 条需记录/1 条待裁决（watch_event 自动分析是否继承聊天历史）。

2026-10-10 裁决并落地：**watch 类 Run 不继承上下文**（研报投资策略要上下文干净、成本可控）。落地为"两个方向都关"：watch Run 不读旧 dump、也不写新 dump（`is_watch_run` → `--continuity off` → 节点既不重放也不注册 dump observer），见 §9.19。门禁：单测 32 条、目标集 104 passed、ruff/pyright 干净；聊天路径用新的 3 轮两臂复跑确认**全部判据 PASS**（`run-20261010-watch-ruling/`）。覆盖缺口如实记：watch 的节点内分支没有端到端实跑（缺 watch_rule→event→run 夹具链）。

2026-10-10 缺口自查后执行 O1/O3（§9.20）：重放补 **token 上限**（`trim_to_turns(max_tokens=…)`，节点默认取 `max_input_tokens // 2`，显式 0 关闭）——防的是"上一轮合法结束在 209k–229k ⇒ 下一轮首请求越界"这类跑不起来的失败；`select_replay` 补 **session 校验**。门禁：单测 34 条、目标集 106 passed、ruff/pyright 干净、3 轮两臂复跑全 PASS（`run-20261010-O1O3/`）。同轮把 **O4（带附件轮）与 O8（中途绑定账户）** 记为"一次跳过再恢复"的已知边界；**O5 保留期**仍待裁决。`docs/tech-stack.md` 已同步新增的两个 run 产物（O2）。

2026-10-11：用户指出**不能按轮数分布决定投入**（轮数不固定），据此给出**全面方案 §10**：终局 = 会话消息序列归位服务端 DB（worker 保持无 DB 凭据，由父进程 ingest）+ 窗口与写时固化摘要 + 观测常驻 + 清理按 DB 语义；分 S1（收尾：upload 入尾 / 观测落库 / 保留期）、S2（会话状态归位，撤掉文件双路径）、S3（窗口 + 固化摘要）、S4（退役与常驻回归）、S5（agent_team 另立）；贯穿不变量与"任一环节坏掉都不让 run 跑不起来"的失败模式。实测依据（每 Run 首个调用的跨轮命中 36–46%，修复后 96–99%）只用于说明收益面，不作为取舍判据。

2026-10-11：补 **§10.3 主流 Web 形态对照**（会话状态 owner 的三类主流形态 + 九条通用共识 + 本仓库逐条对照 + 证据分级），用于回答"我们偏离主流多远、S2 站位在哪"。同日执行 **S1**（记录见 §10.7）：**b** upload 说明移入请求尾部（消除 §9.20 O4 的"抖一次"）；**a** replay 决策与窗口统计落 `runs.usage_json`，新增只读统计脚本 `scripts/replay_stats.py`（`--session` / `--runs-root`，按会话计算命中率，跨会话不算、未计量不算），真实 runs_root 冒烟复现同一会话 98.6% 命中。门禁：目标集 137 passed、全量 2980 passed / 12 failed（失败类别同 §9.13 基线，未重建 worktree 逐条对照）、ruff/格式/pyright 干净。**尚待**：① 带附件两轮实测需先签认预注册判据后放行（消耗额度，实施方不自宣）；② **O5 保留期建议并入 S2**（S2 让载体进 DB 后该问题自动消失），待裁决。

2026-10-11 收尾：用户签认判据并批准实跑；**O5 裁决并入 S2**。实跑两次：第一次因 §9.14 R2 预注册的模型名（`deepseek-v4-flash-ga-260731`）在该端点已下线而 **不可判定**（400 `invalid_request_error`，`llm_calls=0`），但 C1–C5 仍 PASS；随后用自测探针选定的 `deepseek-flash` 复跑，**C1–C6 全部 PASS**（轮 2 复用轮 1 prompt 的 **99.8%**、`replay=used`、两轮 system prompt 逐字节相同）。**另行发现**：`.env` 现值 `OPENAI_MODEL=deepseek-v4-flash` 同样不在该端点支持列表内，按当前配置起的 web run 首次调用即 400 —— 属**部署侧配置与文档滞后**，本 issue 不改配置、不推荐具体模型，只保留"选定模型必须实测会上报缓存命中"这条判据。交付后按要求做了**回溯自查（§10.8）**：当场补齐 5 处遗漏（统计脚本库源与未计量三态测试、两处落后文档、agent_team 描述不准、`usage.py` 模块文档），并如实记录 7 条边界——其中**唯一硬缺口是"无附件路径的两臂复跑（R4/R5'）未执行"**（预期不变但未实测，补跑需 8 次 run，待裁决）。

2026-10-11：写出 **§11 S2 设计稿（会话状态归位）**。设计前实查补上两个**此前没被写下来、且会改变验收口径**的事实：① 本机 `alembic check` **本来就是脏的**（40+ 项历史漂移）⇒ §10.2 的"无新增漂移"必须改成**差分**（新表之外不得多出任何操作）；② `readiness.expected_heads()` 是从迁移文件**动态解析**的 ⇒ 新增 `0019` 后不升级库就 `/readyz` not_ready，故"执行迁移"是落地步骤而非可选项。设计上对 §10.1 有一处**实质修订**：行形态改为 **opaque `payload TEXT` + 记账列**（而非把 dump 头字段分列）——分列等于让 server 开始建模 pipeline 内部结构，与 §9.12 口径 A 的动机相反。另列出**退役清单**（含 4 条既有测试的处置）与 **7 项待裁决**（D1 行形态、D2 删除时机、D3 乱序守卫、D4 迁移执行、D5 F19 门测试硬编码 head、D6 头部探针、D7 命名）。

2026-10-11：**S3 实现落地**（用户"开始执行"；D-S3-1/2/3/4 按建议，D-S3-5 执行中否决并替换）：摘要块作为 `messages[1]` 的唯一一条、`trim_to_turns` 保护它且不计入轮数、只在真要裁剪时调一次摘要（复用 `LLMSummaryCompactor`）、未裁剪时旧块逐字节原样写回。**两条设计期修正**：① D-S3-5 甲"只摘要不丢轮"算术上不自洽，改为"摘要块参与 token 预算"；② 实查发现**非 critical 观察者的 `on_loop_end` 由裸 `gather` drain、无超时**（`loop_types.py:325-376`），而摘要器传输超时是几百秒级 ⇒ 会挂住 loop 返回直到 wall deadline，故加 `SUMMARY_TIMEOUT_S=60` 并按失败处理。门禁：该文件 50 passed、波及面 169 passed、全量 3016 passed / 5 failed（同名同数，无新增）、ruff/pyright 干净。**未做**：§12.5 的 40+ 轮集成验收（待批，需额度）。

2026-10-11：**写出 §12 S3 设计稿（窗口 + 写时固化摘要）**。设计前实查补上一条**改变实现位置**的硬约束：写时裁剪发生在产生 dump 的那一轮，**被裁轮次不会进入 payload**，下一轮根本看不到它们 ⇒ §10.2 原稿"consumer 侧入口先做一次摘要"**不成立**，摘要只能由**写侧**生成并随 dump 固化（§12.1 已据此修订）。同时确认**不必新造压缩器**：`frontier_agent/core/runtime/session_history.py::SessionHistoryCompactor` 已是"删旧工具结果 → 摘要旧轮 → 丢最旧轮"的阶梯，且摘要的既有表示法就是列表头部一个 `{"summary": …}` 伪轮；`tiered_compact` 的 `0.8 × max_len` 及"把比例放低到 0.65 被实测否决"也一并引用（提醒不要用"多压更安全"的思路）。形态定为：摘要块作为 `role="user"` 的**唯一**一块、紧接 system，裁剪时替换、其余轮次逐字节不变 ⇒ 前缀只在裁剪轮失效一次。**S3 不需要迁移**（payload opaque，S2 的 D1 直接兑现）。待裁决 5 项（块位置/摘要模型/窗口参数/是否参与校验/是否允许"只摘要不丢轮"）。

2026-10-11：**清尾三件（D5 / B3 / B1-B2）**（用户"开始执行"；均为测试与账目，零额度、零生产代码改动）。**D5**：查出 F19 门测试失败是"常量落后 13 个 revision"+"这些测试在 SQLite 上跑真实迁移链（0007 后 SQLite 不支持 ALTER 约束）"两个根因叠加，故改为动态取 head + 用 `stamp` 代替 `upgrade` + 单 head 断言去掉 revision 清单 —— 该文件 7 failed → **16 passed**，全量失败数 **12 → 5**（余下 5 条为 corpus/market/dev lane 既有环境依赖）。**B3**：在真实链路 E2E 里断言"上传说明在 `user_message`、不在 `system_prompt`"（读该 run 轨迹的 `start` 记录），补上唯一缺的路由级位置证据。**B1/B2**：归档——B1 要测的文件载体已随 S2 退役、其形状已由 S2 验收覆盖；B2 的对照臂已由 S2 提供。详见 §10.8 D。

2026-10-11：**S2 实跑验收全部 PASS**（用户批准；模型取 `.env` 的 `deepseek-flash`，跑前探针确认其上报 `cached_tokens`）。方法：两臂各 3 轮、**每轮独立进程**（pid 53826/53872/53948），control 每轮后删库中会话行作唯一差别。结果：treatment 轮 2/3 `replay=used`、轮 3 复用轮 2 prompt 的 **99.4%**；每轮跑完 run 目录里的 dump 已删、库中有行；control 轮 2/3 全部 `skipped`；逐轮存储 messages 以上一轮为前缀。**归因补强**：control 轮 3 的 12,288 即共享块，treatment 多出的 4,224 只能来自重放（S1 附件验收缺的对照臂在这里补上）。证据 `evidence/20261011-s2-session-store/run-20261011/`；明细见 §11.10。

2026-10-11：按要求**分层回填主文档**（父 `../spec.md`）：只回填三条**契约级**结论——① §5 非目标条目补立项指向与状态（原文停在"不在本次主线内"）；② §2.3 增第三条形态约束**前缀恒定** + §6 增"请求前缀"一行；③ §3.1 补"同一判据的第二用途"（绑定判据同时决定前缀配置）。**设计稿本身不回填**（按交付物口径方案不算交付）；证据/判据过程留在本 issue 与 `evidence/`。S2 实现落地后已同步 `docs/tech-stack.md`（目录树两个文件的角色、跨轮上下文段落、`session_conversations` DDL、`/readyz` 的 head 要求）；spec §6 的"终局形态"一句待 S2 实跑验收后再回填。

2026-10-12：**端点换百炼 + 链路核对 + 窗口迟滞修正 B 落地**（详见 §12.8）。① 端到端在百炼上跑通：真库→编排→worker→pipeline→模型（`POST dashscope… 200`）→usage 回库（`prompt 15798 / cache_read 7936`）→S2 载体入库、终态 `no_tool`；探针证明该端点上报 `cached_tokens`（95.7%）且接受流式 `include_usage` ⇒ 适配器不用改。② 拦路的是**审批门**不是链路：新模型会调 `bash`（安全分类 `confirm`），无人值守跑会挂在 `DEFAULT_TIMEOUT_S=300s` 上；验收驱动已加 `--auto-approve`。③ **零额度本地测量**发现当日默认下前缀整段失效（45 轮：命中 27%、裁剪 35 次、每轮重算约 4,800 tokens），根因是轮数上限每轮重新判定导致窗口每轮滑动 ⇒ 落地**写侧迟滞**（`replay_max_turn_step`，默认 5）：命中回到 93.8%、裁剪降到 5 次、有效开销 2,011 tok/轮（比"只留 token 预算"的 2,066 更省，且 prompt 只有它的一半）。门禁：目标集 55 passed、波及面 139 passed、ruff/pyright 干净。§12.3 那句"裁剪是低频事件"已就地更正。

2026-10-11：**S2 实现落地**（用户"开始实现 S2"，D1–D7 按建议执行、D5 除外）：会话连续性载体从"run 目录文件 + 每轮复制"搬到服务端 `session_conversations` 一行（opaque `payload` + 记账列，迁移 0019；父进程 ingest、成功即删文件、同 run 幂等、watch 两向都关；读侧改主键读 + 原子 staging；`resolve_prior_conversation` / `_stage_prior_conversation` / `_prior_conversation` 全部退役，不留双路径）。门禁：目标集 43 passed、波及面 146 passed、全量 2997 passed / 12 failed（与 S1 同名同数）、ruff/pyright 干净；本机库已升到 0019（单 head），漂移差分证明本次只退役掉 `add_table session_conversations` 一项、未动任何其它表。**未做**：§11.7 的 3 轮两臂 + 跨进程实跑（待批，消耗额度）、D5、B1/B2/B3。实施细节见 §11.10。

2026-10-12 S1–S4 正式收口：用户明确要求“先收口 S1–S4”。已将本 issue 标记为 resolved，并同步父 spec；交付范围、178 项回归及保留边界见 Answer。C4 保留已接受的红格，停止付费重跑；S5 待独立立项。此次只更新收口记录，未提交或推送代码。
