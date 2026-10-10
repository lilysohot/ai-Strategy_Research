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

## Comments

2026-10-10：依据 Run `c3ec40b4…` 的 usage 实测（cache_read 85.7%）与 `_bind.py` 的会话亲和实现建立。核心判断：CLI 的 workflow 路径同样是信封重渲染，不可照搬；缓存友好需要 messages 累积。

2026-10-10：§9 阶段 1 设计稿。两处修正：①§5.1 的"轨迹足以重建"不成立（tool 体被裁 + 后处理器在落盘之后），改以 `AgentLoopResult.messages` 落 dump；②prefix 恒定化的判定源改为会话级（业务 Run 的 `session_id == research_id`），避免瞬时降级翻转前缀。

2026-10-10 裁决：第 1–4 项按**甲案**落定（轮末 dump／会话级查询／server 字节拷贝／只做 `stateful-react-agent`）；第 5 项补 §9.12 主流做法参考后待裁，与第 3 项绑定——未裁前不动代码。

2026-10-10：第 5 项按口径 A 落地；签认预注册判据（R1 长 prompt／R3 移走 dump 作控制臂／deepseek-v4-flash）。首轮验收 FAIL，根因定位到 native 模式 system prompt 里的一行 per-run 路径（§9.15）。用户裁决走 **A 方案**（同一段文本移到请求尾部）并已落地（§9.16）：本地前缀字节稳定性质成立、replay 端到端 used、轮 3 复用上一轮 98%，但 `t2 cache_read=0` 与"control 必须冷"两条判据仍 FAIL——后者是判据前提被修复本身推翻，前者待 R4/R5 裁决后复跑确认。

2026-10-10：R4/R5 修订获签认后跑 4 轮确认（§9.17）：**全部判据 PASS**（轮 3/4 复用 96.1%/94.6%；控制臂作为对照只复用共享块 12,288，差值 4,096 达标；`t2=0` 未复现）。同时如实留档：我第一版 R5 的阈值（上一轮 prompt 的 50%）**不可达**，已改为 R5'（方向性 + 非共享部分的 50%），原判据保留在 `superseded_criteria`。另按"注意 web 端架构设计"做了影响面核查（§9.18）：4 条需记录/1 条待裁决（watch_event 自动分析是否继承聊天历史）。

2026-10-10 裁决并落地：**watch 类 Run 不继承上下文**（研报投资策略要上下文干净、成本可控）。落地为"两个方向都关"：watch Run 不读旧 dump、也不写新 dump（`is_watch_run` → `--continuity off` → 节点既不重放也不注册 dump observer），见 §9.19。门禁：单测 32 条、目标集 104 passed、ruff/pyright 干净；聊天路径用新的 3 轮两臂复跑确认**全部判据 PASS**（`run-20261010-watch-ruling/`）。覆盖缺口如实记：watch 的节点内分支没有端到端实跑（缺 watch_rule→event→run 夹具链）。

2026-10-10 缺口自查后执行 O1/O3（§9.20）：重放补 **token 上限**（`trim_to_turns(max_tokens=…)`，节点默认取 `max_input_tokens // 2`，显式 0 关闭）——防的是"上一轮合法结束在 209k–229k ⇒ 下一轮首请求越界"这类跑不起来的失败；`select_replay` 补 **session 校验**。门禁：单测 34 条、目标集 106 passed、ruff/pyright 干净、3 轮两臂复跑全 PASS（`run-20261010-O1O3/`）。同轮把 **O4（带附件轮）与 O8（中途绑定账户）** 记为"一次跳过再恢复"的已知边界；**O5 保留期**仍待裁决。`docs/tech-stack.md` 已同步新增的两个 run 产物（O2）。
