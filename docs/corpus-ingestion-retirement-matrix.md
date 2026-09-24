# 语料退休与保留矩阵

此矩阵是 I5-3 对 I0-C 消费者矩阵、I2 归并和 I4-5 退休结果的现行核验。它区分产品新链与仍被历史财务/R2 使用的显式兼容能力；后者不能成为公开读取的隐式回退。

| 路径或符号 | 状态 | 约束与核验 |
| --- | --- | --- |
| `plugins.corpus.preparation` 的 `plan_builds`、`execute_builds`、`check_build_publishable`、`publish_build` | 活动写链 | preparation CLI 是正常增量入口；build 和 publish 分阶段执行。 |
| `CorpusService.ingest_path` / `ingest_dir` | 活动适配 | 代理到 preparation 新链，不写旧 ingest 台账。 |
| `CorpusService.run_ingest` 和 service CLI `ingest` | 已退休 | 恒定拒绝，拒绝发生在数据库连接之前；`tests/test_corpus_ingest_retired.py` 覆盖编程和 CLI 调用。 |
| `CorpusService.save_evidence_run` / `extract_claims(..., persist=True)` | 已退休写入口 | 恒定拒绝，不创建或写入 `corpus_evidence_runs`。评测改为工件回读。 |
| `CorpusService.search`、`fetch`、`fetch_verbatim`、`document_text`、`source_resolver`、`stats`、`list_documents` | 活动产品读链 | 读取 `corpus` schema 的活动 publication/build；旧或未知句柄拒绝，不回退 `public.documents`/`blocks`。 |
| `extract_legacy_claims`、`legacy_claims_of`、`blocks_of`、`_legacy_documents` | 显式历史兼容 | 保留给历史财务 claims 的抽取和溯源。它们直接指向旧对象，不能被产品公开列表或 `fetch` 调用。 |
| `load_evidence_run`、`claims_of`、`fetch_evidence`、`derive_claims`、`reconcile_claims` | 历史证据读取 | 仅用于已存在的 evidence run；没有新链持久化或公共读侧 fallback。新评测使用 JSON 工件。 |
| `scripts/corpus_evidence_pilot.py`、`scripts/corpus_holdout_eval.py` | 已迁移评测 | `persist=False`，把完整 `EvidenceRun` 写为内容寻址工件并重新解析、校验 identity 和 packet 坐标。 |
| claims 规则、`claims_detail.py`、财务公式和 R2 material understanding | 保留共享依赖 | 不因 claims 旧写表退休而删除；正常路径以内存 `EvidenceRun` 或明确的历史读取使用它们。 |

核验规则：产品 API 不得调用兼容行；兼容行必须由其明确名称或 `--legacy` 选择；任何新增删除、迁移或持久化方案需要单独的对象清单和批准，不能由本矩阵推断授权。
