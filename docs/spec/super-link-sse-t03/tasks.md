# SSE-T03 实施任务

| 项目 | 内容 |
|---|---|
| 状态 | 已完成；验证证据见 [spec.md §10](spec.md#10-实施状态) |
| 规格 | [spec.md](spec.md) |
| 边界 | 不启动本机服务、不连接/迁移业务库；PG 仅使用隔离库 `apodex_biz_test` |
| 完成定义 | 快照切流无空隙、补读/去重/过期重同步、Run 终态不关流、约定拓扑下鉴权隔离、连接资源有界 |

## T3.1 配置与流模块骨架

- [x] 在 `server/config.py` 增加 `super_link_sse_*` 八项参数（含发送超时），默认值按规格 §5，
  均带正数约束。
- [x] 新建 `server/super_link/stream.py`，定义 `FrameBuffer`、`ConnectionLimiter`、
  `SpaceHintHub`、`Subscription` 与常量（帧事件名、批次上限、控制帧）。
- [x] `FrameBuffer` 实现 256 帧/1 MiB 双上限、FIFO 取帧、溢出清空并终止；`None` 表示正常结束。
- [x] `ConnectionLimiter` 按用户计数，支持 acquire/release/count；进程内单例，测试可重置。
- [x] `SpaceHintHub` 惰性启动单个 Redis Pub/Sub 监听和共享头核对任务；支持 `listen=False`；
  最后订阅者退出后取消任务；断线退避重试；每 2 秒按全部活跃空间查一次事件头，仅在
  `(stream_epoch, last_seq)` 变化时按 `space_id` 唤醒；查询失败只发内部确认提示。

## T3.2 一致快照

- [x] `snapshot_session()`：打开 AsyncSession、`begin()`，PostgreSQL 首条语句设置
  `REPEATABLE READ`，SQLite 等方言只开事务。
- [x] 事件头缺失抛 `event_chain_unavailable`；读取期间不取行锁、不写库、不另开 session。
- [x] `snapshot_payload(session, ...)` 读取：空间与预算、参与方、Run 列表、交付列表、
  待审批、操作、活动 Run。
- [x] 四个列表各自精确 `total`、默认/最大 `limit`、`next_after`；Run/交付/操作按新到旧，
  待审批按旧到新；待审批只含 `approval/pending/running`。
- [x] `runs.items` 直接复用 `management.run_status`，`deliveries.items` 直接复用
  `management.delivery_status`；不新造摘要 schema。
- [x] `read_snapshot(...)` 组合事务与 payload，返回 `schema_version`、`cursor`、`as_of`、
  `durability_scope`、`capabilities`。
- [x] `min_cursor` 校验：格式/跨空间/超前 400，epoch 或 `min_after` 不符 410；
  成功时返回本次快照头。
- [x] 用户/空间归属复用 `management.owned_space`；其他用户与不存在统一 `not_found`。

## T3.3 SSE 建连与补读

- [x] 路由层校验 `after` 必填；复用 `events.read_events` 的游标语义，返回 400/404/410/503。
- [x] 申请配额失败返回 429 + `Retry-After`；校验失败不得泄漏事件头信息。
- [x] `StreamingResponse` 设置 `Cache-Control: no-cache`、`X-Accel-Buffering: no`；
  显式忽略 `Last-Event-ID`。
- [x] `event_stream`：先订阅通知，再从 `after` 每批 200 条补读；批次按 `seq` 升序；
  `next_cursor` 推进；满批立即继续。
- [x] 补读结束后**再次核对事件头**；头已前进则继续补读，头未变化才登记已同步并等待。
- [x] 事实帧格式：`event: sl.fact`、`id: <cursor>`、单行紧凑 JSON；`seq` 为十进制字符串。
- [x] 等待逻辑：共享头提示立即唤醒；提示丢失/重复不影响正确性；连接不各自轮询事件头。
- [x] 补读错误映射控制帧：权限失效 → `sl.auth_required`；游标/epoch/`min_after` →
  `sl.resync_required`；事件头/数据库 → `sl.unavailable`；均关闭且不推进游标。
- [x] Run 终态事件只作为事实发送，不因 `status` 终结而关闭空间连接。

## T3.4 流中生命周期与有界资源

- [x] 空闲 15 秒发送 `: heartbeat` 注释帧，不带 `id`。
- [x] 每 15 秒及每批发送前复核用户状态与空间归属；失败发送 `sl.auth_required` 并关闭；
  数据库暂时失败不误判撤权。
- [x] 单连接 5 分钟直接关闭，不新增协议帧；客户端重新鉴权并补读。
- [x] 生产者写入 `FrameBuffer`；溢出清空并直接关闭；消费者排空剩余帧后退出。
- [x] Run 终态、空间停止与控制状态变化均不关闭连接。
- [x] 生成器 `finally` 取消生产者、注销订阅、释放配额、关闭缓冲；异常与取消路径均释放。

## T3.5 SQLite 测试

- [x] 新建 `tests/test_super_link_stream.py`，复用 `seed_pair`/事件夹具；`super_link_enabled`
  与认证依赖按现有测试方式覆盖。
- [x] 快照：字段完整性、`cursor == head`、列表排序/总数/`next_after`/`limit` 边界。
- [x] 无空隙：快照 → 提交事件 → `read_events(after=cursor)` 只返回新事件。
- [x] `min_cursor`：成功、格式错误、跨空间、超前 400、epoch/`min_after` 410。
- [x] 归属与可用性：其他用户 404、关闭功能 404、事件头缺失 503、待审批独立分页。
- [x] SSE 建连错误矩阵：400/404/410/503/429。
- [x] 补读、`id`/`cursor` 一致、重复游标去重、Run 终态与空间停止后继续接收。
- [x] 补读收口：补读期间提交的事件在再次核对头时读出。
- [x] 心跳、权限复核、流中重同步、数据库不可用、最大寿命直接关闭。
- [x] `FrameBuffer` 帧数/字节上限、溢出清空并直接结束；配额占用/释放。
- [x] 共享头核对：多订阅者只查一次头；头变化唤醒、头未变不唤醒；轮询失败不伪造不可用。
- [x] 关闭功能时不启动 Hub、不查询事件表，并保持既有路由行为。

## T3.6 隔离 PostgreSQL 测试

- [x] 新建 `tests/pg/test_super_link_stream.py`，复用 `sl_migrated`/`pg_clean`。
- [x] 事务内先建立快照；另一连接提交 `space.control_state` 与事件；本事务 `snapshot_payload`
  仍见旧状态/旧游标。
- [x] 事务结束后新快照见新状态/新游标；`read_events(after=旧游标)` 返回该事件。
- [x] 仅在 `PG_INTEGRATION=1` 与隔离库运行；不连接业务库。

## T3.7 回归与文档

- [x] 运行新增 SQLite 测试与既有 `tests/test_super_link*.py`；记录通过数。
- [x] 运行 `tests/test_context_inheritance.py`、`tests/test_web_dispatch_recovery.py` 等既有相关回归。
- [x] 定向 Ruff；定向 Pyright（`server/super_link/stream.py`、`server/routes/super_link.py`、
  `server/config.py`）。
- [x] 在计划更新 §20.2 SSE-T03 状态，新增 §20.9 完成记录（命令、通过数、未验证项、基线对照）；
  不改 §20.7/§20.8。
- [x] 在规格首页回填实施与验证状态；区分“已实现”和“已用隔离环境验证”，不宣称部署完成。

## T3.8 验收收尾（2026-11-20）

- [x] 读进度：`FrameBuffer.put` 满载等待消费者并带超时；100 条 × 12 KB、64 KiB 缓冲的
  快速消费者可推进到当前头，游标不丢失。
- [x] 连接释放：`SSEStreamingResponse` 对每次发送施加 `send_timeout`，并受总 `max_age`
  deadline 约束；发送阻塞时中止并 `aclose()` 生成器，配额与订阅释放。
- [x] 错误映射：快照与 SSE 建连的 `SQLAlchemyError` 均映射为 503
  `event_chain_unavailable`（覆盖断连与缺表）。
- [x] 分页：快照 `runs_after`/`deliveries_after`/`pending_after`/`actions_after`；
  `/interventions` 支持 `pending_after`、`limit`、`pending_total`、`pending_next_after`；
  runs/deliveries/actions 响应补 `cursor`；SQLite 毫秒归一化时间键。
- [x] Hub 缓存：无订阅空间的 `dispatch` 不写 `_known`，只保留活跃空间。
- [x] 补测试：大载荷积压、数据库异常 503、快照与 `/interventions` 全列表续读、Hub 缓存
  边界、阻塞发送释放。
- [x] 列表一致性：`/runs`、`/deliveries`、`/recovery-actions`、`/interventions` 统一使用
  `snapshot_session`，先读事件头再读内容；列表内容投影期间提交的新事件不会产生“旧内容 +
  新游标”。
- [x] 旧列表续页：`/runs` 等 newest-first 入口改用 `stream.page_order`/`page_cursor`，
  数据库默认时间同秒时不再重复返回同一行。
- [x] 寿命覆盖读取：`SSEStreamingResponse` 的总 deadline 包裹整个响应迭代；`read_events`
  永久挂起时仍释放配额与订阅。
- [x] 补测试：`/runs` 默认时间续页、返回游标不新于内容、读取挂起释放。
- [x] 复跑：SQLite 26 passed、隔离 PG 2 passed、Super-link 非 PG 142 passed、
  context/dispatch 83 passed；Ruff 与 Pyright 通过。
