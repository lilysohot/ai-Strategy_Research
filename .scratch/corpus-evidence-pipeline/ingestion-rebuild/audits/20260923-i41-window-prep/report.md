# I4-1 窗口前准备/演练（M7 · I4 首项）

日期：2026-09-23。授权：U 本会话核定（生产 5432 只读盘点 + 预演备份）；窗口安排：仅完成 I4-1 准备，窗口另排（U 选择）。

## 结论

I4-1 的 A 侧准备全部完成：获准分支确认、最新盘点零漂移、M6 最终版本绑定核验、容量/恢复目标与回退步骤就绪、预演备份（明确标非最终）完整性通过。**I4-1 尚未完成**：停写窗口批准与预期操作范围仍待 U；批准前不进入 I4-3。

## 1. 获准分支

`migrate_then_reset_limited`（design-review.json `i0c_1_branch` 冻结裁决，随 i0c-r1 入链）：

- migrate：corpus schema 并行新建（生产 DDL 仅在 I4 窗口执行），消费者已在 I2-7/8 接线；
- I4 阶段对旧 public 派生表执行 reset-limited（仅精确对象清单，逐表 U 签认后才执行）；
- 已否决：整库 reset（共库 apodex，§10.1 禁止）、defer（§9 无静默 legacy fallback）。

## 2. 当前对象与消费者（最新盘点，write-once [i41-inventory-findings.json](i41-inventory-findings.json)）

- PostgreSQL 18.6（容器 pg / 镜像 pg18-zhvector / 具名卷 pgdata）；库：postgres 26MB、apodex 9.7MB；schema：public + zhparser；**corpus schema 不存在**（符合窗口内 DDL 纪律）。
- 扩展：pg_trgm 1.6、plpgsql 1.0、vector 0.8.6、zhparser 2.4（与 I0 基线一致）。
- **重置候选逐表精确行数与 I0A-1/设计复核完全一致，零漂移**：documents 89、blocks 1101、claims 1318、claims_v2 0、claim_block_runs 290、claim_block_runs_v2 0、corpus_evidence_runs 57、ingest_runs 11、ingest_failures 1。
- **写入者**：8 个后端全部为 PG 内部 worker（checkpointer/bgwriter/walwriter/autovacuum 等），零客户端连接、零写查询、零 idle-in-transaction；无复制槽；pg_cron 未安装（无计划写入任务）。
- 留出依赖不在清理范围：docs/chinese_docs 归属未定（C12，窗口内导出+观察后 U 单独裁决）、apodex 库全部、扩展与词典表、.audit 88 工件、I0B 备份。
- 消费者矩阵以 design-review.json `i0c_4` 为准（I2-7/8 已接线；旧写入口停用清单见 I4-5）。

## 3. M6 最终版本绑定

- 冻结链验证通过：链头 **i0c-r5f**（"r5e product acceptance retained; validator supersession verified"），validate_i0c_freeze.py 全链 green；M6 放行 = U（xyl）2026-09-23 具名签认（r5c 入链）+ r5e 产品门整改通过。
- 链相关代码零 git 漂移（仅 .codebuddy/memory 与一份计划外方法论文档，不入链）。

## 4. 来源漂移核对

- dev-manifest 73 源：**68/68 哈希匹配，0 变更、0 缺失**（5 份留出件守卫禁读，仅 stat 元数据入账：size/mtime 记录于 findings）。
- data/corpus 另有 123 项非源文件（.audit 29、.evidence 54、Zone.Identifier 元数据、index.db、originals/）——均为保留依赖或垃圾元数据，无源文档变更。

## 5. 容量与恢复目标

- 磁盘：878G 可用（预演产物合计 ~131MB）；archive 容量门 ≥1GB 基线满足。
- 恢复目标（I4-6 窗口内核定）：候选 = corpus-db 隔离容器（现役，127.0.0.1:543）或按 I0B-2 模式新建 verify 容器；**排除**原库任何写路径。窗口批准时由 U 与 A 确认。

## 6. 预演备份（非最终）

backups/`i4-rehearsal-20260923T1023Z-NOT-FINAL/`（rehearsal-notes.json 显式标 REHEARSAL_ONLY_NOT_FINAL_BACKUP）：

- PG：pg_dump -F c（容器内 18.6）postgres（1.96MB，206 TOC 项 / 11 TABLE DATA）+ apodex（190KB，61/8）+ globals；WAL 括号 0/4FAFA088→0/4FB2BA40；dump+拷出 ~52s。
- 原文（受守卫）：data/corpus 全量 tar.gz（191 文件）；**5 份留出件守卫禁读显式排除**（完整原文归档属 I4-6 窗口守卫授权范围）。
- 完整性：artifact-manifest.sha256（9 项）`sha256sum -c` 全 OK。
- 最终备份（I4-6）须在停写截止点后重做，覆盖 PG+原文+人工/审计/raw 同一清单。

## 7. 失败回退步骤（窗口草案）

1. migrate 阶段失败（DDL/构建/发布异常）：新 corpus schema 对象可整体 DROP（尚未成为活动来源），旧链 public 对象未动，恢复服务=确认旧检索入口可用后结束窗口；不触发任何 reset。
2. reset-limited 阶段失败：回退依据=I4-6 最终备份已验证恢复 + 导出件（claims/claim_block_runs/corpus_evidence_runs/ingest_runs 台账已导出入归档）；按批准中止路径保留旧服务可恢复；不扩大删除。
3. 任一步骤漂移/错误：停止，保留现场，重新核验后再议（§3.7 纪律）。

## 8. 窗口操作范围（草案，待 U 批准）

I4-3 停写（停用 ingest_path/ingest_dir 等旧写入口调用方，确认无新增提交并记录截止点）→ I4-6 最终备份+隔离恢复实测 → I4-2 锁定 i4-cutover-manifest.json（reset 分支另绑 i4-reset-manifest.json）→ I4-7 执行 migrate（生产建 corpus schema 九表+构建 8 源+发布）与 reset-limited（逐表 U 签认）→ I4-4 重建/验证活动集（8/8 published+active）→ I4-5 真 CLI/工具往返核验+恢复服务+旧写入口停用记录。

窗口能力参考：预演 PG dump ~1min、原文归档秒级；构建/发布耗时以 I3-7 电池实测为准（8 源重建分钟级）；完整窗口链（含恢复实测与逐表签认）预计远小于一个工作时段——正式标定在 I4-6 后回填。

## 9. 待 U 决定项

1. 停写窗口时间批准（本轮 U 选择：仅完成 I4-1，窗口另排）。
2. 写入者区分手段确认（设计复核 R1 必需项）：最新盘点显示零客户端写入者；窗口内停写复核 = pg_stat_activity 零客户端 + 旧写入口进程停用清单，U 需确认无窗口外写入者（如外部应用直连 5432）。
3. I4-6 隔离恢复目标核定（corpus-db 复用 vs 新建 verify 容器）。
4. 生产 corpus_app 最小权限角色与归档根路径核定（I0C-2 遗留待核定项）。

## 10. 证据清单

- [guard-selfcheck-i4-inventory.json](guard-selfcheck-i4-inventory.json)：守卫 24/24 合成自检
- [i41_inventory_refresh.py](i41_inventory_refresh.py) / [i41-inventory-findings.json](i41-inventory-findings.json)：只读盘点
- [i41_rehearsal_originals.py](i41_rehearsal_originals.py)：受守卫原文预演归档
- backups/`i4-rehearsal-20260923T1023Z-NOT-FINAL/`：预演备份（NOT-FINAL）
- 冻结链核验：validate_i0c_freeze.py（本会话运行，链头 i0c-r5f）
