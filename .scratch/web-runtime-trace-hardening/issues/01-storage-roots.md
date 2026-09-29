# 01：对齐运行根目录与持久卷，兼容历史 Run

Status: needs-triage
Priority: P1
Type: task
Requirements: PR-GOV-01, PR-GOV-05, PR-BIZ-06

## 问题与范围

见[报告 F01](../../../docs/plan/web-runtime-trace-repair-report.md#f01持久卷数据根目录及历史路径迁移)。
范围为 server 配置/受控路径解析、Web Docker 部署和历史 Run 兼容；不是直接移动或删除生产目录。

## 修复前提与验收

- 核验实际环境覆盖、卷、Run 数据量；依赖 07 提供迁移前备份和回退。
- 明确生产目录，卷挂到准确落点；旧/新 Run 读取使用一致、受控的定位。
- 隔离环境验证容器重建、根目录切换、历史读取、越界拒绝、缺失状态与回退。
- 活动 Run 不跨新旧根目录读写；不得仅修改配置就宣称迁移完成。

## Comments

- 2026-09-29：配置/读取路径已检查，实际部署及迁移验收未执行。
