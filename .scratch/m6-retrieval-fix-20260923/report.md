# M6 检索召回、证据完整性与负例拒答整改

日期：2026-09-23

## 结论

保持冻结 30 题、金标、评分器、95% 阈值和产品调用参数不变，真实注册
`corpus_search` → `corpus_fetch` 链路现已通过产品门：

- 可回答题 QuestionPass：24/24；
- 可回答题 EvidencePass：24/24；
- 无答案负例：6/6 拒答，false positive = 0；
- 工具失败：0；
- 模型调用：0。

机器可读结果见 [product-summary.json](product-summary.json)，逐题观测见
[product-raw-default-details.json](product-raw-default-details.json)。

## 基线与根因

r5d 真实产品基线中，默认自然问题按 websearch AND 执行，QuestionPass/EvidencePass
均为 0/24；统一 OR 诊断虽然把 QuestionPass 提升到 22/24，但 EvidencePass 只有
13/24，并把 6 个负例全部误报；旧 abstain 又会误拒 24/24 正例。

诊断确认四个相互独立的实现原因：

1. 自然问题没有转换为内容词元 OR 候选查询，任一题面附加词缺失就会整题归零；
2. 全局候选上限可被单一长文档占满，来源标题也未参与召回；
3. 同一 PDF 页的稀疏命中被拆成多个证据带，且产品工具只暴露单个锚点块；
4. abstain 对所有问题执行严格 AND，无法区分普通研究问题与“这些材料是否提供某事实”的语料可用性询问。

证据链还有两项完整性问题：相关性锚点被提前后会打乱权威文档顺序；结构化 cell
只校验值是否存在于整个块，未校验值是否属于声明的 `unit_id`。

## 修复

- 产品服务把原始自然问题分词后，仅用实质词元生成内部 OR 候选查询；原始题干仍原样传入注册工具和拒答判定。
- PG 候选同时覆盖 chunk 正文与来源原名，每来源最多 40 个候选，总池下限 200，再执行固定 top-5 / band-cap-8 的有界选择。
- 同页稀疏命中只在既有最大宽度 49 和 pool cap 内合并；不同页不合并。
- 搜索结果按来源返回一个相关性锚点，同时提供按原文序排列的有界 `context_locators`；取证仍逐句柄经过权威 `corpus_fetch`。
- 观测器保持 `context_locators` 的原文顺序，避免长引文被锚点重排破坏。
- `corpus_fetch` 暴露由权威 unit 网格派生的 cell；观测器要求 cell 的页码、unit 和 unit span 全部一致，错归属 fail-closed。
- abstain 默认开启，但只对明确的语料可用性询问执行严格证据存在性检查；普通研究问题直接放行，显式 `off` 仍可回滚。

## 验证

- 真实 30 题产品链：24/24 QuestionPass，24/24 EvidencePass，0 FP，0 工具失败；重复运行并在隔离库重建后复跑，结果一致。
- PostgreSQL authority 集成：12 passed，包含自然问题附加未命中词仍召回、缺失事实语料询问拒答；测试后按 I3-7 流程恢复 8/8 published+active。
- PG 排序/候选门：11 passed，覆盖 chunk/标题双候选、活动 build、每来源 40 上限与稳定顺序。
- 全仓 pytest：2961 passed / 2 failed / 17 skipped。两项失败均为整改前既有且与本模块无关：固定 2026-09-09 市场时间夹具在当前日期触发 stale warning；旧 React profile 工厂断言拿到空工具集。
- 静态门：CI 路径 ruff 通过；pyright 0 errors；import smoke stage 1 为 365/365、stage 2 为 414/414；symbol closure 0 missing。

未运行模型 preflight、答案语义模型评测、留出调参、生产 5432 或 I4。隔离库仅使用
`127.0.0.1:543/i2_sandbox_corpus`。
