# 02：排除 Web 运行数据进入构建上下文和镜像

Status: needs-triage
Priority: P1
Type: task
Requirements: PR-GOV-01, PR-GOV-06

## 问题与范围

见[报告 F02](../../../docs/plan/web-runtime-trace-repair-report.md#f02运行数据进入构建上下文及镜像的风险)。
核验根/专属 Docker ignore、Web 构建路径及必须保留的源码。Git ignore 不能代替 Docker ignore。

## 修复前提与验收

- 临时构建目录用无敏感 sentinel 复现，不复制真实用户数据作为样例。
- build/runtime 镜像及相关层均不含 sentinel，源码和必要 fixture 正常打包。
- 新增构建回归保护；若发现历史受影响镜像，另行记录范围并制定处置，不擅自删发布镜像。

## Comments

- 2026-09-29：复制链和 ignore 缺口确认，尚未构建测试镜像；没有已泄露证据。
