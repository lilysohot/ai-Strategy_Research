# I3-1 三类开发 E2E 记录

- 生成：2026-09-19T18:46:24+08:00；目标：`postgresql://***@127.0.0.1:543/i2_sandbox_corpus`（库 `i2_sandbox_corpus`）
- 守卫：`.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json`（sha256 1c238a62d0d7；已装载=True）
- **范围状态：proposed_pending_ratification** —— dev-manifest.json 的 73 份来源终态均为 review_required（M1 前置未决）。本轮按 Agent 提案的 3 类×2 份在隔离库执行，登记的审核决定作者已写明『Agent 提案，待 U 追认』；**本记录不构成开发范围冻结，也不宣告 I3-1 完成**。

## 前置

- 当前库：i2_sandbox_corpus；实例含 apodex：False；corpus schema：True

## 链路（真实产物）

| 步骤 | 退出码 | 秒 |
|---|---|---|
| plan | 0 | 5.4 |
| build | 0 | 9.14 |
| check | 4 | 0.01 |
| publish | 4 | 0.01 |
| status | 0 | 0.02 |

- build_id：`['3267838741573161a92e57493672f6f882bceda7f84b9d69fc85db85a6481493', '6509bf635ab5dd2a2090fad369b116c744c43d9be842d4c2c6f90569963f2281', 'a95779f6872d9e6103bcc755e947070e46a9ae6ec45f6156087356bdfc18b58f', 'b7291df6abc1bed46d56e39f44eb594f61c172019f214a70e6fe226fb05facf4', 'bf06d59c7c6639e10abe854485b063a818114fd9b38872a16cbec1e56a3f6a28', 'f6ce586247b5c88a6a1091f8f1f194366a14be57c17e664cd6d024a5caa5eca8']`
- publish generation：None

## 检索 / 取证 / 核验

| 查询 | 命中 |
|---|---|
| 营业收入 | 0 |
| 景气 | 0 |
| 非农 | 0 |
| 同比 | 0 |

逐条核验（任一项 false = 链路问题）：active / chunk=单元拼接 / 单元非空 / 单元文本⊆文档文本 / 页号在范围。
PDF 说明：正文由 PyMuPDF 解析而来，**字节级逐字不适用**；本记录按『单元文本 ⊆ 该文档解析文本』核验。

## 覆盖与审计

- coverage：{"requested_scope_ref": "corpus_schema", "effective_scope_ref": "corpus_publications.active_build_id", "publication_snapshot_ref": "corpus_publications@b37c0c0d63411276251b6608fa320ed6", "processing": "unknown", "query_status": "matched", "availability": "unknown", "reason_codes": [], "counts": {"so
- 同快照组合读取：{"hits": 0, "same_snapshot_ok": false}
- 审计冲突：[]

## 领域×格式矩阵

- 领域：{"?": 6}；格式：{"?": 6}
- 缺口：docx：开发范围无 DOCX 样本 → 缺格式门未过（需 U 定性：补样本 或 声明缺格式）
- 缺口：pdf：company/industry/macro 各 2 份
