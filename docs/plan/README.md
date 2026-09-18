# 投研平台计划与设计索引

本目录只维护实施设计、执行顺序和进度记录。产品范围、状态语义与验收口径分别以
[产品需求基线](../product-requirements.md) 和 [业务流程](../business-process.md) 为准。

## 当前有效计划

| 文档 | 当前职责 |
|---|---|
| [研究材料 × 同花顺数据 × 分析总计划](claims-market-closed-loop-plan.md) | 当前唯一跨层进度真源；I0 细任务台账已回填：守卫已放行、I0A-1～5 与 I0-B 完成（M1/M2 达成），I1-1～I1-9 完成、F1—F7/R1—R6 整改收口后当前候选 i1-r3，**M4 已独立复核放行并由 U 签认（2026-09-16）**；I0-C（M3）待执行、I2 not_ready。R2 历史失败保留，R3 未开始 |
| [语料清洗、切块、入库与索引重构草案](corpus-ingestion-rebuild-architecture.md) | 唯一当前基础链路候选设计 v1.1；I0-A/B/C 门后才冻结物理架构，I4 另核最新备份；强制零模型，I0-A/B 已完成、I0-C 待执行，业务新链未落地、未清库 |
| [语料重构任务分解](corpus-ingestion-rebuild-tasks.md) | 执行分解 v1.1，含守卫、消费者接线、最终重验和条件切换；页首新增状态导航与每轮回填规则，状态裁决仍归总计划，不凭文件存在勾选完成 |
| [三类研报清洗与 R2 收口方案](research-report-cleaning-scope-plan.md) | 公司/行业/宏观范围及 R2 语义交付设计，纪要退出默认处理及验收；来源到索引的细节与执行顺序以重构设计为准，不再将基础 PG 验证放在模型试验之后；功能未实施、模型预算未授权 |
| [清洗与入库回溯诊断](../../.scratch/corpus-evidence-pipeline/cleaning-ingestion-diagnosis-report.md) | 只读诊断：内容去重阻止重清洗发布、解析双路径、状态/定位及恢复缺口；建议局部重设计版本/准入/发布，不更换 PG，不以重入库代替 R2 修复；未实施 |
| [R2 局部重设计与 CLI 闭环计划](r2-local-redesign-cli-closure-plan.md) | plan-v13阶段记录：P3-I人工通过，P4调用1/5后协议失败；最新边界与主链归并方向见总计划及下列归因评估，旧实验表/入口不要求永久兼容 |
| [P4归因与旧流程重整评估](../../.scratch/corpus-evidence-pipeline/r2-p4-root-cause-and-legacy-review.md) | 已完成诊断：实际模型错误、gold依赖、P2/P4接线断裂、G2/G6反例及旧模块/实验数据库重整范围；不表示已完成重构或业务验收 |
| [排除纪要后的测试结论](../../.scratch/corpus-evidence-pipeline/r2-nonminutes-report-v1.md) | 非纪要范围仍未通过：v13重评分24/25；当前P4为24义务、4合法/4非法/16未评估；55项基础工程测试通过，1项PG跳过，新增模型调用0 |
| [R2 P1 Interface 与验收契约](r2-p1-interface-contract.md) | P1 前瞻设计冻结：有限候选不冒充已验证原子命题；终态、容量、运行时/开发评分分离；不是生产验收 |
| [Web 平台加固计划](web-platform-hardening.md) | 历史实施与后续加固范围保留；2026-09-14 用户决定 Web 后续工作暂缓，先打通 CLI 数据链路 |

## 已实施的设计与决策记录

| 文档 | 读取目的 |
|---|---|
| [数据层架构](data-layer-architecture.md) | 已有 PostgreSQL/zhparser 选型与历史实施记录；旧 schema/零调用方改动不约束本轮重构，新草案不冒充已实现 |
| [PostgreSQL 迁移记录](pg-migration.md) | 已完成迁移、排序校准和回归过程 |
| [D2 Claims 设计](d2-claims-design.md) | 已实施的 company/industry/macro 抽取基线 |
| [D2 Claims 优化记录](d2-claims-optimization-plan.md) | 旧规则/金标与发布验收历史；剩余任务已迁移到当前总计划，不再维护第二套优先级 |
| [宏观契约专项记录](corpus-macro-contract-implementation.md) | M1 模型、M2 适配器的实现记录；BLS 真实验收暂缓，原 M3—M6 不再作为研报主线 |
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

2026-09-13：材料中的数字属于来源论据，不能自动成为数据层观测；政府数据和行情由用户确认的同花顺接口承担。
网页逐条复核不再是材料理解的前置。产品范围见 PR-DATA-09—12、PR-OUT-06—07。
