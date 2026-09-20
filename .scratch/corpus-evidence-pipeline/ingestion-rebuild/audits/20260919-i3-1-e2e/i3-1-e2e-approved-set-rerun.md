# I3-1 开发集 E2E —— 照 U 批准集（干净沙箱重跑）

- 生成：2026-09-19T22:32:58+08:00；范围来源：i0a2-adjudicated-20260915.json :: dev_selection_approved（sha256 839166417b97，6 份）
- 取样自检：**PASS**（6/6；`preflight-scope-check.json`）；**无自选、无换料、无越权**
- 环境：干净沙箱（teardown residue=0 后重建 corpus schema）；守卫 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json`（279d86662d5e）

## 逐来源（缺口如实登记）

| 领域 | 来源 | 单元/切块 | check | publish | 阻断缺口 |
|---|---|---|---|---|---|
| company | 2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张 | 778/25 | 4 | 4 | image_region_unreadable(needs_ocr)@2 |
| company | 2026-09-06_2026.09.06-国信证券-光力科技-3004 | 798/198 | 4 | 4 | image_region_unreadable(needs_ocr)@7 |
| industry | 2026-08-13_2026.08.13-长江证券-国内研报-长江证券 | 1518/282 | 4 | 4 | image_region_unreadable(needs_ocr)@1；image_region_unreadable(needs_ocr)@2；table_lines_without_extraction(review_required)@12；table_lines_without_extraction(review_required)@13；table_lines_without_extraction(review_required)@17；table_lines_without_extraction(review_required)@18；table_lines_without_extraction(review_required)@21；table_lines_without_extraction(review_required)@22；table_lines_without_extraction(review_required)@24；table_lines_without_extraction(review_required)@3 |
| industry | 2026-09-06_2026.09.06-华福证券-华福证券-基础化工 | 258/54 | 0 | 0（gen 1） | 无 |
| macro | 2026-09-06_2026.09.06-华创证券-宏观专题-从分化到 | 258/21 | 0 | 0（gen 1） | 无 |
| macro | 2026-09-06_2026.09.06-光大证券-2026年8月美国 | 695/187 | 4 | 4 | table_lines_without_extraction(review_required)@6 |

- 汇总：可发布 **2/6**；阻断 4；阻断缺口 13 处 {"image_region_unreadable": 4, "table_lines_without_extraction": 9}；4305 单元 / 767 切块
- 检索命中：{"营业收入": 0, "景气": 0, "非农": 0, "同比": 4}；取证核验全过=True；被拒句柄=0；审计冲突=[]
- **『三类每类≥2』满足：False** —— 照批准集真实结果：company 0/2、industry 1/2、macro 1/2 可发布 → 『三类每类≥2 份』在现行门 + 现行裁定下不可满足；缺口无处置路径

## 领域×格式矩阵

| 单元格 | 份数 | 已发布 |
|---|---|---|
| company:pdf | 2 | 0 |
| industry:pdf | 2 | 1 |
| macro:pdf | 2 | 1 |

> DOCX/MD 在准入口径下样本数 = 0（相关材料均被裁定 `excluded_from_active`）→ §12.1 的格式门在现行裁定下无法满足（须补研报类料，或 U 明确 v1 不声称覆盖）。

## 被阻断来源的处置口径（§7.3，机读）

- 2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:image_region_unreadable:page:2']（image_region_unreadable@page:2）
- 2026-09-06_2026.09.06-国信证券-光力科技-300480-2：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:image_region_unreadable:page:7']（image_region_unreadable@page:7）
- 2026-08-13_2026.08.13-长江证券-国内研报-长江证券-化工专：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:image_region_unreadable:page:1', 'issue:image_region_unreadable:page:2', 'issue:table_lines_without_extraction:page:12', 'issue:table_lines_without_extraction:page:13', 'issue:table_lines_without_extraction:page:17', 'issue:table_lines_without_extraction:page:18', 'issue:table_lines_without_extraction:page:21', 'issue:table_lines_without_extraction:page:22', 'issue:table_lines_without_extraction:page:24', 'issue:table_lines_without_extraction:page:3']（image_region_unreadable@page:1, image_region_unreadable@page:2, table_lines_without_extraction@page:12, table_lines_without_extraction@page:13, table_lines_without_extraction@page:17, table_lines_without_extraction@page:18, table_lines_without_extraction@page:21, table_lines_without_extraction@page:22, table_lines_without_extraction@page:24, table_lines_without_extraction@page:3）
- 2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:table_lines_without_extraction:page:6']（table_lines_without_extraction@page:6）

处置路径：补 OCR（图像区域）/ 换料 / 转 review_required；**本轮未降级门**。
