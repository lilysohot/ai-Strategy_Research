# 网页端语料库接入方案（用户做交易策略时能用上资料库）

> 起草日期：2026-09-10
> 目标来源：用户提出「网页端用户在进行交易策略时，也能够用上现在构建的资料库」
> 状态：**待评审**（尚未动手实现）

## 一、目标

让网页端用户在**发起并审视一笔交易策略**的全过程中，能够：

1. **看得见**：知道资料库里有什么（多少篇研报、覆盖哪些标的、抽取了多少 claim）；
2. **选得着**：本次策略可以明确选择是否启用资料库、限定标的范围；
3. **溯得到源**：策略里的每一条结论能指出来自哪篇研报的哪一段（或来自哪个市场数据工具 + 留痕）；
4. **看得懂兜底**：标的无研报覆盖时，网页明确告知"已切换市场数据路径"，而不是让用户以为是模型瞎编；
5. **管得了**：能在网页上看到 claim 抽取进度与失败情况，不必回到 CLI。

一句话：把资料库从「Agent 内部的黑盒能力」升级为网页用户**可见、可选、可溯源、可运维**的一等公民。

## 二、现状勘察（先说结论：能力已通，产品未通）

### 2.1 已经通的：唯一打通的 profile

`workflows/stateful_react_agent/profiles/tui.yaml` 已把**策略工具 + 语料工具 + 市场工具**绑在同一份工具清单里：

```yaml
agent_tools: [web_search, web_fetch, bash, grep_search, glob_search, add_task,
  update_task, read_file, create_file, recover_result,
  position_sizing, strategy_lint,          # 交易策略
  corpus_search, corpus_fetch, data_coverage,   # 语料
  market_resolve, market_quote, market_history, market_financials]  # 行情
```

而以下 profile **不含**语料与策略工具，走这些链路时用不到资料库：

- `stateful_react_agent/profiles/simple.yaml`、`benchmark.yaml`
- `agent_team/profiles/*`（`main_agent_tools` / `sub_agent_tools` 均无 corpus）

结论：**多智能体（agent_team）路径目前与资料库完全无关**。

### 2.2 网页已经"部分可见"

`web/src/components/ActivityPanel.vue` 按工具调用逐行渲染 **名称 / 状态 / 耗时 / 输入 / 输出**（可展开）。
所以 Agent 只要调了 `corpus_search`，网页上**是看得到痕迹的**。

但这是**黑盒可见**——用户看到的是一次 JSON 调用，不是"这份结论依据了茅台 12 篇研报"。

### 2.3 产品层四处缺口

| 缺口 | 现状 | 后果 |
|---|---|---|
| **不可见** | 网页无任何语料入口，`server/routes/` 无 corpus 路由 | 用户不知道库里 78 份研报、哪些标的有覆盖 |
| **不可选** | `submit_run` 用 `pipeline_id=cfg.pipeline_id`，pipeline 服务端写死 | 用户无法决定本次是否用资料库；只能改服务端配置 |
| **不可溯源** | 策略卡的 evidence（`doc_id`/`locator`）只作为文本混在回复里 | 无法一键查看"这句话出自哪篇原文"，硬闸①的价值没体现在 UI |
| **不可运维** | claim 抽取只能走 CLI（`extract-claims`） | 624 个候选块抽了多少、失败多少，网页一概不知 |

### 2.4 连接层三个坑（前置，不做则后续全空）

1. **两个 compose 栈网络不通**：`deploy/docker-compose.yml` 只有 `frontend/caddy/api`、无任何数据库；`corpus-db` 在独立的 `docker/docker-compose.yml`。两个栈各建网络，`api` 容器连不到 `corpus-db`。
2. **`localhost:5432` 是致命默认值**：`plugins/corpus/service.py` 的 `dsn()` 默认 `postgresql://postgres:postgres@localhost:5432/postgres`（注释说明依赖 WSL2 localhost 转发，只适用于本机开发）。容器内的 `localhost` 指向容器自身。且 `CORPUS_DSN` / `CORPUS_DB_PASSWORD` **未写进根 `.env.example`**（隐形配置）。
3. **同步驱动 + 无连接池**：每次 `_connect()` 都 `psycopg.connect` 新建连接（`connect_timeout=10`），而 `api` 是 async（SQLAlchemy async engine + FastAPI）。网页列表/轮询会握满连接，且同步调用会堵塞事件循环。

> 补充：业务库与语料库**无需统一**。`server/config.py` 的 `database_url` 默认 `sqlite+aiosqlite:///./server/dev.db`，与 corpus 的 PG 各司其职，二者不需要 join；正确做法是让 **api 进程同时持有两个连接**。

## 三、设计原则

1. **网页路径只读**：HTTP 请求绝不触发 `init_db()` / `ensure_prerequisites()`（建表、建扩展是运维动作，不该由 Web 请求引发）。
2. **不泄露凭据**：任何响应不得回显 DSN。健康接口只返回 `{ok, counts}`。
3. **异步不堵循环**：所有 corpus 同步调用必须 `await asyncio.to_thread(...)` 包裹，并配连接池。
4. **硬闸不降级**：UI 只是呈现层；"无证据不出卡 / 算术不出 LLM"由既有 `verify` 保证，网页不得绕过或伪造来源标注。
5. **单一数据源**：网页显示的数字必须与 CLI（`extract-claims --dry-run`）同源同口径，避免两套统计互相打脸。

## 四、分层方案

### L0 连接层（前置，必须最先做完）

- 将 `corpus-db` 并入 `deploy` 单栈同网络（推荐），或建 external 共享网络；容器内以服务名 `corpus-db:5432` 访问，删除对 `localhost` 的默认依赖。
- `CORPUS_DSN` / `CORPUS_DB_PASSWORD` 补进根 `.env.example`，并在 deploy compose 的 `api.environment` 显式声明。
- `CorpusService` 引入 `psycopg_pool.ConnectionPool`（min/max 可配），替换逐次 `connect`。
- 新增 `GET /api/corpus/health` → `{ok, counts:{documents,blocks,claims}}`，不回显 DSN。

### L1 可见：语料总览

新增 `GET /api/corpus/overview`、`/documents`、`/documents/{doc_id}`、`/claims?ticker=`：

- 概览卡：文档数 / 块数 / claim 数 / 已抽取 vs 候选（复用 dry-run 统计口径）
- **按 ticker 查询是否有覆盖**（直接服务用户构想：做策略前先知道这个标的有没有研报）
- 文档详情：分块原文（只读浏览）
- 前端新增 `/corpus` 路由与页面（总览 + 列表 + 详情）

### L2 可控：本次策略是否启用语料

- 后端：`submit_run` 增加可选参数（如 `corpus_scope`: `off | auto | {tickers:[...]}`），映射为是否向工具集注入 `corpus_search/corpus_fetch/data_coverage`；不得推翻既有 profile 体系，优先做成 profile 变体或运行时工具过滤。
- 前端：输入框旁增加"资料库"开关/标签，实时显示"本次将引用：贵州茅台 12 篇研报"。
- `off` 时明确：Agent 不得引用研报，`data_coverage` 也一并关闭，避免"关了检索却还声称有研报"。

### L3 可溯源：结论回到原文

- 策略卡 `evidence` 结构化渲染为**证据清单面板**（而非混在正文里），每条含：`doc_id`、`locator`、quote 文本、来源类型。
- 点击任一条：调 `corpus_fetch` 取逐字原文并高亮对应片段（呼应硬闸① `search` 给 snippet、`fetch` 才给原文）。
- 市场数据类证据单独标注：留痕 `tid`、`computed_by`、`coverage`，明确"数值由工具计算，非模型生成"。

### L4 可观测：本次 run 用了多少语料

- run 级语料使用指标：`corpus_search` 调用次数、命中文档数、被策略卡采纳的 claim 条数。
- **coverage 信号 UI 化**：`data_coverage` 返回的值在网页顶部显式呈现：
  - 有研报 → "本次引用 N 篇研报"
  - `coverage="none"` → "资料库无该标的研报，本次已切换市场数据路径"（对接既有出口逻辑）
- 这样用户能理解"为什么策略没引用研报"，而不是误判模型偷懒。

### L5 可运维：抽取进度与质量

- 网页展示抽取进度：候选 624 块 / 已抽 X / 失败 N（复用 `ExtractStats` 字段）。
- 只读展示失败原因列表（定位限流 vs 解析失败）。
- 触发/停止仅开放给管理员，且必须后台错峰执行（避免撞 429）。

## 五、阶段计划

| 阶段 | 内容 | 依赖 |
|---|---|---|
| **Stage 1** | L0 连接层 + L1 语料总览页 | 无（最先做） |
| **Stage 2** | L2 可控开关 + L4 使用观测 | Stage 1；需放宽 pipeline 写死 |
| **Stage 3** | L3 证据溯源面板 + L5 抽取运维 | Stage 2 |

建议节奏：**Stage 1 先把链路跑通**（本机跑 api 直连 corpus-db 即可看到数据），再把部署收敛回容器（避免一上来就改 compose 而看不到结果）。

## 六、验收标准（可测）

1. **数据一致**：网页 `/corpus` 显示 78 文档 / 928 块 / 624 候选，与 `extract-claims --dry-run` 输出完全一致。
2. **看得见**：网页能用 ticker 查到该标的研报篇数；无覆盖的标的返回明确的"无覆盖"而非空列表。
3. **选得着**：发起策略时关闭资料库 → Activity 面板不出现任何 `corpus_*` 调用，且回复不声称引用研报。
4. **溯得到源**：策略卡任一条 evidence 点击后能取到逐字原文，且与 evidence 文本**逐字匹配**（硬闸①）。
5. **看得懂兜底**：无研报标的发起策略 → 网页显示"无研报覆盖，已切换市场数据"，策略卡仍可通过 verify。
6. **性能**：连续刷新 `/corpus` 概览 20 次不出现连接池耗尽，且异步路由不阻塞其他请求。

## 七、风险与非目标

- **非目标**：网页不承担写库（ingest / 抽取触发走运维通道）；不做业务库与语料库合并。
- **风险 1**：`asyncio.to_thread` + 连接池若漏配，会把 FastAPI 拖慢——Stage 1 必须做压测式验收（标准 6）。
- **风险 2**：放开 pipeline 选择可能引入"配错工具集导致策略退化"，L2 需保证默认与现状一致（向后兼容）。
- **风险 3**：网页展示 claim 时不得暴露凭证，遵循既有 `redactDeep/redactSecrets` 渲染层纪律。
