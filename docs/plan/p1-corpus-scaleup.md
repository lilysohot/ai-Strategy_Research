# P1 语料规模化与持续接入 · 主题计划

| 项 | 内容 |
|---|---|
| 版本 / 状态 | v1.0 · **P0 已完成**（P0a 11/11 ✅ · P0b §7.2 五条验收 ✅）· **P1 未开始** |
| 上游文档 | [p0-research-kernel.md](./p0-research-kernel.md) · [plan.md](./plan.md) |
| 远期架构 | [corpus-ingestion-architecture.md](../corpus-ingestion-architecture.md)（Discord / IMA / 向量 / 信号层，仍推后，本文不重复设计） |
| 状态图例 | ✅ 已完成 · 🔄 进行中 · ⬜ 未开始 · 🅿️ 暂缓 · ⛔ 阻塞 |
| ⚠️ 存储变更 | **数据层已定为 PostgreSQL**（zhparser 中文全文 + pgvector 留位），见 [data-layer-architecture.md](./data-layer-architecture.md) v2.0 与 [pg-migration.md](./pg-migration.md)。本文涉及 WAL / `VACUUM INTO` / FTS5 的描述**以那两份为准** |

> **本文是 P0 之后的下一段排期入口**。P0 的施工规格见
> [p0-implementation-spec.md](../p0-implementation-spec.md)，持续接入的远期设计见
> `corpus-ingestion-architecture.md`。

---

## 1. 目标与范围

把语料接入做成可持续的能力：**份数不预设**——目录里放多少文件就 ingest 多少，
全量与增量都按目录实际文件数执行；并建立每日增量的常态化跑批。

**为什么是它**：原计划 `p0-research-kernel.md` 第 38 行显式排期「全量 8000 份 ingest | P0b 之后」；
且实际每天新增**不止 10 份、有时 30 份**（约 1.1 万/年，3 年后约 4 万份）。

**由此得到的关键判断**：语料是**流**而非一次性批次，所以目标不是"跑一次 8000 份",
而是「**首次全量 + 每日增量**」——增量能力必须与首次全量同期建成，否则每天都要重解析全量。

### 不在本次范围（含推后理由）

| 项 | 推到 | 理由 |
|---|---|---|
| Discord / IMA 接入 | 远期 | 见 `corpus-ingestion-architecture.md`，已确认推后 |
| 前端表单（CapitalForm / FillPriceForm） | Web 阶段 | TUI 无前端；接 web 时用 server 现成通道 |
| `EvidenceAuditObserver` 在线审计 | P2 | 离线三闸逻辑跑对后再搬进 observer |
| 增量 FTS / 索引版本 / schema 迁移框架 | 不做（已收回） | 按 30/天测算，**全量重建 FTS 在百万块量级是分钟级**，几年内不是瓶颈 |
| 性能优化（并发 / 缓存 / N+1 / 结构 / 资源 / 日志 6 轴） | 技术债，入账 | P0 验证阶段不做，见 §6 |
| 独立服务进程（HTTP / RPC） | 按需（不现在做） | 当前是单写入者 + 本地读取，进程内服务层已够；接口保持不变，将来需要多进程/跨机时可平滑升级，见 §2.1 |

---

## 2. 从 P0 继承的约束

三条硬闸继续适用于规模化后的全部产出（`p0-research-kernel.md` §2）：

1. **数字可溯源**：每个数字能在被引用原文的 `source_ref + 定位符` 处逐字找到
2. **算术不出 LLM**：`sizing` 必须带 `computed_by: "position_sizing@v1"`
3. **schema 完备**：止损 / 失效条件 / 时间窗必填，`strategy_lint` 硬校验

**P0b 遗留的 defer 项**（原计划标为不阻塞，规模化后性质变化，见 E 组）：

| 项 | P0b 判定 | P1 判定 |
|---|---|---|
| `superseded_by` | defer，靠 `doc_id` 日期前缀 + 提示词 | **升级为必需**（E1）——同系列新期持续堆积会劣化检索 |
| `first_observed_at` | defer | 暂缓（E2），等新颖性聚合（D4）再做 |

---

## 2.1 语料服务层（PG 按服务层管理）

**决策**：源数据（原始研报）放 `data/` —— 文件即资产；
**数据库不当裸文件用，统一走服务层**（存储已由 SQLite 换成 **PostgreSQL 18.6**）。

**为什么**：备份、内容梳理、将来的存储替换都需要**唯一收口**。此前
`corpus_search` / `corpus_fetch` / `verify` / `golden` 各自 `sqlite3.connect`
直连，导致「备份无处下手、梳理逻辑无处安放、换存储要改 N 处」。

> **进度（2026-09-08）**：`service.py`（`CorpusService`，PG 实现）已建成；
> `corpus_search` / `corpus_fetch` / `verify` / `golden` **四个调用方已全部改走服务层**。
> 存储切换随迁移一并完成，详见 [pg-migration.md](./pg-migration.md) v2.0。

**形态：先做进程内服务层**（库内模块 + 统一入口），**不起独立进程**。
当前是单写入者 + 本地读取，独立进程只增加部署成本、不解决实际问题；
接口保持不变，将来真需要多进程/跨机时再升为独立服务，调用方无感。

**唯一收口原则**：所有调用方**一律不再直接 `sqlite3.connect`**，全部经服务层。
否则"服务层"只是多一层转发，备份与梳理仍然没有落点。

**服务层职责**（`plugins/corpus/service.py`）：

| 能力 | 接口 | 说明 |
|---|---|---|
| 连接治理 | 内部 | **PG 连接池**（存储已改 PG）；原 SQLite 的 WAL / busy_timeout 方案作废 |
| 写入 | `ingest(path)` / `ingest_dir(root)` | 解析 → 落库 → **建索引** 一次完成，杜绝"入库未建索引"的静默失效 |
| 读取 | `search(q)` / `fetch(doc_id, locator)` / `document_text(doc_id)` / `list_documents(...)` | 工具与离线校验的统一入口 |
| **备份** | `backup(dest, mode=)` / `restore(src, target_dsn)` | **优先 `pg_dump`**（含 schema/约束/索引，一致性快照）；无该二进制时自动退回纯 Python 的 CSV 逻辑备份。恢复到全新库会自动补齐扩展与 `zhcfg`（原 `VACUUM INTO` 快照方案随 SQLite 作废） |
| **内容梳理** | `mark_superseded(new, old)` / `set_published` / `dedupe()` / `list_by_series()` / `list_failed()` | 取代关系、时效字段、去重、系列归组、失败清单 |
| 运维 | `stats()` / `reindex()` | 台账统计（added/skipped/failed/needs_ocr）、索引重建 |

---

## 3. 任务清单

### S 组｜语料服务层（基础，A 组的载体）

| # | 任务 | 依赖 | 状态 | 要点 / 验收 |
|---|---|---|---|---|
| S1 | 建 `plugins/corpus/service.py` | — | ✅ | **已建成（PG 实现）**：连接治理 + 读写/运维接口齐备；WAL / busy_timeout 随 SQLite 作废，改为 psycopg 连接池（见 §2.1） |
| S2 | 调用方改为只走服务层 | S1 | ✅ | **全部完成**：`corpus_search` / `corpus_fetch` / `verify` / `golden` **与 ingest CLI** 均走服务层，无 `sqlite3.connect` 直连（`service.py` 与迁移脚本除外） |
| S3 | 备份能力 | S1 | ✅ | **`backup()` / `restore()`**：优先 `pg_dump`（自定义格式，含 schema / 约束 / 索引，一致性快照）；无该二进制时自动退回纯 Python 的 CSV 逻辑备份。恢复时自动补齐扩展与 `zhcfg`（**库级对象不随 `CREATE DATABASE` 继承**，灾备到新库必须补）。**已实测**：备份 57 份 → 恢复到全新库，行数一致、生成列自动重算、原文逐字一致、检索可用。<br>⚠️ 运维提示：本工作区（WSL）**无 `pg_dump` 客户端**，实际走 CSV 模式；生产/容器内应能用到 `pg_dump`。<br>🐛 顺带修复：`snapshot()` 原用 psycopg2 的 `copy_to`，**psycopg3 无此方法 ⇒ 该备份功能此前从未跑通** |
| S4 | 内容梳理接口 | S1 | 🔄 | 已有 `stats()` / `list_by_status()` / `list_revisions()`；**仍缺** `mark_superseded` / `set_published` / `dedupe` / `list_by_series` / `list_failed`。验收：可标记取代关系并查询生效 |

> **A 组四条实现在服务层内**（S1 的组成部分），不另起一套直连代码。

### A 组｜全量前置（最小集，属正确性/可运维，非优化）

> 这四条是「跑全量」和「每天跑」的**成立前提**。不做则全量会**静默失败**（白跑数小时才被发现）。

| # | 任务 | 依赖 | 状态 | 要点 / 验收 |
|---|---|---|---|---|
| A1 | `ingest` 后检索可用（原「末尾接 `build_index`」） | — | ✅ | **在 PG 下结构性解决**：`blocks.tsv` / `documents.title_tsv` 是 **GENERATED ALWAYS AS ... STORED** 列，入库即由 PG 自动维护，「忘了建索引」这个失败模式**不存在**。已实测：`tests/test_corpus_a1_ingest_search.py` 在临时 schema 跑「init_db → ingest → **立即** search」往返（不调用任何索引构建）**2 passed** |
| A2 | 跑批统计与失败日志 | — | ✅ | `service.ingest_dir` 已实现：`IngestStats` 输出 `added / skipped_duplicate / skipped_unchanged / needs_ocr / empty / failed`，**失败带文件名 + 原因**（`failures: [{path, reason}]`）并落 `logger` |
| A3 | 跳过已入库未变文件 | — | ✅ | `service.ingest_dir` 已实现：按 `(source_path, content_hash)` 预检跳过未变文件。实测二次跑批 `added=0 / skipped_unchanged=1`（A1 测试第二个用例） |
| A4 | 跑批 CLI 入口 | A1–A3 | ✅ | `python -m plugins.corpus.service ingest [--dir X] [--db DSN]` 一键跑通（内部先 `init_db()` 再 `ingest_dir()`）；另有 `stats` / `snapshot` 子命令 |

> ✅ **A 组已全部完成（2026-09-09 核实）** ⇒ §7 的第一个**硬停点已通过**，
> **B1 首次全量可以启动**（建议先把 S3 备份补上——跑 2–7h 之前要有退路）。
> ⚠️ A1 通过的原因是**存储换成 PG 后 GENERATED 列带来的结构性保证**，
> 不是"补了一个 `build_index` 调用"；回归门禁已把这个保证钉住。

### B 组｜首次全量

| # | 任务 | 依赖 | 状态 | 要点 / 验收 |
|---|---|---|---|---|
| B1 | 首次全量 ingest（**份数以目录实际文件为准，不预设**） | A 组 | ✅ | **已核实（2026-09-09）**：目录可解析文件 **57**（54 pdf + 1 docx + 2 md；另 36 个 Windows `:Zone.Identifier` 附属文件不参与解析），`documents=57`、`blocks=888`、`fully_ingested=True`，服务层自证全量完成。`by_status`: ok 56 / empty 1 |
| B2 | 全量后回归 | B1 | ✅ | **通过（2026-09-09）**：`test_corpus_golden` + `test_corpus_verify_b7` 共 4 项全绿，Recall@5 与溯源命中率不退化 |

### C 组｜每日增量（稳态）

| # | 任务 | 依赖 | 状态 | 要点 / 验收 |
|---|---|---|---|---|
| C1 | 每日增量接入（**份数以实际为准**） | B1 | 🔄 | **C1a 跑批任务化已完**（幂等跑批 + advisory lock 防重入 + 退出码 0/1/2）；**C1b 定时调度未做**（待确认 WSL/Windows 调度方式）。验收：每天只解析新增份，**跑批耗时与语料总量无关**。细化方案见 **[p1-daily-incremental.md](./p1-daily-incremental.md)** |
| C2 | 跑批台账留存 | C1 | 🔄 | **C2a 已完**：`ingest_runs` / `ingest_failures` 两表 + `runs` / `failures` 查询子命令 + 磁盘 JSONL 镜像。**失败带文件名 + 原因**已实测可查。C2b（90 天保留清理）未做。见细化方案 |

### D 组｜P1 能力（依赖规模，顺序不可换）

| # | 任务 | 依赖 | 状态 | 要点 / 验收 |
|---|---|---|---|---|
| D1 | 表格抽取（pdfplumber） | — | ✅ | §9 记账「表格数字未入 L3」是 P0 真实短板，**已修复**。`ingest.py` 新增 `extract_pdf_tables`（pdfplumber，**可选依赖**，缺失/失败均不拖垮 ingest），按行列重建表格并以 `[表格]` 段追加进**该页**块（页码 locator 不变，取证仍按页）⇒ 表格数字以「指标 \| 数值」规整形式进 L3。实测真实研报抽出财务表（`营业收入 \| 174144 \| 172054 \| 173340`）。验收：`tests/test_corpus_tables.py` 6 项通过。⚠️ 代价：pdfplumber 比 pymupdf 慢（测试 6 项 17s），全量可按需用 `with_tables=False` 关闭 |
| D2 | claim / entities LLM 抽取 | B1 | ✅ | **已实现**。新增 `plugins/corpus/claims.py`：① **分级**（规则筛「无数字 / 免责声明」⇒ 实测 888 块中 278 块无信号被跳过，省下约 31% 调用）；② LLM 抽取（prompt 约定 JSON，输出容错解析：去 ```围栏、套对象拆包、非法 JSON 返回空而非抛）；③ **退避重试**（实测供应商 429「模型访问量过大」，重试即可救回）；④ 字段清洗（kind 非法按预测词回退、空 ticker 过滤、confidence 夹到 [0,1]、claim 截断 500 字符防 UNIQUE 索引行超限）。<br>**存储**：新表 `claims`（`doc_id`/`seq`/**`locator` 与 blocks 同一套取证句柄 ⇒ 硬闸①可溯源**、`kind`、`tickers text[]` + GIN 索引供 D3/D4 聚合、`metric`/`value_text`/`period`/`confidence`），`init_db` 幂等建表，不影响既有表。<br>**集成**：`service.extract_claims()`（LLM 可注入）+ `claims_of(doc/ticker/kind)` + CLI `extract-claims` / `claims`。<br>**验收**：`tests/test_corpus_claims.py` 11 项通过（分级、JSON 容错、字段清洗、locator 可溯源、**端到端落库与查询**、幂等重跑、单块失败不中断、重试恢复）。<br>⚠️ **全量未跑**：真实 smoke 触发供应商 429 限流（GLM-4.7-Flash），需分批 / 换模型后再跑全量 |
| D3 | `screen_tickers` 挖掘能力 | B1, D2 | ⬜ | 20 份算出的"新标的"是统计噪声，**必须等全量** |
| D4 | 共识度 / novelty 聚合指标 | B1, D3 | ⬜ | 同上，必须等全量 |
| D5 | `backtest_strategy` | — | 🅿️→**可解禁** | 原阻塞：依赖历史行情源。**已解除（2026-09-09）**：market 模块（同花顺 fuyao）提供 `market_history` 日 K（10 年窗口、复权口径可选），历史价格不再是"假的"。启动前置：① 回测口径需拍板（用 `adjust=none` 不复权还是 `forward` 前复权——跨次调用不可比，见 ths-market-data.md §9 坑1）；② 回测结果属**衍生数字**，须由确定性工具产出并带 `computed_by`（对齐硬闸②），不得由 LLM 编造 |
| D6 | 向量检索（BGE-M3 + sqlite-vec） | — | 🅿️ | **按判据决定**：当前 FTS 在现有语料上 Recall@5 = 100%，**无缺口**；等实际语料规模下黄金题掉分再上 |
| D7 | Discord / IMA 接入 | — | 🅿️ | 远期，见 `corpus-ingestion-architecture.md` |
| D8 | 前端表单 | — | 🅿️ | Web 阶段 |

### E 组｜P0b 遗留 defer（随规模升级）

| # | 任务 | 依赖 | 状态 | 要点 / 验收 |
|---|---|---|---|---|
| E1 | `superseded_by`（同系列取代） | B1 | ⬜ | **由 defer 升级为必需**：一年累计大量同系列新期，无取代关系则近重复持续堆积、BM25 返回所有期次、时效判断全压给 Agent。验收：同系列查询只返回最新一期（或最新期排在首位且可解释） |
| E2 | `first_observed_at` | B1 | 🅿️ | 新颖性判定依赖，等 D4 再做 |

### G 组｜可管理化与可视化

| # | 任务 | 依赖 | 状态 | 要点 / 验收 |
|---|---|---|---|---|
| G1 | **台账 CLI** | S1 | ⬜ | `stats` / `list` / `show <doc_id>` / `failed` / `needs_ocr` / `series`；**只读消费服务层，不另起一套 SQL**。验收：一条命令看到 份数 / 块数 / 日期范围 / 格式分布 / 异常清单 |
| G2 | **静态 HTML 报告** | G1 | ⬜ | 由 `stats` 生成，**零部署**；看趋势（每日新增）与异常（failed / needs_ocr / 重复 / 修订并存）。验收：`corpus report --out x.html` 产出可打开报告 |
| G3 | 交互式看板（Web / TUI） | G1 | 🅿️ | **按需再开**。G1+G2 已覆盖约 80% 需求；先不做，避免摊大 |

> **两条硬约束**：
> 1. 可视化**只读消费服务层**，不得另写直连查询 —— 否则重复 SQL 散落，与「服务层收口」原则直接冲突。
> 2. 合规：看板默认只展示**元数据与统计**；研报原文按需展开且需脱敏（与 §5「原文明文落 trace」同源风险）。

---

## 4. 验收标准（P1 阶段）

| # | 标准 |
|---|---|
| 1 | 首次全量：**`documents` 数 == 目录实际可解析文件数**（不预设目标值），`failed` / `needs_ocr` 有清单且可解释 |
| 2 | 首次全量后回归：**黄金题 Recall@5 = 100% 不退化**、溯源命中率 100% |
| 3 | 每日增量：新增报告当天可被检索；**跑批耗时不随语料总量线性增长** |
| 4 | 可运维：任一次跑批的失败项可查到文件名与原因（A2 / C2） |
| 5 | 能力：D1 表格数字可检索；D3 在全量语料上产出可解释的挖掘结果 |
| 6 | **可管理**：台账 CLI 可查（份数 / 异常 / 系列），静态报告可产出；可视化只读消费服务层，无直连查询 |

---

## 5. 已知不覆盖的风险（记账，避免将来误判已验证）

| 风险 | 说明 | 何时暴露 |
|---|---|---|
| 表格数字未入 L3 | D1 前，表格里的数字检索不到 | D1 |
| 挖掘未验证 | 标的由用户指定，「从库里发现标的」未验证 | D3 |
| 共识度 / novelty 未验证 | 依赖规模与 claim 抽取 | D4 |
| **语料无覆盖时模型会硬凑** | 无相关研报时 `corpus_search` 曾返回与「检索成功」同形的空结果，模型无法区分 ⇒ 反复重试，或引用**不适用**的研报凑 evidence（溯源闸只保证"数字出自原文"，不保证"原文适用于该标的"） | **已加机制**：空结果返回 `coverage="none"` + 明确指令（停止检索 → 转市场数据与技术面，指标数值须带 `computed_by`）；`research_discipline` 同步该规则 |
| **数据源覆盖度未知，模型逐个试错** | 模型只能先 `corpus_search`、再试 `market_*`，逐个发现有没有数据 ⇒ 白费轮次，且容易半途"以为没数据"而放弃或硬凑 | **已加机制**：新增 `data_coverage` 工具——**开局一次**探测「研报 N 篇 / 行情 / 财报」，输出 `full` / `partial` / `research_only` / `none` 四种结论与对应指令；`none`（三源皆无）时要求输出『数据不足，不做判断』并**明确这是唯一正确产出、不是失败**；语料库**故障**与**真的没有研报**分开记（`error` vs `count=0`）。实测：茅台 ⇒ `full`（研报 5 篇）；不存在标的 ⇒ `none` + 正确出口 |
| 溯源校验是宽松的 | 只抓「完全编造」，抓不出「张冠李戴」 | P2 |
| 原文明文落 trace | `trace.py:64` 把 `corpus_fetch` 的**研报逐字原文**全量写 JSONL（无脱敏、无截断）；规模化后**体积与合规风险同步放大** | 随 B1 |
| 修订去重缺口 | `doc_id = f(日期, content_hash)` 且 `source_path` 无 UNIQUE ⇒ **同一文件修订后新旧两版并存**；每日接入下"重发/修订"是常态 | 随 C1 |
| ~~时效无 `published` 列~~ | **已解决（2026-09-08）**：PG 迁移中新增 `published` 列并由 `doc_id` 日期前缀回填，已建 `idx_documents_published` 索引；检索侧已用于「最新一期」的 Recency 偏置 | ✅ 已关闭 |
| 合规 | 自有合法订阅、仅内部使用；演示与文档不引用真实研报内容 | 持续 |

---

## 6. 技术债（验证阶段不做，仅入账）

2026-09-08 对 P0 链路做了 6 轴性能/质量分析，**结论是"暂不改进"，仅登记**。
当前语料规模很小，这些优化的收益低于复杂度成本；等 B1 全量后有实测数据再决定是否启用。

| 轴 | 登记项数 | 该轴最重的一项 |
|---|---|---|
| 调度与并发 | 6 | `_sandbox.py:2842` 持 `threading.Lock` 做网络 IO / 子进程 → 卡死事件循环 |
| 数据访问 | 5 | `index.py:search` 每命中再查一次 `text`（N+1）；~~`blocks` 缺 `(doc_id, locator)` 索引~~（**PG 侧已建** `idx_blocks_locator`，SQLite 实现仍缺） |
| 缓存 | 4 | `corpus_search` / `corpus_fetch` 每次调用新建并关闭 sqlite 连接；`fetch` 无负缓存（穿透） |
| 代码结构 | 7 | `verify.py` 与 `strategy_lint.py` 容差 0.01 **两处独立硬编码** → 会漂移成「在线过、离线不过」 |
| 资源管理 | 3 | `parse_docx:162` 未关闭 ZipFile，批量 ingest 每份 docx 泄漏一个 FD |
| 日志与监控 | 5 | `trace.py:64` 研报逐字原文全量落盘，无脱敏无截断 |

> 注：**A1 / A2 两条不在技术债内**——它们是「跑全量会静默失败 / 丢报告无人知晓」的
> 正确性与可运维问题，属于 P1 的成立前提，必须做。

---

## 7. 排期与停点

| 阶段 | 内容 | 预估 |
|---|---|---|
| **S 语料服务层** | S1–S4 | **约 1 天** |
| **A 全量前置**（实现在 S 内） | A1–A4 | **约 0.5 天** |
| — | **停点：前置验收**（ingest → search 闭环跑通 + 失败有日志 + 二次跑批跳过已入库） | — |
| **B 首次全量** | B1–B2 | **2–7 小时**（独立批处理，不阻塞） |
| — | **停点：全量验收**（规模到位 + 回归不退化） | — |
| **C 每日增量** | C1–C2 | 常驻（每天 10–30 份） |
| **D P1 能力** | D1 → D2 → D3 → D4 | 按规模推进 |
| **E 遗留升级** | E1（`superseded_by`） | B1 之后 |
| **G 可管理化与可视化** | G1–G2 | **约 0.5 天**（G3 按需，暂缓） |

**停点规则**：

1. **A 组未跑通则不启动 B**。A1 不修的话，全量 2–7h 跑完检索是静默失效的，
   会表现为"语料是空的"而难以定位 —— 这是本次排期唯一的硬停点。
2. **D3 / D4 必须等 B1**（20 份样本下挖掘结果是统计噪声）。
3. **D6 向量检索按判据启动**：先看全量语料上黄金题的 Recall 缺口，有缺口才上。

---

## 8. 进度规则

1. 状态以本文件 §3 表格为准；完成后改 ✅ 并在要点栏记录实际结果（含发现的 bug）
2. 出现阻塞时标 ⛔ 并注明阻塞原因与解除条件
3. A 组四条属于「成立前提」，不计入"可推迟的优化"；§6 技术债在 B1 完成前一律不动
4. 范围变更需先回写本文件再改实施
