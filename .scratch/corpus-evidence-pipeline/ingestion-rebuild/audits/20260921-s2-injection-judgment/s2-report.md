# S2 判定实验：标签注入对召回与 EvidencePass 的贡献（读侧虚拟重建）

- 生成：2026-09-21T10:55:37+08:00；类型：判定实验（spec §6.1 S2 / §10.2）
- corpus：8 份 active builds（index-4-zhcfg-2，与 i42 同）
- 方法：不重摄入。无注入索引文本 = 候选 chunk 引用单元 raw_text 逐字拼接 + normalize_search_text（R5），重算 to_tsvector('zhcfg', …) @@ tsq 与 ts_rank。
- 口径：79 目标、perdoc 选择、工作树空白规约 scorer、query=问题词元 OR、limit=2000 不饱和断言（与 i42 backtest.py 一致）。
- 自检（with_injection 复现 i42）：**通过**

## 漏斗对比（嵌套累计）

| 层 | i42 基线 | with_injection | no_injection | Δ(no_inj − i42) |
|---|---|---:|---:|---:|
| S0_kept | 77 | 77 | 77 | **+0** |
| S1_candidates | 66 | 66 | 66 | **+0** |
| S2_doc_topk | 60 | 60 | 30 | **-30** |
| S3_chunk_top8 | 51 | 51 | 18 | **-33** |
| S4_matched | 44 | 44 | 13 | **-31** |

## 三类指标（with_injection / no_injection）

| 类 | DocRecall | QuestionPass | EvidencePass |
|---|---|---|---|
| company | 7/8 / 7/16 | 7/8 / 3/8 | 3/8 / 2/8 |
| industry | 1 / 9/16 | 8/8 / 4/8 | 3/8 / 0/8 |
| macro | 1 / 3/8 | 8/8 / 3/8 | 6/8 / 0/8 |

- EvidencePass：with_injection 12/24；no_injection 2/24（i42 基线 12/24）
- 负例误报：with_injection 6；no_injection 6（i42 基线 6，不得回升）

## 注入的召回贡献（S1_candidates 掉失目标）

**带注入可召回、无注入不可召回的目标数 = 0**（0 即注入对召回零贡献）


## 逐目标对比（with_injection → no_injection）

| 目标 | S1(wi→ni) | S2 | S3 | S4 | 桶(wi) → 桶(ni) |
|---|---|---|---|---|---|
| company-001 a-2 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| company-001 e4 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| company-002 e1 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| company-002 e2 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| company-002 e3 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| company-003 e1 | ✓→✓ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → selected_but_match_fail |
| company-003 e2 | ✓→✓ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-003 e3 | ✓→✓ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-003 e4 | ✓→✓ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-003 e5 | ✓→✓ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-003 e6 | ✓→✓ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-004 a-2 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-004 a-3 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-004 e2 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-005 e2 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-005 e3 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-006 e1 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| company-006 e2 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| company-006 e3 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| company-007 e1 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | not_in_doc_unreachable → not_in_doc_unreachable |
| company-008 a-1 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | not_in_doc_unreachable → not_in_doc_unreachable |
| company-008 a-2 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-008 a-3 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| company-008 a-4 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| company-008 a-5 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| industry-001 a-4 | ✓→✓ | ✓→✓ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| industry-001 a-5 | ✓→✓ | ✓→✓ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| industry-001 e1 | ✓→✓ | ✓→✓ | ✓→✓ | ✗→✗ | selected_but_match_fail → selected_but_match_fail |
| industry-001 e2 | ✓→✓ | ✓→✓ | ✓→✓ | ✗→✗ | selected_but_match_fail → selected_but_match_fail |
| industry-001 e3 | ✓→✓ | ✓→✓ | ✓→✓ | ✗→✗ | selected_but_match_fail → selected_but_match_fail |
| industry-002 a-3 | ✓→✓ | ✓→✓ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| industry-002 a-4 | ✓→✓ | ✓→✓ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| industry-002 e1 | ✓→✓ | ✓→✓ | ✓→✗ | ✗→✗ | selected_but_match_fail → kept_page_not_selected |
| industry-002 e2 | ✓→✓ | ✓→✓ | ✓→✗ | ✗→✗ | selected_but_match_fail → selected_but_match_fail |
| industry-003 a-3 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| industry-003 e1 | ✓→✓ | ✓→✓ | ✓→✓ | ✗→✗ | selected_but_match_fail → selected_but_match_fail |
| industry-003 e2 | ✓→✓ | ✓→✓ | ✓→✓ | ✗→✗ | selected_but_match_fail → selected_but_match_fail |
| industry-004 a-1 | ✓→✓ | ✓→✓ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| industry-004 a-2 | ✓→✓ | ✓→✓ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| industry-005 e1 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| industry-005 e2 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| industry-006 a-1 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| industry-006 a-2 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| industry-006 a-3 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| industry-007 e1 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| industry-007 e2 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| industry-007 e3 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| industry-008 a-2 | ✓→✓ | ✓→✓ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| industry-008 a-3 | ✓→✓ | ✓→✓ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| industry-008 a-4 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| industry-008 a-5 | ✓→✓ | ✓→✓ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| industry-008 e1 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-001 a-3 | ✓→✓ | ✓→✓ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-001 e1 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| macro-001 e2 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| macro-002 e1 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| macro-002 e3 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| macro-002 e4 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| macro-003 a-2 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| macro-003 a-3 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| macro-003 a-4 | ✗→✗ | ✗→✗ | ✗→✗ | ✗→✗ | kept_page_not_selected → kept_page_not_selected |
| macro-003 e1 | ✓→✓ | ✓→✓ | ✓→✓ | ✓→✓ | matched → matched |
| macro-004 a-1 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-004 a-2 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-004 a-3 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-004 a-4 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-004 a-5 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-004 a-6 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-005 a-2 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-005 e1 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-006 a-3 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-006 e1 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-006 e2 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-007 e1 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-007 e2 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-007 e3 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-008 a-3 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-008 e1 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |
| macro-008 e2 | ✓→✓ | ✓→✗ | ✓→✗ | ✓→✗ | matched → kept_page_not_selected |

## 判定

- **S1_candidates 掉失：0 条**。（0 掉失）→ 注入对召回零贡献，支持 S3b 删除注入。
- EvidencePass 变化：12/24 → 2/24。
- 负例误报：6 → 6（符合不回升约束）。
