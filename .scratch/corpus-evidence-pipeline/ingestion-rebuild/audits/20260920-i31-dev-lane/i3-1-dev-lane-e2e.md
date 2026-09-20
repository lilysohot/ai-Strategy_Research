# I3-1 第二轮 E2E —— dev lane 纳入 MD / DOCX（U 2026-09-20 裁决）

- 生成：2026-09-20T09:39:32+08:00；清单 `dev-scope-manifest.json`（sha256 8487c51b548e，8 份）
- dev lane 政策 `admission-policy-dev.json`（v2-dev-20260920，scope=dev，lane=i3-1-dev-lane-md-docx，production_in_scope_unchanged=True）
- 取样自检（带 `--dev-lane`）：**PASS**（8/8，dev lane 授权 2 份，格式 ['docx', 'md', 'pdf']）
- fail-closed 反例（不给 `--dev-lane`）：**FAIL**（fail 2，裁定冲突 2，格式仅 ['pdf']）
- 环境：干净沙箱（teardown residue=0 后重建 corpus schema）；守卫 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json`（3faac9e01fc3）；`CORPUS_DEV_LANE=1`

## 逐来源（缺口如实登记）

| 领域 | 格式 | 来源 | provenance | 材料类型 | 单元/切块 | check | publish | 阻断缺口 |
|---|---|---|---|---|---|---|---|---|
| company | pdf | 2026-08-16_2026.08.16-华创证券-欧阳予-田 | approved_set | None | 778/25 | 4 | 4 | image_region_unreadable(needs_ocr)@2 |
| company | pdf | 2026-09-06_2026.09.06-国信证券-光力科技- | approved_set | None | 798/198 | 4 | 4 | image_region_unreadable(needs_ocr)@7 |
| industry | pdf | 2026-08-13_2026.08.13-长江证券-国内研报- | approved_set | None | 1518/282 | 4 | 4 | image_region_unreadable(needs_ocr)@1；image_region_unreadable(needs_ocr)@2；table_lines_without_extraction(review_required)@12；table_lines_without_extraction(review_required)@13；table_lines_without_extraction(review_required)@17；table_lines_without_extraction(review_required)@18；table_lines_without_extraction(review_required)@21；table_lines_without_extraction(review_required)@22；table_lines_without_extraction(review_required)@24；table_lines_without_extraction(review_required)@3 |
| industry | pdf | 2026-09-06_2026.09.06-华福证券-华福证券- | approved_set | None | 258/54 | 0 | 0（gen 1） | 无 |
| macro | pdf | 2026-09-06_2026.09.06-华创证券-宏观专题- | approved_set | None | 258/21 | 0 | 0（gen 1） | 无 |
| macro | pdf | 2026-09-06_2026.09.06-光大证券-2026年 | approved_set | None | 695/187 | 4 | 4 | table_lines_without_extraction(review_required)@6 |
| company | md | 工业富联_投委会决策报告_20260829.md | dev_lane | None | 91/20 | 0 | 0（gen 1） | 无 |
| industry | docx | 9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径 | dev_lane | None | 44/7 | 0 | 0（gen 1） | 无 |

- 汇总：可发布 **4/8**；阻断 4；阻断缺口 13 处 {"image_region_unreadable": 4, "table_lines_without_extraction": 9}；4440 单元 / 794 切块
- 检索命中：{"营业收入": 0, "景气": 1, "非农": 0, "同比": 5, "工业富联": 1, "光模块": 5}；取证核验全过=True；被拒句柄=0；审计冲突=[]
- 逐类可发布：{"company": {"total": 3, "published": 1}, "industry": {"total": 3, "published": 2}, "macro": {"total": 2, "published": 1}}；**『每类≥2』满足：False**

## 领域×格式矩阵

| 单元格 | 份数 | 已发布 |
|---|---|---|
| company:md | 1 | 1 |
| company:pdf | 2 | 0 |
| industry:docx | 1 | 1 |
| industry:pdf | 2 | 1 |
| macro:pdf | 2 | 1 |

## 格式覆盖（架构 §12.1）

| 格式 | 份数 | 已发布 | 来源 |
|---|---|---|---|
| docx | 1 | 1 | 9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx |
| md | 1 | 1 | 工业富联_投委会决策报告_20260829.md |
| pdf | 6 | 2 | 2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司；2026-09-06_2026.09.06-国信证券-光力科技-300480-2；2026-08-13_2026.08.13-长江证券-国内研报-长江证券-化工专；2026-09-06_2026.09.06-华福证券-华福证券-基础化工行业新材；2026-09-06_2026.09.06-华创证券-宏观专题-从分化到收敛-可；2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据 |

- 声称格式 ['pdf', 'docx', 'md']；有可发布样本的格式 **['docx', 'md', 'pdf']**；**§12.1 格式门满足：True**

> dev lane 口径：两份新增来源的材料类型如实记为 `internal_committee_report` / `internal_unattributed`（**不得伪写为研报**）；其 in_scope 仅在 `scope=dev` 政策 + `CORPUS_DEV_LANE=1` 下成立，生产判定（v1 政策）不变。

## 被阻断来源的处置口径（§7.3，机读）

- 2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:image_region_unreadable:page:2']（image_region_unreadable@page:2）
- 2026-09-06_2026.09.06-国信证券-光力科技-300480-2：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:image_region_unreadable:page:7']（image_region_unreadable@page:7）
- 2026-08-13_2026.08.13-长江证券-国内研报-长江证券-化工专：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:image_region_unreadable:page:1', 'issue:image_region_unreadable:page:2', 'issue:table_lines_without_extraction:page:12', 'issue:table_lines_without_extraction:page:13', 'issue:table_lines_without_extraction:page:17', 'issue:table_lines_without_extraction:page:18', 'issue:table_lines_without_extraction:page:21', 'issue:table_lines_without_extraction:page:22', 'issue:table_lines_without_extraction:page:24', 'issue:table_lines_without_extraction:page:3']（image_region_unreadable@page:1, image_region_unreadable@page:2, table_lines_without_extraction@page:12, table_lines_without_extraction@page:13, table_lines_without_extraction@page:17, table_lines_without_extraction@page:18, table_lines_without_extraction@page:21, table_lines_without_extraction@page:22, table_lines_without_extraction@page:24, table_lines_without_extraction@page:3）
- 2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:table_lines_without_extraction:page:6']（table_lines_without_extraction@page:6）

处置路径：补 OCR（图像区域）/ 换料 / 转 review_required；**本轮未降级门**。
