# I42 全链路逐层召回率实测（产品 select_structural / perdoc）

- 生成：2026-09-21T01:16:48+08:00；scorer：工作树空白规约（NOT frozen）；model_calls=0
- 链路：search_chunks → selection.select_structural（perdoc）→ fetch_verbatim → scoring

## 逐层漏斗（79 目标，嵌套累计，含 S4=matched 判定）

| 层 | 含义 | 存活目标 | 累计存活率 |
|---|---|---:|---:|
| S0_kept | 引文在源文档 kept 单元内（可取证） | 77/79 | 97.5% |
| S1_candidates | 引文在源文档候选块内（search 层可召回） | 66/79 | 83.5% |
| S2_doc_topk | 源文档进入 top-5 选择文档（文档层 DocRecall） | 60/79 | 75.9% |
| S3_chunk_top8 | 引文块进入该文档选中 top-8（块层，I-B2） | 51/79 | 64.6% |
| S4_matched | EvidenceTarget.matches 逐字命中（证据层） | 44/79 | 55.7% |

## 逐层损失

| 断点 | 损失数 | 目标 |
|---|---:|---|
| S0_kept→S1_candidates | 11 | company-004 a-2, company-004 a-3, company-004 e2, company-005 e2, company-005 e3, company-008 a-2, company-008 a-3, company-008 a-5, macro-002 e4, macro-003 a-2, macro-003 a-4 |
| S1_candidates→S2_doc_topk | 6 | company-003 e1, company-003 e2, company-003 e3, company-003 e4, company-003 e5, company-003 e6 |
| S2_doc_topk→S3_chunk_top8 | 9 | industry-001 a-4, industry-001 a-5, industry-002 a-3, industry-002 a-4, industry-004 a-1, industry-004 a-2, industry-008 a-2, industry-008 a-3, industry-008 a-5 |
| S3_chunk_top8→S4_matched | 7 | industry-001 e1, industry-001 e2, industry-001 e3, industry-002 e1, industry-002 e2, industry-003 e1, industry-003 e2 |

## 评分器指标（工作树空白规约）

| 类 | DocRecall | QuestionPass | EvidencePass |
|---|---|---|---|
| company | 7/8 | 7/8 | 3/8 |
| industry | 1 | 8/8 | 3/8 |
| macro | 1 | 8/8 | 6/8 |

- EvidencePass 合计：12/24（i37 基线 13/24）
- 负例误报：6（i37 基线 6，不增）
- 议题 B：7/10 引文进选择范围

## 桶分布对照

| 桶 | i37 | i42(perdoc) |
|---|---:|---:|
| candidates_no_doc | 0 | 6 |
| doc_not_kept_clean_stage_loss | 2 | 0 |
| doc_topk_no_chunk | 0 | 9 |
| kept_not_candidate | 0 | 11 |
| kept_page_not_selected | 21 | 0 |
| matched | 49 | 44 |
| not_in_doc_unreachable | 0 | 2 |
| selected_but_match_fail | 7 | 7 |
