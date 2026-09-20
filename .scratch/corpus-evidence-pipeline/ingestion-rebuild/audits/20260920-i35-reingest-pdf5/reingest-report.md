# I3-5 阅读序修复重摄入（reader-pdf-5，teardown 重建）

- 生成：2026-09-20T19:35:41+08:00；清单 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-dev-lane/dev-scope-manifest.json`（sha256 8487c51b548e，8 份）
- 读取器：reader-pdf-2 → **reader-pdf-5**（保留原生阅读序 + 表格结构重建；parse_rev 依赖读取器版本，故重解析）
- 路径：teardown 重建沙箱再全量重跑（U 2026-09-20 决策）
- teardown：exit 0（{'step': 'i2s1_teardown', 'dropped': 'corpus schema (CASCADE)', 'database_kept': 'i2_sandbox_corpus', 'residue': 0}）
- apply：exit 0（tables None / indexes None）
- 守卫：`.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json`（3faac9e01fc3）；`CORPUS_DEV_LANE=1`；沙箱 `corpus-db 容器（127.0.0.1:543）i2_sandbox_corpus，teardown 重建`

## 逐来源

| 领域 | 格式 | 来源 | provenance | 单元/切块 | build | parse_rev | check | publish | 阻断缺口 |
|---|---|---|---|---|---|---|---|---|---|
| company | pdf | 2026-08-16_2026.08.16-华创证券 | approved_set | 727/25 | 2fc48247fa47 | 9f88e481afb3 | 4 | 4（gen None） | image_region_unreadable@issue:image_region_unreadable:page:2 |
| company | pdf | 2026-09-06_2026.09.06-国信证券 | approved_set | 786/197 | f3221a1e91e2 | 914d405841cd | 4 | 4（gen None） | image_region_unreadable@issue:image_region_unreadable:page:7 |
| industry | pdf | 2026-08-13_2026.08.13-长江证券 | approved_set | 1255/284 | f467708311ed | 6e686a5e4648 | 4 | 4（gen None） | image_region_unreadable@issue:image_region_unreadable:page:1；image_region_unreadable@issue:image_region_unreadable:page:2；table_lines_without_extraction@issue:table_lines_without_extraction:page:12；table_lines_without_extraction@issue:table_lines_without_extraction:page:13；table_lines_without_extraction@issue:table_lines_without_extraction:page:17；table_lines_without_extraction@issue:table_lines_without_extraction:page:18；table_lines_without_extraction@issue:table_lines_without_extraction:page:21；table_lines_without_extraction@issue:table_lines_without_extraction:page:22；table_lines_without_extraction@issue:table_lines_without_extraction:page:24；table_lines_without_extraction@issue:table_lines_without_extraction:page:3 |
| industry | pdf | 2026-09-06_2026.09.06-华福证券 | approved_set | 229/54 | 3b25c64babf7 | 031071d9101d | 0 | 0（gen 1） | 无 |
| macro | pdf | 2026-09-06_2026.09.06-华创证券 | approved_set | 243/21 | 2a314543ff30 | 71c110b11376 | 0 | 0（gen 1） | 无 |
| macro | pdf | 2026-09-06_2026.09.06-光大证券 | approved_set | 512/187 | 9af73f907a82 | ee7f6276b7db | 4 | 4（gen None） | table_lines_without_extraction@issue:table_lines_without_extraction:page:6 |
| company | md | 工业富联_投委会决策报告_20260829.md | dev_lane | 91/20 | c01bab5926fc | 28fd6541c91a | 0 | 0（gen 1） | 无 |
| industry | docx | 9月8日 光模块技术演进与供应链重构：从1.6T到3 | dev_lane | 44/7 | 010e9a900053 | 747860affaab | 0 | 0（gen 1） | 无 |

- 汇总：built **8/8**；published 4；blocked 4；active(new build) 4
- parse_rev：["031071d9101d6d24687947e7b6571cb578b3e33188290e4b01d4bfa799cc1a0a", "28fd6541c91aad284905e19175272b3fb3133293bd5417675ae9b57f732fdfcf", "6e686a5e46481b140b624f8e977ac9a535ad09aa63945d9adf646959c370d951", "71c110b11376784837feb080652858926daaed91ab5a89928bd28fe3a762843a", "747860affaab837c29c5f6386cf76b6d0225c03a1490680a277752f03a15524a", "914d405841cd25b2589fd6c884b15216f61dcce5f62d69d4b6a28075623b601d", "9f88e481afb3feeb26458fcadcf039213bc2226db29d1ba10182f35a4aa62188", "ee7f6276b7db0a8e03342a792f2daffff6a5985c741be43510f90d0f5060e1b7"]；**全部新 build 成为 active：False**
- 说明：teardown 重建后代码全部重解析；新 build 因 parse_rev 变更产生新 build_id。
