# I42 议题 B 同口径回测（index-4-zhcfg-2 × 结构重叠排序，global/perdoc 两变体）

- 生成：2026-09-21T00:56:04+08:00；类型：同口径回测（参照 i37，非冻结回归）
- corpus：8 份 active builds（i42 teardown 重建，reader-pdf-6 / chunk-3 / index-4-zhcfg-2）
- 选择上限保持 8（I-B3）；查询只用问题词元 OR 连接；信号只来自 chunk 结构标签（I-B1 注入）
- i37 基线：DocRecall 全域 1；负例误报 6；EvidencePass 13/24

## 两变体对照

| 指标 | global（全池主键） | perdoc（文档内主键） |
|---|---|---|
| 议题 B 进选择范围 | 7/10 | 7/10 |
| EvidencePass | 12/24 | 12/24 |
| 负例误报 | 6 | 6 |
| 目标桶回退数（vs i37） | 22 | 21 |

## 议题 B 十条引文探针（global 变体）

| 目标 | 文档排名 | 原始块排名 | 选中块排名 | 进选择范围 |
|---|---:|---:|---:|---|
| industry-001 e1 | 1 | 9 | 1 | ✓ |
| industry-001 e2 | 1 | 9 | 1 | ✓ |
| industry-001 e3 | 1 | 9 | 1 | ✓ |
| industry-002 e1 | 1 | 3 | 5 | ✓ |
| industry-003 e1 | 1 | 4 | 1 | ✓ |
| industry-003 e2 | 1 | 4 | 1 | ✓ |
| industry-003 a-3 | 1 | 4 | 1 | ✓ |
| industry-008 a-2 | 1 | 35 | None | ✗ |
| industry-008 a-3 | 1 | 49 | None | ✗ |
| industry-008 a-5 | 1 | 49 | None | ✗ |

## 逐目标桶回退明细（global → perdoc，对照 i37）

| 目标 | i37 | global | perdoc |
|---|---|---|---|
| company-003 e1 | selected_but_match_fail | kept_page_not_selected | kept_page_not_selected |
| company-003 e2 | selected_but_match_fail | kept_page_not_selected | kept_page_not_selected |
| company-003 e3 | selected_but_match_fail | kept_page_not_selected | kept_page_not_selected |
| company-003 e4 | selected_but_match_fail | kept_page_not_selected | kept_page_not_selected |
| company-003 e5 | selected_but_match_fail | kept_page_not_selected | kept_page_not_selected |
| company-003 e6 | selected_but_match_fail | kept_page_not_selected | kept_page_not_selected |
| company-007 e1 | doc_not_kept_clean_stage_loss | not_in_doc_unreachable | not_in_doc_unreachable |
| company-008 a-1 | doc_not_kept_clean_stage_loss | not_in_doc_unreachable | not_in_doc_unreachable |
| company-008 a-4 | matched | kept_page_not_selected | None |
| industry-001 a-4 | matched | kept_page_not_selected | kept_page_not_selected |
| industry-001 a-5 | matched | kept_page_not_selected | kept_page_not_selected |
| industry-001 e1 | kept_page_not_selected | selected_but_match_fail | selected_but_match_fail |
| industry-001 e2 | kept_page_not_selected | selected_but_match_fail | selected_but_match_fail |
| industry-001 e3 | kept_page_not_selected | selected_but_match_fail | selected_but_match_fail |
| industry-002 a-3 | matched | kept_page_not_selected | kept_page_not_selected |
| industry-002 a-4 | matched | kept_page_not_selected | kept_page_not_selected |
| industry-002 e1 | kept_page_not_selected | selected_but_match_fail | selected_but_match_fail |
| industry-003 a-3 | kept_page_not_selected | matched | matched |
| industry-003 e1 | kept_page_not_selected | selected_but_match_fail | selected_but_match_fail |
| industry-003 e2 | kept_page_not_selected | selected_but_match_fail | selected_but_match_fail |
| industry-004 a-1 | matched | kept_page_not_selected | kept_page_not_selected |
| industry-004 a-2 | matched | kept_page_not_selected | kept_page_not_selected |

## 三类指标（global / perdoc）

| 类 | DocRecall | QuestionPass | EvidencePass |
|---|---|---|---|
| company | 13/16 / 7/8 | 6/8 / 7/8 | 3/8 / 3/8 |
| industry | 1 / 1 | 8/8 / 8/8 | 3/8 / 3/8 |
| macro | 1 / 1 | 8/8 / 8/8 | 6/8 / 6/8 |

## 关键发现

- 议题 B：两变体均 7/10 引文进入选择范围（6 条 selected_but_match_fail + 1 条 matched；industry-001 e1-e3 / industry-003 e1/e2/a-3 选中块 rank 1，industry-002 e1 rank 5）。
- 未进的 3 条全部是 industry-008 的页 10 图6 表头/脚注引文（a-2/a-3/a-5）：raw rank 35/49，该查询下页 10 图6 块未进入长江文档 top-8（页 6/7 的涨幅TOP5 表格块占据），是候选池内排名问题而非 cap 问题。
- 6 条带 row:/col: 定位符的目标（industry-001/002/003 的 e1-e3）在现行观测构造下最多只能到 selected_but_match_fail（EvidenceTarget.matches 要求 locator 全部 token ∈ evidence.locator，而 evidence locator 只有 page:N）；只有 page-only 定位符的 a-3 可达 matched。
- company-003 回退（光力科技 doc 落出 top-5）是词法层回归：I-B1 标签注入改变 ts_rank 后，光力在该查询下 doc rank 6；两变体均受影响，与结构排序信号无关。
- company-008 a-4 是两变体唯一分歧点：global 因全池重排把贵州茅台文档挤出 top-5 而回退，perdoc 保持词法文档序后维持 matched（['company-008 a-4']）。
- 系统级：EvidencePass 两变体均 12/24（i37 基线 13/24）；负例误报均 6（不增）；company DocRecall global 13/16、perdoc 7/8（perdoc 恢复 company-008）。

## 待决

1. 排序信号形态：perdoc（文档序=词法，文档内按 (结构重叠, ts_rank)）相对 global 少 1 条回退且不扰动文档级召回，建议优先；是否采纳需裁决。
2. company-003 词法级回退：属 I-B1 标签注入副作用，不在结构排序信号范围内，需另立议题。
3. industry-008 表头/脚注引文：需判断是否属议题 B 验收必须（原文判据含 10 条全进），如必须则需扩展候选或检索侧信号。

## 决定（2026-09-21，用户裁决）

1. **排序信号形态**：采纳 **perdoc**（文档序=词法首次出现，仅文档内前 8 块按 (结构重叠, ts_rank) 重排）。
   理由：相对 global 少 1 条回退（company-008 a-4 保持 matched），且不扰动文档级召回（company DocRecall 7/8 > 13/16）。
2. **company-003 光力科技回退**：**另立议题**处理。根因是 I-B1 标签注入改变 ts_rank 导致光力 doc rank 6（词法层），
   不在结构排序信号范围内，本轮议题 B 不接受该回退但不在本票内解决。
3. **industry-008 表头/脚注引文（a-2/a-3/a-5）**：**移出议题 B**。表头/脚注文本在多个表格块 label_path 重复出现，
   属内容归属问题而非结构排序问题；当前桶 = kept_page_not_selected，记录在案。
4. **议题 B 验收口径**：进选择范围 = 7/10（industry-001/002/003 的 7 条 cell/header 引文）；
   6 条 row:/col: 定位符目标在现行观测构造下最多到 selected_but_match_fail（locator 子集约束），另立观测侧议题。
5. **产品落点**：perdoc 已落产品 `selection.py::select_structural(hits, policy, *, lexemes)`（文档序=词法，
   文档内按 (结构重叠数, score) 重排）；`search_pg.rank_hits` 的 structural 模式保留为审计对照原语。
   `tests/test_corpus_selection.py` 新增 4 条 perdoc 常驻测试；test_corpus_*.py 全绿 + pyright/ruff 通过。
