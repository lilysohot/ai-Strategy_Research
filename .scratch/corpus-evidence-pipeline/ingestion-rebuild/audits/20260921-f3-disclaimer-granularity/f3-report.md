# B3 / F3 重摄入后复验（company-007/e1 × index-4-zhcfg-2）

- 生成：2026-09-22T10:45:16+08:00；类型：同口径复验（参照 i42 / F2，非冻结回归）
- corpus：8 份 active builds（index-4-zhcfg-2，2026-09-22 按当前字节全量重建，clean 含 F3）
- 选择：产品 `select_band`（G=1/K=1/带数=8/POOL_CAP=24；可证带宽上界 49，实测最大带宽 33）
- 口径：79 目标、查询=问题词元 OR、limit=2000 不饱和断言、scorer=工作树空白规约（NOT frozen）、0 model calls

## F3 焦点：company-007/e1

- 引文所在 build `58735cff57d8` 的 ord 716–720 单元：

| ord | status | reasons | page | 字符数 | 尾部 | 含完整引文 |
|---|---|---|---|---:|---|---|
| 716 | noise | ['heading_by_font_size', 'disclaimer_heading'] | 7 | 5 | `分析师声明` | False |
| 717 | kept | [] | 7 | 193 | `股股东华创云信4.06%的股` | False |
| 718 | noise | ['disclaimer_section'] | 7 | 2 | `份。` | False |
| 719 | noise | ['heading_by_font_size', 'disclaimer_heading'] | 7 | 4 | `免责声明` | False |
| 720 | noise | ['disclaimer_section'] | 7 | 578 | `易。市场有风险，投资需谨慎。` | False |

- 该句相关块：[{"chunk_id": "58735cff57d8", "kind": "body", "refs": ["unit:0709", "unit:0710", "unit:0711", "unit:0712", "unit:0713", "unit:0714", "unit:0715", "unit:0717"], "has_tail_fragment": false}]（`has_tail_fragment=true` 表示 ord718 的『份。』进块）
- 逐层：{"S0_kept": false, "S1_candidates": false, "S2_doc_topk": false, "S3_band_cover": false, "S4_matched": false}
- 召回：块被召回 = True；文档进 top-5 = True；引文在该块文本内 = False
- 桶：`not_in_doc_unreachable`（重摄入前 = `not_in_doc_unreachable`，`f2-funnel-targets.json` 2026-09-21 15:40）
- 产品路径（`CorpusService.search_bands` = band + 跨边界 + cell）：e1 命中 **False**
- 结节点：把 NOISE 尾片段（ord718『份。』）接回块文本后，引文逐字可承载 = **True**

> 结论：F3 单元级判定已生效（ord717 NOISE→KEPT），但**不足以**让 e1 转绿——事实句被版面切成 kept 前半 + NOISE 尾片段（『份。』），块装配只收 kept 单元 ⇒ 引文在句中断开。转绿需二选一：clean 侧句跨单元粒度（⇒ 重摄入 + 新修订 + 粒度签认）或读取侧续接片段聚合（免重摄入，需新修订）。**均属需 U 裁决的粒度/机制变更，未擅自实施。**


## 漏斗对比（band vs i42 基线）

| 层 | i42 基线 | band（F3 后） | Δ |
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

- EvidencePass：base 12/24；band **17/24**（i42 基线 12/24、F2 band+cell 18/24）
- 负例误报：band 6（i42 基线 6，不得回升）
- 桶分布：{"matched": 60, "kept_page_not_selected": 8, "not_in_doc_unreachable": 2, "selected_but_match_fail": 9}
- 带宽：实测最大 33 ≤ 可证上界 49（满足）

## 自检

- `S1_S2_not_regressed` = True
- `S0_kept_plus_f3` = False
- `e1_S0_kept_green` = False
- `e1_S4_matched_green` = False
- `e1_product_path_matched` = False
- `width_le_provable` = True
- `fp_not_increased` = True
