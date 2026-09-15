# 多源资料库接入 Harness 架构设计（Discord + IMA）

> ⚠️ **施工状态：本文档是历史远期探索，不是当前需求、流程或施工依据。**
> 当时架构评审收敛范围是 **P0（投研内核 + 最小资料库）**，
> 历史规格见 **[p0-implementation-spec.md](p0-implementation-spec.md)**。
> 本文档中以下部分**已推后至 P1 及以后**：Discord / IMA 接入、向量检索、信号层与
> `screen_tickers`、论证单元 LLM 抽取、全量 8000 份 ingest。
> 本文档保留作为远期设计依据，其中的精度红线、近重复与数字处理原则对 P0 同样适用。
> 当前产品状态与目标流程分别见 [product-requirements.md](product-requirements.md) 和
> [business-process.md](business-process.md)；当前语料存储见
> [plan/data-layer-architecture.md](plan/data-layer-architecture.md)。
> 2026-09-15：本轮新目标唯一候选见[重构草案 v1.1](plan/corpus-ingestion-rebuild-architecture.md)，
> I0 复核后才冻结；本文不恢复向量、模型调用或全量入库授权，也不作为平行施工方案。

> 适用项目：FrontierAgent（本仓库）
> 目标：将 Discord（实时社媒/信号流）与 IMA（知识库/研报/策略文档）两个数据源接入
> Agent Harness，使 Agent 能够挖掘潜在的交易股票与交易策略。
> 本文是设计讨论的整合稿，结论与待决问题均在末节标明。

---

## 0. 背景与设计原则

项目已完成 Agent Harness 的搭建，下一步要将资料库接入 Harness。资料库数据来源包括
**Discord** 与 **IMA**，接入目的是让 Agent 能够基于该资料库挖掘潜在交易股票与交易策略。

贯穿全文的五条原则：

1. **检索只负责定位，取证永远回原文**——任何 LLM 摘要不得进入证据链。
2. **精度优先于召回**——交易场景下「错一个数字」比「漏一条信息」危害大。
3. **结构化聚合解决「广」（挖掘），长上下文解决「深」（理解）**——二者是乘法关系，不是替代关系。
4. **LLM 用于生成索引/标签，绝不用于生成内容**——入库管道可离线、可批处理、结果可自动校验。
5. **先确认合规边界与 baseline，再投入工程**——避免为无法上线的系统做过度优化。

本文大量复用了已归档三层设计的 L1/L2/L3 分层与精度红线，并针对「多源 + 高时效 +
交易挖掘」三个特性做了探索。其 SQLite/NPZ 实现已被 PostgreSQL 方案替代。

---

## 1. 当时的现状约束（历史快照）

| 事实 | 位置 | 对设计的影响 |
|---|---|---|
| 工具是**显式白名单**，不在列表则 Agent 不可见（fail-closed） | `plugins/tools/__init__.py:34-58` `_BUILTIN_TOOLS` | 新增工具必须改这一处 + `tests/test_tool_registry.py:6` `EXPECTED_TOOLS` |
| 工具可见性由 profile 的 `agent_tools` 下发 | `workflows/stateful_react_agent/profiles/tui.yaml:75` | 不改 YAML，走 `profile_overrides` 缝 |
| Web 侧已预留工具挂载钩子 | `server/profile.py:33` `MARKET_TOOL_NAMES = []` | 复用该钩子即可，无需动 workflows |
| `@tool` 装饰器：async 函数，Google docstring 生成 schema | `frontier_agent/core/tool.py` | 工具函数必须 async；注解不可放 `TYPE_CHECKING` |
| 大结果溢写磁盘机制 | `plugins/tools/_overflow.py:370` `maybe_overflow()` | 检索/全文工具天然支持渐进式展开 |
| 文件读取工具带 PDF/docx/xlsx 解析器 | `plugins/tools/read_file.py` + `_reader_*.py` | 长上下文 L3 可复用 `read_file`，无需新工具 |
| 可复用观察者：去重、预算、墙钟、重复检测 | `frontier_agent/components/observers/` | 检索工具零改动享受 `DuplicateQueryRollbackObserver` |
| 无向量库 / embedding / 调度器（全仓 0 命中） | — | 全部新建，但**不**引入 ES / Milvus / Celery |
| 无 database 模块；`event_store` 是 no-op 桩 | `frontier_agent/state/event_store/sqlite.py` | 资料库自建独立库文件，不与 framework 耦合 |
| 已有 `category="finance"` 的工具 meta 范式 | `plugins/tools/meta.py:112-132` | 新增工具复用该 category |

关键继承：`WorkflowContext` **不提供** `register_tool`，因此资料库接入必须落在
`plugins/tools/_BUILTIN_TOOLS` 白名单 + profile 覆盖，而非新建 workflow 子包。

---

## 2. 整体架构：四层 + 双速管道

```
┌─ 采集层 L0 ────────────────────────────────────────────────────────┐
│  fast lane (秒级)              │  slow lane (分钟~小时级)            │
│  Discord: Gateway WS 事件      │  IMA: 定时 poll 清单 diff          │
│         + REST 历史回溯        │       → 只取 new/changed           │
│         httpx 直调 v10,        │  adapter 三档降级:                 │
│         snowflake 游标         │   OpenAPI → 导出文件 → 投放目录    │
└────────────────┬───────────────┴──────────────┬─────────────────────┘
                 ↓ outbox (SQLite, 幂等)         ↓
┌─ 规范层 L1 ────────────────────────────────────────────────────────┐
│  normalize: 近重复消除 · boilerplate 剥离 · 线程重建 · URL 展开    │
│             PII 脱敏 · 语种检测 · ticker 抽取 · 数字/时间结构化     │
│  → 统一 Record（含 first_observed_at 用于回测，区别于 published_at）│
│  → 逐字原文不可变存档（L1 是唯一证据源）                           │
└────────────────┬────────────────────────────────────────────────────┘
                 ↓
┌─ 索引层 L2 ───────────┬──────────────────┬────────────────────────┐
│ FTS5 + jieba 预分词   │ sqlite-vec 稠密   │ 结构化倒排 (SQL)        │
│ BM25 稀疏检索         │ 仅 IMA 长文档做   │ ticker/时间/作者/频道  │
└───────────────────────┴──────────────────┴──────────────────────────┘
                 ↓
┌─ 信号层 L3 (挖掘核心，派生数据) ──────────────────────────────────┐
│  argument_unit   论证单元（结构感知切片，替代 chunk）              │
│  ticker_mention  标的提及 + 立场/情绪 + evidence_span             │
│  ticker_daily_agg 标的×日: 提及量/独立作者数/去均值偏离度/novelty │
│  strategy_card   策略卡: thesis/catalyst/risk/tickers/horizon     │
│  cross_source_resonance 跨源共振强度                              │
└────────────────┬───────────────────────────────────────────────────┘
                 ↓
┌─ 工具层 L4：5 个候选工具（建议先收敛到 3 个）────────────────────┐
│  corpus_search(定位) · corpus_fetch(取证)                         │
│  screen_tickers(选票) · ticker_dossier(单票档案) · strategy_search│
└────────────────────────────────────────────────────────────────────┘
```

**为什么必须双速**：Discord 信号价值随分钟衰减（一条喊单 2 小时后可能已失效），IMA
策略文档随周衰减。同一条批处理管道要么让 Discord 延迟不可接受，要么对 IMA 高频轮询打爆
对端。两条 lane 在 **L1 之后合并**，共用后续一切。

---

## 3. 统一资料库接口

### 3.1 归一：SourceAdapter 协议

两个源的差异被封装在一个协议后，新增源只需实现它：

```python
# plugins/corpus/sources/base.py
class SourceAdapter(Protocol):
    name: str                       # "discord" | "ima"
    async def list_objects(cursor: Cursor) -> list[ObjectRef]:
        """增量清单：返回自 cursor 以来 new/changed/deleted 的对象。"""
    async def fetch(ref: ObjectRef) -> RawPayload:
        """取回原始内容（含元数据）。"""
    def to_records(p: RawPayload) -> list[Record]:
        """源特有结构 → 统一 Record。纯函数，可单测。"""
    async def resolve_ref(ref: str) -> ResolvedRef:
        """source_ref → 可回溯的人类可读定位（含 jump_url）。"""
```

| 维度 | Discord | IMA |
|---|---|---|
| `source_ref` | `guild:ch:msg`（snowflake） | `kb:doc:chunk` |
| 定位回跳 | `https://discord.com/channels/{g}/{c}/{m}` | 知识库深链 / 文件名+页码 |
| 原子粒度 | 消息（+线程内上下文窗口） | 章节 chunk |
| 作者 | user_id（显示名哈希，PII 脱敏） | 文档作者/机构 |
| 时间 | `published_at`（消息）+ `edited_at` | `published_at` + `version` |
| `trust_tier` | 作者历史准确率 + 频道权重 | 文档类型/机构 |

### 3.2 统一记录模型 Record

```python
Record(
  source        = "discord" | "ima",
  source_ref    = "discord:8812.../9912.../1177...",
  author        = "u_8f3a…",          # PII 脱敏
  published_at  = "2026-09-05T09:14:22Z",   # 原文署名/发送时间
  first_observed_at = "2026-09-05T10:02:11Z", # 我方首次观测到的时间，回测以它为准
  ingested_at   = "2026-09-05T10:02:15Z",
  text          = "……逐字原文……",
  trust_tier    = "A",
  lang          = "zh",
  tickers       = ["300308", "中际旭创"],
  doc_type      = "message" | "research" | "note",
  is_boilerplate = False,             # 模板段标记，检索时排除
  duplicate_of  = None,               # 近重复指向，检索时折叠
  superseded_by = None,               # 同 series 新版本，旧版不可作证据
)
```

### 3.3 统一查询 DSL：一个 `corpus_search` 覆盖两源

```python
@tool
async def corpus_search(
    query: str,
    sources: list[str] = ["discord", "ima"],
    tickers: list[str] = [],                 # 精确实体过滤，高选择性
    authors: list[str] = [],
    channels: list[str] = [],
    since: str = "", until: str = "",         # ISO8601；空则用默认窗口
    doc_types: list[str] = [],
    recency_half_life_hours: float = 0.0,     # 0=不衰减；按 doc_type 覆盖
    top_k: int = 10,
) -> str:
    """在统一资料库中检索相关原文片段。只返回定位信息（source_ref + 摘要片段 +
    时间戳），引用任何观点前必须先用 corpus_fetch 按 source_ref 取回逐字原文。
    """
```

**统一返回体 Hit**（所有工具共用，Agent 形成稳定心智模型）：

```python
Hit(
  source_ref   = "discord:8812.../9912.../1177...",
  source       = "discord",
  jump_url     = "https://discord.com/channels/...",
  author       = "u_8f3a…",  author_tier = "A",
  published_at = "2026-09-05T09:14:22Z",
  age_hours    = 3.2,
  snippet      = "…光模块明年需求…",      # 仅定位用，禁止引用
  score        = 0.71,  matched = {"tickers": ["300308"], "rerank": 0.83},
  vector_indexed = False,               # 嵌入批未处理完时为 False
  llm_extracted  = False,               # snippet 是否含 LLM 生成内容
  stale         = False,                # 超 freshness SLA 标记
)
```

要点：**`snippet` 与「证据」在类型上分离**。`Hit` 只回答「看哪里」，`corpus_fetch(source_ref)`
才返回可引用的逐字原文。这条边界是精度红线在接口层面的体现。

### 3.4 五个工具（建议先收敛到三个）

| 工具 | 职责 | 建议 |
|---|---|---|
| `corpus_search` | 语义+结构混合定位 | **核心，必做** |
| `corpus_fetch` | 按 ref 取逐字原文 + 前后文 | **核心，必做** |
| `screen_tickers` | 按信号指标筛选候选标的 | **核心，必做** |
| `ticker_dossier` | 单标的全景档案 | 一期可做成 `screen_tickers` 的参数模式 |
| `strategy_search` | 策略卡检索 | 一期可做成 `corpus_search` 的 `doc_types=["strategy"]` 过滤 |

> 工具过载（5 + 现有 24 = 29 个）会显著升高模型选错工具的概率。建议一期收敛到
> 三个核心工具，`ticker_dossier` 与 `strategy_search` 后续再作为独立工具拆分。

---

## 4. 时效性与增量更新

### 4.1 Discord：三段式

```
① 冷启动回溯  REST /channels/{id}/messages?before={snowflake}&limit=100
              按 channel 倒序分页到起点；snowflake 天然含时间戳，可直接按 ID 切分
② 实时流      Gateway MESSAGE_CREATE / UPDATE / DELETE / DELETE_BULK
              需要 privileged intent: MESSAGE_CONTENT（v10 起读正文必需）
③ 编辑回填    每 N 小时对最近 72h 窗口重扫一次，修正 ② 漏掉的事件与编辑
```

**水印表**保证幂等与断点续传：

```sql
CREATE TABLE channel_watermark (
  adapter TEXT, channel_id TEXT,
  last_snowflake TEXT,        -- 已处理的最大 ID
  backfill_done  INT DEFAULT 0,
  last_sync_at   TEXT,
  PRIMARY KEY (adapter, channel_id)
);
```

限流：per-route bucket，读 `X-RateLimit-Bucket` / `Retry-After` 做指数回退；全局 50 req/s 硬顶。
抓取失败只影响水位，不影响已入库数据。

### 4.2 IMA：清单 diff

`list_objects()` 拉取全量 `ObjectRef{id, version, content_hash}` → 与 `manifest` 比对 →
只处理 new / hash 变化的。删除走软删（tombstone），保留 `source_ref` 以避免 Agent 手里的旧
引用变成死链（应返回「该内容已被删除，删除于 X」而非「未找到」）。

### 4.3 索引侧增量（关键决策）

| 索引 | 增量策略 |
|---|---|
| FTS5 | 行级 `INSERT/DELETE`，与 record 同事务提交 |
| 稠密向量 | **sqlite-vec**（而非 npz）——行级增删，与 FTS5 同库同事务，避免「文本入库但向量还没」的不一致窗口 |
| 信号层 | `ticker_mention` 行级追加；`ticker_daily_agg` 按 (ticker, date) upsert 重算当日 |

**为什么弃用研报方案里的 npz**：研报方案是一键全量建库，npz 无所谓；Discord 是持续流式，
npz 只能周期性全量重建，重建期间索引不一致且延迟高。sqlite-vec 是纯 SQLite 扩展，仍是单文件
零运维，且保留升级 FAISS/pgvector 的余地（接口固定为 `VectorStore` 协议）。

### 4.4 Embedding 延迟不得拖累时效性

Discord 消息短且量大，embedding 走**异步微批**（30s 窗口或 200 条触发）。批内未完成的新消息
**仍可被 `corpus_search` 命中**（走 BM25-only 路径），Hit 标注 `vector_indexed=False`。
即可查性优先于召回质量（优雅降级）。

### 4.5 时效纪律（三道闸）

1. **数据层**：每条记录带 `published_at` / `first_observed_at` / `ingested_at`
2. **检索层**：时间衰减 `exp(-λ·age)`，λ 按 `doc_type` 差异化——Discord 快衰减（小时级），IMA 慢衰减（天级）
3. **提示词层**：`stateful_react_agent/prompts.py` 追加——引用必须声明时间；超 `freshness_sla_hours` 的数据须显式标注为历史观点

配置 `freshness_sla_hours: {discord: 48, ima: 720}`，超 SLA 的 Hit 降权并打 `stale=True`。

---

## 5. 索引与检索策略（挖掘核心）

纯语义检索回答不了「最近有什么新票被盯上」——这是**聚合问题，不是相似度问题**。所以必须有
信号层。

### 5.1 检索主链路：预过滤 → 双路召回 → 融合

```
query ──► 解析出结构化约束 (tickers, time, authors, doc_types)
          │
          ├─► 结构化预过滤：SQL 精确条件 → candidate_ids（高选择性，从 10⁶ 缩到 10³）
          │      ⚠ 精度关键：向量检索在小候选集上显著更准
          ├─► 稀疏路：FTS5 BM25 (jieba 预分词 + unicode61) → top-50
          ├─► 稠密路：BGE-M3 → sqlite-vec 在 candidate_ids 内 ANN → top-50（仅 IMA）
          ├─► RRF 融合 (k=60)：只用排名不用分数，BM25 与余弦不可比
          ├─► [二期] bge-reranker-v2-m3 精排 top-20 → top-k
          └─► 时间衰减 + 权威权重 + 跨源共振 加权
                score = rrf × exp(-λ·age) × authority × (1 + α·resonance)
```

### 5.2 信号层：把「挖掘」变成一等公民

```sql
-- 提及级（从论证单元派生，保留证据锚点）
CREATE TABLE ticker_mention (
  ticker TEXT, source_ref TEXT, author TEXT, published_at TEXT,
  stance TEXT,              -- bullish / bearish / neutral / unstated
  conviction REAL,          -- 0~1
  evidence_span TEXT,       -- 原文中的起止，溯源必备
  llm_extracted INT,        -- 1 = 该字段由 LLM 推断，非原文直取
  PRIMARY KEY (ticker, source_ref)
);

-- 日聚合（支撑"选票"）。注意 bull_bear 存「去均值的偏离度」与「变化量」，
-- 而非原始多空比（详见第 7、12 节）
CREATE TABLE ticker_daily_agg (
  ticker TEXT, date TEXT,
  mention_count INT,
  distinct_authors INT,           -- 抗单人刷屏
  bull_bear_deviation REAL,       -- 相对该作者/全库均值的偏离
  bull_bear_delta REAL,           -- 相对上一期的方向变化
  novelty REAL,                   -- 今日提及量 / 过去30日基线  ← 发现新冒出的票
  cross_source INT,               -- 该日是否也出现在 IMA  ← 跨源共振
  PRIMARY KEY (ticker, date)
);
```

**`screen_tickers` 的默认排序**就是挖掘逻辑本身：

| 维度 | 含义 | 发现的信号 |
|---|---|---|
| `novelty` | 提及量 / 30日基线 | **新标的**：突然被讨论的票 |
| `momentum` | 近3日 vs 前7日斜率 | 正在升温的票 |
| `resonance` | Discord 情绪 ∩ IMA 研究覆盖 | **最强信号**：社媒热度 + 研究背书同时出现 |
| `deviation` | 去均值后的多空偏离 | 分歧大 = 预期差机会；一边倒 = 拥挤度风险 |

**跨源共振是本方案相对单源资料库的独特价值**：只有把 Discord（实时情绪/草根信息）和 IMA
（成体系研究）统一进同一 `ticker` 维度，才能算出这个指标。也是「统一接口」最大的收益点。

### 5.3 反操纵（交易场景必须做）

Discord 是 pump-and-dump 高发地。三层防御：

1. `min_distinct_authors` 默认 ≥3，单作者重复喊单不产生信号
2. `author_tier` 由历史准确率滚动计算（`author_stats` 表：历史观点事后命中率）
3. **单源孤证不升级**：只在 Discord 出现 → 标记 `single_source`；IMA 独立佐证 → 才升为 `evidence-backed`

---

## 6. 关键决策：是否需要向量化

**结论：不要全局向量化。IMA 长文档做，Discord 先不做，用黄金查询集验证后再决定。**

### 6.1 为什么 Discord 不急

向量检索的价值来自「同义改写召回」——随文本长度增长、随专有名词密度减少。Discord 两头都不占：

- **短文本**：信息量少，embedding 容易糊成一团，区分度差
- **术语/黑话密集**：`$NVDA`、「杀估值」是精确匹配项，BM25 命中率 100%，向量反而可能召回标的错误的噪声
- **大量低信息消息**（`+1`、`顶`）：污染向量空间，BM25 天然免疫
- **查询以实体为主**：「NVDA 怎么看」结构化倒排比任何检索都准

**先上 FTS5 + 结构化倒排 + 同义词查询扩展**，成本差两个数量级。

### 6.2 为什么 IMA 该做

长文档、章节化、概念性论述、同一论点多种表述——这是同义改写召回的主场。更新频率低，增量
embedding 不是瓶颈。

### 6.3 核心目标不靠语义检索

「挖掘潜在交易股票」的查询形态是聚合查询（`ticker_daily_agg` 按 novelty 排序）和结构化过滤，
走 `screen_tickers`，**向量一分钱贡献没有**。为一个只服务语义型查询的能力背上 torch 依赖 +
GPU/CPU 算力 + 索引一致性 + 模型升级全量重建的运维债，性价比低。

### 6.4 决策判据（可执行）

```
构造 50 条真实查询（精确型/语义型/聚合型），测 Recall@10
├─ Recall@10 ≥ 0.85 且失败案例不是"语义鸿沟" → 不做向量，继续投入信号层
├─ 失败案例集中在"换个说法就没召回"          → 上向量
└─ 失败案例集中在"召回得到但排不准"          → 上 rerank，别上向量
```

### 6.5 真要做，把成本砍掉 90% 的三刀

1. **只 embedding 高信息量消息**（长度 > 阈值、非纯表情、被回复/转发次数 > N）
2. **只在 IMA 建全量向量**，Discord 建精选子集
3. **sqlite-vec 而非独立向量服务**：行级增删 + 与 FTS5 同事务

**隐性成本提醒**：换 embedding 模型 = 全量重建索引。BGE-M3 现在合适，未来换模型重建的时间成本
要先算进去；BM25 索引无此问题。

---

## 7. 研报特有的检索难题：近重复 + 数字

### 7.1 近重复：危害不是「浪费上下文」，是「虚假共识」

研报近重复四个来源：模板化套话（风险提示/免责声明，单份 10–25%）、同机构系列自我复制、
行业共识（20 家券商论点雷同）、同一文档多版本转载。

- **对向量最致命**：近重复文本向量相似度 > 0.95，top-10 里 8 条是同一段话的副本。模型得出
  「8 份研报都提到」——实际是同一段模板。**凭空制造不存在的证据强度，污染置信度。**
- **对 BM25**：共识表述与差异化表述区分度被压缩；模板段落虚增文档长度稀释正文分数。
- **对 RRF**：近重复破坏「两路独立」假设，boilerplate 因双重排名加成被顶到前面——越融合越糟。

### 7.2 数字：向量在数字上基本失效

1. **数字 IDF 畸形**（BM25）：「2024/2025」DF 极高 IDF→0；「47.3」DF 极低 IDF 爆炸
2. **FTS5 把数字切碎**：默认 unicode61 下 `30%` 切成 `30` + `%`（可能被当分隔符丢弃），
   `3%`/`30%`/`300%` 在索引里塌缩成相近 token——**金融语料灾难级 bug**，必须自定义 tokenizer
   或在 jieba 预分词阶段把「数字+单位」绑成整体 token（`30%`、`47.3亿`、`120bp`）
3. **向量对数字无感知**：「增长 30%」与「增长 300%」余弦相似度可能 > 0.98，「2024」与「2025」
   几乎重合。查「2025 年预测 PE」会稳定召回到 2023 年历史数据——**语义全对，数字全错**

历史三层方案曾假设「检索能给我正确候选，只是不能引用 snippet」。但真实情况是**检索层本身
就可能把数字错误的候选排到前面**——单靠该红线挡不住
「取证了一个语义正确、数字过期的原文」。

### 7.3 叠加：最危险的场景

同一券商连续 6 期月报，核心段落一字未改只更新数字 → 6 个 chunk 向量相似度 > 0.99 → 检索
「XX 公司最新营收」返回 6 个版本（1–6 月数据）。Agent 拿到 6 条「互相印证」证据 →
**虚假共识 + 数字错误 + 无法判断哪个最新**三重叠加，置信度反而最高。

### 7.4 解法：入库层做掉 80%

| 机制 | 位置 | 解决什么 | 成本 |
|---|---|---|---|
| SimHash/MinHash 近重复消除 | L1 入库 | 近重复 chunk（汉明距离 ≤3） | 极低 |
| 不删除，打 `duplicate_of` 指针 | L1 | 保留溯源，检索时折叠只贡献一次 | — |
| Boilerplate 自动识别与剥离 | L1 入库 | DF>30% 段落入模板库，建索引排除，`corpus_fetch` 仍可见 | 低，投产比最高 |
| 数字+单位绑定分词 | FTS5 tokenizer | `30%` 不再塌缩 | 低 |
| 时间表达式结构化抽取 | L1 入库 | 「2025Q3」→ `period_start/end`，检索做硬过滤 | 中 |
| 数值事实入 L3 走 SQL 精确查 | L1→L3 | 数字查询绕开语义通道（已有方案） | 中 |
| `superseded_by` 版本链 | L1 入库 | 同 series 多期次旧版标记被取代，检索只留最新版 | 低，研报必做 |
| MMR / 聚类折叠 | L2 检索 | 相似度 >0.92 折叠成一条，附「另有 N 份报告表述相同：{id}」 | 低 |
| 单报告配额（top-10 内 ≤2 chunk） | L2 检索 | 最简单有效多样性 | 极低 |
| 数字掩码 `<PCT_LARGE_UP>` | 若做向量 | 向量只捕获语义与量级方向 | 中 |

**聚类折叠的展示方式**：不要静默丢弃重复项，而是显式告知 Agent「这 6 份报告表述相同」——把
「共识度」变成显式可核验信号，而非 6 条伪装成独立的证据。

### 7.5 反直觉推论：去重是向量化的前置条件

IMA 若主要是研报，近重复会大幅削弱向量价值。在 boilerplate 和跨期重复没清掉之前上向量，等于
花钱买一个专门放大噪声的组件。所以顺序：先 L1 近重复消除 + boilerplate 剥离 + 数字/时间结构化，
再重评向量。清完之后很多召回缺口会自然消失，语料信噪比变了。

---

## 8. Chunking 之殇与 Wiki 方向：论证单元 + 条目动态视图

### 8.1 Chunking 是 RAG 的原罪，研报尤甚

- 论证链跨页：前提→数据→推理→结论横跨 3–5 页，固定窗口切完单 chunk 只有前提没结论
- 论点与数据物理分离：「如上表所示」而表在两页外
- 研报自带强结构（目录/章节/表格），按 token 窗口切是对结构的主动破坏
- 上下文依赖代词（「该公司」「上述因素」）切出来是断头句

### 8.2 Wiki 方向：对在哪，为什么不能直接用

LLM wiki（STORM / GraphRAG / RAPTOR 类）正面解决了碎片化与近重复（同一论点只写一次附多引用）。
但**纯 LLM wiki 在交易场景有三条硬伤**：

1. **精度红线**：原方案第一条「入库零 LLM 参与」。数字经综合会被改写/张冠李戴/丢单位
2. **丢失分歧**：综合把 20 家机构观点平均化，而**分歧本身就是 alpha**（一致预期已 price in，预期差才是机会）
3. **压平时序**：不同时点观点压进一个条目，「上月看多本月转空」的拐点消失

**Wiki 的价值在于「条目」组织形式，而非「正文由 LLM 生成」。两者拆开即可兼得。**

### 8.3 分水岭：LLM 生成内容 vs 生成索引

- ❌ LLM 写条目正文 → 幻觉进入证据链 → 不可接受
- ✅ LLM 抽取条目结构（实体/论点/数字指针/论证关系）→ 原文一字不动 → 可接受

### 8.4 推荐方案：结构感知切片 + 论证单元 + 条目动态视图

**论证单元（ArgumentUnit）替代 chunk**：按文档原生结构切（小节 300–1500 字，恰是一个完整论证
尺度），版面邻近的表格/图题自动并入所属小节（解决「如上表所示」分离）。零 LLM，纯规则+版面。

**给每单元建结构化索引（LLM 只打标签）**：

```json
{
  "unit_id": "au_7f3a",
  "source_ref": "ima:doc123#p7-9",
  "text": "……逐字原文，绝不改写……",

  "claim": "光模块2026年需求增速将放缓至15%",
  "claim_type": "forecast",
  "entities": ["300308", "光模块", "中际旭创"],
  "metrics": [
    {"name": "需求增速", "value": 15, "unit": "%",
     "period": "2026", "kind": "forecast",
     "raw": "15%", "evidence_span": [1204, 1210], "as_of_version": "2026Q1"}
  ],
  "stance": {"ticker": "300308", "dir": "bearish", "conviction": 0.6},
  "reasoning": ["上游产能扩张", "价格竞争加剧"],
  "llm_extracted": true
}
```

铁律：**每个 `metrics` 项必须能在 `text` 里精确定位，定位不到就丢弃**——让 LLM 抽取结果
变成可自动验证的，幻觉无法通过闸门。

**`claim` 字段的免费收益**：它是规范化、去噪、单一论点的短句，在其上做 BM25 远优于原文全文
（天然完成去 boilerplate + 查询扩展 + 粒度对齐）。**用一次离线可验证的 LLM 调用，买到比向量化
更好的召回质量，不引入幻觉**（claim 只用于召回，永不用于引用）。

**条目（Wiki）是动态视图，不是生成物**：条目 = 实体（公司/行业/策略），正文不由 LLM 写，而由
指向论证单元的指针组成，查询时动态渲染：

```
条目「300308 中际旭创」
├─ 看多论证（按时间倒序）  au_1a2b 2026-08-20 中信 目标价上调 [forecast]
│                          au_3c4d 2026-07-11 国盛 订单超预期 [fact]
├─ 看空论证              au_7f3a 2026-09-01 某券商 需求增速放缓 [forecast]
├─ 数值事实表（来自 L3，非 LLM 生成）
└─ 共识度：4 份报告持类似看多论点（显式列出 id，不伪装成 4 条独立证据）
```

- 去重 ✅ 同一论点聚合，共识度显式化
- 分歧保留 ✅ 多空分开，不平均
- 时序保留 ✅ 按时间排序 + superseded 标记
- 精度 ✅ 数字只能来自 L3 或 corpus_fetch 取原文
- 增量友好 ✅ 新研报→新增单元→条目指针更新，不需重建（优于 GraphRAG 重建社区）

### 8.5 向量位置

排序最后：实体/结构化索引 → claim 字段 BM25（主力，很可能够用）→ 原文 BM25 → 向量（兜底）。
若做向量，建在 `claim` + `text` 拼接上（claim 主导语义），非纯原文。

### 8.6 方案对比

| 方案 | 碎片化 | 近重复 | 数字精度 | 保留分歧 | 增量成本 |
|---|---|---|---|---|---|
| Chunk + 向量 | ✗ | ✗ | ✗ | ✓ | 低 |
| Chunk + BM25 | ✗ | △ | △ | ✓ | 低 |
| GraphRAG / 社区摘要 | ✓ | ✓ | ✗ | ✗ | 高（重建社区） |
| RAPTOR 摘要树 | ✓ | ✓ | ✗ | ✗ | 高 |
| 纯 LLM Wiki | ✓ | ✓ | ✗ | ✗ | 高 |
| **论证单元 + 条目动态视图** | ✓ | ✓ | ✓ | ✓ | **低（指针增量）** |

---

## 9. 长上下文 vs RAG：渐进式展开（L0–L3）

**结论：作为主架构不值得，作为架构里一个明确层级非常值得，且项目现有机制已支持。**

### 9.1 规模

~30k tokens/份研报估算：单份轻松 / 单标的 20–50 份勉强 1M 档 / 行业 200–500 份 ❌ / 全库 5000 份 ❌。
全库入上下文物理不成立；单份/少量成立。这是规模分水岭，非选择问题。

### 9.2 Lost in the Middle + 近重复放大

模型对长上下文呈 U 型注意力（开头结尾好、中间差）。**近重复文本在注意力上互相干扰，进一步
压扁中部区分度**——模型不是看完了 20 份，而是看清了头尾 5 份、中间 10 份糊成一团，而你要的答案
可能就在中间。Same disease, two symptoms.

### 9.3 成本与延迟

50 份 ≈ 1.5M tokens → 长上下文档位 ~$4.5/次；RAG 路线 ~$0.015/次（差 300 倍）。Prompt caching
命中前缀，每次筛选集不同则命中率低。1M token prefill 几十秒~分钟级，Agent 循环 10 轮 = 用户等
十分钟。TTFT 对交互式投研致命。

### 9.4 长上下文对「挖掘」帮不上忙

挖掘信号是跨文档统计性的（「本月提及是 30 日基线 5 倍」「6 家机构同时上调预测」），模型读一遍
原文数不出来，只能来自结构化聚合。长上下文擅长的是**深度理解少数几份文档**。目标（挖掘）在「广」
侧，长上下文在「深」侧。

### 9.5 正确姿势：渐进式展开

```
L0  结构化索引：ticker / metric / period / 数字表         极小，常驻
L1  claim 列表：几十条规范化短句                         小
L2  命中的论证单元全文（3–10 个）                        中   ← 默认到这里
L3  完整研报原文（1–3 份）                               大   ← 按需，显式触发
```

默认停在 L2；需全局综合时才升 L3，且必须是显式工具调用。L3 可复用 `read_file`（带 PDF/docx 解析），
无需新工具。更妙的是 `_overflow.py:370` 的 `maybe_overflow()` 天然支持「先给指针、模型需要时自己
read_file 取全文」——**项目架构本就为渐进式展开设计，全量塞上下文反而在绕开它**。

### 9.6 决策矩阵

| 场景 | 方案 | 成本 |
|---|---|---|
| 1–5 份，深度理解论证链 | 全上下文（直接 read_file 全文） | 高但可接受 |
| 6–30 份，针对性问题 | 论证单元检索（L2） | 低 |
| 30+ 份，找特定信息 | claim 索引 → 论证单元 | 低 |
| 全库，发现性/统计性 | 结构化聚合（screen_tickers） | 极低 |
| 全库，需全局综合 | **两级混合**：聚合先筛到 N 份 → 再全上下文读 N 份 | 中 |

**关键组合**：先用结构化方法把 5000 份缩到 20 份，再用长上下文读这 20 份。这是检索 × 长上下文
的正确乘法。

### 9.7 精度隐患

长上下文里模型在 1M token 找到的数字无法验证出处，易「综合」多源产生混合幻觉，顶到精度红线。
全上下文路线天然不满足逐字溯源，若接受需显式降级溯源能力。

### 9.8 实验建议

构造 25 道跨多份研报综合问题：**A 组** claim+论证单元（L1→L2）；**B 组** 聚合筛出相关研报全文
塞入（L3）。对比答案质量（人工盲评）、数字溯源准确率、成本、TTFT。用数据定 L3 触发阈值（如
「命中单元 > 8 且来自 ≥4 份不同报告时自动升 L3」）。

---

## 10. 模块职责、数据流与技术选型

### 10.1 代码结构

```
plugins/corpus/                    # 新建；放 plugins 层，不新增顶层包破坏五包边界
├─ schema.py          Record / Hit / ArgumentUnit / TickerMention / StrategyCard + DDL + migration
├─ settings.py        路径、凭据(env)、freshness SLA、模型名+版本
├─ db.py              SQLite WAL 连接、user_version 迁移、幂等 upsert 原语
├─ normalize.py       近重复消除、boilerplate 剥离、线程重建、URL 展开、PII、语种、ticker 抽取、数字/时间结构化
├─ entities.py        证券词典：A股6位/港股5位/美股 ticker + 中文别名消歧 → 统一 ticker
├─ index/
│   ├─ fts.py         FTS5 建表、jieba 预分词（数字单位绑定）、BM25
│   ├─ vector.py      VectorStore 协议 + sqlite-vec 实现 + embed() 微批
│   └─ retrieval.py   预过滤 → 双路 → RRF → (rerank) → 衰减 → Hit[]
├─ signals/
│   ├─ extract.py     论证单元抽取（LLM，强制 evidence_span + llm_extracted=1 + 定位校验）
│   ├─ aggregate.py   ticker_daily_agg、去均值偏离、novelty 基线、跨源共振
│   └─ strategies.py  strategy_card 构建与检索
├─ sources/
│   ├─ base.py        SourceAdapter 协议
│   ├─ discord_adapter.py
│   └─ ima_adapter.py
└─ ingest.py          CLI: --source --backfill --watch --verify --prune --status

plugins/tools/                     # 薄 @tool 门面，只做参数校验 + 格式化 + 限流
├─ corpus_search.py  corpus_fetch.py  screen_tickers.py
└─ (ticker_dossier.py strategy_search.py  -- 二期)
```

**为什么放 `plugins/corpus/` 而非 `plugins/tools/_corpus/`**：ingest 是离线 CLI 与常驻 watcher，
塞进 tools 目录会被 sandbox 约定污染；新建顶层包会破坏 AGENTS.md 五包边界与 `import_smoke.py`
两阶段分层断言。`plugins/` 正是外部能力层，且已有 `plugins` extra。

### 10.2 数据流（一次完整挖掘）

```
[离线]  cron/systemd timer
        └─> ingest --source discord --watch       (常驻) ─┐
        └─> ingest --source ima --once            (15min) ┤
                                                          ↓
                              outbox → normalize → Record → 论证单元
                                                          ↓
                              FTS5 + sqlite-vec + 信号层增量
                                                          ↓
[在线]  Agent: "最近有没有被新盯上的光模块标的？"
        ├─ screen_tickers(novelty, lookback=7) → 候选 [300308, 002281, ...]
        ├─ corpus_search("300308 需求 订单")   → Hit[]
        ├─ corpus_fetch(hit.source_ref)        → 逐字原文（唯一可引用来源）
        └─ create_file(/outputs/xxx.md)        → 带 [source_ref, published_at] 报告
```

### 10.3 技术选型

| 组件 | 选型 | 理由 / 备选 |
|---|---|---|
| Discord 采集 | httpx 直调 REST v10 + Gateway WS | 不用 discord.py（全量 message cache 内存不可控）；少重依赖 |
| IMA 采集 | adapter 三档降级：OpenAPI → 导出文件 → 投放目录 | API 能力需实测确认，接口先行实现可换 |
| 主存储 | SQLite WAL（独立 `data/corpus/corpus.db`） | 与 server 业务库物理分离；读写模式不同；不复用 Alembic |
| 稀疏检索 | FTS5 + jieba 预分词（数字单位绑定） | 零运维，规模内毫秒级 |
| 稠密检索 | sqlite-vec（BGE-M3, 1024d, 本地，仅 IMA） | 行级增删 + 与 FTS5 同事务；接口可换 FAISS |
| 重排（二期） | bge-reranker-v2-m3 | 只改排序不改文本，无精度风险 |
| 融合 | RRF k=60 | 分数不可比，只用排名，免调参 |
| 调度 | cron/systemd timer + `--once`，二期并入 server lifespan | 不引入 APScheduler；`--once` 幂等 |
| 输出限界 | 复用 `maybe_overflow()` | meta 设 `max_result_chars=8_000`、`result_is_ranked=True` |
| 凭据 | 沿用 `config/providers.yaml` 的 `${ENV}` 范式 | 不入库 |

### 10.4 与 Harness 集成点（改动清单）

| # | 文件 | 改动 |
|---|---|---|
| 1 | `plugins/tools/__init__.py:34-58` | `_BUILTIN_TOOLS` 追加工具 |
| 2 | `plugins/tools/meta.py:46` `TOOL_META` | 新增条目，`category="corpus"`，检索类 `result_is_ranked=True`，`max_result_chars=8_000` |
| 3 | `tests/test_tool_registry.py:6` | `EXPECTED_TOOLS` 同步（否则 CI 红） |
| 4 | `server/profile.py:33` | 新增 `CORPUS_TOOL_NAMES`，或复用 `MARKET_TOOL_NAMES` 钩子 |
| 5 | `workflows/stateful_react_agent/prompts.py` | 追加引用纪律：先定位后取证、声明时间、单源 vs 跨源、fact/opinion/forecast 区分、**强制检索并陈述一条反方证据** |
| 6 | `pyproject.toml` | 新增 `corpus` extra：sqlite-vec、jieba、httpx(已有) |
| 7 | `deploy/docker-compose.yml` | 新增 corpus 数据卷；SQLite 则无需新服务 |

**不改任何 workflow 子包**——`WorkflowContext` 不提供 `register_tool`。

### 10.5 精度红线（沿用并扩展）

1. 入库管道零 LLM 改写原文；LLM 只允许标注，且必须落 `llm_extracted=1` + `evidence_span`
2. Agent 引用数字/观点只能来自 `corpus_fetch` 逐字原文，**禁止**引用 `Hit.snippet` 或记忆
3. 每条证据带 `source_ref` + `published_at` + `first_observed_at`（三时间戳缺一不可）
4. fact / opinion / forecast 字段级区分，混用视为答案错误
5. embedding 模型版本写入索引元数据，版本不一致拒绝查询
6. 单源孤证不升级为结论；跨源共振才标记 `evidence-backed`
7. 合规：只用 Bot token + 已授权 guild；禁止 user token；PII 脱敏；支持按 user_id 彻底 purge

---

## 11. 风险、盲点与遗漏

> 本节为设计讨论中识别出的、易被技术优化掩盖的非技术性/方向性问题，按「是否改变架构决策」排序。

### 11.1 能让项目停摆的（合规）

1. **研报版权**：券商研报有分发限制，批量入库 + LLM 抽取 + 生成输出每一步都可能踩线。IMA 内文档
   是否有权这样处理需先明确。→ 先做授权范围界定。
2. **投资建议持牌**：输出「潜在交易股票」在很多辖区接近证券投资顾问业务，需持牌。→ 从架构层钉死
   输出形态/用户范围/强制免责，或只做内部研究工具。这反向决定产品形态。
3. **Discord 二次同意 + GDPR**：群成员是否同意发言被长期 AI 分析？付费社群常禁转载。欧盟成员涉
   被遗忘权。→ 频道白名单 + 授权证据 + 按 user_id purge 能力，提前做。

### 11.2 让系统稳定给出错误答案的（金融建模陷阱）

4. **前视偏差（结构缺失）**：`published_at` 远早于真正可见时间，用其做时序会喂入未来信息。
   **必须补 `first_observed_at`**，任何回测以它为准。这是设计稿里漏掉的字段。
5. **卖方研报系统性看多偏差**：原始多空比 ≈ 常数无信息量。真正有信号的是**评级变化**与**相对
   偏离**。→ `ticker_daily_agg` 存去均值偏离度 + 变化量，非原始 `bull_bear_ratio`。
6. **幸存者偏差**：库里只有被写的标的，失败标的根本不在库，任何统计验证会系统性高估。无法靠工程
   消除，评估结论须标注此偏差。
7. **Point-in-time**：财务数据会被追溯调整。用当前值回测历史等于用当时不存在的数据。→ `metrics`
   加 `as_of_version`，按 `as_of` 取当时版本。原方案仅在 macro.db 设计 revision，研报抽取侧缺失。
8. **反身性与 alpha 衰减**：Agent 会成为市场一部分，被广泛采用后信号自我消解。→ 信号强度显式
   衰减因子 + 监控拥挤度。工程手段有限，但需认知。

### 11.3 无法验证价值的

9. **缺 baseline 对照组**：检索质量 ≠ 投资决策质量，且金融 ground truth 难定义。→ 先跑**无资料库**
   的 Agent（仅 web_search）做同样任务作对照，成本近零，决定项目 ROI 论证。
10. **上线前大概率无法证明有用**：交易机会稀疏且相关，样本不足以统计显著。→ 架构须为「无法证明」
    设计：先 shadow mode / paper trading，且先做「辅助研究」而非「决策建议」。
11. **成本账未算**：全库 LLM 抽取约 15 万次调用（数万美元一次性）+ 每日增量。→ 分级抽取：先按
    标题/摘要/机构筛高价值研报，只对这批完整抽取。

### 11.4 被忽略的工程细节

| # | 问题 | 对策 |
|---|---|---|
| 12 | SQLite 批量写持锁：大事务 ingest 阻塞 server 读 | 小批量分批提交，或 staging 库 + 定期 merge |
| 13 | 数据删除级联：合规删除要穿透 Record→单元→claim→FTS→向量→**聚合表需重算** | 设计 `purge_user(user_id)` 反向链路，聚合表按日重算 |
| 14 | 工具过载：5+24=29 个，模型选错概率升 | 收敛到 3 个核心工具，另两个先做成参数模式 |
| 15 | 实体歧义：「平安」=中国平安或平安银行？A+H 双代码？中英混排 | `entities.py` 需上下文消歧 + 别名优先级 |

### 11.5 Agent 确认偏误 + 房间的大象

16. **确认偏误经检索系统放大**：ReAct 首轮检索倾向主导后续。多空分组只提供反方材料未强制。
    → 提示词强制「下结论前必须检索并陈述至少一条反方证据」，改动极小杠杆很大。
17. **管道扎实但管子尽头接什么没定义**：原始需求含「挖掘交易策略」，`strategy_card` 只是数据结构，
    **方法论（策略表达/验证/组合）几乎全空**。这是产品真正护城河，应单独立项讨论。

---

## 12. 分期与验收

> **本节分期已被 P0 收敛取代。** 经架构评审，先做投研内核与最小资料库（P0），
> 施工规格见 [p0-implementation-spec.md](p0-implementation-spec.md)。下表为 P0 之后的路线。

| 阶段 | 内容 | 验收闸 | 状态 |
|---|---|---|---|
| **P0a** | `position_sizing` + `strategy_lint` + `strategy.json` + 策略对话闭环（stub 研报） | Agent 调用工具算仓位、`lint.passed=true`、缺失参数会追问 | **待施工** |
| **P0b** | 20 份真实研报 ingest + FTS5 + `corpus_search`/`corpus_fetch` + 离线校验脚本 | 20 道黄金题全对；数字溯源命中率 100%；去重与 `superseded_by` 生效 | **待施工** |
| **P1** | 全量 ingest + 论证单元抽取 + `screen_tickers` + 向量判据 + IMA/Discord adapter | Recall@10 ≥ 0.85；「新标的」P@10 ≥ 0.6 | 推后 |
| **P2** | `EvidenceAuditObserver` + 提示词引用纪律（含强制反方证据）+ L3 渐进式展开 | 未溯源数字可标记；端到端产出可逐条核对 | 推后 |

**P0 与 P1 之间必须停下来验收**：P0a 若跑不通，P0b 全不做——理由见
`docs/tittel/trading-strategy-platform-feasibility.md:271`。

**远期验收指标**（P1 及以后）：
- 精度：`corpus_fetch` 逐字可重现 100%；数值查询精确率 100%
- 时效：Discord P95 ingest lag < 60s
- 挖掘：`screen_tickers` 对「近 30 天首次提及且多作者共振标的」精确率/召回（人工标注集合）

---

## 13. 待决问题与下一步

### 13.1 已决策（评审收敛结果，见 P0 实施规格）

| 项 | 结论 |
|---|---|
| 阶段顺序 | P0 先行（投研内核 + 最小资料库），Discord/IMA 推后 |
| 合规 | 研报为自有合法订阅、仅内部使用 → 正常做；P0 演示与文档不引用真实研报内容 |
| 样本规模 | 20 份，**刻意挑选**（跨机构/同系列多期/双格式/故意重复），非随机 |
| 向量化 | P0 不做；用 20 道黄金题测 FTS5 基线，按第 6.4 节判据再决定 |
| 产出形态 | `/outputs/strategy.json`（机器校验）+ `/outputs/report.md`（人读） |
| 溯源校验 | P0 用离线脚本；`EvidenceAuditObserver` 推到 P2 |
| 数据落地 | `data/corpus/`（仓库根 + `.gitignore`），不用 `plugins/fin_data/` |
| 结构化输入 | 首轮 task 文本 + Agent 追问；不建 TUI addendum 通道 |
| 计算内核 | P0 只做 `position_sizing` + `strategy_lint`；`backtest_strategy` 推 P1 |
| 验收立场 | 不要求「指导有投资价值」，但要求三条硬闸（溯源/算术出工具/schema 完备） |

### 13.2 仍待决

1. **策略方法论**：什么是可计算、可验证的交易策略表达——本产品真正护城河，尚未设计
2. **IMA API 能力**：需实测确认 OpenAPI 是否存在及字段，决定 adapter 实现档位
3. **L2→L3 触发规则**：渐进式展开的升级阈值，需第 9.8 节实验定夺
4. **论证单元抽取 prompt**：技术含量最高、最决定成败的一步，需单独详细设计（含
   `evidence_span` 校验机制、抽取约束设计）
5. **baseline 对照组**：无资料库的 Agent 做同样任务的对照实验，决定项目 ROI 论证
6. **20 份样本由谁挑选**：需明确执行人与挑选时间（约 1–2 小时）

---

*本文整合自多轮架构讨论，覆盖：整体架构、统一接口、时效增量、检索与信号层、向量化决策、近重复
与数字难题、chunking 与 wiki 方向、长上下文与 RAG、以及合规/建模/验证类的盲区。所有代码路径与
行号均基于当时代码快照，落地前须以最新代码为准复核。*
