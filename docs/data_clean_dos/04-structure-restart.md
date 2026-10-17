# 04 · 结构重启与 A/B 基线（v14）

> 状态：`S4_FROZEN_MATRIX_PASSED` · 2026-10-17。S0 已建立结构契约、兼容投影和
> control 绑定；S1 已接入 PDF 表格成员、表头、行标签、表题与表注关系；S2 修复
> 表格文字被伪网格线拆散，以及结构优先排序挤出词法最佳正文的问题；S3 修复 compact
> 分页中结构元数据先于正文占满预算的问题；S4 修复通用查询只按单块最高分筛来源的问题。
> 冻结零模型矩阵达到 51/51。OCR、向量和 clean 策略均未改变。v13 的
> `CLOSED_WITH_ACCEPTED_EXCEPTIONS` 是历史轮次结论，保持不变。

## 1. 本轮入口

实现从 reader 输出 seam 开始：跨格式 reader 输出节点、来源坐标和有依据的关系；
现有 clean/chunk 继续消费逐字段等价的 `CandidateUnit` 投影。这样先解决解析阶段拥有
结构、下游却反复猜测结构的问题，再分别验证表格、标题、多栏、OCR 和检索改动。

代码入口：

- `plugins/corpus/preparation/structure.py`：结构节点、关系、文本来源及不变式。
- `plugins/corpus/preparation/readers/base.py`：shadow 结构生成和兼容投影。
- `plugins/corpus/preparation/engine.py`：`parse-checkpoint-4` 完整结构往返，包括不参与
  兼容投影的 table/cell 节点。

## 2. Control 绑定

机器可读清单见 [v14-control-manifest.json](v14-control-manifest.json)。它绑定：

- commit `669b7d4a8540c38d47cf642dc0de4d879eb28c4f`；
- `reader-pdf-11`、`clean-5`、`chunk-5`、`index-4-zhcfg-2`；
- 来源盘点、51 项 holdout、评分器、历史结果与收尾报告的 SHA-256；
- 历史结果 42/51（required 31/36、supplementary 11/15）。

2026-10-17 已在 `e6_holdout_corpus` 隔离库重新执行正式构建和只读验证：12/12 来源
发布且活动 build 与预期一致；51 项重新得到 42/51（required 31/36、supplementary
11/15），失败分类仍为 quote 5、dependency 1、fetch 2、source 1。当前状态已改为
`reproduced`；51 项的角色、通过状态、首个失败点、命中/提供/计划/分页/完整性/引文
字段与冻结结果逐项一致。本次证据保存在 `.scratch/corpus-structure-restart/`，未覆盖 v13 产物。

## 3. S0 A/B 变量

| 项目 | control | candidate |
|---|---|---|
| 来源、目标、评分器 | manifest 固定值 | 完全相同 |
| reader 提取文本 | 当前 `CandidateUnit` | 相同文本的结构 shadow 投影 |
| OCR | 关闭 | 关闭 |
| 向量检索 | 关闭 | 关闭 |
| clean/chunk/index/search/fetch | 当前版本 | 当前版本 |
| 唯一变量 | 无结构对象 | 节点 + 显式阅读顺序 + 兼容投影 |

## 4. S0 通过门

1. `project_candidate_units(result.structure) == result.units`，逐字段一致。
2. 解析检查点恢复后的 `ReaderResult` 与首次解析结果相等。
3. reader/clean/chunk/engine focused tests 零回归。
4. 隔离库重放得到 42/51，且 51 项逐 target 状态与冻结结果一致。
5. 在第 4 项完成前，不启用表头、行标签、标题、多栏等行为变化关系。

## 5. S1 表关系候选

S1 只处理有 PDF 网格、阅读序和相邻来源证据支持的关系：

- 表格和单元格成为不参与 `CandidateUnit` 投影的结构节点；
- 发射组、表格和单元格以 `contains` 连接；
- 多层表头按视觉顺序最多识别三层，生成 `header_for` 与 `continuation_of`；
- 数据行首个数值格之前的紧凑格生成 `row_label_for`；
- 同页、相邻表格之间最近的编号表题，以及表后连续的来源／注释行，分别生成
  `caption_of` 和 `footnote_of`；
- 关系派生的紧凑表上下文只进入首个表头单元的 `label_path`。文字层漏掉一个期间字符时，
  仅在表题存在唯一完整期间且删去一个字符可与残缺表头精确相等时修复派生标签；
  `raw_text` 不改写。

解析器版本升为 `reader-pdf-12`。解析检查点升为 `parse-checkpoint-4`，保存完整结构节点，
避免 rich structure 在恢复时退化为扁平 shadow。

## 6. S1 A/B 结果

机器可读结果见 [v14-s1-ab-report.json](v14-s1-ab-report.json)，运行证据保存在
`.scratch/corpus-structure-restart/`。control 使用 `e6_holdout_corpus`，candidate 使用
`v14_s1_table_corpus`；两者均为 12/12 活动发布，并使用同一 51 项零模型评分器。

| 指标 | control | S1 candidate | 门槛 |
|---|---:|---:|---:|
| 全部 | 42/51 | **46/51** | ≥44/51 |
| required | 31/36 | **33/36** | ≥32/36 |
| supplementary | 11/15 | **13/15** | ≥12/15 |
| 既有通过项回归 | — | **0/42** | 0 |

预定的两个结构目标都恢复：

- `f86c6d2c-cxotable`：表题中的 `2026H1` 与多层表头关联后，四个表头依赖全部送达；
- `f3b28791-table1`：第三层表头、折叠数据行和两条表注形成同一证据上下文，逐字引文、
  10 个表头、行标签和脚注全部通过。

另有两个正向外溢：`c1ddcd8a-realestate` 从引文缺失恢复，`d179b615-hikerate` 从分页取回
不完整恢复。42 个 control 通过项无回归。候选仍有 5 项失败：3 项引文未送达、1 项分页
未完成、1 项来源未提供；它们不属于本次两个表关系目标。

持久化不变量逐来源核对：12 个来源的 `ordinal/kind/status/reasons/raw_text/page/bbox/cells`
完全一致；376 个表格单元的派生 `label_path` 发生预期变化。候选没有新增超长块或发布阻断。

## 7. S2 引文送达候选

机器可读结果见 [v14-s2-ab-report.json](v14-s2-ab-report.json)。S2 以 S1 的 46/51 为
control，candidate 使用独立库 `v14_s2_quote_corpus`，同样发布 12/12 来源并重跑冻结的
51 项零模型矩阵。

| 指标 | S1 control | S2 candidate | 门槛 |
|---|---:|---:|---:|
| 全部 | 46/51 | **49/51** | ≥49/51 |
| required | 33/36 | **35/36** | ≥35/36 |
| supplementary | 13/15 | **14/15** | ≥14/15 |
| 既有通过项回归 | — | **0/46** | 0 |

三项预定目标全部恢复：

- `c1ddcd8a-summarytable`：PDF 原生文字层完整含有 `0.9% / 4.2% / -2.4% / -0.6%`，
  `find_tables` 的伪竖线却把一个词切成数个格，旧的中心点匹配把外侧碎片推到页尾。S2 在
  同一视觉行有横向交叠时，将碎片绑定回同一个原生文字位置；解析器版本升为
  `reader-pdf-13`，没有猜测或补造字符。
- `b7e932c8-index`、`b7e932c8-industry`：正确正文块在两次查询中均为文档内词法第 1 名，
  但通用的“行业／涨幅”表格标签使它落到结构带第 3 名；五来源轮询下每来源只送达前两带。
  S2 保留结构最佳带为第一席，同时固定保留词法最佳带为第二席，再接其余结构带。

持久化审计显示：12 个来源逐页非空白字符多重集完全相同，所有非表格单元逐字段稳定；变化
只对表格碎片重新分组和排序，7 个来源出现页内表格序列变化。目标螺纹钢引文已在权威单元中
逐字存在。冻结矩阵没有既有通过项回归。

仍有两项失败，且失败类别已不再包含 `quote_not_delivered`：

- `5e305376-fedrate`：`fetch_incomplete`，进入分页／取回实验臂；
- `f7f65d7e-risk`：`source_not_offered`，进入来源召回实验臂。

## 8. S3 分页完整性候选

机器可读结果见 [v14-s3-ab-report.json](v14-s3-ab-report.json)。S3 直接复用
`v14_s2_quote_corpus`，没有重建或重新发布语料；唯一变量是 `corpus_fetch` 在 compact 页的
预算回退策略。

`5e305376-fedrate` 的正确来源已有 3 个 fetch plan、50 个 locator。旧实现遍历 28 页后，
`heading:0128` 仍为 `budget_exceeded`：该标题正文很短，但它在 34 块证据带内携带一条指向
每个成员的关系，关系清单使空正文 item 也超过 6000 字符。目标引文已经送达，整组计划却因
该 unresolved 成员不能宣称完整。

S3 仍先尝试原 compact 结构元数据；只有固定字段无法给正文留下预算时，才把重复关系清单和
标签路径替换为 `relations_elided`／`relation_count` 或
`label_path_elided`／`label_path_count`。正文、定位、哈希、结构状态、关系状态和游标继续送达；
调用方可提高预算重取完整结构诊断。

| 指标 | S2 control | S3 candidate | 门槛 |
|---|---:|---:|---:|
| 全部 | 49/51 | **50/51** | ≥50/51 |
| required | 35/36 | **36/36** | 36/36 |
| supplementary | 14/15 | **14/15** | ≥14/15 |
| 既有通过项回归 | — | **0/49** | 0 |

目标重放保持 3 个 plan 和 28 页不变，`fetch_complete` 从 false 变为 true，未解决项和成员
错误均归零；冻结 51 项矩阵仅该 required 目标转绿。S2 的字符与单元不变量继续有效，因为
数据库和 build 未改变。

## 9. S4 来源召回候选

机器可读结果见 [v14-s4-ab-report.json](v14-s4-ab-report.json)。S4 继续复用
`v14_s2_quote_corpus`；唯一变量是 PG 候选池的来源级排序信号。

`f7f65d7e-risk` 的风险正文一直存在于活动 build，也在 52 个原始命中中命中“风险提示”；
旧排序按每个来源的单块最高分确定文档序。问题“本期研报列出了哪些主要风险提示？”使全部
12 个来源都命中通用风险措辞，目标来源按最高块分排第 12，而选择层只保留前 5 个来源，
所以不是抽取或切块缺失，而是来源选择前已被淘汰。

S4 在候选 SQL 内计算候选查询词元在**整份来源全部命中块**上的去重覆盖数：先按来源词元
覆盖数排序，再按既有来源最高块分、块分和稳定句柄排序。候选集合、来源内 40 块上限、
结构带选择和 10-hit 产品上限均不变。目标查询中，“本期”位于该研报的其他块，“风险／提示”
位于风险正文；跨块来源覆盖使目标来源从第 12 升至第 4。

| 指标 | S3 control | S4 candidate | 门槛 |
|---|---:|---:|---:|
| 全部 | 50/51 | **51/51** | 51/51 |
| required | 36/36 | **36/36** | 36/36 |
| supplementary | 14/15 | **15/15** | 15/15 |
| 既有通过项回归 | — | **0/50** | 0 |

目标在正常 10-hit 响应中得到 2 个有界计划、7 个 locator 和 2 页完整取回；来源提供、分页
完整性、逐字引文与全部依赖均通过。冻结矩阵没有残留失败，S2 的字符与单元不变量继续有效，
因为数据库和 build 未改变。

## 10. S5 真实模型 A/B 预检

首轮机器可读冻结清单见 [v14-s5-real-model-manifest.json](v14-s5-real-model-manifest.json)，第 2、
3 次扩展冻结清单见 [v14-s5-real-model-manifest-r3.json](v14-s5-real-model-manifest-r3.json)，结果见
[v14-s5-real-model-ab-report.json](v14-s5-real-model-ab-report.json)。三道预注册题为
`f86c6d2c-cxotable`（复杂表格）、`5e305376-fedrate`（跨片段／分页）和 `f7f65d7e-risk`
（来源召回）。每题每臂完成 3 个独立 `react` 会话、并发 1、相同 40 轮／30 分钟预算；控制臂
固定在提交 `669b7d4a` + `e6_holdout_corpus`，候选臂固定在提交 `28871184` +
`v14_s2_quote_corpus`。代理只收到自然语言问题，金标在进程退出后才进入评分器。18 个正式会话
全部正常退出；首轮 6 条结果保持不变，第 2、3 次新增 12 个会话。

用户指定复用当前已配置的 `glm-5.3-flash` 及 API 凭据作为 judge；因此本轮 judge 是同提供商、
同模型评审，报告明确标为 **非独立裁判**。它可用于本轮预检，但不能支持“独立模型 A/B”结论。

| 指标 | control | candidate | 差异 |
|---|---:|---:|---:|
| 来源已提供 | 9/9 | 9/9 | 0 |
| 金标原文已取回 | 9/9 | 9/9 | 0 |
| 金标原文已送达 | 9/9 | 9/9 | 0 |
| 同模型 judge 回答通过 | 8/9 | **9/9** | +1 |
| 墙钟合计 | 3535.4 s | 2772.4 s | **-21.6%** |
| 工具调用 | 153 | 124 | **-19.0%** |
| `corpus_search` | 34 | 27 | **-20.6%** |
| `corpus_fetch` | 50 | 31 | **-38.0%** |
| input token | 5,344,048 | 4,205,387 | **-21.3%** |
| output token | 141,633 | 90,099 | **-36.4%** |
| cached token | 4,564,992 | 3,728,256 | **-18.3%** |

按问题观察三次独立会话的行为方差：

| 问题 | 臂 | judge | 墙钟均值 / CV | search 均值（范围） | fetch 均值（范围） | input 均值 / CV |
|---|---|---:|---:|---:|---:|---:|
| 复杂表格 | control | 3/3 | 338.5 s / 0.570 | 2.0（1–3） | 3.0（2–4） | 314,154 / 0.406 |
| 复杂表格 | candidate | 3/3 | 338.6 s / **0.208** | 1.3（1–2） | 3.0（2–4） | 269,956 / **0.073** |
| 跨片段／分页 | control | 3/3 | 81.2 s / 0.222 | 1.0（1–1） | 1.7（1–2） | 135,499 / **0.078** |
| 跨片段／分页 | candidate | 3/3 | 103.1 s / **0.050** | 1.0（1–1） | 1.0（1–1） | 172,205 / 0.180 |
| 来源召回 | control | 2/3 | 758.8 s / 0.480 | 8.3（5–15） | 12.0（2–27） | 1,331,696 / 0.697 |
| 来源召回 | candidate | **3/3** | **482.5 s / 0.312** | **6.7（5–8）** | **6.3（3–10）** | **959,635 / 0.504** |

复杂表格题两臂平均时延相同，但 candidate 的时延和 input 方差明显更低。跨片段题 candidate 平均
慢 21.9 秒、input 更高，但三次路径固定为 1 次 search + 1 次 fetch，质量稳定。主要收益来自来源
召回题：candidate 的平均时延低 36.4%，search 和 fetch 的上界均收窄，并保持 3/3。control 的
失败会话用了 15 次 search、27 次 fetch、1236.6 秒和 2,636,400 input token，却把单篇研报问题
扩成 12 篇汇总，因大量题外内容被 judge 判为不受证据支持。这是来源约束失稳，不是漏检索。

candidate 仅有一次可恢复工具错误：复杂表格第 3 次的一次 `corpus_fetch` 漏传 `doc_id`，最终仍
通过；control 无工具错误。S4 已证明目标来源在正常候选集合内，三次真实模型结果进一步表明 S4
降低了宽泛问句的查询及取回长尾，但模型仍会改写查询，后者应继续在模型工具使用层观测。

正式运行前发生过一次数据库定向预检失败：只设置 `CORPUS_TARGET_DB`、连接串仍指向
`postgres`，fail-closed 拒绝后立即停止；该次调用保留在报告的 `excluded_preflight_attempts`，
不进入 A/B 分母，但成本没有删除。运行器随后增加硬预检，要求实际 `current_database` 与每臂
目标一致且 12 个活动发布齐全。

回答代理的 token 已完整落盘；首轮 runner 没有保存 judge 调用的 token usage，第 2、3 次已保存
（control 4,362 input / 9,872 output，candidate 4,316 / 6,107）。因此回答代理成本可以完整比较，
judge 总成本只能比较后两次。首轮预执行 manifest 也未包含当时未跟踪 runner 的源码哈希，报告
保留预执行资产绑定，并另记当前后处理 runner 哈希；这些限制不改写质量与查询行为结果。

当前判定为 `pilot_repeats_pass_expand_51_matrix`：候选已满足三题三次的来源、取回、送达和回答门，
总体成本方向转为改善，关键来源召回题的长尾也收窄。该判定只允许进入冻结 51 项真实模型矩阵，
不构成生产发布门；使用独立 judge 后才能形成独立真实模型 A/B 结论。

## 11. 后续顺序

1. 保持 S4 冻结，扩展到 51 项真实模型矩阵；继续并发 1、每题独立进程和相同预算，并单列回答
   token、judge token、search／fetch 次数及长尾。更换独立 judge 后方可称为独立真实模型 A/B。
2. 51 项矩阵已无残留缺陷，因此 OCR、向量和多栏不再以这 12 份材料调参；各自建立新的
   外部 holdout 和独立候选臂，证明新增模块带来增益后再进入组合实验。
3. 发布前复跑版本绑定、回滚演练和真实模型门；生产指针切换仍需单独的发布步骤。

最终业务门仍为 51/51、required 36/36、supplementary 15/15、既有通过项零回归；
S4 已达到这组冻结零模型门。它证明当前 12 份 holdout 的正常检索／取回链可交付全部金标证据，
不等同于真实模型答案门、扫描件/OCR 泛化门或生产发布完成。
