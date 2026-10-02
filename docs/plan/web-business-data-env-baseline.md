# Web 业务资料专项 · 环境基线与验证入口（DATA-00）

| 项 | 内容 |
|---|---|
| 版本 / 日期 | v0.1 · 2026-10-02（当日只读核定） |
| 状态 | 台账与入口已建立 · **独立测试库、受限角色与后台进程尚未建立**，不作为就绪声明 |
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
| 迁移 | `0001 → 0006_business_operations`（入口自动执行 `alembic upgrade head`） |
| 执行 | `PG_INTEGRATION=1 PG_BUSINESS_TEST_DB=apodex_biz_test SERVER_DATABASE_URL=postgresql+asyncpg://biz_test:***@localhost:5432/apodex_biz_test uv run --extra dev --group web pytest tests/pg -q -m pg` |
| 结果 | **33 passed**（DATA-00 基线 4 项 + DATA-02 业务对象 7 项 + DATA-03 写入服务 13 项 + HTTP 路由 9 项） |
| 回归对比 | 在 HEAD 干净副本（临时 worktree）上跑 `tests/test_web_p2_files.py` + `test_web_p3_revert.py` 得 9 failed/13 passed/6 errors，与当前工作区**完全一致** → 这批失败是 Windows 原生环境的既有现象（worker 进程组、符号链接），非本次改动引入；相关用例仍需按 §2.2 在 WSL 复验 |
| 清理 | 本批结束按 §3 清理；测试库与角色保留至 DATA-03 复用，口令只在本批有效 |

已取得的真 PG 证据：金额列为 `NUMERIC(30,10)`、比例列为 `NUMERIC(20,10)`；
`1234567890.1234567890` 与 `0.0000000001` 写入后逐位回读一致；缺失资金为 `NULL` 而非 0；
重复 `(account_id, revision)` 被唯一约束拒绝；跨研究主计划与跨用户账户被复合外键拒绝；
成交更正保留原行与前值。

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
