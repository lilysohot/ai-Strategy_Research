# 12 定义宏观计算契约

Status: completed
Execution: specification-complete — production implementation not enabled
Priority: P1

产物：[宏观计算契约 v1](../../../docs/corpus-macro-calculation-contract.md)。
限定 US.NFP_CHANGE_SA 首发实际值减事前一致预期，定义指标、岗位单位、月份、版本、时点、
快照、证据核验、配对门禁、输出与稳定拒绝码，包含 M01—M16 后续实现验收用例。
这些用例是预期行为，不是现有生产代码通过的测试。当前 NFP 仍不能自动计算。
后续依赖：语义绑定/身份/时间门禁修复、受信任来源适配器、纯计算器与独立事件影子验收。
