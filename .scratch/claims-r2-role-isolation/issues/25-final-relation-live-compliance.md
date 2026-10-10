# 25 · Relation boolean v2 最终有界真实服从性复验

Status: closed-semantic-gate-failed
Execution: 4/4 requests and packets completed under boolean v2; protocol passed; signed gold-v2 quality gate failed
Type: task
Parent: [24 · Relation question-group 布尔终态协议与零调用回放](24-relation-boolean-protocol.md)
Model attempt ceiling: 4 relation calls
Production database access: 0

## 授权

用户明确授权：“授权执行冻结并执行最后一次最多 4 次的真实协议服从性复验”。

## 冻结范围

- 沿用 Issue 22 的 snapshot、accepted items、333 个 candidate-v5、validation-v11、4 packet、
  Doubao Seed 2.1 Lite、`max_tokens=262144`、`reasoning_effort=minimal` 和零自动重试。
- 唯一有意协议变化为 `material-relations-question-group-jsonl-v1` →
  `material-relations-question-group-jsonl-v2`；answers 仍为局部索引，non-answer 为 JSON boolean。
- 使用 xyl 已签认 gold-v2：38 条可评分、最低正确 35；known errors 至少 7/9；29 条非 known-error
  案例最多回退 2；target 4/4；supports/conditions 不得回退。
- Claims/items 调用为 0；relation 调用最多 4；任一 outcome_unknown 不重发。
- publication、query、delivery、context_use、M_main 和生产数据库均未授权。

## Evidence

- `../evidence/25-final-relation-live-compliance-20261010/r0-live/`

## 执行结果

- 冻结 batch：`batch:3269051ddc97ebc979132d5110bdf923c22f28b9f87dd579717b27acb120f920`；
  相对 Issue 22 唯一有意变化为 question-group v1 → boolean v2。
- relation 请求 4/4 succeeded，retry 0；实际模型 `doubao-seed-2-1-lite-260915`，四次均
  `finish_reason=stop`，reasoning tokens 为 0。
- 用量：prompt 53,642、completion 2,930、total 56,572；可见输出 9,097 字符、100 行。
- 协议门通过：4 completed、0 partial、0 failed，333/333 candidate decisions；
  missing/duplicate/invalid 均为 0，控制器保留 213 条 relations。
- gold-v2 质量门失败：30/38（最低 35）、known errors 6/9（最低 7）、29 条非 known-error
  案例回退 5（最多 2）；target 4/4、supports/conditions 回退 0 通过。
- 按冻结终止规则关闭当前模型 + extractor 路线，不追加调用、不修改 prompt、不降低阈值、不重整金标。
  publication、query、delivery、context_use 与 M_main 仍未授权且均为 0。
