# M7 放行签认记录（U 具名签认）

| 项 | 内容 |
|---|---|
| 状态 | **已签认（signed）** · 签认入链 i0c-r5n |
| 范围 | M7 放行（I4 迁移/清理/切换窗口执行 × m7-review 六项整改 × m7-rereview F1–F3 修复验证 × U 具名签认） |
| 复核结论 | 通过（[m7-review-20260924](report.md) 六项整改落实；[m7-rereview-20260924](report.md) 遗留 F1–F3 已修复验证闭环） |
| 签认人 | **xyl** |
| 签认时间 | 2026-09-24 |

## 签认决定

1. **M7 放行**：认可 I4 窗口执行结果、两轮独立复核结论与全部修复验证。M7 放行三要件
   ——I4 窗口执行通过、独立复核闭环、U 具名签认——全部达成。
2. **M8 启动（同日裁定，另行记录）**：I5 增量与运维开启，I5-1 验证范围批准为
   **全四场景 × 全部 8 个活动源**（同源同版本重跑、源变化、新规则 build、复用解析
   重建索引；源变化/新规则/复用解析在隔离环境执行，不触碰生产活动来源）。
   此项属 M8 启动记录，不属于本签认范围。

## 签认所依据的证据

- **I4 窗口执行**（[窗口报告](../corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/report.md)）：
  I4-3 停写门禁 8/8（截止点 LSN `0/4FB2BD00`）；I4-6 最终备份恢复验证 11/11、扩展 4/4；
  I4-2 双 manifest 锁定（U 具名批准九表两阶段）；I4-7 migrate 九表一次受控回滚后重跑绿色
  （19 索引、zhcfg 等价、行数零漂移）+ reset 阶段 1 七表逐字执行；I4-4 生产重建 8/8
  built/published/active、build_id 与 I3-7 沙箱基线逐一相同；I4-5 真注册工具生产往返通过、
  零模型断言、无双写实测、旧写入口停用；reset 阶段 2（U 解除暂缓后批准）五门全过
  （write-once [i4c-reset-phase2-report.json](../corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i4c-reset-phase2-report.json)，sha `11762f4e…`），旧九表归零、保留序列与见证表不变；
- **m7-review-20260924**（[report.md](../m7-review-20260924/report.md)）：六项复核——G1 默认服务恢复
  （30 题 QP/EP 24/24、负例 0/6）、S1 目标解析去 import 缓存、G2 旧 ingest 写入口 fail-closed、
  S2 search() 统一委托、G3/G4 部分关闭转 F2/F3；U 批准「全部修复，P1 优先」；
- **m7-fix-20260924**（[工作区](../m7-fix-20260924/)）：G1/S1/G2/S2 修复随 r5j 入链；冻结 PG 电池复放
  全绿（m4-plain/i1 各 320、dev-lane 9、search-live 11、fullchain 12、hermetic 78、d2d6 73）；
  全仓 pytest 2931 passed / 2 既有 failed / 49 skipped；
- **m7-rereview-20260924**（[report.md](report.md)）：F1（P1，evidence 写入口未停用）、F2（P2，恢复
  取证未验正文）、F3（P2，验收报告未绑实际版本）；
- **m7-finalize-20260924**（[工作区](../m7-finalize-20260924/)）：F1 修复验证
  [f1-retired-evidence-writer-verification.json](../m7-finalize-20260924/f1-retired-evidence-writer-verification.json)
  （`save_evidence_run()` 恒定抛 `RetiredEvidenceWriteError`，零 `psycopg.connect`，`extract_claims()`
  默认非持久化且 persist=True 同样拒绝）；F2 修复验证
  [g3b-isolated-restore-body-verification.json](../m7-finalize-20260924/g3b-isolated-restore-body-verification.json)
  （一次性库恢复，290 条可解析历史正文与 `public.blocks.text` 全量逐字一致，manifest 25/25，库已销毁）；
  F3 由 r5k 将脚本/报告/审查件绑定当前代码测试哈希并标注历史基线；r5l/r5m 为验证器语义澄清
  （F1 门=写入口拒绝，非历史空表存在性）。冻结链验证 validate_i0c_freeze.py exit 0（链头 r5m）。

## 不含范围（not_covered）

- **stats/list_documents 迁移残留观察项**：仍查询旧表、输出 0 文档/0 块；接受为已知观察项，
  由 I5-3 退休核验统一处置；
- 全仓 2 既有 failed（market_golden stale-quote、research_discipline）与 49 skipped 口径
  与复核基线相同，非本轮引入；
- abstain=on 下 24/24 正例拒检：M6 签认已裁决为已知限制（延续有效）；
- **I5（M8）执行结果不在本签认范围**：I5-1/2/3 按批准范围执行后另行回填与复核；
- tasks.md / claims-market 工作区改动未 commit，git 提交由 U 另行决定。

机器可读版：[signoff-record-m7.json](signoff-record-m7.json)（`signed_in: i0c-r5n`）。
