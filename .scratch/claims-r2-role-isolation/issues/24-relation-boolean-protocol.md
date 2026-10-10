# 24 · Relation question-group 布尔终态协议与零调用回放

Status: complete
Execution: gold-v2 signed; protocol implementation and zero-call replay passed; live compliance not claimed
Type: task
Parent: [23 · Relation 语义边界更正与零调用敏感性复评](23-relation-adjudication-correction.md)
Model attempt ceiling: 0
Production database access: 0

## 目标

将 question-group relation 协议中 non-answer 终态从容易混淆的
`status="present|absent" + evidence_selector` 收窄为 controller 局部编号和 JSON 布尔值
`is_present`。answers 继续使用 question-local selected indices；relation type、pair identity、证据范围和
relation ID 全部由 controller 持有并回填。

## 不变量

- 新协议为 `material-relations-question-group-jsonl-v2`；v1 只读兼容，不原地放宽。
- `is_present` 必须是 JSON boolean，字符串、relation type 和旧 status shape 都严格拒绝。
- gold-v2 已由 xyl 签认，后续模型结果不得反向修改标签或阈值。
- 本票只实现和零调用回放，不创建 live plan，不发模型请求，不授权 publication/query/delivery/context_use。

## 验收

- prompt、parser、strict role wrapper、RoleArtifact/CLI/contract 枚举完整接线。
- 单元和执行回归证明 v1 可读、v2 布尔终态可解析、type-as-status 在 v2 fail closed。
- 使用 Issue 22 已保存响应的冻结决定零调用生成 v2 终态，4/4 packet 完整、333/333 candidate decisions
  有唯一终态、0 missing/duplicate/invalid。
- 按签认 gold-v2 重算但不改写 Issue 22 历史终态；回放结论明确不等价于真实模型协议服从性。

## Evidence

- `../evidence/24-relation-boolean-protocol-20261010/r0-zero-call/`

## 结果

- 新增 `material-relations-question-group-jsonl-v2`，answers 保持 question-local selected indices，
  non-answer 只接受 `relation_index + is_present:boolean`；controller 回填 type、pair、evidence 和 ID。
- v1 继续历史可读；v2 对字符串布尔、旧 status shape 和 type-as-status 严格拒绝。
- 既有 Issue 22 决定经 v2 零调用回放为 4/4 packet complete、333/333 candidate decisions、
  100 terminals、212 relations，missing/duplicate/invalid 均为 0。
- 签认 gold-v2 重算维持 37/38，唯一错误为兼容厚度排序；149 项相关测试、Ruff、Pyright 通过，
  回放重复运行哈希稳定。
- 下一步只能另行冻结最多 4 次的最终 live compliance 计划；未得到明确授权前不得调用模型。
