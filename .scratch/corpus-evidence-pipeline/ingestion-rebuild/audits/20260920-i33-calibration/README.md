# I3-3 首轮开发校准（r39，未达标）

前置 I3-1 已在 r38 收口：批准八份全部发布，光力 p7 已通过区域判级，13 处缺口 acknowledged。
本轮实跑冻结 30 题（24 有答案、6 无答案），固定 scorer、gold、top_k=5、门槛19/20、关键题全过、
误报/伪引用上限0。零模型，原 i3-e2e 守卫；生产库、来源、金标、索引与检索代码均未改。

## 先固定方案，再执行

[calibration-plan-v2.json](calibration-plan-v2.json) 在检索前绑定脚本、金标、评分器与 r38。
最多两轮，各执行一次：整句 websearch 基线；仅由问题原文经原 zhcfg 分词生成 OR 查询的候选。
候选上限2000块，饱和即停；按原块排名首次出现归并文档 Top-5，每文档最多取原排名前8块。
不按金标提供查询词、定位页或补取证据，原生 fetch 失败立即中止，不伪装 no_match。
接线新增9项合成反例覆盖重复文档、坏来源/build/active/text、取证异常和真实坐标。

第一次入口启动在连接 PG 前因 API 名称 document_handle 错写而停止；只修为已有 build_handle。
原脚本与计划已保留为 before-import-fix，v2 记录修正。两轮参数、范围、停止条件未变。

## 实测结果

| 方案 | 分类 | DocRecall@5 | QuestionPass@5 | EvidencePass@5 |
|---|---|---:|---:|---:|
| 整句基线 | company / industry / macro 各类 | 0% | 各0/8 | 各0/8 |
| 问题词元 OR | company | 100% | 8/8 | 1/8 |
| 问题词元 OR | industry | 100% | 8/8 | 2/8 |
| 问题词元 OR | macro | 100% | 8/8 | 2/8 |

基线30题全部无命中。OR 候选30题均有命中，六道无答案题全部误报，评分器同时登记
6条 fabricated_citation（负例返回证据的评分口径，并非本轮生成了答案文字）。两轮均不通过。
原查询的 native_tsquery 显示大量问题词按 AND 串接；OR 恢复文档召回但过于宽泛，不能直接采用。
候选没有部署或写回生产检索路径。I3-3 仍进行中，M6 未放行。

## 失败分解与下一轮方向

[只读诊断](evidence-diagnosis.json) 对候选缺失的54条目标逐项区分：

- **34条：引文未在 kept 单元按页拼接文本中逐字出现。** 先核对 source-gold 引文与正式读取器
  的空格/换行、表格结构、清洗保留映射；此统计不证明原 PDF 缺内容，也不授权改 gold。
- **14条：引文已保留，但没进本轮选出的证据块。** 下一轮应测试有界的块排名/上下文策略。
- **6条：返回文字含引文，但缺所需 locator。** 当前接线只输出原生 page；行列/cell 语义
  必须从真实结构映射，不能直接把 gold 的 row/col 标签贴到结果上。

六个无答案误报需单独检查检索结果是否足以支撑问题；不能把相关文档命中当成答案存在。
下一轮先解决34条逐字保留/映射原因及6条坐标接线，再预先限定召回与负例策略的试验预算。
本轮已按预声明两轮停止，未继续试分或改变预期。诊断扫描结果未加入原评分观察值。

## 可复验产物

- [汇总](calibration-summary.json)、[基线报告](baseline_literal_websearch-score.md)、[候选报告](candidate_question_lexemes_or-score.md)
- 两轮 trace/observations/score JSON 与 [原生取证回执](fetch-receipts.json)
- [身份映射](source-identity-map.json)：金标旧别名只按唯一 SHA 前缀映射活动来源，真实 build_id 保留
- `verify_calibration.py` 离线从原生回执重建观察值与评分，不访问 PG，不补证据
- [验证结果](validation-results.json)：collector 9 passed，ruff/pyright/符号闭合通过；
  全局 import_smoke 两阶段被既有零模型模块导入守卫拦截，明确不记通过；LLM preflight 未执行

`before-r39` 保存文档/验证器/索引编辑前字节。r38、原签署、原 guard/gold/来源均保留。
