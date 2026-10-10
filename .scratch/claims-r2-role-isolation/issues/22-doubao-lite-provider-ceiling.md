# 22 · Doubao Seed 2.1 Lite 供应商上限能力复验

Status: closed-semantic-gate-failed
Execution: 4/4 requests succeeded; strict protocol 2/4 packets completed; zero-call reconstruction failed quality gate
Type: task
Parent: [21 · GLM-5.3-Flash 16K 输出兼容性有界复验](21-glm-token-compatibility.md)
Model attempt ceiling: 4 relation calls
Production database access: 0

## 目标

验证 `doubao-seed-2.1-lite` 在关闭思考并将 `max_tokens` 放宽到供应商公布的
256K 最大回答额度后，能否完整返回 `material-relations-question-group-jsonl-v1`
记录，并在输出完整时进入既有 44/9/35/4 签认门评分。

## 授权与边界

- 模型为用户已配置的 `doubao-seed-2.1-lite`。
- `max_tokens=262144`，`reasoning_effort=minimal`；本地不另设 token 成本预算。
- 这是模型、token 上限和思考模式共同变化的能力试验，不用于单变量因果归因。
- snapshot、items import、candidate-v5、validation-v11、prompt、Schema、评分样本和阈值冻结。
- Claims/items 调用 0；relation 调用最多 4；自动重试 0。
- 不发布，不触发 query、delivery、context_use 或 M_main 消费。
- 任一 `outcome_unknown` 不得重试。

## 门禁

- 4/4 packets completed，0 partial，0 failed。
- 签认样本至少 40/44 正确。
- 已知错误至少 7/9 正确。
- 35 个原正确案例最多回退 2 个。
- target relations 4/4；supports/conditions 不得系统性回退。

## Evidence

- `../evidence/22-doubao-lite-provider-ceiling-20261010/p0-256k-minimal-live/`

## 执行结果

- 冻结 batch：`batch:60e684c035b5006cfbe1b68b6fd18ca88a70c41dfc9defd8d93ee2e61ab7e9d7`。
- Claims/items 调用 0，relation 调用 4，4/4 succeeded，retry 0；provider 实际模型为
  `doubao-seed-2-1-lite-260915`。
- usage：prompt 53,418、completion 3,100、reasoning 0、total 56,518；四次均
  `finish_reason=stop`，共返回 10,207 个可见字符、100 行终态。
- 严格协议下第 1、4 包各有 1/4 行将 `challenges` 写入 `status`，而不是合法的
  `present`；最终 2 completed、0 partial、2 failed，保留 102 relations，但不可发布。
- 零调用诊断性归一化可无歧义恢复 5 行并重建 333/333 candidate decisions；该 what-if
  不是原始通过结果。语义门为 37/44、7/9、5 个旧正确回退、4/4 target，其中
  supports/conditions 回退 1 个；未过冻结门。
- 本任务关闭，不追加调用；publication/query/delivery/context_use 均为 0。
