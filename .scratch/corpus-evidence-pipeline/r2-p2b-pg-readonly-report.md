# P2-B PostgreSQL 只读影响核查

日期：2026-09-14。用户授权：对本轮测试所连接 PostgreSQL 做只读影响核查，不修改或清理数据。
关联：[原执行偏差报告](r2-p2b-guard-incident.md)、[P2-B 阶段报告](r2-p2b-report.md)。

## 结论

**只读核查已完成：未发现现存测试 schema 残留、明确的旧备份文档缺失或事发时间窗新增主库记录；
但缺少事发前全库快照和完整语句审计，不能证明历史零影响。**

这不是临时空库：按与原测试相同 WSL 环境的 `service.dsn()`，当前解析到本机持久化语料库。
不把这次事后只读检查当作获准的 P0-PG 隔离验收，也不追溯恢复首次 PG 测试的有效性。
P2 保持 partial：技术交付已通过，影响核查已完成但残余不确定性未消除；P3 未自动启动。
真实模型预算仍 0，后续 PG 测试仍封锁。

## 核查范围与身份

| 项 | 观测 |
|---|---|
| 配置入口 | 当前 `service.dsn()` → localhost:5432 / postgres；不显示密码或完整连接串 |
| 实际连接 | database=postgres，role=postgres，server=172.17.0.2:5432 |
| PostgreSQL | 18.6；cluster system_identifier=7683087224215924779 |
| Docker | pg / pg18-zhvector；容器8716f5d7bd4a；持久卷pgdata |
| 实例启动 | 2026-09-14 00:45:58 UTC，早于事件 |
| 事件核查窗 | 2026-09-14 05:37—05:40 UTC，即北京时间13:37—13:40；包含两份首次结果文件的05:38时间 |
| 核查快照 | 05:50起的三个独立只读事务；最终结果以 `p2b-pg-readonly-evidence.json` 的observed_at为准 |

原测试没有保存连接身份，因此不能把“当前相同配置入口、地址/容器/启动时间一致”说成事发连接
指纹已被完全固定。现有证据强支持核查对象是同一库；没有另连平台业务数据库或其他实例。

按 diagnosing-bugs 技能，先固定已知故障及证据边界，再用可证伪的只读检查区分残留、当前完整性
与历史未知。跳过真实写入复现和数据库修复阶段，避免重演已知越界；入口修复已有前轮测试证据。

脚本仅 SELECT/SHOW、事务控制及 SAVEPOINT，连接启动即设置 default_transaction_read_only=on，
再显式 BEGIN REPEATABLE READ READ ONLY，并断言 transaction_read_only=on；每次最终 ROLLBACK。
statement_timeout=5秒、lock_timeout=1秒。无DDL/DML、备份恢复、schema清理、PG测试或模型调用。
只读连接本身仍会产生正常连接/统计/日志及读取开销，不声称数据库物理文件绝对未变。

## 实际检查

| 检查项 | 结果 | 能证明与不能证明 |
|---|---|---|
| 用户schema | 仅public、zhparser | 当前没有固定/随机测试schema残留；不能证明固定schema事前为空 |
| 主库文档/块 | documents=89，blocks=1101 | 当前可读的精确行数；不是事发前后内容快照 |
| claims | claims=1318，claim_block_runs=290；v2两表均0 | claims数量与较早项目报告相同，不能排除同数量更新 |
| EvidenceRun/入库台账 | corpus_evidence_runs=57，ingest_runs=11，ingest_failures=1 | 没有读取payload、错误正文或研报原文 |
| 引用完整性 | 孤立blocks=0，孤立claims=0 | 校验doc_id引用，不是所有字段/关系的完整性证明 |
| public索引 | invalid/not-ready=0 | 目录状态正常；没有执行修复或全量物理一致性扫描 |
| 事件窗新增记录 | documents=0，EvidenceRun=0，ingest_runs=0 | 依赖现存行时间戳，不能检测已删除记录或未留更新时间的更新 |
| 最近文档入库 | 2026-09-14 01:34:33 UTC | 早于事件窗 |
| 最近EvidenceRun创建 | 2026-09-13 03:13:00 UTC | 早于事件窗 |
| 扩展 | public下zhparser2.4、vector0.8.6、pg_trgm1.6 | 当前配置存在；无创建时间/事前快照，不能认证事件中从未变化 |
| zhcfg | public.zhcfg使用zhparser，24个词性映射到simple | 与代码预期映射一致，未改配置或调用同步函数 |

pg_stat_user_tables 的计数与实际 count(*) 不相等；前者是累计/估计统计，不用它作精确行数或
事件级写入归因。没有重置统计、VACUUM、ANALYZE、REINDEX 或运行 schema 初始化。

## 备份核对

找到项目内 `data/corpus_full_backup_v2/manifest.json`，创建于2026-09-11 05:02:33 UTC，列明
78份documents、928个blocks，claims与claim_block_runs为0。它早于事件，但也早于后续合法入库。

仅从 `documents.csv` 投影 doc_id/content_hash 元数据，与当前库同两字段比较：

- 78/78旧文档ID仍存在；存储的content_hash差异0；当前多11个ID。
- 未输出标题、路径、文档ID、正文或块文本；备份原文件未改。
- 这是**存储元数据相同**，不是重新从当前blocks计算全文哈希。既不证明928个旧块逐字相同，
  也不覆盖后来增加的claims、EvidenceRun或测试schema的事前内容。
- 没有恢复备份、制作新逻辑导出或读取留出源文件。本轮没有将数据内容用于R2规则调整。

documents.csv SHA：`b7c48a2dbcc5e8b390e28966f0a6c92840bd00ce9bd6c42f375ad95bd970cf98`。
项目中已找到的备份不等于所有主机/外部备份清单；未扫描其他数据库或用户无关存储。

## 日志与可追溯性限制

当前log_statement=none、log_min_duration_statement=-1、logging_collector=off；日志输出stderr，
Docker使用json-file。pg_current_logfile为空、服务器log目录查询不可用，与collector关闭相符。
archive_mode=off，archived_count=0；track_commit_timestamp=off，无pg_stat_statements扩展。
未启用新的日志、归档或审计配置。

只读查看05:37—05:40 UTC容器日志，收集411行；其中45条LOG为zhparser自定义字典未载入提示，
伴随45条STATEMENT标记。未执行日志建议的字典同步。摘要保存于 [日志元数据](p2b-pg-log-summary.json)，
不复制原始SQL或可能含材料正文的日志。

这些日志并非全量审计，不能还原每次CREATE/DROP及写入所属schema；无schema名称不证明未发生
schema写入。原测试确实执行及删除测试schema的结论仍基于首轮测试结果与已冻结测试源码。
不能利用正常结束或当前无残留，倒推“删除前没有其他内容”。也无法从这些日志追溯B6/B7当时
读取的文档身份；前轮留出暴露未确认状态保留，不能用于新的留出通过结论。

## 证据与复验

本次独立冻结清单为 [r2-p2b-pg-readonly-manifest.json](r2-p2b-pg-readonly-manifest.json)，
其外部SHA记录于issue20最新追加项；旧P2-B清单不覆盖、不解冻。

- [只读核查脚本](p2b_pg_readonly_audit.py)，仅新增scratch诊断文件，无公共模块改动。
- [最终目录/数量/备份比较结果](p2b-pg-readonly-evidence.json)。
- 早期 `p2b-pg-readonly-catalog.json` 的schemas查询因空参数元组与SQL百分号解析冲突未成功；
  修正诊断脚本后，`p2b-pg-readonly-catalog-final.json` 与最终evidence结果均查询成功。早期缺项
  保留为过程证据，不把null错误当schema为空。
- 诊断脚本Ruff通过。P0保护校验及P2-B原清单17个绑定文件复核通过，未修改原偏差报告或冻结证据。
- 本次三个事务均已回滚并关闭，无数据库内容写入、清理、权限修改、模型调用或隐式开发试验。

复验命令（只在同一授权范围内使用新输出路径）：

```bash
uv run python .scratch/corpus-evidence-pipeline/p2b_pg_readonly_audit.py \
  --out /absolute/new/path/pg-audit.json
```

## 后续建议，不自动执行

此次可得结论是“当前未见明确残留/缺失”，不是“历史零影响已证明”。本次授权的只读核查已完成，
不无限重复同一查询。若需进一步证明历史零影响，需要事发前快照或数据库管理员持有的完整审计；
当前开启日志不能补回过去。

建议保留本次事故记录与剩余不确定性，在用户接受该证据边界后继续**封锁PG的纯离线P3**；真实PG
测试需另外确认独立实例/库及不触及业务库的只读/写入边界，不复用本库直接跑夹具。
R2业务语义、P0-PG正式隔离门、模型预算和CLI业务闭环仍分别验收，不因本次核查自动放行。
