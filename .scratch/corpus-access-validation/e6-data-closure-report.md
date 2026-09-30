# E5/E6 数据返回链路收尾报告

> 执行日期：2026-09-30。口径：只验证数据是否能经正式
> `corpus_search → fetch_plan → corpus_fetch` 分页链路完整返回；零模型调用。
> 留出材料只写入隔离数据库 `e6_holdout_corpus`，生产语料库未改动。

## 结论

数据返回机制本身已经闭环：凡通过正式发布门、进入活动语料的留出材料，冻结问题所需的
正文、表格行、表头、单位和必要脚注均能正确返回。当前总任务仍不能整体关闭，因为 12 份
留出材料只有 3 份通过发布门；另外 9 份存在真实读取质量缺口，38 个目标因此正确地表现为
`source_not_offered`，而不是模型错误、搜索错误或分页错误。

## 本轮修复

- 检索结果为每个命中提供同源、同命中的 `fetch_plan`，并按结构带分散取回，避免一个大带
  挤掉其他命中；结构标识符按大小写无关匹配。
- 表格行命中通过已持久化的 `label_path` 附带同页表头上下文；单块与分页取回均返回该结构
  元数据。
- 空内容、全失败分页和未解析 locator 不再被误报为完整取回。
- `clean-5` 修复免责区缓冲结算中 verdict 与 reason 不一致，原 `industry-006` 清洗异常消失。
- `reader-pdf-10` 拒绝把 PDF 解析器误折叠的整列数据复制成每行结构标签；原
  `industry-005` 的 15 个超大表格块降为 0，最大块 1199 字（上限 1800）。

## 验证结果

| 范围 | 结果 | 解释 |
|---|---:|---|
| 开发集必需证据 | 79/79 | 全部经正常问题、检索、同命中取回和分页送达 |
| 开发集全部证据 | 98/99 | 唯一失败为 `industry-001/e5` 补充数字序列，不影响该题必需证据 |
| 留出构建 | 3/12 发布，9/12 门禁阻断 | 12 份均完成构建，0 清洗/分块执行失败 |
| 已发布留出材料 | 13/13 | 必需 9/9、补充 4/4，正文与结构依赖均送达 |
| 全部留出目标 | 13/51 | 其余 38 项全部为 `source_not_offered`，与 9 份未发布材料一一对应 |

主要证据：

- `e5-data-delivery-dev.json`：开发集全量数据送达结果；
- `e6-holdout-build.json`：12 份留出材料的独立构建与正式发布门结果；
- `e6-data-delivery-published.json`：3 份已发布材料 13/13；
- `e6-data-delivery-holdout.json`：51 个目标的完整失败分类；
- `e5_data_delivery.py`：零模型验证器；
- `e6_prepare_holdout_db.py`：隔离库构建器，不伪造人工缺口裁决；
- `e6-human-gap-review-packet.md` / `.json`：9 份未放行材料的人工缺口复核包（逐份列出缺口页、
  该页已提取文本样例与被阻断目标），由 `e6_review_packet.py` 只读生成，供真实人工裁决，
  本身不含任何裁决、不写 `human-gap-review`；
- `e6-gap-prescreening.md` / `.json`：缺口预筛（非裁决），把 38 项被阻断目标的 `expected_quote`
  与冻结 build 的已提取文本、证据页是否落在缺口页做字面比对，由 `e6_gap_prescreen.py` 只读生成。

## 尚未放行的 9 份材料

| 样本 | 发布门缺口 |
|---|---|
| `holdout-industry-003` | `table_lines_without_extraction`：页 3、8、11、16、18、19 |
| `holdout-industry-004` | 页 1–27 的 `image_region_unreadable`；页 4、5、6、13、16–19 的表格线缺口 |
| `holdout-industry-006` | 页 6 图片不可读；页 3、14 表格线缺口 |
| `holdout-industry-007` | 页 6、7 表格线缺口 |
| `holdout-macro-008` | 页 11 图片不可读；页 4、5、9、14、15 表格线缺口 |
| `holdout-macro-009` | 页 9 图片不可读 |
| `holdout-macro-010` | 页 8 表格线缺口 |
| `holdout-macro-011` | 页 11 表格线缺口 |
| `holdout-macro-012` | 页 8 表格线缺口 |

这些缺口必须由真实人工复核作出 `acknowledged`／重新提取等裁决后才能发布。本轮没有代签
`human-gap-review`，也没有绕过发布门。完成裁决后，重跑隔离构建与 51 项数据送达验证；
在达到 51/51 之前，E6 和端到端总任务保持未关闭。

供裁决使用的复核包见 `e6-human-gap-review-packet.md`（同目录 `.json` 为结构化版本）：逐份给出
缺口页清单、该页已提取单元与文本样例、被阻断目标（`target_id`／所需引文／问题），并留出
`acknowledged`／`re-extract`／`reject` + reviewer 的空白裁决栏。该包只读冻结产物与隔离库
（只读事务），不代签、不动发布门。

在此基础上，`e6-gap-prescreening.md` 对 38 项被阻断目标做了机械预筛（**非裁决**）：把每项
所需引文做归一化后与冻结 build 的已提取文本比对，并核对证据页是否落在缺口页上。分布为
`leaning-acknowledge` 28（引文整条已提取，证据页最多只有 `image_region_small`）、`needs-human` 7
（证据页带 `image_region_unreadable` 或 `table_lines_without_extraction`）、`leaning-re-extract` 3
（`c1ddcd8a-summarytable`、`d179b615-chart3`、`f3b28791-table1`——引文与片段均未提取，缺口疑似正
压在该证据上）。该预筛不重跑检索/取回，引文存在不等于检索可达，仍须人工签署裁决。

## 工程门

- 清洗、PDF 读取、分块回归：77 passed；
- 检索、选择、取回、分页、消费与截断回归：157 passed，1 skipped；
- 目标文件 Ruff：通过。

