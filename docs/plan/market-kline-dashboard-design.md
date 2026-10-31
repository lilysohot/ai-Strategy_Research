# K 线看板（行情走势图）设计方案

> 状态：**草案 · 待评审**。本方案只描述设计，不改代码、不改数据、不新增数据源。

| 项 | 内容 |
| --- | --- |
| 日期 | 2026-10-31 |
| 目标 | 在 Web 端接入 K 线看板，把「市场观测」可视化，作为差异化产品面的一部分 |
| 依赖 | `plugins/market/`（已建成）、`server/`（FastAPI）、`web/`（Vue3 + Vite） |
| 工作量 | 后端 0.5~1 天，前端 1~2 天，合计 2~3 天出一个能跑的日 K 看板 |

---

## 1. 背景与目标

投研平台的资料库（语料 + claims + 证据）与业务自动化（投研闭环）已完成，行情数据链路
（`plugins/market/`）也已建成。K 线看板是「市场观测（Market Observation）」在 Web 端的展示层：

- **复用既有数据链路，不新建数据源、不建数据仓库**（数据仓库是既定非目标）；
- 把 `MarketService.history()` 返回的 OHLC 序列渲染为可交互的 K 线图；
- 为后续「研究质量评级引擎」提供一个可溯源、带时点口径的行情可视化锚点。

定位一句话：**K 线看板 = 市场观测的可视化，不是新能力，是既有 market 能力的 Web 出口。**

## 2. 范围

### 在范围内（首版）

1. 单标的**日 K 线**走势图（OHLC 主图 + 成交量副图 + MA 均线）。
2. 标的**最新行情快照**（现价、涨跌、PE 等，来自 `MarketService.quote()`）。
3. 单标的查询，复用 `MarketService.resolve()` 消歧（名称 / 代码 / thscode）。
4. 后端**只读** HTTP 接口 + 进程内缓存。

### 明确排除（首版不做）

| 排除项 | 原因 |
| --- | --- |
| 分钟 / 分时线 | 数据源 `Interval = Literal["1d"]` 只支持日线（`plugins/market/ports.py:16`） |
| 实时推送 / WebSocket | 首版用前端轮询即可，日线数据变动频率低 |
| 数据落库 / 数据仓库 | 既定非目标（`MarketService` 设计为「无存储，取回即用」） |
| 复杂技术指标（MACD/KDJ/布林） | 首版只 K 线 + 成交量 + MA；指标是 P1 增强项 |
| 自选股 / 多标的对比 / 分屏 | P2 完整版 |

## 3. 现状盘点（已具备，零新建）

| 资产 | 位置 | 说明 |
| --- | --- | --- |
| K 线数据源 | `plugins/market/service.py::MarketService.history()` | 返回标准 OHLC（`open/high/low/close/volume/turnover` + `date_ms`），字段与任何 K 线图库一一对应 |
| 行情快照 | `plugins/market/service.py::MarketService.quote()` | 现价 + 估值 + 规范 `quote_text` |
| 标的消歧 | `plugins/market/service.py::MarketService.resolve()` | 名称/代码/thscode → 唯一 thscode |
| 数据供应商 | `plugins/market/adapters/fuyao_rest.py` | 同花顺 fuyao REST，`THS_API_KEY` + 默认 `https://fuyao.aicubes.cn` |
| 网络治理 | `plugins/market/transport/` | 超时(10s)、退避重试(≤3)、并发上限(4)、熔断、**单飞去重**、错误码映射 |
| 盘中隔离 | `plugins/market/temporal.py::annotate_history()` | 已把未收盘 bar 分离到 `provisional_items`，并标注 `bar_status`/`comparison_eligible` |
| 时点渲染 | `plugins/market/render.py` | `as_of_ms`/`as_of`(ISO)/`age`，确定性渲染 |
| 服务工厂 | `plugins/market/factory.py::build_service()` | 读 `.env` 构造真实服务，缺 key 时 fail-closed |
| 测试适配器 | `plugins/market/adapters/mock.py::MockAdapter` | 不发网络、不连库，可做路由测试 |
| 后端 import 先例 | `server/monitor_worker.py:15` | `from plugins.market.factory import ...`，无架构阻碍 |
| 后端路由范本 | `server/routes/corpus.py` | 懒加载单例、`get_current_user` 鉴权、fail-closed 翻译 |

## 4. 总体架构与数据流

```text
浏览器 (Vue3)
   │  GET /api/market/kline?query=茅台&days=250&adjust=none
   ▼
server/routes/market.py   ── 鉴权(get_current_user) → 懒加载单例 MarketService → 进程内缓存
   │  MarketService.history() / quote()  (同步, 走线程池避免阻塞事件循环)
   ▼
plugins/market/  (transport 治理: 重试/熔断/单飞/限流)
   │
   ▼
同花顺 fuyao REST API  (THS_API_KEY 只在后端, 前端不接触)
```

**关键点**：`THS_API_KEY` 只在后端（`.env`），前端永不接触；所有 `/api/market/*` 走
`get_current_user` 鉴权，与 `corpus.py` 同款。

## 5. 后端设计

### 5.1 新文件 `server/routes/market.py`

仿照 `server/routes/corpus.py` 的结构：

```python
router = APIRouter(prefix="/api/market", tags=["market"])

# 懒加载单例：transport 里的熔断器有状态，不能每次请求重建
_service_lock = threading.Lock()
_service: MarketService | None = None

def _market_service() -> MarketService | None:
    """build_service() 读 .env；缺 key 时返回 None，由 unavailability() 给原因。"""
    global _service
    with _service_lock:
        if _service is None:
            _service = build_service()
        return _service
```

三个端点（全部只读）：

| 端点 | 说明 | 返回 |
| --- | --- | --- |
| `GET /api/market/resolve` | 消歧：`query` → 候选/thscode | `ResolveResult.to_dict()` |
| `GET /api/market/kline` | 日 K 线 | OHLC 序列 + 盘中隔离元数据（见 §8 契约） |
| `GET /api/market/quote` | 最新行情快照 | `quote()` 结果 + 时点标注 |

### 5.2 同步/异步

`MarketTransport` 是**同步**的（`httpx` 同步客户端 + `threading.Event` 单飞）。FastAPI handler
用**同步 `def`**（FastAPI 自动丢进线程池）即可，不要用 `async def` 直接同步调用——那会阻塞事件循环。

### 5.3 鉴权与 fail-closed

- 每个 handler 声明 `user: User = Depends(get_current_user)`（`server/deps.py`）。
- 失败翻译成 HTTP 状态码，**不吞成空 200**：
  - `MarketUnavailable(kind="credentials")` → `502`（缺 key / 未认证，前端提示配置）
  - `MarketUnavailable(kind="not_found")` → `404`（标的不存在）
  - `MarketUnavailable(kind="rate_limited")` / `unavailable` → `503`（上游限流/熔断）
  - `MarketUnavailable(kind="bad_request")` → `400`
  - 复用 `plugins/market/failure.py::translate()` 产出 `reason` + `next`，透传为 `detail`。

### 5.4 缓存（防限流，不落库）

`MarketService.history()` 每次实时打 THS；transport 有并发上限(4) + 熔断，多用户频繁刷新会打爆。
方案：**进程内 TTL 缓存**，key = `(thscode, days, adjust)`：

- 已收盘历史段：日内基本不变，TTL 可长（如 5 分钟）。
- 当日 `provisional_items`：盘中会变，随整体结果一起缓存，TTL 取短（如 60 秒），
  或干脆不缓存当日、只缓存 `latest_closed_trade_date` 及之前的部分。

首版从简：整体结果 TTL **60 秒**，加上 transport 已有的单飞去重，足够保护限流；后续再细化分段。
**不引入 Redis / 不落库**，进程内 `dict` + 时间戳即可（单进程部署）。

### 5.5 注册

`server/app.py` 仿照 `corpus_routes`：`from server.routes import market as market_routes` +
`app.include_router(market_routes.router)`。

## 6. 前端设计

### 6.1 图表库选型

当前 `web/package.json` **无图表库**。推荐：

| 候选 | 取舍 | 结论 |
| --- | --- | --- |
| **klinecharts** | K 线专用，主图+成交量/MACD 副图开箱即用；轻量；中文文档；免费；Vue3 支持好 | **首选** |
| echarts | 通用全能，但要自己拼 candlestick；全量引入体积大 | 若平台后续要统一图表生态再考虑 |
| lightweight-charts | TradingView 出品、专业、性能好，但英文文档、偏西式、无内置中文 | 备选 |

### 6.2 前端落点

| 文件 | 内容 |
| --- | --- |
| `web/src/api/index.ts` | 新增 `market` 对象：`resolve` / `kline` / `quote` 三个 `request<T>()` 调用 |
| `web/src/types.ts` | 新增 `KlineBar` / `KlineResponse` / `MarketQuote` 等类型 |
| `web/src/components/market/KLineChart.vue` | klinecharts 封装：接收 `KlineBar[]`，渲染主图+成交量+MA，十字光标/缩放 |
| `web/src/views/MarketView.vue` | 页面：标的查询框（消歧）+ 快照栏 + 图表 + 空态/错误态 |
| `web/src/router/index.ts` | 在 `AppShell` children 下加 `{ path: 'market', name: 'market', component: MarketView }` |

### 6.3 前端要点

- 走 `request<T>()`（`web/src/api/client.ts`），不要裸 `fetch`——自动带 token、统一 401 跳登录、统一错误归一化。
- 盘中 bar（`bar_status != "closed"`）在图上**视觉区分**（如不同颜色/虚线），并显示
  `provisional_policy` 的提示文案，避免用户把盘中快照当收盘价。
- `date_ms` → 本地日期：前端用 `trade_date` 字段（后端已按 Asia/Shanghai 算好），不要自己换算毫秒戳。

## 7. 数据契约

### 7.1 `GET /api/market/kline`

请求：`query`（必填，1~100 字）、`days`（默认 250，`ge=1, le=3650`）、`adjust`（`none`/`forward`/`backward`，默认 `none`）。

响应（基于 `MarketService.history()` + `annotate_history()`）：

```json
{
  "ok": true,
  "thscode": "600519.SH",
  "name": "贵州茅台",
  "interval": "1d",
  "adjust": "none",
  "raw_count": 251,
  "count": 250,
  "items": [
    {
      "date_ms": 1730000000000,
      "open_price": 1500.0, "high_price": 1520.0,
      "low_price": 1490.0, "close_price": 1510.0,
      "volume": 1234567, "turnover": 4567890000,
      "trade_date": "2024-10-27",
      "bar_status": "closed",
      "comparison_eligible": true
    }
  ],
  "provisional_items": [ { "...": "当日未收盘 bar，bar_status=provisional" } ],
  "latest_closed_trade_date": "2025-10-30",
  "market_timezone": "Asia/Shanghai",
  "retrieved_at": "2025-10-31T14:30:00",
  "provisional_policy": "盘中临时柱仅是 retrieved_at 时刻快照，不能称为收盘价……"
}
```

注意：`items` 只含已收盘日线（可做完整日比较）；当日盘中柱在 `provisional_items`，图上要区分。

### 7.2 `GET /api/market/quote`

复用 `MarketService.quote()` 返回：`items[]`（`thscode`/`name`/`last_price`/`pe_ttm`/
`open/high/low/prev_price`/`price_change_ratio_pct`/`volume`/`turnover`/`as_of_ms`/`as_of`/`age`/`quote_text`）。

## 8. 关键决策与坑（实施前必须读）

1. **只有日线**（`ports.py` `Interval = Literal["1d"]`）。要做分时/分钟线，必须先扩展
   adapter 与 `Interval` 类型，**这是数据源改造，不在本方案范围**。先确认产品要的是「日线走势」还是「实时盘面」。
2. **90 天上限是给 LLM 的，不是给看板的**。`plugins/tools/market_history.py:27` 的 `MAX_DAYS=90`
   是为了避免 10 年日线 13 万字符打爆模型上下文。前端 HTTP 接口**不套这个限制**，直接调
   `MarketService.history()`（它支持 ≤10 年窗口，`ports.py:173`）。
3. **盘中 provisional 隔离**。`annotate_history()` 已把未收盘 bar 分离；看板必须区分展示，
   且不得把盘中柱当收盘价（`provisional_policy` 明确此语义）。
4. **复权口径**。默认 `adjust=none`；前复权随基准漂移、跨次调用不可比（`service.py:246` 注释）。
   看板切换复权时，UI 要标注口径，且同序列不要混用。
5. **缓存 vs 限流**。transport 有并发上限(4)+熔断；多用户并发会触发。必须加 §5.4 缓存，
   否则看板会在高峰期熔断全站 market 工具（连 agent 的 `market_quote` 也受影响）。
6. **key 安全**。`THS_API_KEY` 只在后端，HTTP 层代理，前端永不接触；接口必须挂鉴权依赖。
7. **同步服务**。`MarketService` 同步 + 网络 IO，handler 用同步 `def`（FastAPI 线程池），不要 `async def` 裸调。

## 9. 分期交付

### P0 最小可验证版（2~3 天）

- 后端：`server/routes/market.py`（`resolve`/`kline`/`quote` 三端点 + 懒加载单例 + 60s 缓存 + fail-closed）+ app.py 注册。
- 前端：引入 `klinecharts`；`market` API 对象 + 类型；`KLineChart.vue`；`MarketView.vue`（查询框 + 日 K + 成交量 + MA）；路由 `/market`。
- 验收：查「茅台」出日 K 图，盘中柱有区分，缺 key 时前端提示（不白屏）。

### P1 增强（1~2 天）

- 复权切换（none/forward/backward）+ 口径标注；多周期（250/500/全部）。
- 常用指标（MA5/10/20/60 已含，可加 MACD）；快照栏展示 `quote_text`。
- 缓存分段（已收盘长 TTL / 当日短 TTL）。

### P2 完整版（视产品优先级）

- 自选列表、多标的、与「研究/策略卡」联动（点击 K 线回填到研究上下文）。
- 若产品需要实时盘面：扩展 `Interval` 支持分钟线（数据源改造，单独立项）。

## 10. 验收标准（P0）

1. `GET /api/market/kline?query=茅台&days=250` 返回合法 OHLC 序列，`items` 全为 `bar_status=closed`。
2. 缺 `THS_API_KEY` 时接口返回 502 + 明确 `next`，前端显示配置提示，不白屏、不空页。
3. 未登录访问 `/api/market/*` 返回 401。
4. 前端日 K 图可缩放、平移、十字光标看 OHLC；盘中柱视觉区分。
5. 前端 API 调用全走 `request<T>()`，token 由 client 自动携带。
6. 复用 `MockAdapter` 的路由测试通过（不发真实网络）。

## 11. 与既有约定的对齐

- **投影/非目标**：看板是「市场观测」的展示，不落库、不回流到语料/claims 提示词，符合投影三铁律中「不回流」的边界精神。
- **领域词汇**：K 线对应 `CONTEXT.md` 的「市场观测（Market Observation）」，看板展示的是带 `as_of` 时点的观测，不制造「静态权威值」。
- **fail-closed**：所有失败显式转 4xx/5xx，不静默空页，与 corpus 路由同款纪律。
