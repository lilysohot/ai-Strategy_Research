# HTTP 价格监控 V1：运行与恢复

对应需求：[技术方案](../design/monitoring-technical-plan.md)、[业务 PRD](../design/web-business-data-prd.md)。实现日期：2026-10-16。

## 实际链路

1. 工作台每 30 秒发送认证心跳，用户在线租约 120 秒；多个页面共享用户在线状态，不发送关闭页面即注销的请求。
2. 独立 `server.monitor_worker` 定时领取行情目标，HTTP 请求最多同时 4 个，单次 15 秒上限；相同服务凭据范围、市场、标的、币种和价格口径共享采样。默认每 900 秒采样。
3. 报价精确十进制文本、供应商时间和接收时间、对应规则版本及生命周期代次先进入 PostgreSQL `monitor_messages`。Redis `quotes` Stream 只传消息 ID。
4. 消费报价时重新核对在线状态、配置版本、暂停/恢复代次、报价质量；判定结果、触发事件和 `triggers` outbox 在同一事务提交，提交后才 ACK。
5. `triggers` 消费者提交 `accepted` 回执后 ACK。独立调度循环重新核对规则、在线周期、事件有效期、研究是否空闲及最新有效价格，冻结业务快照并创建 Run 和现有派发 outbox。
6. Run 执行使用现有研究串行和总 worker 数限制，监控采集不等待 Run。监控 Run 不读写 `session_conversations`。

单会话当前配置上限是服务端事务约束，默认 1；暂停、离线、已触发仍占位，取消释放，历史事件不删除。实体和 API 保持集合形态，未来可调大上限。当前行情适配器仅接受 `6xxxxx.SH` / `0xxxxx.SZ` / `3xxxxx.SZ` A 股、CN/CNY、最新成交价；指数、期货和其他市场需要独立核验适配器，不能套用 A 股响应。

## 启动

先安装依赖、备份数据库并迁移：

```bash
uv sync --frozen --group web --extra dev
uv run --group web alembic -c server/alembic.ini upgrade head
```

API 与监控进程使用相同 PostgreSQL 和配置：

```dotenv
SERVER_MONITOR_ENABLED=true
SERVER_MONITOR_STREAMS_ENABLED=true
SERVER_AUTO_ENABLED=true
SERVER_MONITOR_REDIS_URL=redis://127.0.0.1:6379/0
SERVER_MONITOR_SESSION_LIMIT=1
SERVER_MONITOR_POLL_SECONDS=900
SERVER_MONITOR_VENDOR_TIME_VERIFIED=true
```

`SERVER_MONITOR_VENDOR_TIME_VERIFIED` 默认 false，必须有当前源的时点证据才开启。当前 Fuyao A 股快照依据 `docs/plan/ths-market-data.md` §2 中 `data.timestamp = as_of` 的既有接口核验，加上 2026-10-16 实测：供应商时间 `06:58:24 UTC`，本地接收 `06:58:28 UTC`，价格字段以 Decimal 解码，不使用旧 float 包装器或本地时间回退。它是采样时点的快照，**不保证捕获采样间的短暂穿越**；休市时的陈旧快照不会触发，默认最大年龄 120 秒、未来容忍 30 秒。

```bash
# 独立进程，不能与 API 内的旧轮询重复启动；streams 开关自动禁用旧循环。
uv run --group web python -m server.monitor_worker
# 将来拆开部署时使用同一数据库、Redis 和 stream prefix：
uv run --group web python -m server.monitor_worker --role collector
uv run --group web python -m server.monitor_worker --role delivery
uv run --group web python -m server.monitor_worker --role scheduler
```

容器部署提供 `deploy/docker-compose.monitor.yml` overlay：Redis AOF、128 MB、`noeviction`、持久卷、无宿主端口；监控进程依赖 API schema readiness。Redis 只允许内部可信进程接入，跨主机部署时另外配置认证、TLS 和网络访问控制。本版未部署跨主机组件。

```bash
cd deploy
docker compose --env-file ../.env -f docker-compose.yml -f docker-compose.monitor.yml \
  --profile full --profile monitoring up -d --build
```

API 重启前确认没有运行中的研究；监控 worker 启动不执行 API 的孤儿 Run 对账。前端开发服务器使用热更新，刷新页面可看到会话内“价格监控”。

## 排障和恢复

- 页面状态来自 `/api/business/monitor/sessions/{research_id}`，仅所有者可见，含当前规则、最近检查/有效报价、源错误、worker 心跳、事件与消费结果、关联 Run。心跳接口 `/api/business/monitor/heartbeat` 使用登录身份，不能代替其他用户续约。
- 重投：`pending` 消息默认每 60 秒重放到 Redis。Redis 丢失 Stream/consumer group 时自动重建；以 PG 消息 ID、事件身份和 Run 关联约束去重。
- 崩溃：未 ACK 的消息在 idle 30 秒后 `XAUTOCLAIM`；提交后未 ACK 的重投读取既有结果，不能再次建 Run。
- 失败：每条消息最多处理 5 次，指数退避最长 300 秒，之后 `quarantined`。修复原因后可显式执行 `python -m server.monitor_worker --retry-message <message UUID>`；仍沿用旧身份并重新检查有效期、在线状态和规则版本，过期消息不会启动模型。
- 长 Run：触发回执不依赖 Run 完成；同研究忙时暂缓冻结资料。等待中持续采样，空闲后若最新价格已不满足则过期；默认触发有效期一小时，陈旧行情等待下一次有效采样。
- 关闭页面：120 秒宽限后停止新的采集、判定和分析。已创建 Run 不受影响。重新打开页面后不会补发上一个在线周期的触发。
- 暂停/恢复：增加生命周期代次，旧代次积压消息失效；恢复从新采样重新校验。编辑创建新规则版本，显式重新获得一次触发资格。
- 背压：Streams 各限 10,000 条，PG 未完成消息总数达到 10,000 停止新采样；Redis 内存不足时拒绝写入，PG outbox 保留待重放。不要使用 `allkeys-lru` 静默丢失投递状态。
- 留存：完成的投递 payload/receipt 默认保留 7 天、分批清理；隔离消息保留待人工处置。有效报价审计、业务触发和 Run 记录继续持久保存，应纳入业务数据库容量和备份管理。
- 关闭/回滚：先停监控 worker，再关闭三个启用开关并重启 API。保留新增表和代次列便于恢复；不要直接在业务库 downgrade 删除消息账本。恢复模式继续禁止采集和派发。

## 验收环境与证据

专用容器 `frontier-monitor-pg-test`（127.0.0.1:55432，库 `frontier_monitor_test` / `frontier_monitor_ui_test`）与 `frontier-monitor-redis-test`（127.0.0.1:56379）。不接触业务库测试数据，不调用模型执行研究。

- `tests/pg/test_monitor_pipeline.py`：真实 Redis/PG，提交后未 ACK、Redis 消息丢失重放、隔离重试、并发名额、同标的跨会话共享请求、离线/重新上线、旧版本/暂停恢复、长 Run 忙时继续消费并重新校验。
- 结合 `test_watch_eval.py`、`test_watch_rules.py`、`test_watch_scheduler.py` 和 `test_monitor_source.py`：70 项通过；另有 3 项 watch Run 不读写普通会话连续性载体的回归通过。
- `web/tests/monitor-real.cjs`：真实 API/PG 的保存、暂停、恢复、编辑、取消、会话隔离、心跳；零浏览器异常。截图在 `.scratch/monitoring-v1/monitor-dialog.png`。
- 前端 typecheck、生产 build、96 项已有测试通过；变更文件 Ruff、框架 import smoke stage 1、符号闭包和真实单次 LLM preflight 通过。
- import smoke stage 2 首次发现当前环境缺可选 `harbor` 评测依赖；使用 `uv run --frozen --extra eval --group web` 补齐后，442/442 模块导入通过。Compose overlay 配置检查通过。

## 本机启用记录

2026-10-16，确认无运行中的研究后，以 `pg_dump -Fc` 备份业务库及原配置到
`/home/administrator/.local/share/frontier-agent/backups/monitoring-20261016T071730Z`（目录/文件限制访问），
执行 `0020 → 0021` 增量迁移并重启 API。`/readyz` 返回 `ok`，5173 页面返回 200。

- 生产监控 Redis：`frontier-monitor-redis`，仅绑定 `127.0.0.1:6379`，AOF/128 MB/noeviction，持久卷 `frontier_monitor_redis_data`。
- 独立进程：用户级 `frontier-monitor.service`，开启自启动和失败重启；collector/delivery/scheduler 三个角色心跳均正常。
- 实际上游闭环：真实 HTTP 报价 `47.78`、供应商快照时间 `2026-10-16 07:18:56 UTC`，在**隔离测试库**和测试 Redis 中完成采集→投递→判定→持久回执 `completed/watched`；没有创建模型 Run，也没有向业务会话添加测试监控。
- 页面刷新即可看到入口，无需用户手动重启服务。系统并发仍使用现有 `SERVER_WORKER_POOL_SIZE`，未增加用户级并发配置。
