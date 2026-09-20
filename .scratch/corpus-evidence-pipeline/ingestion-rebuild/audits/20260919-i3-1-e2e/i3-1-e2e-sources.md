# I3-1 三类开发 E2E（逐来源结果）

- 生成：2026-09-19T18:47:24+0800；目标 `postgresql://***@127.0.0.1:543/i2_sandbox_corpus`；守卫 sha256 1c238a62d0d7
- **范围状态：proposed_pending_ratification**（见 findings F2）

## 逐来源门与发布

| 来源 | 格式 | 单元/切块 | check | publish | 阻断缺口 |
|---|---|---|---|---|---|
| 2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司研究 | pdf | 778/25 | 4（不可发布） | 4 | image_region_unreadable@issue:image_region_unreadable:page:2 |
| 2026-09-06_2026.09.06-国信证券-光力科技-300480-202 | pdf | 798/198 | 4（不可发布） | 4 | image_region_unreadable@issue:image_region_unreadable:page:7 |
| 2026-08-13_2026.08.13-长江证券-国内研报-长江证券-化工专题- | pdf | 1518/282 | 4（不可发布） | 4 | image_region_unreadable@issue:image_region_unreadable:page:1；image_region_unreadable@issue:image_region_unreadable:page:2；table_lines_without_extraction@issue:table_lines_without_extraction:page:12；table_lines_without_extraction@issue:table_lines_without_extraction:page:13；table_lines_without_extraction@issue:table_lines_without_extraction:page:17；table_lines_without_extraction@issue:table_lines_without_extraction:page:18；table_lines_without_extraction@issue:table_lines_without_extraction:page:21；table_lines_without_extraction@issue:table_lines_without_extraction:page:22；table_lines_without_extraction@issue:table_lines_without_extraction:page:24；table_lines_without_extraction@issue:table_lines_without_extraction:page:3 |
| 2026-09-06_2026.09.06-华福证券-华福证券-基础化工行业新材料周 | pdf | 258/54 | 0（可发布） | 0 | 无 |
| 2026-09-06_2026.09.06-华创证券-宏观专题-从分化到收敛-可能的 | pdf | 258/21 | 0（可发布） | 0 | 无 |
| 2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据点评 | pdf | 695/187 | 4（不可发布） | 4 | table_lines_without_extraction@issue:table_lines_without_extraction:page:6 |

## 检索 / 取证 / 核验（已发布集合）

| 查询 | 命中 |
|---|---|
| 营业收入 | 0 |
| 景气 | 0 |
| 非农 | 0 |
| 同比 | 4 |

- 已发布：['2026-09-06_2026.09.06-华福证券-华福证券-基础', '2026-09-06_2026.09.06-华创证券-宏观专题-从分']
- 覆盖：{"requested_scope_ref": "corpus_schema", "effective_scope_ref": "corpus_publications.active_build_id", "publication_snapshot_ref": "corpus_publications@f223368972471e5499622e50adaca5ae", "processing": "scoped", "query_status": "matched", "a
- 审计冲突：[]

## Findings

- **F1** CLI `plan` 的 stdout 被 PyMuPDF 横幅（『Consider using the pymupdf_layout package…』）污染 → 严格按 JSON 解析 stdout 的调用方会解析失败；本阶段已改为取首个 `{` 起解析并记录前缀；建议：PyMuPDF 输出应改道 stderr（或 plan 阶段显式抑制）；属 CLI stdout 契约缺陷，建议单列修复
- **F2** 开发范围 73 份来源终态仍为 review_required（M1 未决） → 本轮按 Agent 提案 3 类×2 份执行，登记决定作者已写明待追认；I3-1 不能据此宣告完成；建议：U 批准范围后重跑并冻结该清单
- **F3** docx 无开发样本 → 格式矩阵缺一格；按任务口径『缺格式门未过』登记；建议：U 定性：补 DOCX 样本 或 声明缺格式
