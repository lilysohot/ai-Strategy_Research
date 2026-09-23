# 投研 Agent 平台 · 技术选型与架构设计

| 项 | 内容 |
|---|---|
| 版本 / 状态 | **v1.5 · 技术实现参考**（产品范围与状态已归并到产品需求基线） |
| 上游文档 | [product-requirements.md](./product-requirements.md)（唯一产品需求真源）· [business-process.md](./business-process.md)（业务流程真源） |
| 验证物 | `server/spike.py` + `server/verify_spike.py`——A1–A7 门禁，退出码即结论；见 [plan.md](./plan/plan.md#m05-链路验证spike) |
| 既定决策 | 业务数据库 = PostgreSQL 16；**语料库 = 独立 PostgreSQL 18.6 实例（zhparser，见 §3.1）**；部署 = Docker Compose；代码组织 = 仓库内延续（monorepo）；**沙箱后端 = `native`** |
| 原则 | 复用 FrontierAgent 运行时既有挂载点，Web 层为纯新增，不修改 `frontier_agent/` 内核；本文不重新定义产品优先级 |

> **v1.2 相对 v1.1 的四处实质修正**（均由 spike 实测得出，非推测）：
> 1. **事件持久化不需要自研**——运行时 `TrajectoryFileObserver` 已增量落盘完整轨迹（含参数、用量、system_prompt、SIGKILL 安全），原 ADR-4 基于不完整复审（§5.2、§6.2）。
> 2. **默认 profile 没有文件工具**——`agent.agent_tools` 决定工具集，`simple`/`benchmark` 无 `read_file`/`create_file`，仅 `tui` 有（§5.4）。
> 3. **native 模式忽略 `_sandbox_mounts`**——bind mount 只在 bwrap 分支，上传直接进 `FRONTIER_AGENT_INPUTS_DIR`（§5.1）。
> 4. **`on_tool_call` 不是 OpenAI 线格式**——扁平 `{id, name, args}` 且此刻 `args` 为空，参数摘要须取 trajectory（§5.2）。
>
> **v1.4 文档归并**：需求、业务流程与技术实现分开维护；并按当前代码修正 Web 控制通道、市场数据源和工具暴露状态。
> **v1.5 上下文收口**：明确语料检索、用户投资约束、市场观测和对话历史是四条独立通道；
> 当前协议与入口状态见 [资料库检索与 Agent 上下文接线](corpus-retrieval.md)。
> **v1.3 变更**：新增 **§3.1 语料数据层** 与 **ADR 13–15**——语料库由 SQLite 迁至**独立
> PostgreSQL 18.6 实例**（zhparser 中文全文 + pgvector 留位 + psycopg 3），并记录排序校准结论。
> 需求与实施细节见 [plan/pg-migration.md](./plan/pg-migration.md) v2.0。

## 1. 总体架构

```text
浏览器 (Vue3 SPA)
   │ HTTPS: REST(认证/会话/模型配置/产物) + SSE(事件流/轨迹回放) + 文件上传下载
   ▼
Caddy (edge: 静态托管 + 反代, SSE 友好)
   ▼
api 容器 (frontier-web 镜像, FastAPI 单实例)
   ├─ Auth: JWT + argon2          ├─ LLM 配置: Fernet 加密存取
   ├─ Orchestrator: 任务队列 + 子进程池 (run-per-subprocess)
   │      └─ worker 子进程 (同镜像, CWD=仓库根)
   │             ├─ BenchmarkSession(注册表快照) + tui profile + server profile_overrides
   │             ├─ 用户级 LLM 注入: env OPENAI_API_KEY/BASE_URL/MODEL
   │             ├─ BridgeObserver → stdout JSONL  ← 仅流式 delta，**不落盘**
   │             ├─ TrajectoryFileObserver(运行时自带) → run_dir/agent/trajectories/*.jsonl ← **落盘**
   │             ├─ 已注册 corpus / market / strategy 工具（Web 默认 override 尚未完整暴露，见 PR-DATA-04）
   │             ├─ CorpusService(plugins/corpus/service.py) → 语料库 PG 18.6(独立实例)
   │             └─ stdin JSONL 控制通道 (stop / steer / approve)
   ├─ EventRelay: stdout JSONL(实时) + trajectory tail(回放) → asyncio 队列 → SSE
   └─ Store: SQLAlchemy 2.0 async + asyncpg → PostgreSQL (业务主库)
外部: PostgreSQL 16 容器(业务库) │ **PostgreSQL 18.6 容器(语料库 corpus-db，独立实例)** │ run_dir(trajectories/engine.log/outputs) │ 用户 LLM 端点 │ fuyao 同花顺 REST 数据源
```

## 2. 代码组织（monorepo 决策）

**在 FrontierAgent 仓库内延续，不另起仓库。** 三条硬约束：

1. **import 图谱**：server 依赖四个不可 pip 安装的仓库内模块——`frontier_agent`（内核）、`benchmarks.public.core.kernel_adapter`（BenchmarkSession）、`plugins.tools`（工具注册）、`workflows`（pipeline spec）。`pyproject.toml` 只打包核心包，其余全靠仓库根在 sys.path 才能导入；另起仓库 = sys.path hack 或 submodule，脆弱点叠加。
2. **CWD 敏感发现**：`_discover_pipeline_specs` 以 `Path("workflows")` 相对工作目录扫描 spec（kernel_adapter.py），worker 必须在仓库内路径环境下运行才能注册 `stateful-react-agent` / `agent_team` 两条 pipeline。
3. **Docker 构建上下文**：单镜像 = 整仓库 COPY。但**根 `Dockerfile` 是 apodex agent 镜像**（`SANDBOX_BACKEND=bwrap`、bubblewrap + libreoffice，被 `compose.yaml`、`docker/` 脚本与 CI 的 compose 配置校验引用），**不可覆盖**——平台镜像用 `deploy/Dockerfile.web`。

边界规则：

| 规则 | 内容 |
|---|---|
| 新代码全进新顶层目录 | `server/`、`web/`、`plugins/market/`、`deploy/`，不改动现有目录结构 |
| 依赖方向单向 | `server → frontier_agent/benchmarks/plugins/workflows`，反向禁止（先例：sdk_shim 明示"仓库中没有任何地方 import serve 层"） |
| 共享文件改动收敛一处 | 仅 `plugins/tools/__init__.py` 的 `_BUILTIN_TOOLS` 注册市场工具（+2 行），上游合并冲突面最小。注意两点：① 必须同步改 `tests/test_tool_registry.py::EXPECTED_TOOLS`，否则该用例红；② 工具**可见性**由 profile 的 `agent.agent_tools` 决定，该列表通过 `metadata['profile_overrides']` 从 server 下发，**不落上游文件** |
| git 策略 | fork 当前仓库为主仓库，打 tag 记录基线 commit；上游更新按需 cherry-pick |

何时再抽离：平台需适配多个 Agent 运行时，或需独立发布 server 层时（届时依赖面已收敛在少数 import 点，抽离成本低）。

## 3. 技术选型总表

| 层 | 选型 | 版本基线 | 理由 / 落选方案 |
|---|---|---|---|
| 后端框架 | FastAPI + uvicorn | FastAPI ≥0.115 | 原生 async、SSE 用 `StreamingResponse`、pydantic 与运行时同源；落选 Flask/Django(同步包袱) |
| 数据库 | **PostgreSQL** | 16+ | 既定决策：多写者并发、JSONB、行级锁、多用户/审计打底；落选 MySQL(无增益)、Mongo(事务弱) |
| DB 访问 | SQLAlchemy 2.0 async + asyncpg + Alembic | SQLA ≥2.0 | 异步原生；Alembic 管 schema 演进 |
| 认证 | PyJWT (HS256) + argon2-cffi | — | argon2id 抗暴力破解；JWT 24h；落选 session-cookie、passlib(维护停滞) |
| 密钥加密 | cryptography Fernet | — | 主密钥来自 `MASTER_KEY` 环境变量 |
| **事件持久化** | **运行时 `TrajectoryFileObserver`（不自建）** | — | v1.2 修正：EventStore 确为 no-op，但轨迹另有一套且已增量 flush、SIGKILL 安全、含参数与用量；见 §5.2 |
| **流式推送** | 自研 BridgeObserver → stdout JSONL → SSE | — | 运行时轨迹不含 delta，只补这一层；**不落盘**，回放走 trajectory tail；见 §5.2 |
| Agent 编排 | asyncio.create_subprocess_exec + JSONL IPC | — | run-per-subprocess；落选 Celery(重)、K8s Job(过度设计) |
| 多轮对话 | `render_session_history` / `build_session_turn` / `SessionHistoryCompactor` | frontier_agent.core.runtime.session_history | 与 TUI 同一压缩范式；注意：位于**运行时核心**（非 apodex），直接 import |
| 前端 | Vue 3 + Vite + TypeScript + Pinia | Vue ≥3.4 | 中文生态成熟、轻量 |
| 前端 SSE | fetch + ReadableStream 自封装 | — | `EventSource` 不能带 Authorization 头，且需游标重连参数 |
| UI 组件 | Element Plus | ≥2.7 | 表单/表格/上传现成 |
| 行情数据 | stub `MarketDataSource` 接口（**AKShare 预留**） | — | P1 只定接口与 mock；真实源实现为一个 factory 替换 |
| 反向代理 | Caddy | 2.x | SSE 自动适配、自动 HTTPS；落选 Nginx(需手工关缓冲/调超时) |
| 部署 | **Docker Compose** | v2 | 既定决策；见 §6 |
| 测试 | pytest + `deploy/huggingface/mock_llm.py` 假端点 | — | 全链路回归零 API 成本 |

### 3.1 语料数据层（corpus，独立于业务库）

投研语料（研报 / 文章）的检索与取证是 Agent 的**数据底座**，与上面的业务库是**两个独立 PG 实例**——
不共用连接、不共用 schema。完整需求与实施记录见 [plan/pg-migration.md](./plan/pg-migration.md) v2.0。

| 层 | 选型 | 版本基线 | 理由 / 落选方案 |
|---|---|---|---|
| 语料数据库 | **PostgreSQL**（独立实例 `corpus-db`） | **18.6** | host:port 网络接入（Windows 客户端直连）+ 多写者并发 + `pg_dump` 备份；落选继续 SQLite（**单写入者且无 host:port，硬边界**）、MySQL（无增益） |
| 中文全文检索 | **zhparser**（基于 SCWS）+ `zhcfg` 检索配置 | 源码编译（基础镜像 `pgvector/pgvector:pg18`） | **PG 内置 FTS 无中文分词器，必须装扩展**；落选 `pg_jieba`（维护活跃度）、`pgroonga`（体积/生态） |
| 向量检索 | **pgvector** | 扩展已装，**未建列** | **判据驱动、留位不建列**：当前 FTS Recall@5 已 100%，无缺口；需要时同库启用，不引入新系统 |
| DB 驱动 | **psycopg 3**（`psycopg[binary]`，`dict_row`） | `>=3.3.5` | 替代标准库 `sqlite3`；服务端游标 + 原生 COPY 入库；`dict_row` 按列名取值，避免驱动类型外泄 |
| 文档解析 | PyMuPDF / `python-docx` / `python-pptx` | `>=1.28.2` / `>=1.1` / `>=0.6.23` | 沿用 P0 选型，本次未变 |
| 排序 | **`ts_rank`**（标题 5× 加权）+ AND→OR 兜底 + 按文档去重 + 时效偏置 | — | 对照 SQLite 的 `bm25(fts, 0, 0, 5.0, 1.0)`；落选 `ts_rank_cd`（覆盖密度，不按词频/稀有度加权，实测 Recall 仅 85%）、`pg_textsearch`（新兴扩展，不压宝） |

**三条硬约束（来自 `data-layer-architecture.md` §5，写代码时遵守）**：

1. **服务层唯一收口**：所有 DB 访问经 `plugins/corpus/service.py` 的 `CorpusService`，调用方
   （`corpus_search` / `corpus_fetch` / `verify` / `golden`）**一律不直连**。
2. 服务层**不向外暴露驱动类型**（不返回 `sqlite3.Row` / psycopg 游标 / 连接对象），否则换库连坐。
3. 检索能力（分词、权重、排序）**完全关进服务层**——zhparser / ts_rank / 将来 pgvector 都只影响这一层。

> ⚠️ **版本分叉**：业务库 PG **16** vs 语料库 PG **18.6**。两者是**不同实例**，无需对齐版本；
> 但部署、备份与升级文档必须分别标注，避免混淆（已列入 `pg-migration.md` §8 待办）。

### 3.2 语料检索与业务上下文 seam

语料库的深模块是 `CorpusService`；其对 Agent 的稳定界面是 `corpus_search` 和
`corpus_fetch`。中文分词、`ts_rank`、标题加权、时效偏置及将来可能的向量融合都属于
模块实现，不得泄漏成 Workflow 或 Web 的调用约定。

在线运行不预先把全库注入 prompt：Agent 调用 `data_coverage → corpus_search → corpus_fetch`，
`run_agent_loop` 把选中的工具结果追加为 ToolMessage。搜索 snippet 只用于定位，
evidence 必须来自 fetch 的逐字原文。

结构化投资约束不属于该 seam。目标实现需新增一个小界面：

```python
InvestmentContextResolver.resolve(user_id, run_id) -> InvestmentContext
```

该模块隐藏投资计划、实际持仓/成交、用户默认值与 Run 快照的优先级和版本化逻辑，
只向 Workflow 返回已校验、可回放的 `investment_context` 和缺失字段清单。当前代码尚无该模块；
`Run.prompt` 和 Turn 对话不能作为替代实现。

## 4. 运行时链路（M0.5 spike 实测逐段验证）

「实测」= `server/spike.py` 真实跑通并由 `verify_spike.py` 的 A1–A7 断言覆盖。

| 链路段 | 结论 | 代码证据（仓库相对路径） | 状态 |
|---|---|---|---|
| Worker 驱动 | `BenchmarkSession.run(instruction, *, meta, pipeline_id, extra_input)` 返回最终 state | benchmarks/public/core/kernel_adapter.py:123 | ✅ 实测 |
| pipeline 注册 | CWD=仓库根 → `Path("workflows")` 扫描注册 | kernel_adapter.py:33 | ✅ A1 |
| 流式事件 | `metadata['sdk_extra_observers']` 主智能体与子智能体均消费 | stateful_react_agent/nodes/main_agent.py:1028；子智能体 :1403 | ✅ 实测 |
| **事件持久化** | **运行时已自带**：`TrajectoryFileObserver` 每 record `flush()`，JSON 信封原子替换 | components/observers/trajectory.py:3-4、:251-261、:329-363 | ✅ 实测 |
| 协作停止 | `metadata['pause_check']` → turn 边界检查闭环 | loop/agent_loop.py:972；pause_check.py:62 | ✅ |
| **工具集** | 由 profile 的 `agent.agent_tools` 决定，**覆盖**角色池；仅 `tui` 含 `read_file`/`create_file` | stateful_react_agent/nodes/main_agent.py:547；simple.yaml:40、benchmark.yaml:39、tui.yaml:75 | ✅ A2 |
| **文件系统约定提示** | `metadata['fs_mode']` 或 `agent.fs_mode`，缺则模型不知道 `/outputs` | stateful_react_agent/nodes/main_agent.py:670、:816 | ✅ |
| **per-run 目录** | native/container 分支读 `FRONTIER_AGENT_*_DIR`；**`_sandbox_mounts` 仅 bwrap 分支生效** | stateful_react_agent/nodes/main_agent.py:841-848 | ✅ A3 |
| **轨迹落点** | `metadata['_trial_dir']`；缺失则落 CWD 的 `logs/`（在持久卷之外） | stateful_react_agent/nodes/main_agent.py:380-386 | ✅ A4 |
| 多轮会话 | `render_session_history(turns, current_query)` + `build_session_turn` | frontier_agent/core/runtime/session_history.py:115,160 | ✅ |
| **LLM 注入** | **profile YAML 的 `${OPENAI_*}` 占位符** → `create_react_llm(profile)`；`create_llm(config)` 只喂 `ResourceManager`（aux/摘要）与 `profile` 缺失时的降级分支 | stateful_react_agent/nodes/main_agent.py:623-633、:376；stateful_react_agent/profile.py:137-140；infra/config.py:50-51 | ✅ 实测 |
| 用量 | trajectory 的 `llm` 记录带 `usage{prompt,completion,cache_*}_tokens` | components/observers/trajectory.py（spike 实测输出） | ✅ 实测 |
| 工具注册 | `_BUILTIN_TOOLS` 硬编码池；`_bootstrap` 调 `get_builtin_tools()`；**可见性**另由 `agent.agent_tools` 控制 | plugins/tools/__init__.py:49,61 | ✅ |

## 5. 服务端关键机制

### 5.1 进程与隔离

1. **run-per-subprocess**：`BenchmarkSession` 快照/恢复进程级全局注册表，同进程并发必互踩 → 每 run 独立子进程。**永不池化**：`_llm_cache`（`main_agent.py:356`，命名 profile 且无 overrides 时缓存 LLM 客户端）、`ResourceManager`、`_sandbox` 单例、`get_config()` 全为进程级状态。
2. **worker CWD = 仓库根**：pipeline 发现是 CWD 相对的（`Path("workflows")`）。副作用：`_bootstrap` 在 CWD 建 `data/`（`kernel_adapter.py:192`，已 gitignore，spike 实测确认无内容写入）。**`data/` 之外还要设 `APODEX_SPILL_DIR`**：工具结果溢出的 `spill_root()` 默认落系统临时目录，在任何 per-run 根之外，并发会互串（`_sandbox.py:2333`）。
3. **预算默认值**：`run()` 不暴露 wall_time（`kernel_adapter.py:158` 只传 `pipeline_id`）→ worker 自实现 deadline（到时 pause_check 返回 True 干净落地）+ 编排器硬超时 SIGKILL 兜底；并可设 `FRONTIER_AGENT_TASK_WALL_TIME_S` 作为调度器级硬上限（`deploy/huggingface/adapter.py:914` 的做法）+ `asyncio.wait_for` 外层兜底。默认 wall 900s、max_turns 上限，超限按 stopped 处理。
4. **孤儿治理**：worker 以 `start_new_session` 启动，编排器停机先 drain 队列再 kill 进程组；容器重建由 PID namespace 兜底。
5. **stdout 纪律**：stdout 仅 JSONL 事件；所有日志（含运行时 logging）强制 stderr 并重定向 run_dir/engine.log，worker 入口统一 logging 配置。
6. **per-run 目录树（spike 验证通过）**：`outputs` **必须嵌在 `workspace` 内**——`CODING_WORKSPACE_ROOT` 只授权一个写根，兄弟目录的 `outputs/` 会被路径授权拒绝：

```text
server/runs/<run_id>/
├── ws/                  FRONTIER_AGENT_WORKSPACE_DIR + CODING_WORKSPACE_ROOT
│   └── outputs/         FRONTIER_AGENT_OUTPUTS_DIR   ← 产物，run 结束扫描入 artifacts 表
├── inputs/              FRONTIER_AGENT_INPUTS_DIR    ← 上传文件，只读，在 ws 之外
├── spill/               APODEX_SPILL_DIR
└── run/                 _trial_dir
    ├── agent/trajectories/react_agent.{json,jsonl}   ← 运行时自写，含参数/用量
    └── engine.log
```

7. **上传不走 `_sandbox_mounts`**：native/container 分支直接读 `resolve_mount_dirs()`，bind mount 只在 bwrap 分支构造（`main_agent.py:841-848`）。上传文件**落进 `FRONTIER_AGENT_INPUTS_DIR` 即可**，再用 `metadata['_sys_prompt_addendum']` 告知路径（该 addendum 两个分支都生效，`:817`）。

### 5.2 事件与控制（v1.2 重写：持久化不自建）

**修正缘起**：v1.1 依据"运行时 EventStore 为 no-op"推出"持久化必须自建"。前半句对，后半句错——EventStore 与轨迹是两套东西，运行时自带 `TrajectoryFileObserver`，且它就是为"部分运行可读"设计的：

```3:4:frontier_agent/components/observers/trajectory.py
JSON snapshots are atomically replaced; JSONL events are flushed incrementally
so partial runs remain readable without retaining full payloads in memory.
```

每 record `flush()`（`:261`），JSON 信封 `os.replace` 原子替换、首次 flush 立即发生，注释明写理由是 *"which matters when the process is SIGKILLed (OOM)"*（`:171-175`）。spike 实测输出：

```json
{"t":"start","model_name":"…","system_prompt":"…","tool_names":[…]}
{"t":"llm","turn":1,"content":"","tool_calls":[{"name":"create_file","args":{"path":"/outputs/report.md","content":"…"}}],
 "usage":{"provider":"openai","model":"…","prompt_tokens":128,"completion_tokens":1}}
{"t":"result","turn":1,"name":"create_file","tool_call_id":"call_707a…","result":"✓ created md: …","error":false,"ms":57}
```

**职责切分**：

| 能力 | 归属 | 说明 |
|---|---|---|
| 工具调用**参数**、结果、耗时 | 运行时 trajectory | `tool_calls[].args` 完整；`result` 带 `error`/`ms` |
| token 用量（PR-GOV-03） | 运行时 trajectory | 每轮 `usage` 字段，run 结束聚合进 runs 表 |
| system_prompt 归档（L5） | 运行时 trajectory | `start` 记录 |
| SIGKILL 后仍可回放（PR-GOV-02） | 运行时 trajectory | 增量 flush，非进程结束时才写 |
| **流式 delta 实时推送** | **自研 BridgeObserver** | 轨迹只存每轮最终 content，无 delta |
| 生命周期事件（run_started/finished） | 自研 BridgeObserver | 纯推送，不落盘 |

- **双通道**：`BridgeObserver`（经 `sdk_extra_observers` 注入）→ stdout JSONL → api → asyncio 队列 → SSE，只管实时；**回放与断线续传读 `run_dir/agent/trajectories/react_agent.jsonl`，按行号游标**，不再另建 `events.jsonl`。
- **背压**：照搬 HF adapter `EventChannel` 设计——压力下只丢已读的流式 delta，绝不丢生命周期事件。delta 丢了也不影响留痕，因为轨迹里有该轮完整 content。
- **stopped_by 取值**：它在 `AgentLoopResult` 上（`on_loop_end` 的 `result.stopped_by`），**不在** `BenchmarkSession.run()` 返回的 pipeline state 里。`run()` 返回的 state 只有 `final_answer`/`final_content`/`answer_status` 等；平台需从 observer 捕获 `stopped_by` 与 worker 自己的 deadline/SIGKILL 路径合并落库。
- **observer 钩子形状（实测）**：`on_tool_call(ctx, tool_call)` 的 `tool_call` 是**扁平** `{"id","name","args"}`，**不是** OpenAI 的 `{"function":{"name","arguments"}}`；且此刻 `args` 为空（流式仍在组装）。按 `tool_call["function"]["name"]` 取值会得到空串。参数摘要一律从 trajectory 的 `llm` 记录取。
- **停止**：`metadata['pause_check']` 协作停止（带走 partial answer 回填 turns，`stopped_by` 记录）+ 编排器 SIGKILL 兜底。
- **steer**：`server.steer.SteerInbox/SteerObserver` 从 worker stdin 接收内容，在安全的工具/轮次边界注入；Web 显示“下一工具边界生效”。
- **审批**：`ApprovalObserver` 对 confirm 级工具调用发出 `approval_requested`，等待 stdin 的 approve/reject/replace；停止时拒绝尚未处理的审批，避免 worker 悬挂。

### 5.3 用户级 LLM 注入（PR-LLM-02）

**机制修正（v1.2）**：主智能体的 LLM **不是** `create_llm(config)` 造的。`create_llm(config)` 在 `BenchmarkSession._bootstrap` 里只喂给 `ResourceManager`（aux/摘要，以及 `profile` 缺失时的降级分支）。主链路是：

```
metadata["profile"] → load_react_profile() → 解析 ${OPENAI_*} 占位符 → create_react_llm(profile)
```

即环境变量注入**能生效，靠的是 profile YAML 里写了 `model: ${OPENAI_MODEL}` 这样的占位符**，属于 profile 契约而非运行时契约（`stateful_react_agent/profile.py:137-140`、`nodes/main_agent.py:623-633`）。

由此产生两条硬约束：

1. **禁止部分注入**。`_resolve_env_vars` 对裸 `${VAR}` 取不到值时返回**空串且不报错**（`infra/config.py:50-51`），而 `OpenAIClient` 把空串当未指定（`infra/openai_client.py:63-68`）：

   | 注入情况 | 结果 |
   |---|---|
   | 三个变量全注入 | ✅ 正常 |
   | 用户变量全未注入 | worker 随后从仓库 `.env` 读取系统默认三元组；系统默认也不完整时才响亮失败 |
   | **只注入 key，漏 `base_url`** | `base_url=""` → `None` → **静默打到 `https://api.openai.com/v1`，带着用户的 key** |

   故 worker 启动前必须断言用户注入要么三个全有、要么三个全无（PR-LLM-02 要求的“配置失效直接失败，不静默换用他人配置”）。

2. **`metadata["profile"]` 或 `profile_inline` 必须存在**，缺则静默走 `resource_mgr.get_llm("stateful_react")` 降级分支（`main_agent.py:376`），返回 `profile=None`，导致轮次上限、超时、压缩、工具策略全部回落到模块常量且**不报错**。

**系统默认回落**：仓库 `.env` 的路径由 `__file__` 推算（`infra/config.py:22`、`profile.py:17`），**与 CWD 无关**，且 `load_dotenv(override=False)` 保证注入值不被覆盖。结论成立，但理由不是"worker CWD=仓库根"。runs 表记录快照（model/base_url，不含 key）。

### 5.4 profile 与工具集契约（v1.4 按当前代码校正）

**默认 profile 没有文件工具。** spike 第一跑撞出：

```
Error: unknown tool 'create_file' is not available.
Available tools: bash, download_file, glob_search, grep_search, recover_result, web_fetch, web_search
```

工具集由 profile 的 `agent.agent_tools` 决定，且**它覆盖角色池**（`main_agent.py:547`）：

| profile | `agent_tools` | 文件工具 |
|---|---|---|
| `default` → `simple` | web_search, web_fetch, bash, download_file, grep_search, glob_search, recover_result | ❌ **无 `read_file` / `create_file`** |
| `benchmark`（别名 `keep5`） | 同上 | ❌ 同上 |
| `tui` | Web/文件工具 + `position_sizing` / `strategy_lint` + `corpus_*` + `data_coverage` + 四个 `market_*` 工具 | ✅ |

**PR-WB-03/04（附件与产物）在 `default`/`benchmark` 下不成立。** 二选一，均无需改上游文件：

- **方案 A**：`metadata["profile"] = "tui"`（现成，spike 已验证 7/7 通过）；
- **方案 B**：`metadata["profile"]` 用任一 profile，再用 `metadata["profile_overrides"]` 下发
  `{"agent": {"agent_tools": [...], "fs_mode": true}}`。override 是深合并且最后应用（`profile.py:73-77`），server 侧完全可控。

当前 Web worker 选择 `tui`，随后由 `server/profile.py::build_profile_overrides()` 精确覆盖
`agent.agent_tools`。该覆盖目前只保留基础 Web/文件工具，反而移除了 `tui.yaml` 中已经注册的
corpus、market、coverage、sizing 与 lint 工具；因此“注册成功”和“TUI 可用”不能写成“Web 投研链
已可用”。这是 [PR-DATA-04](product-requirements.md#44-语料市场与证据) 的 P0 接线缺口。

**投研产品目标基线**（方案 B，由 `server/` 的 profile 常量维护）：

```python
PROFILE_OVERRIDES = {
    "agent": {
        # 与 workflows/stateful_react_agent/profiles/tui.yaml 的投研工具集合取并集，
        # 再按服务端 allowlist 缩减；不得用基础列表意外遮蔽已批准的金融工具。
        "agent_tools": [
            "web_search", "web_fetch", "bash", "grep_search", "glob_search",
            "read_file", "create_file", "recover_result",
            "position_sizing", "strategy_lint", "corpus_search", "corpus_fetch",
            "data_coverage", "market_resolve", "market_quote", "market_history",
            "market_financials",
        ],
        "fs_mode": True,          # 否则模型不知道 /workspace /outputs /inputs 约定
        "thinking_format": "tag",  # 显式声明，不依赖 model_registry.yaml 对未知模型的推断
    },
}
```

`thinking_format` 显式声明的理由：未知模型走 `infer_thinking_format(model_id, default="tag")`（`profile.py:105`）；用户自带任意模型名不崩，但 `tui.yaml:55-61` 记录了 tag 模式下开标签可能缺失的坑。

**必须开启 `fs_mode`**：它决定系统提示是否包含 `/workspace`、`/outputs`、`/inputs` 约定与产物写作规范（`main_agent.py:670`、`:816`）。不开，模型不知道产物该写哪。

## 6. 数据库设计

### 6.1 PostgreSQL 业务主库（Alembic 管理）

```sql
CREATE TABLE users (
  id UUID PRIMARY KEY, username TEXT UNIQUE NOT NULL,
  password_hash TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'active',
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE user_llm_configs (
  id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id),
  name TEXT NOT NULL, base_url TEXT NOT NULL, model TEXT NOT NULL,
  api_key_cipher BYTEA NOT NULL,             -- Fernet 密文, 永不回传明文
  params_json JSONB,                         -- temperature / max_tokens / reasoning_effort
  is_default BOOLEAN NOT NULL DEFAULT false,
  last_verified_at TIMESTAMPTZ, last_verify_ok BOOLEAN,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now());

CREATE TABLE sessions (
  id UUID PRIMARY KEY, user_id UUID NOT NULL REFERENCES users(id),
  title TEXT NOT NULL, deleted_at TIMESTAMPTZ,        -- 软删除(PR-WB-01)
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  updated_at TIMESTAMPTZ NOT NULL DEFAULT now());
CREATE INDEX idx_sessions_user ON sessions(user_id, updated_at DESC);

CREATE TABLE runs (
  id UUID PRIMARY KEY, session_id UUID NOT NULL REFERENCES sessions(id),
  user_id UUID NOT NULL REFERENCES users(id),
  status TEXT NOT NULL,                               -- queued|running|completed|failed|stopped
  pipeline_id TEXT NOT NULL, prompt TEXT NOT NULL,
  final_answer TEXT, stopped_by TEXT, error TEXT,
  llm_config_id UUID REFERENCES user_llm_configs(id),
  llm_snapshot_json JSONB,                            -- model/base_url/params 快照, 不含 key
  prompt_tokens INT, completion_tokens INT, total_tokens INT,
  cache_read_tokens INT, cache_write_tokens INT, reasoning_tokens INT,
  llm_calls INT, usage_json JSONB,                    -- PR-GOV-03，聚合自 trajectory
  run_dir TEXT NOT NULL,                              -- run/agent/trajectories/、run/engine.log、ws/outputs/
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  started_at TIMESTAMPTZ, finished_at TIMESTAMPTZ);
CREATE INDEX idx_runs_session ON runs(session_id, created_at);

CREATE TABLE turns (
  id BIGSERIAL PRIMARY KEY, session_id UUID NOT NULL REFERENCES sessions(id), seq INT NOT NULL,
  role TEXT NOT NULL,                                 -- user|assistant
  content TEXT NOT NULL, run_id UUID REFERENCES runs(id),
  created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  UNIQUE (session_id, seq));

CREATE TABLE artifacts (
  run_id UUID NOT NULL REFERENCES runs(id), rel_path TEXT NOT NULL,
  size BIGINT, sha256 TEXT, created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
  PRIMARY KEY (run_id, rel_path));

CREATE TABLE audit_log (
  id BIGSERIAL PRIMARY KEY, user_id UUID REFERENCES users(id), action TEXT NOT NULL,
  detail_json JSONB, ip TEXT,
  created_at TIMESTAMPTZ NOT NULL DEFAULT now());     -- 登录/配置增删改/key 轮换
```

多轮回填：run 成功后仅取 `state["final_answer"]`（含 final_content fallback、llm_error 时 partial 处理）写为 assistant turn；不读 workflow 内部 messages（task-scoped）。

### 6.2 事件轨迹（v1.2 决策：运行时 trajectory + 自研仅 delta 推送）

**不自建 `events.jsonl`。** 运行时在 `<_trial_dir>/agent/trajectories/` 下写两个文件：

| 文件 | 内容 | 用途 |
|---|---|---|
| `react_agent.jsonl` | 增量 flush 的事件流：`start` / `llm` / `result` / `compaction` | **回放与断线续传的唯一真源**，行号即游标 |
| `react_agent.json` | 原子替换的完整信封（含 messages） | 整体查看；未来会话导出的输入（PR-GOV-05） |

记录类型与承载能力（spike 实测）：

| `t` | 关键字段 | 覆盖需求 |
|---|---|---|
| `start` | `system_prompt`、`model_name`、`tool_names`、`max_turns` | PR-GOV-01/02 诊断与回放 |
| `llm` | `turn`、`content`、`tool_calls[{name,args}]`、`usage{prompt,completion,cache_*}_tokens` | PR-GOV-02/03 参数摘要与用量 |
| `result` | `turn`、`name`、`tool_call_id`、`result`、`error`、`ms` | PR-GOV-02 工具结果 |
| `compaction` | 被丢弃与被保留的内容 | 长程运行的可解释性 |

- **理由**：与自建方案相比，运行时版本额外提供参数、用量、system_prompt 与 SIGKILL 安全，且随 run 目录整体归档，满足 PR-GOV-01/02。自研只剩“delta 实时推送”一层，且该层**不落盘**——delta 丢了也不影响留痕；导出和保留期仍属 PR-GOV-05 待办。
- **代价**：无跨 run SQL 查询（轨迹查询本就是单 run 粒度，可接受）；run 目录必须持久卷挂载；`.jsonl` 的字段契约属上游，升级时需比对（建议 T1.11 加一条 schema 断言：四个 `t` 值均出现且 `llm.usage` 可解析）。
- **EventStore 仍是 no-op**，与本节不冲突：它和轨迹是两套东西，不要再用它论证"持久化需自建"。

### 6.3 当前 HTTP 边界

| 领域 | 当前接口 |
|---|---|
| 认证 | `POST /api/auth/register`、`login`、`logout`、`password`；`GET /api/auth/me` |
| 模型连接 | `GET/POST /api/models`；`GET/PUT/DELETE /api/models/{id}`；`POST /api/models/{id}/test` |
| 研究 | `GET/POST /api/sessions`；`GET/DELETE /api/sessions/{id}`；`GET /api/sessions/{id}/turns` |
| Run | `POST /api/runs`；`GET /api/runs/{id}`、`events`、`trace` |
| 运行控制 | `POST /api/runs/{id}/control`、`steer`、`approve`、`revert` |
| 产物与变更 | `GET /api/runs/{id}/artifacts`、`artifacts/preview`、`artifacts/download`、`diff` |

除注册、登录与 `/healthz` 外，接口必须从认证上下文取得用户并做 owner 过滤。当前没有 usage 聚合、Project/Tag、全局研究搜索或在线 Claim 比较接口；不得沿用旧需求中的 `/api/models/configs` 或 `/api/sessions/{id}/runs` 作为现行契约。

## 7. Docker 化部署

### 7.1 Compose 拓扑

当前 `deploy/docker-compose.yml` 的 `full` profile 由三项服务组成：

```text
frontend（一次性构建 Vite） ──> web_dist ──> caddy（静态站点 + SSE 反代）
                                               │
                                               ▼
                                      api（FastAPI + worker 子进程）
                                               ├─ SERVER_DATABASE_URL → 外部/宿主业务库
                                               ├─ CORPUS_DSN → 外部/宿主 corpus PG
                                               └─ .env → 系统 LLM、密钥与市场凭据
```

- Compose 不创建 PostgreSQL 服务；业务库和 corpus 库必须由 `.env`/环境变量指向已部署实例。
- `frontend` 写 `web_dist` 后退出，Caddy 等待构建成功再启动；Caddy 默认发布 8080/8443，API 的 8000 端口只用于调试。
- API 只读挂载配置与 `.env`，并挂载 `data` 和 `agent_data`。
- **当前持久化缺口**：`ServerConfig.runs_root` 是 `/app/server/runs`，但 Compose 的命名卷
  `agent_data` 挂在 `/app/agent_data`；`Dockerfile.web` 对 `/app/server/runs` 和 `/app/uploads` 的
  `VOLUME` 会形成匿名卷，不能满足可识别备份与恢复。生产发布前必须把命名卷直接挂到
  `runs_root/uploads_root`，并完成 PR-GOV-05 的重启、备份和恢复验收。

### 7.2 镜像与沙箱

- 多阶段构建：python:3.12-slim + uv sync --frozen；前端 `npm run build` → dist/ 由 Caddy 托管；worker 由 api 进程同容器 spawn。
- **沙箱后端必须显式为 `native`**，这是功能前提而非仅安全选择：`main_agent.py:841-848` 只有 `container`/`native` 分支读 `FRONTIER_AGENT_*_DIR`，`auto`/`bwrap` 会改用 `<_trial_dir>/sandbox/{worktree,outputs}` 并要求真实 bind mount。因此：
  - `SANDBOX_BACKEND` 必须在**进程启动前**就位——`get_config()` 首次读取即缓存，写进 `deploy/Dockerfile.web` 的 `ENV`，不要放进 orchestrator 的 per-run env；
  - 容器内不再需要 bwrap/CAP_SYS_ADMIN；隔离由容器 + 路径授权 + 工具策略承担：沿用 HF deployment 的 `BASH_ALLOWLIST_MODE=enforce`、`FRONTIER_AGENT_TOOL_USER=off`；
  - `native` 分支下 `_sandbox_mounts` 不生效，上传走 `FRONTIER_AGENT_INPUTS_DIR`（见 §5.1-7）。
- **网络守卫**：P1 不运行不受信第三方代码（无 `run_python_code`、bash 走 allowlist）；二期若放宽，worker 移入 sidecar 容器（gVisor/kata 或低权限镜像）。
- 运维：日志 json-file 限 `max-size=50m, max-file=3`；密钥全走 .env/secrets 不烧进镜像，`MASTER_KEY` 与 `PG_PASSWORD` 独立轮换；pgdump 定时 + run 目录 rsync 备份。

## 8. 关键决策记录（ADR 摘要）

| # | 决策 | 备选 | 理由 |
|---|---|---|---|
| 1 | 业务库 PostgreSQL（既定） | SQLite | 多写者并发、JSONB、审计与多用户扩展 |
| 2 | **monorepo：仓库内延续** | 另起仓库 | import 图谱 + CWD 敏感发现 + Docker 上下文三重约束；边界靠目录规则维持 |
| 3 | run-per-subprocess，worker **CWD=仓库根**，**永不池化** | 线程并发 / CWD=run目录 / worker 池 | 全局注册表隔离 + pipeline CWD 相对发现；`_llm_cache`/`ResourceManager`/`_sandbox` 单例/`get_config()` 皆为进程级 |
| 4 | ~~事件自研 events.jsonl~~ **→ 运行时 trajectory + 自研仅 delta 推送** | 自研 events.jsonl / 事件入 Postgres / 运行时 EventStore | **v1.2 推翻**：EventStore 确为 no-op，但 `TrajectoryFileObserver` 已增量 flush 且含参数、用量、system_prompt、SIGKILL 安全。自研面从"整套事件持久化"缩小到"delta 实时推送，不落盘" |
| 5 | ~~steer 降级 P2~~ → **Web 安全边界 steer + 审批已实现** | 仅停止后追问 | worker stdin + Observer 已验证可在运行中补充方向并处理 confirm 级调用；UI 必须表达延迟生效和真实确认态 |
| 6 | 沙箱后端 **强制 `native`**（功能前提，非仅安全） | `auto`/bwrap-in-docker | 只有 container/native 分支读 `FRONTIER_AGENT_*_DIR`；同时避免 CAP_SYS_ADMIN，P1 不跑不受信代码 |
| 7 | fetch 封装 SSE | EventSource | 需 Authorization 头与游标重连 |
| 8 | Caddy 边缘代理 | Nginx | SSE/HTTPS 零配置调优成本 |
| 9 | JWT(HS256)+argon2id | session/OAuth | 单实例足够；SSO 留二期（PR-AUTH-02） |
| 10 | **profile 用 `tui` + `profile_overrides` 下发 `agent_tools`+`fs_mode`** | 沿用 `default`/`benchmark` | `simple`/`benchmark` 无文件工具；当前 Web override 还需修复金融工具遮蔽（PR-DATA-04） |
| 11 | **`_trial_dir` 必设** | 依赖 CWD 默认 | 缺失则轨迹落 CWD 的 `logs/`，在持久卷之外，PR-GOV-02/05 失效 |
| 12 | **镜像用 `deploy/Dockerfile.web`** | 根 `Dockerfile` | 根 Dockerfile 是 apodex agent 镜像，被 compose.yaml / docker/ / CI 引用，不可覆盖 |
| 13 | **语料库用独立 PG 实例（18.6）+ zhparser**，与业务库 PG 16 分离 | 并入业务库 / 继续 SQLite | 语料是 Agent 的数据底座，写入模式（按需跑批）与业务库（在线事务）不同，分离后可独立备份与扩缩；SQLite 因**单写入者 + 无 host:port** 被排除（硬边界）。详见 §3.1 |
| 14 | 语料排序用 **`ts_rank` + 标题 5× + 按文档去重 + 时效偏置** | `ts_rank_cd` / `pg_textsearch` / 服务层 rerank | 实测校准：切 PG 后 Recall@5 一度 **0%**，逐项补齐后才回到 **100%**（`pg-migration.md` §4.7）。`ts_rank_cd` 不按词频/稀有度加权，且多块文档会霸占 top-k，Recall 仅 85% |
| 15 | pgvector **留位不建列** | 现在建 `embedding` 列 | 判据驱动：当前 FTS Recall@5 = 100%，无缺口；留位可在需要时同库启用，不引入新系统 |

## 9. 安全设计要点

全接口 JWT 鉴权与用户归属过滤（非本人 404）；api_key 仅密文落库、掩码返回、不入日志，env 注入不经 argv，事件流经脱敏器再推送；上传/下载路径校验（限会话/run 目录，防越界）；登录限速锁定；audit_log 覆盖登录/配置/密钥操作；前端投研输出固定"不构成投资建议"免责声明。

## 10. 目录结构（新增部分）

```text
server/        app.py config.py orchestrator.py worker.py
               bridge.py relay.py history.py store.py security.py profile.py
               approval.py steer.py diff.py artifacts.py usage.py
               routes/{auth,models,sessions,runs,artifacts}.py  alembic/
               runs/<run_id>/{ws/{outputs/}, inputs/, spill/, run/{agent/trajectories/,engine.log}}
plugins/corpus/ PostgreSQL 语料、Claims、审计与服务层
plugins/market/ ports.py service.py factory.py sink.py trace_store.py adapters/ transport/
web/           Vite+Vue3: views/ components/ stores/ api/ sse.ts
deploy/        Dockerfile.web Dockerfile.frontend Caddyfile docker-compose.yml
docs/          product-requirements.md business-process.md tech-stack.md plan/
```

- `deploy/` 已存在 `huggingface/`（HF Space，被 CI 的 `check_public_leaks.py` 与 registry 漂移检查覆盖）。平台部署文件与它并列，**不要放进 `deploy/huggingface/`**。
- `spike.py` / `verify_spike.py` 不随 M1 删除：它们是唯一能在不开 API、不连真端点的情况下证明链路的回归门禁（对应 T1.11）。

## 11. 里程碑映射

| 里程碑 | 内容 | 验收标准 |
|---|---|---|
| **M0.5** | **链路 spike（已完成）** | `spike.py` + `verify_spike.py` A1–A7；`--profile tui` 7/7 通过，`--profile default` A2/A3 红（可复现，已定为 profile 契约约束） |
| M1 | worker/orchestrator/bridge + compose 骨架 + Alembic 初始化 | ① `verify_spike.py` 在真端点上 7/7（**A2 是 Go/No-Go 门**）；② SSE 收到 delta 且 trajectory 可回放；③ 市场工具经 `profile_overrides` 出现在 agent 工具列表；④ worker 崩溃不影响主服务 |
| M2 | 多轮/stop/产物 + PR-LLM-01/02 模型连接全套（注入+预检）+ 文件上传 | 同会话 3 轮追问上下文连贯；停止后 partial 回填 + `stopped_by` 落库；断线重连不丢事件；错误 key 预检报错；产物 size/sha256 入库 |
| M3 | Vue3 前端（登录+会话+模型配置页+运行详情回放）+ Caddy 上线 | 免责声明可见；移动端可读；运行详情能回放 trajectory 时间线 |
| M4 | corpus/claims/同花顺工具基线已落地；Web 工具暴露、Run 级市场证据、比较层与用量页待闭合 | 以 `PR-DATA-04` 至 `PR-DATA-08`、`PR-GOV-04` 的验收为准 |

**阶段 0 前置（不再与 M1 并行）**：GLM-5.3-Flash 的**工具调用**质量必须在动工前实测——`ModelProfile.tool_call_format` 默认 `native_fc` 且 ReAct 工作流**没有任何 profile 旋钮能改它**（已 grep 确认）。端点若不能稳定驱动 function calling，网页层救不回来。实测命令即 `spike.py --real`，模型名小写 `glm-5.3-flash`（官方 API enum）。

## 12. 风险与开放问题

- GLM-5.3-Flash 编排质量未实测（阶段 0 与 M1 并行暴露）；thinking 流经 BridgeObserver 以 delta 类型分事件转发，不全文透传防刷屏。
- Postgres 故障面增大 → healthcheck + restart policy + 每日备份。
- 单 api 实例 = SSE 队列在进程内；多实例需 Postgres LISTEN/NOTIFY 或 Redis 分发，二期决策。
- Web `profile_overrides` 当前遮蔽已注册金融工具，需用真实 Run 验证工具可见性、用户隔离和产物门禁。
- 产品开放问题与优先级统一见 [product-requirements.md](product-requirements.md)，不再在技术文档维护第二份清单。
