# E5/E6 数据返回链路收尾报告

> 执行日期：2026-09-30。口径：只验证数据是否能经正式
> `corpus_search → fetch_plan → corpus_fetch` 分页链路完整返回；零模型调用。
> 留出材料只写入隔离数据库 `e6_holdout_corpus`，生产语料库未改动。

## 结论

（2026-10-01 更新）12 份留出材料已全部通过正式发布门（12/12 published）；51 个评测目标中
42 个经 `corpus_search → fetch_plan → corpus_fetch` 正式链路完整送达。其余 9 项失败经零模型
逐项归因，全部单列为暂不支持项（见文末「2026-10-01 收口」），开发集 79/79 必需证据不受影响。

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

> （2026-10-01 注：本节为历史状态。9 份材料此后全部经人工裁决（38 acknowledge）+
> `reader-pdf-11` 普遍性修复 + 4 份合规 gap-review 放行，12/12 published。见文末收口章节。）

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

## 2026-10-01 收口：12/12 发布、42/51 送达、9 项单列

### 本轮经过

1. **人工裁决回填**：复核包 38 项全部 `acknowledged`（逐项源页诊断证据：3 项预筛 absent 为
   误报——引文已完整保留在 kept 单元；缺口页均为图表页假阳性或真大图页且证据页不相交）。
2. **reader-pdf-11 普遍性修复**：`_count_grid_lines` 只计 >40pt 长线段且要求交叉成网
   （`crossings >= H+V`），消除图表坐标轴/刻度线误判（25 处假阳性）；整页衬底背景图按
   `image_region_small` 记账。新增反例回归 `test_chart_page_lines_do_not_trigger_table_gap`。
3. **隔离重建与发布**：12/12 过发布门（generation=2 全部 published）；其中 4 份真实缺口
   （M6 页9 / M5 页11 / M3 页6 真大图、M9 页8 真表格）经合规 gap-review 放行——PAGE 级
   （缺口页 ≠ 证据页）3 份 + REGION 级（引文在单个 kept 单元精确出现且单元 bbox 与全部
   图像 bbox 不相交）1 份（industry-006），`store.put_gap_review` 内部校验全部通过。
4. **重跑 51 项数据送达验证**：42/51（`e6-data-delivery-holdout-rerun.json`）。

### 9 项失败的逐项归因（零模型、只读证据）

| target_id | role | first_fail | 根因与证据 |
|---|---|---|---|
| `b7e932c8-index` | required | quote_not_delivered | 引文 chunk `5a213a95:body:0002` 在候选池排 **#0** 且选带内含，但最终 10 条命中中该文档仅保留 `table:0014/0022`（perdoc 截断 + 结构重叠重排把表格挤前），引文 chunk 未进任何送达窗口。引文数据完好 |
| `b7e932c8-industry` | required | quote_not_delivered | 同上（同一 chunk `body:0002`、同一文档、同一机制） |
| `c1ddcd8a-realestate` | supplementary | quote_not_delivered | 同机制：引文 chunk `a6be5fb9:body:0001` 池排 **#1**（score 0.047），该文档仅 `table:0009/0002` 进最终命中。引文含全部 %/- 数据，整条存在于 kept 单元 unit:0011 |
| `f3b28791-table1` | required | quote_not_delivered | 引文核心 chunk `bb6c4f16:table:0015` **已送达**；27 个引文 token 中 25 个命中，仅 2 个表头 token（“净利润上修幅度”“年预测净利润增速”）因表头多行单元格跨单元拆散而不连续，验证器 `verbatim_quote` all-token 全量要求失败。数据（27.1%/194%/-29.6%/6.9%）完整在库 |
| `5e305376-fedrate` | required | fetch_incomplete | 单个 heading 块超 6000 字符 fetch 预算（`budget_exceeded`），compact 视图下分片未生效 |
| `d179b615-hikerate` | required | fetch_incomplete | 同上 |
| `f86c6d2c-cxotable` | supplementary | dependency_not_delivered | `row_labels` 依赖未命中（`_structured_label_in_text` 跨度内分词匹配失败） |
| `f7f65d7e-risk` | supplementary | source_not_offered | 检索 top-10 未提供该源 |
| `c1ddcd8a-summarytable` | supplementary | quote_not_delivered | **唯一真「单元格 % 拆分」**：unit:0053 = `螺纹钢\n元/吨\n3240\n0.9\n4.2\n.\n-0.\n6000`，`%` 全丢、`-2.4` 记为 `.`。reader-pdf-11 后仍存在，属 PDF 文本流单元格拆分 |

关键结论：**「% / - 拆分」不是主要失败模式**（9 项中仅 1 项 supplementary 为真），主要失败
模式是检索选择策略把 raw score 最高的正文引文 chunk 挤出送达窗口（3 项，含 2 required）。

### 单列决定与协议注记

按用户 2026-10-01 裁定，上述 9 项依 protocol §1「范围外与暂不支持项在验收报告中单列，
不计入分母，也不从分母移除」全部单列：支持范围内分母 42，送达 42/42。

**注记（诚实披露）**：§6.3 要求「预先指定的关键目标及其必要依赖 L1–L9 全通过」，本批
单列中含 5 项 required（index/industry/table1/fedrate/hikerate）。这些项的数据本身完整
（引文在库、可复算），失败发生在检索选择、fetch 预算与验证器比对口径三层机制，均为
已定位、可修的工程缺陷而非数据缺陷。若后续按严格口径复核，修复优先级为：
① 检索选择保底（perdoc 截断保 raw top-1 命中）；② fetch 超长块分片；③ 表头跨单元
quote 口径（`_quote_in_text` 允许部件级 span 匹配）；④ reader 单元格拼接（随 B 线
语料重建顺带）。

### 证据

- `e6-data-delivery-holdout-rerun.json`：42/51 重跑结果（`CORPUS_DSN` + `CORPUS_TARGET_DB`
  均指向隔离库）；
- `e6_diag_fetch.py` / `e6_diag_fetch2.py` / `e6_diag_table1.py`：引文 chunk 全 build 装配比对
  与 delivered 集合交叉验证；
- 检索链路复算：`query_lexemes → retrieval_query → search_with_coverage_bands` 候选池排名
  与选带内容（body:0002 池 #0 / body:0001 池 #1 / table:0015 池 #2，均在带内）；
- `e6-human-gap-review-packet.md`（已回填裁决）、`e6_apply_gap_review.py`（4 份放行记录）、
  `e6-holdout-build.json`（12/12 构建与发布门结果）；
- 回归：corpus 全量 306 passed（含新增反例 4）。

