# Web 平台加固计划 · 任务清单

| 项 | 内容 |
|---|---|
| 版本 / 状态 | **v1.0 · 待开始** |
| 上游文档 | [tech-stack.md](../tech-stack.md)（选型与 §6 数据模型） · [plan/pg-migration.md](./pg-migration.md)（语料库 PG，不在本计划范围） |
| 范围 | `server/`（FastAPI 业务层） · `web/`（Vue3 前端） · `deploy/`（Caddy/compose） · `.github/`（CI） |
| 不在范围 | `frontier_agent/` 内核 · `workflows/` · `apodex/` · 语料库（`plugins/corpus`） · **多实例横向扩容**（见 T17，需独立架构决策） |
| 追踪方式 | 每个任务带 `Status:` 行，取值为 `待开始` / `进行中` / `已完成` / `已搁置`；推进时只改这一行 |

> 判断基线：功能骨架（SSE 游标重连、审批门、审计、anti-IDOR、argon2id、密钥加密）已达主流水准，
> 缺的是**多用户生产化**这一层。本清单按「先正确性、再可靠性、后体验」排列。

---

## 0. 已完成基线（本计划之前已落地）

| 项 | 说明 |
|---|---|
| 业务库迁至 PostgreSQL | `server/dev.db` → PG database `apodex`；`.env` 的 `SERVER_DATABASE_URL` 为唯一开关，改回即回滚 |
| 迁移脚本 | `scripts/migrate_sqlite_to_pg.py`：ORM 搬运 + 复制模式保留孤儿历史 + 序列同步 + 行数校验 |
| 序列同步 | `turns_id_seq` / `audit_log_id_seq` 推进到 `max(id)`，修复 `POST /api/runs` 的 500 |
| 会话恢复 | 重新进入自动选中上次会话（`localStorage` + 用户维度 key） |
| 多轮不被覆盖 | run 终态及发送前回填服务端 turns，上一轮回复不再随流缓冲清空而消失 |

---

## 1. 进度总览

| # | 任务 | 优先级 | 依赖 | Status |
|---|---|---|---|---|
| T1 | `server/` 纳入 CI 静态检查 | P0 | — | 已完成 |
| T1b | 存量 pyright 错误清理 | P0 | T1 | 已完成 |
| T2 | 启动时孤儿 run reconcile | P0 | T1 | 已完成 |
| T3 | 密钥加固与启动校验 | P0 | T1 | 已完成 |
| T3b | 测试数据库隔离 | P0 | — | 已完成 |
| T4 | 列表接口分页 | P0 | T1 | 已完成 |
| T5 | 业务库备份与恢复预案 | P1 | — | 待开始 |
| T6 | 孤儿数据清理与外键策略 | P1 | T5 | 待开始 |
| T7 | request id 与结构化日志 | P1 | T1 | 待开始 |
| T8 | `/healthz` 真实探活 | P1 | T7 | 待开始 |
| T9 | `/api/runs` 限流与配额 | P1 | T7 | 待开始 |
| T10 | run 指标与成本观测 | P1 | T7 | 待开始 |
| T11 | 前端测试接入与 CI 覆盖 | P2 | — | 已完成 |
| T11b | SSE store 层测试覆盖 | P2 | T11 | 已搁置（需先决策） |
| T12 | 全局错误边界与 404 | P2 | T11 | 已完成 |
| T13 | 长会话虚拟滚动 | P2 | T11 | 待开始 |
| T14 | Caddy 安全响应头 | P2 | — | 待开始 |
| T15 | refresh token 与登出吊销 | P3 | — | 待开始 |
| T16 | i18n / 暗色 / 无障碍 | P3 | — | 待开始 |
| T17 | 多实例改造 | 延后 | 架构决策 | 已搁置 |

依赖关系：

```text
T1 ─┬─> T2 ──────────────┐
    ├─> T3                │
    ├─> T4                ├─> （批次验收：回归全绿）
    └─> T7 ─┬─> T8        │
            ├─> T9        │
            └─> T10 ──────┘

T5 ──> T6                 （先有备份再动存量数据）
T11 ─> T12 ─> T13         （先有测试再动渲染层）
T1b / T14 / T15 / T16     独立，可任意插队（T1b 决定 CI 何时真正变绿）
```

---

## 2. P0 · 正确性

### T1 `server/` 纳入 CI 静态检查

Status: 已完成

**目标**：消除 `server/` 的 lint 与类型盲区 —— 它是唯一有测试覆盖却没有静态检查的业务代码目录。

**关键步骤**
1. `.github/workflows/ci.yml`：ruff 命令加入 `server/`（当前为 `frontier_agent/ apodex/ benchmarks/ workflows/ plugins/ deploy/ tools/ scripts/`）。
2. `pyrightconfig.json` 的 `include` 加入 `server`。
3. 修复由此暴露的存量告警；若某一类告警量过大，在配置里显式列出并注明原因，而不是整目录跳过。

**完成标准**
- `uv run ruff check server/` 与 `uv run pyright` 在本地零新增错误。
- CI 的 lint / type-check 两步覆盖 `server/`，推空提交可验证步骤确实执行。
- 未新增任何 `exclude`/`noqa` 的整目录豁免。

**实际结果（已完成）**
- ruff：`server/` 原本就是干净的，零修复。
- pyright：`server/` 11 个错误全部修完，其中
  - `store.py` ×3 `__table__.update()` → `update(Model)`（SQLAlchemy 2.0 惯用法，也修掉了 pyright 把 `__table__` 推断成 `FromClause` 的问题）；
  - `orchestrator.py` ×6 `proc.stdin` 判空（stop / steer / approve 三处）；
  - `relay.py` 的 `sse_for_run` 队列元素类型与 orchestrator 对齐（带 `None` 哨兵）；
  - `alembic/env.py` 的 `do_run_migrations` 参数改为 `Connection`。
- CI：ruff 门禁加入 `server/`；依赖安装加 `--group web`（**关键**：`web` 是 dependency-group 而非 extra，此前 CI 环境根本没装 FastAPI/SQLAlchemy，这也是 `server/` 一直没进 CI 的根本原因）。`uv lock --check` 已确认 lockfile 未过期。
- 回归：`pytest tests/test_auth_t22.py tests/test_llm_config_t23.py` → 37 passed。

> 注意：`uv run pyright` 全量仍有 88 个**存量**错误，全部在 `plugins/corpus`、`plugins/market`、`deploy/huggingface`，与本次改动无关 —— 见 T1b。

---

### T1b 存量 pyright 错误清理

**目标**：让 CI 的 `Pyright type check` 这一步真正变绿 —— T1 只保证 `server/` 干净，全量命令仍会因存量错误失败。

**关键步骤**
1. 先确定 CI 的真实基线：本地未装 `--extra hf-space`，`deploy/huggingface/app.py:26` 的 `Import "gradio" could not be resolved` 在 CI 不会出现。用 CI 的 sync 组合复跑一次，只修 CI 上真实存在的错误，避免在本地噪音上浪费功夫。
2. `plugins/corpus/service.py`（占绝大多数）：psycopg 的 `dict_row` 与 `RowMaker[TupleRow]` 冲突，导致 `row["col"]` 全被判成元组下标。根治方式是把取行收敛到一个返回 `dict[str, Any]` 的访问器（或在 `_connect()` 上给出正确的泛型标注），而不是逐行加 ignore。`pg-migration.md` §8 待办 4 已记录该问题。
3. `plugins/market/failure.py` 与 `transport/client.py`：`str` 未收窄为 `FailureKind` 字面量，加校验分支收窄类型。
4. `plugins/corpus/claims.py` / `ingest.py` / `verify.py`：逐个修；确实无法在短期内修的，在 `pyrightconfig.json` 里**按文件或规则**显式豁免并写明原因，禁止整目录豁免。

**完成标准**
- `uv run pyright` 在 CI 的依赖组合下零错误。
- `plugins/corpus` 的 `dict_row` 取行不再产生 `TupleRow` 相关报错。
- 新增的（如有）豁免精确到文件/规则，且带原因注释。

**实际结果（已完成）**：**89 → 1**，且最后 1 个是本地环境噪音。

| 根因 | 修法 | 消除的错误 |
|---|---|---|
| `_connect()` 返回标注是裸 `psycopg.Connection`，使 psycopg 把行类型固定为 `TupleRow` | 返回值 `cast` 成 `Connection[DictRow]`（psycopg 无法从 `row_factory` 推断，参数处留一条 `# type: ignore[arg-type]` 说明） | ~70 |
| 动态 SQL 传给 `execute`/`copy`（psycopg 3.2 起要求 `LiteralString`） | 内部常量用 `cast(LiteralString, ...)`；扩展名改用 `sql.SQL(...).format(sql.Identifier(...))` | 9 |
| `fetchone()` 结果直接下标 | 判空；`_ledger_start` 拿不到行直接抛错（不再伪造 id） | 3 |
| 字面量字典被推断成 `dict[str, int]` 后塞不进 list | 显式标注 `dict[str, object]` | 2（service / claims 各一） |
| `BlockLike` 协议声明了可写属性，frozen `BlockView` 无法满足 | 协议属性改为 `@property` 只读 | 2 |
| `market_resolver` 同名函数覆盖变量声明 | 内部函数改名 `_market_resolver` 再赋值 | 2 |
| `MarketUnavailable.kind` 属性被推断为 `str` | `self.kind: FailureKind = kind` 显式标注 | 2 |
| `triage_blocks(list[BlockLike])` 不变 | 参数改 `Sequence[BlockLike]` | 1 |
| `FetchedBlock` 只注解不导入（循环依赖） | `TYPE_CHECKING` 块内导入，函数内运行时导入保留 | 1 |
| `_BACKUP_COLUMNS` 未标 `ClassVar`（ruff RUF012） | 补 `ClassVar` 标注 | 1（ruff） |

- 回归：`plugins/` 的 pyright 0 错误、ruff 全过；**corpus 23 个测试全过（含 golden 检索，Recall 未退化）**；全量 `pytest` **2170 passed, 3 skipped**。
- 仅剩的一条 `deploy/huggingface/app.py:26 Import "gradio" could not be resolved` 是**本地未装 `--extra hf-space`** 所致；CI 的 sync 带该 extra，不会出现。若本地也要干净：`uv sync --extra hf-space`。

---

### T2 启动时孤儿 run reconcile

Status: 已完成

**目标**：服务重启后，不再有永远停在 `running` 的 run —— 它们现在会让前端无限转圈，且占用配额统计。

**关键步骤**
1. `server/orchestrator.py` 增加启动钩子：扫描 `runs` 表中 `status IN ('queued','running')` 且不属于当前进程的行。
2. 对每条孤儿 run：尽力从 `run_dir` 下的 `summary.json` 取部分结果，标记 `failed` 或 `stopped`，写 `stopped_by='server_restart'` 与 `error`。
3. 启动钩子必须幂等且不阻塞请求（放到 lifespan 中，异常吞掉并记日志）。
4. 补单测：造一条 `running` 的 run，走一遍 reconcile，断言终态与原因字段。

**完成标准**
- 杀掉服务再启动后，DB 中不再残留 `status='running'` 的历史 run。
- 前端打开这类 run 显示明确的「已中断（服务重启）」而非转圈。
- `uv run pytest -q -k run` 全绿，新增用例覆盖重启场景。

**实际结果（已完成）**
- `store.list_active_runs()`：查询 `status IN ('queued','running')`，不按用户过滤（启动期没有请求上下文）。
- `Orchestrator.reconcile_orphan_runs()`：
  - 跳过本进程 `_handles` 里仍活着的 run；
  - 尽力读 `run_dir/summary.json`，**有部分答案 → `stopped`，否则 `failed`**——有产出也绝不记为 `completed`，因为它确实被中断了；
  - 统一打 `stopped_by='server_restart'`；
  - 整个方法不抛异常，查询失败只记日志（下一轮启动会再试）。
- 调用点：`app.py` 的 lifespan，在 `init_db()` 之后。
- 顺带把 `_synthesize_terminal_frame` 里内联的 summary.json 读取抽成 `_read_run_summary()`，两处共用一条解析路径。
- 单测 `tests/test_orphan_run_reconcile.py` 4 个用例全过：无 summary → failed、有部分答案 → stopped、本进程 handle 被跳过、已终态 run 不被改写。
- 实跑验证：造一条 `running` run 后重启服务 → 该 run 变为 `failed` / `server_restart` / 「服务重启导致运行中断」。

> ⚠️ 首次启动的副作用：本次实跑**一次性收尾了 356 条历史遗留的 running run**。它们来自 SQLite 迁移（1243 条 run 里有 356 条从未收尾），本来就是死记录。这印证了 T6（孤儿数据清理）的必要性 —— 只是这 356 条现在已由 reconcile 处理掉，T6 的清点数字会相应变化。

---

### T3 密钥加固与启动校验

Status: 已完成

**目标**：拆开「加密 LLM api_key」与「签发 JWT」两件事，并确保生产不会带着默认密钥启动。

**关键步骤**
1. `server/config.py` 新增 `jwt_secret`（默认空）；`server/security.py:94 _secret()` 改为读它。
2. 启动校验：生产环境（`SERVER_DEBUG` 未开或新增显式开关）下，`master_key` 仍为默认值或 `jwt_secret` 为空时 **直接拒绝启动**。
3. `master_key` 轮换说明写入部署文档：轮换会让已存的 `api_key_cipher` 不可解密，需要重新录入。

**完成标准**
- 不配置 `SERVER_JWT_SECRET` 时服务无法在生产模式启动，错误信息指明缺少哪个变量。
- 改 JWT 密钥后旧 token 全部失效（预期行为，需在文档中写明「上线会强制全员重新登录」）。
- 单测覆盖「默认密钥 → 启动失败」。

**实际结果（已完成）**
- `config.py`：新增 `jwt_secret`（默认空）与 `debug`（默认 False）；默认 `master_key` 抽成常量 `INSECURE_DEFAULT_MASTER_KEY`，避免校验与默认值两处漂移。
- `security._secret()`：优先 `jwt_secret`，未配置时回退 `master_key`（兼容拆分前的部署，不至于一升级就把所有人踢下线）。
- `security.check_startup_secrets()`：非 debug 下，`master_key` 为占位值或 `jwt_secret` 为空即抛 `RuntimeError`，错误信息逐条列出缺哪个变量及其后果；`SERVER_DEBUG=true` 时降级为 warning。调用点在 `app.py` 的 lifespan 最前面 —— 用 httpx ASGITransport 的测试不触发 lifespan，因此不受影响。
- 单测 `tests/test_startup_secrets.py` 6 个用例全过：默认密钥+无 JWT 密钥 → 拒绝、只设 master_key → 仍拒绝、两者齐备 → 通过、debug 降级为警告、JWT 密钥优先、未设时回退。
- 实测：`SERVER_DEBUG=false SERVER_JWT_SECRET=""` 启动 → `Application startup failed. Exiting.` 并打印两条原因。
- 部署文档 `deploy/README.md` 新增「密钥」小节：两个密钥的生成方式、分别轮换的后果、以及「部署时务必删除 `SERVER_DEBUG`」。

> 本机 `.env` 的处理：写入了新生成的 `SERVER_JWT_SECRET`，并把 `SERVER_DEBUG=true` 作为**本地开发**开关保留 —— 没有轮换 `SERVER_MASTER_KEY`，因为那会让库里 160 条 LLM 配置的密文变成不可解密。真要上线时按 `deploy/README.md` 生成两个新密钥并删掉 `SERVER_DEBUG` 即可。

---

### T3b 测试数据库隔离

Status: 已完成

**目标**：任何测试都不得触碰配置里指向的数据库。

**为什么单列一条**：业务库迁到 PG 后，一批 server 测试（`test_web_p3_steer.py`、`test_web_p3_revert.py` 等）因为不切换 `database_url`，直接连上了真实业务库 —— 在那里建表、注册用户。这不仅让 40 个用例报错（`create_all` 撞上已在使用的 schema），更严重的是**测试会污染生产数据**。

**关键步骤**
1. 新增 `tests/conftest.py`，用一个 `autouse` fixture 把 `cfg.database_url` 强制指向 `tmp_path` 下的临时 SQLite，测试结束后恢复。
2. 需要别的库的测试仍可自行覆盖该值（fixture 只负责前后恢复），因此不会破坏已有隔离逻辑。
3. `import` 失败时（未安装 web 依赖组）直接跳过隔离，不影响纯框架测试。

**完成标准**
- `uv run pytest -q` 全绿（实测：**2165 passed, 3 skipped，0 failed / 0 errors**；修复前为 2 failed + 40 errors）。
- 跑测试前后，PG 业务库的各表行数不变。

---

### T4 列表接口分页

Status: 已完成

**目标**：长会话不再一次性返回全部 turns；会话列表可增长而不拖慢首屏。

**关键步骤**
1. `server/store.py:743 list_sessions` 增加 `limit/offset`（或 cursor），路由层 `server/routes/sessions.py` 接收并校验上界。
2. `list_turns` 的 `limit` 参数已在 store 层存在，路由层补上 `?limit=` 与 `?before_seq=`（取最近 N 条）。
3. 前端 `api/index.ts` 与 `stores/sessions.ts` 适配；`ChatView.vue` 保留「加载更早消息」入口。
4. 约定默认页大小（建议 sessions 50 / turns 100），写进接口文档注释。

**完成标准**
- `GET /api/sessions?limit=1` 只返回 1 条且带总数或 has_more 标识。
- 一个人为构造的 1000 轮会话，首屏只拉最近 100 条 turns，可翻页。
- 前端手动验证：滚动到顶部能加载更早消息，不重复不丢序。

**实际结果（已完成）**
- 后端 store：`list_sessions(limit/offset)` + 新增 `count_sessions()`；`list_turns` 增加 `before_seq`（只取更旧的 seq）。
- 后端路由：`GET /sessions?limit&offset` 返回 `{sessions, total, has_more}`；`GET /sessions/{id}/turns?limit&before_seq` 返回 `{turns, has_more}`。页大小默认 sessions 50 / turns 100，**硬上界 200 / 500**，越界（含 `limit=0`）一律 422 —— 没有上界的分页等于没分页。
- 前端：`api` 与 `types` 适配分页响应；store 新增 `hasMoreTurns` / `loadingOlder` / `loadOlderTurns()`（**前插**而非替换）；`ChatView` 滚到顶部自动加载更早，并用 `scrollHeight` 差值还原滚动位置，避免读者被弹到别处；顶部同时给出「加载更早消息 / 已经是最早的消息」的状态条。
- 一个容易踩的坑已处理：run 终态后的 `reloadTurns()` 若只取一页，会把用户已翻出来的历史冲掉 —— 现在按 `max(已加载条数, 100)` 拉取。
- 单测 `tests/test_sessions_pagination.py` 5 个用例全过（含「连续向前翻页不重复不丢序」：7 条 turns 翻完得到 `[1..7]`）。
- 端到端：`limit=1` → 1 条 / `total=4` / `has_more=true`；`limit=0` 与 `limit=9999` → 422。
- 全量回归 **2170 passed, 3 skipped**；`ruff` 与 `pyright` 于 `server/` 均为 0 错误，`vue-tsc --noEmit` 通过。

---

## 3. P1 · 可靠性与数据治理

### T5 业务库备份与恢复预案

**目标**：业务库（用户、会话、run、审计）目前没有任何备份手段，先补上再动存量数据。

**关键步骤**
1. 备份脚本：`scripts/backup_business_db.sh`，用 `pg_dump`（自定义格式，含 `--no-owner --no-acl`），输出到 `backups/<日期>/`。
2. 恢复脚本：同源 `pg_restore`，并在临时库验证后再切。
3. 记录保留策略与恢复演练步骤（至少本地演练一次）。
4. 语料库已有 `CorpusService.backup/restore`，保持风格一致，不要另造一套。

**完成标准**
- 一条命令可完成备份；恢复演练成功，且恢复后行数与备份前一致。
- 文档中写明备份频率与存放位置（非本机）。

---

### T6 孤儿数据清理与外键策略

**目标**：消除迁移暴露的孤儿行（runs 517 条指向已删 session、audit_log 29 条指向已删 user），并防止再次产生。

**关键步骤**
1. 在 T5 备份完成后，统计并导出孤儿清单，人工确认处理方式（删除 / 挂到占位用户 / 保留但标记）。
2. 明确会话删除语义：`sessions` 是软删除，需定义其下 runs/turns 的处置（一并软删除，或保留但不可达）。
3. 为 turns/runs/artifacts 补上明确的外键 `ON DELETE` 行为，并用 Alembic 迁移落库。
4. 加一个只读的一致性检查脚本，可随时复跑输出孤儿计数。

**完成标准**
- 一致性检查脚本输出全 0（或全为确认保留的行）。
- 新建迁移后 `alembic upgrade head` 在空库和现有库都能跑通。
- 删除一个会话后，其子资源状态符合第 2 步定义的语义。

---

### T7 request id 与结构化日志

**目标**：出 500 时能靠一条 id 串起请求全链路 —— 现在只能翻 uvicorn 裸日志。

**关键步骤**
1. FastAPI 中间件生成/透传 `X-Request-ID`，写入 `contextvar` 与响应头。
2. 日志格式统一为结构化（时间、级别、request_id、路由、user_id、耗时），经 `logging` formatter 实现。
3. 全局异常处理：未捕获异常记录 request_id 与堆栈，对外仍返回通用错误体（不泄漏内部信息）。
4. SSE 与 worker 侧日志带上同一 request_id / run_id。

**完成标准**
- 任意一个 500，日志里有唯一 request_id，响应头可见同一 id。
- 用 request_id 能过滤出该请求涉及的全部日志行（含 worker）。
- 日志中不含明文 api_key / 密码（已有 `redact` 的前端逻辑，后端同样要兜住）。

---

### T8 `/healthz` 真实探活

**目标**：`server/app.py:50` 现在恒返回 `{"status":"ok"}`，DB 挂了也报健康。

**关键步骤**
1. `/healthz` 执行 `SELECT 1`，失败返回 503；耗时设短超时（≤2s）。
2. 区分 liveness（进程活）与 readiness（DB 可用），Caddy/compose 的 healthcheck 用后者。
3. 加 `/readyz` 或查询参数，避免探活打满连接池。

**完成标准**
- 停掉 PG 后 `/healthz` 返回 503，恢复后 200。
- compose 的 `depends_on: service_healthy` 语义与之一致。

---

### T9 `/api/runs` 限流与配额

**目标**：`POST /api/runs` 会起子进程并消耗 LLM token，目前没有任何闸门。

**关键步骤**
1. 按用户限流：单用户并发 run 数上限、单位时间提交次数上限。
2. 配额：可选的日/月 run 数与 token 预算上限，超限返回 429 并给出可读提示。
3. 超限与超配额要落审计（`audit_log` 目前主要覆盖登录类事件）。
4. 计数存放位置先按单实例设计（内存 + DB 兜底），为 T17 预留外置接口。

**完成标准**
- 并发超限返回 429，前端提示而非白屏。
- 配额用尽后提交被拒，审计表有对应记录。
- 有单测覆盖限流判定逻辑（不依赖真实时间，用可注入时钟）。

---

### T10 run 指标与成本观测

**目标**：回答「系统现在健康吗、花了多少钱」这两个基本问题。

**关键步骤**
1. 基于已有 `server/usage.py` 与 `runs` 表的 token 列，暴露聚合口径：成功率、P50/P95 耗时、失败原因分布、token/成本。
2. 先做成内部接口或日志指标，再决定是否接 Prometheus。
3. 失败原因用 `stopped_by` + `error` 归类，避免只统计一个「失败数」。

**完成标准**
- 能按天给出：run 数、成功率、P95 耗时、token 总量。
- 失败 run 能按原因分组查看。
- 不引入新中间件即可查看（命令行或内部接口二选一）。

---

## 4. P2 · 前端体验

### T11 前端测试接入与 CI 覆盖

Status: 已完成（接入与 CI 部分；store 覆盖移交 T11b）

**目标**：让已有的 63 个前端用例真正跑起来，并补上最复杂逻辑（SSE 归约）的覆盖。

**现状（2026-09-12 核对，接入前）**：`web/src/utils/` 下已有 8 个 `*.test.ts`、共 **63 个用例**（activity / approval / diff / plan / preview / revert / statusbar / transcript），用的是 **Node 内置 test runner**（`node:test`，文件头写明「项目没有 vitest，离线装不了」）。它们能跑，但**运行方式从未固化**：`package.json` 无 `test` script、CI 无任何前端步骤（前端连类型检查都没有）。`stores/runs.ts`（SSE 归约、去重、重连）与 `stores/sessions.ts` 仍**完全没有覆盖**。

**关键步骤**
1. 把 vitest 加进 `web/package.json` 的 devDependencies 与 `test` script（与 Vite 同源，配置成本最低），先让既有 63 个用例可跑。
2. 覆盖 store 层：事件归约、重连不重复渲染、终态 reconcile、审批门生命周期、turns 回填。
3. CI 增加一步 `npm ci && npm run test`（放在 `vue-tsc` 之后）。

**完成标准**
- `npm run test` 让既有 63 个用例全绿，并新增 store 层用例。
- 人为破坏重放去重逻辑时测试会失败（证明测试有效）。
- CI 有前端测试步骤。

> 覆盖 63 个已存在的用例是低垂果实：它们是现成的，只是缺一个 runner。

**实际结果（已完成 · 接入部分）**

- 澄清了一个此前的误判：**测试文件不是 vitest 风格，而是 Node 内置 test runner**（`node:test` + `node:assert/strict`）。文件头写明「项目没有 vitest，离线装不了」—— 所以**不引入 vitest 才是遵循项目既定约束**，我最初写的"引入 vitest"是错的。
- `web/package.json` 新增 `test` script（`node --experimental-strip-types --test "src/**/*.test.ts"`）与 `engines.node >= 22.6`（`--experimental-strip-types` 的最低版本）。
- `.github/workflows/ci.yml` 新增独立 `frontend` job：`setup-node@v4`（Node 22）→ `npm ci` → `npm run typecheck`（vue-tsc）→ `npm run test`。**这是 CI 第一次覆盖 `web/`** —— 此前前端既无类型检查也无测试。
- 验证：`npm run test` → **63 passed / 0 failed**；`vue-tsc --noEmit` 零错误（Node 22.12.0）。

---

### T11b SSE store 层测试覆盖

Status: 已搁置（需先决策）

**目标**：`stores/runs.ts` 的 SSE 归约（重放去重、游标重连、`streamedTurns` 集合、终态 reconcile）是全应用最复杂的逻辑，目前零覆盖。

**障碍（已实测确认，非推测）**：裸 Node ESM 不支持**目录导入**。探针测试在 `import { useRunStreamStore } from '../stores/runs.ts'` 处失败：

```
Error [ERR_UNSUPPORTED_DIR_IMPORT]: Directory import
'/home/.../web/src/api' is not supported resolving ES modules
imported from '/home/.../web/src/stores/runs.ts'
```

`runs.ts` 内部是 `from '../api'`（无扩展名的目录导入），Node 不做路径推断 —— 这是「既有 63 个测试全部集中在 `utils/`」的根本原因：只有 `utils/` 模块之间的导入带了 `.ts` 扩展名。

**两条可行路径（需选一，均要动生产源码，故先不做）**

| 路径 | 做法 | 代价 |
|---|---|---|
| A | 给 `stores/` + `api/` + `sse.ts` 依赖链的导入补显式扩展名（`'../api/index.ts'`） | 改动面覆盖多个生产文件；Vite 兼容带扩展名的导入，但需要回归一遍构建 |
| B | 把 `applyEvent` 的纯归约逻辑抽到 `utils/` 下的无依赖模块，store 只做状态容器 | 更符合既有测试架构（utils 纯函数 + 测试），但需要一次小重构 |

**建议**：选 B。它与现有 8 个 `utils/` 模块 + 测试的组织方式一致，且抽出的纯函数正是"重放去重"这类最该被测的逻辑；A 则是为测试便利去改生产代码的导入形态。

**完成标准**：`npm run test` 覆盖事件归约、重连不重复渲染、终态 reconcile、turns 回填；人为破坏去重逻辑时测试会失败。

---

### T12 全局错误边界与 404

Status: 已完成

**目标**：单组件抛错不应白屏；未知路由不应静默跳首页。

**关键步骤**
1. 顶层 `onErrorCaptured` + 兜底错误页，提供「重试 / 返回首页」。
2. `router/index.ts:38` 的 catch-all 改为真正 404 页（保留返回入口）。
3. 关键异步操作（提交 run、加载会话）失败时给出可操作提示，而非仅 `ElMessage`。

**完成标准**
- 让某个子组件故意抛错，界面显示错误页而不是白屏。
- 访问 `/no-such-page` 显示 404 页。

**实际结果（已完成）**
- `App.vue` 从空壳升级为顶层错误边界：`onErrorCaptured` 捕获全部后代组件错误（渲染 / 生命周期 / 异步事件），落一个兜底页（错误摘要 + 「重试 / 返回首页」），并 `return false` 阻断传播；「重试」通过递增 `RouterView` 的 key 强制重挂载子树，路由变化时自动清除错误态（浏览器后退也是合法恢复路径）。
- 新增 `views/NotFoundView.vue`；`router/index.ts` 的 catch-all 从 `redirect: '/'` 改为 shell 内的真实 404 路由（`name: 'not-found'`）——保留 shell 导航作为返回入口，未登录访问未知深链仍会先经登录守卫。
- 关键异步操作的可操作提示（ChatView）：
  - 提交 run 失败：不再用一闪而过的 toast，改为 composer 上方的常驻错误横幅（保留失败原因），附「重试发送」——原文被保存在 `sendFailure` 里，一键原样重发，成功后横幅自动消失；
  - 加载会话失败：`onMounted` 的 loadList / restore 失败统一收敛为消息区顶部的「加载会话失败：…」横幅 + 「重试」按钮（`bootSessions()` 同时服务首载与重试），替换掉原先两处各自为政的 toast。
- 验证（浏览器实测，vite dev + FastAPI 后端，临时注入抛错后回滚）：
  - `/no-such-page` 显示 404 页（标题、文案、返回按钮、shell 导航齐全）；
  - `/models` 注入 `throw` 后显示兜底错误页而非白屏，「重试」后仍稳定显示错误页，「返回首页」正常回到对话；
  - 停掉后端后发送消息 → 「发送失败：请求失败（HTTP 500）」横幅 + 「重试发送」，用户气泡保留，重试再失败横幅仍在、页面不白屏（500 来自 vite proxy 对不可达上游的转发行为，生产 Caddy 下为 502，前端处理路径相同）。
- 回归：`vue-tsc --noEmit` 0 错误；`npm run test` 63 passed；`npm run build` 通过。
- 遗留：测试账号 `smoke_t12` 留在业务库（无删除接口），冒烟会话已通过 API 删除。

---

### T13 长会话虚拟滚动

**目标**：`ChatView.vue` 的 `messages` 全量 `v-for` + 每步 `v-html` markdown，几十轮后必然卡。

**关键步骤**
1. 引入虚拟列表（仅对消息层做，steps 区域按需折叠）。
2. 保留「滚动到底部」与「跳到命中项」既有行为（`flashStep` 依赖 DOM 查询，需适配）。
3. 用 200+ 轮会话做性能对比（首屏与滚动帧率）。

**完成标准**
- 200 轮会话下滚动无明显掉帧，首屏耗时不高于改造前。
- 查找命中跳转、自动滚到底部功能仍正常。

---

### T14 Caddy 安全响应头

**目标**：`deploy/Caddyfile` 目前只有 gzip 与 Cache-Control。平台处理 LLM API key，且前端用 `v-html` 渲染 markdown。

**关键步骤**
1. 增加 CSP（至少限制脚本与样式来源，配合 DOMPurify 作为第二道防线）、HSTS、`X-Content-Type-Options`、`Referrer-Policy`、`X-Frame-Options`。
2. CSP 若与 Element Plus 的内联样式冲突，用 nonce 或收窄指令解决，不要整体放弃。
3. 本地 `caddy validate` 校验；如有 docker 环境则实跑一次。

**完成标准**
- 响应头齐全且页面功能无回归（登录、会话、SSE 均正常）。
- 浏览器控制台无 CSP 违规报错。

---

## 5. P3 · 可插队项

### T15 refresh token 与登出吊销

**目标**：现在只有 24h access token，登出靠进程内 `jti` denylist（多实例失效）。

**关键步骤**：引入 refresh token 与滑动续期；`jti` denylist 落到 DB 或 Redis（为 T17 铺路）；支持「登出所有设备」。

**完成标准**：refresh 可续期且旧 refresh 一次性作废；重启服务后登出状态仍生效。

---

### T16 i18n / 暗色 / 无障碍

**目标**：中文硬编码、无暗色、气泡不可聚焦、流式回复无 `aria-live` 播报。

**关键步骤**：抽离文案层（先做结构再翻译）；Element Plus 暗色变量；消息容器加 `aria-live="polite"` 与键盘可达。

**完成标准**：切暗色无样式破面；至少一轮「键盘 + 读屏」可用。

---

### T17 多实例改造（已搁置）

**目标**：消除三处进程内状态 —— `LoginThrottle`（`security.py:213`，注释已注明 in-process）、orchestrator 的 worker 注册表、SSE 事件队列。

**搁置原因**：需要引入 Redis（或 PG LISTEN/NOTIFY）与分布式锁，属于架构决策；当前单实例部署没有痛点，提前做会拖慢迭代。

**触发条件**：出现第二副本需求，或单实例成为可用性瓶颈时重启本任务。

---

## 6. 每批次验收基线

每个批次合入前，以下必须全绿：

```bash
uv run ruff check .            # 含 server/
uv run pyright                 # 含 server/
uv run pytest -q               # 含 server 相关 tests/test_*_t2x.py
cd web && npm run typecheck    # vue-tsc
cd web && npm run test         # T11 之后
cd web && npm run build        # 构建产物可用
```

人工冒烟（5 分钟）：登录 → 新建会话 → 发送一条 → 等待流式回复 → 停止 → 切换会话 → 刷新页面 → 确认历史仍在 → 再发一条确认上一轮未被覆盖。

---

## 7. 明确不做

- **不改 `frontier_agent/` 内核**：Web 层为纯新增，这是既定原则（tech-stack.md）。
- **不动语料库**：`plugins/corpus` 的 PG 迁移已完成且有独立报告，本计划不触碰。
- **不提前做多实例**：见 T17 搁置说明。
- **不引入新的前端框架**：Vue3 + Vite + Pinia + Element Plus 已冻结。
