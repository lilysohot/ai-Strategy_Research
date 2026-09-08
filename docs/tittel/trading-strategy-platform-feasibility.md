# 交易机会与策略平台 —— 基于 Apodex Harness 的可行性评估

> 评估对象：在现有 FrontierAgent / Apodex Web 平台上，构建「资料库挖掘机会 → 分仓方案 → 价格策略 → 实盘价格回填 → 区间监控预警」的投研闭环。
> **明确范围：只做机会发现、策略生成与风险提示，不做任何交易执行。**
> 前置文档：[fin-research-three-layer-architecture.md](fin-research-three-layer-architecture.md)（研报三层库，已设计未实现）、[../plan/plan.md](../plan/plan.md)（M4 金融工具排期）。

---

## 0. 结论摘要

| 能力块 | 可行性 | 判断依据 | 主要代价 |
|---|---|---|---|
| ① 资料库挖掘（研报 / 宏观 / 个股） | **高** | 三层架构方案已完备，4 个 `@tool` 契约已定 | 入库管道 + BGE-M3 本地部署 |
| ② 分仓方案 + 价格策略 | **高，但必须重构生成方式** | 算术必须剥离出 LLM，走确定性工具 | 新增 3 个纯函数工具 + 策略卡 schema |
| ③ 多轮交互（填总资金 / 填买入价） | **高，近乎零成本** | T2.6 历史回填 + T2.10 addendum 注入通道现成 | 前端两个表单组件 + 一个请求字段 |
| ④ 实时价格监控与区间预警 | **当前架构结构性不支持** | run 是一次性子进程 + wall-clock budget + 占 worker slot | **必须新建旁路服务 Watcher** |
| ⑤ 交易执行 | **不做** | 工具白名单 fail-closed，天然无法发生 | 需把"禁止"结构化固定，而非靠提示词 |

**一句话结论**：构想可行，且 ①②③ 与现有 Harness 的接缝几乎是现成的（M4 的 T4.1–T4.3 就是为此预留的）；真正的工程量在 ④ ——它不能复用 `run`，必须与 agent 主链路解耦，做成一个确定性规则引擎。同时，**策略可信度的成败取决于一件事：所有算术不得由 LLM 完成**。

---

## 1. 现有 Harness 的能力边界（事实核对）

### 1.1 运行模型：一次性、有预算、占槽位

| 事实 | 位置 |
|---|---|
| 一次 run = 一个独立 Python 子进程，跑完即退，不复用进程 | `server/orchestrator.py` `_launch`；设计理由见文件头注释（进程级全局 `_llm_cache` / `ResourceManager` / `get_config` 会串用户配置） |
| 同 session 串行（`asyncio.Queue` + 常驻 drain task），跨 session 并行（`asyncio.Semaphore(worker_pool_size)`，默认 **2**） | `server/orchestrator.py` `_session_queues` / `_drain_session` / `_acquire_slot` |
| wall-clock budget 会作为**预算中止**抛 `TaskWallTimeExceeded` | `frontier_agent/scheduling/scheduler.py:24` `resolve_wall_time_s` |
| 停止信号走 stdin JSONL → `metadata["pause_check"]`，协作式在 turn 边界停 | `server/worker.py:131`；`orchestrator.stop()` |
| SSE 订阅以 **run_id 为键**，`orch.subscribe(run_id)` / `unsubscribe` | `server/routes/runs.py:222` |

**推论**：一个"盯盘 run"会同时违反三件事 —— 被 wall-clock 掐断、永久吃掉一半 worker 并发、run 一结束 SSE 订阅即失效。因此**监控不能是 agent run**。

### 1.2 工具接入：两处注册，白名单 fail-closed

```python
# plugins/tools/__init__.py:34 —— 24 个内置工具，不在列表即不存在（fail-closed）
_BUILTIN_TOOLS: list[Tool] = [web_search, web_fetch, ..., recover_result]

# workflows/stateful_react_agent/nodes/main_agent.py:543
def _tools_for_stateful_react(resource_mgr, agent_cfg) -> list[Any]:
    override = agent_cfg.get("agent_tools")   # profile 的 agent_tools 名单优先于角色池
    ...
    tool = all_tools.get(name)                # 但必须已在注册表中存在，否则 skip
```

即：**注册（能不能用）在 `_BUILTIN_TOOLS`，可见性（这次给不给用）在 `profile_overrides["agent"]["agent_tools"]`**。后者可由 server 每次 run 动态下发，不落上游文件。

现有的两个预留钩子，正是为金融工具准备的：

```python
# server/profile.py:33 —— 空列表，等 T4.2 填充
MARKET_TOOL_NAMES: list[str] = []

# server/worker.py:326
# Parse any extra agent_tools the orchestrator appends (e.g. market tools ...)
if args.agent_tools:
    overrides["agent"]["agent_tools"] = [*overrides["agent"]["agent_tools"], *extra]
```

### 1.3 注入通道：per-run 提示词与 profile

| 通道 | 位置 | 用途 |
|---|---|---|
| `metadata["_sys_prompt_addendum"]` | `server/worker.py:351`；消费方 `main_agent.py:817` | **注入结构化用户上下文（资金、持仓、成本价）的正确位置** |
| `metadata["profile_overrides"]` | `server/worker.py:334`，deep-merge 后覆盖 profile | 下发 `agent_tools` / `fs_mode` / `thinking_format` |
| `metadata["profile_inline"]` | `main_agent.py:346/632`，天然 bypass 缓存 | 整份投研 profile 由 server 下发，**零上游改动** |
| `metadata["sdk_extra_observers"]` | `server/worker.py:345` | 注入 Bridge / DiffRecorder / Steer / Approval 四个观察者 |

### 1.4 产物链：结构化输出已有落点

T2.9 已把 run 产物闭环做完：agent 写 `<run_dir>/ws/outputs/` → 扫描落 `artifacts` 表（含 `sha256` + `size`）→ 鉴权下载端点。**策略卡走这条路即可，无需改 SSE 事件词汇表。**

### 1.5 沙箱与网络

`plugins/tools/_sandbox.py:944` 对沙箱内的 `bash` / `run_python_code` 默认加 `--unshare-net`（无网络），仅 `allow_net=True` 的调用方才放开。

**推论**：agent 不能在沙箱里自己 curl 行情。**行情必须由宿主进程内的原生 `@tool` 直连，或由 server 侧抓取服务预取落本地库后只读访问**——后者更可控、可缓存、可审计、可复现。

---

## 2. 技术架构

### 2.1 总体分层

```
┌────────────────────────────────────────────────────────────────────┐
│  数据面（server 侧，确定性，无 LLM）                                  │
│  ┌────────────────┐  ┌─────────────────┐  ┌──────────────────────┐  │
│  │ 研报三层库      │  │ 行情服务         │  │ 计算内核              │  │
│  │ L1 原文         │  │ MarketDataSource│  │ position_sizing      │  │
│  │ L2 FTS5+稠密RRF│  │  akshare/stub   │  │ strategy_lint        │  │
│  │ L3 数值表       │  │ + DuckDB 缓存   │  │ backtest_strategy    │  │
│  └────────────────┘  └─────────────────┘  └──────────────────────┘  │
└────────────────────────────────────────────────────────────────────┘
                    ↓ 全部以 @tool 暴露（宿主进程内，只读）
┌────────────────────────────────────────────────────────────────────┐
│  推理面（agent run，一次性）                                          │
│  ReAct loop：选标的 → 定风险预算 → 调计算内核 → 产出 strategy.json     │
│  LLM 只做「选什么、为什么」；所有数字由工具产出                        │
└────────────────────────────────────────────────────────────────────┘
                    ↓ /outputs/strategy.json → artifacts 表 → 前端渲染
┌────────────────────────────────────────────────────────────────────┐
│  监控面（Watcher，旁路，确定性规则引擎，默认不调 LLM）                 │
│  watch_rules → 轮询行情 → 区间命中 → watch_events → 用户级 SSE 推送   │
└────────────────────────────────────────────────────────────────────┘
```

### 2.2 ④ 实时监控的具体设计（唯一的架构新增）

现有 SSE 是 per-run 的，`watcher` 的告警发生在 run 之外，因此必须新增一条**用户级**推送通道。

| 组件 | 说明 |
|---|---|
| `watch_rules` 表 | `user_id, symbol, strategy_id, lower, upper, direction, expires_at, status` + Alembic 迁移 |
| `watch_events` 表 | 命中留痕，可回溯"哪条规则在何时因何价触发了什么建议" |
| `server/watcher.py` | 独立 asyncio task，随 `app.py` 的 lifespan 启停；按 `poll_interval_s` 批量拉取、纯规则判定 |
| 用户级 fan-out | 现有 `orchestrator.subscribe` 以 run_id 为键。新增 user 级订阅（或独立轻量通道），避免改动 run 侧语义 |
| 新端点 | `POST/GET/DELETE /api/watches`、`GET /api/watches/stream`（SSE，挂 `get_current_user`） |
| LLM 的定位 | **默认不参与判定**。命中后可选地按需唤起一次 run 做定性解读（"为什么这条线被击穿"），由用户显式触发 |

关键设计取舍：**判定层确定性、解释层用 LLM**。若把"是否触发"交给模型，成本随标的数×频率线性放大，且结果不可复现、无法审计。

### 2.3 合规的结构性落法（不是提示词说教）

| 手段 | 落地位置 |
|---|---|
| 不提供任何下单 / 账户 / 券商类工具 | `_BUILTIN_TOOLS` 白名单本身即 fail-closed，不注册即不存在 |
| 数据源协议只声明读方法 | `MarketDataSource`（`kline/financials/announcements/news`），无写语义 |
| 输出硬性约束 | 经 `profile_inline` / `_sys_prompt_addendum` 注入，模板强制带免责与"非投资建议"表述 |
| 前端每屏免责 | 复用 T3.7 `DisclaimerBar.vue`（已是每屏必带、文案单点定义） |
| 全链路留痕 | 复用 `audit_log`（T2.2 模式）+ `watch_events`；策略卡带 `sha256` 可校验未被篡改 |
| 敏感数据保护 | 用户资金 / 持仓按敏感数据处理：沿用 T2.3 Fernet 加密 + T2.7 归属隔离（非本人一律 404，不给存在性 oracle） |

---

## 3. 数据接入

### 3.1 资料库（研报 / 宏观 / 研报内个股解读）

直接施工 [fin-research-three-layer-architecture.md](fin-research-three-layer-architecture.md)，不再重述选型。要点：

- **L1 原文层**是唯一证据源，逐字存档；**L2 检索层**只回答"看哪份报告哪一节"；**L3 数值层**做精确匹配。
- 四个工具：`query_research_reports`（定位）/ `fetch_report_fulltext`（取证）/ `query_report_tables`（取数）/ `query_macro_indicator`（宏观直查）。
- **精度红线**：入库管道除 embedding 外零 LLM 参与；Agent 引用数字只能来自 L1 逐字或 L3 精确行，禁止引用 L2 snippet 或模型记忆；fact 与 forecast 字段级区分。

### 3.2 行情数据：分层接入，按授权等级决定颗粒度

| 层级 | 数据源 | 颗粒度 | 授权风险 | 建议 |
|---|---|---|---|---|
| L0 | `stub.py` 确定性 mock CSV | — | 无 | 一期先把工具与流程跑通（即 T4.1 已排内容） |
| L1 | akshare（东财 / 新浪等公开接口） | 日频为主，分钟级受限 | 免费源通常有延时、限频，商用条款需核实 | **一期定位日频**，DuckDB 缓存（T4.5 已排） |
| L2 | Tushare Pro / 聚宽等 | 分钟级 | 积分 / 付费，商用需确认 | 监控功能的起步线 |
| L3 | Wind / Choice / 交易所直连 | tick | 明确商用授权 | 成本与合规代价高，一期不做 |

**必须处理的状态**（放在工具层，不能让 LLM 猜）：复权方式、停牌、涨跌停、ST/退市、上市不足 N 日（次新）、除权除息跳空。这些若漏掉，回测与止损计算会静默出错。

**时效契约**：所有行情返回强制带 `as_of` 与 `stale` 标记；源不可用时**明确降级并告知用户**，绝不静默用旧价充当实时价。

### 3.3 缓存与限频

DuckDB 单文件（T4.5 已规划）存 K 线与 fundamentals，按 `symbol + freq + as_of` 主键 upsert；抓取侧统一限频与退避，避免被公开源封禁。

---

## 4. 策略生成逻辑

### 4.1 核心原则：LLM 负责「选什么、为什么」，工具负责「算多少」

这是整个方案可信度的分水岭。自由生成的问题不是"模型算不对"，而是**错了不可检测**：一段自然语言里混着对的和错的算术，没有任何机制能区分。

| 决策项 | 归属 | 理由 |
|---|---|---|
| 选标的、定逻辑、定失效条件 | **LLM**（须带资料库溯源） | 定性判断，需要跨文档综合 |
| 仓位股数、金额、占比 | **`position_sizing` 工具** | 算术，必须可复现 |
| 止损/目标/加仓区间一致性校验 | **`strategy_lint` 工具** | 约束校验，必须确定性 |
| 收益率、最大回撤、胜率 | **`backtest_strategy` 工具** | 纯函数回测，禁止口算 |
| 区间是否触发 | **Watcher 规则引擎** | 高频，成本与可复现性决定 |

### 4.2 策略卡 schema（落 `/outputs/strategy.json`）

```jsonc
{
  "version": 1,
  "capital_total": 1000000,
  "positions": [{
    "symbol": "600519.SH",
    "thesis": "……",                       // 定性判断
    "evidence": [                          // 每条必带出处，可逐字溯源
      {"report_id": "R-2026-0815-XX", "page": 12, "quote": "……", "kind": "fact"}
    ],
    "entry": {"low": 1420, "high": 1450},  // 价格策略区间
    "stop_loss": 1310, "target": 1720,
    "invalidation": "季度营收同比转负",     // 可证伪的失效条件，必填
    "horizon": "3-6M",
    "sizing": {"risk_budget_pct": 1.0, "shares": 300, "amount": 435000, "weight_pct": 43.5},
    "computed_by": "position_sizing@v1",   // 标明由哪个工具计算
    "lint": {"passed": true, "warnings": []}
  }],
  "portfolio": {"gross_exposure_pct": 87.0, "max_single_weight_pct": 43.5,
                "sector_concentration": {"食品饮料": 0.435}},
  "disclaimer": "本研究性推演不构成投资建议，不涉及任何交易执行。"
}
```

落盘后走 T2.9 产物链入库（含 `sha256`），前端解析渲染为策略卡片；用户回填实际成交价后，下一轮 run 读回该文件并产出 v2，天然形成版本链。

### 4.3 反过拟合约束

- 策略参数数量设硬上限（建议 ≤ 6），超过即 `strategy_lint` 拒收。
- 回测必须报告样本外表现 + 参数网格敏感度；对"参数微调即失效"的策略自动降级提示。
- 任何策略**必须**声明失效条件与时间窗；无失效条件的策略不允许落卡。

---

## 5. 风险控制

### 5.1 产品侧（保护用户不因本产品亏钱）

| 约束 | 落地方式 |
|---|---|
| 单票仓位上限、行业集中度上限、总敞口上限 | `strategy_lint` 硬校验，超限直接拒收并说明 |
| 每笔风险预算上限（占总资金 %） | `position_sizing` 强制入参，不可省略 |
| 止损位必填 | 策略卡 schema 必填字段，`strategy_lint` 校验 `stop < entry_low < entry_high < target` |
| 禁止杠杆 / 配资 / 衍生品建议 | 产品级硬约束；提示词 + lint 双重拒绝 |
| ST / 退市 / 停牌标的 | 工具层直接标注并建议排除 |
| 无投顾资质 | 全站免责；输出定性为"研究性推演" |

### 5.2 系统侧（防幻觉与静默错误）

| 风险 | 对策 |
|---|---|
| 数字幻觉 | 沿用三层架构精度红线 + `EvidenceAuditObserver`（fin-research 文档 §6 已设计）：终稿数字与本次 loop 工具返回做规范化匹配，未命中标记"未溯源" |
| 行情陈旧被当实时 | `as_of` + `stale` 字段强制返回；源故障明确降级 |
| 回测前视偏差 / 幸存者偏差 | 回测工具内部固定处理，不交给 LLM 配置 |
| 工具结果过大被截断导致信息丢失 | 复用 `maybe_overflow()` + `recover_result`（已在白名单内） |
| LLM 调用失败 / 超时 | 已有 salvage 与 deadline 语义，partial 答案带 `_[partial: reason]_` 标记 |
| 监控拖垮服务 | Watcher 独立于 worker slot，批量拉取 + 限频 |

---

## 6. 与现有 Harness 的整合方式（改动清单）

**原则：零改动 `frontier_agent/` 与 `workflows/`。** 工具可见性一律走 server 下发的 `profile_overrides` / `profile_inline`（tech-stack §5.4 既定契约）。

| # | 改动 | 位置 | 性质 |
|---|---|---|---|
| 1 | `MarketDataSource` 协议 + `stub.py` | `plugins/market/`（新建） | 即 plan.md T4.1 |
| 2 | 行情四件套 `@tool` + 注册 | `plugins/tools/market_*.py` + `_BUILTIN_TOOLS`；**同步改 `tests/test_tool_registry.py::EXPECTED_TOOLS`** | 即 T4.2 |
| 3 | 填充 `MARKET_TOOL_NAMES` | `server/profile.py:33` | 即 T4.2 预留钩子，填值即可 |
| 4 | 研报三层库 + 四工具 | `plugins/tools/_fin_research/` + 4 个 `@tool` | 按 fin-research 文档施工 |
| 5 | 计算内核三工具 | `position_sizing` / `strategy_lint` / `backtest_strategy` | **新增，本方案特有** |
| 6 | 结构化输入 | `POST /api/runs` 增加 `context: {capital, fills[]}` → worker 拼 `_sys_prompt_addendum` | 复用 T2.10 已验证通道 |
| 7 | 策略卡 | agent 写 `/outputs/strategy.json` → 复用 T2.9 产物链 | 零后端改动 |
| 8 | 前端 | `CapitalForm` / `FillPriceForm` / `StrategyCard` / `WatchPanel` | 新增 Vue 组件 |
| 9 | 监控（P2） | `watch_rules` + `watch_events` 表 + Alembic；`server/watcher.py`；`routes/watches.py`；用户级 SSE 通道 | **唯一的新增服务** |
| 10 | 合规 | `profile_inline` 注入硬性约束；复用 `DisclaimerBar.vue` | 零成本 |

### 实施路线

| 阶段 | 内容 | 依赖 | 预估 |
|---|---|---|---|
| **P0 确定性内核** | 计算内核三工具 + 策略卡 schema + 结构化输入 + 前端表单 | 无（可用 stub 数据） | 2 周 |
| **P1 数据与资料** | 研报三层库（T4.1–T4.3）+ 行情源 + DuckDB（T4.5） | 无 | 3 周 |
| **P2 监控** | Watcher + 用户级推送 + 前端面板 | P1 的行情源 | 2 周 |
| **P3 可选** | `workflows/investment_research` 多智能体投研 | agent_team 编排质量达标 | 已在 P2 暂缓清单 |

P0 先行是关键：**它不依赖任何外部数据源，却已经能验证整个交互闭环与"算术不出 LLM"这条核心设计**。若 P0 跑不通，后面投再多数据也救不回可信度。

---

## 7. 待决策项（阻塞 P1/P2 排期）

1. **实时行情的数据源与商用授权** —— 决定监控能否做、颗粒度到哪一层。免费源延时且条款受限，付费源需预算与授权确认。
2. **是否真的需要"实时"** —— 日频 / 分钟级已能覆盖绝大多数分仓与策略场景；tick 级的成本与合规代价高出一个量级，建议一期明确不做。
3. **监控命中后是否唤起 LLM 解读** —— 涉及成本、延迟与价值权衡；建议默认关闭，用户按需触发。
4. **用户资金 / 持仓的敏感度定位** —— 建议一律按敏感数据处理（加密 + 归属隔离），即便初期是单机自用。
5. **策略卡的持久化形态** —— 当前方案借道 artifacts 表（复用 T2.9，零改动）；若后续需要"按策略查询 / 跨 run 对比"，则需独立 `strategies` 表，届时再迁移不迟。

---

## 8. 红线（全程不可违反）

1. **所有算术（仓位、收益、回撤、触发判定）不得由 LLM 完成**，必须经确定性工具。
2. **所有引用的数字必须可逐字溯源**到 L1 原文或 L3 精确行；fact 与 forecast 字段级区分。
3. **不提供、不描述、不暗示任何交易执行通道**；数据源协议无写语义。
4. **行情必须带 `as_of` 与 `stale` 标记**，源故障明确降级，绝不静默以旧价充实时价。
5. **无失效条件、无止损、无时间窗的策略不允许落卡**。
6. **监控判定不得依赖 LLM**；LLM 只做命中后的解释层，且默认关闭。
7. **用户资金与持仓按敏感数据处理**，加密存储 + 归属隔离，全链路审计留痕。
