# 20 · GLM-5.3-Flash relation-only 单变量有界复验

Status: closed-output-completeness-failed
Execution: 4/4 调用运输成功，但全部在 4096 completion token 上限终止且可见内容为空；本轮已关闭
Type: task
Parent: [19 · relation selection 后继路线零调用去留门](19-relation-selection-successor.md)
Model attempt ceiling: 4 relation calls
Production database access: 0

## 目标

判断 P14 的失败是否能通过仅替换模型为 `glm-5.3-flash` 消除。本轮冻结 P14 的
snapshot、已签认 items import、candidate-v5、validation-v11、question-group 提示与协议、
44/9/35/4 评分门及严格 `complete_parent` 依赖策略。

## 授权与边界

- Claims 调用 0；items 调用 0；relation 调用最多 4。
- 无自动重试；未知结果立即停止。
- 不新增金标，不改候选、prompt、Schema、评分器或阈值。
- 只允许模型身份及由其派生的 profile/role/task/batch 身份变化。
- 执行后无论通过或失败都终止本轮，不在本票内修 prompt 或换第二个模型。
- publication、query、delivery、context_use 仍为 0；通过后另行授权最小正向消费闭环。

## 预注册门禁

- 4/4 packets completed，0 partial，0 failed。
- 签认样本至少 40/44 正确。
- 9 个已知错误至少修正 7 个。
- 35 个原正确案例最多回退 2 个。
- 4/4 target relations 命中。
- supports/conditions 不允许系统性回退。

## 停止策略

- 若任一 packet 运输结果未知，停止后续调用。
- 若协议完整性失败，仍保留原始响应供零调用审计，不宽松解析。
- 若语义门失败，结论只是 `glm-5.3-flash + 冻结提取器` 不达标。

## 执行结果

- 冻结 batch：`batch:5c0a6386599b91e18bcfc62ea5a5d45a23e367eff62d99e2649f6fa7485efeb9`。
- Claims/items 调用为 0；relation 调用为 4；4/4 HTTP/model attempt succeeded；0 retry。
- 四个响应都是 `finish_reason=length`、`completion_tokens=4096`、可见内容 0 字符。
- token 合计：prompt 49,683，completion 16,384，reasoning 16,377，total 66,067。
- packet 结果：0 completed、0 partial、4 failed；产生 0 条协议记录和 0 条 relation。
- 失败类别是 `model_output_budget_exhausted_before_visible_protocol_content`，不是运输或 controller index 失败。
- 44/9/35/4 语义门因输出完整性失败而不可评分，因此本轮没有回答 GLM 的 relation 语义准确率。
- 按预注册停止策略，不在本票内增加 token 上限、关闭 reasoning、修 prompt 或重跑。

## Evidence

- `../evidence/20-relation-model-replacement-20261010/p0-glm-5-3-flash-bounded-live/`
