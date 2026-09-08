# 投研 Agent 平台 · 项目计划清单

| 项 | 内容 |
|---|---|
| 版本 / 状态 | v1.1 · 构建基线（随进度更新；已并入 M0.5 spike 实测结论） |
| 上游文档 | [requirements-user-layer.md](./requirements-user-layer.md) · [tech-stack.md](./tech-stack.md) |
| 状态图例 | ✅ 已完成 · 🔄 进行中 · ⬜ 未开始 · 🅿️ P2 暂缓 · ⛔ 阻塞 |

## 当前焦点

> **M2 全部完成，进入 M3 进行中**。M1 全部任务（T1.1–T1.12）已完成且**无阻塞项**；M2 十层（认证/存储/接口/注入/多轮/会话/停止/产物/上传/计量）+ 里程碑验收均已落地：T2.1 security.py（18 passed）、T2.2 routes/auth.py（21 passed）、T2.3 user_llm_configs 存储层（16 passed）、T2.4 routes/models.py（10 passed）、T2.5 LLM 注入链（10 passed）、T2.6 history.py 多轮回填（21 passed）、T2.7 routes/sessions.py + runs 鉴权与 Run 落库（12 passed）、T2.8 stop 控制链（2 passed）、T2.9 产物链（9 passed）、T2.10 文件上传契约定稿（5 passed）、T2.11 用量计量（10 passed）、**T2.12 M2 验收测试（4 passed）** 均通过。T2.12 四项验收：①双用户互不可见（跨租户全 404、列表零泄漏）；②错误 key 预检报错且可改正（同一端点改凭证即可过关，错误摘要无明文 key）；③重启后历史 run 可回放（引擎 dispose + Orchestrator 换新 + 新 client，trajectory 文件为唯一真源，计量随库留存）；④全库无明文 key（逐表逐行扫描 + 响应体只回 masked）。全量 `tests/` **1030 passed / 2 failed / 3 skipped**（最新全量实测）：失败的两 case 是 `tests/test_path_authorization.py::test_sandbox_search_branch_prunes_spill_unless_targeted[...]`，**已在 `git stash` 掉全部 T2.x 改动后的干净 `main` 上复现（全量 1 failed→即该用例两 parametrize）**，属预存在的测试隔离缺陷（单文件 39/39 全过、与 T2.x 改动无关），不阻塞 M2 交付。T2.11 计量口径为**聚合运行时 trajectory 每轮 `usage`**（不自写 Observer）：cache 读/写分开计量（计费倍率不同）、`update_run_usage` 不触碰 `finished_at`、重扫可复现同一数字（trajectory 是唯一真源）。注意：本地 `server/dev.db` 此前由 `create_all` 建立而无 alembic 版本记录，已 `alembic stamp 0001_initial` 后 `upgrade head` 至 `0002_run_usage`（生产环境直接走迁移即可）。tech-stack.md v1.2 的四处实质修正已回写进需求与计划。
>
> **M3 进展**：T3.1 web/ 骨架已完成——Vue3+Vite+TS+Pinia+Element Plus，`fetch+ReadableStream` 封装 SSE（Authorization 头 + `?after=seq` 游标重连 + 指数退避），`vue-tsc --noEmit` 0 错、`vite build` 通过；后端 `server/relay.py` 补 seq 游标（trajectory_tail 改产 `(i, rec)` 元组，`_traj_record_to_event` 带 seq）。T3.2 登录/注册页已完成（`LoginView.vue` 完整交互、401 跳转、错误分支）。T3.3 会话列表+对话流已完成（`SessionList.vue` + `stores/sessions.ts` + `ChatView.vue` 升级：消息流、markdown 渲染、工具卡片、运行状态条）。T3.4 模型配置页已完成（`ModelConfigsView.vue` 升级：CRUD 对话框、掩码显示、连通性预检、设默认）。T3.5 运行详情面板已完成（`RunDetailView.vue` + ChatView「详情」抽屉：trajectory 时间线回放 start/llm/result/compaction）。T3.6 产物面板+停止按钮已完成（`ArtifactPanel.vue` + 抽屉 tabs 整合 + 停止 loading/409/停止后刷新）。T3.7 合规与脱敏已完成（`DisclaimerBar` variant 覆盖登录页 + `utils/redact.ts` 密钥脱敏器接入全部 LLM 内容渲染路径）。T3.8 Caddy 上线已完成（`Dockerfile.frontend` + Caddyfile 静态托管/SPA fallback/关缓冲反代/HTTPS + compose 全栈编排 + 上线手册）。**M3 八项任务（T3.1–T3.8）至此全部完成**；剩余唯一未实跑项为 docker 镜像构建与 `caddy validate`，需有 docker daemon 的环境补齐（承 T1.10 环境限制）。

> **CLI → Web 复刻（设计稿，待评审）**：已产出 [cli-web-parity.md](./cli-web-parity.md)，以 `docs/tui-user-guide.zh-CN.md` + `apodex/` 为复刻基准，清出展示内容 17 项（8 项完全缺失）与业务流程 10 项（3 项完全缺失）的差距矩阵，并给出三阶段实施计划与「完美复刻」6 条判据。**评审已通过并进入实施。进度见** [.scratch/cli-web-parity/issues/](../../.scratch/cli-web-parity/issues/)。
>
> **阶段一（P1.1–P1.5 实时化）已完成**：relay 双源合并、orchestrator 订阅分发、worker stdout 帧泵、bridge 声明 `wants_llm_delta`、前端增量渲染与去重均已落地，实测单条短答复产生 118 个实时增量事件（思考逐 token 到达）。⚠️ **待补验证**：`vue-tsc --noEmit` 与 `vite build` 因环境拒绝执行命令未能跑通（[02](../../.scratch/cli-web-parity/issues/02-frontend-streaming.md)），合并前必须重跑；后端 `uv run ruff check server/` 已全绿。
>
> 已按阶段一 P1.1–P1.3 预先落下三处改动并**原样保留**作为起点：`server/bridge.py`（声明 `wants_llm_delta` 开启运行时流式 + 增量带 `turn`/`thinking_text`）、`server/worker.py`（`_bridge_pump` 把实时事件经 stdout 帧泵出 + `_drain_bridge` 排空）、`server/orchestrator.py`（`_subscribers` 订阅分发：`subscribe`/`unsubscribe`/`_publish`/`_close_streams`）。**现阶段无可见效果**——relay 双源合并（P1.4）与前端增量渲染（P1.5）未做，实时事件到不了浏览器；已验证语法与导入正常（`imports OK`）。遗留 2 处 ruff `UP037`（`server/worker.py` 我加的引号型标注），因 CI 仅 lint `frontier_agent/ apodex/ benchmarks/ workflows/ deploy/ tools/ scripts/`（不含 `server/`）故无 CI 风险，待实施时一并清理。
>
> **P0 投研内核与最小资料库（新焦点，优先于 M4）**：已产出 [p0-research-kernel.md](./p0-research-kernel.md)——架构评审决定先做 P0 再回 M4（理由见 `trading-strategy-platform-feasibility.md:271`：「若 P0 跑不通，投再多数据也救不回可信度」），范围为 **P0a** 计算内核（stub 研报）→ **P0b** 最小资料库（20 份真实研报）；`backtest_strategy`、向量检索、Discord / IMA 接入、全量 8000 份 ingest 均推后。**进度见** [.scratch/p0a-research-kernel/issues/](../../.scratch/p0a-research-kernel/issues/)。

---

## M0 基线（文档与决策）

| # | 任务 | 状态 | 产出 |
|---|---|---|---|
| M0.1 | 可行性评估 + apodex/FastAPI 链路复审（EventStore no-op、steer 降级、CWD 约束等修正） | ✅ | 复审报告（会话） |
| M0.2 | 用户层需求文档定稿 | ✅ | docs/requirements-user-layer.md（v1.1） |
| M0.3 | 技术选型与架构文档定稿（PostgreSQL + Docker + monorepo 决策固化） | ✅ | docs/tech-stack.md（v1.2，含 §5.4 profile/工具集契约、§5.2 事件持久化修正） |
| M0.4 | 项目计划清单建立 | ✅ | docs/plan.md（本文档） |

## M0.5 链路验证（spike，已完成）

| # | 任务 | 状态 | 产出 |
|---|---|---|---|
| M0.5.1 | `server/spike.py`：纯验证脚本（不写库/API/前端），覆盖全部 per-run 挂载点 | ✅ | server/spike.py |
| M0.5.2 | `server/verify_spike.py`：A1–A7 验收门禁，退出码即结论 | ✅ | server/verify_spike.py（实测：`--profile tui` 7/7，`--profile default` A2/A3 红可复现） |

> spike 结论驱动的改动：事件持久化不自建（→ 运行时 trajectory）；默认 profile 无文件工具（→ `tui`/`profile_overrides`）；native 忽略 `_sandbox_mounts`（→ 上传落 INPUTS_DIR）；`on_tool_call` 非 OpenAI 线格式（→ 参数取 trajectory）。详见 tech-stack.md §4/§5。

---

## M1 执行链路骨架（第 1 周）

**目标**：不鉴权、单会话，从 API 发起 run → SSE 实时 delta → 回放走运行时 `react_agent.jsonl`（**不自建 events.jsonl**）；worker 崩溃不影响主服务。

### 服务器骨架

| # | 任务 | 状态 | 要点 / 验收 |
|---|---|---|---|
| T1.1 | server/ 包骨架 + config.py | ✅ | pydantic-settings：端口、WORKER_POOL_SIZE（默认2）、WALL_TIMEOUT（默认900s）、MAX_TURNS、路径（runs/data）；**新增 `SANDBOX_BACKEND="native"` 与 `DEPLOY_DOCKERFILE` 引用说明** |
| T1.2 | store.py：DB 连接层 | ✅ | SQLAlchemy 2.0 async + asyncpg；启动健康检查；WAL 无关（Postgres） |
| T1.3 | Alembic 初始化 + 首版 migration | ✅ | users/sessions/runs/turns/artifacts/audit_log 全表（DDL 见 tech-stack §6.1；`run_dir` 注释指向 trajectories 子目录） |
| T1.4 | events.py：SSE 事件词汇（**仅推送层**） | ✅ | 删除"落盘 events.jsonl"职责；仅定义 `run_started/assistant_delta/tool_started/tool_finished/run_completed/run_failed/run_stopped/artifact_created/warning` 的 SSE 信封；回放数据从 trajectory 读（见 T1.9） |

### 执行链路（承重三件套）

| # | 任务 | 状态 | 要点 / 验收 |
|---|---|---|---|
| T1.5 | bridge.py：BridgeObserver（**仅 delta，不落盘**） | ✅ | 经 metadata['sdk_extra_observers'] 注入；只转发 `assistant_delta`/`tool_*` 生命周期到 stdout；**不写文件**（trajectory 由运行时自写）；运行时日志强制 stderr；事件经脱敏器；**钩子形状按扁平 `{id,name,args}` 处理，参数摘要不在此取**（tech-stack §5.2） |
| T1.6 | worker.py：子进程入口 | ✅ | CWD=仓库根；logging 重配；**启动预检（v1.1 新增，对应 tech-stack §5.2/§5.3）**：① 三 LLM 变量全非空否则拒绝；② `metadata['profile']` 或 `profile_inline` 必须存在；③ 全部 per-run 路径（FRONTIER_AGENT_{WORKSPACE,OUTPUTS,INPUTS}_DIR + CODING_WORKSPACE_ROOT + APODEX_SPILL_DIR + _trial_dir）指向 `runs/<run_id>/`；BenchmarkSession 引导（pipeline_id=stateful-react-agent）；**profile 走 `tui` 或 `profile_overrides`（含 agent_tools+fs_mode+thinking_format）**；pause_check deadline；stdin JSONL 控制通道（stop）；engine.log 落 run_dir |
| T1.7 | orchestrator.py：编排器 | ✅ | asyncio 子进程池 + 队列（会话串行/跨会话并行）；硬超时 SIGKILL 兜底；**全局模型并发闸门**（SpawnGuard 不经 BenchmarkSession 暴露，需自管，见 tech-stack 综述 S6）；start_new_session + 进程组回收（孤儿治理）；优雅停机 drain |
| T1.9 | relay.py：事件中继（**trajectory tail + SSE**） | ✅ | 实时：BridgeObserver stdout → asyncio 队列 → SSE；回放：**tail `run/agent/trajectories/react_agent.jsonl`**，按行号游标；背压：压力下只丢 delta，不丢生命周期事件（trajectory 里有完整 content 兜底） |

### API 与部署

| # | 任务 | 状态 | 要点 / 验收 |
|---|---|---|---|
| T1.8 | routes/runs.py（最小版） | ✅ | POST /api/runs（暂免鉴权）、GET /api/runs/{id}/events SSE（先 replay 后增量，断线凭游标续传，replay 源为 trajectory）、POST /control{stop} |
| T1.10 | deploy/ 骨架 | ✅ | **`deploy/Dockerfile.web`**（多阶段 uv，不可覆盖根 `Dockerfile`）；docker-compose.yml（postgres healthcheck 依赖、runs/ 持久卷、stop_grace_period=30s、SANDBOX_BACKEND=native 在 Dockerfile ENV 就位）、Caddyfile。验证：compose YAML 解析通过，api.build.dockerfile=deploy/Dockerfile.web、stop_grace_period=30s、runs/uploads 持久卷、postgres healthcheck+service_healthy 依赖均齐备；Dockerfile.web 含 SANDBOX_BACKEND=native 且多阶段构建（docker daemon 不在本环境，未做 build 实跑） |

### 测试与烟测

| # | 任务 | 状态 | 要点 / 验收 |
|---|---|---|---|
| T1.11 | 端到端 pytest（mock_llm） | ✅ | 指向 deploy/huggingface/mock_llm.py 假端点：发起 run → SSE 收到 delta/tool 事件 → **trajectory 可回放**（含参数/用量）→ **`verify_spike.py` A1–A7 作为 CI 门禁**；kill worker 主服务不倒。**实测结论**：`tests/test_web_m1.py` 2 passed（12.0s）；worker 子进程跑通 BenchmarkSession，`final_answer="Report written to /outputs/report.md."`，产物 `ws/outputs/report.md` 落 run 目录，trajectory 四类记录齐备（`start`/`llm`/`result`/`end`），`llm` 含完整 `tool_calls[].args`（path/content）与 `usage{prompt,completion,cache_*}_tokens`，`result` 含 `error=False`/`ms=61`；`/trace` 行号游标回放通过（游标越界返回 `[]`）；SIGKILL worker 后 `/healthz` 仍 200 且可接新 run；`_kill_handle` 的 SIGTERM/SIGKILL 升级路径单独验证通过（returncode=-15）；`verify_spike.py` A1–A7 **7/7 PASS**（含 A2 Go/No-Go 门与 A6 上游零污染）；`ruff check server/ tests/test_web_m1.py` 全绿。修复两个真 bug：`worker.py` 的 `_StopFlag` 缺 `stopped_by` 导致 summary 未落盘（AttributeError）、`orchestrator.py` 未 import `signal` 致 kill 路径 NameError |
| T1.12 | M1 烟测清单 | ✅ | ① spike `--profile tui` 7/7；② `spike --profile default` 须红；③ GLM 端点 smoke；④ .env 与 .gitignore 确认。**实测结论（真实端点 GLM-4.5-Flash @ open.bigmodel.cn）**：① mock 下 7/7 PASS（见 T1.11）；③ 真实端点下 A1/A2/A3/A4/A5/A7 **全绿，A2 Go/No-Go 门通过**（`2 call(s): read_file, create_file`，模型自主选对工具与参数、产物 `report.md` 落 run 目录、final answer 216 字符、71 事件游标稠密）；④ `.gitignore` 已补 `server/runs/`、`uploads/`、`server/*.db`（运行产物与本地库不再有入库风险）。**A6 红灯 = 误报**：捕获到的 `M apodex/agent_tools.py`（+19 行中文注释）经确认为**人工编辑**，非模型越界写入；A6 门只比对 git 快照差异，无法区分改动来源。tech-stack §7.2 的隔离假设**未被推翻**（静态反证见下方已撤销的 B1 记录）。**教训**：A6 门禁只报差异不定性，回滚操作须先经人工确认——本次误判已导致该人工改动被 `git checkout` 丢弃。② **已验证**：`spike.py --profile default` 下 A2/A3 双红（`tool calls raised: ['create_file']`），与 `--profile tui` 的 7/7 形成对照，证明 §5.4 的 profile 契约约束真实生效——`default`/`benchmark` 无文件工具，FR-3.4/3.5 在其下不成立，平台必须走 `tui` 或 `profile_overrides`（`server/profile.py` 采用 `PROFILE_NAME="tui"` + `build_profile_overrides()` 双保险）。四项烟测**全部完成**（③④ 见上，① 见 T1.11） |

### M1 阻塞项

无。此前登记的 B1 已撤销，见下方「已撤销记录」。

<details>
<summary>B1（已撤销）— 原题：「native 沙箱下模型可改写仓库源码」</summary>

**撤销原因**：A6 门捕获的 `M apodex/agent_tools.py`（+19 行中文注释）经确认为**人工编辑**，非模型越界写入。A6 门的实现（`verify_spike.py:129-157`）对比 spike 运行前后的 `git status --porcelain` 快照，**无法区分"模型改的"与"人在同一时间窗口内改的"**——本次正是后者（操作人员在 spike 跑批期间编辑了该文件）。当时误判并执行了 `git checkout -- apodex/agent_tools.py`，丢失了该人工改动；教训是**门禁只报差异、不定性，回滚类操作必须先与人工确认**。

**静态反证**（证明路径授权本身有效，模型写不了该文件）：
- `_path_auth.py:27-30` 的 `_ALLOWED_ABSOLUTE_PREFIXES` 仅含 `/tmp/agent-outputs/` 与 `plugins/skills/`；`_ALLOWED_RELATIVE_PREFIXES` 仅含 `plugins/skills/`、`data/`。`apodex/agent_tools.py` 不在任何允许前缀内。
- `_path_auth.py:300` 对位于服务检出目录内的（非隔离）workspace root 还会主动 `Refusing local write access`。
- 故 tech-stack §7.2「隔离由容器 + 路径授权 + 工具策略承担」的假设**未被推翻**，无需追加沙箱加固措施。

</details>

---

## M2 会话 · 多轮 · LLM 配置（第 2-3 周）

**目标**：双用户隔离；用户级 LLM 配置全链路（CRUD/预检/注入）；多轮上下文连贯；停止回填；产物下载。

| # | 任务 | 状态 | 要点 / 验收 |
|---|---|---|---|
| T2.1 | security.py | ✅ | argon2id 哈希；JWT(HS256, 24h) 签发/校验；登录限速（5次/10分钟）。**实测结论**：`tests/test_security_t21.py` **18 passed**（0.73s），`ruff` 全绿。实现要点：① argon2id（`argon2-cffi`，已加进 `web` 依赖组）用 `asyncio.to_thread` 卸载——argon2 单次约 50–100ms，同步调用会阻塞事件循环，测试含并发上界断言防回归；② JWT HS256/24h，签发与校验失败统一抛 `TokenError`（不区分过期/篡改，避免泄露 token 状态）；③ 登录限速 5 次/10 分钟，按用户名隔离、成功即清零、窗口过期自动解锁，懒清理防止用户名枚举撑爆内存；④ 顺带实现 FR-1.4 的登出吊销（短黑名单）。**修复一个真 bug**：吊销表最初以整串 token 的 sha256 为键，而同用户在同秒内签发的两个 token 字节完全相同（`iat` 为秒级），导致登出一个会话会连带踢掉另一个；改为签发时带唯一 `jti`、吊销表只存 `jti`（不存 token 本体），并补了对应用例 |
| T2.2 | routes/auth.py | ✅ | register/login/me/logout/password + audit_log 记录；`get_current_user` 鉴权依赖注入。**实测结论**：`tests/test_auth_t22.py` **21 passed**（3.4s），`ruff` 全绿。实现要点（含清单逐项核对）：① **FR-1.1 注册**：`/api/auth/register`（201），密码强度前置校验（`validate_password_strength`，含长度/大小写/数字）、非法用户名（`/`或不可打印）拒 400、重名 409；密码经 argon2id 落库（`$argon2id$` 前缀，无明文）；并写 `register` 审计行。② **FR-1.2 登录/身份**：`/api/auth/login` 签发 HS256/24h JWT（`expires_in=86400`），`/api/auth/me` 经 `get_current_user` 解析当前用户。③ **FR-1.3 限速**：复用 `security.LoginThrottle`（5次/10分钟、按用户名隔离、成功清零、锁定返 423），路由层在核验前先查锁。④ **FR-1.4 登出/改密**：`/api/auth/logout`（204）吊销 token `jti`（短黑名单，不存 token 本体）；`/api/auth/password`（204）校验原密码+强度后更新哈希。⑤ **全接口鉴权依赖注入**：`server/deps.py::get_current_user` 为唯一解析点，失败统一 401（不区分过期/篡改/吊销/删户，防账户枚举 oracle）；`[B008]` 已在 pyproject 对 `server/deps.py`、`server/routes/*.py` 豁免。⑥ **抗枚举**：登录对未知/禁用账号跑 dummy argon2 哈希保持时序对齐（未知用户名路径 >10ms，测试用例覆盖）；失败信息统一「用户名或密码错误」。⑦ **审计留痕**：`_audit()` 改为 `await`（非 fire-and-forget，防丢记录），覆盖 register/login/login_failed/logout/password_changed/password_change_failed，失败仅记日志不阻断主流程。**app.py 已 `include_router(auth_routes.router)`**；`/api/auth/*` 全部受 `get_current_user` 或公开语义保护。`routes/runs.py` 按 M1 约定暂免鉴权（依赖不可猜测 UUID、晚于账户体系），待 T2.7 会话引入时挂 `get_current_user`。 |
| T2.3 | user_llm_configs 存储层 | ✅ | Fernet 加解密（MASTER_KEY）；API 恒掩码返回；日志/响应无明文 key。**实测结论**：`tests/test_llm_config_t23.py` **16 passed**（0.65s），`ruff` 全绿。实现要点（含清单逐项核对）：① **Fernet 加解密**：新增 `server/crypto.py`（`encrypt_api_key`/`decrypt_api_key`/`mask_api_key`），密钥由 `ServerConfig.fernet_key` 从 `MASTER_KEY` 派生（SHA-256→base64，32字节）；存储列 `api_key_cipher` 为 `LargeBinary`，明文从不落库（测试断言 `plain.encode() not in cipher` 且列类型为 bytes）。② **API 恒掩码**：`_serialize_config()` 永远返回 `masked_api_key`（保留 `sk-` 前缀 + 末 4 位，隐藏中段），响应体无 `api_key` 原始字段名；解密仅用于掩码展示（`_decrypt_for_display`，失败回退空串），明文 key 不进日志/响应。③ **CRUD**：`create_llm_config` / `list_llm_configs` / `get_llm_config` / `update_llm_config` / `delete_llm_config` / `set_default_llm_config` 全部落 `store.py`，审计由 T2.4 路由层 await 写入（存储层预留 `write_audit_log` 复用）。④ **默认互斥**：任意 `is_default=True` 写入/更新/置默认前，先 `UPDATE ... SET is_default=False WHERE user_id=?`，保证每用户至多一个默认；`get_default_llm_config` 供 T2.5 注入链取默认。⑤ **删除保护**：删唯一默认被拒（`OnlyOneDefaultAllowed`）；删含其他的默认则把最新剩余项提升为默认；所有权校验（`_get_owned_config` 比对 `user_id`）拒绝越权读/改/删（IDOR 防护，测试 `test_user_cannot_access_another_users_config` 覆盖）。⑥ **明文泄漏面验证**：测试断言 DB 列非明文、列表响应不含明文、改密后掩码变化、密钥轮换后旧密文解密失败（`InvalidToken`），全链路无明文 key 出现。 |
| T2.4 | routes/models.py | ✅ | 配置 CRUD + POST /{id}/test 连通性预检（记录 last_verified_at/ok 与报错摘要）。**实测结论**：`tests/test_models_t24.py` **10 passed**（1.9s），`ruff` 全绿。实现要点（含清单逐项核对）：① **全路由鉴权**：所有 `/api/models` 路由声明 `get_current_user` 依赖，未带 token 一律 401（`test_all_routes_require_auth` 覆盖）。② **CRUD**：`POST /api/models`（201 创建，api_key 经 T2.3 Fernet 加密）、`GET /api/models`（列表掩码）、`GET /api/models/{id}`、`PUT /api/models/{id}`（可选字段补丁，api_key 更新即重加密）、`DELETE /api/models/{id}`（删默认保护沿用 T2.3 `OnlyOneDefaultAllowed`）。③ **API 恒掩码**：响应体仅含 `masked_api_key`，无 `api_key` 原始字段；更新后掩码随明文变化。④ **连通性预检** `POST /api/models/{id}/test`：进程内解密 api_key → 一次带 Bearer 的轻量 `GET {base_url}/v1/models`（10s 超时）→ 经 `store.record_verify_result` 记录 `last_verified_at`/`last_verify_ok` 与**无密钥**的错误摘要（存 `params_json._last_verify_error`，截断 500 字符）；返回 `{ok, detail}`，detail 永不含 key。⑤ **所有权隔离（IDOR）**：路由只传认证用户 id 给 store，越权读/改/删/测均 404（`test_user_cannot_access_others_config`、`test_preflight_forbidden_for_other_user` 覆盖）。⑥ **审计留痕**：create/update/delete/test 均 `await write_audit_log`（复用 T2.2 模式，失败仅记日志不阻断），`test_audit_rows_written` 校验四条 action 均落库。⑦ **路由注册**：`server/app.py` 已 `include_router(models_routes.router)`。预检出站请求在测试中用 `AsyncMock` patch，确定性无真实网络/LLM 配额消耗。 |
| T2.5 | LLM 注入链 | ✅ | orchestrator 解密默认配置 → worker env（OPENAI_API_KEY/BASE_URL/MODEL，不经 argv，**三者全非空或全不注入**）；未配置回落 server/config.env；启动预检拒绝部分注入；llm_snapshot_json 落 runs 表（不含 key）。**实测结论**：`tests/test_inject_t25.py` **10 passed**（0.52s），`ruff` 全绿；与 T2.2/23/24 全量回归 **57 passed**（5.4s）。实现要点（含清单逐项核对）：① **解密注入（不经 argv）**：`store.resolve_user_llm_env(user_id)` 取默认配置经 `get_decrypted_api_key` 解密，返回 `{OPENAI_API_KEY, OPENAI_BASE_URL, OPENAI_MODEL}`；`Orchestrator._resolve_llm_env` 在父进程解密后，仅通过子进程 `env=` 注入（`_launch` 的 `child_env.update(llm_env)`），**彻底移除 `--api-key/--model/--base-url` 的 argv 透传**（旧 `submit(model, base_url, api_key)` 明文参数已删除），杜绝 `ps` 泄露。② **三者全非空或全不注入**：`user_with_config` 部分缺失（model 空/解密失败）→ 返回 None → 不注入 → worker 回落 server `.env`；worker `_assert_llm_env` 仍保留 all-or-nothing 校验（任一缺失即 `SystemExit`）。③ **回落 server 默认**：`user_id=None` 或解析失败 → env 不注入，`worker.run_once` 从 `os.environ` 读 OPENAI_*，缺失时由 `load_dotenv` 填 server `.env`（tech-stack §5.3 override=False）。④ **worker 改造**：`run_once` 改从 env 读取凭证（argv 参数仅留作手动调试、编排器不再设置），`apply_env` 写入逻辑不变。⑤ **llm_snapshot 不含 key**：`store.build_llm_snapshot(user_id)` 返回 `{source, config_id?, model, base_url, last_verify_ok}`（无 api_key），供 runs 表 `llm_snapshot_json` 使用（Run 行持久化在 T2.7 会话路由落库，本任务已提供该能力）。⑥ **routes/runs.py 收敛**：`RunRequest` 移除明文 `api_key/model/base_url`，仅留可选 `user_id`（T2.7 会话体系接入后驱动默认配置解析），凭证永不经客户端。⑦ **容错**：`_resolve_llm_env` 捕获 store/解密异常 → 回落 None，绝不注入破损的部分集合。 |
| T2.6 | history.py 多轮回填 | ✅ | turns → render_session_history → workflow_input；run 后仅取 final_answer（含 final_content/partial 处理）写 assistant turn；不读 workflow 内部 messages。**实测结论**：`tests/test_history_t26.py` **21 passed**（0.52s），`ruff` 全绿。实现要点（含清单逐项核对）：① **session/turn 落库**：`store.py` 新增 `ensure_session`（幂等，按需建会话，T2.7 前自包含）、`append_turn`（自增 `seq`，可绑 `run_id`）、`list_turns`（按 seq 升序，`limit` 取最近 N 条）；`Turn`/`Session` 表已存在（M1 Alembic）。② **history 渲染**：新增 `server/history.py` 的 `render_session_history(turns)`，仅渲染 `user`/`assistant` 角色为 `## Conversation so far` 转录块，剔除 system/tool 等内部角色；空 turns 返回 `""`（调用方跳过前缀）；`turns_to_dicts` 把 ORM 行投影为 `{role,content}`。③ **注入 workflow_input**：`orchestrator._spawn` 渲染 prior turns 后写入 `run_dir/history.txt`（避免超长 argv），`worker.run_once` 读回并经 `BenchmarkSession.run(extra_input={"conversation_history":..., "is_multi_turn":bool})` 注入下一轮——**只注入服务器允许的对话历史，绝不读 workflow 内部 messages**。④ **当前轮排除**：渲染时剔除 `run_id==当前 run` 的 turn（即本次 user 提问），使 history 为前文、prompt 携带即时问题，避免重复。⑤ **final_answer 回填**：worker `run_finished` 帧现携带 `final_answer`；`orchestrator._pump_frames` 检测该帧后调用 `_backfill_assistant_turn`，**仅取 `final_answer`（回退 `final_content`/report/answer/output）** 写 assistant turn；partial（stopped_by/error 非空）答案仍落库并加 `_[partial: <reason>]_` 标记。⑥ **回归**：T2.6 21 passed + T2.2–T2.5 共 96 passed，原 M1 `test_web_m1` 因 `_launch` 未建 run_dir 写 history 而卡死，已补 `run_dir.mkdir(parents=True, exist_ok=True)`，全量 `tests/` 987 passed（修复前 3 个失败均为该卡死的连带）。 |
| T2.7 | routes/sessions.py | ✅ | 会话 CRUD + turns 查询；标题取首条消息摘要；用户归属过滤（非本人 404） + runs 路由挂 `get_current_user` 鉴权与 Run 行落库。**实测结论**：`tests/test_sessions_t27.py` **12 passed**（2.1s），ruff 全绿；M1 `test_web_m1.py`（2 passed）已补 `auth_headers` fixture 以适配 T2.7 鉴权。实现要点（含清单逐项核对）：① **会话 CRUD**：`server/routes/sessions.py` 提供 `POST/GET /api/sessions`、`GET /api/sessions/{id}`、`DELETE /api/sessions/{id}`（软删，置 `deleted_at`），全部声明 `get_current_user`，所有权在 `store.get_session`/`delete_session` 内以「非本人或软删即 404」强制（防 IDOR oracle：不区分存在/归属）；`app.py` 已 `include_router(sessions_routes.router)`。② **标题派生**：`store.derive_title` 折叠空白/换行并截断 60 字；创建时客户端未给 `title` 但有 `first_message` 则以其派生，否则默认「新对话」；`first_message` 同时作为首条 user turn 落库供历史渲染。③ **turns 查询**：`GET /api/sessions/{id}/turns` 经归属校验后返回按 `seq` 升序的 `{seq,role,content,run_id,created_at}`。④ **runs 路由鉴权（T2.7 收口 M1 暂免）**：`routes/runs.py` 全部路由（`POST /api/runs`、`GET /{id}/events`、`/trace`、`POST /{id}/control`）挂 `get_current_user`；`user_id` 恒取认证用户（客户端 `user_id` 字段被忽略，凭证仍由 store 默认配置服务端注入）；`_run_visible()` 以 `store.get_run` 做归属校验（非本人 404）。⑤ **Run 行持久化**：`store.create_run`（提交即写 `status=queued` + user_id/session_id/prompt/pipeline_id/run_dir）、`update_run_result`（run 终态写 status/final_answer/error/stopped_by/finished_at）；`orchestrator._pump_frames` 在 `run_finished` 帧调用 `_persist_run_result`（状态 completed/failed，partial 答案仍落库但保持非 completed，与 T2.6 assistant turn 标记一致），凭据与 prompt 永不回写。⑥ **归属隔离验证**：测试覆盖「Bob 看不到 Alice 会话/运行（均 404）」「列表仅含本人」「软删后对 owner 也不可见」。全量 `tests/` 1000 passed（仅 `test_path_authorization` 两 case 在全量并发跑时因共享端口/单例争用偶发失败，单独跑 39/39 全过，与 T2.7 代码无关）。 |
| T2.8 | stop 控制链 | ✅ | control 端点 → stdin → pause_check；partial answer 回填 + **`stopped_by` 从 observer 捕获 `AgentLoopResult`（非 pipeline state）并与 deadline/SIGKILL 合并落库**（tech-stack §5.2）；验收：停止后对话流显示部分结果。**实测结论**：`tests/test_stop_t28.py` **2 passed**（6.7s），ruff 全绿；`tests/test_sessions_t27.py` 12 passed（修正 1 处 T2.7 旧断言以适配 T2.8 的 `stopped_by→stopped` 语义）。实现要点（含清单逐项核对）：① **控制通道修复**：原 worker 用 `connect_read_pipe(sys.stdin)` 在 pytest 子进程下静默失效（stop 信号永不可达），改为**线程阻塞读 `sys.stdin`** 解析 `{"action":"stop"}`，可靠置 `_StopFlag.requested` 并经 `pause_check` 在 turn 边界协作停止（修复 T2.8 暴露的真 bug）。② **observer 注入**：worker 将 `BridgeObserver` 经 `metadata["sdk_extra_observers"]` 注入 loop（`bridge.py` queue 改为可选、capture-only），`on_loop_end` 捕获 `AgentLoopResult.stopped_by` 与 `final_content`（partial answer）——二者**只在此处可得**，pipeline state 不含（§5.2）。③ **stopped_by 合并**：`worker` 优先级 `user_stop`（stdin）> `deadline`（worker `asyncio.wait_for` 超时）> observer 捕获的 `paused/max_turns/context_limit`；帧经 `run_finished.stopped_by` 回传。④ **partial 回填**：`run_finished` 优先取 `state.final_answer`，否则回退 `bridge.final_content`（协作停止时的部分文本）；`_backfill_assistant_turn` 对 `stopped_by/error` 非空答案加 `_[partial: <reason>]_` 标记。⑤ **SIGKILL 兜底**：orchestrator 硬超时（`wall+grace`）触发 `_kill_handle` SIGKILL；`_pump_frames` 不再阻塞 `proc.wait()`，改由 `_spawn` 的 `finally` 在 SIGKILL 后调 `_synthesize_terminal_frame`——读 `summary.json` 兜底 partial，无 `run_finished` 时落 `stopped_by="sigkill"`，关闭 Run 行并回填 turn。⑥ **状态语义**：`update_run_result`/`_persist_run_result` 改为 `stopped_by` 非空即 `stopped`（原 T2.7 误用 `failed`），纯 `ok=False` 无 stop 才 `failed`。⑦ **验收通过**：端到端验证「发 stop 后 run 变 `stopped` + `stopped_by=user_stop` + 对话流出现 `_[partial: user_stop]_` 标记」，以及「SIGKILL 兜底 run 恢复为 `stopped` + `stopped_by=sigkill`」。 |
| T2.9 | 产物链 | ✅ | run 结束扫描 **`ws/outputs/`**（FRONTIER_AGENT_OUTPUTS_DIR，须嵌在 workspace 内）→ artifacts 表（size+sha256）；下载端点路径校验防越界。**实测结论**：`tests/test_artifacts_t29.py` **9 passed**（单元 1.1s + 端到端 2.8s），ruff 全绿；全量 `tests/` **1011 passed**（较 T2.7 基线 +11 = T2.8 的 2 + T2.9 的 9）。实现要点（含清单逐项核对）：① **扫描落点**：新增 `server/artifacts.py`，`outputs_dir_for()` 把「outputs 嵌在 workspace 内」这一布局事实编码在唯一一处（`<run_dir>/ws/outputs`，tech-stack §5.1-6）；`scan_outputs()` 在 run 终态遍历该目录产出 `{rel_path, size, sha256}`，`rel_path` 为 posix 相对路径（即 artifacts 主键与下载句柄）。② **扫描时机**：`orchestrator._spawn` 的 `finally` 中、worker 退出后（进程已不再写文件）调 `_record_artifacts()`；**stopped/failed 的 run 同样扫描**——部分产物也是用户应能下载的交付物。③ **落库**：`store.record_artifacts`（按 `(run_id, rel_path)` 主键 upsert，重扫更新 size/sha256 不产生重复行）、`list_artifacts`/`get_artifact` 均先校验父 run 归属（非本人返回空/None，无存在性 oracle）。④ **下载端点**：`routes/artifacts.py` 提供 `GET /api/runs/{id}/artifacts` 与 `GET /api/runs/{id}/artifacts/download?path=`，全部挂 `get_current_user`，非本人 run 统一 404。⑤ **路径越界防护**：`resolve_artifact_path()` 是**唯一**把不可信字符串变成文件系统路径的地方——拒绝绝对路径（含 `C:` 与 `//`）、`..` 穿越、NUL、指向 root 自身、目录、以及逃逸符号链接（`os.walk(followlinks=False)` 剪除符号链接目录，扫描阶段同样不记录）；穿越尝试返回 **404 而非 400**（不给探测文件系统布局的 oracle）。⑥ **测试覆盖**：size/sha256 正确性、空目录、逃逸符号链接不入库、6 类越界输入、upsert 去重、归属隔离、未认证 401、他人 run 404，以及端到端（真实 worker 写 `/outputs/report.md` → 扫描入库 → sha256 与磁盘一致 → 下载内容正确 → 三种穿越均 404）。**顺带修复两个真缺陷**：(a) SQLite 并发写 `database is locked`——`store.get_engine()` 对 SQLite 启用 `journal_mode=WAL` + `busy_timeout=10s`（PostgreSQL 生产无影响），此前 orchestrator 落 turns/runs、路由写 audit、启动 DDL 三者重叠即报错，T2.9 新增的 artifacts 写入把压力推过临界点而暴露；(b) 测试跨文件争用 orchestrator 单例并发槽（前一测试文件遗留的 run 占住唯一槽位导致新 run 永不启动），给 T2.8/T2.9 端到端测试加 `isolated_orchestrator` fixture 替换全局单例。 |
| T2.10 | 文件上传契约定稿 | ✅ | `POST /runs` 兼容 JSON 与 multipart（T2.7 旧 `json={"message"}` 契约不破坏）；multipart 文件落盘 `FRONTIER_AGENT_INPUTS_DIR`（native 分支即 `<run_dir>/inputs`，agent 经 `/inputs`/物理路径只读可见），受 `max_upload_bytes`(50MiB)/`max_upload_files`(20) 双限额约束（超额 413）；文件名 `_flatten_filename` 剥离 `/ \ .. :` 防越界；上传清单经 `prompt_addendum`→`--prompt-addendum`→worker `metadata["_sys_prompt_addendum"]` 告知 agent（含 `/inputs/<name>` 约定与 native 物理路径）。测试 `tests/test_upload_t210.py`（5 用例：落盘/超量/超大/穿越 flatten/端到端 agent 可见性） |
| T2.11 | 用量计量 | ✅ | 新增 `server/usage.py`：**聚合运行时 trajectory**（`run/agent/trajectories/react_agent.jsonl` 的每轮 `t=="llm"` 记录）而非自写 UsageObserver；`aggregate_usage()` 求和 prompt/completion/total/**cache_read**/**cache_write**/reasoning tokens（cache 读写**分开计量**，二者计费倍率不同，合并会低估 Anthropic 写入开销；缺失 total 时以 `prompt+completion` 推导；未报 usage 的轮次不计入 `llm_calls`；兼容 `cached_tokens`/`cache_creation_tokens` 旧别名）。runs 表新增 5 列（`cache_read_tokens`/`cache_write_tokens`/`reasoning_tokens`/`llm_calls`/`usage_json`）+ Alembic `0002_run_usage`；`orchestrator._record_usage` 在 worker 退出后（trajectory 完整时）落库，`update_run_usage` **不改动 `finished_at`**（重计量不得移动完成时间）。**实测结论**：`tests/test_usage_t211.py` **10 passed**（2.3s），ruff 全绿；全量 `tests/` **1050 passed**（+10）。顺带修复 T2.10 的一个**真 bug**：`isinstance(part, fastapi.UploadFile)` 恒为 False（Starlette 的 multipart 解析器实例化的是**基类** `starlette.UploadFile`），导致上传文件被静默丢弃；改为按基类判定后 `tests/test_upload_t210.py` **5 passed**。另修复 T2.10 测试自身的 httpx 用法 bug（`files=` 需 `(字段名, 文件元组)` 二元组）与 T2.5 契约回归（恢复 `RunRequest` 模型承载"不接受客户端明文凭证"的可验证契约） |
| T2.12 | M2 验收测试 | ✅ | 双用户互不可见；错误 key 预检报错且可改正；服务重启后历史 run 可回放；全库无明文 key（4 passed；全量下稳定性经修复 carol 默认 config 锁定 mock 后通过） |

---

## M3 Web 前端（第 3-4 周）

**目标**：Vue3 可用产品面——登录、会话对话、模型配置、运行详情回放、产物下载、免责声明。

| # | 任务 | 状态 | 要点 / 验收 |
|---|---|---|---|
| T3.1 | web/ 骨架 | ✅ | Vite+Vue3+TS+Pinia+Element Plus；fetch+ReadableStream 封装 SSE（Authorization 头 + `?after=seq` 游标重连 + 指数退避）；已实现并 `vue-tsc --noEmit` 0 错、`vite build` 通过；后端 `server/relay.py` 补 seq 游标（trajectory_tail 改产 `(i, rec)` 元组，`_traj_record_to_event` 带 seq） |
| T3.2 | 登录/注册页 | ✅ | token 管理（auth store 单源 + localStorage）、401 跳转（`setUnauthorizedHandler` 路由守卫）、错误提示（`ApiError.code` 分支：401/409/423/400/0）。`LoginView.vue` 升级：前端镜像校验（用户名 3-64、密码 8+ 含字母数字）、注册 `autocomplete=new-password`、423 锁定倒计时、用户名占用切登录、注册成功自动登录；`auth.ts.login` 在 `/auth/me` 失败时清 token 防僵尸会话。`vue-tsc --noEmit` 0 错、`vite build` 通过 |
| T3.3 | 会话列表 + 对话流 | ✅ | 会话列表侧边栏（`SessionList.vue` + `stores/sessions.ts`：list/create/remove/select/loadTurns，移动端抽屉化）；消息流（`ChatView.vue`）：用户气泡 + 助手消息 `markdown-it` 渲染（DOMPurify  sanitize 防 XSS）+ 工具调用卡片（tool_started/finished 聚合）+ 运行状态条（queued/running/completed/failed/stopped 标签 + 停止/重试按钮）；复用 T3.1 的 `runStream` SSE 订阅与 `runs.submit`/`runs.stop`。`vue-tsc --noEmit` 0 错、`vite build` 通过 |
| T3.4 | 模型配置页 | ✅ | `ModelConfigsView.vue` 升级为完整 CRUD：新增/编辑对话框（name/base_url/model/api_key/params JSON/is_default，表单校验；编辑模式留空 key=保留原 key）、删除二次确认、行内「预检」（`models.test` 连通性，detail 不含明文 key）、「设默认」（`models.update(id,{is_default:true})`）、`last_verify_ok` 状态标签；掩码 key 仅显示 `masked_api_key`，无任何回显明文路径。`vue-tsc --noEmit` 0 错、`vite build` 通过 |
| T3.5 | 运行详情面板 | ✅ | `RunDetailView.vue`（drawer 内嵌于 ChatView「详情」按钮）：调 `runs.trace(runId)` 回放 `react_agent.jsonl`，按 `t=start/llm/result/compaction` 渲染时间线（模型/工具集/max_turns、轮次+assistant 内容(markdown 渲染)+tool_calls+usage、工具结果成功/失败/耗时、上下文压缩）；404→无权限提示、空→空态；内容经 `renderMarkdown` DOMPurify 防 XSS。新增 `RunTraceRecord`/`RunTraceResponse` 类型、`api.trace` 返回类型化。`vue-tsc --noEmit` 0 错、`vite build` 通过 |
| T3.6 | 产物面板 + 停止按钮 | ✅ | `ArtifactPanel.vue`（产物列表：文件名/大小/sha256 前 12 位/时间，刷新按钮，空态与 404→无权限错误态；下载走 `api/artifacts.download` 鉴权 blob 路径，`rel_path` 服务端权威不做二次清洗）；停止交互增强：按钮 loading 防重复点击、409「该运行已结束」提示而非静默成功、停止后 1.2s 延迟刷新产物与轨迹面板（worker 关机时会落盘产物）；详情抽屉改为 `el-tabs`（轨迹回放 / 产物）。`vue-tsc --noEmit` 0 错、`vite build` 通过 |
| T3.7 | 合规与脱敏 | ✅ | ①免责声明：`DisclaimerBar.vue` 加 `variant='banner'\|'inline'`，登录页（AppShell 之外）补 inline 声明，实现"每屏必带声明"且文案单点定义（强制常量非 prop，防调用方省略）；②脱敏：新增 `utils/redact.ts`（`redactSecrets`/`redactDeep`，覆盖 sk-/Bearer/AWS/GitHub/vendor 前缀与 `api_key=...` 赋值四种形态，保留 4 位前缀便于识别、无误伤 gpt-4o 等）；应用于 `renderMarkdown`（助手消息、轨迹 assistant 内容，先脱敏再渲染防止密钥被烘进 href/src）、`RunDetailView`（tool_calls args/result 深度脱敏）、`ChatView`（用户消息、工具卡片名）。实录冒烟：sk/aws/github 均掩码、Bearer 与赋值保留上下文、gpt-4o 与 temperature 无误伤。`vue-tsc --noEmit` 0 错、`vite build` 通过 |
| T3.8 | Caddy 上线 | ✅ | 静态托管+反代关缓冲+HTTPS+compose 全栈拉起。新增 `deploy/Dockerfile.frontend`（node:20-alpine 构建 `web/dist` → alpine 产物镜像，与 API 镜像分离，避免 node 工具链污染 agent 运行时镜像）；`Caddyfile` 由占位改为真实站点：`/api/*` 反代 `api:8000`（`flush_interval -1` 关缓冲、`transport http` 读写超时 7200s 容忍 token 间隙、`X-Accel-Buffering: no` 兼容 nginx 语义中间层），`/*` 静态托管 `/srv/web`（`/assets/*` immutable 长缓存、其余 `no-cache`、`try_files {path} /index.html` SPA fallback）；`SITE_ADDRESS` 默认 localhost 自签、设真实域名即自动 ACME 续期。`docker-compose.yml` 增 `frontend` 服务（发布 dist 到 `web_dist` 卷后退出）+ `caddy`（`service_completed_successfully` 等待构建完成、只读挂载 `web_dist`），防止站点在空目录状态启动；补 `deploy/README.md` 上线手册与 `web/.dockerignore`。校验：compose YAML 解析、服务与卷引用一致、依赖条件正确、Caddyfile 括号配对与关键指令齐备、`vite build` 产出 `index.html`+13 assets、`ruff check deploy/` 通过。**未实跑**：本环境无 docker daemon（承 T1.10 限制），`docker compose config` / `caddy validate` / 镜像 build 待有 daemon 的环境验证 |

---

## M4 金融工具与投研闭环（第 4 周后）

**目标**：stub 数据源跑通投研问答；换真实源零改 Web/Agent 层。

| # | 任务 | 状态 | 要点 / 验收 |
|---|---|---|---|
| T4.1 | plugins/market/base.py + stub.py | ⬜ | MarketDataSource 协议（kline/financials/announcements/news）；确定性 mock CSV |
| T4.2 | tools.py 工具注册 | ⬜ | @tool 四件套；plugins/tools/__init__.py 的 `_BUILTIN_TOOLS` 注册（+2 行，**同步改 `tests/test_tool_registry.py::EXPECTED_TOOLS`**）；**可见性经 `profile_overrides["agent"]["agent_tools"]` 从 server 下发，不落上游文件**（tech-stack §5.4） |
| T4.3 | 投研 prompt/profile | ⬜ | **走 `metadata["profile_inline"]`**（不落文件到 `workflows/`，零上游改动、天然 bypass_cache）；`server/profile.py` 定义投研 PROFILE_OVERRIDES（agent_tools 含文件+市场工具、fs_mode=true、thinking_format=tag）；验收：agent 调用 mock 工具产出带引用的投研问答 |
| T4.4 | 用量页（P1 项） | ⬜ | 按日/按配置聚合展示（只计量不计费） |
| T4.5 | akshare.py 真实源 + DuckDB 缓存 | 🅿️ | factory 替换 stub；定时抓取（cron 级，日频定位）；不被 P1 阻塞 |

---

## P2 暂缓清单（记录在案，不进当前排期）

| 项 | 依赖 / 触发条件 |
|---|---|
| steer 运行中插话 | 逆向 apodex/steer.py 的 Intervention 注入语义并验证；主链路稳定后 |
| 审批仲裁器（挂起→卡片→放行） | 交易场景需求确认后 |
| 多实例 SSE 分发（Postgres LISTEN/NOTIFY 或 Redis） | 单实例并发不足时 |
| sidecar 沙箱强化（gVisor/kata） | 运行不受信第三方代码需求出现时 |
| workflows/investment_research 多智能体投研工作流 | agent_team 编排质量实测达标后 |
| 会话导出 / 邮箱验证 / SSO / 多设备管理 / 按会话切模型 / 计费 | 对应 FR 优先级升级时 |

---

## 进度规则

1. 每完成一项任务即更新本文档状态标记，并在任务行补一句实际结果（如烟测数据）；
2. 出现阻塞时标记 ⛔ 并在行内注明阻塞原因与解除条件；
3. 里程碑验收 = 该里程碑全部测试任务（T1.11/T1.12、T2.12、T3.x 验收列）通过；
4. 范围变更需回写 requirements/tech-stack 文档后再改本清单。
