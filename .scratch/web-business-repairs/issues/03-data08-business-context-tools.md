# 03 DATA-08 业务上下文与工具真实接线

Type: task
Status: resolved
Blocked by: 02

## 目标

- 按认证身份和 Run 精确解析冻结的 InvestmentContext，显式注入真实 worker → workflow 模型请求。
- 压缩或模型切换后仍从同一冻结快照重建上下文，不依赖历史摘要猜测业务数值。
- 将依赖资金、成本等字段的计算工具绑定到受限快照值，服务端强制必要字段门禁。
- 将业务工具加入 server profile 白名单并验证 market/sizing 路径可达，同时记录调用与缓存指标。

## 验收

- 真实 PostgreSQL 与 worker 路径证明采用冻结版本，当前业务资料改版不影响旧 Run。
- 模型不能通过工具参数替换 resolver 绑定的资金或成本；缺字段只阻止依赖该字段的计算。
- 长对话压缩、模型切换、缓存丢失后仍得到同一上下文。
- Ruff、相关单元/PG/worker 测试及真实链路验收通过。

## Comments

2026-10-03：DATA-07 修复复验通过后按依赖顺序开始执行。

2026-10-03：实现认证 Run 快照 resolver、最小上下文物化、worker 用户数据注入、受保护
sizing/lint 包装工具及完整 Web 研究工具 profile。补充 resolver 缓存与工具调用指标；worker 不继承
平台数据库 DSN。真 PG 113 项、定向 worker/工具 78 项、相关能力回归 231 项通过；Pyright、Ruff、
两阶段 import smoke、symbol closure、真实模型 preflight 均通过。验收证据见
`../evidence/data08-validation.log` 与环境基线 §4.4。

2026-10-03：验收回溯发现资金口径未参与计算、非对象策略 JSON 异常、指标写盘可中断收尾、
worker `.env` 可恢复敏感服务变量四项遗漏；同时加固认证解析失败时的旧上下文清除，并补充压缩后
快照恢复测试。修复后两轴复审无剩余阻断项，验收通过。详见 `../data08-acceptance-review.md`。
