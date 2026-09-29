# Web 运行存储与轨迹追溯修复

Status: needs-triage
Type: repair-spec
Date: 2026-09-29

用户要求将本次发现整理为后续修复报告，未要求本轮实施修复或迁移数据。
后续用户明确要求存储位置不合理时在此次修复一并改正：F01 已升级为必交付范围，
具体新路径、历史迁移和回退验收见报告 v1.2；当前仍处于计划整理阶段。

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
补充复核新增 08—14，其中 08 为多用户上线阻断项，优先处理。

| 补充任务 | 报告发现 | 依赖 |
|---|---|---|
| [08 提交 Run 缺少会话归属校验](issues/08-session-ownership.md) | F08 | 详见报告 v1.1 修复顺序 |
| [09 SSE 游标与终态恢复协议存在缺口](issues/09-stream-replay-contract.md) | F09 | 详见报告 v1.1 修复顺序 |
| [10 流式去重导致文字缺失与用量漏计或重复](issues/10-replay-text-usage.md) | F10 | 详见报告 v1.1 修复顺序 |
| [11 切换 Run 后旧异步响应可能覆盖新视图](issues/11-watch-generation.md) | F11 | 详见报告 v1.1 修复顺序 |
| [12 上传校验与运行创建缺少失败清理](issues/12-upload-atomicity.md) | F12 | 详见报告 v1.1 修复顺序 |
| [13 轨迹读取与事件缓冲缺少容量边界](issues/13-capacity-bounds.md) | F13 | 详见报告 v1.1 修复顺序 |
| [14 排队 Run 的历史上下文没有明确截止点](issues/14-history-boundary.md) | F14 | 详见报告 v1.1 修复顺序 |
推进时只更新单项 issue 的状态和证据，本索引不重复复制进度。

## Comments

- 2026-09-29：基于源码/配置检查建档，未执行动态复现和应用修复。
- 2026-09-29：遗漏复核补充 7 项，合计 14 项；F01 追加 UUID 规范化问题，仍未修改运行代码。
