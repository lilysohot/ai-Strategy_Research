# I3-1 开发集 E2E —— 照 U 批准集（真实结果，缺口如实登记）

- 生成：2026-09-19T22:31:38+08:00
- 范围来源：i0a2-adjudicated-20260915.json :: dev_selection_approved（U 2026-09-15 批准）（6 份）
- 取样自检：**PASS**（6/6；覆盖格式 ['pdf']）
- 证据：i3-1-e2e-record.json + i3-1-e2e-sources.json（第一/二阶段用的 6 份与批准集完全一致，故该批真实结果即批准集结果，无需重跑；沙箱自 2026-09-19 23:0x 起不可用（Docker 停），数据层重置登记为 pending。）

## 逐来源（缺口如实登记）

| 领域 | 格式 | 来源 | 单元/切块 | check | publish | 阻断缺口 |
|---|---|---|---|---|---|---|
| company | pdf | 2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦 | 778/25 | 4 | 4 | image_region_unreadable(needs_ocr)@2 |
| company | pdf | 2026-09-06_2026.09.06-国信证券-光力科技-30 | 798/198 | 4 | 4 | image_region_unreadable(needs_ocr)@7 |
| industry | pdf | 2026-08-13_2026.08.13-长江证券-国内研报-长江 | 1518/282 | 4 | 4 | image_region_unreadable(needs_ocr)@1；image_region_unreadable(needs_ocr)@2；table_lines_without_extraction(review_required)@12；table_lines_without_extraction(review_required)@13；table_lines_without_extraction(review_required)@17；table_lines_without_extraction(review_required)@18；table_lines_without_extraction(review_required)@21；table_lines_without_extraction(review_required)@22；table_lines_without_extraction(review_required)@24；table_lines_without_extraction(review_required)@3 |
| industry | pdf | 2026-09-06_2026.09.06-华福证券-华福证券-基础 | 258/54 | 0 | 0（gen 1） | 无 |
| macro | pdf | 2026-09-06_2026.09.06-华创证券-宏观专题-从分 | 258/21 | 0 | 0（gen 1） | 无 |
| macro | pdf | 2026-09-06_2026.09.06-光大证券-2026年8月 | 695/187 | 4 | 4 | table_lines_without_extraction(review_required)@6 |

- 汇总：可发布 **2/6**；阻断 4；阻断缺口合计 13 处；4305 单元 / 767 切块
- 检索命中：{"营业收入": 0, "景气": 0, "非农": 0, "同比": 4}；取证核验全过=True；审计冲突=[]
- **『三类每类≥2』是否满足：False** —— 按批准集执行，可发布 = company 0/2、industry 1/2、macro 1/2 → **『三类每类≥2 份』在现行门 + 现行裁定下无法满足**；缺口无处置路径（见真问题 1）

## 格式覆盖（§12.1）

- §12.1『每种声称支持的格式均需真实样本』在现行裁定下**无法满足**；须补研报类 MD/DOCX 料，或 U 明确 v1 不声称覆盖（见真问题 2）
- pdf：6 份（批准集全部为 PDF）
- docx：0 份 —— 语料内 DOCX 均被裁定 excluded_from_active → 准入口径下无样本
- md：0 份 —— 同上（6 份投委会报告 excluded_from_active，5 份 pipeline_artifact excluded）

## 阻断缺口清单

| 代码 | 条数 |
|---|---|
| table_lines_without_extraction | 9 |
| image_region_unreadable | 4 |

- 待办：Docker 不可用；恢复后执行：CONFIRM_TEARDOWN=i2_sandbox_corpus CORPUS_I2_DSN=… uv run python .scratch/…/i2/i2s1_teardown.py 然后 i2s1_apply.py —— 目的：清除越权样本（2 MD + DOCX + 5 自选 PDF）在沙箱留下的 publications/admissions


## 重跑确认（干净沙箱，2026-09-19T22:32:58+08:00）

- 沙箱已 teardown（`residue=0`）后按冻结脚本重建 `corpus` schema（9 表 / 19 索引 / vector 0.8.6 + zhparser 2.4）
- 范围仍为 U 批准集 6 份（**无自选、无换料、无越权**），取样前 `preflight_scope_check.py` = PASS
- 结果**逐源一致**：可发布 2/6，阻断缺口 13 处，
  矩阵 {"company:pdf": {"total": 2, "published": 0}, "industry:pdf": {"total": 2, "published": 1}, "macro:pdf": {"total": 2, "published": 1}}
- 检索命中 {"营业收入": 0, "景气": 0, "非农": 0, "同比": 4}；取证核验全过=True；
  审计冲突=[]
- 产物：`i3-1-e2e-approved-set-rerun.json` / `.md`
