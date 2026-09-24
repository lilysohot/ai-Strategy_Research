# M8 I5 执行记录（2026-09-24）

本轮完成先前 M8 复核中仍未闭合的 F1、F3、I5-2 与 I5-3。历史审计产物未改写；本目录只追加本轮实现和验证记录。

## I5-1：重跑与新链消费者

- 修复检查点重放时 `extractor_rev` 丢失运行时依赖版本的问题。`extractor_rev_for()` 现在与实际 PDF/DOCX 读取器生成同一动态 revision；旧裸 revision 检查点会失效并安全重建一次，之后同一输入重放保持相同 `parse_rev`、`build_id` 并复用检查点。
- 新增动态 revision 的检查点重放回归，覆盖 build ID、parse revision、检查点字段和只读一次的缓存约束。
- 公开 `stats`、文档列表和状态列表改为读取活动 publication/build；新 PG 用例确认发布后计数、MIME 聚合、`cv2:` 句柄与文档元数据均来自新链。
- 隔离 PG 消费者门：21 passed、零 skip；全表哈希恢复一致。见 `consumers-pg-results.json` 与 `lane-i5-consumers-pg.txt`。

早先四场景证据保留在 `../20260924-i51-scenarios/`。其中场景一对动态读取器的 7/8 build churn 已由本轮 F1 修复和新增回归覆盖；历史报告仍保留原始发现，不被本报告改写。

## I5-2：运维说明

新增 `docs/corpus-ingestion-operations.md`，写明实际存在的 preparation CLI 和 service 备份/恢复 CLI、增量顺序、失败恢复、交接字段及恢复验证。说明明确当前没有 GC 命令，禁止清理原文、活动/已发布版本和审计工件，也没有把恢复操作表述为生产写入授权。

## I5-3：退休核验

- 删除 CSV 备份枚举中已退休、不会由 `init_db()` 创建的 `corpus_evidence_runs`，消除新库备份覆盖漂移。
- 两个评测脚本不再请求退休 evidence 写入或旧表回读：完整 `EvidenceRun` 写入内容寻址 JSON 工件，随后重新解析、校验 identity、事实数量和 packet 坐标。
- 退休矩阵新增于 `docs/corpus-ingestion-retirement-matrix.md`。它保留历史 claims/财务/R2 的显式兼容读取能力，并把它与产品公开新链分开；没有删除共享能力，也没有恢复隐式 fallback。
- 临时 legacy 形态库中的 audit/evidence 门：24 passed、零 skip，数据库已删除。见 `legacy-audit-results.json` 与 `lane-i5-legacy-audit.txt`。

## 验证汇总

| 检查 | 结果 |
| --- | --- |
| 定向语料回归（release gate、evidence、audit、claims、metadata） | 109 passed, 1 skipped |
| 退休入口与评测脚本回归 | 27 passed |
| 隔离 PG 新链消费者 | 21 passed, 0 skipped；恢复哈希相等 |
| 隔离 legacy 审计/evidence | 24 passed, 0 skipped；临时库已删除 |
| Ruff（全 CI 范围） | passed |
| Pyright | 0 errors, 0 warnings |
| import smoke | stage 1: 366/366；stage 2: 415/415 |
| symbol closure | 465 files, 0 missing imports |
| 全量 pytest（收口复跑） | 2937 passed, 48 skipped, 1 failed |

市场金标已按固定样例的一个月窗口修复并通过。全量 pytest 仅剩 ReAct profile 没有绑定 `position_sizing`/`strategy_lint`，已由用户明确划为另一条任务线，不作为 I5 通过证据。

## M8 收口判定

四场景已在各自既有隔离库中以 post-F1 代码重放：场景一检查点重放 8/8 build ID 稳定；场景二验证源变化和旧版本保留；场景三验证新解析规则；场景四验证复用解析后的索引重建。每次运行均在恢复原库全表内容后结束，生产前后快照均在显式只读事务中一致。

最终绑定见 `i5-final-binding.json`：四场景、隔离恢复、生产只读和源代码/守卫/文档哈希均通过。因此，重建任务的 M8 范围已完成；ReAct 财务工具绑定不属于此收口范围。
