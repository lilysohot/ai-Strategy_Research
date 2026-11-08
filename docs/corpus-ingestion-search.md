# 资料库入库时间检索

`corpus_search` 和 `GET /api/corpus/search` 支持独立的入库日期条件：

- `ingested_from` / `ingested_to`：YYYY-MM-DD，可只传一端，两端包含当天。
- `ingested_timezone`：IANA 时区，默认 `Asia/Shanghai`。按该时区的自然日转换为时间戳区间 `[首日零时, 末日次日零时)`，兼容夏令时。
- `published_from` / `published_to`：仍只代表研报发布日期。两组条件同时提供时取交集。
- 可以只给日期条件并将 `query` 留空，也可以与关键词组合。

例如查询北京时间 2026-11-07 新收录的资料：

```python
corpus_search(ingested_from="2026-11-07", ingested_to="2026-11-07")
```

```text
GET /api/corpus/search?ingested_from=2026-11-07&ingested_to=2026-11-07
```

查询 11 月新收录、研报发布于 9 月的农业资料：

```python
corpus_search(query="农业", ingested_from="2026-11-01", ingested_to="2026-11-30",
              published_from="2026-09-01", published_to="2026-09-30")
```

## 时间口径

`corpus.corpus_sources.ingested_at` 为该来源首次成功发布到新链可检索范围的时间，不是上传开始时间、文件修改时间或研报发布日期。由数据库在成功发布的同一事务记录；失败回滚不产生入库时间。同一来源别名、重新解析、重建索引、撤销后再次启用均不刷新已记录时间。

原生检索及非原生词法/向量通道都在截断候选、排序前应用条件。仅按入库日期检索时不要求存在研报发布日期；显式入库筛选排除入库时间未知的来源。过滤命中携带独立的 UTC `ingested_at` 时间戳；`coverage.ingestion_filter` 提供时区、实际边界和未知时间处理政策。原生路径同时报告允许来源范围内的未知数、日期匹配数、组合条件匹配数；这些数不等于本次实际返回条数。

没有入库日期条件时不会新增未知时间排除规则，也不强制读取入库时间；此时结果中的 `ingested_at=null` 不应被解释为对该来源入库时间的全量审计。原生检索沿用已有来源 allowlist、撤销和原文完整性检查；结果数量仍受条数和正文预算限制。旧 legacy 检索链拒绝日期筛选，不静默忽略条件。

## 数据库升级与历史记录

先在目标库完成现有 corpus 基础 schema 初始化，再运行可重放的增量迁移：

```bash
uv run python -m plugins.corpus.preparation.ingestion_schema
```

连接沿用 `.env` / 环境中的 `CORPUS_DSN` 与显式 `CORPUS_TARGET_DB`，执行前核验实际目标库；读路径不自动做 DDL。迁移为来源表增加时间列、索引及 `ingestion_tracking_started` 标记，并为活动版本表安装触发器。该标记区分开始记账后的来源和已丢失首次时间的历史来源，避免旧资料下次重建时被误记为新收录。

历史回填仅使用 `corpus_publications.generation=1` 且有活动版本的 `activated_at`：在现有版本指针协议下，这是尚未发生切换的首次成功发布记录。多次切换后的 `activated_at` 只是最近切换时间，保持未知；不以迁移执行时间、审核时间、文件名或文件 mtime 替代。此口径不能证明来源在旧 legacy 系统中的首次收录时间。

迁移与发布互斥，锁等待上限 10 秒；锁冲突时回滚后重试。先应用迁移再启用新检索代码；常驻 HTTP 服务需重新加载代码，逐运行创建的 Agent worker 在下一次运行使用新工具定义。回滚应用代码可保留新增列和触发器，不影响旧读路径。

## 验证

- `uv run pytest tests/test_corpus_ingestion_range.py tests/test_corpus_publication_range.py -q`
- `tests/test_corpus_ingestion_pg.py` 使用显式 `CORPUS_INGESTION_TEST_DSN`，仅允许空的 `vector_pilot_ingestion_*` 隔离库；测试内所有 DDL/数据均回滚，覆盖历史保守回填、首次成功入库、重建不刷新及真实词法/向量 SQL 在 top-k 前过滤。
