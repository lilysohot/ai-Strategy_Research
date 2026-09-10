# FrontierAgent 工作流程参考

本文档梳理 FrontierAgent 中两条核心工作流（`stateful-react-agent` 与 `agent_team` / `agent_team_report`）的整体流程、节点职责、工具使用、执行顺序与数据流向，以及异常处理与分支逻辑。它可作为项目结构与二次开发的参考。

> 说明：框架层（`frontier_agent/`）只提供**与领域无关的通用循环、调度、注册表与 AgentBus**；工作流语义（规划、终局工具行为、reporter 路由、恢复）全部放在 `workflows/` 包中，工具实现放在 `plugins/tools/`。框架**永不导入**评测层（`benchmarks/`）。

---

## 1. 整体流程概述

### 1.1 两条工作流

| 工作流 (pipeline_id) | 形态 | 入口节点 | 终局节点 | 适用场景 |
|---|---|---|---|---|
| `stateful-react-agent` | 单状态化 ReAct 智能体 | `react_agent` | `react_agent` | 单智能体研究 / 文件类基准、TUI 默认 |
| `agent_team` | 协调器 + 并行子智能体 | `main_agent` | `main_agent`、`agent_team_reporter` | 多子任务分解、协作研究 |
| `agent_team_report` | `agent_team` 的报告版变体 | `main_agent` | 同上 | reporter 默认开启 |

两条工作流都通过**同一套声明式拓扑**（`PipelineSpec`）描述，并由**同一个 ReAct 内核**（`run_agent_loop`）执行节点内的多轮推理-工具循环。

### 1.2 执行分层

```
请求/任务 (task_id, input_data, pipeline_id)
        │
        ▼
Scheduler.execute()                       # 包裹 MiniDAG，OS 级生命周期管理（墙钟、状态机）
        │ astream() 按 DAG 拓扑产出 (phase, state) 增量
        ▼
MiniDAG (DynamicGraphBuilder 由 PipelineSpec 编译)
        │ 每个节点 = node_function(state, ctx) -> dict
        ▼
节点函数 (react_agent_node / main_agent_node / agent_team_reporter)
        │ 内部调用
        ▼
run_agent_loop()                           # 领域无关的 ReAct 内核（单智能体/子智能体共用）
        │ 逐轮：准备请求 → 调用 LLM → 解析工具调用 → 执行工具 → 收尾/压缩
        ▼
ToolRegistry 解析的工具（按 role 的 allowed_tools 过滤，fail-closed）
        │
        ▼
plugins/tools/* 工具实现（受 sandbox 策略与授权约束）
```

### 1.3 声明式拓扑要素

- **`PipelineSpec`**：描述整张 DAG——`nodes`、`transitions`、`entry_point`、`terminal_nodes`、`agent_definitions`、`metadata`。
- **`NodeDefinition`**：节点身份与行为——`role_id`、`node_function`（dotted path）、`context_policy`（进入节点时从全局 state 过滤字段）、`execution_policy`（节点级工具门控）、`compression`、`output_fields`（写回 state 的字段）、`sub_agent_profiles`（本节点派生子智能体的模板）。
- **`TransitionSpec`**：有向边，`from_phase → to_phase`，`to_phase="__END__"` 表示终止；可带 `condition`（dotted path 条件函数）实现分支。
- **`ContextPolicy`**：`include_fields`（白名单）+ `inject_fields`；`filter_fn` 优先于白名单。

---

## 2. 节点 / 环节：名称、职责、依赖关系

### 2.1 `stateful-react-agent`

只有一个节点，单轮 ReAct 循环即整条流水线。

| 节点 | 函数 | 角色 | 职责 | 依赖 |
|---|---|---|---|---|
| `react_agent` | `workflows.stateful_react_agent.nodes.main_agent.react_agent_node` | `stateful_react` | 解析 profile/语言/沙箱；构造 system prompt 与 observer 栈；运行 `run_agent_loop`；在终局做答案救援（force_final_answer / ReportSynthesis）；产出 `final_answer` 与轨迹 | profile 加载器、`ResourceManager`（LLM/工具）、沙箱后端、`ToolRegistry` |

- **输入**（`context_policy.include_fields`）：`original_question`、`current_query`、`language`、`task_id`、`metadata`。
- **输出**（`output_fields`）：`final_answer`、`final_content`、`react_steps`、`language`、`session_turn`、`answer_status`、`answer_sentinel`、`final_answer_rescued`、`final_answer_rescue_mode`、`final_answer_source`、`stopped_by`、`llm_error`、`llm_error_reason`。
- **终局边**：`react_agent → __END__`。

### 2.2 `agent_team` / `agent_team_report`

两个节点，先协调器后（可选）报告器。

| 节点 | 函数 | 角色 | 职责 | 依赖 |
|---|---|---|---|---|
| `main_agent` | `workflows.agent_team.nodes.main_agent.main_agent_node` | `swarm_main` | 规划并分解问题；经 AgentBus **派生并行子智能体**；异步 fan-in 收集报告；证据/断言汇聚；通过条件边决定是否需要 reporter；产出协调器答案及 `reporter_enabled` 等控制字段 | `ResourceManager`、沙箱、AgentBus、`SpawnGuard`、子智能体运行时 `SwarmSubagentRuntime` |
| `agent_team_reporter` | `workflows.agent_team.nodes.reporter.agent_team_reporter` | `swarm_reporter` | （可选）运行 fast reporter：先评审证据候选、再撰写带引用的最终报告；**失败开放**——保留协调器答案 | `metadata` 中的 reporter 控制字段、`fast_reporter_v1` 模块 |

- **`main_agent` 输入**：`original_question`、`current_query`、`language`、`task_id`、`metadata`（外加经 AgentBus 累积的 `evidence_cards`/`assertions`）。
- **`main_agent` 输出**：`final_answer`、`final_content`、`answer_confidence`、`evidence_cards`、`assertions`、`clarified_questions`、`react_steps`、`live_followups`、`effective_question`、`answer_status`、`answer_sentinel`、`reporter_enabled`、`reporter_backend`、`reporter_wall_time_s`、`reporter_deadline_monotonic_s`、`turns_used`、`tool_calls_count`、`stopped_by`、`llm_error`、`llm_error_reason`。
- **`agent_team_reporter` 输入**（`context_policy`）：在 main 字段基础上追加 `final_answer`、`final_content`、`evidence_cards`、`assertions`、`live_followups`、`effective_question`、`reporter_backend`、`reporter_wall_time_s`、`reporter_deadline_monotonic_s`。
- **`agent_team_reporter` 输出**：`final_answer`、`final_content`、`report_markdown`、`answer_status`、`answer_sentinel`、`final_answer_source`、`final_answer_rescued`、`final_answer_rescue_mode`。

### 2.3 子智能体（agent_team 内部，非 DAG 节点）

子智能体由 `create_subagent` 工具在 `main_agent` 循环内派生，经 AgentBus 各自运行一次 `run_agent_loop`，逻辑上等同于一个受 `SwarmSubagentRuntime` 约束的 ReAct 节点：

- **角色**：`swarm_sub`
- **终局工具**：`submit_report`（terminal，必须调用才结束）
- **职责**：执行一个聚焦子任务（检索/抽取/计算），返回结构化 `Scope/Finding/Evidence` 报告；可选 `can_publish` 时按 `output_paths` manifest 写入 `/outputs`
- **约束**：`SpawnGuard` 限制深度/并行度/墙钟；`StopSignalObserver` 响应协调器的协作停止（`stop_subagent`）

### 2.4 内核循环 `run_agent_loop`（所有节点共用）

```
run_agent_loop(system_prompt, user_message, llm, tools, config, observers, …)
  └─ _run_loop_inner()
       while turn < max_turns and attempts < max_attempts:
         1) on_before_llm  (准备请求；可注入消息)
         2) call_llm       (LLM 调用，含重试/回退；产生流式 delta 事件)
         3) 解析响应        (MultiFormatToolCallParser；on_llm_response)
         4) 执行工具        (notify_tool_call → execute_tools → notify_tool_result
                             → ToolResultPostProcessor 截断 → 追加 ToolMessage)
         5) 上下文溢出守卫  (context_overflow_guard → 弹出尾部 tool/AI 消息)
         6) on_turn_end     (压缩 compaction / 暂停检查 pause_check)
```

---

## 3. 各环节涉及工具及其用途

### 3.1 工具注册与可见性（关键点）

- `plugins/tools/__init__.py` 用 **`_BUILTIN_TOOLS` 显式 allowlist** 决定哪些工具“可解析”。
- 是否对某个智能体**可见**，由其 `AgentDefinition.allowed_tools` 决定；`ToolRegistry.get_for_role(role_id)` 据此过滤（`frontier_agent/core/runtime/registries`）。
- **fail-closed**：授权失败、`sandbox` 不可用、命令越权均拒绝，绝不回退到未隔离的主机执行。

### 3.2 `stateful_react` 角色工具

| 工具 | 用途 | 备注 |
|---|---|---|
| `web_search` | 网页检索 | `REACT_NO_WEB=1` 时移除 |
| `web_fetch` | 抓取网页内容（可 `info_to_extract` 压缩） | 同上 |
| `download_file` | 下载二进制/大文件 | 同上 |
| `bash` | 受限 shell（bwrap 沙箱，命令 allowlist） | `_bash_policy` 默认 `enforce` |
| `grep_search` / `glob_search` | 在沙箱内搜索文件 | 沙箱感知 |
| `read_file` | 结构化读取（office/pdf/csv→markdown），自带分页 | 经 `recover_result` 续读 |
| `write_file` / `create_file` | 写文件 / 生成 office 文档 | |
| `recover_result` | 取回被截断的工具结果（本 run 轨迹） | 即使闭卷也保留 |
| `file_editor_*` | 文件增量编辑 | |

### 3.3 `swarm_main`（协调器）角色工具

| 工具 | 用途 | 备注 |
|---|---|---|
| `create_subagent` | 派生并注册一个子智能体会话（AgentBus） | 不实际执行子任务，仅派发 |
| `assign_task` | 给子智能体下派任务（可带 `output_paths` manifest） | agent_team 用更严格 schema |
| `collect_reports` | 异步 fan-in 聚合已完成的子智能体报告 | 长阻塞，受墙钟约束 |
| `stop_subagent` | 协作停止某子智能体（软停止，可再派发） | |
| `add_task` / `update_task` / `finish_planning` | 规划模式任务看板 | Planning 模式专用 |
| `web_search` / `grep_search` / `glob_search` | 协调器只读：澄清术语、探查输入 | 协调器**不写文件、不执行代码** |

### 3.4 `swarm_sub`（子智能体）角色工具

| 工具 | 用途 | 备注 |
|---|---|---|
| `web_search` / `web_fetch` / `download_file` | 检索/抓取 | `SWARM_NO_WEB=1` 时移除 |
| `read_file` | 读取已抓取/输入文件 | |
| `bash` / `grep_search` / `glob_search` | 沙箱内执行与检索 | 每子智能体独立 `/workspace` |
| `submit_report` | 提交结构化报告（终局工具） | 触发 `FinalizeAnswerObserver` |
| `recover_result` | 续读被截断结果 | |

### 3.5 agent_team 内置投研/市场工具（allowlist 内，按 profile 可见）

`position_sizing`、`strategy_lint`（投研内核，纯函数）、`corpus_search`、`corpus_fetch`（语料检索）、`data_coverage`（数据源覆盖度）、`market_resolve`/`market_quote`/`market_history`/`market_financials`（同花顺市场数据，只读，未配置 key 时返回 `ok=false`，不影响其他工具）、`view_image`、`run_python_code`、`submit_report` 等。

---

## 4. 执行顺序与数据流向

### 4.1 `stateful-react-agent` 数据流

```
input_data {original_question, metadata{profile, language, ...}}
   │  Scheduler._get_graph("stateful-react-agent") → 编译 MiniDAG
   ▼
[react_agent]  react_agent_node(state)
   │  - 解析 profile/语言/沙箱/observer
   │  - run_agent_loop(...) 多轮：tools 读写 /workspace,/inputs(ro),/outputs
   │  - 终局：ReportSynthesisObserver(若 reporter_enabled) 或 FinalAnswerSalvageObserver
   ▼
state += {final_answer, final_content, react_steps, answer_status, stopped_by, ...}
   │  transition: react_agent → __END__
   ▼
Scheduler 检查 _has_terminal_output(state) → 标记 COMPLETED → REPORT_GENERATED 事件
```

### 4.2 `agent_team` 数据流（含分支）

```
input_data {original_question, metadata{profile, reporter, ...}}
   │
   ▼
[main_agent]  main_agent_node(state)
   │  ├─ (可选 Planning 循环) 只读 + 看板工具规划 → finish_planning
   │  ├─ Execution 循环（run_agent_loop, 协调器工具）：
   │  │     create_subagent ──► AgentBus 派生子会话
   │  │           └─► 子智能体 run_agent_loop（swarm_sub 工具，submit_report 终局）
   │  │                 └─► SubAgentResult → fan-in 累积 evidence_cards/assertions
   │  │     collect_reports ──► 异步聚合报告回协调器
   │  │     stop_subagent ──► 协作停止
   │  ├─ 终局：reporter_enabled ? prepare_report_handoff : force_final_answer
   │  └─ bus.drain_task_metadata → 证据/断言合并；cleanup_task
   ▼
state += {final_answer, evidence_cards, assertions, reporter_enabled,
          reporter_backend, reporter_wall_time_s, ...}
   │  transition 条件：edges.should_run_reporter(state)
   │     reporter_enabled == True  → agent_team_reporter
   │     reporter_enabled == False → __END__   （保留协调器答案）
   ▼
[agent_team_reporter]  agent_team_reporter(state)       （仅在 reporter_enabled）
   │  - 解析 reporter_backend（fast / heavy；OSS 仅 fast）
   │  - _run_fast_reporter：评审证据候选 → 撰写带引用报告
   │  - 失败开放：异常时返回 {}，保留 main_agent 答案
   ▼
state += {final_answer(report_md), report_markdown, ...}
   │  transition: agent_team_reporter → __END__
   ▼
Scheduler 标记 COMPLETED
```

### 4.3 子智能体执行顺序（并行）

- 协调器在一个 ReAct 轮内可多次调用 `create_subagent` 派生多个子会话；
- `SpawnGuard` 限制同时并行数量与总墙钟；
- 子智能体各自独立 `run_agent_loop`，通过其 `LoopConfig`/`observers`/`result_adapter`/`force_finalizer`（由 `build_swarm_session_runtime_spec` 提供）；
- `collect_reports` 在子会话完成时把 `SubAgentResult` 汇合进 `AgentBus` 会话元数据，协调器读取并 fan-in。

---

## 5. 异常处理与分支逻辑

### 5.1 内核循环停止原因（stop_reason）

| 原因 | 触发 | 处理 |
|---|---|---|
| `no_tool` | 轮次无工具调用且 `no_tool_behavior="stop"` | 单智能体：文本即终局答案 |
| `response_truncated` | 输出被截断且续写超限 | 进入救援路径 |
| `max_turns` / `max_attempts` | 达到轮次/回滚预算 | 终局 |
| `llm_error` | LLM 重试耗尽仍失败 | `force_final_answer` 救援 |
| `wall_deadline` | 墙钟到（研究截止） | 协调器停研究、reporter 接管 |
| `budget_exhausted` | token 预算耗尽 | 终局救援 |
| `context_limit_reached` | 上下文溢出守卫触发 | 弹出尾部消息后终局 |
| `paused` | 暂停检查返回 True | 持久化后暂停，可恢复 |

### 5.2 答案救援（fail-open 核心）

- 非正常/基础设施终局（`max_turns`/`context_limit_reached`/`response_truncated` 属“优雅”；`llm_error`/`budget_exhausted`/`wall_deadline`/`max_attempts` 属“异常”）触发 `force_final_answer`：
  1. 用干净恢复上下文（剥离 `<think>` 与泄漏的 tool_call 标记）做**一次无工具 LLM 调用**提取纯文本答案；
  2. 失败则回退到已有 `final_content` / 已收集的子智能体报告（`collected_reports`）；
  3. 仍失败则用 `_minimal_best_effort_answer` 给出确定性、非空的部分答案（标记 `answer_status="not_found"`，前导 `<ANSWER_NOT_FOUND>`）。
- `salvage_infra_errors=False` 时跳过额外 LLM 救援，但仍返回确定性部分答案（用于 fail-fast 基准）。

### 5.3 分支逻辑

1. **reporter 条件边**：`edges.should_run_reporter` 读取 `reporter_enabled`（由 `_resolve_reporter_enabled` 依 profile / pipeline 解析；缺失键时 fail-safe 直接 `__END__`，保留协调器答案）。
2. **reporter 后端**：`reporter_backend="fast"`（OSS 含）；`"heavy"` 在 OSS 版**不支持**，会抛错；reporter 节点整体失败开放。
3. **闭卷模式**：`REACT_NO_WEB` / `SWARM_NO_WEB` 在角色工具池与实际绑定两处都强制移除 web 工具。
4. **Planning 模式**：`planning_mode` 开且 `fresh_execution_context` 开 → 两轮（规划循环用只读+看板工具，终局 `finish_planning`；随后丢弃上下文、以看板为输入启动全新执行循环）；否则单循环（PlanningGateObserver 在规划期门控工具）。
5. **直接推理模式**（`direct=true`）：不绑定任何工具，单轮纯知识作答；跳过看板/沙箱提示。

### 5.4 调度器级异常与生命周期

- **墙钟**（`FRONTIER_AGENT_TASK_WALL_TIME_S` / profile / 工作流默认）由 `Scheduler.resolve_wall_time_s` 解析；超时抛 `TaskWallTimeExceeded`，置 ABORTED。
- **过期执行令牌**：`_is_stale_execution` 检测新 runner 接管，旧 runner 在 chunk/终局边界安全退出。
- **状态机**：正常完成置 `COMPLETED` 并追加 `REPORT_GENERATED`；异常时 `set_error` 并重新抛出；`SUSPENDED`/`ABORTED` 状态抑制重复完成与失败转移。
- **沙箱/授权**：`SandboxUnavailableError` 直接拒绝（无 bwrap 且非受信 container 时）；`reset_policy_mode` / `clear_task_sandbox` / `clear_board` 在 `finally` 清理，避免跨 trial 泄漏。

### 5.5 Observer 侧护栏（部分）

| Observer | 信号 | 动作 |
|---|---|---|
| `DuplicateQueryRollbackObserver` | 已执行且已返回内容的重复 `web_search` | 弹出该轮、重采样，不消耗 `max_turns` |
| `RepetitionGuard` | 连续轮次工具调用字节相同 | 第 3 次提示，达 `stop_after` 停止（可恢复处启用） |
| `TextRepetitionGuard` | 跨轮近似一致文本 | 提示→停止 |
| `WallClockDeadlineObserver` | 到达研究截止 | 停止研究，`wall_deadline` 退出 |
| `FinalizationReserveObserver` + `LastTurnForcer` | 进入最终化保留轮 | 注入收尾提示，落地轮剥离工具 |
| `StuckTargetGuard` | 单主机持续失败 | 提示换路→隔离主机 |
| `NoProgressGuard`（协调器） | 反复 `create_subagent`/`assign_task` 无产出 | 防自旋 |
| `EvidenceObserver` / `AssertionObserver` | 子智能体产出证据/断言 | 汇入 `AgentBus` 会话元数据 |

---

## 6. 投研/交易智能体模块（Trading / Research Module）

> 术语说明：本模块在仓库文档中也称「投研内核 / 交易模块 / 交易智能体」。
> 它**不是一条独立的 DAG 流水线节点**，而是一组**挂在通用工作流之上的业务工具链 +
> 校验纪律**，主要接入 `stateful-react-agent` 的 `tui` profile（详见 §6.5 接线点），
> 其中 corpus / market 取数工具也作为「内置投研/市场工具」出现在 `agent_team` 的 allowlist。
>
> **定位红线**：本项目是**研究性推演**，`DISCLAIMER` 明示「本研究性推演不构成投资建议，
> 不涉及任何交易执行」。模块负责「让 Agent 会用研报与市场数据、产出自洽可校验的策略卡」，
> 不负责下单、不负责选股荐股。

### 6.1 模块定位与边界

| 维度 | 内容 |
|---|---|
| 核心设计 | **「算术不出 LLM」**——Agent 只做定性判断（选什么、为什么），所有数字由确定性工具产出 |
| 验收底线 | 三条硬闸（§6.6）：数字可溯源 / 算术不出 LLM / schema 完备 |
| 数据范围 | 文本侧 = 研报语料（corpus）；结构化侧 = 同花顺 fuyao 行情/财务/估值（market） |
| 模块边界 | market 侧「只做工具接入，不做存储」：取回即用、不落库、不跑批、不建表（§5.1 对照 `docs/plan/ths-market-data.md`） |
| 解耦原则 | 核心流程（workflows / corpus / position_sizing / strategy_lint / verify）**只依赖 ports 协议，永不 import `plugins.market`**；`plugins/market` 整体可删除而核心流程仍全绿（`MARKET_ENABLED=false` 即退化） |

### 6.2 模块构成（组件清单）

| 链路 | 组件 | 形态 | 职责 |
|---|---|---|---|
| **文本侧（研报）** | `corpus_search` | `@tool`（只读） | 在研报语料库定位命中文档 + 取证句柄（**只定位，不取证**：snippet 截断，禁止直接引用） |
| | `corpus_fetch` | `@tool`（只读） | 取回**逐字原文**，供写入 evidence 的 `quote`（硬闸①机制核心：原文锁在另一工具，溯源从「叮嘱」变成「路径」） |
| | `data_coverage` | `@tool`（只读） | 查询某标的研报覆盖度；`coverage=none` 时返回 `NO_COVERAGE_HINT`，强制切换到市场数据路径 |
| **结构化侧（同花顺）** | `market_resolve` | `@tool`（只读） | 标的消歧：名称/代码/完整 thscode → 唯一 `thscode`（**一切取数前置步骤**，数据端点不接受纯代码） |
| | `market_quote` | `@tool`（只读） | 实时行情快照 + 估值，带 `as_of` 时点与规范 `quote_text` |
| | `market_history` | `@tool`（只读） | 历史日 K 线（默认截断行数，禁止一次塞十年），标注复权口径 |
| | `market_financials` | `@tool`（只读） | 财务三表/指标，每条带 `period_end_ms` 与 `report_date_ms`（防前视偏差） |
| **投研内核** | `position_sizing` | `@tool`（确定性纯函数） | 单笔仓位计算；返回恒带 `computed_by="position_sizing@v1"`（硬闸②依据） |
| | `strategy_lint` | `@tool`（纯函数，无 IO） | 在线校验策略卡：10 ERROR + 4 WARN，含 evidence 溯源校验；返回 `passed` + `checked_by` |
| **离线校验** | `verify`（三硬闸） | CLI 脚本 `python -m plugins.corpus.verify` | 不信任落盘字段、一律重算：溯源命中率 + 算术复核 + schema 完备；`strict=True` 下任一闸 skipped 整卡不通过 |
| **落盘** | `create_file` + `/outputs` | 工作流文件工具 | 策略卡写 `/outputs/strategy.json`，报告写 `/outputs/report.md` |

> market 侧采用 `plugins/market/` 四层 + 两横切架构（详见 `docs/plan/ths-market-data.md §5.0`）：
> `L0 核心流程 → L1 MarketService（唯一收口） → L2 Ports（协议） → L3 Adapters（fuyao_rest/mock/csv）+ Transport`；
> 横切为 `FailurePolicy`（失败分类/熔断/转译）与 `Observability`（进程内计数 + request_id 对账，非数据库）。

### 6.3 分层架构与执行路径

```text
L0 核心业务流程（零改动）  workflows/ · corpus · position_sizing · strategy_lint · verify
        ↑ 只依赖「端口」（Protocol），永不 import plugins.market
L1 MarketService（编排）  口径归一 · 调用编排 · 错误转译 · 可选留痕（默认 no-op）
        ↑ 依赖 L2 端口；不认识 HTTP、不认识供应商、不碰数据库
L2 Ports（协议）          MarketPort 取数 · Clock 时间 · Sink 留痕（可选，默认丢弃）
        ↑ 由 L3 提供实现
L3 Adapters（可替换）     fuyao_rest（默认）/ mock（测试）/ csv（离线兜底）
L3' Transport（HTTP 治理）超时 · 退避重试 · 并发上限 · 熔断 · 单飞去重
```

**依赖方向单向**（`L0 → L1 → L2 ← L3`）：L3 不反向依赖 L1，L1 不认识 HTTP。
换供应商只改 `adapters/`；换传输（REST→推送）只改 `transport/`；market 整体下线只改配置开关。

### 6.4 业务流程（端到端执行路径）

一次「帮我分析某标的」的研究性推演，在 `run_agent_loop` 内按如下顺序推进：

```text
① 用户任务（首轮 text）：资金 / 风险偏好 / 标的 / 持有周期
        │ 缺失关键参数（如 risk_budget_pct）→ Agent 追问，不假设（P0a 验收 #5）
        ▼
② 研报路径（有研报覆盖）
   corpus_search（定位） → corpus_fetch（取证逐字） → 写入 evidence[].quote（逐字、带 source_ref+page）
        │ 若 data_coverage=none → 收到 NO_COVERAGE_HINT，立即停检索，转③
        ▼
③ 市场数据路径（无研报或需对照现实）
   market_resolve（消歧→thscode） → market_quote（实时快照+估值，带 as_of）
        → market_history（区间/均线/波动） → market_financials（财报，防前视偏差）
        │ 引用的数字原样取自 quote_text；行情口径（unit/currency/adjust）随数字走
        ▼
④ 仓位计算
   position_sizing（确定性）→ 返回 shares/amount/weight_pct/constrained_by/computed_by
        │ 缺失参数或 stop_loss>=entry_low → 返回 error，Agent 修正后重调
        ▼
⑤ 组装策略卡
   build_strategy_card(...) → Agent 用 create_file 落 /outputs/strategy.json
        │ sizing 必须原样来自 position_sizing，禁止手填
        ▼
⑥ 在线校验
   strategy_lint（纯函数）→ passed=true 才允许定稿；passed=false → Agent 修正重跑，不得绕过
        ▼
⑦ 离线校验（验收/CI）
   python -m plugins.corpus.verify strategy.json → 三硬闸重算裁定（passed/failed/skipped）
        ▼
⑧ 报告
   /outputs/report.md：关键数字带 source_ref，并标注覆盖情况（研报-only / 市场数据路径）
```

**策略卡（`strategy.json`）关键字段**（`plugins/corpus/strategy_schema.py` 权威定义）：

- `version`、`capital_total`、`position.{symbol,thesis,evidence,entry,stop_loss,target,invalidation,horizon,sizing,parameters}`
- `evidence[]`：必填四键 `source_ref / page / quote / kind`（`kind ∈ fact|forecast|opinion`；至少一条 `fact`）
- `sizing`：`computed_by` 必须等于 `"position_sizing@v1"`（硬闸②）；`sources[]` 至少含 `id` 与 `url/title` 之一
- `horizon`：封闭枚举 `1-5D|1-4W|1-3M|3-6M|6-12M|12M+`
- 风控边界（kernel 共用）：`RISK_BUDGET_MIN_PCT=0.1`/`MAX=5.0`、`DEFAULT_LOT_SIZE=100`、`DEFAULT_MAX_WEIGHT_PCT=40.0`、`MIN_RISK_REWARD=1.5`、`TUNABLE_PARAM_BUDGET=6`

### 6.5 工具用途表（投研/交易模块）

| 工具 | 入参要点 | 用途 | 产出要点 |
|---|---|---|---|
| `corpus_search` | `query`、`limit` | 研报定位（只定位不取证） | 截断 snippet + `doc_id`/`locator` 句柄 + `hint` |
| `corpus_fetch` | `doc_id`/`locator` | 取逐字原文 | 可写入 evidence 的完整原文（硬闸①来源） |
| `data_coverage` | 标的 | 研报覆盖度 | `coverage` + `NO_COVERAGE_HINT` 流程指令 |
| `market_resolve` | `query`、`limit` | 标的消歧 | `thscode`+名称；多义列候选（`ambiguous`）；找不到给 `next` |
| `market_quote` | `thscode` | 实时快照+估值 | `as_of_ms/as_of/age` + `quote_text`（口径随行）+ `caveats` |
| `market_history` | `thscode,start,end,adjust` | 日 K 线 | OHLC 序列（行数截断）+ 复权口径标注 |
| `market_financials` | `thscode,statement,period,limit` | 财报 | 三表/指标，带 `report_date_ms`（防前视偏差） |
| `position_sizing` | 资金/风险%/区间/止损/lot | 仓位计算 | `shares/amount/weight_pct/risk_per_share/constrained_by/computed_by` |
| `strategy_lint` | JSON 字符串（策略卡） | 在线校验 | `passed/errors/warnings/checked_by` |

> 四个 market 工具统一返回 `{ok, ..., as_of, quote_text, caveats, hint}`；失败时 `ok=false` +
> `reason` + `request_id` + `next`（**可执行的下一步**，绝不用估算值顶替，绝不抛异常打断 ReAct）。

**接线点（工具如何被工作流加载）**：

- `stateful-react-agent` 的 `tui.yaml`：`agent.agent_tools` 同时列出
  `position_sizing, strategy_lint, corpus_search, corpus_fetch, data_coverage, market_resolve, market_quote, market_history, market_financials`（**这才是 `--mode react` 实际绑定工具之处**；apodex 的 `react.yaml` 仅选 workflow + workflow_profile）。
- 新增一个工具须改齐 **6–7 处**：`plugins/tools/__init__.py`（导入 + `_BUILTIN_TOOLS` allowlist）、`plugins/tools/meta.py`（`TOOL_META`：`is_read_only=True`、`category="finance"`、`timeout`、行数不截断）、`apodex/agent_tools.py`（注册 + `_READ_ONLY`）、`apodex/profiles/react.yaml`、`workflows/stateful_react_agent/profiles/tui.yaml` 的 `agent_tools`。漏改则工具不可见或每次调用都要人工确认。
- `MARKET_ENABLED`（默认 `true`）总开关：关闭/缺 `THS_API_KEY` 时四个 market 工具恒定 `ok=false`，核心流程退化为未接入形态（corpus + 投研内核仍可用）。

### 6.6 三硬闸（验收底线，机械可验证）

| 闸 | 含义 | 在线（strategy_lint） | 离线（verify） |
|---|---|---|---|
| **① 数字可溯源** | 每条 evidence 的 quote 在其 `source_ref` 指向原文里逐字命中 | evidence 溯源校验（11 ERROR + 4 WARN） | `GATE_TRACEABILITY`（语料）+ `GATE_MARKET`（市场，`ths:` 前缀走 run 目录留痕比对）；未给解析器则该闸 `skipped`，`strict` 下整卡不通过 |
| **② 算术不出 LLM** | `sizing.computed_by=="position_sizing@v1"`，金额/权重可重算复核 | 删 `computed_by` → ERROR | `GATE_ARITHMETIC`：按容差 `RECOMPUTE_TOLERANCE=0.01` 重算复核；市场衍生量（ATR/波动率/回撤）同样需 `computed_by`（M12 待办 `market_stats`） |
| **③ schema 完备** | 止损/失效条件/时间窗必填 + 反过拟合预算 | 10 ERROR（含 `entry/stop_loss/target/invalidation/horizon` 必填、风险敞口、过拟合旋钮预算） | `GATE_SCHEMA`：重跑 lint 契约 + 校验 lint 结果确实来自 `strategy_lint@v1` |

> 三条闸**不保证「策略有投资价值」**，只保证「**不产出骗人的策略**」。
> 市场数据溯源语义从「冻结值相等」放宽为「来源时点可证伪 + 值域可比」——价格实时时变，
> 我们不要求值等于某静态快照，只要求值确实出自标注 `as_of` 时点的真实调用、且未被篡改/编造；
> 凭空编数仍必被 `GATE_MARKET` 挡住。

### 6.7 异常处理与分支逻辑

**market 取数失败分类（四道防线，各层只做自己那件事）**：

| 层 | 机制 | 失败行为 |
|---|---|---|
| Transport | 超时 10s、退避重试（≤3 次，指数+抖动）、并发上限（默认 4）、**熔断**（连续失败→60s 快速失败）、单飞去重 | 抛 `MarketUnavailable`，**不把 `httpx` 异常外传** |
| Service | 失败转译 + 部分成功 `partial` | 转成 `{ok, reason, request_id, next}` |
| Tool | 恒定返回结构 + 可执行 `hint` | `ok=false`，**绝不抛异常打断 ReAct** |
| 流程/硬闸 | 缺数据 ≠ 编造数据 | 见下 |

**失败分类与可重试性**：

| 类 | 触发 | 重试 | 工具层行为 |
|---|---|---|---|
| 网络/超时 | 连接失败、读超时 | 是（≤3） | 退避后仍失败 → `ok=false` |
| 限流 | 429 / `code=4001` | 是（更长退避+降并发） | 仍失败 → `ok=false`，**绝不返回旧值** |
| 鉴权 | `2001`/`2003` | 否（fail-fast） | 提示检查 `THS_API_KEY`/capability |
| 标的/数据 | `3001`/`3002`/`3004` | 否 | 引导 `market_resolve` 消歧 |
| 上游异常 | `5001–5003` | 是（1 次） | `ok=false` + 计数 |
| 解析失败 | 字段缺失/类型漂移/`data` 为 `null` | 否 | 判为契约破坏，保留 `raw_json`，**绝不猜值填进**（猜值≈编造，正是硬闸要挡的） |

**业务流程级分支**：

- **研报无覆盖**（`data_coverage=none`）→ 收到 `NO_COVERAGE_HINT`，立即停研报检索、切市场数据路径，结论标注「无研报覆盖，基于市场数据与技术面」。
- **行情取不到** → 该维度留空、卡里记 `market_data_unavailable`；允许落「研报-only 卡」+ WARN（不阻断）；若要求「无行情不出卡」需把该 WARN 升 ERROR（§10 待拍板）。
- **market 整体不可用**（`MARKET_ENABLED=false`/缺 Key）→ 工具恒定 `ok=false`，流程退化为今日形态（corpus + 投研内核仍可用），全绿。
- **硬闸不通过** → `strategy_lint` 返回 `passed=false`，Agent **修正后重跑或直接报告不可行，不得绕过校验落卡**（反向验收：构造 `stop_loss>=entry_low` 的策略必须 `passed=false`）。
- **前视偏差**（`financial_lookahead`）→ evidence 引用的 `report_date_ms` 晚于策略形成时点 ⇒ ERROR。
- **口径混用**（`adjust_mismatch`）→ 同卡混用不同复权口径 ⇒ ERROR。

## 7. 关键文件索引

| 关注点 | 路径 |
|---|---|
| 声明式拓扑模型 | `frontier_agent/models/pipeline_spec.py` |
| DAG 编译 | `frontier_agent/core/runtime/dag/graph_builder.py` |
| 调度器（墙钟/状态机） | `frontier_agent/scheduling/scheduler.py` |
| 工作流加载 | `frontier_agent/scheduling/workflow_loader.py` |
| ReAct 内核 | `frontier_agent/core/runtime/loop/agent_loop.py` |
| 工具注册表与 allowlist | `plugins/tools/__init__.py` |
| 单智能体工作流 | `workflows/stateful_react_agent/` |
| 多智能体工作流 | `workflows/agent_team/` |
| 子智能体运行时 | `workflows/agent_team/subagent_runtime.py` |
| reporter 条件边 | `workflows/agent_team/edges.py` |
| AgentBus / SpawnGuard | `frontier_agent/components/agent_bus/` |
| Observer 库 | `frontier_agent/components/observers/` |
| 投研内核（仓位/校验） | `plugins/tools/position_sizing.py` · `plugins/tools/strategy_lint.py` · `plugins/corpus/strategy_schema.py` |
| 离线三硬闸校验 | `plugins/corpus/verify.py` |
| 研报语料链路 | `plugins/corpus/`（service/index/fetch/verify）· `plugins/tools/corpus_search.py` · `plugins/tools/corpus_fetch.py` |
| 同花顺市场数据链路 | `plugins/market/`（service/ports/adapters/transport/failure/sink）· `plugins/tools/market_*.py` |
| 模块设计文档 | `docs/plan/p0-research-kernel.md` · `docs/plan/ths-market-data.md` · `docs/plan/p1-corpus-scaleup.md` |
