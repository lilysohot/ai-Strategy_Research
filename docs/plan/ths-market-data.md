# 接入同花顺数据 · 需求与设计

| 项 | 内容 |
|---|---|
| 版本 / 状态 | **v3.0 · 边界已重定：只做「工具接入」，不做数据存储** |
| 数据源 | **fuyao 同花顺金融数据 API**（<https://fuyao.aicubes.cn/docs/>）——REST + MCP，**标准 HTTP，跨平台** |
| **接入方式** | 主链路 **REST 同步拉取**（自建 `@tool`）；MCP / SDK 亦可用，各有定位（§3.0–§3.3）。该服务**无 WebSocket / 推送 / 回调**，三者底层均走 `HTTPS + X-api-key` |
| **模块边界** | **本模块 = 给 Agent 一组市场数据工具**。取回即用、**不落库、不跑批、不建表**。数据是否入库**不在本模块考虑**（§1.1） |
| 凭据状态 | **API Key 已开通**（2026-09-09）；剩余待确认见 §10 |
| 上游文档 | [p0-research-kernel.md](./p0-research-kernel.md)（三条硬闸）· [p1-corpus-scaleup.md](./p1-corpus-scaleup.md)（D5 回测因无行情源暂缓）· [data-layer-architecture.md](./data-layer-architecture.md)（服务层收口）· [corpus-ingestion-architecture.md](../corpus-ingestion-architecture.md)（适配器 / 精度红线） |
| 影响范围 | 新增 `plugins/market/*` + 四个 `@tool`；改动 `verify.py` 溯源解析器、5 处工具注册点、`.env.example`。**不新增 PG 表** |
| 状态图例 | ⬜ 未开始 · 🔄 进行中 · ✅ 已完成 · 🅿️ 暂缓 · ⛔ 阻塞 |

> **v3.0 相对 v2.1 的实质变化**：v2.1 把「取数 → 落库 → 跑批 → 检索」当成一件事设计，
> 其中包含了 `market` schema、日/增量跑批、Parquet 全量导入。**按你的要求全部移出本模块**：
> Agent 取回数据是为了**当场分析**，不需要存。本模块只负责「**让 Agent 会用同花顺**」——
> 工具集 + 调用治理 + 失败处理 + 分析友好的返回体。存储另立议题，本模块只留接缝（§5.3）。

> **v2.0 相对 v1.0 的实质变化**：v1.0 假设供应商是 iFinD（Windows SDK），因此设计了
> Windows 常驻 bridge。核实文档后确认是**标准 REST 接口**（`X-api-key` 头、跨平台），
> **bridge 方案整体作废**，架构大幅简化。同时修正两处数据范围误判（无一致预期接口、
> 交易日历只覆盖近一年），并新增三个接口层的坑（§9）。

> **业务前提：本模块处理的是实时时变价格。** Agent 取同花顺**当下最新快照**做策略讨论与研究——价格随时变化，不存在「权威冻结值」。因此每个被引用的数字都必须标注 `as_of` 时点与来源；溯源硬闸比对的是「**来源与时点是否真实、数值是否未被篡改 / 编造**」，而非「值是否等于某个静态快照」。这直接决定了 §3 的接入方式取舍与 §5.5 的硬闸语义。

---

## 1. 为什么现在要接

当前系统只有**文本侧**（研报语料），没有**结构化数据侧**。三个具体缺口：

| # | 缺口 | 证据 | 后果 |
|---|---|---|---|
| 1 | **价格没有客观锚** | `position_sizing` 的 `entry_low / entry_high / stop_loss` 全是入参，只校验关系（`stop_loss < entry_low`），不校验与现实价格是否有关 | 入场区间与止损是「研报里写的 / 模型拍的」，无法发现「现价已远超目标价」这类失效 |
| 2 | **`backtest_strategy` 起不来** | `p1-corpus-scaleup.md §3 D5`：「依赖历史行情源；无行情则回测数字全是假的」，状态 🅿️ | 唯一能证伪策略的手段缺失 |
| 3 | **研报无法与现实对照** | corpus 里只有观点（目标价、盈利预测），没有实际财务与行情 | 「研报说的」与「实际发生的」无法对齐，预期差无从计算 |

**一句话目标**：在不破坏三条硬闸的前提下，把同花顺的**结构化行情 / 财务 / 估值**
接成与 corpus 对称的第二条数据链路，使策略卡里**每一个市场数字都可溯源、可证伪其来源与时点**（价格是实时时变的，无法「复算」）。

### 不在本次范围

| 项 | 理由 |
|---|---|
| 实盘交易 / 下单 | 本项目是「研究性推演」，`DISCLAIMER` 已明示不涉及交易执行 |
| Tick / Level2 / 盘中实时 | 日频已足够覆盖 V1 目标 |
| 自动选股（`market_screen`） | 依赖 D3 挖掘与全量 corpus；且「不荐股」是定位红线 |
| 涨跌停池 / 热榜 / 龙虎榜等特色数据 | 面向短线情绪，与「3–6 个月持有期」的研究定位弱相关（V2 再评估；「个股异动原因」对「解释为什么跌」有价值，单列 V2） |
| 直接挂载官方 MCP 工具 | 会绕过硬闸与审批，理由见 §3.3 |

### 1.1 模块边界：只做「工具」，不做「存储」

**做什么**（本模块唯一目标：让 Agent 会用同花顺）

1. **一组 `@tool`**：`market_resolve` / `market_quote` / `market_history` / `market_financials`
2. **调用治理**：鉴权、超时、退避重试、并发上限、熔断、错误码转成人话（§5.2）
3. **失败处理**：失败不打断 Agent，给出可执行的下一步（§6）
4. **分析友好的返回体**：口径标注、时间可读、`null` 显式说明、反幻觉提示（§5.4）
5. **硬闸对接**：让「引用市场数字」这件事仍然可校验（§5.5）

**不做什么**（移出本模块；将来如需，另立议题）

| 项 | 归属 |
|---|---|
| PG 表 / `market` schema / 快照落库 | **存储议题**（不在本文范围） |
| 日频跑批 / 全量导入 / Parquet dump / `pyarrow` 依赖 | **存储议题** |
| 历史数据回补 / 交易日历累积留存 | **存储议题** |
| 跨会话缓存 | 可选优化，默认不做；本模块只做**进程内单飞去重**（§5.2） |
| 回测 D5 | 依赖存储议题；本模块只提供取数工具 |

⇒ 一句话：**本模块是「同花顺的取数能力 + 治理」，不是「同花顺的数据仓库」。**

**由此产生一个必须回答的问题**：不落库，且价格是实时时变的，硬闸①「数字可溯源」拿什么比对？
答案见 §5.5 —— 溯源从「**可复算 / 冻结值相等**」调整为「**可证伪来源与时点、数值未被篡改**」，
并提供一个可选的「响应留痕」旁路（写 **run 目录**，不是数据库）。

---

## 2. 数据源事实（来自官方文档，改动以此为据）

| 事实 | 内容 |
|---|---|
| Base URL | `https://fuyao.aicubes.cn` |
| 鉴权 | 请求头 `X-api-key: <key>`（文档站「API Key 管理」页签发，绑定同花顺账号） |
| 路径形态 | `/api/<标的宇宙>/<数据类型>/<动作>`，如 `/api/a-share/prices/snapshot` |
| 响应信封 | `{code, message, request_id, data:{timestamp, item}}`；**业务错误也返回 HTTP 200**，靠 `code` 分发；限流可能返回 HTTP 429 |
| 时间 | 全部为**毫秒级 Unix 时间戳**，时区 `Asia/Shanghai` |
| 标的代码 | 必须用完整 `thscode`（`600519.SH`），**不接受纯 `600519`** |
| 限流 | **不限制累计调用次数**；动态 QPS，触发时返回 HTTP 429 或 `code=4001` |
| 金额单位 | 原币元；A 股恒为 CNY；`basic_eps` 为元/股（不可与金额字段换算） |
| 空值 | `null` 表示「该期未披露」，透传不补零（**禁止当成 0 参与计算**） |

### 2.1 V1 会用到的能力

| 能力 | 端点 | 关键字段 | 备注 |
|---|---|---|---|
| 标的检索（消歧） | `GET /api/meta/tickers/search` | `thscode / ticker / name / exchange / asset_type / currency`，`q` 支持名称子串 | **一切的前置步骤**；`data.timestamp` = 代码表快照时间 |
| 标的列表 | `GET /api/meta/tickers/list` | 按 `asset_type` 分页 | 全量列举（本模块不建表，按需调用） |
| 行情快照 | `GET /api/a-share/prices/snapshot` | `last_price / open / high / low / prev_price / price_change / price_change_ratio_pct / volume / turnover` | **`data.timestamp` 即 `as_of`**；**不含中文名** |
| 历史 K 线 | `GET /api/a-share/prices/historical` | `date_ms, OHLC, volume, turnover` | 单 `thscode`（不接受逗号）、`interval=1d`、**窗口 ≤ 10 年**、`adjust=none/forward/backward`（默认 `forward`） |
| 复权因子事件流 | `GET /api/a-share/corporate-actions/adjustment-factors` | `ex_date_ms, dividend_per_share, per_share_bonus, allotment_ratio, allotment_price` | 官方只给**原始事件**，复权自行推导 |
| 财务报表 | `/api/a-share/financials/{income-statements,balance-sheets,cash-flow-statements}` | `period, fiscal_year, fiscal_period, report_date_ms, period_end_ms, currency` + 各科 | **`report_date_ms` = 披露日**（防前视偏差的关键） |
| 财务指标 | `GET /api/a-share/financials/indicators` | 成长 / 盈利 / 偿债 / 营运 / 现金流五类 | V1.1 |
| 估值快照 | `GET /api/a-share/valuations/snapshot` | `pe_ttm / pe_mrq / pb_mrq / ps_ttm / pcf_ttm`，**含 `name`** | 单次最多 100 个 token；只给最新，无历史 |
| 交易日历 | `GET /api/a-share/calendar/trading-days` | `date_ms, date(yyyyMMdd)` | ⚠️ **固定窗口 = 近一年，无入参** |
| 全量导出（备用，本模块不用） | `/api/dump/market-dumps/{daily-k,daily-k-10d,adjustment-factors}/download-url` | Parquet：10 年全量日 K / 最近 10 交易日 / 复权因子全量 | **S3 预签名链接 ~5 分钟有效**；本模块不落库，此端点本期不使用（属存储议题） |
| 指数与成分股 | `/api/a-share-index/catalog/ths-index-list`、`/constituents/ths-stock-list` | 同花顺概念/行业指数、成分股 | V1.2（D3 挖掘） |

> **供应商没有的东西（不要写进计划）**：一致预期 / 机构盈利预测 / 目标价 / 研报原文。
> 「市场一致预期」只能来自我们自己的 corpus 研报（依赖 D2 claim 抽取），不能指望这个接口。

### 2.1.1 实测契约修正（M0 capability 探测，2026-09-09）

官方文档未标注请求参数名，M0 用真实 Key 实测探明。**以下为写代码时的唯一依据**，
与文档不一致处一律以本节为准：

| # | 实测结论 | 影响 |
|---|---|---|
| 1 | **参数名分两套**：批量端点用 **`thscodes`**（复数，逗号分隔，单次 ≤100）；单标的端点用 **`thscode`**（单数） | ⚠️ **最危险的坑**：`prices/snapshot` 若误传 `thscode`，参数被**静默忽略**并返回**全市场 5569 条**（不报错！）。adapter 必须按端点固定参数名，`market_quote` 须校验返回条数与请求条数一致 |
| 2 | `financials` 必须传 **`period`**，取值为字面量 **`annual`** / **`quarterly`**（不是日期） | 传日期格式一律 `code=1002 Invalid parameter format`。工具层 `market_financials` 需暴露这两个枚举 |
| 3 | `prices/historical` 需 **`start` / `end`**（毫秒时间戳）+ **`interval`**（`1d`） | 缺 `start` 报 `code=1001`。实测 2025 全年窗口返回 243 条日 K |
| 4 | **响应信封不统一**：`snapshot` / `valuations` / `financials` 的 `data` = `{timestamp, [total], item}`；`historical` 的 `data` = `{timestamp, item, thscode, interval, adjust}`；**`corporate-actions` 的 `data` = `{thscode, ticker, item}`，没有 `timestamp`** | adapter 不能统一假设 `data.timestamp`；`corporate-actions` 的 `as_of` 需另取（用 `received_at` 或事件 `ex_date_ms`） |
| 5 | **HTTP 429 真实存在**（`code=429 request limit exceeded`） | transport 必须处理 429 退避（§5.2）；探测期间密集调用即触发 |
| 6 | 五个 capability **全部已开通**（`meta` / `prices` / `valuations` / `financials` / `corporate-actions` 均无 `2001`/`2003`） | M0 通过，停点 0 解除 |

实测样本（供契约测试固定响应用，价格为**当时时点**值，会实时变化，测试只比结构不比值）：
`600519.SH` snapshot → `last_price=1290.88`（`data.timestamp` 为毫秒）；
valuations → `pe_ttm=19.816116`（含 `name=贵州茅台`）；
historical（2025 窗口，`adjust` 默认 `forward`）→ 243 条，字段 `date_ms/OHLC/volume/turnover`；
financials `period=annual` → 4 期，含 `fiscal_year/fiscal_period/report_date_ms/period_end_ms`；
`corporate-actions` → 30 条事件，含 `ex_date_ms/dividend_per_share/per_share_bonus`。

> 探测脚本：`.scratch/ths-market-data/probe_capability.py`（capability）与
> `probe_contract.py`（参数 / 信封），凭据只读环境变量、不打印 Key。

### 2.2 错误码（转成工具层可执行的提示）

| code | 含义 | 工具层行为 |
|---|---|---|
| 0 | 成功 | — |
| 1001 / 1002 / 1003 / 1004 | 参数缺失 / 格式错 / 越界 / 冲突 | `ok=false` + 指名哪个参数（如「财务 `start`/`end` 必须成对」） |
| 2001 / 2003 | 未认证 / 无权限 | `ok=false` + 提示检查 `THS_API_KEY` 与该 capability 权限 |
| 3001 / 3002 / 3004 | 标的不存在 / 数据未就绪 / 类型不支持 | `ok=false` + **提示先用 `market_resolve` 消歧**（对齐 `corpus_fetch` 找不到时引导下一步的风格） |
| 4001 | 限流 | 退避重试（见 §6.2），仍失败则 `ok=false` 且**绝不返回旧值冒充新值** |
| 5001–5003 | 服务/上游异常 | 重试一次后 `ok=false`，记 observability（进程内计数 + 可选日志） |

---

## 3. 接入形态选型

### 3.0 接入方式总论：先澄清「回调」，再看「三方式本质」

**该服务没有回调机制。** REST 是请求-响应，MCP 也是 http 传输（客户端配置 `type: http`），
官方**未提供 WebSocket / 长连接推送 / webhook**。所以「回调失败」在本项目等价于
**「取数请求失败或回包异常」** —— 失败是**同步可见**的，不会异步打进来。

这其实是个好消息：失败点明确、可当场降级，不必处理消息乱序 / 重放 / 消费幂等那一套。

**先纠正一个常见误解：REST / MCP / SDK 不是三种「传输层」。** 三者底层都走同一条
`HTTPS + X-api-key` 链路，差别只在**封装抽象层**：

| 方式 | 本质 | 谁来封装 | 是否带本地存储 |
|---|---|---|---|
| 裸 REST 端点 | `GET/POST` + JSON | 我们（自建 client） | 否（取回即用） |
| 官方 MCP（http 传输） | REST 之上加「工具发现 + 结构化调用」协议 | 供应商（MCP server）+ 官方 mcp 客户端 | 否（按需、无状态） |
| 官方 Python SDK | REST 之上加「客户端对象 + 本地 DuckDB 缓存（`marketdb`）」 | 供应商 | **是**（自动落本地 DuckDB） |

所以讨论焦点不是「能不能连上」，而是：**谁来封装、封装到什么程度、是否引入额外本地存储
与同步行为、以及能否挂进我们的硬闸 / 审批体系。** 三种方式各自的合理定位见 §3.1，
本模块的最终选择见 §3.3。

| 方式 | 本服务可用性 |
|---|---|
| 裸 REST 端点（本模块用到的 6 个） | ✅ 官方主能力，跨平台 |
| 官方 MCP（4 端点 / 55 工具，http 传输） | ✅ 可用 |
| 官方 Python SDK（源码安装，带 DuckDB） | ✅ 可用 |
| WebSocket / 推送 / webhook | ❌ 服务未提供（将来若提供也不进主链路，见 §5.0） |

**调用时机：全部按需（本模块无跑批、无后台任务）**

> Agent 调工具的当下才去拉取，取回即用、用完即弃。没有「本地快照」可查、没有「陈旧值」可退——
> 这反而让失败语义干净：**要么拿到当次真实响应，要么明确失败**（§6）。
> 断网时直接用研报证据出卡（§6.4），而不是卡死。

> 将来若供应商提供推送：**只换 `transport/`**（§5.0 的端口设计保证上层无感）。

### 3.1 三方权衡矩阵（中性，结论见 §3.3）

下面按维度逐一比较，所有比较都基于「本服务」现状（无推送）。先摆事实，再给各自的合理场景。

**① 能力覆盖**
- **REST 裸端点**：我们只用到 6 个，但端点集本身是完整能力面——历史 / 全量（dump）/ 财报 / 复权因子都能取到，只是要自己拼装与口径归一。
- **MCP**：开箱即用的 55 个工具，覆盖最广最省事；但工具粒度细、数量多，需要裁剪才适合给 LLM。
- **SDK**：能力等同甚至超过 MCP（含 dump 全量导入、本地缓存查询），且提供编程友好的对象 API。

**② 依赖与跨平台**
- **REST**：仅 `httpx`，零平台约束，最易跟随我们发行。
- **MCP**：需官方 `mcp` 客户端库（纯 Python、跨平台），但工具 schema 由 server 动态下发，我们对其演进无控制。
- **SDK**：需从 GitHub monorepo **源码安装**（`pip install -e ./python`，非 PyPI），自带 `marketdb`（DuckDB）——引入第二个本地存储引擎与一套我们不可控的同步行为。

**③ 本地存储 / 落库倾向**
- **REST**：不落库，取回即用、用完即弃——与「本模块不落库」边界天然一致。
- **MCP**：无状态按需，不落库。
- **SDK**：自动落本地 DuckDB（`marketdb`）——在「高频复读 / 回测」场景是**资产**，但在「PG 单一收口、本模块不落库」的生产约束下是**额外耦合**，会与存储治理冲突。

**④ 与硬闸①（数字可溯源）对接**
- **REST（自建 `@tool`）**：可强制返回 `quote_text` + 留痕（§5.3 / §5.5）；每个数字带 `as_of` 时点 + `source` + `request_id`，硬闸①可**证伪来源与时点**（价格是实时时变的，不要求"冻结值相等"，只要求值确实出自标注时点的真实调用、未被篡改 / 编造）⇒ 通过（§5.5）。
- **MCP 裸挂**：LLM 直接吃自由 JSON，既无 `quote_text` 规范、又无 run 目录留痕、且绕过 `apodex` 的 allowlist / 审批 ⇒ **来源与时点均不可证伪**，硬闸①失效（§3.3）。
- **SDK 旁路（回测 / 研究脚本）**：不进 Agent 主链路、不经硬闸，本就不是给 LLM 直接喂数，无所谓失效——它面向人写的研究程序。

**⑤ 对 Agent 工具表的适配**
- **REST**：字段由我们定义返回契约，工具表可控（4 个 `@tool`），模型选择成本低。
- **MCP**：55 个工具若直接挂会挤占工具表、抬高误用风险；需裁剪或包一层才能进受控工具表。
- **SDK**：本质是人写程序的客户端库，**不适合直接暴露给 LLM**，只能作为工具的实现后端或旁路。

**⑥ 调用配额压力**
- **REST / MCP**：每次调用都打一次 API（MCP 底层仍是 REST）。
- **SDK**：本地 DuckDB 缓存可显著减少重复 API 调用——高频 / 批量场景优势明显，低频场景无意义（本模块按需、低频，压力可忽略）。

**⑦ 人工探索 / 调试体验**
- **REST**：需自己写调用，人用不友好。
- **MCP**：装在 Claude Desktop / Cursor 里查数**极其方便**，是它的核心价值。
- **SDK**：在 Python 脚本 / 回测框架里调用方便，适合工程师做研究。

**⑧ 维护成本**
- **REST**：需自建并维护 adapter（但只 6 端点，体量小），官方字段变更要我们自己跟。
- **MCP**：schema 动态下发，供应商改了我们自动跟上，但工具行为不完全可控。
- **SDK**：供应商维护客户端，但 DuckDB schema / 同步逻辑我们兜底不了。

**⑨ 未来推送适配**
- 三者当前都无真推送。若将来供应商提供，REST 端口设计可只换 `transport/`（§5.0）；MCP / SDK 由供应商在其侧升级，我们跟随。

**各自的合理适用场景（不偏颇）**
- 选 **REST 自建**：生产 Agent 主链路、必须过硬闸 / 审批、字段自定、低频按需、严禁引入额外本地存储。
- 选 **MCP 直接挂**：人工探索 / Ad-hoc 分析（装桌面客户端）；或作为**跨 Agent 框架的统一工具协议**——但生产链路要包一层 `@tool` 负责 `quote_text` + 留痕，否则硬闸失效。
- 选 **SDK**：回测 / 批量历史研究 / 因子计算 / 需要全量 dump 与本地缓存的高频研究——这些场景本就不走硬闸，DuckDB 反而省 API、提速度。

> 注：v1.0 假设的 **iFinD SDK / Windows 常驻 bridge** 已作废——数据源是同花顺 fuyao 的标准 HTTP 接口，不需要常驻 Windows 机（见 §1 变更说明）。

### 3.2 adapter 可替换

`plugins/market/adapters/` 保留 `fuyao_rest`（默认）、`mock`（测试）、`csv`（离线兜底）三种实现，
`MarketService` 只依赖 adapter 协议 —— 与 corpus 的「服务层收口、存储可替换」是同一条原则：
**换供应商时只改 adapter，工具与硬闸不动。**

### 3.3 本模块定论：主链路走自建 REST `@tool`，MCP / SDK 用在对的位置

综合 §3.1 的权衡，在本模块的约束下——**不落库、无 Windows 依赖、仅用 6 个端点、必须过硬闸①、按需低频**——最终选择 **REST 自建 `@tool` + `MarketService`**：跨平台、零额外存储、字段自定、可强制 `quote_text` + 留痕，硬闸①可**证伪来源与时点（价格实时变化，不冻结值）**。

**为什么主链路不直接裸挂 MCP（重要）**

MCP 在人工探索场景价值很大（见 §3.1），但**裸挂进生产 Agent 主链路**会让硬闸失效：

| 问题 | 后果 |
|---|---|
| 数字不经主链路 | 直接喂 LLM 的数字既无 run 目录留痕、又无规范 `quote_text` ⇒ `verify` 无从比对，硬闸①彻底失效 |
| 无规范 `quote_text` | 模型接收的是自由 JSON，可以随意改写数字（"约 1685 元"） |
| 不走 allowlist / `_READ_ONLY` / 审批 | 绕过 `apodex` 的治理，55 个工具也不会出现在我们受控的工具表里 |
| 55 个工具挤占工具表 | 模型选择成本与误用风险同步上升 |

⇒ **MCP 用在对的位置**：人工探索与 Ad-hoc 分析（装 Claude Desktop / Cursor 查数很方便），
以及作为**跨 Agent 框架的统一工具协议**。若想在生产链路复用 MCP 的工具能力，**应包一层
`@tool`**——由我们的 `MarketService` 补上 `quote_text` + 留痕，再交给 LLM，而不是裸挂。

⇒ **SDK 同样不进主链路**（§3.1 维度③/④：自带 DuckDB 与「PG 单一收口、本模块不落库」冲突），
但它是**回测 / 批量研究**的正确工具，与本模块主链路互不排斥——两条链路各取所需。

---

## 4. 数据范围（V1 最小集）

> 「频率」一列在**不落库**的前提下没有意义——价格实时变化，每次调用取的是**当下最新快照**（数据时点由 `as_of` 标注），故改为「**Agent 什么时候会调它**」。
> 全部是**按需调用**，没有后台任务；引用的价格必须带 `as_of` 以表明新鲜度（见 §5.5 `market_quote_stale`）。

| 主题 | 来源端点 | Agent 何时调用 | 用途 | V1 |
|---|---|---|---|---|
| **标的消歧** | `meta/tickers/search` | 拿到名称/代码后、取数前 | 唯一 `thscode` + **中文名**（行情快照不返回 name）；**接口不接受纯代码，这一步不可省** | ✅ 必做 |
| **最新快照** | `prices/snapshot` | 需要「现在什么价」时 | 给 `position_sizing` 的价格锚；`data.timestamp` 即 `as_of` | ✅ 必做 |
| **估值** | `valuations/snapshot` | 同上（并入 `market_quote`） | PE/PB/PS/PCF，与研报估值观点对照 | ✅ 必做 |
| **历史 K 线** | `prices/historical` | 要看走势 / 波动 / 区间时 | 单标的、`interval=1d`、窗口 ≤10 年；**默认截断，不做全量拉取** | ✅ 必做 |
| **复权因子事件** | `corporate-actions/adjustment-factors` | 需要跨除权比较时 | 自行推导前/后复权（接口只给事件流） | ✅ 必做 |
| **财务三表** | `financials/*` | 要对照「研报说的 vs 实际」时 | **用 `report_date_ms` 对齐**，防前视偏差（§9 坑 2） | V1.1 |
| 财务指标（五类） | `financials/indicators` | 同上 | 成长/盈利/偿债/营运/现金流 | V1.1 |
| 交易日历 | `calendar/trading-days` | 要判断「最新是哪天」时 | ⚠️ **只有滚动近一年**；够用于新鲜度判断，**不够用于长周期回测**（那是存储议题） | ✅ 必做 |
| 指数 / 成分股 | `a-share-index/*` | 要做同行 / 板块对比时 | 同花顺概念与行业指数成分 | V1.2 |
| 集合竞价 / 涨跌停 / 热榜 / 龙虎榜 | `special-data/*` | — | 短线情绪，与 3–6 个月持有期弱相关 | ⬜ |

> **标的映射不建表**：名称与代码每次由 `meta/tickers/search` 现查（进程内可做短 TTL 缓存，
> 不落库）。「建全量代码表」是存储议题，不在本模块。

**口径纪律（写进代码，不写进人脑）**：每个对外数字必须同时带
`as_of`（数据时点）+ `source`（端点名）+ `unit` + `currency` + `adjust`（复权口径）。
口径不一致是这类系统里**最沉默的错误来源**——数字看起来都合理，只是彼此不同源。

---

## 5. 架构：与 corpus 对称的第二条数据链路

### 5.0 模块化：四层 + 两个横切，依赖单向

目标是把「**同花顺接入** / **失败处理** / **核心业务流程**」三件事彻底拆开：
任一模块挂掉、被替换、被下线，其余模块照常跑。

```text
L0 核心业务流程（零改动）  workflows/ · corpus · position_sizing · strategy_lint · verify
        ↑ 只依赖「端口」（Protocol），永不 import plugins.market
L1 MarketService（编排）  口径归一 · 调用编排 · 错误转译 · 可选留痕（默认 no-op）
        ↑ 依赖 L2 端口；不认识 HTTP、不认识供应商、**不碰数据库**
L2 Ports（协议）          MarketPort 取数 · Clock 时间 · Sink 留痕（可选，默认丢弃）
        ↑ 由 L3 提供实现
L3 Adapters（可替换）     fuyao_rest（默认） / mock（测试） / csv（离线兜底）
L3' Transport（HTTP 治理）超时 · 退避重试 · 并发上限 · 熔断 · 单飞去重

横切 A：FailurePolicy     失败分类 · 熔断 · **失败转译**（给 Agent 可执行的下一步）
横切 B：Observability     调用日志（进程内计数 / 可选文件）· request_id 对账
                          —— 注意：是日志，不是数据库表
```

**依赖方向单向**：`L0 → L1 → L2 ← L3`。L3 **不反向依赖** L1，L1 **不认识** HTTP。

| 模块 | 路径 | 只做 | 禁止做 |
|---|---|---|---|
| Transport | `plugins/market/transport/` | 发请求、超时、退避、并发、熔断、留痕 | 认识业务字段、解析业务语义 |
| Adapter | `plugins/market/adapters/` | 端点 → 领域对象、口径归一（毫秒→date、单位、货币） | 直接写库、做降级决策 |
| Service | `plugins/market/service.py` | 口径归一、调用编排、错误转译、可选留痕 | 直接发 HTTP、抛异常给上层、**写任何数据库** |
| Tools | `plugins/tools/market_*.py` | 参数校验、调 service、返回恒定结构 JSON | 自己算数、吞掉异常、抛异常打断 ReAct |
| Failure | `plugins/market/failure.py` | 分类、熔断计数、退避参数、降级顺序 | 依赖任何具体供应商 |
| 硬闸扩展 | `plugins/corpus/verify.py` 内注入 | 只认 `Callable[[str], str \| None]` 的 resolver | 反过来 import market 的实现 |

端口骨架（实施时按仓库 `ANN` 规则补全类型注解）：

```python
# plugins/market/ports.py —— 只有协议与数据类：零依赖、零 IO、可独立 import
@dataclass(frozen=True)
class Quote:
    thscode: str
    as_of_ms: int          # 供应商 data.timestamp，天然 as_of
    last_price: float | None
    raw: dict              # 原样留存，供 quote_text 渲染与 raw_hash

class MarketPort(Protocol):
    def quote(self, thscode: str) -> Quote: ...
    def history(self, thscode: str, start_ms: int, end_ms: int, adjust: str) -> list[Bar]: ...
    def financials(self, thscode: str, statement: str, period: str, limit: int) -> list[Fact]: ...
```

**独立性是可机械验证的**（每条都要有测试，见 §8 M2c / M10）：

| 断言 | 验证方式 |
|---|---|
| 删除整个 `plugins/market` 后核心流程仍全绿 | 架构测试：`plugins.corpus.*` / `workflows.*` 的 import 图中不含 `plugins.market` |
| market 未启用时流程照常 | `MARKET_ENABLED=false` → 工具返回 `ok=false`，P0a + corpus 测试全绿 |
| transport 可无网测试 | 起本地 mock HTTP server，不需要 API Key |
| adapter 可无网测试 | 固定响应样本的契约测试（字段口径归一断言） |
| service 可无网无库测试 | 注入 `mock` adapter，**不需要 PG**（本模块无存储依赖） |
| 失败策略可无网测试 | 注入「永远失败」的 adapter，断言降级阶梯与熔断计数 |

**变更影响面（解耦的验收口径）**

| 变更 | 要改 | 不用改 |
|---|---|---|
| 换供应商 | `adapters/` 新增一个实现 + 注册 | transport 治理、service、工具、硬闸、流程 |
| 换传输（REST → 推送 / WS） | `transport/` + 推送版 adapter | service、工具、硬闸、流程 |
| 新增数据类别（如龙虎榜） | adapter + service + 1 个工具 | 传输治理、已有工具、硬闸、流程 |
| market 整体下线 | 配置开关关闭 | 全部流程（降级为「研报-only」） |
| 失败策略调整 | `failure.py` | 其余全部 |

### 5.1 分层

```text
fuyao REST（HTTPS + X-api-key，按需、同步、无后台任务）
        ↓  Transport（超时 / 退避 / 并发上限 / 熔断 / 单飞去重）
        ↓  Adapter（端点 → 领域对象，口径归一）
plugins/market/service.py   ← MarketService，唯一收口
        ↓  （可选）Sink：原始响应写进 run 目录留痕 —— 是运行留痕，不是数据库
        ↓
@tool: market_resolve / market_quote / market_history / market_financials
        ↓
Agent 直接分析  →  引用的数字写进 evidence  →  strategy_lint  →  离线 verify 三闸
```

**没有存储层**：调用结束即结束，数据只存在于这次调用的返回体里。

沿用 `data-layer-architecture.md §5` 的四条边界（对 market 同样成立）：

| 约束 | 理由 |
|---|---|
| 调用方只调 `MarketService` 接口，不直连驱动、不直接发 HTTP | 换供应商时只改 adapter |
| 服务层不向外暴露驱动对象与供应商专有类型 | 否则供应商类型泄漏到业务代码 |
| 口径（复权、单位、报告期、交易日历）**完全关进服务层** | 与 zhparser 只影响 corpus 服务层同理 |
| 调用语义保持「请求一次、返回完整契约一次完成」 | 避免「半成功响应」（部分字段缺失）被当成完整数据 |

> **import 开销**：`p0-research-kernel.md §4` 已判定「不用 `plugins/fin_data`，会拖慢
> import_smoke / ruff」。故 `plugins/market/` 内**延迟导入** `psycopg` / `httpx` /
> `pyarrow`（对齐 `corpus_fetch` 内部导入 service 的模式），保证 `--stage 1` import smoke 不受影响。

### 5.2 传输层必备行为（不是优化，是正确性）

| 行为 | 说明 |
|---|---|
| 超时与重试 | 连接/读超时（默认 10s）；对 `4001` / `429` / `5002` / `5003` **指数退避 + 抖动**重试 ≤3 次 |
| 并发上限 | 全局信号量（默认 4）；`historical` 单标的串行分片（窗口 ≤10 年） |
| 429 处理 | 退避 + 下调并发；仍失败 → `ok=false` + 明确原因。**无库可退，所以不存在"拿旧值顶上"这个选项 —— 失败语义反而更简单** |
| **单飞去重** | 同一 `(端点, 参数)` 在 60s 内重复请求**复用上次结果**（进程内，不落库）——防 Agent 反复追问同一问题打爆配额 |
| 调用留痕 | 进程内计数 + 可选写文件；**`request_id` 必须随错误一起返回给 Agent**（找供应商对账的唯一凭证） |

### 5.3 无存储：响应留痕与「将来要存」的接缝

**本模块不建任何表。** 数据只活在「一次调用的返回体」里。

#### 5.3.1 可选留痕（默认开，可关）—— 写 run 目录，不是数据库

```text
<cwd>/.apodex/runs/<session-id>/market/<request_id>.json
  {endpoint, params, code, request_id, as_of_ms, received_at, raw_response}
```

- 落点是**已有**的运行产物目录（与 `trace.jsonl` / `session.json` 同级），属于**运行留痕**，
  不是数据存储 —— 不新增部署组件、不需要建表、不需要迁移。
- 存在的唯一理由：让离线 `verify` 能比对「模型写进 evidence 的 quote」是否真出自那次调用（§5.5）。
- 关闭方式：`MARKET_TRACE=off`（关闭后硬闸①降级为「只验格式、不验真值」，见 §5.5 方案 B）。
- ⚠️ 沿用既有风险记账：留痕与 trace 一样是**明文落盘**，供应商数据同样受此约束（§7）。

#### 5.3.2 接缝：`Sink` 端口（现在默认丢弃，将来可接存储）

```python
class Sink(Protocol):
    def write(self, record: RawRecord) -> None: ...

NullSink()   # 默认：什么都不做
FileSink()   # 可选：写 run 目录（5.3.1）
# PgSink()  ← 将来存储议题要落库时实现这一个对象并注入即可
```

⇒ **将来决定要入库时，改动 = 新增一个 `Sink` 实现 + 注入**；
工具、service、失败处理、硬闸**一行不改**。这就是把存储移出本模块却不留后遗症的做法。

### 5.4 工具（V1 四个）

| 工具 | 入参 | 返回要点 |
|---|---|---|
| `market_resolve` | `query`（名称 / 代码 / thscode） | 唯一 `thscode` + 名称 + 交易所 + `asset_type`；**多义时列出候选让模型选**（接口不接受纯代码，这一步不可省） |
| `market_quote` | `thscode` | 最新快照 + 估值 + `as_of`（毫秒 + ISO + 人类可读"X 天前"）+ 规范 `quote_text` |
| `market_history` | `thscode`, `start`, `end`, `adjust="forward"` | 日线（**默认截断到 N 根**，禁止一次塞十年）；标注复权口径与"前复权随基准变化"（§9 坑 1） |
| `market_financials` | `thscode`, `statement`, `period`, `limit` | 三表 / 指标；每条带 `period_end_ms` 与 **`report_date_ms`** |

**统一返回信封**（四个工具一致，便于模型稳定解析）：

```jsonc
{
  "ok": true,
  "thscode": "600519.SH", "name": "贵州茅台",
  "as_of_ms": 1784275991000, "as_of": "2026-09-09T15:00:00+08:00", "age": "同日",
  "unit": "CNY", "adjust": "forward",          // 口径随数字一起走
  "data": { "last_price": 1277.8, "pe_ttm": 21.3567, "...": "..." },
  "quote_text": "last_price=1277.8; pe_ttm=21.3567; as_of=1784275991000",
  "caveats": ["快照不返回 name，name 来自 meta 检索"],
  "hint": "数字可直接用于分析；写入 evidence 时 quote 必须原样取自 quote_text"
}
```

**「分析友好」的四条硬要求**（这是本模块的主要价值，别让模型做脏活）：

| 要求 | 说明 |
|---|---|
| 时间可读 | 同时给 `as_of_ms`、`as_of`（ISO）与 `age`（"同日 / 2 天前"）——毫秒戳让模型换算必错 |
| 口径随行 | `unit` / `currency` / `adjust` 每次都带；前复权必须提示"随基准变化" |
| `null` 显式 | 官方 `null` = 未披露，返回体里**明写 `"未披露"` 而不是省略字段**（省略会被模型当成 0 或自行估算） |
| 不代模型做判断 | 可以给涨跌幅这类已由上游算好的量，**但不给投资结论**（"低估/高估"这类词不出现） |

**反幻觉纪律**（对齐 `corpus_search` / `corpus_fetch` 的分工）：

- 返回体同时给 `data`（用于分析）与 `quote_text`（用于引用）。**分析可以自由发挥，
  引用必须原样抄** —— 写进 evidence 的 `quote` 只能来自 `quote_text`。
- `quote_text` **直接用官方 snake_case 字段名**：不发明新字段名，少一次翻译就少一次出错机会。
- `max_result_chars=0`（不截断）：截断会切掉 `as_of` / `quote_text`，与 `corpus_fetch` 同源理由。
  历史序列的**行数**另行限制（分页 + 截断提示），靠行数而不是字符数控制体积。

### 5.5 硬闸如何扩展（最关键的一节）

**硬闸① 数字可溯源 —— 实时时变价格的溯源语义（最关键）**

**比对目标不是「值等于某个冻结快照」，而是「来源与时点真实、数值未被篡改 / 编造」。**
价格是实时时变的：同标的在不同时点取到的快照本就不同，前复权序列还会随基准漂移（§9 坑1）。
因此硬闸①对市场数据**不要求**"模型写的值 == 权威静态值"；它要求的是：

1. 模型引用的数字带 `source_ref`（含 `request_id` / `as_of` / 端点），且该 ref 在留痕中对应**一次真实调用**；
2. 引用的数值**落在那次响应的值域内**、且字段 / 复权口径与留痕一致 —— 即"未被模型改写、不是凭空编造"；
3. 标注的 `as_of` 与留痕调用一致 —— 即"没有挪用旧时点价格冒充当前"。

真正要挡住的是：**无 `source_ref` 的凭空价格**、**跨时点挪用**、**跨复权口径混用**。
（注意：这比 corpus 的"静态研报逐字比对"语义更松，但更贴合行情本质——我们证明"这个价格来自那次标注时点的真实调用"，而非"价格被冻结成真理值"。）

现有 evidence 结构 `{source_ref, page, quote, kind}`（必填四键），`verify._gate_traceability`
用 `resolver(source_ref)` 取回文本后判 `quote in text`。市场数据**没有「逐字原文」但可渲染出那次
真实响应**；不落库后，这个"渲染物"有两个来源，取决于留痕开关：

| 方案 | 条件 | 能证明什么 | 不能证明什么 |
|---|---|---|---|
| **A 留痕比对**（默认） | 响应留痕开启（§5.3.1） | `quote` 子串命中**那次真实调用响应** ⇒ 值确实出自标注 `as_of` 时点的真实调用、未被篡改 / 编造；`source_ref` 对应一次真实调用 | 不证明供应商数据本身正确；也**不证明"该值永久不变"**（价格实时变化，晚些再取可能不同，这是正常的） |
| **B 哈希自证**（留痕关闭） | `MARKET_TRACE=off` | `quote` 与工具给出的 `quote_sha256` 一致 ⇒ **未被改写** | **不证明供应商真返回过**；该闸须标 `partial`（按 verify 既有语义：验不了 = 没验过，`strict` 下不通过） |

⇒ **留痕默认开启**。关掉等于主动下调可校验性，需要显式接受这个代价。

```jsonc
// sources 段（SOURCE_LOCATOR_KEYS 要求 id + url/title 之一）
{"id": "ths:600519.SH:<request_id>",
 "title": "同花顺行情/估值 600519.SH as_of=2026-09-09T15:00:00+08:00"}

// evidence 段
{"source_ref": "ths:600519.SH:<request_id>",
 "page": "2026-09-09T15:00:00+08:00",      // schema 已允许非页码：URL 或锚点（即 as_of 时点）
 "quote": "last_price=1277.8; pe_ttm=21.3567; as_of=1784275991000",
 "kind": "fact"}
```

- `kind` **不新增枚举**：行情 / 估值 / 已披露财报 = `fact`；研报里的目标价与预测 = `forecast`
  （已在 `FORWARD_LOOKING_KINDS` 内）。`strategy_lint` 的 kind 校验无需改动。
- `page` 填 `as_of` 的 ISO 时间：**不触发** `PAGE_PLACEHOLDERS` 占位符判定 —— schema 注释已
  预留「网页/接口类来源没有 PDF 页码，应填 URL 或锚点」。
- `resolver` 扩展为**按前缀分派**：`ths:` → 读 run 目录留痕并渲染**那次真实响应**；否则 → corpus 全文。
  ⇒ **`verify` 复用的仍是 `quote in text` 子串命中逻辑，一行不改**，只是多一个解析分支；
  差异在于行情渲染必须带上 `as_of` 锚点，且比对语义从「值相等」放宽为「来源时点命中 + 值域可比」。
  `verify` 侧新增 `--market-trace <dir>` 指向 run 目录（不给 ⇒ 方案 B）。
- 渲染函数必须**确定性且字段顺序固定**，否则同一次响应两次渲染不一致会变成随机误判。

**硬闸② 算术不出 LLM —— 不变，加一条衍生量约束**

`position_sizing` 契约不动。新增：市场衍生量（ATR、波动率、区间幅度、回撤）
**同样必须由确定性工具产出**并带 `computed_by`（如 `market_stats@v1`），
禁止模型「看 K 线自己估」。

**硬闸③ schema 完备 —— 不变**（止损 / 失效条件 / 时间窗）。

**新增检查（先 WARN，跑顺再升 ERROR）**

| 检查 | 判据 | 级别 |
|---|---|---|
| `market_ref_malformed` | `ths:` ref 不合法（`thscode` 段须匹配 `^\d{6}\.(SH\|SZ\|BJ)$`，须带 `request_id`） | ERROR（悬空引用） |
| `market_quote_stale` | `as_of` 距策略形成时点超过 N 个自然日；`data.timestamp` 为 `null` 视同 stale | WARN（无日历表时按自然日粗判） |
| `price_out_of_band` | `entry.low/high` 与 `last_price` 偏离超阈值 | WARN（提示复核，不阻断） |
| `adjust_mismatch` | 同一张卡混用不同复权口径 | ERROR（口径混用必错） |
| `financial_lookahead` | 用了 `report_date_ms` **晚于**策略形成时点的财报数据 | ERROR（前视偏差，见 §9 坑 2） |

### 5.6 打通点：现在 → 接入后

| 环节 | 现在 | 接入后 |
|---|---|---|
| 标的确认 | 用户口述 / 研报标题 | `market_resolve` 消歧为唯一 `thscode`（**接口不接受纯代码，这一步不可省**） |
| 研报检索 | `corpus_search` → `corpus_fetch` | **不变**；增加「研报发布日 → 取当日行情上下文」（事件对齐） |
| 观点 vs 现实 | 无 | 研报盈利预测 ↔ `market_financials` 实际值（**按 `report_date_ms` 对齐**）⇒ 预期差证据 |
| 入场 / 止损 | 模型给价 | 现价 + ATR 给锚；`price_out_of_band` 提示复核 |
| 仓位计算 | `position_sizing` | **不变**，但输入从「拍的」变成「有锚的」 |
| 在线校验 | `strategy_lint` | 增 5 条检查（§5.5） |
| 离线校验 | `verify` 三闸 | resolver 支持 `ths:` 前缀；三闸不退化 |
| 回测 D5 | 🅿️ 无行情源 | 本模块只**提供取数工具**；真正的回测要历史数据存储 ⇒ 仍属存储议题，**不在本模块解锁** |
| 挖掘 D3 / 共识 D4 | 等 B1 全量 | 加行业成分与行情后可行（V1.2） |
| Web / 看板 | — | `server/` 侧只读接口**复用 `MarketService`**，不另写 SQL（沿用 G 组硬约束） |

> 端到端不变的是纪律：LLM 只做「选什么、为什么」，**所有数字仍由确定性工具产出并校验**。
> 接数据没有改变这个分界线，只是把「数字」的范围从研报扩大到了市场。

### 5.7 接线清单

**新增**（按 §5.0 分层落位，每层一个目录/文件）：

| 层 | 文件 |
|---|---|
| L2 端口 | `plugins/market/ports.py`（Protocol + 数据类，**零依赖零 IO**） |
| L3 传输 | `plugins/market/transport/{client,retry,circuit_breaker}.py` |
| L3 适配器 | `plugins/market/adapters/{base,fuyao_rest,mock,csv}.py` |
| L2 留痕接缝 | `plugins/market/sink.py`（`NullSink` 默认 / `FileSink` 可选 / 将来 `PgSink`）· `trace_store.py`（留痕读写 + 供 `verify` 的 resolver） |
| 横切 | `plugins/market/failure.py`（分类 / 熔断 / 失败转译）· `plugins/market/observability.py`（进程内计数 + 可选日志） |
| L1 服务 | `plugins/market/service.py`（注入式构造 + `health`）· `render.py`（`quote_text` 确定性渲染） |
| L4 工具 | `plugins/tools/market_{resolve,quote,history,financials}.py` |
| 测试 | `tests/test_market_{transport,failure,adapter,service,verify}.py` · `tests/test_market_isolation.py`（M10） |

> **不新增** `docker/initdb/*.sql`、不引入 `pyarrow`、不新增任何 PG 表。

**改动（新增工具必须改全，P0a 实测 7 处 / 5 个文件）**：

| # | 文件 | 改什么 | 漏改后果 |
|---|---|---|---|
| 1–2 | `plugins/tools/__init__.py` | `import` + 加入 `_BUILTIN_TOOLS` allowlist | **工具不存在**（加文件不等于可访问） |
| 3 | `plugins/tools/meta.py` | `TOOL_META`：`is_read_only=True`、`category="finance"`、`timeout`（网络 ≥15s）、`max_result_chars=0` | 默认 45s / 截断策略不对 |
| 4 | `apodex/agent_tools.py` | `reg.setdefault(...)` + 加入 `_READ_ONLY` | 不带 `-y` 时每次调用都要人工点确认 |
| 5 | `apodex/profiles/react.yaml` | 工具名清单 | TUI 侧不可见 |
| 6 | `workflows/stateful_react_agent/profiles/tui.yaml` | `agent.agent_tools` | **工具不出现在模型可见工具表里** |

另需改动：`plugins/corpus/verify.py`（resolver 支持 `ths:` 前缀，**由调用方注入，不反向 import market 实现**）、
`plugins/corpus/strategy_schema.py`（新增 market 相关常量与提示，不改 `EVIDENCE_KINDS`）、
`.env.example`（`THS_API_BASE_URL` / `THS_API_KEY` / **`MARKET_ENABLED`** —— 总开关，
关闭时工具恒定 `ok=false`，核心流程退化为今天的形态）。

---

## 6. 失败处理：任何时候都不拖垮主流程

> 前提（§3.0）：本服务是**同步请求-响应**，没有异步回调。
> 因此「接口回调失败」= **取数请求失败或回包异常**，失败点当场可见、当场降级。

### 6.1 先分类，再谈处理

| 类 | 触发 | 是否重试 |
|---|---|---|
| 网络 / 超时 | 连接失败、读超时 | 是（≤3 次，指数退避 + 抖动） |
| 限流 | HTTP 429 / `code=4001` | 是（更长退避，同时下调并发） |
| 鉴权 | `2001` / `2003` | **否** —— 重试无意义，直接 fail-fast 并告警 |
| 标的 / 数据 | `3001` / `3002` / `3004` | 否 —— 引导 `market_resolve` 消歧或换标的 |
| 上游异常 | `5001`–`5003` | 是（1 次） |
| **解析失败** | 字段缺失 / 类型漂移 / `data` 为 `null` | 否 —— 判为**契约破坏**，见下 |

> **解析失败要单独当回事**：它意味着供应商静默改了字段。此时返回 `ok=false`
> 并保留 `raw_json` 供事后对账，**绝不猜一个值填进去**——猜值等于把「数据缺失」
> 升级成「数据编造」，而后者正是三条硬闸要挡的东西。

### 6.2 四道防线（分层拦截，各层只做自己那件事）

| 层 | 机制 | 失败时行为 |
|---|---|---|
| **Transport** | 超时 10s、退避重试、并发上限（默认 4）、**熔断**（连续 N 次失败 → 60s 内快速失败） | 抛**领域异常**（`MarketUnavailable`），**不把 `httpx` 异常往外传** |
| **Service** | 失败转译（§6.3）+ 部分成功 `partial` | 见 §6.3 |
| **Tool** | 恒定返回结构 + 可执行 `hint` | `ok=false`，**绝不抛异常打断 ReAct 循环**（对齐 `corpus_search` / `corpus_fetch` 的风格） |
| **流程 / 硬闸** | 数据缺失 ≠ 数据编造 | 见 §6.4 |

**熔断不是优化，是正确性**：Agent 一轮会话可能连调十几次工具，没有熔断时每次都要等满超时，
整轮被拖垮；熔断后快速失败，Agent 立刻知道「这条路不通」，转向研报证据而不是干等。

### 6.3 失败后给 Agent 什么（不落库 ⇒ 没有"退而求其次"这个选项）

```text
① 成功                     → 正常返回，带 as_of / 口径 / quote_text
② 可重试失败（网络/超时/429/上游）→ transport 内退避重试 ≤3 次后仍失败 → ③
③ 不可重试失败（鉴权/参数/标的/解析）→ 直接 ③
④ 熔断中                   → 直接 ③，连请求都不发（快速失败，别让 Agent 干等）
```

**③ 的返回体（关键）**：`ok=false` + `reason`（人话）+ `request_id` + `next`（下一步）。
例：

```jsonc
{"ok": false, "reason": "行情服务限流（code=4001），已重试 3 次",
 "request_id": "b9f91af9...",
 "next": "价格数据现在拿不到。请先用 corpus 的研报证据继续分析，"
         "并在结论里说明「价格未校验」——不要推测或估算价格。"}
```

两条铁律：

1. **失败必须"可执行"**：错误信息里要写清**下一步做什么**（换标的 / 先消歧 / 走研报证据 /
   稍后重试），否则模型只能瞎试或自行编数。
2. **绝不用估算值顶替** —— 没有库就没有"旧值"，这反而消除了一整类"拿陈旧数据冒充最新"的错误。
   **失败就是没有数，模型必须按"没有数"来分析。**

### 6.4 对业务流程的影响：可以降级，但不能降级纪律

| 情形 | 策略卡怎么办 | 校验行为 |
|---|---|---|
| 行情取不到 | 该维度留空，卡里记 `market_data_unavailable` 与原因 | 新增 **WARN**（不阻断）：缺的是数据，不是作者的责任 |
| 只有研报证据 | 允许落「研报-only」卡，thesis 中说明未做价格校验 | 正常通过（现有逻辑不变） |
| 模型在无数据时**自己填了价格** | `source_ref` 无法解析 ⇒ `quote` 比对失败 | **硬闸① ERROR，必须挡住** |
| market 整体不可用 | `MARKET_ENABLED=false`，工具恒定 `ok=false` | 流程退化为今天的形态，全绿 |

⇒ 这就是「失败不影响其他业务流程」的准确含义：
**流程不会因为取不到数而崩，也不会因为取不到数而放松校验。缺数据可以出卡，编数据不行。**

### 6.5 多标的 / 多端点调用时的失败隔离

Agent 可能一次要多家公司对比（`market_quote` 批量 或 连续多次调用）：

- **部分成功要讲清楚**：`ok=true` 但 `partial: [{thscode, reason}]`，成功的照常给，
  失败的列原因 —— 不让一个标的的失败毁掉整次对比。
- **并行调用时相互隔离**：一个请求超时不影响其他（transport 并发上限 + 单请求独立超时）。
- **熔断是全局的**：连续失败触发后，后续调用快速失败并**明确告知"已熔断，N 秒后恢复"**，
  避免 Agent 反复重试把配额打满。

### 6.6 可观测（进程内，无表）

进程内维护：调用次数、失败分类计数、连续失败数 / 熔断状态、最近 `request_id` 与错误。
可选写日志文件（§5.3.1 同目录）。`python -m plugins.market.service health` 输出上述状态。
`request_id` 是与供应商对账的唯一凭证，**必须随错误返回给 Agent**。

---

## 7. 凭据与合规

| 事项 | 要求 |
|---|---|
| API Key 保管 | 走环境变量 / `.env`（已被 gitignore）；**禁止写进示例脚本、日志、trace、Git**。文档明确要求这点 |
| trace 风险 | `corpus_fetch` 已有「研报原文全量落 JSONL」的记账风险；行情 payload 同样会落 trace ⇒ **工具返回体脱敏策略需在 M5 一并评估**（沿用既有风险记账，不在本文展开） |
| 使用范围 | 内部研究；**禁止**对外提供明细数据 / 批量再分发 |
| 演示与文档 | 沿用 P0 纪律：**演示与文档不引用真实行情数字** |
| 留痕 | 进程内调用计数 + 可选写 run 目录（§5.3.1）；每次取数带 `request_id` ⇒ 可对账可审计 |
| 权限 | 部分 capability 需单独开通（无权限返回 `code=2003`）⇒ M0 需确认账号已开通所需 capability |

**配置放在哪里（唯一来源：环境变量 / `.env`）**

对齐既有约定（corpus 用 `CORPUS_DSN`、web 用 `SERPER_API_KEY` / `JINA_API_KEY`）——
**凭据只在 `.env` 里，禁止写进示例脚本、日志、trace、Git**。已在 `.env.example` 建好条目：

| 变量 | 必填 | 默认 | 谁读它 | 缺失 / 关闭时的行为 |
|---|---|---|---|---|
| `THS_API_KEY` | ✅ 唯一必填 | — | `MarketService` → transport 发 `X-api-key` 头 | 工具恒定 `ok=false` + 明确 `reason`（凭据缺失），**不静默返回空数据、不拖垮主流程** |
| `THS_API_BASE_URL` | 可选 | `https://fuyao.aicubes.cn` | transport 拼端点路径 | 用官方默认基址 |
| `MARKET_ENABLED` | 可选 | `true` | 工具注册 / 服务层**总开关** | `false` ⇒ 工具恒定 `ok=false`，核心流程退化为未接入形态（M10 隔离测试依赖此开关） |
| `MARKET_TRACE` | 可选 | `on` | `sink.py`（留痕接缝） | `off` ⇒ 不写 run 目录，硬闸①降级为方案 B（哈希自证，闸标 `partial`，`strict` 下不通过） |

> 读取方式沿用 corpus 的做法：`os.environ.get(...)` + **注入式构造**
> （`MarketService(adapter=..., sink=...)`），因此测试可用 `mock` adapter 与 `NullSink`
> 完全不碰真实凭据、不发网络请求——这也是 M2c / M3「**不需要 API Key**」能成立的前提。

---

## 8. 任务清单（M 组）

| # | 任务 | 依赖 | 状态 | 要点 / 验收 |
|---|---|---|---|---|
| M0 | 凭据与 capability 确认 | — | ✅ **停点 0 已解除** | API Key 已配置（`.env`）；**五个 capability 全部已开通**（meta / prices / valuations / financials / corporate-actions，均无 `2001`/`2003`）。实测契约见 **§2.1.1**（参数名 `thscodes` vs `thscode`、`period` 字面量、信封差异、429 确认） |
| M1 | **标的消歧**（不建表） | M0 | ✅ | 名称 / 代码 → 唯一 `thscode` + 中文名；多义时列候选。进程内短 TTL 缓存，**不落库**。验收通过：`tests/test_market_service.py` ——「茅台」「600519」「600519.SH」得到同一结果；**实测补充**：`meta/search` 接受纯代码（`600519`→`600519.SH`），但 `000001` 会同时命中场外基金与 A 股 ⇒ 已实现「按资产类型优先 + **被丢弃候选仍列 `other_candidates`**」，避免静默拿错标的 |
| M2a | `transport/` HTTP 治理 | M0 | ✅ | 超时（10s）/ 退避+抖动（≤3 次）/ 并发上限（4）/ **熔断** / 单飞去重 + 进程内 observability 计数。**已落地**：`plugins/market/ports.py`（领域对象 + `MarketUnavailable`）+ `transport/{client,retry,circuit_breaker}.py`。验收通过：`tests/test_market_transport.py` 17 项（超时 / 429 / 500 行为正确、**无 `httpx` 异常外泄**、单飞去重只发 1 次、熔断快速失败、参数错误不重试） |
| M2b | `failure.py` 失败策略 | M2a | ✅ | 六类失败分类 + **失败转译**（§6.3，返回 `reason`+`request_id`+`next`）+ 部分成功 `partial`。验收通过：`tests/test_market_failure.py` 14 项（六类均有可执行 `next`、`request_id` 随错误上抛、`call_or_fail` 兜住未预期异常） |
| M2c | `fuyao_rest` adapter | M2b | ✅ | 端点 → 领域对象、口径归一、错误码映射（§2.2）。**已固化 §2.1.1 实测契约**。验收通过：`tests/test_market_adapter.py` 9 项契约测试，**不需要 API Key**（参数名 `thscodes`/`thscode`、`period` 字面量、毫秒窗口、无 `timestamp` 信封、**返回条数 > 请求条数 ⇒ 判定返回全市场并失败**、>100 分片） |
| M3 | `MarketService`（**无存储**） | M1, M2c | ✅ | 注入式构造 `MarketService(adapter=..., sink=...)`；口径归一；`quote_text` 确定性渲染。验收通过：`tests/test_market_service.py` 14 项（注入 `mock` 时**不发网络请求、不连数据库**；估值失败不影响行情；`quote_text` 渲染确定性） |
| M3b | 留痕接缝 + resolver | M3 | ✅ | `NullSink` / `FileSink`（run 目录）+ `verify --market-trace` 已接齐：market 侧（`sink.py` / `trace_store.py` + service 聚合留痕）此前已备，本次补上 **verify 侧接线**——CLI `--market-trace <dir>` 构造 resolver 注入（延迟 import，verify 核心不依赖 market 实现，§5.7 纪律）。验收通过：留痕开时方案 A 命中（`tests/test_market_gate.py`）；未给 `--market-trace` 时该闸 `skipped`、`strict` 下整卡不通过（方案 B 语义） |
| M5 | 四个 `@tool` + 6 处注册点接线 | M3 | ✅ | 严格按 §5.7 接齐 6 处（`__init__` allowlist / `meta.py` / `agent_tools.py` + `_READ_ONLY` / `react.yaml` / `tui.yaml`，`timeout=15`、`market_quote` 不截断）。验收通过：`tests/test_tool_registry.py` 8 项 + **真实凭据端到端 smoke**（`market_resolve`「茅台」与「600519」同结果、`market_quote` 拿到实时价 `1290.88` 且带 `as_of`、`market_history` 3 条日 K、`market_financials` 2025 FY 含披露日）。注：同步更新了 `EXPECTED_TOOLS`（新增工具必须改，否则该断言失败） |
| M6 | 硬闸①扩展 + 回归 | M5, M3b | ✅ | **已实现（§5.5 表的 5 条全做）**：① corpus 溯源闸**跳过 `ths:` 引用**（此前真的市场数字也会被判「无法解析」⇒ 进不了卡）；② 新增**市场溯源闸**（`GATE_MARKET`）：`ths:` 引用须在留痕中逐字命中，未给 `--market-trace` ⇒ `skipped`（strict 下不通过）；③ 一致性检查：`market_ref_malformed`（ERROR）/ `market_quote_stale`（WARN）/ `price_out_of_band`（WARN）/ `adjust_mismatch`（ERROR）/ `financial_lookahead`（ERROR），WARN 不阻断、单独进 `report["warnings"]`。<br>**验收通过**：`tests/test_market_gate.py` 8 项（真留痕通过 / 编造 `quote_not_found` 精确指认 / 无留痕降级 / 口径混用 ERROR）；**回归红线达成**：corpus 全链路 + 黄金题 + strategy_lint 共 88 项全绿不退化 |
| M7 | 黄金题扩展（市场类） | M6 | ✅ | **`tests/test_market_golden.py` 6 项，命中率 100% 达成**：现价（`quote_text`）/ 历史区间（`close_price`）/ 财报（`operating_income`）三类黄金题合一，`traced/total == 3/3`；反向验证编造数字立即跌破命中率并 `failed`；复权口径（`adjust=none`）可从留痕取证。<br>**过程中修复两个真实缺陷**：① 聚合留痕（service 的 sink）与 raw 留痕（transport 的 sink）是**两个接缝**，漏配任何一个，对应引用就溯源不了；② `render_raw_record` 此前不渲染 `data` 层标量 ⇒ 复权口径在留痕里查不到。<br>**已知局限**：`request_id` 暂未用于**精确锁定那次调用**（resolver 按 thscode 渲染该标的全部留痕）——合并 `quote_text` 跨行情+估值两次调用，单个 rid 本就无法覆盖；防编造不受影响（编造值不会出现在任何留痕），精确锁定留作加强项 |
| M9 | （可选）Web 侧转发 | M3 | 🅿️ | `server/` 转发调用 `MarketService`，无直连 SQL、无缓存表 |
| **M10** | **模块隔离架构测试** | M3 | ✅ | 断言 `plugins.corpus.*` / `workflows.*` 的 import 图**不含** `plugins.market`（AST 静态扫描，未发现反向依赖）；`MARKET_ENABLED=false` / 缺 Key 时 `unavailability()` 给出可执行失败、`build_service()` 返回 `None`。对应 §5.0「独立性可机械验证」 |
| **M11** | **失败注入端到端** | M5, M2b | ✅ | 断网 / 429 / 500 / 超时 / 字段漂移五类注入。断言通过：`tests/test_market_failure_injection.py` 6 项——工具 `ok=false` + 可执行 `next`、**无异常冒泡**、字段漂移得 `null` 而非 `0`、失败计入 observability。对应 §6 |
| **M12** | `market_stats`（**可观察形态**） | M5 | 🅿️ **待办（已记录，暂不实现）** | **问题**：`market_history` 实测返回 **243 行 OHLC**，模型面对几百行数字**看不出趋势**——这是「有数据但观察不到」，不是「没有数据」。<br>**方案**：确定性工具输出**区间高低 / 均线（5·20·60）/ 波动率 / 最大回撤**，并带 `computed_by`（硬闸②）。<br>**价值定位**：主要不是合规，而是**让模型能看见**——面对 243 行它"看"不出均线，给 4 个数字就能判断（价格在 MA20 上方、回撤 12%）；`computed_by` 是顺带满足的。<br>**待拍板**：见 §10 第 6 条 |

**可并行**：M1 与 M2a 无依赖；M 组整体与 P1 的 B1（语料全量）**可并行**，
只有 D3 / D4 需要两边都就位。

---

## 9. 三个接口层的坑（写代码时必须处理）

| # | 坑 | 说明 | 对策 |
|---|---|---|---|
| 1 | **前复权序列会变** | `adjust=forward` 以「最新」为基准重算，不同时间点拉到的历史前复权值会不同 ⇒ Agent 多次调用可能看到同一标的"前后不一致"的前复权数字；硬闸①要求**引用的 `as_of` 与留痕调用一致、数值未被跨时点挪用** | **给 Agent 默认 `adjust=none`（不复权）**；需要前复权时在 `quote_text` 固定标注口径与 `as_of`，并提示"前复权随基准变化、跨次调用不可比"。本模块不落库，无"存了漂移值"问题，但返回必须明确口径（§5.4） |
| 2 | **前视偏差** | 财报有 `period_end_ms`（报告期末）与 `report_date_ms`（披露日）；用错就会「用未来数据解释过去」 | 工具返回**两列都带**，`market_financials` 默认按 `report_date_ms` 排序；`financial_lookahead` 在 `verify` 侧执行（evidence 引用的 `report_date_ms` 不得晚于策略形成时点） |
| 3 | **交易日历只有滚动近一年** | `calendar/trading-days` 无入参、固定 `[今日-1年, 今日]` | 本模块**按需调用**它判断"最新交易日"与 `as_of` 新鲜度（§5.5 的 `market_quote_stale`）；**长周期历史日历累积属存储议题，不在本模块**。不调用就没有"丢失"问题 |

其他已知风险（沿用 §7 / P1 的记账方式）：

| 风险 | 说明 | 何时暴露 |
|---|---|---|
| 数字经手 LLM 被润色 | 模型把 `1277.8` 写成「约 1278 元」⇒ 比对失败或被人工放过 | M6 起；靠规范 `quote_text` + WARN |
| 供应商字段变更 | 接口改版静默改字段含义 | 持续；`raw_hash` + 契约测试兜底 |
| `null` 被当 0 | 未披露字段为 `null`，模型或工具把它当 0 参与比较会静默出错 | M3 起；返回体显式标注「未披露」，禁止 `null` 转 0 |
| trace 明文落盘 | 行情 payload 会被写进 trace / 留痕（既有风险项） | 随 M5 |
| 前复权跨次不一致 | Agent 不同时间拉前复权，同一天数值不同 ⇒ 自己矛盾 | M3 起；默认 `adjust=none`，需前复权时标注口径（§9 坑 1） |

**停点规则**

1. **停点 0（M0）**：凭据与 capability 未确认 ⇒ 不写 M1 之后任何代码。
2. **停点 1（M3 之后、M5 之前）**：单标的端到端跑通（resolve → 取数 → 工具读出 → evidence → verify 通过，基于留痕方案 A）。
   不过这关就上线工具 = 硬闸①没接上（对齐 P1「A 组不跑通不启动 B」同款判断）。
3. **停点 2（M6 后）**：三闸回归不退化，才允许 Agent 在真实任务里使用市场工具；
   在此之前只允许测试与离线使用。

---

## 10. 待拍板

1. ~~API Key 是否已开通~~ → **已确认：API Key 已开通**（2026-09-09）。
   仍需确认具体 capability 权限（无权限返回 `code=2003`）：
   prices / corporate-actions / financials / valuations / meta（**dump 不需要了**，本模块不落库）。
2. 市场范围：A 股 only，还是要含指数 / ETF / 场外基金？
3. **留痕默认开启是否可接受**：默认走方案 A（`MARKET_TRACE=on`，写 run 目录，硬闸①可**证伪来源与时点、数值未被篡改**）。
   若要求关闭明文留痕，则降级为方案 B（闸标 `partial`，`strict` 下不通过）—— 可校验性下降，需你接受。
4. V1 取舍：财务报表与财务指标（V1.1）是否并入本期？
5. **降级容忍度**：行情不可用时，接受「研报-only 策略卡 + WARN」吗（§6.4）？
   若要求「无行情不出卡」，则需把该 WARN 升级为 ERROR —— 这会降低可用性，需你定。
6. **`market_stats` 的指标范围与计算路径**（M12 待办，**暂不实现**）：
   ① 先做哪几个指标（建议最小集：区间高低 / 均线 5·20·60 / 波动率 / 最大回撤）；
   ② 长尾指标（RSI / MACD / 布林带）是否允许走 `run_python_code_in_finance_sandbox`——
   它算不算"确定性工具"（执行确定、输入来自留痕 ⇒ 可复现，但模型可能写错代码）；
   ③ 是否同步扩展硬闸②到市场衍生量（M6）：`computed_by` 只防**编造**，
   **重算复核**（verify 用留痕序列按同一公式重算）才防**算错**，两者要一起做。

---

## 11. 进度规则

1. 状态以本文件 §8 表格为准；完成后改 ✅ 并在要点栏记录实际结果（含发现的坑）。
2. 出现阻塞标 ⛔ 并注明原因与解除条件。
3. **硬闸不因接数据而放宽**：任何「先让流程跑通、校验以后再补」的改动一律拒绝。
4. 范围变更需先回写本文件再改实施。

---

## 一句话

**本模块只给 Agent 一组同花顺工具：REST 同步拉取、调用治理、失败可降级、返回体分析友好；
不落库、不跑批、不建表，只留一个 `Sink` 接缝备将来接存储。**
溯源从「库里冻结值比对」变成「run 目录留痕的**来源时点可证伪 + 值域可比**」（可关，关则降级为哈希自证）。
价格是实时时变的：我们不要求"值等于某静态快照"，只要求"值确实出自标注 `as_of` 时点的真实调用、未被篡改 / 编造"，凭空编数仍必被硬闸挡住。
这样接进来的是**即用即弃、取不到数还能出研报-only 卡、但编数必被硬闸挡住的工具**，
而不是又一个让模型更容易讲得头头是道的数据源。
