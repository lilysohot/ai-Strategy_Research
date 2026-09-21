# band 落产品同口径回测（select_band × index-4-zhcfg-2）

- 生成：2026-09-21T11:26:16+08:00；类型：同口径回测（参照 i42，非冻结回归）
- corpus：8 份 active builds（index-4-zhcfg-2，与 i42 同）
- 选择：产品 `select_band`（G=1/K=1/带数=8/POOL_CAP=24；可证带宽上界 49，实测最大带宽 33）
- 口径：79 目标、查询=问题词元 OR、limit=2000 不饱和断言、scorer=工作树空白规约（NOT frozen）、0 model calls

## 漏斗对比（band vs i42 基线）

| 层 | i42 基线 | band | Δ |
|---|---|---:|---:|
| S0_kept | 77 | 77 | +0 |
| S1_candidates | 66 | 66 | +0 |
| S2_doc_topk | 60 | 60 | +0 |
| S4_matched | 44 | 50 | +6 |
| S3（band 覆盖 / i42 chunk_top8） | 51 | 59 | +8 |

## 三类指标（base / band）

| 类 | DocRecall | QuestionPass | EvidencePass |
|---|---|---|---|
| company | 7/8 / 7/8 | 7/8 / 7/8 | 3/8 / 5/8 |
| industry | 1 / 1 | 8/8 / 8/8 | 3/8 / 4/8 |
| macro | 1 / 1 | 8/8 / 8/8 | 6/8 / 8/8 |

- EvidencePass：base 12/24；band **17/24**（i42 基线 12/24）
- 负例误报：band 6（i42 基线 6，不得回升）
- 桶分布：{"matched": 60, "kept_page_not_selected": 8, "not_in_doc_unreachable": 2, "selected_but_match_fail": 9}
- 带宽：实测最大 33 ≤ 可证上界 49（满足）
