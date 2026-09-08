# 投研 Agent 平台 · 用户层需求文档

| 项 | 内容 |
|---|---|
| 版本 / 状态 | v1.1 · 已定稿（并入 **M0.5 spike 实测结论**，见 tech-stack.md §4/§5） |
| 范围 | 用户认证、大模型配置管理、会话留痕与用量归属 |
| 不含 | 金融数据工具实现（stub 预留）、审批仲裁、团队/组织、计费扣费、运行中插话（steer，降级至 P2，见 FR-3.3） |
| 关联文档 | [tech-stack.md](./tech-stack.md)（技术选型与架构设计，含 §5.4 profile/工具集契约、§5.2 事件持久化修正） |
| 验证物 | `server/spike.py` + `server/verify_spike.py`（A1–A7 门禁） |

## 1. 背景与目标

平台基于 FrontierAgent 运行时提供 Web 投研助手。用户层需解决三件事：

1. 多人可各自注册登录，数据互相隔离；
2. 每个用户可配置**自己的**大模型端点（不同厂商 / 不同 key），不与他人共享配额；
3. 每次对话"有迹可循"：从用户消息 → Agent 执行过程（工具调用、LLM 轮次）→ 最终回答 → 产物文件，全链路可回查。

## 2. 角色与术语

- **用户**：注册登录的平台使用者（P1 仅个人角色）。
- **LLM 配置**：一组 `{名称, base_url, model, api_key, 可选参数}`，属于某个用户。
- **会话（Session）**：一个持续的多轮对话容器。
- **运行（Run）**：会话中一次 Agent 执行（子进程隔离）。
- **轮次（Turn）**：会话中一问一答。
- **运行目录（run_dir）**：`server/runs/<run_id>/`，含 `run/agent/trajectories/`（运行时自写轨迹 `react_agent.jsonl` / `.json`，**持久化真源，非自建**）、`engine.log`（引擎日志）、`ws/outputs/`（产物）、`inputs/`（上传）、`spill/`（工具结果溢出）。详见 tech-stack.md §5.1。

## 3. 功能需求

### FR-1 用户注册与登录

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-1.1 | 用户名/密码注册；密码强度≥8 位含字母数字；argon2id 哈希存储 | P0 |
| FR-1.2 | 登录签发 JWT（HS256，有效期 24h）；`GET /api/auth/me` 返回当前用户 | P0 |
| FR-1.3 | 登录失败限速（同账号 5 次/10 分钟锁定） | P0 |
| FR-1.4 | 修改密码、登出（客户端删 token + 服务端短黑名单可选） | P1 |
| FR-1.5 | 邮箱验证 / OAuth SSO | 二期 |

### FR-2 用户级大模型配置

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-2.1 | 用户可增删改多个 LLM 配置，指定一个为**默认配置**；字段：名称、base_url、model、api_key、备注 | P0 |
| FR-2.2 | api_key **加密落库**（Fernet/AES-GCM，主密钥来自服务端 `MASTER_KEY` 环境变量）；API 返回与前端展示一律掩码（如 `f464…moz`），永不回传明文、永不入日志 | P0 |
| FR-2.3 | 配置连通性预检：保存前/手动触发一次最小 chat 请求，记录成功与否与报错摘要（如模型名大小写错误、余额不足） | P0 |
| FR-2.4 | 运行时注入：发起 run 时，worker 子进程以环境变量方式注入该用户配置（`OPENAI_API_KEY` / `OPENAI_BASE_URL` / `OPENAI_MODEL`）。**机制修正（v1.1）**：主智能体 LLM 不是 `create_llm(config)` 造的——它从 profile YAML 的 `${OPENAI_*}` 占位符解析后 `create_react_llm(profile)`（`stateful_react_agent/profile.py:137`、`nodes/main_agent.py:623`）。`create_llm(config)` 在 `BenchmarkSession._bootstrap` 里只喂 `ResourceManager`（aux/摘要），不驱动主链路。**禁止部分注入**：三个变量必须全非空或全不注入，缺 `base_url` 会静默打到 `api.openai.com`（详见 tech-stack.md §5.3）。runs 表记录所用配置快照（含 model/base_url，不含 key）。env 经进程环境传递，不经 argv（防 ps 泄露） | P0 |
| FR-2.5 | 回退策略：用户未配置时使用系统默认（服务器 `server/config.env` 的 GLM 端点；**注意 v1.1 修正**：`.env` 路径由 `__file__` 推算、与 CWD 无关，且 `load_dotenv(override=False)` 保证注入值不被覆盖，理由不是"worker CWD=仓库根"）；配置失效的 run **直接失败**并给出可操作报错，不静默换用他人配置——worker 启动前断言三者全非空 | P0 |
| FR-2.6 | 可选高级参数：temperature、max_tokens、reasoning_effort（GLM 系支持 low/high/max），留空用 profile 默认 | P1 |
| FR-2.7 | 删除默认配置时自动指定其余配置之一或置空回落系统默认；删除前提示存在进行中 run | P1 |

### FR-3 对话与会话管理

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-3.1 | 会话 CRUD 与列表（按用户隔离，按更新时间排序）；会话标题自动取首条消息摘要 | P0 |
| FR-3.2 | 会话内多轮对话；每轮生成一条 run；同一会话串行执行（排队），跨会话并行 | P0 |
| FR-3.3 | **停止运行**：协作式停止（`metadata['pause_check']`），agent 在 turn 边界干净落地并回填已有部分答案。**`stopped_by` 来源修正（v1.1）**：它不在 `BenchmarkSession.run()` 返回的 pipeline state 里，而在 `AgentLoopResult.stopped_by`（`on_loop_end` 的 `result`）；平台需从 observer 捕获并与 worker 的 deadline/SIGKILL 路径合并落库（见 tech-stack.md §5.2）。~~运行中插话（steer）~~：**降级 P2**——复审确认 steer 为 apodex 应用层机制（`apodex/steer.py`），不在内核；Web 版待 P2 逆向其 Intervention 注入语义后实现。P1 的替代交互：停止 → 带上下文追问 | 停止 P0 / steer P2 |
| FR-3.4 | 产物文件列表与下载（限本会话 run 目录，防路径越界）。**前置约束（v1.1）**：产物依赖文件工具，而默认 profile（`default`/`benchmark`）的 `agent_tools` **不含** `read_file`/`create_file`，故 run 必须用 `tui` profile 或经 `profile_overrides` 下发 `agent_tools`（含文件工具）+ `fs_mode`（见 tech-stack.md §5.4） | P0 |
| FR-3.5 | 文件上传（财报 PDF、研报等）→ 注入 `FRONTIER_AGENT_INPUTS_DIR`（**v1.1 修正**：native 沙箱分支忽略 `_sandbox_mounts`，bind mount 仅 bwrap 分支生效；上传直接落 inputs 目录即可，再用 `_sys_prompt_addendum` 告知路径）；API 契约在 M2 前定稿 | P1 |

### FR-4 留痕与可追溯（本期核心）

留痕分五层，逐层递进可回查：

| 层 | 内容 | 载体 | UI 呈现 |
|---|---|---|---|
| L1 对话层 | 用户消息、最终回答、时间戳 | 业务库 turns 表（PostgreSQL） | 对话流 |
| L2 运行层 | 每轮 run 的状态机（queued/running/done/failed/stopped）、起止时间、所用 LLM 配置快照、停止原因 `stopped_by` | 业务库 runs 表 | 对话流中的运行状态条 |
| L3 过程层 | LLM 轮次、工具调用开始/结束与参数摘要、流式 delta | **运行时 `TrajectoryFileObserver`**（`run/agent/trajectories/react_agent.jsonl`，增量 flush、SIGKILL 安全、含参数/用量/system_prompt）+ 本平台 **BridgeObserver 仅做 delta 实时推送（不落盘）** + SSE 实时推送（**v1.1 修正**：不自建 `events.jsonl`，细节见 tech-stack.md §5.2/§6.2） | "运行详情"时间线面板 |
| L4 产物层 | `/outputs` 文件清单 + sha256 | 业务库 artifacts 表 + 文件系统 | 产物面板 |
| L5 诊断层 | `engine.log`、轨迹文件 | run_dir 文件系统 | 运维入口（P1：仅下载） |

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-4.1 | 任意历史轮次可打开"运行详情"：回放事件时间线（按 `react_agent.jsonl` 行号游标，断线可续） | P0 |
| FR-4.2 | 轨迹先落盘后推送：运行时每 record `flush()`，服务重启后历史 run 仍可完整回放（含 SIGKILL 中途 kill 的 partial） | P0 |
| FR-4.3 | 会话导出：Markdown（对话+回答）/ zip（对话+产物+轨迹 jsonl/json） | P1 |
| FR-4.4 | 删除会话 = 软删除，轨迹与日志保留期≥90 天（合规留痕） | P1 |

### FR-5 用量与成本归属

| 编号 | 需求 | 优先级 |
|---|---|---|
| FR-5.1 | 每 run 记录 token 用量（prompt/completion/total）。**来源修正（v1.1）**：不依赖另行注入的 UsageObserver——运行时 trajectory 的每轮 `llm` 记录已带 `usage{prompt,completion,cache_*}_tokens`，run 结束聚合进 runs 表即可（tech-stack.md §5.2） | P0 |
| FR-5.2 | 用户端"用量页"：按日/按配置聚合；本期只计量不计费 | P1 |

## 4. 数据模型（PostgreSQL 业务库，DDL 见 tech-stack.md §4.1）

```text
users(id, username, password_hash, status, created_at)
user_llm_configs(id, user_id, name, base_url, model, api_key_cipher,
                 params_json, is_default, last_verified_at, last_verify_ok,
                 created_at, updated_at)
sessions(id, user_id, title, deleted_at, created_at, updated_at)
runs(id, session_id, user_id, status, pipeline_id, prompt, final_answer,
     stopped_by, error, llm_config_id, llm_snapshot_json,
     prompt_tokens, completion_tokens, total_tokens,
     run_dir, created_at, started_at, finished_at)
turns(id, session_id, seq, role, content, run_id, created_at)
artifacts(run_id, rel_path, size, sha256, created_at)
audit_log(id, user_id, action, detail_json, ip, created_at)
```

事件轨迹（L3）不入业务库：以 `run_dir/run/agent/trajectories/react_agent.{jsonl,json}` 文件形式随 run 目录归档/导出/删除（运行时自带，非自建）。

## 5. API 契约（新增）

```text
POST /api/auth/register        {username, password}
POST /api/auth/login           → {access_token}
GET  /api/auth/me
GET/POST/PUT/DELETE /api/models/configs[/{id}]        # 返回中 api_key 恒为掩码
POST /api/models/configs/{id}/test                    # 连通性预检
POST /api/sessions                     {title}
GET  /api/sessions/{id}/turns
POST /api/sessions/{id}/runs           {message}      # → {run_id}，排队时 202
GET  /api/runs/{id}/events?after=<seq>                # SSE：replay + 增量
GET  /api/runs/{id}/trace?after=<seq>                 # 历史回放（同游标语义）
POST /api/runs/{id}/control            {action:"stop"}
GET  /api/runs/{id}/artifacts[/{path}]                # 列表 / 下载
GET  /api/usage/summary?from=&to=
```

既有 sessions/runs/artifacts 接口全部加用户归属过滤（非本人 404）。

SSE/UI 事件词汇（运行时自带轨迹记录类型 + 自研推送）：轨迹 `t` ∈ `start / llm / result / compaction`；实时推送事件：`run_started / assistant_delta / tool_started / tool_finished / run_completed / run_failed / run_stopped / artifact_created / warning`（delta 来自 BridgeObserver，其余生命周期事件可由平台补充在 SSE 层）。

## 6. 非功能需求

- **安全**：全接口 JWT 鉴权；key 加密存储；上传与下载路径校验；审计日志记录敏感操作（登录、配置增删改、key 轮换）；事件流中 key/secret 脱敏。
- **隔离**：用户 A 的会话、运行、产物、事件轨迹对用户 B 完全不可见（含报错信息不泄露存在性）。
- **可运维**：worker 崩溃不影响主服务（run-per-subprocess）；孤儿进程清扫；优雅停机 drain。
- **合规**：前端与研报模板固定"不构成投资建议"免责声明。

## 7. 验收标准（关键项）

1. 两个用户各自注册登录，互不可见对方会话与产物；
2. 用户配置一个错误 key/错误模型名 → 预检明确报错；改正后 run 正常且 runs 表快照记录正确 model/base_url；
3. 不配置 LLM 的用户可用系统默认模型完成一次完整投研问答；
4. 完成一轮对话后：turns 有问答记录、runs 有 token 用量与 stopped_by、运行详情可回放完整工具时间线（来自 `react_agent.jsonl`，含参数摘要）、产物可下载；
5. 服务重启后，历史 run 的"运行详情"仍可完整回放；
6. 数据库与 API 响应、日志中检索不到任何明文 api_key；
7. 前端展示"不构成投资建议"免责声明。

## 8. 开放问题

1. 注册是否需要管理员审批/邀请码，还是开放注册？（建议：P0 开放注册 + 邮箱留二期）
2. 是否允许多设备同时登录？（建议：允许，P1 再做会话管理页）
3. 用户级配置是否需要支持"按会话临时切换模型"？（建议：P1，schema 已预留）
