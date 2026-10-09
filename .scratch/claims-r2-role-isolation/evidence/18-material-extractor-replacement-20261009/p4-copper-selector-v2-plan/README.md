# Selector v2 zero-call fix and copper plan

P3 selector v1 实跑返回了 487/487 个顶层终态，证明微批容量和终态协议有效；失败集中在模型省略
absence-valued 字段，以及把已经提供的 `evidence_selectors.slot.text` 误认为缺少 source/context。

v2 的确定性修复：

- 缺失 `value` 规范为 null；缺失非 behavior 的 `behavior_status` 规范为 null；缺失时间框架规范为
  unknown，并把相应字段加入 `unknown_fields`。这些规则不生成肯定语义。
- semantic_type 的 `other/negation` 安全落到 unknown；statement_role 的 `forecast` 回到 claim，同时
  forecast 仍保留在 semantic_type。
- terminal shape failure 与 downstream semantic validation failure 分开记账。
- 明确 `evidence_selectors.slot.text` 就是该义务的完整冻结原文，禁止使用 missing-source reason 拒绝。

用 P3 的 23 份 immutable responses 离线 replay（0 calls）：extracted 57→209，failed 252→100，items
58→214，item Schema failures 10→0。剩余 100 是旧响应的语义拒绝，controller 没有替模型改判。

新 plan `batch:c8c98ed42fb25d3fce9ea8e75b4d864c9fefe1ce0ed3ee28448d0d8c96b9d05f`
已冻结但未执行，仍为 items 23 / relations 4 / total 27、strict complete-parent。执行需作为新的显式
预算决定；P3 不可重放为新结果。
