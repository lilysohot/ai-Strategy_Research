# Web 业务资料专项 · 环境基线与验证入口（DATA-00）

| 项 | 内容 |
|---|---|
| 版本 / 日期 | v0.2 · 2026-10-08；表头状态回填（正文 §1、§4.x 保留原日期快照，不追溯改写） |
| 状态 | 台账与入口已建立；独立测试库与受限角色已建立并逐批复用（见 §4.1），**后台受管进程仍未建立**（要求见 §5）；不作为就绪声明 |
| 需求依据 | [产品需求](../product-requirements.md) PR-BIZ-01—06、PR-WATCH-01—04、PR-DATA-13 |
| 任务依据 | [持久化任务清单](web-business-persistence-tasks.md) DATA-00；[页面任务清单](web-business-ui-tasks.md) UI-01—11 |
| 关联 | [环境准备与执行边界](web-storage-validation-environment.md)（沿用其 E0—E4 分级与隔离规则） |
| 观测方式 | 只读：进程/端口列表、`/readyz`、`docker exec` 下的 PG 元数据查询、配置文件读取；未建表、未迁移、未改动业务数据 |

本文只记录“当天的环境是什么、验证从哪个入口进入”。它替代不了 E1/E2 的真实链路验收，
也不代表运行中的服务加载了当前 HEAD 的代码。

## 1. 2026-10-02 当日台账

| 对象 | 观测结果 | 证据命令 |
|---|---|---|
| 代码基线 | HEAD `d05df22`（2026-10-02 20:15:12 提交，工作区干净） | `git rev-parse HEAD` |
| API 进程 | **WSL Ubuntu**：`uv run --group web uvicorn server.app:app --host 0.0.0.0 --port 8000`（PID 66260，观测时已运行 8h46m）；单进程、无 `--reload` | `wsl -d Ubuntu -- ps -eo pid,etime,cmd` |
| 前端进程 | WSL 内 `npm run dev --host 0.0.0.0`（PID 66262）；Windows 侧 8000/5173 由 `wslhost`（PID 10352）转发 | 同上 + `Get-NetTCPConnection -State Listen` |
| 就绪信号 | `/readyz` → `{"status":"ok"}`；`/healthz` → `200` | `Invoke-WebRequest http://127.0.0.1:8000/readyz` |
| 业务库 | 容器 `pg`（镜像 `pg18-zhvector`），宿主 5432；库 `apodex`、角色 `postgres`；**PostgreSQL 18.6** | `docker exec pg psql -U postgres -d apodex -tAc "select current_database()||..."` |
| Schema | `alembic_version = 0004_control_records`（与代码 head 一致）；`public` 下 10 张表，**无任何业务表** | `select version_num from alembic_version;` `pg_tables` |
| 业务数据量 | users 33、sessions 145、turns 1108；runs：completed 85 / failed 214 / stopped 463 → **当前无 queued/running** | `select status,count(*) from runs group by status;` |
| 运行数据根 | 未设 `SERVER_RUNS_ROOT` → POSIX 默认 `/home/administrator/.local/share/frontier-agent/web/runs`，**源码树外**（F01 目标已达成），255 个 Run 目录 | `wsl -d Ubuntu -- ls ~/.local/share/frontier-agent/web` |
| 上传落点 | 无独立上传根配置，上传写入本次 Run 目录的 `inputs/`（见 `server/routes/runs.py`） | 源码核对 |
| 磁盘 | WSL 根文件系统 1007G 总 / 877G 可用 | `df -h ~` |
| 配置与密钥 | `.env`：`SERVER_DATABASE_URL=postgresql+asyncpg://postgres:***@localhost:5432/apodex`、`SERVER_DEBUG=true`；**未设** `SERVER_RUNS_ROOT` / `SERVER_UPLOADS_ROOT` / `SERVER_MASTER_KEY` / `SERVER_PORT` | `.env` 键名读取（密钥值不入库） |
| 模型出口 | `OPENAI_BASE_URL=https://ark.cn-beijing.volces.com/...`、`OPENAI_MODEL=glm-5.3-flash` → 测试必须限制到 loopback mock | `.env` |
| 后台常驻进程 | **不存在**：`server/` 内无 dispatcher / monitor / scheduler，无 systemd/compose 常驻服务；编排全在进程内存 | 源码检索 |
| 前端业务模块 | `web/src/components/business/*` 为前端预览（无 API 调用、无 wire 类型），导航已在 `business-ui.ts` 注册 | 组件源码 |

### 1.1 与历史记录的差异（旧观测不能直接复用）

| 历史记录（2026-09-30 E0 / E1） | 当日观测 | 含义 |
|---|---|---|
| API 为 Windows 原生 `.venv` 进程 | WSL Ubuntu + `uv run --group web` | 解释器、PATH、子进程继承方式全部不同；E1 的“本机缺 `os.getpgid`”结论不覆盖当前环境 |
| 运行根在源码树内（`server/runs`、`uploads/`，F01 未修复） | 源码树外用户数据目录，255 个 Run 目录 | 目录整改已生效；迁移类结论需重新核定，不得沿用“源码树内”表述 |
| Alembic `0002_run_usage` | `0004_control_records` | 期间已执行迁移；新迁移必须挂在当前 head 之后 |
| runs 1263（无 queued/running） | runs 762（无 queued/running） | 数据量已变化（存在清理），跨批次比较需以当日查询为准 |
| 无 Web 业务前端组件 | 6 个业务组件已提交（预览态） | 页面开发基线变化：后续工作是“接真契约”，不是从零搭建 |

### 1.2 当日判定

- **运行代码 ≠ 当前 HEAD**：进程启动早于 `d05df22` 提交时间。任何基于 `server/` 改动的验证，都必须先重启该服务或使用独立第二 API，不能把这次观测当作“新代码已生效”。
- **`SERVER_DEBUG=true` 使启动就绪门禁降级为警告**，且 `SERVER_MASTER_KEY` 仍是开发默认值。`/readyz` 200 **不能**证明生产就绪，也不能证明加密（DATA-14）可用。
- 当前无活跃 Run，孤儿恢复误伤风险为 0；但**每次启动第二 API 前必须重查**（`runs` 中 queued/running 行数）。
- 历史上“本机（Windows 原生）”的进程级阻断（无 `os.getpgid/killpg`）在当前 WSL 部署下不适用；工具/产物类用例可在 WSL 复核，但不能据此宣称跨平台缺陷已修复。

## 2. 隔离规则（沿用并收紧）

| 规则 | 要求 |
|---|---|
| 只读与正常流程 | 复用现有 WSL 服务与 `apodex` 库；两个专用测试账号；并发从 1 开始；只用合成输入 |
| 第二 API / 改动版 | 必须**先**准备同 PG 实例下的独立测试库 + 受限角色 + 独立数据根 + 按需端口，**再**启动；不得先启动再改配置 |
| 禁止 | 第二 API 连接 `apodex`；只换端口或只加测试账号；在业务库试跑 `create_all`/Alembic；把测试资金写成真实用户已确认事实 |
| 模型出口 | 测试账号默认模型指向 loopback mock（`127.0.0.1:8899` 一类），不得触达 `ark` 等真实供应商 |
| 浏览器 | 独立浏览器上下文/配置；cookie 不按端口隔离；验收以真实网络请求为准，不看启动日志 |
| 故障域 | 实例/卷级故障（E3）才另建独立 PG 实例；不顺带升级 PostgreSQL（当前 18.6） |

## 3. 备份与清理清单（每批执行前登记）

| 类别 | 内容 |
|---|---|
| 备份对象 | 业务库 `apodex`（逻辑备份，含 `alembic_version`）、WSL 运行数据根 `/home/administrator/.local/share/frontier-agent/web`、`.env` 之外的密钥（`SERVER_MASTER_KEY`/`SERVER_JWT_SECRET`）、测试库 |
| 登记项 | 批次号、测试账号、会话/Run ID、文件清单与校验值、端口/进程、测试库名、模型来源、执行命令 |
| 清理 | 只清理本批登记对象：测试库、测试 Run 目录、测试账号（按登记清单）；不删整个 `runs`、不按模糊名杀进程、不删其他环境使用的卷 |
| 敏感 | 令牌/密钥不写入报告与日志；日志不写完整资金与持仓正文（DATA-14） |

## 4. 显式 PostgreSQL 集成入口

`tests/conftest.py` 的 `_isolated_database` 会把 `tests/` 下所有用例强制切到临时 SQLite，
常规 pytest 因此不能证明精度、事务、唯一约束和并发行为。`tests/pg/` 是显式入口：

| 文件 | 作用 |
|---|---|
| `tests/pg/conftest.py` | 入口门禁 + 覆盖 SQLite 夹具 + Alembic 到 head + 逐用例 `TRUNCATE` |
| `tests/pg/test_pg_baseline.py` | 基线四项：目标库防护、schema head、NUMERIC 往返、事务回滚（分别对应 DATA-00/02/02/06 前提） |

门禁行为（已实测）：

- 未设 `PG_INTEGRATION=1` → **跳过**（`4 skipped`），不静默回退 SQLite；
- 已启用但 dialect 非 postgresql、库名与 `PG_BUSINESS_TEST_DB` 不一致、命中受保护库（`apodex`/`postgres`/`template*`）、库名不以 `_test` 结尾或 `test_` 开头 → **立即失败**；
- 迁移未达 head → 会话级失败，不带着旧 schema 继续。

运行方式（先由运维/用户批准建库）：

```bash
# 1) 建库与受限角色（独立测试库，禁止在 apodex 上执行）
docker exec -it pg psql -U postgres -c "CREATE ROLE biz_test LOGIN PASSWORD '<本批口令>';"
docker exec -it pg psql -U postgres -c "CREATE DATABASE apodex_biz_test OWNER biz_test;"
docker exec -it pg psql -U postgres -d apodex_biz_test -c "REVOKE ALL ON DATABASE apodex FROM biz_test;"

# 2) 运行集成入口
PG_INTEGRATION=1 \
PG_BUSINESS_TEST_DB=apodex_biz_test \
SERVER_DATABASE_URL='postgresql+asyncpg://biz_test:<本批口令>@localhost:5432/apodex_biz_test' \
SERVER_RUNS_ROOT=/tmp/frontier-agent-biz-test/runs \
uv run pytest tests/pg -q -m pg
```

`SERVER_RUNS_ROOT` 必须同时导出：`server/worker.py` 由子进程自行推导 Run 目录，
只改父进程配置对象无法传递给 worker（父子进程配置一致规则）。

### 4.1 本批登记（2026-10-02，已获授权执行）

| 项 | 值 |
|---|---|
| 批次 | `bizdata-20261002-01` |
| 测试库 | `apodex_biz_test`（同一 PG 实例，宿主 5432，容器 `pg`） |
| 角色 | `biz_test`（LOGIN，本批口令不在文档中登记；拥有 `apodex_biz_test`） |
| 权限边界 | 已执行 `REVOKE ALL ON DATABASE apodex FROM biz_test`；入口额外拒绝 `apodex`/`postgres`/`template*` |
| 迁移 | `0001 → 0009_run_uploads`（入口自动执行 `alembic upgrade head`） |
| 执行 | `PG_INTEGRATION=1 PG_BUSINESS_TEST_DB=apodex_biz_test SERVER_DATABASE_URL=postgresql+asyncpg://biz_test:***@localhost:5432/apodex_biz_test uv run --extra dev --group web pytest tests/pg -q -m pg` |
| 结果 | **65 passed**（DATA-00 基线 4 项 + DATA-02 业务对象 7 项 + DATA-03 写入服务 13 项 + HTTP 路由 9 项 + DATA-05 快照 13 项 + DATA-06 派发/附件/队列 19 项） |
| 编排器 | PG 用例把 `get_orchestrator` 换成记录桩（`tests/pg/conftest.py::StubOrchestrator`）：验收的是持久化与快照，不派生真实 worker 子进程 |
| 回归对比 | 在 HEAD 干净副本（临时 worktree）上跑 `tests/test_web_p2_files.py` + `test_web_p3_revert.py` 得 9 failed/13 passed/6 errors，与当前工作区**完全一致** → 这批失败是 Windows 原生环境的既有现象（worker 进程组、符号链接），非本次改动引入；相关用例仍需按 §2.2 在 WSL 复验 |
| 清理 | 本批结束按 §3 清理；测试库与角色保留至 DATA-03 复用，口令只在本批有效 |

已取得的真 PG 证据：金额列为 `NUMERIC(30,10)`、比例列为 `NUMERIC(20,10)`；
`1234567890.1234567890` 与 `0.0000000001` 写入后逐位回读一致；缺失资金为 `NULL` 而非 0；
重复 `(account_id, revision)` 被唯一约束拒绝；跨研究主计划与跨用户账户被复合外键拒绝；
成交更正保留原行与前值。

### 4.2 核查修复批次（2026-10-03）

本批仅核查和修复已执行范围，不把 DATA-07/08 或前端预览计为已交付。
执行记录见 [修复 issue](../../.scratch/web-business-repairs/issues/01-audit-fixes.md)。

| 项 | 本批证据 |
|---|---|
| 源码 | WSL `/home/administrator/FrontierAgent`；不是 Windows 中的另一 checkout |
| 隔离 PG | 临时容器 `frontier-business-repair-20261003`，复用本机 `pg18-zhvector` 镜像；独立库 `frontier_business_test`、角色 `business_test`，不改现有 `pg`/语料库实例；仅发布 127.0.0.1 随机端口 |
| 迁移 | 空库升级至 `0010_business_history`；带账户/计划版本与 Run 快照执行 `0010 → 0009 → 0010`，逐表内容摘要保持一致，升级后 UPDATE/DELETE 拒绝 |
| PG 回归 | `uv run --no-sync pytest tests/pg -q --tb=short`：**95 passed**（原 65 项 + 本批 30 项）；仍使用记录型 orchestrator |
| 失败复现 | 首批新增用例在修复前为 15 failed / 3 passed；补齐状态与成交更正的 3 项补充用例亦先失败后通过 |
| 既有 Web 回归 | WSL 运行 `test_web_m1.py`、`test_web_p2_files.py`、`test_web_p3_revert.py`、`test_upload_t210.py`、`test_stop_t28.py`：**37 passed**；修正预览夹具漏建 Session 的 6 项 setup error |
| 前端 | Node 22：vue-tsc、Vite build 通过；现有单测 **74 passed**。Playwright + Edge 独立上下文验证账户离开取消/确认、切研究前拦截、计划关闭取消/确认及研究间草稿隔离、375px 草稿保护 |
| 浏览器范围 | `web/tests/business-drafts.cjs` 使用隔离 API fixtures，验证真实 Vue 交互；不能代替真实业务 API/worker 联合验收 |
| 仓库门禁 | Ruff 通过；import_smoke stage 1：379/379，stage 2：428/428；check_symbols：478 文件无缺失；preflight 真实模型单次调用通过 |
| 文件隔离修复 | PG fixture 现在为每项用例设置独立 runs_root 并导出给子进程。早期两批遗留的 22 个已核实测试目录，在只读查询确认无业务 Run 关联后，移至 `/tmp/frontier-business-repair-orphans`；未删除用户运行资料 |
| 清理 | 本批临时 PG 容器已停止并自动删除，临时口令文件已移除；原有业务/语料库容器保持原状。脱敏 PG 结果保存在修复 issue 的 `evidence/` 目录 |

本批没有部署 API，也未对业务库执行迁移。前端账户与计划仍属交互预览；持久补数、
worker 消费业务快照/工具接线、真实浏览器 + API + worker 联合验收仍按 DATA-07/08/15 跟进。

### 4.3 DATA-07 持久补数批次（2026-10-03）

执行记录见 [DATA-07 issue](../../.scratch/web-business-repairs/issues/02-data07-input-requests.md)。

**修复复验：通过。** 后续审计发现的 8 项遗漏已全部关闭，见[复核报告](../../.scratch/web-business-repairs/data07-acceptance-review.md)。

| 项 | 本批证据 |
|---|---|
| 隔离环境 | 临时容器 `frontier-business-data07-20261003`；独立库 `frontier_business_test`、角色 `business_test`、`127.0.0.1` 随机端口及 `/tmp/frontier-business-data07-runs`；现有 `pg`/`corpus-db` 未改 |
| 迁移 | 测试库升级至 `0012_business_events`；新增 `0011_input_requests` 和 `0012_business_events`；既有迁移降级/升级往返继续通过 |
| PG 回归 | `uv run --no-sync pytest tests/pg -q --tb=short`：**112 passed**；DATA-07 定向 **17 passed**，含停止、终态竞争、字段撤回和事件游标并发回归 |
| 前端 | Node 22：74 项单测、vue-tsc、Vite production build 通过；构建仅保留既有大 chunk 提示 |
| 浏览器 | Playwright + 真实 FastAPI + 隔离 PG；覆盖 100 条以上分页、详情迟到响应、跨研究指定请求定位、部分回答、唯一续接、原快照不变和通知已读持久化 |
| 通知范围 | B 阶段仅接入补数创建/回答生产者；无事件清理时游标不会过期，`cursor_expired=false`；监控事件及保留策略留待 DATA-12 C |
| 部署 | 未部署 API，未迁移生产库；测试结束停止临时 API/PG 并移除临时口令文件 |

历史 PG 日志保存在 `.scratch/web-business-repairs/evidence/data07-pg.log`；修复后独立并发审计保存在 `.scratch/web-business-repairs/evidence/data07-post-fix-audit.log`。

### 4.4 DATA-08 业务上下文与工具接线批次（2026-10-03）

执行记录见 [DATA-08 issue](../../.scratch/web-business-repairs/issues/03-data08-business-context-tools.md)，
脱敏结果见 `.scratch/web-business-repairs/evidence/data08-validation.log`。

| 项 | 本批证据 |
|---|---|
| 隔离环境 | 临时 PostgreSQL 15 容器 `frontier-business-data08-test`；独立库 `frontier_business_test`、角色 `business_test`、`127.0.0.1` 随机端口及 `/tmp/frontier-business-data08-test-runs`；未连接或迁移现有业务库 |
| 认证与冻结 | resolver 查询同时约束 Run、快照与认证用户；当前账户/计划修改后旧 Run 仍返回原快照，清空进程缓存后从 PG 重建的摘要和值完全一致 |
| 最小权限 | 父进程物化用途所需字段；worker 环境将 `SERVER_DATABASE_URL` 固定为私有内存库并移除 Docker DSN，不继承平台数据库凭据 |
| 模型边界 | 固定规则进入 system addendum，动态快照作为转义后的用户数据块；真实 worker → loopback mock OpenAI HTTP 验证首次请求中冻结资金值及上下文结束标记均只出现一次 |
| 工具边界 | Web profile 显式开放 corpus、coverage、market；普通 Run 可达确定性 sizing/lint，业务 Run 替换为 Run 绑定的 context/sizing/lint 并排除原始工具；包装 schema 无资金、风险预算、计划价和仓位上限覆盖参数 |
| 可观测性 | resolver sidecar 记录调用、缓存读/写、摘要和本次命中；工具 sidecar 记录上下文读取、仓位计算及策略校验次数；通用 trajectory/usage 继续记录工具输入输出与 LLM token/cache/call 用量 |
| PG 回归 | `uv run --no-sync pytest tests/pg -q --tb=short`：**113 passed**；新增 owner 隔离、冻结值、缓存丢失重建与指标断言 |
| worker/工具 | DATA-08 + 编排器相关定向：**78 passed**；市场、语料覆盖、仓位、策略与注册表回归：**231 passed** |
| 仓库门禁 | Ruff 与 `git diff --check` 通过；Pyright：0 errors；import smoke stage 1：384/384，stage 2：433/433；symbol closure：483 文件无缺失；preflight 真实模型单次调用通过 |
| 清理 | 临时容器与登记的测试 Run 根在验收结束后移除；未删除其他环境的容器、卷或 Run 资料 |

本批没有部署 API，也没有迁移生产库。模型切换不改变 worker 内的 Run 绑定上下文；长对话压缩后
可再次调用 `investment_context` 取得同一快照，不依赖被压缩的聊天摘要。

**验收回溯（2026-10-03）**：初审发现并修复四项遗漏：仓位与策略校验现按冻结
`capital_basis` 选择总资金或可用资金；合法非对象 JSON 返回结构化 lint 失败；指标写盘失败不再
中断 ContextVar 清理及 Run summary；worker 使用空 tombstone 防止 `.env` 恢复业务库 Docker DSN、
master key 或 JWT key，认证解析失败时清除旧物化上下文。新增压缩移除旧消息后从 Run 绑定工具
恢复精确快照的测试。规范与规格两条独立复审均无剩余阻断项，详见
[验收回溯](../../.scratch/web-business-repairs/data08-acceptance-review.md)。

### 4.5 DATA-09 监控规则持久化与管理批次（2026-10-03）

执行记录见 [DATA-09 issue](../../.scratch/web-business-repairs/issues/04-data09-watch-rules.md)，
脱敏结果见 `.scratch/web-business-repairs/evidence/data09-pg.log`。

| 项 | 本批证据 |
|---|---|
| 隔离环境 | 临时 PostgreSQL 容器 `frontier-business-data09-20261003`（复用 `pg18-zhvector` 镜像）；独立库 `frontier_business_test`、角色 `business_test`、`127.0.0.1:55432` 及 `/tmp/frontier-business-data09-runs`；未连接或迁移现有业务库 |
| 模型与迁移 | `store.py::WatchRule(+WatchRuleRevision)`：规则指针行（研究归属、计划绑定、status、current_version、最近检查/有效行情时间）+ 不可变配置版本行（symbol/market/currency/quote_basis/direction/阈值/有效期/trigger_mode/action/task/budget/创建时已达标与断线恢复策略）。迁移 `0013_watch_rules` + `0014_watch_rule_history`（版本行 UPDATE/DELETE 拒绝，沿用 0010 触发器）；0014→0013→0012 降级再升回 head 通过 |
| 生命周期 | `server/watch_rules.py`：创建/编辑（新版本）/暂停/恢复/取消，全部 expected_version + 幂等键 + 归属校验；改版不静默改阈值（无关编辑沿用旧版本冻结值）；计划重绑校验同研究归属；取消为终态（409 rule_cancelled）；`record_check` 供 DATA-10 记录最近检查与有效行情时间 |
| C 阶段边界 | 仅 `trigger_mode=single`；`repeat` 与冷却/重新布防等 D 阶段字段明确拒绝（validation_error / unknown_field_rejected），不静默接受 |
| HTTP | `/api/business/sessions/{rid}/watch-rules` 创建；`/watch-rules` 列表（按研究/状态）；`/{id}` 详情；`/{id}` 编辑；`/{id}/versions` 历史；`/{id}/pause|resume|cancel` |
| PG 回归 | `uv run --no-sync pytest tests/pg -q --tb=short`：**138 passed**（原 113 项 + DATA-09 定向 25 项）；幂等重放、版本冲突、双用户隔离、重启后状态存在、版本行不可变均通过 |
| 仓库门禁 | Ruff 与 `git diff --check` 通过；Pyright：0 errors（存量 7 项为未改动文件既有）；import smoke stage 1：386/386；symbol closure：484 文件无缺失 |
| SQLite 路径 | `init_db()` create_all 建出 `watch_rules`/`watch_rule_revisions`，不可变触发器随建（`immutable_watch_rule_revisions_*`） |
| 清理 | 临时容器与登记的测试 Run 根在验收结束后移除；未删除其他环境的容器、卷或 Run 资料 |

本批没有部署 API，也没有迁移生产库。行情判定（穿越/去重/重新布防）、事件创建与自动分析调度
属 DATA-10/11，规则模型与生命周期只保证"重启后规则及状态存在、操作可追溯、C 只开放单次模式"。

### 4.6 DATA-10 行情判定与防重复唤醒批次（2026-10-03）

执行记录见 [DATA-10 issue](../../.scratch/web-business-repairs/issues/05-data10-watch-evaluation.md)，
脱敏结果见 `.scratch/web-business-repairs/evidence/data10-pg.log`。

| 项 | 本批证据 |
|---|---|
| 隔离环境 | 临时 PostgreSQL 容器 `frontier-business-data10-20261003`（复用 `pg18-zhvector`）；独立库 `frontier_business_test`、角色 `business_test`、`127.0.0.1:55434` 及 `/tmp/frontier-business-data10-runs`；未连接或迁移现有业务库 |
| 观测契约 | `server/watch_eval.py::MonitoringObservation`：精确 Decimal 价格 + `observed_at_ms`/`received_at_ms` 分开 + `time_source(vendor\|unknown)` + `precision_limited`；`QuoteSource` 端口与 `FuyaoQuoteSource` 保守包装（float 源统一标 unknown + precision_limited，不把 now 冒充实时新行情） |
| 判定引擎 | `condition_met`/`classify_cross`：上穿 `prev<thr<=cur`、下穿、进入区间；精确比较不用浮点相等；`_decide_trigger` 单次模式状态机（创建时已达标 `trigger_now/wait_requalify`、断线恢复 `trigger_once/wait_requalify`、常规穿越） |
| 模型与迁移 | `0015_watch_monitoring`：`watch_rules` 追加 `armed/baseline_price/last_triggered_at/last_suppressed_reason`；新增 `watch_observations`（`dedup_hash` 唯一）与 `watch_events`（`(rule_id, rule_version)` 唯一 = 事件身份，status=pending 待 DATA-11）；0015→0014 降级再升回 head 通过；编辑（新版本）复位 armed/baseline，改版不复用旧版基线与触发资格 |
| 原子与防重 | `watch_eval.evaluate`：观测/资格消耗/事件同一事务；重复投递去重、乱序/陈旧忽略、暂停/取消不判定、标的/币种不符不判定；并发判定经 `FOR UPDATE` + 事件唯一约束只消耗一次资格 |
| 常驻轮询 | `server/monitor.py::monitor_tick/monitor_loop` + 配置 `monitor_*`（默认 `monitor_enabled=false`，部署显式开启；DATA-00 §5 后台进程登记），lifespan 接入；监控链不调用 LLM（模块级无框架/LLM import 断言） |
| PG 回归 | `uv run --no-sync pytest tests/pg -q --tb=short`：**156 passed**（原 138 项 + DATA-10 定向 18 项）；上穿/下穿/区间、阈值附近往返一次、一直越线不反复、重启不重复、乱序/重复忽略、暂停/取消不判定、过期不触发、并发单次消耗、断线恢复、改版重新布防均通过 |
| 仓库门禁 | Ruff 与 `git diff --check` 通过；Pyright：0 errors（存量项未改动）；import smoke stage 1：386/386；symbol closure：484 文件无缺失；SQLite create_all 含新表与 armed 列 |
| 清理 | 临时容器与登记的测试 Run 根在验收结束后移除；未删除其他环境的容器、卷或 Run 资料 |

本批没有部署 API，也没有迁移生产库。真实供应商的盘中时效/权限/报价口径核验与轮询容量验证
仍属 DATA-10 供应商项（未核验前保持待核定）；事件→自动分析 Run 的调度属 DATA-11。

### 4.7 DATA-11 自动分析、合并与预算批次（2026-10-03）

执行记录见 [DATA-11 issue](../../.scratch/web-business-repairs/issues/06-data11-auto-analysis.md)，
脱敏结果见 `.scratch/web-business-repairs/evidence/data11-pg.log`。

| 项 | 本批证据 |
|---|---|
| 隔离环境 | 临时 PostgreSQL 容器 `frontier-business-data11-20261003`（复用 `pg18-zhvector`）；独立库 `frontier_business_test`、角色 `business_test`、`127.0.0.1:55436` 及 `/tmp/frontier-business-data11-runs`；未连接或迁移现有业务库 |
| 模型与迁移 | `0016_watch_auto_analysis`：`watch_events` 追加 run_id/generation/merged_into_id/budget_reason/analysis_expires_at/scheduled_at/attempted_at/completed_at；新增 `watch_event_runs`（`(event_id, generation)` 唯一 = 每事件每代次）与 `watch_budget_usage`（`(rule_id, rule_version)` 唯一，runs_created/runs_attempted）；0016→0015 降级再升回 head 通过 |
| 调度服务 | `server/watch_scheduler.py::schedule_event`：校验规则状态/版本/有效期/最大延迟 → 预算原子预留记账（max_runs 达限 blocked_budget）→ 研究绑定解析 → 按执行时最新版本冻结快照（source=watch_event）→ Run + outbox 同一事务 → 事件 dispatching；缺字段经 `_needs_input` 建带续接信息的 DATA-07 请求（needs_input）；`merge_pending` 按（研究, 标的, action）合并到最早一条（merged+merged_into）；`reconcile_event_runs` 按 Run 终态对账 completed/failed；`schedule_cycle` + `scheduler_loop`（`auto_*` 配置，默认关闭，lifespan 接入） |
| 失效与幂等 | 改版/暂停使旧版未启动事件 expired（rule_obsoleted/rule_inactive）；重复调度返回原 Run（每事件每代次唯一）；自动 Run 与手动 Run 共用 dispatch_outbox 研究级串行 |
| 事件查询 | `GET /api/business/watch-events`（所有者隔离、按研究/状态过滤）；`event_view` 暴露 run_id/generation/merged_into/budget_reason/截止与调度时间 |
| PG 回归 | `uv run --no-sync pytest tests/pg -q --tb=short`：**166 passed**（原 156 项 + DATA-11 定向 10 项）；触发→自动 Run、快照 watch_event 冻结、幂等重放、缺字段转补数、预算达限、改版/暂停失效、合并去向、终态对账、notify 不建 Run、事件所有者隔离均通过 |
| 仓库门禁 | Ruff 与 `git diff --check` 通过；Pyright：0 errors；import smoke stage 1：386/386；symbol closure：484 文件无缺失 |
| 清理 | 临时容器与登记的测试 Run 根在验收结束后移除；未删除其他环境的容器、卷或 Run 资料 |

本批没有部署 API，也没有迁移生产库。token 级预算记账与"重新分析 +1 代次"入口、事件通知与
已读展示属 DATA-12 C / DATA-15 联合验收。

### 4.8 DATA-12 业务事件与通知批次（2026-10-03）

执行记录见 [DATA-12 issue](../../.scratch/web-business-repairs/issues/07-data12-notifications.md)，
脱敏结果见 `.scratch/web-business-repairs/evidence/data12-pg.log`。

| 项 | 本批证据 |
|---|---|
| 隔离环境 | 临时 PostgreSQL 容器 `frontier-business-data12-20261003`（复用 `pg18-zhvector`）；独立库 `frontier_business_test`、角色 `business_test`、`127.0.0.1:55438` 及 `/tmp/frontier-business-data12-runs`；未连接或迁移现有业务库 |
| 模型与迁移 | `0017_business_notifications`：`business_events` 追加 `level`/`dedup_key`（per-user 唯一，可空不去重）/`hidden`；新增 `notification_settings`（muted_kinds/muted_levels，默认全开）；0017→0016 降级再升回 head 通过 |
| 事件产生器 | 挂接监控链：`watch_eval.evaluate` 触发 → `watch_triggered`（dedup=事件身份）；`schedule_event` → `auto_analysis_queued`/`watch_budget_blocked`/`watch_rule_inactive`；`reconcile_event_runs` → `watch_analysis_completed/failed`（完成/失败共用终态去重键）；补数沿用 DATA-07 `input_required` |
| 通知服务 | `add_event` 支持 level/dedup_key（保存点兜底并发去重）；`list_notifications` 最近未读优先 `(read_at IS NULL) DESC, cursor DESC` + kinds/levels/read 过滤 + total/unread_count/read_progress；`hide_event` 隐藏不改业务事实（游标重放仍可见）；`get_read_progress`；`get_settings`/`set_settings`；`stream_events` SSE 生成器（游标重放+live tail+可取消，路由薄包装） |
| 端点 | `GET /notifications`、`POST /notifications/{id}/hide`、`GET/PUT /notifications/settings`、`GET /events/read-progress` |
| PG 回归 | `uv run --no-sync pytest tests/pg -q --tb=short`：**179 passed**（原 166 项 + DATA-12 定向 13 项）；触发/排队/结果/错误/预算/规则失效事件、去重、未读优先、等级/类型/已读过滤、已读/隐藏幂等、阅读进度、设置读写、所有者隔离、SSE 游标重放+live tail 均通过 |
| 仓库门禁 | Ruff 与 `git diff --check` 通过；Pyright：0 errors；import smoke stage 1：386/386；symbol closure：484 文件无缺失 |
| 测试性修正 | httpx ASGITransport 缓冲完整响应、无法端到端断言无限 SSE 流；将流生成逻辑提取为 `business_events.stream_events`（路由仅做断连薄包装），测试直接消费生成器验证重放/live tail/可取消 |
| 清理 | 临时容器与登记的测试 Run 根在验收结束后移除；未删除其他环境的容器、卷或 Run 资料 |

本批没有部署 API，也没有迁移生产库。通知设置按"存储偏好 + 显式过滤"落地（写入不静默丢弃，
UI 按 settings/过滤条件展示）；安全类通知不因设置缺失而漏存。

### 4.9 DATA-13 归档、删除与取消联动批次（2026-10-03）

执行记录见 [DATA-13 issue](../../.scratch/web-business-repairs/issues/08-data13-archive-delete.md)，
脱敏结果见 `.scratch/web-business-repairs/evidence/data13-pg.log`。

| 项 | 本批证据 |
|---|---|
| 隔离环境 | 临时 PostgreSQL 容器 `frontier-business-data13-20261003`（复用 `pg18-zhvector`）；独立库 `frontier_business_test`、角色 `business_test`、`127.0.0.1:55439` 及 `/tmp/frontier-business-data13-runs`；未连接或迁移现有业务库 |
| 归档服务 | `server/business_archive.py`：`archive_account`/`archive_plan`（幂等 + 审计；暂停引用它们的监控规则，`last_suppressed_reason=object_archived`）、`delete_research`（单一事务级联：取消活动规则、过期待派发事件 research_deleted、取消待补数、作废待派发 outbox PENDING/RETRYABLE_FAILED→ABANDONED、归档该研究所属计划、软删除会话；共享账户/成交不随研究删除 AC-17）。全部 `run_write` 幂等键 + 归属校验，重复删除/归档返回幂等回执 |
| 调度兜底 | `watch_scheduler.schedule_event` 增补 `ObjectArchivedError` → 事件过期 object_archived，不无限重试 |
| 端点 | `POST /api/business/accounts/{id}/archive`、`POST /api/business/plans/{id}/archive`、`DELETE /api/business/sessions/{rid}`（业务级联；通用 `/api/sessions/{id}` 删除保持原样） |
| PG 回归 | `uv run --no-sync pytest tests/pg -q --tb=short`：**187 passed**（原 179 项 + DATA-13 定向 8 项）；归档幂等+暂停规则、归档停止新采用、删除级联（规则/事件/补数/outbox/计划/会话）、重复删除幂等、共享账户保留、通知引用已删对象可定位、已建 Run/快照保留、所有者隔离均通过 |
| 迁移 | 本批无新增迁移（复用 accounts/plans.archived、sessions.deleted_at、规则/事件/outbox 状态列） |
| 仓库门禁 | Ruff 与 `git diff --check` 通过；Pyright：0 errors；import smoke stage 1：386/386；symbol closure：484 文件无缺失 |
| 清理 | 临时容器与登记的测试 Run 根在验收结束后移除；未删除其他环境的容器、卷或 Run 资料 |

本批没有部署 API，也没有迁移生产库。软删除 ≠ 擦除：业务事实/快照/审计/事件引用一律保留；
运行中 worker 让其完成当前 Run（不再启动新任务）。物理删除范围、保留策略与联合备份恢复属
DATA-14/15。

测试时代码基线：HEAD `d419521ab7220a61b44223d0eef9e9e472313f32`（DATA-12 提交）＋未提交
工作区改动（DATA-13—15 及早期修复均未提交，回溯时以工作区文件为准）。

### 4.10 DATA-14 备份、安全与文件引用批次（2026-10-07）

执行记录见 [DATA-14 issue](../../.scratch/web-business-repairs/issues/09-data14-restore.md)，
脱敏结果见 `.scratch/web-business-repairs/evidence/data14-pg.log`。

| 项 | 本批证据 |
|---|---|
| 隔离环境 | 临时 PostgreSQL 容器 `pg-data14-test`（复用 `pg18-zhvector`）；独立库 `data14_test`、角色 `biz_test14`、`localhost:55440`；逻辑恢复形态（原实例独立库 + 临时 Run 根），未连接或迁移现有业务库 |
| 恢复核对 | `server/restore_check.py`：`check_restore()` 一次核对数据库备份水位（alembic head）、Run 目录清单（inputs/ws/ws-outputs/spill/run/diff/staging + 非 queued Run 轨迹）、8 组跨表孤立引用（含无外键的 `InputRequest.watch_event_id`）、外部调用水位（watch_event_runs/budget_runs_created/run_dispatch_rows/pending_watch_events，防回滚后重复付费）、用户 LLM 密钥解密状态。AC-18：报告不可读时 schema 水位先返、分节失败记入 `errors` 不崩溃；CLI `python -m server.restore_check [runs_root]` exit 0/1 |
| 恢复模式 | `restore_mode`（默认 False，SERVER_ 前缀）：dispatch/monitor/scheduler 三循环见模式即停、lifespan 不启动、`POST /api/runs` 503；显式关闭后循环恢复、提交恢复 202；待处理监控事件不重播，按有效期/取消状态重新裁决 |
| 敏感数据 | 归档/规则变更审计 detail 仅含对象标识与字段名，无资金/持仓正文（测试锁定）；服务端日志 grep 核对无资金正文输出 |
| PG 回归 | `pytest tests/pg -q`：**199 passed**（原 187 项 + DATA-14 定向 12 项，含 AC-18 旧备份缺表报告场景）；证据 `evidence/data14-pg.log` |
| 迁移 | 本批无新增迁移 |
| 仓库门禁 | Ruff check/format 通过；Pyright 本批文件 0 错误（全量 7 个预存错误在未改动的已提交文件，非本批引入）；import smoke stage 1：386/386；symbol closure：484 文件无缺失；`git diff --check` 通过 |
| 清理 | 临时容器 `pg-data14-test` 与测试库在验收结束后移除；未删除其他环境的容器、卷或 Run 资料 |

测试时代码基线：HEAD `d419521ab7220a61b44223d0eef9e9e472313f32`（DATA-12 提交）＋未提交
工作区改动（DATA-13—15 及早期修复均未提交）。开放缺口：业务数据（快照/审计/事件/版本）
保留期限与物理删除流程未定义（见 [DATA-14 issue](../../.scratch/web-business-repairs/issues/09-data14-restore.md) 补记）。

### 4.11 DATA-15 分阶段联合验收与成本批次（2026-10-07）

执行记录见 [DATA-15 issue](../../.scratch/web-business-repairs/issues/10-data15-joint-acceptance.md)，
脱敏结果见 `.scratch/web-business-repairs/evidence/data15-pg.log`。

| 项 | 本批证据 |
|---|---|
| 隔离环境 | 临时 PostgreSQL 容器 `pg-data15-test`（复用 `pg18-zhvector`）；独立库 `data15_test`、角色 `biz_test15`、`localhost:55441`；未连接或迁移现有业务库 |
| 端到端联合链路 | `tests/pg/test_data15_joint.py`：路由提交（PG 快照冻结）→ outbox 领取 → 真实 Orchestrator 派发真实 worker 子进程（用户 LLM 配置真实解密注入 MockLLMServer，mock 同时兜底 OPENAI_* 环境变量防真实外呼）→ 轨迹/diff/目录树落盘 → 终态（`stopped_by=no_tool`→stopped，T2.8 映射）→ 用量计量 → 快照不变（AC-06）→ 活体生成物通过 DATA-14 恢复核对（AC-18） |
| 成本计量（AC-20） | `server/usage.py::usage_summary_for_runs`：多 Run 汇总模型调用/输入/输出/**缓存读写分列**/墙钟延迟，零用量 Run 可见不丢弃；缓存读写分列测试覆盖新旧 usage 别名 |
| 既有证据映射 | 领取后崩溃及恢复 = test_run_dispatch 租约回收/不重投已启动；幂等重放/原子提交 = test_run_dispatch + test_business_repairs；越权/绕过 = 各业务测试所有者隔离用例；监控零模型/预算/防重复唤醒 = DATA-10/11 |
| PG 回归 | `pytest tests/pg -q`：**202 passed**（原 199 项 + DATA-15 定向 3 项）；证据 `evidence/data15-pg.log` |
| 迁移 | 本批无新增迁移 |
| 仓库门禁 | Ruff check/format 通过；Pyright 本批文件 0 错误；import smoke stage 1：386/386；symbol closure：484 文件无缺失；`git diff --check` 通过 |
| 登记缺口 | UI-11 浏览器完整流程（UI 任务侧）；AC-20 输入正确率与真实费用、供应商协议/行情时效实测（需真实凭据的受控试运行）；重复规则/冷却/重新布防（D 阶段）；业务数据保留期限与物理删除流程未定义（DATA-13 转出，发布前冻结归属 DATA-14） |
| 清理 | 临时容器 `pg-data15-test` 与测试库在验收结束后移除 |

测试时代码基线：HEAD `d419521ab7220a61b44223d0eef9e9e472313f32`（DATA-12 提交）＋未提交
工作区改动（DATA-13—15 及早期修复均未提交）。

## 5. 后台 dispatcher / monitor 登记要求（B/C 启用前必须满足）

当前 `server/` 无受管理后台进程，监控与持久派发所需常驻能力待建。启用前需登记并验证：

| 项 | 要求 |
|---|---|
| 启动 | 明确入口（systemd unit / compose service / 受管脚本），与 API 进程分离；启动前完成数据库迁移与就绪检查 |
| 退出 | 定义停止信号与优雅退出；退出前释放租约、回写待派发状态，不把在途任务留成“已领取但无主” |
| 自动重启 | 重启策略与重启后的状态核对：重扫 `dispatch_outbox`/`watch_rules`，按有效期与取消状态重新裁决，不盲目重播付费分析（DATA-14） |
| 租约心跳 | 租约版本随写入与完成回报校验；过期 worker 的回报不接受；未确认旧进程停止不得并发重启同研究任务 |
| 健康信号 | 独立于 `/healthz` 的后台健康信号（最近心跳、最近检查时间、队列深度），页面不以“浏览器打开”表示监控正常 |
| 单实例 | 同一研究同时只有一个执行者；与 `Orchestrator.reconcile_orphan_runs` 职责分开，不靠内存 handles 扫描收尾其他进程任务 |
| 部署形态 | 可先以单 API + 受管后台进程部署，无需先引入 Redis/Kafka；禁止挂在请求协程或浏览器会话中 |

## 6. DATA-00 验收状态

| 验收项 | 状态 |
|---|---|
| 环境对应表（浏览器 → API → 库/schema → Run 根 → worker → 文件） | ✅ 当日已建立（§1） |
| 版本/路径清单与证据命令 | ✅ 已记录，可复跑 |
| 可执行验证入口（配置不符立即失败、无静默回退） | ✅ `tests/pg/`，跳过/失败行为已实测 |
| 独立测试库 + 受限角色 + 独立数据根 | ✅ 已建立并登记（§4.1，`apodex_biz_test` / `biz_test`；独立数据根在引入 worker 用例时再设） |
| 后台进程启动/退出/心跳/健康登记 | ⬜ 未建立（要求在 §5，实现随 DATA-06/10/11） |
| 浏览器自动化入口（UI-11） | ⬜ 未建立（前端当前无 vitest/playwright） |
| 真实 PG 上的业务用例 | 🟡 已添加 DATA-02/03 部分（24 项通过，见 §4.1）；DATA-05 起继续累加 |

## 7. 复核命令清单

```bash
git rev-parse HEAD
wsl -d Ubuntu -- ps -eo pid,etime,cmd | grep -E 'uvicorn|vite'
Invoke-WebRequest http://127.0.0.1:8000/readyz
docker exec pg psql -U postgres -d apodex -tAc "select current_database(),current_user,version();"
docker exec pg psql -U postgres -d apodex -tAc "select version_num from alembic_version;"
docker exec pg psql -U postgres -d apodex -tAc "select status,count(*) from runs group by status;"
wsl -d Ubuntu -- bash -c 'ls -d ~/.local/share/frontier-agent/web/*; ls ~/.local/share/frontier-agent/web/runs | wc -l'
uv run pytest tests/pg -q -m pg
```
