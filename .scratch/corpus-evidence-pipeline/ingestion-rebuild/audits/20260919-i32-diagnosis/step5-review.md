# Step 5 针对性复核（只审新增派生关系／旧基线范围／初始版本）

- 复核时间：2026-09-19T18:30:41+08:00；复核对象：i0c-r28（及 r27 的旧基线冻结）
- 结论：**通过**

| 区域 | 复核项 | 结论 | 证据 |
|---|---|---|---|
| ①派生关系 | 派生件 = 批准投影的确定性材料化（独立重推，未复用派生器自校验） | **pass** | 30 题逐题比对一致；必需 79 条、补充 20 条 |
| ①派生关系 | 条目级回链 source-gold（source_id/quote/locator） | **pass** | 全部回链通过 |
| ①派生关系 | 唯一读入口按 manifest 路径 + 哈希读取（不依赖默认路径/最新文件） | **pass** | manifest.status=frozen_r28；scoring_input=.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl |
| ①派生关系 | 审批原件未被派生改动 | **pass** | query-gold-frozen.jsonl sha256=6f6c5a25d55b…（r26 起未变） |
| ②旧基线范围 | 用例计数与 U 圈定范围一致（19/57/7/2/2，O6 留出排除） | **pass** | 实测 {"legacy_retrieval_golden": 19, "financial_controlled_recalc_57": 57, "formula_7": 7, "prose_numbers_3": 2, "macro_legacy_fields_0_of_3": 2} |
| ②旧基线范围 | 无残留 blocked 项 | **pass** | blocked=0 |
| ②旧基线范围 | 57 格拆分 = maotai 32 / guangli 15 / guosen 10（含 holdout 标记） | **pass** | {"maotai_financial_tables": 32, "guangli_financial_table": 15, "guosen_maotai_holdout": 10} |
| ②旧基线范围 | 7 条公式均有输入指标声明（来自 derivation.py） | **pass** | {"formula7|revenue_growth": ["revenue", "revenue"], "formula7|parent_profit_growth": ["parent_net_profit", "parent_net_profit"], "formula7|operating_cash_growth": ["operating_cash_flow", "operating_cash_flow"], "formula7 |
| ②旧基线范围 | 19 题锚点映射唯一命中 + 指向文件存在 | **pass** | 锚点 22 个；非唯一 0；source_path 缺失 0<br>与已标注 source-gold 同源的 doc_id 5 个：['2026-08-13_174b6462', '2026-08-16_6f14cc14', '2026-09-06_793b3967', '2026-09-06_dddc7cd0', '2026-09-06_f8e31696']<br>confirmed=false 待人工复核：0 个锚点 |
| ②旧基线范围 | doc_kind 导出权威版本：决定件哈希与现文件一致 | **pass** | CSV sha256=d69bbb1d4908…；决定件含该哈希=是 |
| ②旧基线范围 | 留出隔离：guard 4 根覆盖旧基线涉及来源；prose 留出（天风）是否覆盖 | **pass** | forbidden_roots=5 个：['2026-08-12_2026.08.12-国泰海通-国', '2026-08-17_2026.08.17-国信证券-张', '2026-09-06_2026.09.06-中银国际-中', '2026-09-06_2026.09.06-华泰证券-宏', '2026-09-06_2026.09.06-天风证券-海']<br>prose_holdout_manifest pattern=5520fab6.pdf → guard 覆盖=是<br>文件在磁盘=True |
| ③初始版本 | P4 lineage 哈希逐项可复算（评分器/金标/投影/裁决件/阈值确认单/评分输入） | **pass** | 6 项 lineage 全部与现文件一致；评分输入 sha256=1b018ceb081f… |
| ③初始版本 | P4 policy 与 P2 一致 | **pass** | {"top_k": 5, "min_rate": "19/20", "require_critical_all_pass": true, "max_false_positives": 0, "max_fabricated_citations": 0} |
| ③初始版本 | P4 关键题/负例计数与 P2 一致 | **pass** | critical=28；negatives=6 |
| ③初始版本 | 执行段完整且未实现入口显式登记（不写成已可执行） | **pass** | status=not_executable_yet；未实现入口=2 项；运行时显式 policy=有 |
| ③初始版本 | 初始版本组成资产均已入链 | **pass** | 未入链：无 |
| ③初始版本 | P2/P3/P4 内的路径字段均可从仓库根解析 | **pass** | 全部可解析 |

## 复核用可复现命令

- `冻结链` → exit 1
- `阶段完成门` → exit 0
- `派生件自校验` → exit 0

## 未入链文件（Step 6 待绑）

- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r29/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p2/policy-and-lists-confirmation.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r29/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p3/baseline-mapping-reconciliation.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r29/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p4/experiment-initial-version.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r29/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p4/experiment-initial-version.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r31/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/baseline-case-manifest.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r31/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/baseline-case-manifest.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r31/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/legacy-anchor-mapping.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r31/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/legacy-anchor-mapping.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r31/.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r31/.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i3_2_completion.py`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r31/docs/plan/claims-market-closed-loop-plan.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/before-r31/docs/plan/corpus-ingestion-rebuild-tasks.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/diagnose.py`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/freeze_r28.py`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/probes.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/inventory.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/inventory.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p1/materialization-report.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p1/materialization-report.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p1/materialize.py`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p1/query-gold-with-targets.jsonl`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p2/policy-and-lists-confirmation.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remaining-inventory/p3/baseline-mapping-reconciliation.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/approval-report-v1.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-adjudication-v2.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-candidates-v1.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-candidates-v2.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-candidates-v5.json`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-review-v1.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-review-v2.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-review-v5.md`
- `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-verification-v3.json`
