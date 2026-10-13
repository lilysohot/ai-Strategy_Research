# 两个主快照的有界 M_main 消费验证

2026-10-13 按用户指令，对两个已发布主快照各运行一个独立问题。两次运行均使用 `max_turns=8`、串行执行、A4 enforce；发布目录由 bubblewrap 只读挂载。运行侧工具白名单仅含 `corpus_semantic_query`，其伴随工具 `corpus_submit_manifest` 由产品链自动绑定。

## 结果

| 运行 | 有界问题 | 轮次 / 工具调用 | 实际送达 | 最终结论 | A4 |
| --- | --- | --- | --- | --- | --- |
| 工业富联 `20261013-194110+0800-react-9e00` | 材料称工业富联云计算业务同比增长多少？ | 3 / 2 | 2 条完整记录 | 材料称工业富联云计算业务同比增长 75.7%。 | `verified`；1 supported、0 partial、0 unsupported |
| 光模块 `20261013-194545+0800-react-5e37` | 材料对 Q2 800G 出货是否超预期的判断是什么？ | 3 / 2 | 3 条完整记录 | 材料判断 Q2 800G 出货超预期。 | `verified`；1 supported、0 partial、0 unsupported |

两次运行的工具轨迹都严格为一次 `corpus_semantic_query` 加一次 `corpus_submit_manifest`，没有 web、旧 corpus search/fetch、市场工具或第二快照查询。工业富联引用 publication `sha256:0a91883776c853419648ed537d2ce76956760a24c48af638d390655f29516cb6` 的 `7f060c5a…dea4` 和 `itm_abebb2a7163927e9`；光模块引用 publication `sha256:cfd0b3582e1344d87ff5137774fba93a1829e337392fe0bc8aa87d23c1cf399d` 的直接证据 `itm_bf5fa66fb7be5a02`。

消费账确认所有查询记录均为 `delivered`，后续模型请求实际包含完整记录；最终回答逐字包含清单 `report_quote`。发布边界复算两次均为 `boundary_answer_status=complete`、`verification_errors=0`。因此 `delivery → context_use → report_reference` 在两个主快照上均已闭合。

终端外层另有一个状态接缝：两个 workflow 的内部停止原因为 `no_tool`，`answer_status` 与 A4 均为 complete，但 terminal task runner 在 `reporter=false` 时仍把该组合渲染为 `run incomplete`，因此没有把文本复制为 `outputs/` 下的最终报告。最终文本、消费账、manifest 和 A4 复算文件都已保存；该状态差异不改变本票的消费链验收，但应作为后续 CLI 完成态修复项，不能把这两次运行描述为 terminal deliverable 已正式发布。

后续 Issue 44 已修复该判定：显式 `answer_status=complete + stopped_by=no_tool` 现在作为完成交付；缺失状态和各类 partial 状态仍失败关闭。历史运行及其 `outputs/` 不追溯改写，修复只影响后续运行。见 [Issue 44](../../issues/44-cli-complete-no-tool.md)。

## 调用与 token 账

- 工业富联：3 个成功模型响应；input 14,847、output 1,961、cached 8,256。
- 光模块：3 个成功模型响应；input 14,860、output 1,454、cached 7,936。第 2 轮首次模型流 180 秒无 chunk，客户端按既有策略自动重试后成功；该失败尝试无 token 回执，已单列为 1 次 stalled attempt。
- 合计：6 个成功模型响应、1 个无 token 回执的失败尝试；input 29,707、output 3,415、cached 16,192；4 次工具调用。新增抽取调用 0，生产 PostgreSQL 访问 0。

机器可读明细见 [results.json](results.json)。运行时原始 `session.json`、`trace.jsonl`、ConsumptionLedger、manifest 和 A4 复算文件保存在忽略目录 `.local/claims-r2-consumption-20261013/{industrial,optical}/.apodex/runs/`。

## 边界

两份 publication 仍显式返回 `CS_PUBLICATION_EXPLICIT_GAPS`，记录质量仍为 `review_required`。本次只证明所选记录在两个有界问题中的实际送达、模型使用和报告引用，不把局部快照解释为整篇覆盖、模型质量验收或生产放行，也没有修改抽取产物、裁定或发布内容。
