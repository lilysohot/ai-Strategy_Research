# DATA-08 验收回溯

日期：2026-10-03  
结论：**修复后通过验收**。

## 审查范围

- 规格：`docs/design/web-business-data-prd.md` §3.2、§6、§8，DATA-08 任务及 PR-BIZ-05 / PR-DATA-04。
- 实现：认证 resolver、父进程物化、真实 worker 注入、server profile、快照绑定工具及指标。
- 方法：规范与规格两轴独立审查、运行时复现、定向/相关能力/真 PG 回归及仓库门禁。

## 初审发现与修复

1. **资金口径**：仓位与策略校验曾固定采用总资金。现严格按冻结 `capital_basis` 选择
   `total_capital` 或 `available_capital`；口径无效或对应金额缺失时阻断计算。
2. **结构化失败**：合法但非对象的策略 JSON 曾触发 `AttributeError`。现保留底层 lint 的
   `not_an_object` 错误并返回受保护校验结果。
3. **异常收尾**：工具指标写盘失败曾可能跳过 ContextVar reset 和 summary。现遥测写入
   best-effort，reset 位于 `finally`。
4. **凭据隔离**：worker 的 `load_dotenv(override=False)` 曾可恢复被删除的 Docker DSN。
   现为业务库 Docker DSN、master key 与 JWT key 注入空 tombstone，同时使用内存数据库 URL。
5. **旧上下文防御**：认证解析无结果时删除同 Run 目录中的旧物化上下文及 resolver 指标。
6. **压缩恢复证据**：新增测试证明旧消息中的资金值被压缩移除后，Run 绑定工具仍返回同一
   完整快照，不依赖聊天摘要。

## 复验结果

- PostgreSQL：113 passed。
- DATA-08 worker/工具/编排器：78 passed。
- 市场、语料覆盖、仓位、策略及注册表：231 passed。
- Ruff、Pyright、`git diff --check`、两阶段 import smoke、symbol closure、真实模型 preflight：通过。
- 规范复审：无剩余阻断项；规格复审：无缺失、错误或 scope creep。

本次未部署 API，未迁移生产库；隔离 PostgreSQL 与测试 Run 根在复验后清理。
