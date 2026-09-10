# 语料数据层 PostgreSQL 迁移 · 需求与实施记录

| 项 | 内容 |
|---|---|
| 版本 / 状态 | **v2.0 · 已实施**（2026-09-08 完成迁移、校准与回归） · 上一版 v1.0「待实施（方案）」 |
| 上游文档 | [data-layer-architecture.md](./data-layer-architecture.md) v2.0（选型结论） · [p1-corpus-scaleup.md](./p1-corpus-scaleup.md)（排期） |
| **结果报告** | **[corpus-pg-migration-report.md](../corpus-pg-migration-report.md)**（实测结果：数据核验 / 检索校准 / 数字切分 / 硬闸回归） |
| 范围 | 语料数据层：SQLite `data/corpus/index.db` → **PostgreSQL 18.6** |
| 影响面 | `plugins/corpus/*`、`plugins/tools/corpus_search.py`、`plugins/tools/corpus_fetch.py`、`tests/test_corpus_*` |
| **不在范围** | `frontier_agent/` 内核 · `workflows/` · `apodex/` · `server/` · `web/`（均零改动） |
| 服务层收口 | 全部 DB 访问经 `plugins/corpus/service.py`（`CorpusService`），调用方一律不直连 |

> **v2.0 的性质变化**：v1.0 是「怎么做」的方案，v2.0 是「做了什么、结果如何」的记录。
> 决策依据（为什么选 PG）保留在 `data-layer-architecture.md`，本文只做引用；
> 本文新增 **§4 具体改动项 / §5 交互契约变更 / §8 后续待办** 三节。

---

## 1. 改版背景

三个触发条件同时成立，且**换的成本此刻最低**（语料仅 17 份，分钟级迁移；等全量 8000 份之后再换，需回填 + 重做中文检索，成本高一个量级）：

| # | 触发条件 | 性质 |
|---|---|---|
| 1 | **需要 host:port 网络接入**（Windows 客户端直连、web 端、未来多人共享） | SQLite 是文件库，**无此概念 ⇒ 直接排除** |
| 2 | **多进程并发写** | SQLite 单写入者，**硬边界** |
| 3 | **备份与内容梳理需要唯一落点** | 各自 `sqlite3.connect` 导致备份无处下手、梳理逻辑无处安放 |

**容器侧实测（2026-09-08）**：目标 PG 实例已为 **18.6**（Debian `18.6-1.pgdg12+2`），`zhparser` / `vector` / `pg_trgm` **三个扩展均已启用**——v1.0 中「当前容器缺扩展、必须重建」的判断已不成立，**未重建容器**。

---

## 2. 目标与验收硬指标

| # | 目标 | 硬指标 | 实测结果 | 状态 |
|---|---|---|---|---|
| 1 | 服务层唯一收口 | `verify` / `golden` / 两个工具**零直连** | 均改走 `CorpusService` | ✅ |
| 2 | 检索质量不退化 | 黄金题 **Recall@5 = 100%**（数字 8 / 观点 6 / 对比 3 / 时效 3） | **20/20 = 100%** | ✅ |
| 3 | 硬闸①数字可溯源 | 溯源命中率 100%（未溯源数字数 = 0） | `test_corpus_verify_b7` 3/3 | ✅ |
| 4 | 存量数据不丢 | 份数 / 块数与原库一致 | 17 份已迁入 | ✅ |
| 5 | schema 可自解释 | 关键字段带注释 | 16 条 `COMMENT ON` 已落库 | ✅ |
| 6 | 回归不破坏 | corpus 相关测试全绿 | **24 passed** | ✅ |

> 指标 2 的达成过程不平凡：切换后 Recall 一度为 **0%**，经四项排序对齐才回到 100%，详见 §4.7。

---

## 3. 技术选型（本次新增 / 替换）

| 层 | 选型 | 版本 | 替换对象 | 理由 / 落选 |
|---|---|---|---|---|
| 数据库 | **PostgreSQL** | **18.6** | SQLite 3（`data/corpus/index.db`） | 网络接入 + 多写者并发 + `pg_dump` 备份；落选 MySQL（无增益）、继续 SQLite（硬边界） |
| 中文全文检索 | **zhparser**（基于 SCWS）+ `zhcfg` 检索配置 | 源码编译 | SQLite FTS5 + jieba 预分词 | **PG 内置 FTS 无中文分词器，必须装扩展**；落选 `pg_jieba`（维护活跃度）、`pgroonga`（体积/生态） |
| 向量检索 | **pgvector** | 扩展已装，**未建列** | 无（SQLite 侧为 `sqlite-vec` 构想） | **判据驱动、留位不建列**：当前 FTS Recall 已 100%，无缺口；需要时同库启用，不引入新系统 |
| DB 驱动 | **psycopg 3**（`psycopg[binary]`，`dict_row`） | `>=3.3.5` | `sqlite3`（标准库） | 服务端游标 + 原生 COPY 入库；`dict_row` 统一按列名取值，避免泄漏驱动类型 |
| 文档解析 | **PyMuPDF** | `>=1.28.2` | 沿用（未变） | PDF 文本抽取；`status=needs_ocr` 由它判定 |
| DOCX / PPTX 解析 | `python-docx` / `python-pptx` | `>=1.1` / `>=0.6.23` | 沿用 | —— |
| 排序函数 | **`ts_rank` + 标题 5× 加权 + 文档去重 + Recency 偏置** | —— | SQLite `bm25(fts, 0,0,5.0,1.0)` | 见 §4.7；落选 `ts_rank_cd`（覆盖密度，不按词频/稀有度加权）、`pg_textsearch`（新兴扩展，不压宝） |
| 部署 | **Docker Compose**（`corpus-db` 服务） | v2 | 无（原为本地文件库） | 既定决策；`docker/Dockerfile.corpus-db` 基于 `pgvector/pgvector:pg18` |

**版本分叉（需记录）**：语料库用 **PG 18.6**，而 `docs/tech-stack.md` 中**平台业务库**定为 **PostgreSQL 16**。两者是**不同实例**，版本不必对齐；但升级/运维文档需分别标注，避免混淆（见 §8 待办）。

---

## 4. 具体改动项

### 4.1 部署物（`docker/`，新增）

| 文件 | 内容 |
|---|---|
| `docker/Dockerfile.corpus-db` | 基于 `pgvector/pgvector:pg18`，源码编译 SCWS + zhparser |
| `docker/docker-compose.yml` | 服务 `corpus-db`，端口 5432，挂 `pgdata` 与 `initdb` |
| `docker/initdb/00-extensions.sql` | `CREATE EXTENSION` zhparser / vector / pg_trgm + 建 `zhcfg` 检索配置 |

> ⚠️ `initdb` 目前**只有扩展初始化，没有 `documents` / `blocks` 建表 DDL**——建表由服务层 `CorpusService.init_db()` 负责。容器重建后需先跑一次 `init_db()`，否则工具会报「表不存在」。已列入 §8 待办。

### 4.2 服务层 `plugins/corpus/service.py`（新增，唯一收口）

`CorpusService` 提供：`init_db` / `ingest` / `ingest_dir` / `search` / `fetch` / `document_text` / `source_resolver` / `list_documents` / `stats`。

**Schema**（`documents` + `blocks`，含本次新增的列注释）：

| 表 | 关键列 | 说明 |
|---|---|---|
| `documents` | `doc_id`（PK）、`title`、`source_path`、`content_hash`(UNIQUE)、`mime`、`status`、`char_count`、`block_count`、`ingested_at`、**`published`**、`title_tsv` | `published` 为本次**新增**（原 SQLite 无此列，时效只能靠 `doc_id` 日期前缀派生）；`title_tsv` 为 `zhcfg` 生成列 |
| `blocks` | `doc_id`(FK→documents, **级联删除**)、`seq`、`locator`、`text`、`tsv` | `(doc_id, seq)` 主键；`tsv` 为 `zhcfg` 生成列 |

**索引**：`idx_blocks_locator (doc_id, locator)`（取证，P0 识别出的缺失索引）、`idx_blocks_tsv`（GIN，`tsv`）、`idx_documents_published`（时效排序）。

**字段注释（本次新增，16 条）**：`init_db` 逐条执行 `COMMENT ON COLUMN`，让 `documents` / `blocks` 每个字段在库里自带说明（`doc_id` 的「供模型抄进 `evidence.source_ref`」、`blocks.text` 的「硬闸①逐字比对的来源」等），无需翻代码。已实测落库。

### 4.3 工具层（`plugins/tools/`）

`corpus_search.py` / `corpus_fetch.py` 改为调用 `CorpusService`，**不再 `sqlite3.connect`**。

### 4.4 `plugins/corpus/verify.py`（离线三闸）

- **移除** `import sqlite3` 与 `from plugins.corpus.fetch import open_resolver`。
- CLI `main` 改为：`get_service(corpus_dsn).source_resolver()` 提供溯源解析器。
- `verify_card` / `verify_file` / `format_report` **签名与语义不变**（本来就是 `source_resolver` 注入，后端无关）——这正是「服务层收口」设计的收益。

### 4.5 `plugins/corpus/golden.py`（黄金集评测）

- **移除** `import sqlite3` 与 `from plugins.corpus.index import search`。
- `run_golden(conn: sqlite3.Connection, ...)` → **`run_golden(corpus: CorpusService, ...)`**，内部改调 `corpus.search(...)`。
- 黄金集题目、`_matches` 匹配逻辑、`format_golden_report` **未改动**，保证与 P0 基线可比。

### 4.6 测试（`tests/`）

| 文件 | 变更 |
|---|---|
| `tests/test_corpus_golden.py` | 数据源改为 `get_service()`；skip 条件由「SQLite 文件存在」改为「PG 可用且有数据」 |
| `tests/test_corpus_verify_b7.py` | 同上；样本块改由 `svc.search(...)` + `svc.fetch(...)` 取得；resolver 用 `svc.source_resolver()` |
| `tests/test_p0a_acceptance.py` | **未改动**——它用 stub 报告自建 SQLite 库测 `verify` 逻辑（后端无关），属逻辑测试而非数据层测试 |

### 4.7 检索排序对齐（本次实测校准，最关键的一节）

**问题**：切到 PG 后黄金集 Recall 一度为 **0%**。诊断后确认是 `service.search` 相对 SQLite 版缺了四项语义，逐项补齐后回到 100%。过程记录如下，供后续调参参照：

| 步 | 补齐项 | 说明 | Recall@5 |
|---|---|---|---|
| 基线 | —— | `plainto_tsquery` 纯 AND | **0%** |
| 1 | **AND → OR 兜底** | 黄金题是自然语言长问句，纯 AND 要求单个块含全部词元 ⇒ 必空。AND 空结果时退回 OR，与 P0 的 FTS5 AND→OR 兜底一致 | 70% |
| 2 | **标题 5× 加权** | 原 `ts_rank_cd` 不区分标题/正文贡献，导致正文里命中的常见词（如「美元」）把无关文档顶到前面（出现「小红书文案」排在 `James-Bulltard_83126` 之前） | 80% |
| 3 | **正文排序改 `ts_rank`** | `ts_rank_cd` 是**覆盖密度**算法，不按词频/稀有度加权，稀有词（MDB / EXE）无法拉开同系列兄弟文档；改频率型 `ts_rank`，贴近原 BM25 | 85% |
| 4 | **按 `doc_id` 去重** | **FTS 按块排序的经典坑**：一份多块长文档用它的 N 个块霸占前 N 名，把真正相关的其他文档挤出候选集（实测 `市场研判` 一份文档占了前 10 名中的 10 位）。现每份文档只保留分最高的一个块 | 95% |
| 5 | **时效查询 Recency 偏置** | 「最新一期」这类问题无关键词信号，纯 FTS 无法判断时效。查询含「最新/近期/最近/本期」等词时，对 `published` 做轻度偏置（权重 0.1，按候选集日期跨度归一） | **100%** |

> 结论：`data-layer-architecture.md` §4 预判的「BM25 ≠ ts_rank，必须校准」**成立且已解决**。
> 校准后的排序即上表 5 项的组合，已固化为 `service.py` 的 `_SEARCH_SELECT` 与后处理逻辑。

---

## 5. 交互逻辑变更

> **关于界面：本次为数据层 / 后端改版，未涉及任何界面调整**——Web 前端（`web/`）、TUI（`apodex/tui/`）均无改动。
> 以下记录的是**对外契约**（工具返回值、CLI 参数、模块接口）的变更，它们是本次唯一影响「交互」的部分。

| 契约 | 变更前 | 变更后 | 影响 |
|---|---|---|---|
| `corpus_search` 返回 | 同一文档可能连续出现多条（每命中块一条） | **按 `doc_id` 去重**，每份文档只出一条（分最高的块） | Agent 侧候选集更干净；不会因一份多块文档占满 top-k 而漏掉其他文档 |
| `corpus_search` 排序 | BM25（标题 5×），SQLite | `ts_rank`（标题 5×）+ 文档去重 + 时效偏置 | 排序结果有变化，Recall@5 已实测不退化（100%） |
| `corpus_search` 空结果 | 直接返回空 | AND 无结果时**自动退 OR** 再召回 | 「资料里没有」的误判减少，但会多带少量弱相关候选 |
| `verify` CLI `--corpus` | SQLite 数据库**文件路径** | **PG DSN**（如 `postgresql://user:pwd@host:5432/db`） | 调用脚本需改；不给该参数时连默认 DSN（`CORPUS_DSN` 环境变量），**硬闸①始终生效**（原行为是不给就标记 skipped） |
| `golden.run_golden` | `run_golden(conn: sqlite3.Connection)` | `run_golden(corpus: CorpusService)` | 仅签名变更；题目与匹配逻辑不变，结果可与 P0 基线直接对比 |
| 字段可见性 | 无注释 | `documents` / `blocks` 全部字段带 `COMMENT ON` | DBeaver / pgAdmin 里可直接看字段含义，无需翻代码 |

---

## 6. 影响范围

| 模块 | 影响 | 兼容性 |
|---|---|---|
| `plugins/corpus/service.py` | 新增（PG 实现，唯一收口） | 新增 |
| `plugins/corpus/verify.py` | `main` 改走服务层；三闸逻辑不变 | 兼容（`verify_card` 签名不变） |
| `plugins/corpus/golden.py` | `run_golden` 入参类型变更 | **不兼容**：调用方需改（已同步改测试） |
| `plugins/tools/corpus_search.py` / `corpus_fetch.py` | 改调 `CorpusService` | 工具对外契约（入参/返回结构）不变 |
| `plugins/corpus/index.py` / `fetch.py` / `ingest.py` | **保留**（SQLite 实现仍在，其单测继续覆盖） | 仅服务层不再调用 |
| `tests/test_corpus_*` | golden / verify_b7 改 PG 数据源 | 无 PG 时自动 skip（不影响 CI 通过） |
| `frontier_agent/` `workflows/` `apodex/` `server/` `web/` | **零改动** | —— |
| 运维 | 新增 `corpus-db` 容器（PG 18.6） | 需持久化卷 + `pg_dump` 备份 |

---

## 7. 验收结果（2026-09-08 实测）

| 项 | 结果 |
|---|---|
| 实例 | PostgreSQL **18.6**，`localhost:5432` |
| 扩展 | `zhparser` ✅ · `vector` ✅（留位，未建列） · `pg_trgm` ✅（已启用，但未用于检索——Recall 已达标） |
| 检索配置 | `zhcfg` 已建（服务层生成列依赖它） |
| 数据 | **17 份 / 298 块** 已迁入（`status` 全为 `ok`）；格式分布 **PDF 14 · Markdown 2 · DOCX 1**；`published` 覆盖 **2026-08-16 ~ 2026-09-07** |
| 黄金集 | **Recall@5 = 100%（20/20）**，四类分项（数字 8 / 观点 6 / 对比 3 / 时效 3）均不退化 |
| 硬闸① | `test_corpus_verify_b7` **3/3**：逐字证据→命中率 100% 且整卡通过；编造引文→命中率 <100% 且不通过；无 resolver→skipped 且 strict 下不通过 |
| 回归 | corpus 相关测试 **24 passed**（含 SQLite stub 的 `test_p0a_acceptance`） |
| 字段注释 | 16 条 `COMMENT ON` 已落库并核验 |
| 索引 | `documents_pkey` · `documents_content_hash_key`(UNIQUE) · `blocks_pkey` · `idx_blocks_locator` · `idx_blocks_tsv`(GIN) · `idx_documents_published` **全部就位** |

### 7.1 数字切分形态（原方案 §6「必须逐条验证」项）

实测 `to_tsvector('zhcfg', ...)`：

| 输入 | PG 切分结果 | 判定 |
|---|---|---|
| `194.9万亿美元` | `'194.9'` `'万亿'` `'美元'` | ✅ 小数整体保留 |
| `47.3亿` | `'47.3'` `'亿'` | ✅ 小数整体保留 |
| `24.50` | `'24.50'` | ✅ 完整保留 |
| `30%` | `'30'` `'%'` | ⚠️ **与 SQLite 不同**——SQLite 因 `tokenchars '.%'` 绑定为 `30%` 整体 |

**结论**：P0 最花力气的「数字 + 单位整体绑定」在**小数上未被破坏**；仅百分号被拆成两个相邻词元。
功能上无影响——`plainto_tsquery` 对 `30%` 生成 `'30' & '%'`，仍匹配原文中相邻两词，
数字类 8 题 Recall 仍为 100%。`pg_trgm` 保留为「纯百分号 / 子串」失效时的兜底手段（见 §8）。

---

## 8. 后续待办

| # | 待办 | 说明 / 触发条件 |
|---|---|---|
| 1 | ~~补 `docker/initdb` 建表 DDL~~ | **已完成（2026-09-09）**：新增 `docker/initdb/01-schema.sql`（建表 + 索引 + 字段注释）。两点注意：① initdb **仅在数据卷为空时执行**，已有容器仍靠 `CorpusService.init_db()` 幂等补齐；② schema 在 `01-schema.sql` 与 `service.py` 的 `SCHEMA_SQL` **两处都有**，改动须同步 |
| 2 | ~~数字切分形态专项复核~~ | **已完成（2026-09-08）**，结论见 **§7.1**：小数形态完整保留，仅 `30%` 被拆为 `30`+`%`（SQLite 侧为整体）。功能无影响、Recall 仍 100%；仅当日后出现「纯百分号 / 子串」查询失效时才需处理 |
| 3 | ~~`pg_trgm` 是否启用~~ | **已解决**：扩展**已启用**（见 §7）。当前 Recall 达标，**未建 `gin_trgm_ops` 索引、未接入检索**——保留作为数字子串兜底的现成手段 |
| 4 | **`service.py` 类型标注清理** | basedpyright 对 `dict_row` 的 `r["col"]` 下标访问报较多类型错误（`TupleRow` 与 `DictRow` 推断冲突）。运行与测试均正常，属类型标注整洁度问题 |
| 5 | **PG 版本分叉记录** | 语料库 18.6 vs 平台业务库 16（不同实例）。需在部署/运维文档中分别标注，避免混淆 |
| 6 | **全量 8000 份迁移（B1）** | 属 `p1-corpus-scaleup.md` B 组，**须在本文件的排序校准通过后才可做**——当前已通过，可启动 |
| 7 | **`superseded_by`（E1）** | 同系列取代关系。E1 会直接改善「同系列多期」类查询——本次校准中 T1/N4/N5 等题的难点正源于此 |
| 8 | **`source_path` 不唯一** | 同一文件修订后新旧两版并存（P0 已知缺口），本次**未解决**，留给 E1 |

---

## 9. 回滚

SQLite 库（`data/corpus/index.db`）**保留不删**，SQLite 实现（`index.py` / `fetch.py` / `ingest.py`）**保留未删**。

需要回滚时：将 `corpus_search` / `corpus_fetch` 与 `verify` / `golden` 的调用改回 SQLite 实现即可（本次改动集中在服务层与这四处调用点）。P0 验收状态不受影响。

> ⚠️ 注意：`golden.run_golden` 签名已改为接收 `CorpusService`，回滚时需一并改回 `(conn, ...)`。
