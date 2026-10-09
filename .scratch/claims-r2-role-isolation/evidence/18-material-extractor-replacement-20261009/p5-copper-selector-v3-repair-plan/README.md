# Selector v3 targeted repair

P5 只覆盖 P4 的 35 个未闭合槽，不重跑 452 个已有终态槽。四个微批均成功，消耗 24,921 tokens；
v3 仍留下 10 个 failed 槽：2 个把 `condition` 错填进 semantic_type，2 个来自过宽的 evidence
启发式，6 个是结构残片的否定终态。没有 relation、发布、查询、投递或 context use。

这些失败在 v4 中按字段轴分离、收窄 evidence 信号，并把结构性 negative terminal 与协议失败分开。
