# E6 留出材料人工缺口复核包

> Evidence only. No decision is recorded and no human-gap-review is written; the closed form at the end of each section is for a human reviewer to fill in.

## 范围

- 留出材料：**12** 份，其中 **3** 份已过发布门，**9** 份因真实读取质量缺口被阻断。
- 被阻断目标：**38** 项，全部表现为 `source_not_offered`（非模型、检索或分页错误）。
- 缺口与页面来自冻结的门禁结果 `e6-holdout-build.json`；页面证据只读自隔离库 `e6_holdout_corpus`（只读事务），未重跑构建、未写入任何裁决。

## 复核方式

逐份判定，三选一并在「裁决」栏签名：

- `acknowledged`：承认缺口，按现状发布（需写明为何该缺口不影响目标证据）；
- `re-extract`：需重新提取/更换解析，该材料暂不放行；
- `reject`：材料或目标不可用。

完成后重跑隔离构建与 51 项数据送达验证；在达到 51/51 之前 E6 与端到端总任务保持未关闭。

## 1. `holdout-industry-003`（industry）

- 来源文件：`2026-09-06_2026.09.06-光大证券-金属行业周期品高频数据周报-焦煤期货收盘价周内下跌3-64-46877bac.pdf`
- `source_id`：`c1ddcd8aecb80e39c555459e3ea007db1419ed9f3b844724ac90fc65bda8a885`
- `build_id`：`907957c865f6b551f70e6254a270a29b2baab31adf98d24c3250d964278432db`
- 修订：parse_rev=d4cbd3c1be1735dca6b87776f05af831e50286304d91f23c427094fa56743ea4, clean_rev=0fea86694f5d68dda9568b38fc81a7f89093706c3058105ff9693400db016853, chunk_rev=c8a41ddc5ae48e11379a64733867b0c4885b9f9f4b2552541e115e6ac26b826f
- 规模：units 1092 / chunks 86
- 门禁结论：`blocked_by_publish_gate`
- 门禁原因：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:table_lines_without_extraction:page:11', 'issue:table_lines_without_extraction:page:16', 'issue:table_lines_without_extraction:page:18', 'issue:table_lines_without_extraction:page:19', 'issue:table_lines_without_extraction:page:3', 'issue:table_lines_without_extraction:page:8']（table_lines_without_extraction@page:11, table_lines_without_extraction@page:16, table_lines_without_extraction@page:18, table_lines_without_extraction@page:19, table_lines_without_extraction@page:3, table_lines_without_extraction@page:8）

### 缺口页

| 页 | 缺口类型 | 该页已提取单元 | 单元类型分布 | table 单元 |
|---:|---|---:|---|---:|
| 1 | `image_region_small` | 44 | heading 6, paragraph 34, table_row 4 | 0 |
| 2 | `image_region_small` | 85 | heading 3, paragraph 5, table_row 77 | 0 |
| 3 | `image_region_small`, `table_lines_without_extraction` | 56 | heading 5, paragraph 51 | 0 |
| 4 | `image_region_small` | 41 | heading 5, paragraph 33, table_row 3 | 0 |
| 5 | `image_region_small` | 68 | heading 2, paragraph 65, table_row 1 | 0 |
| 6 | `image_region_small` | 47 | heading 2, paragraph 40, table_row 5 | 0 |
| 7 | `image_region_small` | 55 | heading 2, paragraph 49, table_row 4 | 0 |
| 8 | `image_region_small`, `table_lines_without_extraction` | 49 | heading 2, paragraph 47 | 0 |
| 9 | `image_region_small` | 63 | heading 5, paragraph 57, table_row 1 | 0 |
| 10 | `image_region_small` | 86 | heading 2, paragraph 82, table_row 2 | 0 |
| 11 | `image_region_small`, `table_lines_without_extraction` | 45 | heading 2, paragraph 43 | 0 |
| 12 | `image_region_small` | 54 | heading 8, paragraph 42, table_row 4 | 0 |
| 13 | `image_region_small` | 29 | heading 3, paragraph 24, table_row 2 | 0 |
| 14 | `image_region_small` | 56 | heading 2, paragraph 51, table_row 3 | 0 |
| 15 | `image_region_small` | 31 | heading 2, paragraph 27, table_row 2 | 0 |
| 16 | `image_region_small`, `table_lines_without_extraction` | 42 | heading 4, paragraph 38 | 0 |
| 17 | `image_region_small` | 62 | heading 2, paragraph 56, table_row 4 | 0 |
| 18 | `image_region_small`, `table_lines_without_extraction` | 38 | heading 4, paragraph 34 | 0 |
| 19 | `image_region_small`, `table_lines_without_extraction` | 56 | heading 4, paragraph 52 | 0 |
| 20 | `image_region_small` | 33 | heading 2, paragraph 30, table_row 1 | 0 |
| 21 | `image_region_small` | 7 | heading 1, paragraph 6 | 0 |
| 22 | `image_region_small` | 45 | heading 8, paragraph 22, table_row 15 | 0 |

### 缺口页已提取文本样例

**第 1 页**

- `paragraph`/kept reasons=['multi_column_order_flagged'] （12 字）：敬请参阅最后一页特别声明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （3 字）：-1-
- `paragraph`/kept reasons=['multi_column_order_flagged'] （6 字）：证券研究报告
- `paragraph`/kept reasons=['multi_column_order_flagged'] （12 字）：2026 年9 月6 日

**第 2 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （3 字）：-2-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 3 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （3 字）：-3-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 4 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （3 字）：-4-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 5 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （3 字）：-5-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 6 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （3 字）：-6-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 7 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （3 字）：-7-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 8 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （3 字）：-8-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 9 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （3 字）：-9-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 10 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （4 字）：-10-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 11 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （4 字）：-11-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 12 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （4 字）：-12-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 13 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （4 字）：-13-
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['multi_column_order_flagged', 'heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 14 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （4 字）：-14-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 15 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （4 字）：-15-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 16 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （4 字）：-16-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 17 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （4 字）：-17-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 18 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （4 字）：-18-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 19 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （4 字）：-19-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 20 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （4 字）：-20-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 21 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （4 字）：-21-
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：钢铁/有色/煤炭

**第 22 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （13 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （4 字）：-22-
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `heading`/kept reasons=['heading_by_font_size'] （9 字）：行业及公司评级体系

### 被本材料阻断的目标（4）

| target_id | role | 所需引文 | 依赖 | 问题 |
|---|---|---|---|---|
| `c1ddcd8a-coalprice` | required | （3）动力煤价格为 967 元/吨，环比+9.14%；（4）国内主要地区主焦煤平均价格为 2224 元/吨，环比上周+9.34%。 | header_refs, row_labels, footnotes | 研报中动力煤现货价格和国内主要地区主焦煤平均价格本周分别是多少元/吨，环比涨了多少？ |
| `c1ddcd8a-summarytable` | supplementary | 螺纹钢 元/吨 3240 0.9% 4.2% -2.4% -0.6% 6000 | footnotes | 研报的量价利汇总表中，螺纹钢在2026-9-4的价格、7日涨幅、30日涨幅和年内涨幅分别是多少？ |
| `c1ddcd8a-realestate` | supplementary | 地产竣工链条：钛白粉、玻璃价格处于低位水平。 本周钛白粉、玻璃的价格环比分别-0.36%、-0.97%，平板玻璃本周开工率 67.19%。 | header_refs, row_labels, footnotes | 研报中说钛白粉、玻璃价格处在低位，那么本周它们价格环比分别变化多少，平板玻璃开工率又是多少？ |
| `c1ddcd8a-invest` | supplementary | 当前钢铁行业供需两弱，普钢板块相对 PB 处于较低水平，后续板块表现取决于具体减产力度，推荐估值处于低位的行业龙头宝钢股份；7 月原煤产量 3.43 亿吨，同比-10.10%，同比降幅进一步扩大，带动煤炭价格持续修复，推荐中国神华、中煤能源、陕西煤业、山西焦煤、潞安环能。 | header_refs, row_labels, footnotes | 研报的投资建议中对钢铁和煤炭行业是怎么看的，提到了2026年7月原煤产量是多少、同比变化多少，并推荐了哪些公司？ |

### 裁决（待人工填写；本包不代签）

- [ ] `acknowledged`　- [ ] `re-extract`　- [ ] `reject`
- reviewer：__________　日期：__________
- 理由：______________________________________________

## 2. `holdout-industry-004`（industry）

- 来源文件：`2026-09-05_2026.09.05-中信建投-行业数据周报9月第1期-市场普遍下跌-机构低配板块表现居前-a6a30359.pdf`
- `source_id`：`b7e932c80e88d00931374d29ab8a786e4dc42cd194309f126301f58192e5d160`
- `build_id`：`590bb1199568dd8a78083d2b6dc856c7b3b9cff32a2b8a811c34a3820ea23814`
- 修订：parse_rev=8a07d72ef928f9027c8fbc4072e2403ae4521599d6b7417de9547d11564bf171, clean_rev=0fea86694f5d68dda9568b38fc81a7f89093706c3058105ff9693400db016853, chunk_rev=c8a41ddc5ae48e11379a64733867b0c4885b9f9f4b2552541e115e6ac26b826f
- 规模：units 1153 / chunks 154
- 门禁结论：`blocked_by_publish_gate`
- 门禁原因：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:image_region_unreadable:page:1', 'issue:image_region_unreadable:page:10', 'issue:image_region_unreadable:page:11', 'issue:image_region_unreadable:page:12', 'issue:image_region_unreadable:page:13', 'issue:image_region_unreadable:page:14', 'issue:image_region_unreadable:page:15', 'issue:image_region_unreadable:page:16', 'issue:image_region_unreadable:page:17', 'issue:image_region_unreadable:page:18', 'issue:image_region_unreadable:page:19', 'issue:image_region_unreadable:page:2', 'issue:image_region_unreadable:page:20', 'issue:image_region_unreadable:page:21', 'issue:image_region_unreadable:page:22', 'issue:image_region_unreadable:page:23', 'issue:image_region_unreadable:page:24', 'issue:image_region_unreadable:page:25', 'issue:image_region_unreadable:page:26', 'issue:image_region_unreadable:page:27', 'issue:image_region_unreadable:page:3', 'issue:image_region_unreadable:page:4', 'issue:image_region_unreadable:page:5', 'issue:image_region_unreadable:page:6', 'issue:image_region_unreadable:page:7', 'issue:image_region_unreadable:page:8', 'issue:image_region_unreadable:page:9', 'issue:table_lines_without_extraction:page:13', 'issue:table_lines_without_extraction:page:16', 'issue:table_lines_without_extraction:page:17', 'issue:table_lines_without_extraction:page:18', 'issue:table_lines_without_extraction:page:19', 'issue:table_lines_without_extraction:page:4', 'issue:table_lines_without_extraction:page:5', 'issue:table_lines_without_extraction:page:6']（image_region_unreadable@page:1, image_region_unreadable@page:10, image_region_unreadable@page:11, image_region_unreadable@page:12, image_region_unreadable@page:13, image_region_unreadable@page:14, image_region_unreadable@page:15, image_region_unreadable@page:16, image_region_unreadable@page:17, image_region_unreadable@page:18, image_region_unreadable@page:19, image_region_unreadable@page:2, image_region_unreadable@page:20, image_region_unreadable@page:21, image_region_unreadable@page:22, image_region_unreadable@page:23, image_region_unreadable@page:24, image_region_unreadable@page:25, image_region_unreadable@page:26, image_region_unreadable@page:27, image_region_unreadable@page:3, image_region_unreadable@page:4, image_region_unreadable@page:5, image_region_unreadable@page:6, image_region_unreadable@page:7, image_region_unreadable@page:8, image_region_unreadable@page:9, table_lines_without_extraction@page:13, table_lines_without_extraction@page:16, table_lines_without_extraction@page:17, table_lines_without_extraction@page:18, table_lines_without_extraction@page:19, table_lines_without_extraction@page:4, table_lines_without_extraction@page:5, table_lines_without_extraction@page:6）

### 缺口页

| 页 | 缺口类型 | 该页已提取单元 | 单元类型分布 | table 单元 |
|---:|---|---:|---|---:|
| 1 | `image_region_small`, `image_region_unreadable` | 7 | heading 3, paragraph 4 | 0 |
| 2 | `image_region_small`, `image_region_unreadable` | 19 | heading 1, paragraph 18 | 0 |
| 3 | `image_region_small`, `image_region_unreadable` | 24 | heading 1, paragraph 23 | 0 |
| 4 | `image_region_small`, `image_region_unreadable`, `table_lines_without_extraction` | 66 | heading 2, paragraph 64 | 0 |
| 5 | `image_region_small`, `image_region_unreadable`, `table_lines_without_extraction` | 23 | heading 3, paragraph 20 | 0 |
| 6 | `image_region_small`, `image_region_unreadable`, `table_lines_without_extraction` | 52 | heading 3, paragraph 49 | 0 |
| 7 | `image_region_small`, `image_region_unreadable` | 53 | heading 4, paragraph 4, table_row 45 | 0 |
| 8 | `image_region_small`, `image_region_unreadable` | 55 | heading 3, paragraph 4, table_row 48 | 0 |
| 9 | `image_region_small`, `image_region_unreadable` | 46 | heading 3, paragraph 4, table_row 39 | 0 |
| 10 | `image_region_small`, `image_region_unreadable` | 43 | heading 4, paragraph 1, table_row 38 | 0 |
| 11 | `image_region_small`, `image_region_unreadable` | 46 | heading 4, paragraph 4, table_row 38 | 0 |
| 12 | `image_region_small`, `image_region_unreadable` | 46 | heading 5, paragraph 3, table_row 38 | 0 |
| 13 | `image_region_small`, `image_region_unreadable`, `table_lines_without_extraction` | 88 | heading 3, paragraph 85 | 0 |
| 14 | `image_region_small`, `image_region_unreadable` | 39 | heading 4, paragraph 3, table_row 32 | 0 |
| 15 | `image_region_small`, `image_region_unreadable` | 40 | heading 4, paragraph 3, table_row 33 | 0 |
| 16 | `image_region_small`, `image_region_unreadable`, `table_lines_without_extraction` | 39 | heading 1, paragraph 38 | 0 |
| 17 | `image_region_small`, `image_region_unreadable`, `table_lines_without_extraction` | 40 | heading 1, paragraph 39 | 0 |
| 18 | `image_region_small`, `image_region_unreadable`, `table_lines_without_extraction` | 80 | heading 3, paragraph 77 | 0 |
| 19 | `image_region_small`, `image_region_unreadable`, `table_lines_without_extraction` | 81 | heading 4, paragraph 77 | 0 |
| 20 | `image_region_small`, `image_region_unreadable` | 47 | heading 3, paragraph 4, table_row 40 | 0 |
| 21 | `image_region_small`, `image_region_unreadable` | 26 | heading 5, paragraph 21 | 0 |
| 22 | `image_region_small`, `image_region_unreadable` | 41 | heading 4, paragraph 4, table_row 33 | 0 |
| 23 | `image_region_small`, `image_region_unreadable` | 42 | heading 4, paragraph 4, table_row 34 | 0 |
| 24 | `image_region_small`, `image_region_unreadable` | 67 | heading 3, paragraph 64 | 0 |
| 25 | `image_region_small`, `image_region_unreadable` | 15 | heading 1, paragraph 14 | 0 |
| 26 | `image_region_small`, `image_region_unreadable` | 14 | heading 3, paragraph 1, table_row 10 | 0 |
| 27 | `image_region_small`, `image_region_unreadable` | 14 | paragraph 11, table_row 3 | 0 |

### 缺口页已提取文本样例

**第 1 页**

- `heading`/kept reasons=['heading_by_font_size'] （17 字）：市场普遍下跌，机构低配板块表现居前
- `heading`/kept reasons=['heading_by_font_size'] （11 字）：证券研究报告策略周报
- `paragraph`/kept （107 字）：本报告由中信建投证券股份有限公司在中华人民共和国（仅为本报告目的，不包括香港、澳门、台湾）提供。在遵守适用的法律法规情况下，本报告亦可能由中信建投（国际）证券有限公司在香港提供。请务必阅读正文之后的免责条款和声明。
- `paragraph`/kept （50 字）：分析师：夏凡捷 xiafanjie@csc.com.cn SAC 编号：S1440521120005

**第 2 页**

- `heading`/kept reasons=['heading_by_font_size'] （4 字）：内容摘要
- `paragraph`/kept （46 字）：风险提示：数据统计存在误差风险；海内外经济波动风险；市场流动性风险；海外地缘政治冲突加剧风险
- `paragraph`/kept （200 字）：核心观点：本周A股主要宽基指数普遍下跌，市场结构延续再平衡，机构低配板块表现居前。基本面方面，盈利增速预测调整居前行业为电子、环保、非银金融、煤炭和计算机；产业景气方面，航运指数继续走强，能源化工表现强势，中游材料价格分化，存储芯片价格延续上涨；估值方面，部分TMT、消费和金融板块估值修复居前。资金方面，机械设备、基础化工、建筑材料融资净流入较多；交易方面，TMT板块热度持续回落，制造与金融板块热
- `paragraph`/kept （1 字）：

**第 3 页**

- `heading`/kept reasons=['heading_by_font_size'] （4 字）：重要新闻
- `paragraph`/kept （1 字）：3
- `paragraph`/kept （16 字）：资料来源：Choice，中信建投
- `paragraph`/kept （5 字）：宏观基本面

**第 4 页**

- `heading`/kept reasons=['heading_by_font_size'] （12 字）：本周A股主要宽基指数表现
- `paragraph`/kept （1 字）：4
- `heading`/kept reasons=['heading_by_font_size'] （54 字）：本周主要宽基指数普遍下跌，上证综指、东财全A分别下跌0.56%、1.20%，沪深300下跌1.33%；创业
- `paragraph`/kept （87 字）：板指下跌4.03%，科创50下跌5.10%；大盘方面，上证50微涨0.02%；中小盘方面，中证500下跌 3.07%、中证1000下跌2.56%、中证2000下跌0.91%。

**第 5 页**

- `heading`/kept reasons=['heading_by_font_size'] （4 字）：融资融券
- `paragraph`/kept （1 字）：5
- `heading`/kept reasons=['heading_by_font_size'] （53 字）：截至本周四，A股两融余额26275.15亿元，占A股流通市值2.58%，占比较上周四下降0.02pct。
- `heading`/kept reasons=['heading_by_font_size'] （9 字）：图表：融资融券规模

**第 6 页**

- `paragraph`/kept （1 字）：6
- `heading`/kept reasons=['heading_by_font_size'] （10 字）：本周A股行业涨跌情况
- `heading`/kept reasons=['heading_by_font_size'] （51 字）：本周行业多数下跌，传媒、银行和农林牧渔涨幅居前，分别上涨6.0%、4.0%、3.3%，机构低配板块表
- `heading`/kept reasons=['heading_by_font_size'] （40 字）：现靠前；电子、有色金属和建筑材料表现较弱，分别下跌5.4%、5.0%、4.3%。

**第 7 页**

- `paragraph`/kept （1 字）：7
- `heading`/kept reasons=['heading_by_font_size'] （9 字）：盈利预测—一级行业
- `heading`/kept reasons=['heading_by_font_size'] （38 字）：本周盈利增速预测调整居前的五个行业为：电子、环保、非银金融、煤炭和计算机。
- `heading`/kept reasons=['heading_by_font_size'] （40 字）：本周盈利增速预期加速增长居前的五个行业为：电子、环保、计算机、国防军工和煤炭。

**第 8 页**

- `paragraph`/kept （1 字）：8
- `heading`/kept reasons=['heading_by_font_size'] （9 字）：盈利预测—二级行业
- `heading`/kept reasons=['heading_by_font_size'] （15 字）：图表：二级行业盈利预测变化情况
- `heading`/kept reasons=['heading_by_font_size'] （44 字）：本周盈利增速预期调整居前的五个行业为：光伏设备、半导体、航运港口、航海装备和能源金属。

**第 9 页**

- `paragraph`/kept （1 字）：9
- `heading`/kept reasons=['heading_by_font_size'] （9 字）：盈利预测—二级行业
- `heading`/kept reasons=['heading_by_font_size'] （45 字）：本周盈利增速预期加速增长居前五的行业为：半导体、能源金属、航运港口、航海装备和光伏设备。
- `heading`/kept reasons=['heading_by_font_size'] （15 字）：图表：二级行业盈利预测变化情况

**第 10 页**

- `table_row`/kept reasons=['tbl[0]'] （2 字）：10
- `table_row`/kept reasons=['tbl[0]'] （16 字）：资料来源：Choice，中信建投
- `table_row`/kept reasons=['tbl[0]'] （34 字）：名称单位 数值周涨跌幅 近1月涨跌幅 近一季度涨跌幅 年初以来涨跌幅
- `table_row`/kept reasons=['tbl[0]'] （38 字）：焦煤期货价元/吨 1666.0 2.3% -3.6% 30.1% 49.4%

**第 11 页**

- `paragraph`/kept （2 字）：11
- `heading`/kept reasons=['heading_by_font_size'] （8 字）：产业高频景气跟踪
- `heading`/kept reasons=['heading_by_font_size'] （47 字）：本周市场交易情绪有所降温，两融交易额占A股交易额比重下降6.6%；中游材料价格表现分化，玻璃
- `heading`/kept reasons=['heading_by_font_size'] （52 字）：期货上涨5.5%，螺纹钢上涨1.7%，而碳酸锂、氢氧化锂下跌11.1%、0.8%；存储芯片价格延续上涨。

**第 12 页**

- `paragraph`/kept （2 字）：12
- `heading`/kept reasons=['heading_by_font_size'] （7 字）：估值—一级行业
- `heading`/kept reasons=['heading_by_font_size'] （1 字）：
- `heading`/kept reasons=['heading_by_font_size'] （51 字）：估值表现分化，部分TMT、消费和金融板块表现活跃，传媒、银行和农林牧渔涨幅领先；从估值分位数角度看，煤

**第 13 页**

- `heading`/kept reasons=['heading_by_font_size'] （7 字）：估值—一级行业
- `paragraph`/kept （2 字）：13
- `heading`/kept reasons=['heading_by_font_size'] （43 字）：从PE-G看，商贸零售、综合、电子、建筑材料等行业盈利增速较高，且PE估值相对偏低。
- `heading`/kept reasons=['heading_by_font_size'] （40 字）：从PB-ROE看，非银金融、银行、石油石化、有色金属等行业盈利能力相对被低估。

**第 14 页**

- `paragraph`/kept （2 字）：14
- `heading`/kept reasons=['heading_by_font_size'] （7 字）：估值—二级行业
- `heading`/kept reasons=['heading_by_font_size'] （46 字）：本周TMT整体分化，游戏估值明显修复，电子化学品、元件高位回落；周期板块同样表现分化，航运
- `heading`/kept reasons=['heading_by_font_size'] （45 字）：港口、铁路公路涨幅居前，能源金属、小金属回调，玻璃玻纤、航运港口、煤炭开采估值处相对高位。

**第 15 页**

- `paragraph`/kept （2 字）：15
- `heading`/kept reasons=['heading_by_font_size'] （7 字）：估值—二级行业
- `heading`/kept reasons=['heading_by_font_size'] （45 字）：制造板块中航海装备、航空装备估值明显修复，光伏设备、电池调整幅度较大；消费板块中养殖业、
- `heading`/kept reasons=['heading_by_font_size'] （45 字）：互联网电商估值修复，医疗服务、生物制品调整居前，农产品加工估值仍处高位；金融板块普遍修复。

**第 16 页**

- `heading`/kept reasons=['heading_by_font_size'] （9 字）：融资融券—一级行业
- `paragraph`/kept （2 字）：16
- `paragraph`/kept （54 字）：截至周五，两融资金余额居前的行业为电子、非银金融、电力设备、医药生物和有色金属。图表：一级行业两融资金余额
- `paragraph`/kept （44 字）：资料来源：Choice，中信建投 0.0 1.0 2.0 3.0 4.0 5.0 6.0

**第 17 页**

- `heading`/kept reasons=['heading_by_font_size'] （9 字）：融资融券—一级行业
- `paragraph`/kept （73 字）：17 本周（2026/8/31-2026/9/4），融资净流入较多的行业为机械设备、基础化工、建筑材料；融资净流出的行业为电子、通信和医药生物。
- `paragraph`/noise reasons=['footer_repeated_geometric'] （16 字）：资料来源：Choice，中信建投
- `paragraph`/kept （13 字）：图表：一级行业两融资金流向

**第 18 页**

- `heading`/kept reasons=['heading_by_font_size'] （9 字）：融资融券—二级行业
- `paragraph`/kept （2 字）：18
- `heading`/kept reasons=['heading_by_font_size'] （38 字）：截至周五，两融资金余额居前的行业为半导体、证券、保险、工业金属和通信设备。
- `paragraph`/noise reasons=['footer_repeated_geometric'] （16 字）：资料来源：Choice，中信建投

**第 19 页**

- `heading`/kept reasons=['heading_by_font_size'] （9 字）：融资融券—二级行业
- `paragraph`/kept （2 字）：19
- `heading`/kept reasons=['heading_by_font_size'] （55 字）：本周（2026/8/31-2026/9/4），融资净流入较多的行业为电池、玻璃玻纤和房地产开发；融资净流出较
- `heading`/kept reasons=['heading_by_font_size'] （17 字）：多的行业为半导体、通信设备和证券。

**第 20 页**

- `paragraph`/kept （2 字）：20
- `heading`/kept reasons=['heading_by_font_size'] （9 字）：交易热度—一级行业
- `heading`/kept reasons=['heading_by_font_size'] （45 字）：农林牧渔、传媒、房地产交易热度居前，近一年相对换手率分别达1.71、1.25和1.24。
- `heading`/kept reasons=['heading_by_font_size'] （11 字）：图表：一级行业交易热度

**第 21 页**

- `heading`/kept reasons=['heading_by_font_size'] （11 字）：交易热度—行业风格轮动
- `paragraph`/kept （2 字）：21
- `heading`/kept reasons=['heading_by_font_size'] （47 字）：市场结构延续再平衡，板块间分化收敛。TMT板块交易热度持续回落，成交金额占比回落至40%，中
- `heading`/kept reasons=['heading_by_font_size'] （31 字）：游制造与大金融板块热度明显上升，上游周期、大消费板块热度下降。

**第 22 页**

- `paragraph`/kept （2 字）：22
- `heading`/kept reasons=['heading_by_font_size'] （9 字）：交易热度—二级行业
- `heading`/kept reasons=['heading_by_font_size'] （50 字）：换手率方面，消费热度维持高位，农产品加工、化妆品相对换手率分别达2.34、1.42；金融地产普遍升
- `heading`/kept reasons=['heading_by_font_size'] （45 字）：温，房地产开发、大型国有行居前；制造板块中航空装备、航海装备热度明显升温，TMT热度分化。

**第 23 页**

- `paragraph`/kept （2 字）：23
- `heading`/kept reasons=['heading_by_font_size'] （9 字）：交易热度—二级行业
- `heading`/kept reasons=['heading_by_font_size'] （50 字）：成交金额占比方面，消费热度分化，农产品加工、调味发酵品相对交易集中度达3.08、1.70；金融地产
- `heading`/kept reasons=['heading_by_font_size'] （46 字）：普遍上升；制造板块表现分化，航海装备、航空装备提升明显；TMT板块中游戏、广告营销提升明显。

**第 24 页**

- `paragraph`/kept （2 字）：24
- `heading`/kept reasons=['heading_by_font_size'] （9 字）：交易热度—二级行业
- `heading`/kept reasons=['heading_by_font_size'] （42 字）：本周换手率与成交金额占比百分位均居前的行业有贵金属、农产品加工、玻璃玻纤、元件等。
- `heading`/kept reasons=['heading_by_font_size'] （23 字）：图表：二级行业换手率与成交金额占比的历史分位数

**第 25 页**

- `heading`/kept reasons=['heading_by_font_size'] （4 字）：风险提示
- `paragraph`/kept （2 字）：25
- `paragraph`/kept （1 字）：
- `paragraph`/kept （58 字）：1）数据统计存在误差风险：报告相关数据主要来源于Choice、iFinD、Wind等第三方数据库，受数据采集方式、统

**第 26 页**

- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （5 字）：分析师介绍
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （66 字）：夏凡捷（S1440521120005）中信建投资深策略分析师，硕士毕业于武汉大学金融工程专业，曾任安信证券高级策略分析师，长期从事市
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （46 字）：场策略、专题研究和金股配置方面的工作。新财富、水晶球、金牛奖策略分析师，Wind金牌分析师。
- `table_row`/kept reasons=['tbl[0]'] （4 字）：评级说明

**第 27 页**

- `paragraph`/kept （5 字）：分析师声明
- `paragraph`/kept （122 字）：本报告署名分析师在此声明：（i）以勤勉的职业态度、专业审慎的研究方法，使用合法合规的信息，独立、客观地出具本报告, 结论不受任何第三方的授意或影响。（ii）本人不曾因，不因，也将不会因本报告中的具体推荐意见或观点而直接或间接收到任何形式的补偿。
- `paragraph`/kept （6 字）：法律主体说明
- `paragraph`/kept （158 字）：本报告由中信建投证券股份有限公司及/或其附属机构（以下合称“中信建投”）制作，由中信建投证券股份有限公司在中华人民共和国（仅为本报告目的，不包括香港、澳门、台湾）提供。中信建投证券股份有限公司具有中国证监会许可的投资咨询业务资格，本报告署名分析师所持中国证券业协会授予的证券投资咨询执业资格证书编号已披露在报告首页。

### 被本材料阻断的目标（4）

| target_id | role | 所需引文 | 依赖 | 问题 |
|---|---|---|---|---|
| `b7e932c8-index` | required | 本周主要宽基指数普遍下跌 ，上证综指、东财全A分别下跌0.56%、1.20%，沪深300下跌1.33%；成长风格方面 ，创业板指下跌 4.03%，科创50下跌5.10% | header_refs, row_labels, footnotes | 本周A股各主要宽基指数表现如何，上证综指、沪深300、创业板指等分别涨跌了多少？ |
| `b7e932c8-industry` | required | 行业层面 ，本周申万 31个行业中 14个录得正收益 ，机构低配板块表现居前 ，传媒、银行和农林牧渔涨幅居前 ，分别上涨 6.0%、4.0%、3.3%；电子、有色金属和建筑材料表现较弱，分别下跌5.4%、5.0%、4.3%。 | header_refs, row_labels, footnotes | 本周申万行业中有多少个录得正收益？涨幅居前和跌幅居前的是哪些行业、涨跌幅分别是多少？ |
| `b7e932c8-pmi` | supplementary | 国家统计局发布数据显示 ，8月制造业采购经理指数 （PMI）为49.8%，较上月上升0.6个百分点；生产指数和新订单指数分别为 50.4%和50.6%，均位于扩张区间 | header_refs, row_labels, footnotes | 8月制造业采购经理指数是多少、较上月变化如何？生产指数和新订单指数分别是多少？ |
| `b7e932c8-eptable` | supplementary | 电子 -5.4% -5.5% 1800 5394 8006 169.3% 48.6% 2.8% 6.8% 1.0% 4.0% | - | 研报的一级行业盈利预测表中，电子行业本周涨跌幅、2026E盈利预测（亿元），以及2026年盈利增速预测的调整变化分别是多少？ |

### 裁决（待人工填写；本包不代签）

- [ ] `acknowledged`　- [ ] `re-extract`　- [ ] `reject`
- reviewer：__________　日期：__________
- 理由：______________________________________________

## 3. `holdout-industry-006`（industry）

- 来源文件：`2026-09-06_2026.09.06-国联民生证券-医药行业周报-cxo中报我们看到了什么-c1e12af2.pdf`
- `source_id`：`f86c6d2c054a835de4de3707c984529580e8ce57628d59f60b6aeca7a0f61fd2`
- `build_id`：`00b99a5809fc5dd51f29588f10778e90f8a579ef68cf2bfe4a3710ba926e4af7`
- 修订：parse_rev=68eb1086f1cf08d1aa437ba42fd10f760eb734edd5fdc458be5fa9aedf9fe792, clean_rev=0fea86694f5d68dda9568b38fc81a7f89093706c3058105ff9693400db016853, chunk_rev=c8a41ddc5ae48e11379a64733867b0c4885b9f9f4b2552541e115e6ac26b826f
- 规模：units 469 / chunks 32
- 门禁结论：`blocked_by_publish_gate`
- 门禁原因：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:image_region_unreadable:page:6', 'issue:table_lines_without_extraction:page:14', 'issue:table_lines_without_extraction:page:3']（image_region_unreadable@page:6, table_lines_without_extraction@page:14, table_lines_without_extraction@page:3）

### 缺口页

| 页 | 缺口类型 | 该页已提取单元 | 单元类型分布 | table 单元 |
|---:|---|---:|---|---:|
| 1 | `image_region_small` | 12 | heading 4, paragraph 3, table_row 5 | 0 |
| 2 | `image_region_small` | 6 | heading 1, paragraph 5 | 0 |
| 3 | `image_region_small`, `table_lines_without_extraction` | 114 | heading 13, paragraph 101 | 0 |
| 4 | `image_region_small` | 31 | paragraph 9, table_row 22 | 0 |
| 5 | `image_region_small` | 17 | heading 2, paragraph 15 | 0 |
| 6 | `image_region_small`, `image_region_unreadable` | 10 | paragraph 10 | 0 |
| 7 | `image_region_small` | 8 | paragraph 8 | 0 |
| 8 | `image_region_small` | 12 | heading 1, paragraph 11 | 0 |
| 9 | `image_region_small` | 11 | paragraph 11 | 0 |
| 10 | `image_region_small` | 7 | paragraph 7 | 0 |
| 11 | `image_region_small` | 39 | heading 2, paragraph 32, table_row 5 | 0 |
| 12 | `image_region_small` | 13 | paragraph 13 | 0 |
| 13 | `image_region_small` | 9 | paragraph 8, table_row 1 | 0 |
| 14 | `image_region_small`, `table_lines_without_extraction` | 44 | paragraph 44 | 0 |
| 15 | `image_region_small` | 10 | heading 1, paragraph 9 | 0 |
| 16 | `image_region_small` | 55 | heading 19, paragraph 25, table_row 11 | 0 |
| 17 | `image_region_small` | 18 | heading 3, paragraph 4, table_row 11 | 0 |
| 18 | `image_region_small` | 11 | heading 1, paragraph 10 | 0 |
| 19 | `image_region_small` | 9 | heading 2, paragraph 7 | 0 |
| 20 | `image_region_small` | 33 | heading 3, paragraph 29, table_row 1 | 0 |

### 缺口页已提取文本样例

**第 1 页**

- `paragraph`/kept reasons=['multi_column_order_flagged'] （29 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （6 字）：证券研究报告
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：1
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （12 字）：医药周报20260906

**第 2 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：2
- `paragraph`/kept reasons=['multi_column_order_flagged'] （9 字）：行业定期报告/医药

**第 3 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （1 字）：3
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 4 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：4
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 5 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （1 字）：5
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 6 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （1 字）：6
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 7 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （1 字）：7
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 8 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （1 字）：8
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 9 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：9
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 10 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （2 字）：10
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 11 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （2 字）：11
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 12 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept reasons=['multi_column_order_flagged'] （2 字）：12
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 13 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （2 字）：13
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 14 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （2 字）：14
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 15 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （2 字）：15
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 16 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （2 字）：16
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 17 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （2 字）：17
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 18 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept （2 字）：18
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 19 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （30 字）：本公司具备证券投资咨询业务资格，请务必阅读最后一页免责声明
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （7 字）：证券研究报告
- `paragraph`/kept reasons=['multi_column_order_flagged'] （2 字）：19
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：行业定期报告/医药

**第 20 页**

- `heading`/kept reasons=['heading_by_font_size'] （5 字）：分析师承诺
- `paragraph`/kept （174 字）：本报告署名分析师具有中国证券业协会授予的证券投资咨询执业资格并登记为注册分析师，基于认真审慎的工作态度、专业严谨的研究方法与分析逻辑得出研究结论，独立、客观地出具本报告，并对本报告的内容和观点负责。本报告清晰准确地反映了研究人员的研究观点，结论不受任何第三方的授意、影响，研究人员不曾因、不因、也将不会因本报告中的具体推荐意见或观点而直接或间接收到
- `paragraph`/kept （8 字）：任何形式的利益。
- `heading`/noise reasons=['heading_by_font_size', 'disclaimer_heading'] （5 字）：评级说明

### 被本材料阻断的目标（5）

| target_id | role | 所需引文 | 依赖 | 问题 |
|---|---|---|---|---|
| `f86c6d2c-cxo-h1` | required | 2026H1 年 20 家 CXO 企业合计实现收入 562 亿元，同比+24.5%，合计实现归母净利润 132 亿元，同比+17%；2026 年 Q2 共实现营业收入 307 亿元， 同比+29.4%， 合计实现归母净利润73 亿元，同比+13%。 | header_refs, row_labels, footnotes | 2026H1 国联民生选取的 20 家 CXO 样本公司合计实现的营业收入和同比增长是多少？ |
| `f86c6d2c-wuqi-order` | required | 1）截至 2026Q2，药明康德持续经营业务在手订单 664.3 亿元，同比+25.2%。 | header_refs, row_labels, footnotes | 截至 2026Q2，药明康德持续经营业务的在手订单金额和同比增速是多少？ |
| `f86c6d2c-medamt` | required | 医药成交总额5233.99 亿元， 沪深总成交额为97451.96 亿元， 医药成交额占比沪深总成交额比例为5.37%（2013 年以来成交额均值为 6.98%）。 | header_refs, row_labels, footnotes | 当周（08.31-09.04）医药行业的成交额占沪深总成交额的比例是多少？ |
| `f86c6d2c-cxotable` | supplementary | 药明康德 288.97 39% 4,693.7 | row_labels, footnotes | 图 5 中 CXO 龙头药明康德按市值排序的 2026H1 营业收入及同比增速是多少？ |
| `f86c6d2c-glp1` | supplementary | 2026H1，两款 GLP-1 减重降糖大单品替尔泊肽、司美格鲁肽全球销售额合计超 450 亿美元， 分别登顶全球药品销售额第一名/第二名。 | header_refs, row_labels, footnotes | 2026H1 替尔泊肽和司美格鲁肽两款 GLP-1 减重降糖大单品的全球销售额合计是多少？ |

### 裁决（待人工填写；本包不代签）

- [ ] `acknowledged`　- [ ] `re-extract`　- [ ] `reject`
- reviewer：__________　日期：__________
- 理由：______________________________________________

## 4. `holdout-industry-007`（industry）

- 来源文件：`2026-09-06_2026.09.06-国金证券-通信行业研究-hbm市场极度紧缺-字节获296亿美元银团贷款-7ee005e2.pdf`
- `source_id`：`a91d95c71fd0558c054bd2374139b1c24d85f58a305bc8dd83628e380d564961`
- `build_id`：`c9624c5c39909971c39ccd4a8017ab1fd7eaa3626ce8b4b9a8edf893d8bee593`
- 修订：parse_rev=65cd4a78a4d4571f0c4a1a8e662db8d12a94144e8815fe2eaeccb67cd87e03d6, clean_rev=0fea86694f5d68dda9568b38fc81a7f89093706c3058105ff9693400db016853, chunk_rev=c8a41ddc5ae48e11379a64733867b0c4885b9f9f4b2552541e115e6ac26b826f
- 规模：units 681 / chunks 71
- 门禁结论：`blocked_by_publish_gate`
- 门禁原因：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:table_lines_without_extraction:page:6', 'issue:table_lines_without_extraction:page:7']（table_lines_without_extraction@page:6, table_lines_without_extraction@page:7）

### 缺口页

| 页 | 缺口类型 | 该页已提取单元 | 单元类型分布 | table 单元 |
|---:|---|---:|---|---:|
| 1 | `image_region_small` | 42 | heading 12, paragraph 30 | 0 |
| 2 | `image_region_small` | 29 | heading 2, paragraph 27 | 0 |
| 3 | `image_region_small` | 15 | paragraph 12, table_row 3 | 0 |
| 4 | `image_region_small` | 39 | heading 4, paragraph 35 | 0 |
| 5 | `image_region_small` | 172 | heading 90, paragraph 81, table_row 1 | 0 |
| 6 | `image_region_small`, `table_lines_without_extraction` | 146 | heading 8, paragraph 138 | 0 |
| 7 | `image_region_small`, `table_lines_without_extraction` | 89 | heading 4, paragraph 85 | 0 |
| 8 | `image_region_small` | 26 | heading 7, paragraph 19 | 0 |
| 9 | `image_region_small` | 16 | paragraph 16 | 0 |
| 10 | `image_region_small` | 20 | paragraph 20 | 0 |
| 11 | `image_region_small` | 20 | paragraph 20 | 0 |
| 12 | `image_region_small` | 9 | paragraph 9 | 0 |
| 13 | `image_region_small` | 7 | heading 1, paragraph 6 | 0 |
| 14 | `image_region_small` | 51 | heading 9, paragraph 42 | 0 |

### 缺口页已提取文本样例

**第 1 页**

- `paragraph`/kept （12 字）：敬请参阅最后一页特别声明
- `paragraph`/kept （1 字）：1
- `paragraph`/kept （13 字）：通信组分析师：张真桢（执业
- `paragraph`/kept （14 字）：S1130524060002

**第 2 页**

- `paragraph`/kept reasons=['multi_column_order_flagged'] （4 字）：行业周报
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：2
- `paragraph`/kept reasons=['multi_column_order_flagged'] （8 字）：扫码获取更多服务

**第 3 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （4 字）：行业周报
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：3
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：扫码获取更多服务

**第 4 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （4 字）：行业周报
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （1 字）：4
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：扫码获取更多服务

**第 5 页**

- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：行业周报
- `heading`/noise reasons=['heading_by_font_size', 'footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `heading`/kept reasons=['heading_by_font_size'] （1 字）：5
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：扫码获取更多服务

**第 6 页**

- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：行业周报
- `paragraph`/noise reasons=['footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `heading`/kept reasons=['heading_by_font_size'] （1 字）：6
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：扫码获取更多服务

**第 7 页**

- `paragraph`/noise reasons=['header_repeated_geometric'] （4 字）：行业周报
- `paragraph`/noise reasons=['footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `heading`/kept reasons=['heading_by_font_size'] （1 字）：7
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：扫码获取更多服务

**第 8 页**

- `paragraph`/noise reasons=['header_repeated_geometric'] （4 字）：行业周报
- `paragraph`/noise reasons=['footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `heading`/kept reasons=['heading_by_font_size'] （1 字）：8
- `paragraph`/noise reasons=['header_repeated_geometric'] （9 字）：扫码获取更多服务

**第 9 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （4 字）：行业周报
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：9
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：扫码获取更多服务

**第 10 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （4 字）：行业周报
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （2 字）：10
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：扫码获取更多服务

**第 11 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （4 字）：行业周报
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （2 字）：11
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：扫码获取更多服务

**第 12 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （4 字）：行业周报
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （2 字）：12
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：扫码获取更多服务

**第 13 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （4 字）：行业周报
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （2 字）：13
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （9 字）：扫码获取更多服务

**第 14 页**

- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：行业周报
- `paragraph`/noise reasons=['footer_repeated_geometric'] （12 字）：敬请参阅最后一页特别声明
- `heading`/kept reasons=['heading_by_font_size'] （2 字）：14
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （9 字）：扫码获取更多服务

### 被本材料阻断的目标（4）

| target_id | role | 所需引文 | 依赖 | 问题 |
|---|---|---|---|---|
| `a91d95c7-hbm` | required | 2026 年全球 HBM 市场规模预计增长 58%至 546 亿美元， 占 DRAM 市场近四成， 产能缺口仍维持在 50%至 60%。 | header_refs, row_labels, footnotes | 2026 年全球 HBM 市场规模预计增长多少至多少亿美元？ |
| `a91d95c7-bytedance` | required | 字节跳动获 296 亿美元的银团贷款， 为今年亚洲规模第二大的美元贷款，充裕的现金流储备为公司激进扩张提供了有力支撑。公司正考虑将今年资本支出提升至高达 700 亿美元，超过去年总额两倍 | header_refs, row_labels, footnotes | 字节跳动获得的银团贷款规模是今年的亚洲第几大美元贷款，资本支出计划提升至多少？ |
| `a91d95c7-hbmprice` | required | 据内存市场研究公司 MegaGrid Supply 数据，一块36GB 的 HBM3E 产品现货售价为 2100 美元，约为长约价格的四到五倍；16 层 HBM4 现货价格更高达 3500 美元。 | header_refs, row_labels, footnotes | 36GB 的 HBM3E 与 16 层 HBM4 的现货售价分别为多少美元？ |
| `a91d95c7-cxmt` | required | 长鑫存储LPDDR6 内存正式量产，实现全球首次落地商用，标志着中国存储企业首次在高端内存标准上打破海外厂商长期垄断产品先发的局面 | header_refs, row_labels, footnotes | 长鑫存储 LPDDR6 内存落地商用在产业上意味着什么？ |

### 裁决（待人工填写；本包不代签）

- [ ] `acknowledged`　- [ ] `re-extract`　- [ ] `reject`
- reviewer：__________　日期：__________
- 理由：______________________________________________

## 5. `holdout-macro-008`（macro）

- 来源文件：`2026-09-06_2026.09.06-华泰证券-宏观海外周报-联储加息悬念白热化-d571f138.pdf`
- `source_id`：`5e30537691c88e4eee8790af34876323cef08e3cd22d388dee8a7bbe1e8f44e9`
- `build_id`：`313426724dd6b55b978887cc06818f78ba66aa445c37b95c8eeaff554fc0e6e8`
- 修订：parse_rev=9adafd72b4b370f454e4ce310c4c39a03a85395100fff46f641c23ef04a3bf7e, clean_rev=0fea86694f5d68dda9568b38fc81a7f89093706c3058105ff9693400db016853, chunk_rev=c8a41ddc5ae48e11379a64733867b0c4885b9f9f4b2552541e115e6ac26b826f
- 规模：units 1432 / chunks 318
- 门禁结论：`blocked_by_publish_gate`
- 门禁原因：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:image_region_unreadable:page:11', 'issue:table_lines_without_extraction:page:14', 'issue:table_lines_without_extraction:page:15', 'issue:table_lines_without_extraction:page:4', 'issue:table_lines_without_extraction:page:5', 'issue:table_lines_without_extraction:page:9']（image_region_unreadable@page:11, table_lines_without_extraction@page:14, table_lines_without_extraction@page:15, table_lines_without_extraction@page:4, table_lines_without_extraction@page:5, table_lines_without_extraction@page:9）

### 缺口页

| 页 | 缺口类型 | 该页已提取单元 | 单元类型分布 | table 单元 |
|---:|---|---:|---|---:|
| 1 | `image_region_small` | 48 | heading 18, paragraph 13, table_row 17 | 0 |
| 2 | `image_region_small` | 28 | heading 20, paragraph 8 | 0 |
| 3 | `image_region_small` | 23 | heading 18, paragraph 5 | 0 |
| 4 | `image_region_small`, `table_lines_without_extraction` | 150 | heading 24, paragraph 126 | 0 |
| 5 | `image_region_small`, `table_lines_without_extraction` | 130 | heading 23, paragraph 107 | 0 |
| 6 | `image_region_small` | 71 | heading 18, paragraph 50, table_row 3 | 0 |
| 7 | `image_region_small` | 123 | heading 23, paragraph 98, table_row 2 | 0 |
| 8 | `image_region_small` | 116 | heading 22, paragraph 92, table_row 2 | 0 |
| 9 | `image_region_small`, `table_lines_without_extraction` | 61 | heading 23, paragraph 38 | 0 |
| 10 | `image_region_small` | 101 | heading 60, paragraph 19, table_row 22 | 0 |
| 11 | `image_region_small`, `image_region_unreadable` | 28 | heading 13, paragraph 8, table_row 7 | 0 |
| 12 | `image_region_small` | 79 | heading 17, paragraph 37, table_row 25 | 0 |
| 13 | `image_region_small` | 121 | heading 22, paragraph 78, table_row 21 | 0 |
| 14 | `image_region_small`, `table_lines_without_extraction` | 129 | heading 22, paragraph 107 | 0 |
| 15 | `image_region_small`, `table_lines_without_extraction` | 109 | heading 22, paragraph 87 | 0 |
| 16 | `image_region_small` | 35 | heading 19, paragraph 16 | 0 |
| 17 | `image_region_small` | 30 | heading 18, paragraph 12 | 0 |
| 18 | `image_region_small` | 50 | heading 18, paragraph 32 | 0 |

### 缺口页已提取文本样例

**第 1 页**

- `paragraph`/kept reasons=['multi_column_order_flagged'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：1
- `paragraph`/kept reasons=['multi_column_order_flagged'] （6 字）：证券研究报告
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （2 字）：宏观

**第 2 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：2
- `paragraph`/kept reasons=['multi_column_order_flagged'] （4 字）：宏观研究
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （4 字）：正文目录

**第 3 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：3
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （4 字）：宏观研究
- `paragraph`/noise reasons=['multi_column_order_flagged', 'toc_dot_leaders'] （200 字）：图表27：最新一周美国汽油可供应天数较上一周小幅下降 ........................................................................................ 8
图表28：截至8 月28 日，美国EIA 商业原油库存减少 ....................................................

**第 4 页**

- `heading`/noise reasons=['heading_by_font_size', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `heading`/kept reasons=['heading_by_font_size'] （1 字）：4
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：宏观研究
- `heading`/kept reasons=['heading_by_font_size'] （12 字）：全球经济动能高频指标一览

**第 5 页**

- `heading`/noise reasons=['heading_by_font_size', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `heading`/kept reasons=['heading_by_font_size'] （1 字）：5
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：宏观研究
- `paragraph`/kept （39 字）：图表7：分行业看，零售批发和劳工部门走强，家庭、住房部门基本持平，工业部门走弱

**第 6 页**

- `heading`/noise reasons=['heading_by_font_size', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `heading`/kept reasons=['heading_by_font_size'] （1 字）：6
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：宏观研究
- `paragraph`/kept （29 字）：图表13：近期Lightcast 数据指示岗位空缺有所上升

**第 7 页**

- `heading`/noise reasons=['heading_by_font_size', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `heading`/kept reasons=['heading_by_font_size'] （1 字）：7
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：宏观研究
- `paragraph`/kept （25 字）：图表18：近期全球航班总数有所回落，符合季节性趋势

**第 8 页**

- `heading`/noise reasons=['heading_by_font_size', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `heading`/kept reasons=['heading_by_font_size'] （1 字）：8
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：宏观研究
- `paragraph`/kept （27 字）：图表24：房地产待售时长有所上升，显示房屋流通速度下降

**第 9 页**

- `heading`/noise reasons=['heading_by_font_size', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `heading`/kept reasons=['heading_by_font_size'] （1 字）：9
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：宏观研究
- `heading`/kept reasons=['heading_by_font_size'] （6 字）：制造业和出口

**第 10 页**

- `heading`/noise reasons=['heading_by_font_size', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `heading`/kept reasons=['heading_by_font_size'] （2 字）：10
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：宏观研究
- `heading`/kept reasons=['heading_by_font_size'] （6 字）：海外央行跟踪

**第 11 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `paragraph`/kept reasons=['multi_column_order_flagged'] （2 字）：11
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （4 字）：宏观研究
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （11 字）：海外金融市场和金融条件

**第 12 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （2 字）：12
- `heading`/noise reasons=['multi_column_order_flagged', 'heading_by_font_size', 'header_repeated_geometric'] （4 字）：宏观研究
- `paragraph`/kept reasons=['multi_column_order_flagged'] （18 字）：图表36：上周美元指数下降至99.2

**第 13 页**

- `heading`/noise reasons=['heading_by_font_size', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `heading`/kept reasons=['heading_by_font_size'] （2 字）：13
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：宏观研究
- `paragraph`/kept （26 字）：图表38：最新一周AAII 看涨情绪上升至2.19%

**第 14 页**

- `heading`/noise reasons=['heading_by_font_size', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `heading`/kept reasons=['heading_by_font_size'] （2 字）：14
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：宏观研究
- `paragraph`/kept （22 字）：图表43：最新一周美债收益率曲线较上一周上移

**第 15 页**

- `heading`/noise reasons=['heading_by_font_size', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `heading`/kept reasons=['heading_by_font_size'] （2 字）：15
- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （4 字）：宏观研究
- `paragraph`/kept （24 字）：图表49：上周美债流动性收紧，德债流动性小幅宽松

**第 16 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `paragraph`/kept reasons=['multi_column_order_flagged'] （2 字）：16
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （4 字）：宏观研究
- `heading`/noise reasons=['multi_column_order_flagged', 'heading_by_font_size', 'disclaimer_heading'] （4 字）：免责声明

**第 17 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `paragraph`/kept reasons=['multi_column_order_flagged'] （2 字）：17
- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （4 字）：宏观研究
- `paragraph`/kept reasons=['multi_column_order_flagged'] （150 字）：香港-重要监管披露 •华泰金融控股（香港）有限公司的雇员或其关联人士没有担任本报告中提及的公司或发行人的高级人员。 •有关重要的披露信息，请参华泰金融控股（香港）有限公司的网页https://www.htsc.com.hk/stock_disclosure 其他信息请参见下方“美国-重要监管披露”。

**第 18 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （30 字）：免责声明和披露以及分析师声明是报告的一部分，请务必一起阅读。
- `paragraph`/kept （2 字）：18
- `paragraph`/noise reasons=['header_repeated_geometric'] （4 字）：宏观研究
- `paragraph`/kept （6 字）：法律实体披露

### 被本材料阻断的目标（5）

| target_id | role | 所需引文 | 依赖 | 问题 |
|---|---|---|---|---|
| `5e305376-nonfarm` | required | 美国 8 月新增非农就业为 16.2 万，大幅高于预期的 5.6万，前两个月累计上修 5.5万。 | header_refs, row_labels, footnotes | 美国 8 月新增非农就业人数是多少，与市场预期相比如何？ |
| `5e305376-fedrate` | required | 联储年内剩余累计加息预期下降 3bp 至 35bp。 | header_refs, row_labels, footnotes | 全周联储年内剩余累计加息预期变化了多少（降至多少 bp）？ |
| `5e305376-oil` | required | 布伦特原油期货上涨 7.8%至 96.3 美元/桶，COMEX 期金下跌 1.2%至 4476.6 美元/盎司，伦 敦现银下跌 0.3%至 66.2美元/盎司，LME现铜下跌 0.5%至 14325美元/吨。 | header_refs, row_labels, footnotes | 当周布伦特原油期货上涨多少至每桶多少美元？ |
| `5e305376-dxy` | required | 汇率方面，日央行紧缩预期升温导致日元升值 2.4%至 156.3，美元指数下行 0.5%至 99.2，欧元升值 0.3%至 1.16。 | header_refs, row_labels, footnotes | 当周美元指数、日元和欧元相对美元分别变动至多少？ |
| `5e305376-gdpnow` | supplementary | 增长方面，亚特兰大联储 GDPNow上调三季度 GDP 增速预测至 4.7%。 | header_refs, row_labels, footnotes | 亚特兰大联储 GDPNow 将美国三季度 GDP 增速预测上调至多少？ |

### 裁决（待人工填写；本包不代签）

- [ ] `acknowledged`　- [ ] `re-extract`　- [ ] `reject`
- reviewer：__________　日期：__________
- 理由：______________________________________________

## 6. `holdout-macro-009`（macro）

- 来源文件：`2026-09-06_2026.09.06-天风证券-a股策略周报-非农大超预期-加息预期升温-5e671b67.pdf`
- `source_id`：`f7f65d7ee16db19e79766a9f0f13b16f22b56ff318530fedf64d9240fbb87826`
- `build_id`：`45383590029c0b354f7aeb28a0021ccb789bc852159fed3095ce6a5754740538`
- 修订：parse_rev=b633eec35472c9c080f87a89a2510555789248f83e1455ad5db331745eeb5c86, clean_rev=0fea86694f5d68dda9568b38fc81a7f89093706c3058105ff9693400db016853, chunk_rev=c8a41ddc5ae48e11379a64733867b0c4885b9f9f4b2552541e115e6ac26b826f
- 规模：units 176 / chunks 19
- 门禁结论：`blocked_by_publish_gate`
- 门禁原因：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:image_region_unreadable:page:9']（image_region_unreadable@page:9）

### 缺口页

| 页 | 缺口类型 | 该页已提取单元 | 单元类型分布 | table 单元 |
|---:|---|---:|---|---:|
| 1 | `image_region_small` | 23 | heading 3, paragraph 20 | 0 |
| 2 | `image_region_small` | 7 | heading 2, paragraph 5 | 0 |
| 3 | `image_region_small` | 17 | heading 2, paragraph 15 | 0 |
| 4 | `image_region_small` | 14 | heading 2, paragraph 12 | 0 |
| 5 | `image_region_small` | 19 | heading 5, paragraph 8, table_row 6 | 0 |
| 6 | `image_region_small` | 13 | heading 1, paragraph 12 | 0 |
| 7 | `image_region_small` | 18 | heading 1, paragraph 17 | 0 |
| 8 | `image_region_small` | 14 | paragraph 14 | 0 |
| 9 | `image_region_small`, `image_region_unreadable` | 8 | heading 1, paragraph 7 | 0 |
| 10 | `image_region_small` | 5 | heading 1, paragraph 4 | 0 |
| 11 | `image_region_small` | 38 | paragraph 38 | 0 |

### 缺口页已提取文本样例

**第 1 页**

- `heading`/kept reasons=['heading_by_font_size'] （11 字）：策略报告 | 投资策略
- `paragraph`/kept （19 字）：请务必阅读正文之后的信息披露和免责申明
- `paragraph`/kept （1 字）：1
- `heading`/kept reasons=['heading_by_font_size'] （7 字）：A 股策略周报

**第 2 页**

- `paragraph`/noise reasons=['header_repeated_geometric'] （12 字）：策略报告 | 投资策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （25 字）：请务必阅读正文之后的信息披露和免责申明
- `paragraph`/kept （1 字）：2
- `heading`/kept reasons=['heading_by_font_size'] （4 字）：内容目录

**第 3 页**

- `paragraph`/noise reasons=['header_repeated_geometric'] （12 字）：策略报告 | 投资策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （25 字）：请务必阅读正文之后的信息披露和免责申明
- `paragraph`/kept （1 字）：3
- `heading`/kept reasons=['heading_by_font_size'] （17 字）：1.国内：8 月制造业PMI 回暖

**第 4 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （12 字）：策略报告 | 投资策略
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （25 字）：请务必阅读正文之后的信息披露和免责申明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：4
- `paragraph`/kept reasons=['multi_column_order_flagged'] （27 字）：图4：8 月非制造业PMI：建筑业景气度回落（单位%）

**第 5 页**

- `heading`/noise reasons=['heading_by_font_size', 'header_repeated_geometric'] （12 字）：策略报告 | 投资策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （25 字）：请务必阅读正文之后的信息披露和免责申明
- `paragraph`/kept （1 字）：5
- `paragraph`/kept （11 字）：图6：工业生产腾落指数

**第 6 页**

- `paragraph`/noise reasons=['header_repeated_geometric'] （12 字）：策略报告 | 投资策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （25 字）：请务必阅读正文之后的信息披露和免责申明
- `paragraph`/kept （1 字）：6
- `heading`/kept reasons=['heading_by_font_size'] （10 字）：2.1.国际大事跟踪

**第 7 页**

- `paragraph`/noise reasons=['header_repeated_geometric'] （12 字）：策略报告 | 投资策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （25 字）：请务必阅读正文之后的信息披露和免责申明
- `paragraph`/kept （1 字）：7
- `paragraph`/kept （103 字）：地时间8 月30日20时30 分至9月2 日20 时30 分，伊朗共有142 人在敌人的袭击中受伤、18 人死亡。当地时间8 月30 日晚，美军袭击伊朗南部拉腊克岛。当地时间9月1日晚，美军又袭击伊朗多地。

**第 8 页**

- `paragraph`/noise reasons=['header_repeated_geometric'] （12 字）：策略报告 | 投资策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （25 字）：请务必阅读正文之后的信息披露和免责申明
- `paragraph`/kept （1 字）：8
- `paragraph`/kept （14 字）：图13：美国劳动力参与率回升

**第 9 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'header_repeated_geometric'] （12 字）：策略报告 | 投资策略
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （25 字）：请务必阅读正文之后的信息披露和免责申明
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：9
- `paragraph`/kept reasons=['multi_column_order_flagged'] （87 字）：市初期资金更偏好少数高景气赛道，后期资金抱团聚焦主线，新增资金获利难度提升，而周期股又具备低估值、高贝塔的属性，易随着基本面回暖的深化而发挥较好的业绩弹性，获得增量资金青睐。

**第 10 页**

- `paragraph`/noise reasons=['header_repeated_geometric'] （12 字）：策略报告 | 投资策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （25 字）：请务必阅读正文之后的信息披露和免责申明
- `paragraph`/kept （2 字）：10
- `heading`/kept reasons=['heading_by_font_size'] （6 字）：5.风险提示

**第 11 页**

- `paragraph`/noise reasons=['header_repeated_geometric'] （12 字）：策略报告 | 投资策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （25 字）：请务必阅读正文之后的信息披露和免责申明
- `paragraph`/kept （2 字）：11
- `paragraph`/kept （134 字）：分析师声明本报告署名分析师在此声明：我们具有中国证券业协会授予的证券投资咨询执业资格或相当的专业胜任能力，本报告所表述的所有观点均准确地反映了我们对标的证券和发行人的个人看法。我们所得报酬的任何部分不曾与，不与，也将不会与本报告中的具体投资建议或观点有直接或间接联系。

### 被本材料阻断的目标（4）

| target_id | role | 所需引文 | 依赖 | 问题 |
|---|---|---|---|---|
| `f7f65d7e-payroll` | required | 8 月美国非农就业数据 高于预期，失业率 持平 。8 月失业率报 4.1%，前值 4.1%，预期 4.1%。8 月新增非农就业人数 增 16.2 万人，预期增 5.6 万人，前值自 -2.3 万人修正至+2.1 万人。 | header_refs, row_labels, footnotes | 2026年8月美国新增非农就业人数和失业率数据各是多少？ |
| `f7f65d7e-cme` | required | 据 CME“美联储观察” ，截至 2026/9/5，美联储 2026 年 9 月加息 25 基点的概率为 59.4%，维持现有利率的概率 为 40.6%。 | header_refs, row_labels, footnotes | 据CME美联储观察，美联储2026年9月加息25基点的概率有多高？ |
| `f7f65d7e-alloc` | required | 根据经济复苏与市场流动性，可以把投资主线降维为三个方向： 1）AI 产业革命带来的算力、存力、电力及应用的科技主线机会， 2）内外共振，经济逐步修复，牛市主线风格“强者恒强” ，但周期后半段易有所表现， 3）赔率思维，即考虑风格轮动、底部反转的可能性。连续三年跑输但第四年跑赢概率较大的行业有食品饮料、农林牧渔、社会服务、医药生物。 | header_refs, row_labels, footnotes | 本期研报建议投资者关注哪几个投资主线方向？ |
| `f7f65d7e-risk` | supplementary | 地缘冲突超预期，海外通胀持续性超预期，流动性收紧超预期。 | header_refs, row_labels, footnotes | 本期研报列出了哪些主要风险提示？ |

### 裁决（待人工填写；本包不代签）

- [ ] `acknowledged`　- [ ] `re-extract`　- [ ] `reject`
- reviewer：__________　日期：__________
- 理由：______________________________________________

## 7. `holdout-macro-010`（macro）

- 来源文件：`2026-09-06_2026.09.06-中银国际-中银证券-策略周报-外部加息扰动未消-短期以守为攻-880f5e5e.pdf`
- `source_id`：`d179b615e82e4f6b47184ead5a34027abbd7bf2ef65ca4d599d03d31368c7595`
- `build_id`：`fc7ab34ae8cc16e8f805096db5fb6ab7d2ec221e410a335b4d6032d4278a8519`
- 修订：parse_rev=604705f673a68fd61f338da3981c3bcb62887bc959cfe837a3b3bf725370e1e5, clean_rev=0fea86694f5d68dda9568b38fc81a7f89093706c3058105ff9693400db016853, chunk_rev=c8a41ddc5ae48e11379a64733867b0c4885b9f9f4b2552541e115e6ac26b826f
- 规模：units 481 / chunks 65
- 门禁结论：`blocked_by_publish_gate`
- 门禁原因：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:table_lines_without_extraction:page:8']（table_lines_without_extraction@page:8）

### 缺口页

| 页 | 缺口类型 | 该页已提取单元 | 单元类型分布 | table 单元 |
|---:|---|---:|---|---:|
| 1 | `image_region_small` | 18 | heading 2, paragraph 16 | 0 |
| 2 | `image_region_small` | 7 | heading 1, paragraph 6 | 0 |
| 3 | `image_region_small` | 5 | heading 1, paragraph 4 | 0 |
| 4 | `image_region_small` | 38 | heading 1, paragraph 31, table_row 6 | 0 |
| 5 | `image_region_small` | 60 | paragraph 41, table_row 19 | 0 |
| 6 | `image_region_small` | 48 | paragraph 28, table_row 20 | 0 |
| 7 | `image_region_small` | 68 | heading 1, paragraph 25, table_row 42 | 0 |
| 8 | `image_region_small`, `table_lines_without_extraction` | 50 | heading 8, paragraph 42 | 0 |
| 9 | `image_region_small` | 116 | paragraph 108, table_row 8 | 0 |
| 10 | `image_region_small` | 6 | heading 1, paragraph 5 | 0 |
| 11 | `image_region_small` | 11 | heading 1, paragraph 10 | 0 |

### 缺口页已提取文本样例

**第 1 页**

- `paragraph`/kept （18 字）：策略研究 | 证券研究报告—总量周报
- `paragraph`/kept （12 字）：2026 年9 月6 日
- `paragraph`/kept （24 字）：中银国际证券股份有限公司具备证券投资咨询业务资格
- `paragraph`/kept （4 字）：策略研究

**第 2 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：2026 年9 月6 日
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （4 字）：策略周报
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：2
- `heading`/noise reasons=['multi_column_order_flagged', 'heading_by_font_size', 'toc_heading'] （2 字）：目录

**第 3 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：2026 年9 月6 日
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （4 字）：策略周报
- `paragraph`/kept reasons=['multi_column_order_flagged'] （1 字）：3
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （4 字）：图表目录

**第 4 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （12 字）：2026 年9 月6 日
- `paragraph`/noise reasons=['footer_repeated_geometric'] （4 字）：策略周报
- `paragraph`/kept （1 字）：4
- `heading`/kept reasons=['heading_by_font_size'] （6 字）：市场热点思考

**第 5 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （12 字）：2026 年9 月6 日
- `paragraph`/noise reasons=['footer_repeated_geometric'] （4 字）：策略周报
- `paragraph`/kept （1 字）：5
- `paragraph`/kept （25 字）：图表4. 不同库存周期阶段大类资产及A 股胜率表现

**第 6 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （12 字）：2026 年9 月6 日
- `paragraph`/noise reasons=['footer_repeated_geometric'] （4 字）：策略周报
- `paragraph`/kept （1 字）：6
- `paragraph`/kept （32 字）：图表7. 历年十一前2 周A 股主要指数及风格表现（涨跌幅：%）

**第 7 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （12 字）：2026 年9 月6 日
- `paragraph`/noise reasons=['footer_repeated_geometric'] （4 字）：策略周报
- `paragraph`/kept （1 字）：7
- `heading`/kept reasons=['heading_by_font_size'] （6 字）：一周数据集锦

**第 8 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （12 字）：2026 年9 月6 日
- `paragraph`/noise reasons=['footer_repeated_geometric'] （4 字）：策略周报
- `paragraph`/kept （1 字）：8
- `heading`/kept reasons=['heading_by_font_size'] （20 字）：图表10. 本周大盘价值风格表现相对占优

**第 9 页**

- `paragraph`/noise reasons=['footer_repeated_geometric'] （12 字）：2026 年9 月6 日
- `paragraph`/noise reasons=['footer_repeated_geometric'] （4 字）：策略周报
- `paragraph`/kept （1 字）：9
- `paragraph`/kept （17 字）：图表12. 本周主力资金重回净流出

**第 10 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：2026 年9 月6 日
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （4 字）：策略周报
- `paragraph`/kept reasons=['multi_column_order_flagged'] （2 字）：10
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （4 字）：风险提示

**第 11 页**

- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （12 字）：2026 年9 月6 日
- `paragraph`/noise reasons=['multi_column_order_flagged', 'footer_repeated_geometric'] （4 字）：策略周报
- `paragraph`/kept reasons=['multi_column_order_flagged'] （2 字）：11
- `heading`/kept reasons=['multi_column_order_flagged', 'heading_by_font_size'] （4 字）：披露声明

### 被本材料阻断的目标（4）

| target_id | role | 所需引文 | 依赖 | 问题 |
|---|---|---|---|---|
| `d179b615-hikerate` | required | 非农强化加息预期， 短期利率扰动难消。8 月非农数据发布后， 市场对9 月加息的定价进一步抬升。当前 CME 隐含的 9 月加息概率已升至59%， 美债长端利率随之走高，10 年期收益率一度触及4.79%。 | header_refs, row_labels, footnotes | 非农数据发布后，市场对9月加息的定价以及美债长端利率有何变化？ |
| `d179b615-passive` | required | 被动补库阶段多为权益资产表现最差的时期。 万得全A 月均收益-1.83%、 胜率仅13%， 上证月均-1.80%、胜率 0%；大类资产角度，债券资产则全面占优，中证全债月均+0.29%、胜率 75%。 | header_refs, row_labels, footnotes | 历史复盘显示被动补库阶段各类资产的月均表现如何？ |
| `d179b615-chart3` | required | 涨跌幅:% 万得全 A 南华商品 中证全债 上证 沪深 300 创业板 工业品 金属 能化 农产品 被动补库 (1.83) (0.10) 0.29 (1.80) (2.21) (1.28) 0.21 0.29 0.14 (0.26) | - | 被动补库阶段，各类资产及A股指数的月均涨跌幅是多少？ |
| `d179b615-goldoil` | supplementary | 当前金油比 43.61，自本轮高点回落 40.6%，自 4 月 7 日本轮低点修复 36.7%。 | header_refs, row_labels, footnotes | 当前金油比数值是多少？自高点回落和自低点修复的幅度各是多少？ |

### 裁决（待人工填写；本包不代签）

- [ ] `acknowledged`　- [ ] `re-extract`　- [ ] `reject`
- reviewer：__________　日期：__________
- 理由：______________________________________________

## 8. `holdout-macro-011`（macro）

- 来源文件：`2026-09-06_2026.09.06-国金证券-a股策略周报-迷雾与罗盘-fb9b3c67.pdf`
- `source_id`：`2f8aa70958184296f74bc9a78193c49f5966608bd3ff2330331472eaa3b90339`
- `build_id`：`ffb0ccd22615b21f3a4e4f22967fb4c45ed8f25ae84bc111777d0938e0efd5f4`
- 修订：parse_rev=91d6fd3a0975bd7ae85ecbc9da0456497dcd1358153d5559b16f92eddeb21adf, clean_rev=0fea86694f5d68dda9568b38fc81a7f89093706c3058105ff9693400db016853, chunk_rev=c8a41ddc5ae48e11379a64733867b0c4885b9f9f4b2552541e115e6ac26b826f
- 规模：units 232 / chunks 50
- 门禁结论：`blocked_by_publish_gate`
- 门禁原因：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:table_lines_without_extraction:page:11']（table_lines_without_extraction@page:11）

### 缺口页

| 页 | 缺口类型 | 该页已提取单元 | 单元类型分布 | table 单元 |
|---:|---|---:|---|---:|
| 1 | `image_region_small` | 3 | table_row 3 | 0 |
| 2 | `image_region_small` | 3 | table_row 3 | 0 |
| 3 | `image_region_small` | 3 | table_row 3 | 0 |
| 4 | `image_region_small` | 3 | table_row 3 | 0 |
| 5 | `image_region_small` | 53 | heading 1, paragraph 34, table_row 18 | 0 |
| 6 | `image_region_small` | 21 | paragraph 18, table_row 3 | 0 |
| 7 | `image_region_small` | 3 | table_row 3 | 0 |
| 8 | `image_region_small` | 14 | table_row 14 | 0 |
| 9 | `image_region_small` | 6 | table_row 6 | 0 |
| 10 | `image_region_small` | 3 | table_row 3 | 0 |
| 11 | `image_region_small`, `table_lines_without_extraction` | 114 | heading 11, paragraph 103 | 0 |
| 12 | `image_region_small` | 3 | table_row 3 | 0 |
| 13 | `image_region_small` | 3 | table_row 3 | 0 |

### 缺口页已提取文本样例

**第 1 页**

- `table_row`/kept reasons=['tbl[0]'] （14 字）：敬请参阅最后一页特别声明 1
- `table_row`/kept reasons=['tbl[0]'] （200 字）：策略组分析师：牟一凌（执业S1130525060002） 分析师：季宏坤（执业S1130526060001） mouyiling＠gjzq.com.cn jihongkun＠gjzq.com.cn 迷雾与罗盘产业纠结期，货币政策预期的摇摆当下美国 AI 产业链呈现明显的结构性分化：上游硬件端需求依旧强劲，算力租赁价格维持高位；但下游大模型厂商持续以价换量，Token 价格已跌至低于2025 年底的
- `table_row`/kept reasons=['tbl[0]'] （61 字）：下载日志已记录，仅供内部参考 2026 年09 月06 日 A 股策略周报 20260906 策略专题研究报告证券研究报告

**第 2 页**

- `table_row`/kept reasons=['tbl[0]'] （30 字）：下载日志已记录，仅供内部参考扫码获取更多服务策略专题研究报告
- `table_row`/kept reasons=['tbl[0]'] （14 字）：敬请参阅最后一页特别声明 2
- `table_row`/noise reasons=['tbl[0]', 'toc_dot_leaders'] （200 字）：内容目录
1、产业纠结期，货币政策的分歧阶段 .............................................................. 3
2、企业盈利：周期性顶部的可能 .................................................................. 4
3、美伊冲突再度升级，当下库存位置要比3 月低很多 .

**第 3 页**

- `table_row`/kept reasons=['tbl[0]'] （30 字）：下载日志已记录，仅供内部参考扫码获取更多服务策略专题研究报告
- `table_row`/kept reasons=['tbl[0]'] （14 字）：敬请参阅最后一页特别声明 3
- `table_row`/kept reasons=['tbl[0]'] （200 字）：1、产业纠结期，货币政策的分歧阶段当下美国 AI 产业链呈现明显分化：从算力租赁价格指数（Silicon Data H100 Rental Price Index）来看，AI 上游硬件端的需求较好，算力租赁价格仍维持高位；但从Token 价格指数（Silicon Data LLM Token expenditure index）来看，Token 的价格已经下降至比 2025 年底还要低的水平，下游

**第 4 页**

- `table_row`/kept reasons=['tbl[0]'] （30 字）：下载日志已记录，仅供内部参考扫码获取更多服务策略专题研究报告
- `table_row`/kept reasons=['tbl[0]'] （14 字）：敬请参阅最后一页特别声明 4
- `table_row`/kept reasons=['tbl[0]'] （200 字）：8 月私营部门就业人数远低于市场预期，以及威廉姆斯+沃勒发表鸽派言论使得降息预期有所回落；（3）但周五晚的新增非农就业16.2 万人，远超市场预期（5.6 万人），同时上修了6 月、7 月的非农就业数据，这又让9 月加息预期再度上升。尽管数据本身结构上具有争议，目前来看，9 月加息预期在50%-60%之间，市场一方面对加息定价并非非常悲观，又没有形成乐观的共识，下周美国的通胀数据仍需观测。图表3：

**第 5 页**

- `table_row`/kept reasons=['tbl[0]'] （30 字）：下载日志已记录，仅供内部参考扫码获取更多服务策略专题研究报告
- `table_row`/kept reasons=['tbl[0]'] （14 字）：敬请参阅最后一页特别声明 5
- `table_row`/kept reasons=['tbl[0]'] （200 字）：2025 年，美国宽松的货币政策 图表7：美国AI 投资明显带动了中国对于AI 品类的出口显上行 增速美国ISM制造业PMI % 中国:出口金额:当月值:同比:% %，右 美国:有效联邦基金利率%，右 8% 中国:出口金额:集成电路:当月值:同比:% 中国:出口金额:自动数据处理设备及其零部件:当月值:同比:% 140 美国AI相关投资同比增速:右轴 25% 6% 120 100 20% 4% 8
- `paragraph`/kept （15 字）：驱动海外制造业PMI 明显上行

**第 6 页**

- `table_row`/kept reasons=['tbl[0]'] （30 字）：下载日志已记录，仅供内部参考扫码获取更多服务策略专题研究报告
- `table_row`/kept reasons=['tbl[0]'] （14 字）：敬请参阅最后一页特别声明 6
- `table_row`/kept reasons=['tbl[0]'] （200 字）：图表9：伴随着内需政策，2024H2-2025H1 国内的社零增速和固投增速一度出现了企稳回升中国:社会消费品零售总额:累计同比:% 中国:固定资产投资完成额:累计同比:% 40 35 30 25 20 15 10 5 0 -5 -10 2021-02 2021-04 2021-06 2021-08 2021-10 2021-12 2022-02 2022-04 2022-06 2022-08 2
- `paragraph`/kept （7 字）：FDI 的增长

**第 7 页**

- `table_row`/kept reasons=['tbl[0]'] （30 字）：下载日志已记录，仅供内部参考扫码获取更多服务策略专题研究报告
- `table_row`/kept reasons=['tbl[0]'] （14 字）：敬请参阅最后一页特别声明 7
- `table_row`/kept reasons=['tbl[0]'] （200 字）：图表12：在手订单同比增速已经连续两个季度回落 图表13：非AI 领域的扣非净利润增速仍偏弱库存营收TTM同比增速差 扣非净利润剪刀差 AI产业链扣非净利润同比增速（TTM，中位数）全部A股（非金融地产）：库存同比 非AI扣非净利润同比增速（TTM，中位数） 60% 全部A股（非金融地产）：营业收入同比增速（TTM） 50% 全部A股（非金融地产）：合同负债+预收账款同比增速 50% 40% 40

**第 8 页**

- `table_row`/kept reasons=['tbl[0]'] （30 字）：下载日志已记录，仅供内部参考扫码获取更多服务策略专题研究报告
- `table_row`/kept reasons=['tbl[0]'] （14 字）：敬请参阅最后一页特别声明 8
- `table_row`/kept reasons=['tbl[0]'] （200 字）：图表15：8 月制造业PMI 显示，新订单相比新出口订单回升幅度明显更大，这或意味着国内内需正在修复中国:制造业PMI:新订单-中国:制造业PMI:新出口订单:%:右轴中国:制造业PMI:新订单:% 中国:制造业PMI:新出口订单:% 56 6 54 5 52 4 50 3 48 2 46 1 44 0 42 -1 40 -2 2021-01 2021-03 2021-05 2021-07 202
- `table_row`/kept reasons=['tbl[1]'] （4 字）：日期事件

**第 9 页**

- `table_row`/kept reasons=['tbl[0]'] （30 字）：下载日志已记录，仅供内部参考扫码获取更多服务策略专题研究报告
- `table_row`/kept reasons=['tbl[0]'] （14 字）：敬请参阅最后一页特别声明 9
- `table_row`/kept reasons=['tbl[0]'] （200 字）：图表18：全球原油陆地库存相比3 月明显下降 图表19：剔除美国以外的OECD 国家的商业原油库存也处于历史最低点全球原油陆地库存（亿桶） OECD商业原油库存（百万桶） OECD（剔除美国）商业原油库存（百万桶，右） 39.0 3300 1800 3200 38.5 1750 3100 38.0 1700 3000 37.5 1650 2900 37.0 2800 1600 36.5 2700
- `table_row`/kept reasons=['tbl[1]'] （172 字）：美国汽油库存（百万桶） 270 2021 2022 2023 2024 2025 2026 260 250 240 230 220 210 200 1周 3周 5周 7周 9周 11周 13周 15周 17周 19周 21周 23周 25周 27周 29周 31周 33周 35周 37周 39周 41周 43周 45周 47周 49周 51周

**第 10 页**

- `table_row`/kept reasons=['tbl[0]'] （30 字）：下载日志已记录，仅供内部参考扫码获取更多服务策略专题研究报告
- `table_row`/kept reasons=['tbl[0]'] （15 字）：敬请参阅最后一页特别声明 10
- `table_row`/kept reasons=['tbl[0]'] （200 字）：图表21：对于国内而言，主要石化产品库存同样降至过去5 年同期较低水平甲醇：华南港口库存量（万吨） 乙二醇：浙江、江苏港库存量（万吨） 2026 2025 2024 2023 2022 2026 2025 2024 2023 2022 60 140 120 50 100 40 80 30 60 20 40 10 20 0 1 3 5 7 9 11 13 15 17 19 21 23 25 27 2

**第 11 页**

- `heading`/kept reasons=['heading_by_font_size'] （8 字）：策略专题研究报告
- `heading`/kept reasons=['heading_by_font_size'] （12 字）：敬请参阅最后一页特别声明
- `heading`/kept reasons=['heading_by_font_size'] （2 字）：11
- `heading`/kept reasons=['heading_by_font_size'] （8 字）：扫码获取更多服务

**第 12 页**

- `table_row`/kept reasons=['tbl[0]'] （30 字）：下载日志已记录，仅供内部参考扫码获取更多服务策略专题研究报告
- `table_row`/kept reasons=['tbl[0]'] （15 字）：敬请参阅最后一页特别声明 12
- `table_row`/kept reasons=['tbl[0]'] （115 字）：5、风险提示海外货币政策预期大幅收紧：如果由于滞胀预期持续导致货币政策预期大幅收紧，那么市场可能存在超预期下跌的风险。 AI 产业趋势迎来重大突破：如果AI 产业趋势出现重大突破，那么市场将会重新回到科技主线，防御思维就不再适用。

**第 13 页**

- `table_row`/kept reasons=['tbl[0]'] （30 字）：下载日志已记录，仅供内部参考扫码获取更多服务策略专题研究报告
- `table_row`/kept reasons=['tbl[0]'] （15 字）：敬请参阅最后一页特别声明 13
- `table_row`/kept reasons=['tbl[0]'] （200 字）：特别声明：国金证券股份有限公司经中国证券监督管理委员会批准，已具备证券投资咨询业务资格。形式的复制、转发、转载、引用、修改、仿制、刊发，或以任何侵犯本公司版权的其他方式使用。经过书面授权的引用、刊发，需注明出处为“国金证券股份有限公司”，且不得对本报告进行任何有悖原意的删节和修改。本报告的产生基于国金证券及其研究人员认为可信的公开资料或实地调研资料，但国金证券及其研究人员对这些信息的准确性和完整性

### 被本材料阻断的目标（4）

| target_id | role | 所需引文 | 依赖 | 问题 |
|---|---|---|---|---|
| `2f8aa709-hike` | required | 8 月私营部门就业人数远低于市场预期，以及威廉姆斯+沃勒发表鸽派言论使得降息预期有所回落； （3）但周五晚的新增非农就业16.2 万人，远超市场预期（5.6 万人） ，同时上修了6 月、7 月的非农就业数据，这又让9 月加息预期再度上升。尽管数据本身结构上具有争议，目前来看，9 月加息预期在50%-60%之间 | header_refs, row_labels, footnotes | 国金证券认为市场对美联储9月加息概率定价在什么区间？8月新增非农就业人数是多少？ |
| `2f8aa709-oil` | required | 与之对应的是， 霍尔木兹海峡通航量再度接近清零， 布油价格重回95 美元/桶以上。 | header_refs, row_labels, footnotes | 美伊冲突再度升级背景下，霍尔木兹海峡通航量和布油价格情况如何？ |
| `2f8aa709-alloc` | required | 第一， 商品侧，能源是首要推荐，以煤炭、石油、油运和炼化为代表的能化链条将继续受益于全球对能源的补库需求。有色金属（铜、金、铝）作为美元对立面资产，当前压制因素只是外生变量，9 月 FOMC 会议之前等待时机。 第二， 防御思维下， 红利风格受益于绝对收益者的切换，高股息+低波动+稳定现金流的红利资产仍是绝对收益资金的核心回流方向。 第三， 紧缩预期下， 全球制造复苏阶段性需等待逆风过去，出口链条（工程机械、电网设备等）等资产仍具备配置价值。 | header_refs, row_labels, footnotes | 国金证券在当前市况下的主要配置推荐有哪些？ |
| `2f8aa709-fedtable` | supplementary | 美联储官员 表态 通胀仍是第一优先级：通胀仍然高于2%的目标，因此美联储当前的主要关注点应该放在价格上；以PCE衡量的2%目标是坚定、固定的目标。 | - | 报告中美联储官员沃什、威廉姆斯、沃勒对通胀与加息的表态各是什么？ |

### 裁决（待人工填写；本包不代签）

- [ ] `acknowledged`　- [ ] `re-extract`　- [ ] `reject`
- reviewer：__________　日期：__________
- 理由：______________________________________________

## 9. `holdout-macro-012`（macro）

- 来源文件：`2026-09-06_2026.09.06-兴业证券-极致轮动如何收敛-探讨几个契机-733fc399.pdf`
- `source_id`：`f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279`
- `build_id`：`fa066c5a178c02128b5058d62ccaff442fa3004bd6d43e1189f6f75257900209`
- 修订：parse_rev=578b3d8f0b10715ef3f1ccb1b6a1f450f90ea3ca1e8a95e80707c480657b564f, clean_rev=0fea86694f5d68dda9568b38fc81a7f89093706c3058105ff9693400db016853, chunk_rev=c8a41ddc5ae48e11379a64733867b0c4885b9f9f4b2552541e115e6ac26b826f
- 规模：units 278 / chunks 61
- 门禁结论：`blocked_by_publish_gate`
- 门禁原因：publish 拒绝：存在未解决的质量缺口（gap_regions 非空，须按架构 §7.3 处置）: ['issue:table_lines_without_extraction:page:8']（table_lines_without_extraction@page:8）

### 缺口页

| 页 | 缺口类型 | 该页已提取单元 | 单元类型分布 | table 单元 |
|---:|---|---:|---|---:|
| 1 | `image_region_small` | 32 | heading 1, paragraph 30, table_row 1 | 0 |
| 2 | `image_region_small` | 10 | heading 3, paragraph 6, table_row 1 | 0 |
| 3 | `image_region_small` | 22 | heading 10, paragraph 10, table_row 2 | 0 |
| 4 | `image_region_small` | 13 | heading 7, paragraph 4, table_row 2 | 0 |
| 5 | `image_region_small` | 18 | heading 8, paragraph 5, table_row 5 | 0 |
| 6 | `image_region_small` | 34 | heading 17, paragraph 4, table_row 13 | 0 |
| 7 | `image_region_small` | 30 | heading 16, paragraph 3, table_row 11 | 0 |
| 8 | `image_region_small`, `table_lines_without_extraction` | 45 | heading 1, paragraph 44 | 0 |
| 9 | `image_region_small` | 15 | heading 10, paragraph 3, table_row 2 | 0 |
| 10 | `image_region_small` | 16 | heading 6, paragraph 2, table_row 8 | 0 |
| 11 | `image_region_small` | 43 | heading 7, paragraph 25, table_row 11 | 0 |

### 缺口页已提取文本样例

**第 1 页**

- `table_row`/kept reasons=['tbl[0]'] （20 字）：策略研究 | A 股市场策略证券研究报告
- `paragraph`/kept （14 字）：请阅读最后评级说明和重要声明
- `paragraph`/kept （4 字）：1/11
- `paragraph`/kept （4 字）：报告日期

**第 2 页**

- `table_row`/kept reasons=['tbl[0]'] （14 字）：策略研究 | A 股市场策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （14 字）：请阅读最后评级说明和重要声明
- `paragraph`/kept （4 字）：2/11
- `heading`/noise reasons=['heading_by_font_size', 'toc_heading'] （2 字）：目录

**第 3 页**

- `table_row`/noise reasons=['tbl[0]', 'header_repeated_geometric'] （14 字）：策略研究 | A 股市场策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （14 字）：请阅读最后评级说明和重要声明
- `paragraph`/kept （4 字）：3/11
- `heading`/kept reasons=['heading_by_font_size'] （13 字）：一、近期市场极致轮动的背后

**第 4 页**

- `table_row`/noise reasons=['tbl[0]', 'header_repeated_geometric'] （14 字）：策略研究 | A 股市场策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （14 字）：请阅读最后评级说明和重要声明
- `paragraph`/kept （4 字）：4/11
- `heading`/kept reasons=['heading_by_font_size'] （24 字）：图3、市场对9 月加息的预期跟随各类事件反复摇摆

**第 5 页**

- `table_row`/noise reasons=['tbl[0]', 'header_repeated_geometric'] （14 字）：策略研究 | A 股市场策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （14 字）：请阅读最后评级说明和重要声明
- `paragraph`/kept （4 字）：5/11
- `heading`/kept reasons=['heading_by_font_size'] （33 字）：图5、Token 价格自6 月以来持续下行，近期算力价格也高位回落

**第 6 页**

- `table_row`/noise reasons=['tbl[0]', 'header_repeated_geometric'] （14 字）：策略研究 | A 股市场策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （14 字）：请阅读最后评级说明和重要声明
- `paragraph`/kept （4 字）：6/11
- `heading`/kept reasons=['heading_by_font_size'] （36 字）：我们倾向于认为，“分久必合”，极致的轮动不是常态，后续大概率将通过宏观、

**第 7 页**

- `table_row`/noise reasons=['tbl[0]', 'header_repeated_geometric'] （14 字）：策略研究 | A 股市场策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （14 字）：请阅读最后评级说明和重要声明
- `paragraph`/kept （4 字）：7/11
- `heading`/kept reasons=['heading_by_font_size'] （48 字）：一是随着Anthropic 上市临近，即将披露的ARR 数据。Anthropic 大概率将在10

**第 8 页**

- `paragraph`/noise reasons=['header_repeated_geometric'] （14 字）：策略研究 | A 股市场策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （14 字）：请阅读最后评级说明和重要声明
- `paragraph`/kept （4 字）：8/11
- `paragraph`/kept （24 字）：图11、9-11 月，北美大厂重要会议与事件梳理

**第 9 页**

- `table_row`/noise reasons=['tbl[0]', 'header_repeated_geometric'] （14 字）：策略研究 | A 股市场策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （14 字）：请阅读最后评级说明和重要声明
- `paragraph`/kept （4 字）：9/11
- `heading`/kept reasons=['heading_by_font_size'] （35 字）：这三条应对思路共同导致的，是景气投资的失效。衡量高景气行业龙头股表现的

**第 10 页**

- `table_row`/noise reasons=['tbl[0]', 'header_repeated_geometric'] （14 字）：策略研究 | A 股市场策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （14 字）：请阅读最后评级说明和重要声明
- `paragraph`/kept （5 字）：10/11
- `heading`/kept reasons=['heading_by_font_size'] （26 字）：表1、7 月以来2026E 净利润上修的典型细分方向

**第 11 页**

- `table_row`/noise reasons=['tbl[0]', 'header_repeated_geometric'] （14 字）：策略研究 | A 股市场策略
- `paragraph`/noise reasons=['footer_repeated_geometric'] （14 字）：请阅读最后评级说明和重要声明
- `paragraph`/kept （5 字）：11/11
- `heading`/noise reasons=['heading_by_font_size', 'disclaimer_heading'] （5 字）：分析师声明

### 被本材料阻断的目标（4）

| target_id | role | 所需引文 | 依赖 | 问题 |
|---|---|---|---|---|
| `f3b28791-rotation` | required | 近期市场给人的最大感受，依然是混沌、轮动、缺乏主线。我们构造的行业轮动强度指标仍在持续上行，本周再创年内新高。 | header_refs, row_labels, footnotes | 兴业证券认为近期A股市场呈现什么特征？行业轮动强度指标走势如何？ |
| `f3b28791-fedwatch` | required | 几个影响美联储决策的重要观察点已不远，有助于市场分歧的弥合、宏观不确定性的下降。包括 9.11 美国 CPI 数据，以及 9.17 FOMC 会议。 | header_refs, row_labels, footnotes | 兴业证券建议重点观察哪些影响美联储决策、有助于降低宏观不确定性的事件节点？ |
| `f3b28791-table1` | required | 板块 一级行业 二级行业 7 月以来 2026E 净利润上修幅度 2026 年预测净利润增速 7 月以来 涨跌幅 年初以来 涨跌幅 龙一 龙二 龙三 AI 算力硬件 电子 光学光电子 27.1% 194% -29.6% 6.9% 京东方 A 惠科股份 TCL 科技 | - | 兴业证券表1中，7月以来2026E净利润上修的典型细分方向包括哪些？电子光学光电子的数据如何？ |
| `f3b28791-regression` | required | 随着后续轮动收敛的契机临近、 基本面定价权重提升，对于今年宏观流动性收紧、定价主要矛盾转向盈利的市场环境中，受益的仍将是景气投资的回归。 | header_refs, row_labels, footnotes | 在极致轮动收敛之后，兴业证券认为哪种投资风格有望回归？ |

### 裁决（待人工填写；本包不代签）

- [ ] `acknowledged`　- [ ] `re-extract`　- [ ] `reject`
- reviewer：__________　日期：__________
- 理由：______________________________________________
