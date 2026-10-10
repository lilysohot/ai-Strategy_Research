# 19 · relation selection 后继路线零调用去留门

Status: closed-at-r0-same-model-semantic-no-go
Execution: P14 只读反事实完成；333/333 决策可重建，但冻结语义门失败，因此不实施同模型 selected-indices Interface，不冻结新计划、不发新调用
Type: task
Parent: [18 · material extractor 替换实现与严格依赖门](18-material-extractor-replacement.md)
Model attempts: 0
Production database access: 0

## 目标

在不复活 P14、不增加模型调用和人工金标的前提下，判断 P14 是单纯输出格式缺陷，还是即使窄化解释
非法 `status` 后仍存在语义质量不足。只有冻结的 44/9/35/4 门全部通过，才允许实现 controller-owned
selected-indices 后继 Interface。

## R0 · 只读反事实

- [x] 只读打开 P14 ledger，验证 batch、plan、response object 与 candidate-v5 身份。
- [x] 仅当 non-answer `status` 恰好等于该 candidate 的 `allowed_type` 且 selector 为 `pair_window` 时，
  诊断性解释为 `present`；不修改 P14 工件。
- [x] 按 P13 question-group 映射重建 333 个 pair 决策并记录 provenance。
- [x] 使用 P11 human-signed 样本、P12 九个已知错误、P10 baseline/target 和 P14 frozen gate 评分。
- [x] 两次运行输出同一 canonical JSON hash；Ruff、Pyright 通过。

## 结果

- 333/333 决策完整；15 条 type-as-status 均可窄化解释；无不可恢复记录。
- present 222。
- 签认样本 32/44，低于 40/44。
- 已知错误 5/9，低于 7/9。
- 35 个此前正确案例回退 8 个，高于上限 2。
- target relation 4/4。
- supports/conditions 回退 2 个，高于预注册上限 0。

因此 P14 不只是格式问题。按执行前 decision tree，在 R0 关闭同模型后继路线；不进入 Interface 实现、
计划冻结或 live trial。任何模型替换、确定性或混合 relation 算法均须另立新任务和预算。

## Evidence

- [R0 manifest](../evidence/19-relation-selection-successor-20261010/r0-p14-counterfactual/manifest.json)
- [design freeze](../evidence/19-relation-selection-successor-20261010/r0-p14-counterfactual/design-freeze.json)
- [counterfactual summary](../evidence/19-relation-selection-successor-20261010/r0-p14-counterfactual/counterfactual-summary.json)
- [read-only audit](../evidence/19-relation-selection-successor-20261010/r0-p14-counterfactual/audit_counterfactual.py)

## Stop policy

- 不复活或改写 P14。
- 不为同一模型实现 selected-indices 协议。
- 不新增 prompt trial、计划或调用。
- 不发布、不 query、不 delivery、不 context_use。
- 后续替换路线必须是新任务，不属于本票。
