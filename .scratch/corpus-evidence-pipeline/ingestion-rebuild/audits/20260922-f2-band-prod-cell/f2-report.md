# F2：band / band+cell 接入产品读取路径（只读回测）

- 生成：2026-09-21T15:40:04+08:00；类型：同口径回测（产品 read_pg/search_bands 路径；非冻结回归）
- corpus：8 份 active builds（index-4-zhcfg-2，与 i42 同）
- 生产默认：perdoc（未翻转）；band 为新增并行路径
- 选择：`select_band`（G=1/K=1/带数=8/POOL_CAP=24；可证带宽上界 49，实测最大 33）
- 产品方法：`read_pg.search_with_coverage_bands` / `read_pg.fetch_bands` / `CorpusService.search_bands`（含 `_emit_cells` cell 坐标投影）
- 口径：79 目标、查询=问题词元 OR、limit=2000 不饱和、0 model calls；负例=判定层拒检兜底（F1 同模块）

## 漏斗（band 层 vs i42 基线）

| 层 | i42 基线 | band | Δ |
|---|---|---:|---:|
| S0_kept | 77 | 77 | +0 |
| S1_candidates | 66 | 66 | +0 |
| S2_doc_topk | 60 | 60 | +0 |
| S4_matched | 44 | 50 | +6 |

## 逐层 EvidencePass

| 层 | company | industry | macro | 合计 |
|---|---|---|---|---|
| base（perdoc·对照） | 3/8 | 3/8 | 6/8 | 12/24 |
| band（产品带区间·页级） | 5/8 | 4/8 | 8/8 | 17/24 |
| band_s2（+ cell 坐标投影） | 5/8 | 5/8 | 8/8 | 18/24 |

- band（17/24）：17/24
- band_s2（19/24）：18/24
- row:/col:：13 条 → matched 5，仍是 8：
  - company-003 e1 ['page:20', 'row:每股收益', 'col:2026E']
  - company-003 e2 ['page:20', 'row:经营活动现金流', 'col:2026E']
  - company-003 e3 ['page:20', 'row:每股收益', 'col:2027E']
  - company-003 e4 ['page:20', 'row:经营活动现金流', 'col:2027E']
  - company-003 e5 ['page:20', 'row:每股收益', 'col:2028E']
  - company-003 e6 ['page:20', 'row:经营活动现金流', 'col:2028E']
  - industry-002 e2 ['page:10', 'row:R32', 'col:2026E产能（配额）']
  - industry-003 e2 ['page:10', 'row:尿素', 'col:2026E产能']

## 负例

- 认证：6 条经判定层拒检兜底 → retrieved_documents=0
- canary（OR 路径，若拒检关闭）：[{'query_id': 'company-009', 'retrieved_documents': 5}, {'query_id': 'company-010', 'retrieved_documents': 5}, {'query_id': 'industry-009', 'retrieved_documents': 5}, {'query_id': 'industry-010', 'retrieved_documents': 5}, {'query_id': 'macro-009', 'retrieved_documents': 5}, {'query_id': 'macro-010', 'retrieved_documents': 5}] docs / fp=6（i42 基线 6）
- self_check.fp_not_increased = True（认证 0 ≤ 6）

## 自检

- S0/S1/S2 与 i42 逐字节一致：True
- band_equals_product：{"S3_band_cover": true, "S4_matched": true, "band_evidence_pass_17": true, "band_s2_evidence_pass_19": false}
- width_le_provable：True
- 桶分布：{"matched": 60, "kept_page_not_selected": 8, "not_in_doc_unreachable": 2, "selected_but_match_fail": 9}
