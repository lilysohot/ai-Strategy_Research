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
| T1b | 存量 pyright 错误清理 | P0 | T1 | 待开始 |
| T2 | 启动时孤儿 run reconcile | P0 | T1 | 待开始 |
| T3 | 密钥加固与启动校验 | P0 | T1 | 待开始 |
| T4 | 列表接口分页 | P0 | T1 | 待开始 |
| T5 | 业务库备份与恢复预案 | P1 | — | 待开始 |
| T6 | 孤儿数据清理与外键策略 | P1 | T5 | 待开始 |
| T7 | request id 与结构化日志 | P1 | T1 | 待开始 |
| T8 | `/healthz` 真实探活 | P1 | T7 | 待开始 |
| T9 | `/api/runs` 限流与配额 | P1 | T7 | 待开始 |
| T10 | run 指标与成本观测 | P1 | T7 | 待开始 |
| T11 | 前端测试与 SSE store 覆盖 | P2 | — | 待开始 |
| T12 | 全局错误边界与 404 | P2 | T11 | 待开始 |
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

---

### T2 启动时孤儿 run reconcile

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

---

### T3 密钥加固与启动校验

**目标**：拆开「加密 LLM api_key」与「签发 JWT」两件事，并确保生产不会带着默认密钥启动。

**关键步骤**
1. `server/config.py` 新增 `jwt_secret`（默认空）；`server/security.py:94 _secret()` 改为读它。
2. 启动校验：生产环境（`SERVER_DEBUG` 未开或新增显式开关）下，`master_key` 仍为默认值或 `jwt_secret` 为空时 **直接拒绝启动**。
3. `master_key` 轮换说明写入部署文档：轮换会让已存的 `api_key_cipher` 不可解密，需要重新录入。

**完成标准**
- 不配置 `SERVER_JWT_SECRET` 时服务无法在生产模式启动，错误信息指明缺少哪个变量。
- 改 JWT 密钥后旧 token 全部失效（预期行为，需在文档中写明「上线会强制全员重新登录」）。
- 单测覆盖「默认密钥 → 启动失败」。

---

### T4 列表接口分页

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

### T11 前端测试与 SSE store 覆盖

**目标**：`stores/runs.ts` 的 SSE 归约（重放去重、游标重连、`streamedTurns` 集合）是全应用最复杂逻辑，目前零测试。

**关键步骤**
1. 引入 vitest（与 Vite 同源，配置成本最低），配置 `web/package.json` 的 `test` script。
2. 优先覆盖：事件归约、重连不重复渲染、终态 reconcile、审批门生命周期。
3. 再覆盖 `stores/sessions.ts` 的 turns 回填（对应本计划前的多轮覆盖修复）。
4. CI 增加一步 `npm ci && npm run test`。

**完成标准**
- `npm run test` 覆盖上述四个场景，全部通过。
- 人为破坏重放去重逻辑时测试会失败（证明测试有效）。
- CI 有前端测试步骤。

---

### T12 全局错误边界与 404

**目标**：单组件抛错不应白屏；未知路由不应静默跳首页。

**关键步骤**
1. 顶层 `onErrorCaptured` + 兜底错误页，提供「重试 / 返回首页」。
2. `router/index.ts:38` 的 catch-all 改为真正 404 页（保留返回入口）。
3. 关键异步操作（提交 run、加载会话）失败时给出可操作提示，而非仅 `ElMessage`。

**完成标准**
- 让某个子组件故意抛错，界面显示错误页而不是白屏。
- 访问 `/no-such-page` 显示 404 页。

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
