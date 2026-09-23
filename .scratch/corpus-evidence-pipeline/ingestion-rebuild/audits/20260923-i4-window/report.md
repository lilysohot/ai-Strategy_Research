# I4 停写窗口报告（M7：迁移、清理与切换）

- **窗口**：2026-09-23 停写窗口 → 2026-09-24 收尾（本报告）
- **分支**：`migrate_then_reset_limited`（design-review.json i0c_1_branch，U 签认）
- **批准链**：U 2026-09-23 停写窗口批准连续执行（I4-3→I4-6→I4-2→I4-7→I4-4→I4-5）；U 2026-09-24 一次具名批准九表两阶段 reset + 追认 r5g 目标适配（[i42-approval.json](i42-approval.json)，sha 0e225214…）
- **停写截止点**：LSN `0/4FB2BD00` @ 2026-09-23T15:42:19Z（[i43-stopwrite-findings.json](i43-stopwrite-findings.json)，门禁 8/8）
- **最终备份**：`backups/i4-final-20260923T1544Z`（artifact-manifest.sha256 `085abf4c…`）；隔离恢复验证 **11/11 计数一致、扩展 4/4、验证库已销毁**（[i46-restore-verification.json](i46-restore-verification.json)）
- **结论**：I4-3/I4-6/I4-2/I4-7/I4-4/I4-5 全绿；**reset 阶段 2 经 U 复核裁决暂缓**（见 §5）；本报告不构成 M7 放行，I5 增量任务另行核定。

## 1. I4-3 停写核验

写入者停驻、无活动写事务、截止点记录；持续停写限制保持至窗口结束。证据：[i43-stopwrite-findings.json](i43-stopwrite-findings.json)（sha ab92146b…）、[i43_stopwrite_verify.py](i43_stopwrite_verify.py)。

## 2. I4-6 最终备份与恢复验证

PG dump + 原文归档 + 人工/审计/raw 同一清单；哈希、数量、扩展、历史取证核验通过；恢复在隔离库实际执行后销毁。证据：[i46_final_archive.py](i46_final_archive.py)、[i46-restore-verification.json](i46-restore-verification.json)（sha 8e80cc4c…）。

## 3. I4-2 双 manifest 锁定 + r5g 冻结修订

- [i4-cutover-manifest.json](../../i4-cutover-manifest.json)（migrate 分支变更清单/禁止项/回滚/批准记录，locked 2026-09-24T01:05+08:00）
- [i4-reset-manifest.json](../../i4-reset-manifest.json)（九表两阶段逐表清单，U 一次具名批准后锁定）
- reset 事实采集：[i42-reset-facts.json](i42-reset-facts.json)（sha 850dc937…；行数与 I4-6 恢复验证完全一致 = 截止点后零漂移）
- r5g 目标适配入链：`pg_target.py` 显式 `CORPUS_TARGET_DB` 放行生产（默认 `i2_sandbox_corpus` fail-closed 不变），链头 i0c-r5g（sha `5ef07ef0…`），验证器 exit 0（[i42-r5g-validation.txt](i42-r5g-validation.txt)）。

## 4. I4-7 migrate + reset 阶段 1（含一次受控回滚）

### 4.1 zhcfg 前置探针

postgres 与 i2_sandbox_corpus 两库 zhcfg 逐字段一致（24 token 全→simple、custom_words 0、无 GUC 覆盖，`equivalent: true`）→ migrate 的「zhcfg 条件创建」为无操作。证据：[i47_zhcfg_probe.py](i47_zhcfg_probe.py)。

### 4.2 migrate（corpus schema 九表 DDL）与首跑事件

- 六道门（CORPUS_WINDOW_DSN 目标核验、DDL sha==i0c-r4 冻结值 `c4bc8aff…`、schema 缺席+zhcfg 等价、行数零漂移、单事务 DDL+结构比对、write-once）。
- **首跑事件**：DDL 已提交后验证器索引期望值写错（10 ≠ 19，漏数 9 张表 PRIMARY KEY 支撑索引）。按 cutover manifest rollback[0] 处置：前置复核（9 表全 0 行/19 索引/0 序列）→ 逐字 `DROP SCHEMA corpus CASCADE;` → 零残留核验 → 事件落章 [i47-migrate-incident.json](i47-migrate-incident.json)（sha b5625e10…，[i47_rollback.py](i47_rollback.py)）→ 期望值修正（附注释）后重跑。
- **重跑绿色**：[i47-migrate-report.json](i47-migrate-report.json)（sha 188c75fa…）——9 表/0 序列/19 索引（9 pkey + 10 显式，名称全列），columns/constraints/indexes 与沙箱逐一一致，zhcfg_baseline 等价且 zhcfg_created=false，WAL `0/503E6860→0/50464000`。

### 4.3 reset 阶段 1（七表）

[i47_reset_phase1.py](i47_reset_phase1.py)（守卫 lane）按 manifest 逐字六语句单事务执行：

- 前置行数精确匹配 rows_before：claims_v2 0 / claim_block_runs_v2 0 / claim_block_runs 290 / claims 1318 / corpus_evidence_runs 57 / ingest_failures 1 / ingest_runs 11；
- 执行后全 0；3 个 owned 序列归零（last_value=1, is_called=false）；保留序列（docs/chinese_docs）与见证表（blocks 1101 / documents 89 / docs 3 / chinese_docs 3）不变；
- 台账导出前提核验（artifact-manifest.sha256 `085abf4c…` 逐条哈希一致）；
- 报告：[i47-reset-phase1-report.json](i47-reset-phase1-report.json)（sha cf0e9bcc…），WAL `0/504717C8→0/50471D18`。

守卫自检：[i47-guard-selfcheck.json](i47-guard-selfcheck.json)（24/24 合成反例，config sha `e599d9b4…`）。

## 5. I4-4 生产重建（8/8）

[i44_rebuild.py](i44_rebuild.py)（守卫内先装 + `CORPUS_TARGET_DB=postgres` import 前置）：

- 播种 8 份 ReviewedDecision（U 2026-09-15 批准集逐字保留：approved 6 + dev lane 2 supersede），rationale 明示 I4-4 生产重建重播种，REVIEWER=U（I4 停写窗口具名批准连续执行）；
- cli build/check/publish：**8/8 built/published/active，blocked 0**；build 9.44s exit 0；
- **确定性**：build_id 与 I3-7 沙箱基线逐一相同，单元/切块计数一致（chunks 834 / units 3887 / index_rev=index-4-zhcfg-2）；
- 归档根：`i44-archive/`（守卫 locked 禁写 data/；生产归档根归属属 C12 类裁决随 I4-close 登记）；
- 报告：[i44-rebuild-report.json](i44-rebuild-report.json)（sha b6879345…）。

## 6. I4-5 真 CLI/注册工具往返 + 旧写入口停用

[i45_tool_roundtrip.py](i45_tool_roundtrip.py) → [i45-tool-roundtrip.json](i45-tool-roundtrip.json)（sha 5c85279a…）：

- **正向**：corpus_search「半导体划片机」matched 4 命中（cv2: 句柄 + chunk: locator + context_locators）；corpus_fetch 逐字原文 18 单元 / text 1189 字，spans 按 `"\n".join(切片)` 复算 text（单元按 ordinal 以 "\n" 拼接、span 不含分隔符）；snippet 为 ts_headline 对清洗视图 search_text 的高亮定位投影（`<b>` 标记），与权威 raw_text 不同源，不做子串断言（I4-1 receipts 同口径；source_ranges 合法为空，contract 默认 `()`）；
- **失败三例**：伪造 cv2 句柄拒（句柄不存在或跨 build）、旧句柄 `archive_required` 结构化拒绝、GARBAGE_QUERY（见 §8 观察）；
- **恢复**：失败注入后同实例复取同文（same_text=true）；
- **零模型**：openai/anthropic/material_semantics/_r2_runtime 往返前后不在 sys.modules；
- **无双写**：往返前后旧链七表恒 0 + blocks/documents 1101/89 不变；
- **旧写入口停用记录**：claims/claim_block_runs（service.py:2169/2177）、ingest_runs/ingest_failures（:2758/2806）、corpus_evidence_runs（:1596，检索/取证纯读不触）、documents/blocks 直写（I2-7 退役）——共四条；
- **switched**：corpus schema（I4-7 migrate 九表）/ 活动集 8/8（I4-4，build_id 与 I3-7 基线相同）/ 消费路径 search_pg+read_pg / 写路径唯一化 preparation engine；**retained**：docs/chinese_docs（C12）、blocks/documents（阶段 2 随 I4-close → 见 §7 暂缓）、apodex 库、扩展与 zhcfg、I0B/I4 备份。

## 7. reset 阶段 2 —— U 复核裁决：暂缓

- manifest phases[1] 前置「I4-4 验证通过 + U 复核」：前者满足，U 于 2026-09-24 AskUserQuestion 裁决**「暂缓，先出窗口报告」**；
- 现状保留：blocks 1101 / documents 89（四张引用表仍为阶段 1 后的 0）；
- **前置对照件已导出待用**（[i4c_exports.py](i4c_exports.py)，守卫 lane，READ ONLY）：
  - [i4c-old-evidence-locator-crosswalk.jsonl](i4c-exports/i4c-old-evidence-locator-crosswalk.jsonl)：台账引用对 307（claims/claim_block_runs/corpus_evidence_runs payload），290 精确联块（含块全文）、17 非数字 locator 如实保留、0 丢失（sha `a97fda27…`）；
  - [i4c-docid-source-map.json](i4c-exports/i4c-docid-source-map.json)：89 行源身份；content_hash16 为新链 corpus_sources.source_id 的 16-hex 前缀，8 行唯一精确 join（sha `142273cb…`；[清单](i4c-exports/i4c-exports-manifest.json)）；
- 执行时回退只靠已验证备份（postgres.dump 恢复验证 11/11），不靠旧指针；语句仍以锁定 manifest 为准，届时另走执行门。

## 8. 偏差与观察登记

1. **无守卫子进程 lane（I4-5）**：守卫对 `CORPUS_DSN` 的 fail-closed 投毒使 `dsn()` 依赖路径（注册工具经 `get_service()`）在守卫 lane 下结构性不可用——这是冻结的正确设计。处置沿 I3-7 先例（audits/20260923-i37-final-reverify/README.md）：无守卫 lane + 偏差登记 + 补偿控制四条（零 data/ 读取、结构性零模型断言、无双写实测、固定脚本 write-once）。随 r5h 冻结修订一并登记。
2. **migrate 首跑索引期望值事件**：验证器缺陷而非 DDL 缺陷；受控回滚逐字记录（§4.2），修正后重跑绿色。fail-closed 按设计生效（失败发生在验证层、库已回滚重建）。
3. **GARBAGE_QUERY 观察（非验收项）**：`qzzx不存在词组wjqtt` 经 zhparser 存活词素仍 matched 5 条——no_match 路径未被该串触发，i45 报告如实记录。检索质量议题不在 I4 切换完整性范围内，留 I5 观察项。
4. **snippet/source_ranges 断言校准**：I4-5 脚本首版对 fetch 载荷断言过严（source_ranges 恒非空 + snippet⊂text）；按 I4-1 receipts 与 contract 默认值口径修正（键存在 + spans 复算 text + 高亮结构），见 §6。
5. **I4-5 往返脚本调试期间未产生 DB 写入**：三次中止均发生在只读阶段（fetch 载荷断言/失败用例断言），无双写破坏，最终报告 write-once。

## 9. 工件索引（sha256 前 8 位）

| 步骤 | 工件 | sha256 |
| --- | --- | --- |
| 守卫 | guard-selfcheck-i4-window.json / i47-guard-selfcheck.json | 6b5df288… / 83481f27… |
| I4-2 | i42-approval.json / i42-reset-facts.json | 0e225214… / 850dc937… |
| r5g | i42-r5g-validation.txt / previous-effective-bindings-r5g.json | 61fb3055… / 4bb3f732… |
| I4-3 | i43-stopwrite-findings.json | ab92146b… |
| I4-6 | i46-restore-verification.json | 8e80cc4c… |
| I4-7 | i47-zhcfg 探针 / 事件 / migrate 报告 / 阶段 1 报告 | 4a9579c9… / b5625e10… / 188c75fa… / cf0e9bcc… |
| I4-4 | i44-rebuild-report.json | b6879345… |
| I4-5 | i45-tool-roundtrip.json | 5c85279a… |
| I4-close | i4c-exports 三件（crosswalk / 映射 / 清单） | a97fda27… / 142273cb… / 61d378a5… |
| I4-close | r5h 快照 / 验证输出 / prev-bindings | 7fb195cf… / 550c7719… / b50c334a… |

冻结链收尾：新修订 **i0c-r5h**（parent r5g，快照 sha `7fb195cf…`），验证器 exit 0
（[i4c-r5h-validation.txt](i4c-r5h-validation.txt)）；tasks.md 按 r4z/r5g 先例
archive-first 重绑（before-r5h/ 归档=重绑后字节，验证器归档=改前字节
`b44c0ee9…`）。

## 10. 后续（非本窗口）

- reset 阶段 2 另行安排（§7）；
- I5-1 四场景复核、I5-2 维护说明定稿、I5-3 旧入口停用核验（将以本窗口 i45 停用记录为输入）；
- 生产归档根归属（I4-4 用 i44-archive/）随 C12 类裁决定案。
