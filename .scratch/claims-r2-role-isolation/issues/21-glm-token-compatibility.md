# 21 · GLM-5.3-Flash 16K 输出兼容性有界复验

Status: closed-output-completeness-failed
Execution: 3 次确定成功响应耗尽 16K 且为空，第 4 次超时为 outcome_unknown；不重试
Type: task
Parent: [20 · GLM-5.3-Flash relation-only 单变量有界复验](20-relation-model-replacement.md)
Model attempt ceiling: 4 relation calls
Production database access: 0

## 目标

判断 `glm-5.3-flash` 在每包 `max_output_tokens=16384` 时能否产生完整的
`material-relations-question-group-jsonl-v1` 输出，并在输出完整时按冻结的
44/9/35/4 门评分。

## 授权与边界

- 相对 Issue 20，唯一有意配置变化是 `max_output_tokens: 4096 → 16384`。
- 模型仍为 `glm-5.3-flash`；provider、endpoint、timeout、token parameter 不变。
- snapshot、items import、candidate-v5、validation-v11、prompt、Schema、评分样本和阈值不变。
- Claims/items 调用 0；relation 调用最多 4；自动重试 0。
- 不发布，不触发 query、delivery、context_use 或 M_main 消费。
- 执行后无论通过或失败都关闭本票；不在本票内继续增加 token 或修 prompt。

## 门禁

- 4/4 packets completed，0 partial，0 failed。
- 签认样本至少 40/44 正确。
- 已知错误至少 7/9 正确。
- 35 个原正确案例最多回退 2 个。
- target relations 4/4；supports/conditions 不得系统性回退。

## Evidence

- `../evidence/21-glm-token-compatibility-20261010/p0-16384-bounded-live/`

## 执行结果

- 冻结 batch：`batch:c1cbc89331a8866beb28d62b33bff5ef1e5a2fb3c0bf6261a3c8f858f5d7f2e2`。
- 第一个通用 CLI preflight 因恢复的默认 4K profile 与冻结 16K profile 不匹配，请求前以 `CS_CONFIG_MISSING` 阻断；调用 0。
- 同一计划随后由显式 16K profile 执行入口运行；Claims/items 调用 0，relation attempts 4，retry 0。
- attempts 1—3 返回成功，分别用时 270,562 / 261,561 / 273,167 ms；全部 `finish_reason=length`、`completion_tokens=16384`、可见内容 0 字符。
- 已知三次 usage：prompt 32,812，completion 49,152，reasoning 49,121，total 81,964。
- attempt 4 在 300,116 ms 后进入 `outcome_unknown`，无 response object；不得重发，且它可能已产生费用。
- packet 结果为 0 completed、0 partial、4 failed；可见协议记录 0，relation 0。
- 44/9/35/4 语义门仍不可评分。16K 反事实证明单纯增加 token 不能修复该端点的可见输出。
- 下一个可行方向必须是可控/禁用 reasoning，或换成能保证可见结构化输出的模型；不再继续增加 token。
