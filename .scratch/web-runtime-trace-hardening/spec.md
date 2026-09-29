# Web 运行存储与轨迹追溯修复

Status: needs-triage
Type: repair-spec
Date: 2026-09-29

用户要求将本次发现整理为后续修复报告，未要求本轮实施修复或迁移数据。

详细证据、影响、修复建议和验收唯一正文见
[修复报告](../../docs/plan/web-runtime-trace-repair-report.md)。产品范围与完成定义依从
[产品需求](../../docs/product-requirements.md)；本目录仅维护任务状态，不另建需求真源。

## 任务索引

| 任务 | 报告发现 | 依赖 |
|---|---|---|
| [01 持久根目录与历史迁移](issues/01-storage-roots.md) | F01 | 07 的迁移前备份能力；02 防止再次污染构建 |
| [02 构建上下文隔离](issues/02-build-context.md) | F02 | 无 |
| [03 轨迹安全输出](issues/03-trace-redaction.md) | F03 | 无 |
| [04 工具调用身份](issues/04-tool-call-identity.md) | F04 | 无 |
| [05 历史轨迹展示](issues/05-history-trace-ui.md) | F05 | 03、04 |
| [06 轨迹完整性](issues/06-trace-completeness.md) | F06 | 与 04 协调格式契约 |
| [07 保留与恢复](issues/07-retention-recovery.md) | F07 | 盘点先行；联合验收在 01/03/06 后 |

Status 行遵循仓库 triage labels；本轮均待分诊，不代表可无人值守迁移生产数据。
推进时只更新单项 issue 的状态和证据，本索引不重复复制进度。

## Comments

- 2026-09-29：基于源码/配置检查建档，未执行动态复现和应用修复。
