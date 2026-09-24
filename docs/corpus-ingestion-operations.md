# 语料增量与维护操作说明

本文记录现有新链的实际入口和恢复边界，服务于 I5-2。命令只面向已明确的隔离目标或已获批准的维护窗口；不会自行选择生产库。

## 日常增量

清单是显式 JSON，至少包含 `sources`，每项给出 `path`；可在清单中给出 `archive_root` 和 `policy`。先计划和预检，再构建、检查、发布：

```bash
uv run python -m plugins.corpus.cli plan --manifest <manifest.json> --dsn "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.cli build --manifest <manifest.json> --archive-root <archive-root> --dsn "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.cli check --build <build_id> --dsn "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.cli publish --build <build_id> --operator <operator> --dsn "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.cli status --build <build_id> --dsn "$CORPUS_I2_DSN"
```

`plan` 只做预检；`build` 不发布；只有 `check` 通过后才能 `publish`。CLI 不会隐式连接数据库：应显式提供 `--dsn` 或受控的 `CORPUS_I2_DSN`，并由目标守卫拒绝不在批准范围内的目标。命令没有 `--force` 旁路。

同一来源、相同内容和规则可重跑。解析检查点的读取器版本包含运行时依赖版本，因此旧的裸版本检查点会被安全地失效并重建一次；随后重跑复用检查点，保持相同 `parse_rev` 和 `build_id`。源内容、规则或索引版本改变时，预期会生成新的版本，不能把旧活动版本当作已更新。

## 失败恢复与交接

先查询失败版本，再由恢复计划定位阶段，而不是重新扫描或直接发布：

```bash
uv run python -m plugins.corpus.cli status --build <build_id> --dsn "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.cli rebuild-plan --build <build_id> --dsn "$CORPUS_I2_DSN"
```

交接记录须附上 build ID、source ID、当前 generation、`status` 输出的 `gaps`/`gap_summary`/`recovery`、执行命令和退出码、清单及策略哈希、归档路径、操作者和活动版本。存在 blocking gap、目标守卫拒绝、来源或规则漂移时，停止在该状态；不要用旧表、旧句柄或默认检索绕过。

## 备份与恢复演练

以下是现有 `plugins.corpus.service` CLI 的真实命令。恢复会写入其 `--db` 目标；只能用于已经核验的隔离恢复库，不能把本文当作生产恢复授权。

```bash
uv run python -m plugins.corpus.service backup --out <backup-dir> --mode pg_dump --db "$CORPUS_I2_DSN"
uv run python -m plugins.corpus.service restore --src <backup-dir> --db "$ISOLATED_RESTORE_DSN"
```

`pg_dump` 模式没有客户端工具时会明确失败；`auto` 才允许 CSV 回退。恢复后比较备份 `manifest.json` 中的行数和列清单，并运行新链 `status`、`search`/`fetch` 的隔离验证。备份目录、恢复日志和核验结果应一并交接。

## 保留与 GC

当前没有语料 GC 命令。不得编造或执行“清理旧版本”的自动命令。原始归档、已发布或活动 build、准入/审核决定、检查点、备份和评测工件均是保留对象，不能由本说明删除。

若容量需要处理，只能由维护负责人提出精确对象清单、保留依据、恢复点和批准记录；先在隔离目标演练并留存结果。`_staging` 等执行暂存物也必须先确认未被任何未决 job、恢复计划或审计工件引用。没有这份清单和批准，GC 状态为不执行。

## 旧入口边界

正常写入入口是 preparation CLI 的 `plan`/`build`/`check`/`publish`。旧 `run_ingest` 和旧 evidence 写入已 fail-closed 退休。公开 `search`、`fetch`、`stats` 与文档列表使用活动的新链版本；未知或旧句柄不会回退到旧正文。

历史 claims/财务验证和 R2 仍有显式兼容读取能力，详见[退休矩阵](corpus-ingestion-retirement-matrix.md)。这不是公开读侧的 fallback，也不是运行常规增量的入口。
