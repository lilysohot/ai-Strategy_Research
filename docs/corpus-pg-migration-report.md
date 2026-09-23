# SQLite → PostgreSQL 语料迁移 · 结果报告

> 🗃️ **本文是 2026-09-08 迁移与排序校准的历史验证报告。**
> 17 份/298 块是当时的迁移基线，不是当前库容量或发布覆盖承诺。
> 当前 Agent 检索协议、非向量状态与 Web 接线结论见
> [资料库检索与 Agent 上下文接线](corpus-retrieval.md)。

| 项 | 内容 |
|---|---|
| 报告日期 | 2026-09-08 |
| 迁移范围 | 语料数据层：`data/corpus/index.db`（SQLite 3） → **PostgreSQL 18.6** |
| 迁移规模 | **17 份文档 / 298 块** |
| 总体结论 | ✅ **迁移成功**，全部验收硬指标达成（数据零丢失、检索质量不退化、硬闸与回归全绿） |
| 关联文档 | [plan/pg-migration.md](./plan/pg-migration.md) v2.0（需求与实施记录） · [plan/data-layer-architecture.md](./plan/data-layer-architecture.md) v2.0（选型结论） |
| 回滚状态 | SQLite 库与 SQLite 实现**均未删除**，可回滚 |

---

## 1. 结论摘要

| 验收项 | 指标 | 实测 | 结论 |
|---|---|---|---|
| 数据完整性 | 份数 / 块数与源库一致 | **17 份 / 298 块**（与迁移基线完全一致） | ✅ 零丢失 |
| 数据质量 | 无解析失败 / 无 OCR 待处理 | `status` **全部为 `ok`**（17/17） | ✅ |
| 检索质量 | 黄金题 **Recall@5 = 100%** | **20/20 = 100%**，四类分项均不退化 | ✅ |
| 硬闸①数字可溯源 | 溯源命中率 100% | `test_corpus_verify_b7` **3/3** | ✅ |
| 回归 | corpus 相关测试全绿 | **24 passed** | ✅ |
| 中文检索 | zhparser + `zhcfg` 可用 | 已建并投入检索 | ✅ |
| 数字检索 | 数字形态不被切碎 | 小数完整保留；`30%` 被拆分（**功能无影响**） | ⚠️ 见 §7 |
| schema 可维护性 | 字段带注释 | **16 条 `COMMENT ON`** 已落库 | ✅ |

> **一句话**：迁移达成全部硬指标；过程中最主要的挑战不是"搬数据"，而是
> **排序校准**——切换后 Recall 一度归零，经五步对齐才恢复到 100%（详见 §6）。

---

## 2. 迁移前后对比

| 维度 | 迁移前（SQLite） | 迁移后（PostgreSQL 18.6） |
|---|---|---|
| 形态 | 本地文件库 `data/corpus/index.db` | 网络数据库实例 `localhost:5432` |
| 网络接入 | ❌ 无 host:port（**硬边界**） | ✅ 原生支持，Windows 客户端可直连 |
| 并发写入 | ❌ 单写入者（**硬边界**） | ✅ 多写者并发 |
| 中文全文 | FTS5 + jieba 预分词 + `tokenchars '.%'` | **zhparser**（SCWS）+ `zhcfg` 检索配置 |
| 排序 | `bm25(blocks_fts, 0, 0, 5.0, 1.0)` | `ts_rank` + 标题 5× + 文档去重 + 时效偏置 |
| 向量 | `sqlite-vec`（构想） | **pgvector** 扩展已装，**留位未建列** |
| 驱动 | 标准库 `sqlite3` | **psycopg 3**（`dict_row`）`>=3.3.5` |
| 备份 | `VACUUM INTO` 快照 | **`pg_dump`** |
| 时效字段 | ❌ 无 `published` 列 | ✅ 新增 `published` 并建索引 |
| 取证索引 | ❌ `blocks` 无 `(doc_id, locator)` | ✅ `idx_blocks_locator` |
| 字段注释 | 无 | ✅ 16 条 `COMMENT ON` |

---

## 3. 数据完整性核验

**基线对照**：`plan/pg-migration.md` v1.0 记录迁移前语料为 **17 份 / 298 块**。

| 指标 | 迁移前基线 | 迁移后实测 | 差异 |
|---|---|---|---|
| 文档数 | 17 | **17** | 0 |
| 块数 | 298 | **298** | 0 |
| 状态 | — | `ok` **17** / `needs_ocr` 0 / `empty` 0 | 无失败项 |

**格式分布**：`application/pdf` **14** · `text/markdown` **2** · DOCX **1**（合计 17）

**时效覆盖**：`published` 从 **2026-08-16** 到 **2026-09-07**（由 `doc_id` 日期前缀回填，覆盖全部 17 份）

> 结论：**零丢失、零失败**，与迁移基线逐项吻合。
>
> 📌 **本报告是迁移时点的快照**（17 份 / 298 块）。此后语料持续增长，
> 口径已改为**份数不预设**：目录里放多少文件就 ingest 多少，
> 用 `stats()` 的 `corpus_files` 与 `documents` 对比判断是否全跑完
> （2026-09-09 已增至 **19 份 / 335 块**）。

---

## 4. 环境与扩展核验

| 项 | 实测结果 |
|---|---|
| 数据库版本 | **PostgreSQL 18.6**（Debian `18.6-1.pgdg12+2`，x86_64） |
| 连接串 | `postgresql://postgres:postgres@localhost:5432/postgres`（可由 `CORPUS_DSN` 覆盖） |
| 已启用扩展 | **`zhparser`** · **`vector`**（pgvector，留位） · **`pg_trgm`** · `plpgsql` |
| 中文检索配置 | **`zhcfg`** 已建（`CREATE TEXT SEARCH CONFIGURATION ... PARSER = zhparser`） |
| 缺失扩展 | 无（三个目标扩展全部就位） |

> 注：原迁移方案 v1.0 曾判断「当前容器缺 zhparser/vector，必须重建镜像」。
> 实测确认目标实例**已具备**这三个扩展，因此**未重建容器**。

---

## 5. Schema 落地核验

**表**：`documents`（17 行）· `blocks`（298 行）

**索引（6 个，全部就位）**：

| 索引 | 用途 |
|---|---|
| `documents_pkey` | 主键 |
| `documents_content_hash_key` | 内容哈希 UNIQUE —— **幂等去重键** |
| `blocks_pkey` | 复合主键 `(doc_id, seq)` |
| `idx_blocks_locator` | **取证**（`doc_id` + `locator`）——P0 识别出的缺失索引，本次补上 |
| `idx_blocks_tsv` | GIN，正文全文检索 |
| `idx_documents_published` | 时效排序与 Recency 偏置 |

**字段注释**：`documents` 11 个字段 + `blocks` 5 个字段 = **16 条 `COMMENT ON`** 已落库并核验，
在 DBeaver / pgAdmin 中可直接查看字段含义（如 `doc_id` 的「供模型抄进 `evidence.source_ref`」、
`blocks.text` 的「硬闸①逐字比对的来源」）。

---

## 6. 检索质量核验（本次最关键的一节）

> 📘 **想看懂原理？** 面向非专业读者的完整教学版见
> [guide-recall-calibration.md](./guide-recall-calibration.md)（含「召回」概念、分词/倒排索引、
> 五步修复的**人话版 + 技术版**对照、诊断清单与术语表）。本节只给结论与数据。

### 6.1 问题：切换后 Recall 归零

迁移完成后首次运行黄金集，**Recall@5 = 0%（0/20）**——所有题目均未召回。
诊断确认：PG 的 `plainto_tsquery` 是**纯 AND**，而黄金题是自然语言长问句，
要求单个块同时包含全部词元 ⇒ 必然零命中。

### 6.2 五步校准过程

| 步 | 措施 | 说明 | Recall@5 |
|---|---|---|---|
| 基线 | 纯 AND | `plainto_tsquery('zhcfg', q)` | **0%** |
| 1 | **AND → OR 兜底** | AND 空结果时退回 OR，对齐 P0 的 FTS5 行为 | 70% |
| 2 | **标题显式加权** | `setweight('A')` 默认权重不等价 BM25 的 5×，须显式加权 | 80% |
| 3 | **正文改用 `ts_rank`** | `ts_rank_cd` 是覆盖密度算法，不按词频/稀有度加权，稀有词（MDB / EXE）拉不开兄弟文档 | 85% |
| 4 | **按 `doc_id` 去重** | 按块排序时，一份多块长文档会霸占 top-k 挤掉其他相关文档（实测某文档独占前 10 名中的 10 位） | 95% |
| 5 | **时效查询 Recency 偏置** | 含「最新/近期/最近」的查询对 `published` 加权，解决「最新一期」无关键词信号的问题 | **100%** |

### 6.3 最终结果

**Recall@5 = 100%（20/20）**，四类分项全部不退化：

| 题型 | 题数 | 结果 |
|---|---|---|
| 数字型 | 8 | ✅ |
| 观点型 | 6 | ✅ |
| 对比型 | 3 | ✅ |
| 时效型 | 3 | ✅ |
| **合计** | **20** | **100%** |

> 原方案预判的「**BM25 ≠ ts_rank，必须校准，不可想当然**」**成立且已解决**。
> 校准结论已固化在 `plugins/corpus/service.py` 的 `_SEARCH_SELECT` 与后处理逻辑中。

---

## 7. 数字检索专项核验

原方案 §6 将「数字 + 单位整体绑定」列为**最大风险**（P0 依赖 jieba 预分词 + FTS5
`tokenchars '.%'` 保持 `47.3亿` / `30%` / `24.50` 完整形态）。本次实测
`to_tsvector('zhcfg', ...)` 结果如下：

| 输入 | PG 切分结果 | 判定 |
|---|---|---|
| `194.9万亿美元` | `'194.9'` `'万亿'` `'美元'` | ✅ **小数整体保留** |
| `47.3亿` | `'47.3'` `'亿'` | ✅ **小数整体保留** |
| `24.50` | `'24.50'` | ✅ **完整保留** |
| `30%` | `'30'` `'%'` | ⚠️ **被拆为两个词元**（SQLite 侧为 `30%` 整体） |

**结论**：

- P0 最花力气的**小数形态未被破坏**，`194.9` / `47.3` / `24.50` 均完整保留。
- 仅**百分号**被拆成 `'30'` + `'%'` 两个相邻词元，与 SQLite 行为不同。
- **功能上无影响**：`plainto_tsquery` 对 `30%` 生成 `'30' & '%'`，仍会匹配原文中相邻两词，
  数字类 8 题 Recall 仍为 **100%**。
- `pg_trgm` 已启用，保留为日后「纯百分号 / 子串」查询失效时的兜底手段（当前未接入检索）。

---

## 8. 硬闸与回归核验

| 项 | 结果 |
|---|---|
| `test_corpus_verify_b7` | **3/3 通过** —— ① 逐字引文 → 命中率 100% 且整卡通过；② 编造引文 → 命中率 <100% 且整卡不通过；③ 无 resolver → 标记 skipped 且 strict 下不通过 |
| corpus 相关测试 | **24 passed**（含 SQLite stub 的 `test_p0a_acceptance`，未受影响） |
| 服务层收口 | `corpus_search` / `corpus_fetch` / `verify` / `golden` **四个调用方全部改走 `CorpusService`**，无直连 |

> 硬闸①（数字可溯源）在 PG 后端下**依然被逐字比对兜死**——这是 P0 的核心成果，
> 迁移未削弱它。

---

## 9. 遗留问题与后续建议

| # | 事项 | 严重度 | 建议 |
|---|---|---|---|
| 1 | `docker/initdb` **只有扩展初始化，没有 `documents` / `blocks` 建表 DDL** | 中 | 容器重建后必须先跑一次 `CorpusService.init_db()`，否则工具报「表不存在」。建议把 schema 固化进 `initdb/01-schema.sql` |
| 2 | `pg_trgm` 已启用但**未接入检索** | 低 | 当前 Recall 达标，无需处理；作为数字子串兜底保留 |
| 3 | `service.py` 类型标注 | 低 | basedpyright 对 `dict_row` 的 `r["col"]` 下标访问报较多类型错误（`TupleRow` / `DictRow` 推断冲突）。运行与测试正常，属整洁度问题 |
| 4 | `source_path` **不唯一** | 中 | 同一文件修订后新旧两版并存（P0 已知缺口），本次未解决，随 `superseded_by`（E1）一并处理 |
| 5 | 版本分叉 | 低 | 业务库 PG 16 vs 语料库 PG 18.6（不同实例）。部署 / 备份 / 升级文档需分别标注 |
| 6 | 全量 8000 份迁移 | — | **校准已通过，可启动**（`p1-corpus-scaleup.md` B1） |

---

## 10. 附录：核验方法（可复现）

```bash
# 1) 数据完整性：份数 / 块数 / 状态 / 格式 / 时效范围
uv run python -c "from plugins.corpus.service import CorpusService; print(CorpusService().stats())"

# 2) 检索质量：黄金集 Recall@5（20 题，四类分项）
uv run pytest tests/test_corpus_golden.py -q

# 3) 硬闸①：溯源命中率与编造检测
uv run pytest tests/test_corpus_verify_b7.py -q

# 4) 全量回归
uv run pytest tests/test_corpus_search.py tests/test_corpus_ingest.py \
               tests/test_corpus_golden.py tests/test_corpus_verify_b7.py \
               tests/test_p0a_acceptance.py -q

# 5) 环境与扩展（psql）
psql -h localhost -U postgres -c "SELECT version();"
psql -h localhost -U postgres -c "SELECT extname FROM pg_extension ORDER BY 1;"
psql -h localhost -U postgres -c "SELECT cfgname FROM pg_ts_config WHERE cfgname='zhcfg';"
```

**字段注释核验 SQL**：

```sql
SELECT c.relname, a.attname, d.description
FROM pg_description d
JOIN pg_class c     ON c.oid = d.objoid
JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum = d.objsubid
WHERE c.relname IN ('documents','blocks') AND d.objsubid > 0
ORDER BY c.relname, a.attnum;   -- 期望 16 行
```

**数字切分核验 SQL**：

```sql
SELECT to_tsvector('zhcfg', '194.9万亿美元');  -- '194.9':1 '万亿':2 '美元':3
SELECT to_tsvector('zhcfg', '47.3亿');         -- '47.3':1 '亿':2
SELECT to_tsvector('zhcfg', '24.50');          -- '24.50':1
SELECT to_tsvector('zhcfg', '30%');            -- '30':1 '%':2
```

---

## 11. 回滚说明

- SQLite 库 `data/corpus/index.db` **保留未删**；
- SQLite 实现 `plugins/corpus/{index,fetch,ingest}.py` **保留未删**（其单测继续覆盖）；
- 需回滚时，将 `corpus_search` / `corpus_fetch` 与 `verify` / `golden` 改回 SQLite 实现即可；
- ⚠️ 注意 `golden.run_golden` 签名已改为接收 `CorpusService`，回滚时需一并改回 `(conn, ...)`。
