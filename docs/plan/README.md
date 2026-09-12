# 投研平台计划与设计索引

本目录只维护实施设计、执行顺序和进度记录。产品范围、状态语义与验收口径分别以
[产品需求基线](../product-requirements.md) 和 [业务流程](../business-process.md) 为准。

## 当前有效计划

| 文档 | 当前职责 |
|---|---|
| [D2 Claims 优化执行计划](d2-claims-optimization-plan.md) | Claims v2 发布验收与后续质量加固；代码已实施，按现有 87 份数据验收中 |
| [Claims × 同花顺闭环计划](claims-market-closed-loop-plan.md) | Web 工具入口、Run 级市场证据、比较语义、确定性统计与复盘的主执行计划 |
| [Web 平台加固计划](web-platform-hardening.md) | 多用户生产化、可靠性、观测与前端加固；P0 已完成，后续项进行中/待排 |

## 已实施的设计与决策记录

| 文档 | 读取目的 |
|---|---|
| [数据层架构](data-layer-architecture.md) | 当前 PostgreSQL/zhparser 语料存储结论 |
| [PostgreSQL 迁移记录](pg-migration.md) | 已完成迁移、排序校准和回归过程 |
| [D2 Claims 设计](d2-claims-design.md) | 已实施的 company/industry/macro 抽取基线 |
| [同花顺数据接入](ths-market-data.md) | 已实施市场工具的边界、供应商契约与已知限制 |
| [CLI → Web 复刻](cli-web-parity.md) | 已完成的实时、可观测、steer、审批和 revert 实施记录 |

## 历史计划与需求输入

这些文档可解释设计演进，但其“当前状态”和优先级不得覆盖产品需求基线：

- [早期 Web 平台里程碑](plan.md)：M0–M3 历史台账；M4 已迁移到新需求和闭环计划。
- [P0 投研内核](p0-research-kernel.md)：早期最小资料库验收记录。
- [P1 语料规模化](p1-corpus-scaleup.md) 与 [每日增量](p1-daily-incremental.md)：后续数据运营输入，部分状态已被实际实施超越。
- [投研双数据链路优化报告](research-data-closed-loop-optimization-report.md)：形成闭环计划前的评审输入。
- [Web 语料库接入方案](web-corpus-integration.md)：产品诉求已归并到 `PR-DATA-04`，原状态不再作为现状判断。

## 已失效

- [D2 Claims 质量加固旧清单](d2-claims-quality-hardening-失效.md)
- [D2 Claims v2 旧设计](d2-claims-v2-design-失效.md)

新增计划必须引用 `PR-*` 需求编号，并在页首声明“有效 / 已实施记录 / 历史 / 已失效”之一。计划完成后保留验证记录，但将后续工作迁移到新的唯一有效计划，避免同时维护多个待办真源。
