# I3-1 最终开发范围（换料 + U 补料）——真实结果

- 生成：2026-09-19T19:11:27+08:00；目标 `postgresql://***@127.0.0.1:543/i2_sandbox_corpus`；守卫 `.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json`（允许路径 15 条，sha256 ef0063240ad1）
- 范围规则：零阻断且非留出（换料，规范口径）+ U 补 DOCX + U 要求接受的 MD；company 类零阻断样本为 0（唯一干净者系留出件）
- **company 缺口**：company 类：3 份公司研报中 1 份零阻断但属留出件（不可用），另 2 份各 1 处 `image_region_unreadable`(needs_ocr/blocking)；规范内**无人工认可入口**（gaps.py 默认表把该代码固定为 blocking）→ company 需 U 决定：补料 / 改实现 / 显式登记未覆盖

## 逐来源

| 领域 | 格式 | 来源 | 单元/切块 | decision | check | publish |
|---|---|---|---|---|---|---|
| macro | pdf | 2026-09-06_2026.09.06-华创证券-宏观专题-从分 | 258/21 | in_scope | 0 | 0（gen 2） |
| industry | pdf | 2026-09-06_2026.09.06-华源证券-环保行业周报- | 45/13 | in_scope | 0 | 0（gen 2） |
| industry | pdf | 2026-09-06_2026.09.06-华福证券-华福证券-基础 | 258/54 | in_scope | 0 | 0（gen 2） |
| industry | pdf | 2026-09-06_2026.09.06-国泰海通-国泰海通证券- | 230/34 | in_scope | 0 | 0（gen 2） |
| industry | pdf | 2026-09-06_2026.09.06-国泰海通-国泰海通证券- | 192/38 | in_scope | 0 | 0（gen 2） |
| industry | pdf | 2026-09-06_2026.09.06-国金证券-地产专题分析报 | 221/24 | in_scope | 0 | 0（gen 2） |
| industry | pdf | 2026-09-06_2026.09.06-国金证券-电力设备与新能 | 322/82 | in_scope | 0 | 0（gen 2） |
| macro | pdf | 2026-09-07_2026.09.07-国盛证券-宏观点评-这次 | 83/10 | in_scope | 0 | 0（gen 2） |
| industry | docx | 9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格 | 44/7 | in_scope | 0 | 0（gen 3） |
| company | md | 仕佳光子_投委会决策报告_20260831.md | 244/72 | in_scope | 0 | 0（gen 1） |
| company | md | 天孚通信_投委会决策报告_20260830.md | 94/20 | in_scope | 0 | 0（gen 1） |

- 汇总：来源 11，可 build 11，**已发布 11**，review_required 0；1991 单元 / 375 切块
- 检索命中：{"营业收入": 1, "景气": 5, "非农": 0, "同比": 5, "光模块": 5, "碳市场": 3}；取证核验全过=True；审计冲突=[]

## 各份决定与取代链

| 来源 | label | decision_id | supersedes | material_type |
|---|---|---|---|---|
| 2026-09-06_2026.09.06-华创证券-宏观专 | pdf | `i3e2e-scope-pdf-43300146` | ['i3e2e-scope-pdf-43300146'] | （不给，沿用机器检出） |
| 2026-09-06_2026.09.06-华源证券-环保行 | pdf | `i3e2e-scope-pdf-523c5d7f` | ['i3e2e-scope-pdf-523c5d7f'] | （不给，沿用机器检出） |
| 2026-09-06_2026.09.06-华福证券-华福证 | pdf | `i3e2e-scope-pdf-f269774b` | ['i3e2e-scope-pdf-f269774b'] | （不给，沿用机器检出） |
| 2026-09-06_2026.09.06-国泰海通-国泰海 | pdf | `i3e2e-scope-pdf-beedf7bb` | ['i3e2e-scope-pdf-beedf7bb'] | （不给，沿用机器检出） |
| 2026-09-06_2026.09.06-国泰海通-国泰海 | pdf | `i3e2e-scope-pdf-30442c75` | ['i3e2e-scope-pdf-30442c75'] | （不给，沿用机器检出） |
| 2026-09-06_2026.09.06-国金证券-地产专 | pdf | `i3e2e-scope-pdf-d5273acf` | ['i3e2e-scope-pdf-d5273acf'] | （不给，沿用机器检出） |
| 2026-09-06_2026.09.06-国金证券-电力设 | pdf | `i3e2e-scope-pdf-bae1ecbe` | ['i3e2e-scope-pdf-bae1ecbe'] | （不给，沿用机器检出） |
| 2026-09-07_2026.09.07-国盛证券-宏观点 | pdf | `i3e2e-scope-pdf-704d63b2` | ['i3e2e-scope-pdf-704d63b2'] | （不给，沿用机器检出） |
| 9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的 | docx | `i3e2e-scope-docx-21b0e21e` | ['i3e2e-scope-docx-21b0e21e'] | （不给，沿用机器检出） |
| 仕佳光子_投委会决策报告_20260831.md | md | `i3e2e-scope-md-46a663e0` | ['i3e2e-scope-md-46a663e0'] | research_report |
| 天孚通信_投委会决策报告_20260830.md | md | `i3e2e-scope-md-e4411890` | ['i3e2e-scope-md-e4411890'] | research_report |
