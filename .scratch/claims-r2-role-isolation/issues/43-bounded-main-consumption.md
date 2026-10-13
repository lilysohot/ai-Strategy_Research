# 43 · 两个主快照的有界 M_main 消费闭环

Status: completed
Execution: 已完成
Type: task
Blocked by: 42 已完成发布与正向查询

## 目标与授权

2026-10-13 用户指令：“用两个主快照各跑一个有界问题，只验证消费链，不扩大抽取范围”。据此各执行一条独立 M_main 研究运行：工业富联主快照回答云计算业务同比增长；光模块主快照回答 Q2 800G 出货是否超预期。

每条运行只允许查询指定 source/build 的已发布语义记录，不使用 web、`corpus_search`、`corpus_fetch`、市场工具或其他快照；须完成 `delivery → context_use → report_reference`，提交 `corpus_submit_manifest` 并通过 A4 强制校验。发布目录以只读挂载提供。

## 预算与边界

- 问题数：2；每主快照 1 题。
- 每题 `max_turns=8`，并发 1，自动重试沿用 M_main 现行客户端策略并完整记账。
- 新增提取调用 0；生产 PG 访问 0；不改抽取产物、裁定、发布内容或范围。
- 本票只验已发布证据的真实送达、使用和报告引用，不声明整篇覆盖或研究质量。

## 验收

- 每题至少一次 `corpus_semantic_query`，其完整记录实际进入 M_main 请求。
- 最终答案使用送达记录，并提交可解析的 `semantic_references`。
- A4 在强制模式下通过，引用回溯到本题唯一 publication/snapshot。
- 保存问题、运行配置、调用与 token 账、工具轨迹、最终答案和验收结果。

## Comments

- 两题均在只读 publication 挂载、A4 enforce 和两工具白名单下完成；各 3 轮、2 次工具调用。
- 工业富联送达 2 条记录，结论为“材料称工业富联云计算业务同比增长 75.7%。”；光模块送达 3 条记录，最终引用直接证据 `itm_bf5fa66fb7be5a02`，结论为“材料判断 Q2 800G 出货超预期。”
- 两次 A4 边界复算均为 `verified`、1 supported、0 partial、0 unsupported、0 verification errors，`boundary_answer_status=complete`。
- 光模块第 2 轮首次模型流 180 秒无 chunk，现行客户端自动重试成功；失败尝试无 token 回执，已单列记账。总计 6 个成功模型响应、1 个 stalled attempt、4 次工具调用；新增抽取调用 0、生产 PG 访问 0。
- 两个 workflow 内部均为 `answer_status=complete` 且 A4 `boundary_answer_status=complete`，但 terminal task runner 将 `reporter=false + stopped_by=no_tool` 渲染为 `run incomplete`，未生成 `outputs/` 最终报告。原始最终文本及全部消费/A4 工件已保存；消费链验收通过，CLI 完成态接缝另列后续修复，不能写成 terminal deliverable 已发布。
- 该 CLI 接缝已由 [Issue 44](44-cli-complete-no-tool.md) 修复并补回归；历史运行不追溯改写，后续显式 complete 的 `no_tool` 终态可正常交付。
- 证据：[81-bounded-main-consumption-20261013](../evidence/81-bounded-main-consumption-20261013/README.md)。两份 publication 的显式缺口和 `review_required` 状态保持不变，本票不扩大为整篇覆盖或生产放行。
