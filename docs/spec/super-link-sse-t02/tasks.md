# SSE-T02 实施任务（修订版）

状态：实现完成，SQLite 与隔离 PG 验收通过（见计划 §20.8）。完成后逐项勾选，并在计划新增的 **§20.8 SSE-T02 完成记录**留证；§20.7 保持为 T01 记录。

## T2.1 事件表与迁移

- [x] `server/super_link/models.py`：新增 `SuperLinkEventHead`、`SuperLinkEvent`（字段/约束见 spec §2.2）。
- [x] 新增 `server/super_link/alembic/versions/sl_0006_events.py`：接 `sl_0005_controls`，建表、索引、唯一约束；为既有空间逐行补基线头；降级只删两表。
- [x] 验证：SQLite 测试 `sl.Base.metadata.create_all` 可建表；隔离库按升级→降级→升级重建，确认外键指向事件头并回填基线头。

## T2.2 事件核心 `server/super_link/events.py`

- [x] `Change`、`Notification`、`ReadPage`、参数校验（type/键/16 KiB/invalidate/source_id）。
- [x] 托管保存点 `events.savepoint(session)`；未托管嵌套事务暂存抛 `event_unmanaged_savepoint`。
- [x] 根事务监听只做清理；`before_flush`/`before_commit` 守卫（未 seal、seal 后 ORM 写入）；监听器幂等注册、无状态零副作用。
- [x] `tracking`、`stage_for_space/session/run`、`stage_change`（`super_link_enabled` 门禁 + 参与方反查）。
- [x] `seal_changes`：flush、内存去重、按空间 UUID 锁头、**跨事务 change_key 幂等检查**、分配 seq、写事件、更新头、缓存通知。
- [x] `format_cursor`/`parse_cursor`/`event_envelope`/`read_events`（鉴权、分页、`(after, head]` 上界、`invalid_cursor`、`resync_required`）。
- [x] `EventNotifier.publish_once/run_forever`（Pub/Sub 提示、成功后水位、失败重试）；`super_link_event_env` 配置。
- [x] 测试 `tests/test_super_link_events.py` 全部用例通过（含读头后并发提交不越过本页）。
- [x] 测试 `tests/test_super_link_notifier.py` 全部用例通过。

## T2.3 Super-link 来源接线

- [x] `service.py`：`create_pair`（建头 + `space.created`）、`register`、`publish`、`receive`（只暂存，调用方 seal）。
- [x] `runtime.py`：`prepare`、`witness_exit`、`launch_failed`；`finalize` 改用 `events.savepoint`，所有失败早退先暂存并 seal。
- [x] `process_witness.py`：`record_launch`。
- [x] `coordination.py`：`inspect_delivery` 两个事务分别 seal（含校验失败早退）；`accept_delivery`、`accept_feedback`、`enqueue_direct` 事务末尾 seal；`enqueue_automatic` 直接暂存 `run.created`，**不 seal**。
- [x] `controls.py`：`control` 最终 return 前 seal；`reconcile_stops` 空间事务 seal，Run 由 `stop_queued_run` 自行提交。
- [x] `management.py`：`recover` 最终 return 前 seal；预算用幂等键；批量 hold 解除发一条预算事件并整集合失效。
- [x] `worker.py`：`recover_finalizations` 领取/finally 事务分别 seal；`admit_reviewed`、`dispatch_feedback` 最终事务 seal。
- [x] `transport.py`：`Delivery.consume` 每个事务退出前 seal，提交成功才 ACK。
- [x] 测试 `tests/test_super_link_event_sources.py` 对应断言通过。

## T2.4 业务来源接线

- [x] `store.py`：`create_run`、`add_run`、`mark_run_started`、`update_run_result`（两个 commit 分支）、`mark_run_failed_if_active`、`record_artifacts`（UUID 键）、`sync_run_artifacts`（两事务）、`upsert_session_conversation`（归档/提交/冲突三分支）、`delete_session`、`create_control`、`resolve_control`、`close_open_controls`。
- [x] `dispatch_outbox.py`：`enqueue`（含 Run stopped 分支）、`claim_due`、`mark_dispatched`、`mark_submit_failed`、`reclaim_expired`、`cancel_pending`、`stop_queued_run`（自带提交并 seal）、`abandon_for_run`、`dispatch_once` 直写分支。
- [x] `business_service.business_transaction`：`yield` 返回后、commit 前统一 seal，覆盖 HTTP 写路径。
- [x] `routes/super_link.py:create_space`：初始 Run/turn/dispatch 与 `space.created` 同事务，退出前 seal。
- [x] `routes/runs.py`：rerun 旧 Run stopped 直写暂存；submit/rerun/cancel 由 business_transaction seal。
- [x] `input_requests.py`：input_required/续接 Run/dispatch 暂存；HTTP 路径由 business_transaction seal，worker 路径各自事务 seal。
- [x] `watch_scheduler.py`、`monitor_longterm.py`：schedule/defer/stop 暂存；监控循环与 `claim_due` 事务 seal。
- [x] `business_archive.py:delete_research`：先 SELECT 待作废 dispatch（id/claim_version）再批量更新并逐行暂存；参与会话暂存 `participant.unavailable`；由 business_transaction seal。
- [x] 核对 `orchestrator.py` 恢复/重算路径，确认无绕过 store 的 Run/Control 直写，或补齐暂存+seal。
- [x] 测试：只对参与空间产生事件；普通会话零事件；各旁路来源有断言。

## T2.5 PostgreSQL 并发与故障

- [x] `tests/pg/test_super_link_events.py`：A01 晚提交/回滚与先提交、双空间锁顺序、Space/事件头交叉锁序、来源+事件同回滚、迁移基线头（隔离 PG 6 passed）。
- [x] 故障注入：同键内容冲突、事件头缺失、Redis 失败已验证来源回滚或仅延迟通知；数据库唯一约束并发冲突未单独注入。

## T2.6 发布器与启动接线

- [x] `server/config.py`：`super_link_event_env`（非空校验）。
- [x] `server/app.py`：`readiness.ok && super_link_enabled && !restore_mode` 时与 `coordination_loop` 同批启动；退出时取消并等待。
- [x] 测试启动条件谓词与 Redis 故障恢复；确认事件捕获不依赖展示订阅开关。

## T2.7 回归与记录

- [x] `uv run pytest tests/test_super_link*.py tests/test_web_dispatch_recovery.py tests/test_context_inheritance.py`。
- [x] `uv run ruff check` 相关文件；定向 Pyright。
- [x] 确认 `SERVER_SUPER_LINK_ENABLED=false` 时普通模式无新查询、无监听器副作用、无 Redis 依赖。
- [x] 在计划中新增 **§20.8 SSE-T02 完成记录**（变更、测试数量、限制、下一步 T03），更新 §20.2 T02 状态；不改动 §20.7。
- [x] 不启动本机服务、不迁移业务库。
