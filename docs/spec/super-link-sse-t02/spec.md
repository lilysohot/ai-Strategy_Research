# SSE-T02 持久事件与可靠发布 实施规格（修订版）

| 项目 | 内容 |
|---|---|
| 状态 | 已实现；SQLite 34 项与隔离 PG 6 项验收通过；未启动服务、未迁移业务库 |
| 依据 | [技术框架 §11](../../design/super-link-technical-design.md#11-sse-接入边界2026-11-20)；[建设计划 §20](../../plan/super-link-communication-foundation.md#20-sse-状态同步执行计划2026-11-20) |
| 任务 | SSE-T02：独立事件存储/可选迁移、业务写入适配、发布与补偿读取 |
| 本版修订 | 保存点生命周期、事务所有者矩阵、跨事务幂等、seal 后写入守卫、发布器启动条件、`read_events`；收尾修复反馈键、事件外键、分页上界、预算失效与 PG 用例 |

## 0. 本版修正的审查问题

1. **不再依赖 `after_soft_rollback` / `after_transaction_end` 的触发顺序。** 保存点结果由显式上下文管理器 `events.savepoint()` 决定；监听器只做根事务清理。未托管的保存点禁止暂存事件。
2. **接线表按真实事务所有者重写。** 明确谁写业务数据、谁暂存、谁 seal/commit，以及每个提前返回/异常提交分支。`enqueue_automatic` 直接建 Run、不自带提交；`stop_queued_run` 自带提交，均按实际代码登记。
3. **幂等覆盖跨事务重试。** seal 在锁头后按 `change_key` 读已提交事件：内容一致复用、不增序号；内容不同报冲突。产物改用变更 UUID，预算改用幂等操作键，重试类使用单增次数或操作键。
4. **seal 后禁止 ORM 业务写入。** `before_flush`/`before_commit` 双层守卫检测 seal 后的 `new/dirty/deleted`；Core SQL 写入无法自动检测，由调用顺序契约与测试保证。
5. 发布器启动条件与现有后台任务一致：`readiness.ok && super_link_enabled && !restore_mode`。
6. 补齐 `read_events` 的鉴权、游标、分页与恢复语义；HTTP/SSE 仍留给 T03。
7. 完成记录写入计划新增的 **§20.8**，§20.7 保留给 T01。

## 1. 目标与完成定义

1. 新增独立事件账本 `super_link_event_heads` / `super_link_events`，只用事务内整数序号，不用 sequence。
2. 提供 `stage_change` / `seal_changes` / `read_events`；游标与事件信封在本批固化，快照与 SSE 接口留给 T03。
3. 业务事务内登记脱敏草稿；保存点回滚丢弃草稿；最外层提交前必须 seal；seal 后不得再写业务对象。
4. seal 在业务 SQL 与 flush 之后执行：按空间 UUID 排序最后锁定事件头、跨事务幂等检查、分配空间内序号、写事件、更新头，随即提交。
5. 覆盖技术框架 §11.2 全部来源，并为每个来源登记真实事务所有者。
6. Redis Pub/Sub 只发空间 head 提示；发布器从 PostgreSQL 扫描未通知事件，成功后记录 `notified_at`，崩溃可重发。Redis 失败不回滚业务、不阻塞执行。
7. 事件写入失败与来源记录同事务回滚；未接入空间与普通会话不写事件、不增加查询。

## 2. 事件核心

### 2.1 模块与公开接口

新增 `server/super_link/events.py`：

```python
SCHEMA_VERSION = 1
CURSOR_PREFIX = "sl1"
PAYLOAD_LIMIT_BYTES = 16 * 1024
VIEWS = {"space", "participants", "runs", "deliveries", "interventions", "actions"}

@dataclass(frozen=True, slots=True)
class Change:
    type: str
    space_id: uuid.UUID
    change_key: str
    data: Mapping[str, Any] = field(default_factory=dict)
    invalidate: tuple[str, ...] = ()
    source_kind: str = "space"
    source_id: str | None = None
    participant_id: uuid.UUID | None = None
    session_id: uuid.UUID | None = None
    run_id: uuid.UUID | None = None

@dataclass(frozen=True, slots=True)
class Notification:
    space_id: uuid.UUID
    stream_epoch: uuid.UUID
    head_seq: int

@dataclass(frozen=True, slots=True)
class ReadPage:
    events: list[dict]
    next_cursor: str | None
    stream_epoch: uuid.UUID
    head_seq: int

@asynccontextmanager
async def savepoint(session: AsyncSession) -> AsyncIterator[None]

async def tracking(session, *, session_id=None, run=None) -> bool
async def stage_change(session, change: Change) -> bool
async def stage_for_space(session, space_id, *, ...) -> bool
async def stage_for_session(session, session_id, *, ...) -> bool
async def stage_for_run(session, run, *, ...) -> bool
async def seal_changes(session: AsyncSession) -> list[Notification]

async def read_events(*, user_id, space_id, after: str | None, limit: int = 200) -> ReadPage
def format_cursor(space_id, stream_epoch, seq) -> str
def parse_cursor(cursor: str) -> tuple[uuid.UUID, uuid.UUID, int]
def event_envelope(event: models.SuperLinkEvent) -> dict
class EventNotifier: ...
```

- `tracking()` 先检查 `cfg.super_link_enabled`，再按会话/Run 反查参与方；供产物等需要先决定“是否计算摘要”的来源使用。
- `stage_for_session/stage_for_run` 内部复用 `tracking`；非参与会话返回 `False`，不打开事件表。
- 载荷校验：`type` 在目录内；`change_key` ≤200 字符；`data` 可 `json.dumps(ensure_ascii=False, allow_nan=False)` 且 ≤16 KiB；`invalidate` ⊆ `VIEWS`；`source_id` ≤64 字符。失败抛 `CollaborationError` 并回滚来源事务。

### 2.2 表结构与迁移

`models.py` 新增（均不加入主 metadata）：

| 表 | 字段 |
|---|---|
| `super_link_event_heads` | `space_id` PK/FK `super_link_spaces.id`；`stream_epoch` UUID；`last_seq` bigint default 0；`min_after` bigint default 0 |
| `super_link_events` | PK `(space_id, stream_epoch, seq)`；`space_id` FK 指向 `super_link_event_heads.space_id`（不直接指向 `super_link_spaces`，避免外键检查重新引入 Space 行锁）；`event_id` unique；`transaction_id`；`change_key` varchar(200)；`type` varchar(64)；`schema_version`；`source_kind` varchar(32)；`source_id` varchar(64) nullable；`participant_id/session_id/run_id` UUID nullable（无业务外键）；`data_json`/`invalidate_json` JSON；`recorded_at` timestamptz default now()；`notified_at` nullable；unique `(space_id, stream_epoch, change_key)`；索引 `(notified_at, space_id, stream_epoch, seq)` |

迁移 `server/super_link/alembic/versions/sl_0006_events.py` 接 `sl_0005_controls`：建表与约束；为既有空间插入 `stream_epoch=uuid4()`、`last_seq=0` 的基线头；降级只删两表。事件只对事件头建外键，不对 Space/Run/Message/Session 建业务外键，避免锁序回退。

### 2.3 保存点：显式托管，不依赖监听顺序

当前 SQLAlchemy 在保存点回滚时先触发 `after_transaction_end`、后触发 `after_soft_rollback`，因此**不能**用“先标记、后判断”的监听方案。改为：

```python
async with events.savepoint(session):
    ...  # service.publish 等
```

- `savepoint()` 进入时压入托管 scope，内部执行 `session.begin_nested()`；正常退出时按登记顺序合并到父 scope；任何异常（含保存点释放失败）丢弃本 scope。
- 只处理 `SessionTransaction`；`transaction.nested is True` 才视为真正保存点。自动 begin、flush 等内部事务不创建事件 scope。
- `stage_change` 若发现当前处于嵌套事务但不在 `events.savepoint()` 托管 scope 内，抛 `CollaborationError("event_unmanaged_savepoint")`，避免无法判定回滚。
- 根事务监听只做清理：`after_transaction_end`（非嵌套）清空该会话全部事件状态；`after_soft_rollback`（非嵌套）同样清空。触发顺序不再影响结果。
- 业务代码中唯一需要事件保存点的位置是 `runtime.finalize()` 的发布块，改为 `events.savepoint(session)`；其他 `begin_nested()`（如 `business_service._claim_operation`）不暂存事件，保持原样。

### 2.4 提交守卫与 seal 后写入

根事务守卫：

- `before_flush(session)`：若存在已 `sealed` 的 scope，且会话有 `new/dirty/deleted`，抛 `CollaborationError("event_seal_business_writes")`。`seal_changes` 在设置 `sealed` 前完成最后一次 flush，因此正常 seal 不会误报。
- `before_commit(session)`：若当前无嵌套事务且存在未 seal 草稿，抛 `CollaborationError("unsealed_event_drafts")`。
- 嵌套保存点释放不触发上述“根事务”判断：`session.get_nested_transaction() is not None` 时跳过；托管 scope 的最终合并由 `savepoint()` 完成。
- Core SQL 在 seal 之后更新业务表无法被 ORM 状态检测；契约禁止该顺序，并用来源测试验证 seal 位于所有业务 SQL/flush 之后。
- 监听器首行检查会话是否持有事件状态，无状态立即返回；`super_link_enabled=false` 时永远不会创建状态。注册使用模块级标记与 `event.contains()`，重复导入不重复注册。

### 2.5 seal：跨事务幂等与锁顺序

`seal_changes(session)`：

1. 断言无活动保存点（`event_seal_inside_savepoint`）；无草稿直接返回 `[]`。
2. `await session.flush()`（业务 SQL 已完成）。
3. 合并托管 scope 的草稿；按 `change_key` 在内存中检查：内容一致保留一条，不同抛 `change_key_conflict`。
4. 涉及空间按 `str(space_id)` 排序，逐个 `session.get(SuperLinkEventHead, space_id, with_for_update=True)`；缺失抛 `event_head_missing`。
5. 在每个空间内，按本批 `change_key` 查询已提交事件（`space_id + stream_epoch + change_key IN (...)`）：
   - 已存在且 `type/source_kind/source_id/participant_id/session_id/run_id/data/invalidate` 全部一致：复用，不分配序号、不插入；
   - 已存在但内容不同：抛 `change_key_conflict`，来源事务回滚；
   - 不存在：分配 `seq+1`，插入事件。
6. 更新 `last_seq`，`await session.flush()`，标记 scope `sealed`，返回**发生序号推进**的空间通知；重复调用返回缓存结果。
7. 取得事件头锁后不再查询业务行、不执行外部调用或新事务；幂等查询只读本空间事件表。

`transaction_id` 每批一个 UUID；同一事务多次 seal（不应出现）复用同一值。内容比较不包含 `event_id/seq/transaction_id/recorded_at`。

### 2.6 事件键的身份类型

每个键必须明确属于以下一种，避免 A→B→A 覆盖：

| 身份类型 | 使用位置 | 规则 |
|---|---|---|
| 稳定操作标识 | 空间创建、控制动作、恢复动作、预算、介入 | 使用来源已有的 `idempotency_key` / 单调 `control_version` |
| 单调版本 | Run 状态、dispatch `claim_version`、review/admission/feedback 尝试次数、finalization 重试次数 | 版本只增；同一版本同内容可重试，不同内容报冲突 |
| 一次变化 UUID | 产物索引等无既有幂等标识的事务 | 每次**实际变化**生成一个新 UUID；内容摘要只作 `data` 字段 |

据此修正此前易错的键：

- 产物：`artifacts:{run_id}:{change_uuid}`；`index_sha256` 是变更后整个索引的摘要，仅作载荷。A→B→A 生成两个事件；无实际变化不发事件。
- 预算：`space:{space_id}:budget:{idempotency_key}`，不再用额度值。
- 恢复/重试：`review|admission|feedback:{message_id}:action:{idempotency_key}` 或带单增尝试次数；不使用可回退的状态字符串。`feedback:{message_id}:{feedback.attempts}:started` 只由 `accept_feedback` 产生，`dispatch_feedback` 只产生带 `error_code` 的失败事件，避免同一成功键被两个所有者写入。
- dispatch：`dispatch:{row_id}:{claim_version}:{status}`；Run：`run:{id}:{created|running|terminal:{status}|input_required}`。

### 2.7 `read_events`

`read_events(user_id, space_id, after, limit)` 在短只读事务内：

1. 校验空间归属，否则 `not_found`；`limit ∈ [1,200]`。
2. 读取事件头；缺失 `event_head_missing`。
3. 解析游标 `sl1:<space_uuid>:<epoch_uuid>:<decimal_seq>`：格式错、空间不符、`seq > head.last_seq` → `invalid_cursor`；epoch 不符或 `seq < min_after` → `resync_required`。
4. `SELECT ... WHERE seq > after_seq AND seq <= head.last_seq ORDER BY seq LIMIT limit`；返回信封（`seq` 为十进制字符串）与 `next_cursor`；无新事件时 `next_cursor` 保持输入值。上界使用本次读到的 head，禁止返回读头之后才提交的事件；调用方下一轮凭游标补取。
5. 不写库、不锁事件头；T03 负责 HTTP/SSE 与快照一致性。

### 2.8 发布器

`EventNotifier(sessions, redis, *, channel, batch=200)`：

- `publish_once()`：短事务按 `(space_id, stream_epoch)` 取未通知事件的 `MAX(seq)`（`GROUP BY ... LIMIT batch`）；逐空间发布
  `{"schema_version":1,"space_id":...,"stream_epoch":...,"head_seq":N}` 到
  `<super_link_event_env>:<super_link_namespace>:ui-events:v1`；全部成功后用新事务把 `seq <= head_seq AND notified_at IS NULL` 置为 `now()`。
- 任一发布失败：不更新水位，返回失败计数；业务提交不受影响，下一轮重发。
- `run_forever(interval_seconds=1.0)`：异常记录后继续；由 `app.py` 在
  `readiness.ok && cfg.super_link_enabled && !cfg.restore_mode` 时与 `coordination_loop` 同批启动，退出时取消。
- 配置新增 `super_link_event_env: str = "local"`（非空），测试使用独立前缀。事件捕获只看 `super_link_enabled`，不看展示订阅开关。

## 3. 来源接线与事务所有者

约定：**写业务数据** = 谁改 ORM/Core SQL；**暂存** = 谁调用 `stage_*`；**seal/commit** = 谁拥有事务边界并负责 seal。非提交型辅助函数一律只暂存，不得提前 seal；提交型函数在最后一条业务 SQL 后 seal。

### 3.1 提交型函数（自己 commit）

| 文件/函数 | 业务写入 | 暂存 | seal/commit 与分支 |
|---|---|---|---|
| `store.create_run` | Run | `run.created` | 函数内 commit 前 seal |
| `store.mark_run_started` | Run 状态/启动时间 | `run.running`（实际变化才发） | commit 前 seal |
| `store.update_run_result` | Run 终态；input_required 早退分支 | `run.terminal:{status}` / `run.input_required` | 两个 commit 分支各自 seal；无变化不发 |
| `store.mark_run_failed_if_active` | 仅活动 Run | `run.terminal:failed` | commit 前 seal；未命中直接返回 |
| `store.record_artifacts` | Artifact upsert | 实际变化时 `artifacts.changed`（UUID 键） | commit 前 seal；无变化不发 |
| `store.sync_run_artifacts` | 先调用 record_artifacts（独立事务），再删除缺失行 | 两个事务分别按实际变化暂存 | 各自 commit 前 seal |
| `store.upsert_session_conversation` | 归档与 head | `continuity.archived` / `continuity.committed` | 3 个 commit 分支分别 seal；head 冲突分支 **commit 后抛错** |
| `store.delete_session` | 软删除 | `participant.unavailable`（参与会话） | commit 前 seal |
| `store.create_control` | 新介入记录 | `intervention.changed` | 新行才暂存；commit 前 seal；幂等命中不暂存 |
| `store.resolve_control` | 终态迁移 | `intervention.changed` | 实际迁移才暂存；commit 前 seal |
| `store.close_open_controls` | 批量关闭 | 每个受影响记录 `intervention.changed` | 有变更才 commit；seal 在 commit 前 |
| `dispatch_outbox.claim_due` | 领取/放弃/延迟 | 领取与放弃 | 事务退出前 seal；纯忙碌延后不发 |
| `dispatch_outbox.mark_dispatched` | 状态 | `dispatch.changed` | **非提交型**（见 3.2） |
| `dispatch_outbox.mark_submit_failed` | 状态/次数 | `dispatch.changed` | 非提交型 |
| `dispatch_outbox.reclaim_expired` | 领取版本/状态 | `dispatch.changed` | 非提交型 |
| `dispatch_outbox.stop_queued_run` | Run+dispatch | `run.changed` + `dispatch.changed` | **自带事务并 commit**；退出前 seal；无行直接返回 |
| `runtime.prepare/witness_exit/launch_failed` | Finalization | `finalization.changed` | 各自 `begin()` 退出前 seal；早退无暂存 |
| `runtime.finalize` | Finalization；保存点内发布 Message/Outbox | 发布草稿在 `events.savepoint`；外层 ready/failed | 保存点成功合并、失败丢弃；所有会返回的失败分支先暂存并 seal，再 return |
| `process_witness.record_launch` | 进程身份可用性 | `finalization.changed` | 函数自带 commit 时 seal |
| `coordination.inspect_delivery` | 领取/租约/结果 | `review.changed`（领取、租约、校验、结论） | 两个事务分别 seal；**校验失败分支在 `begin()` 内 return 前 seal** |
| `coordination.accept_delivery` | Receipt/Execution/Run/dispatch | `admission.changed` + 调用的暂存 | 事务退出前 seal |
| `coordination.accept_feedback` | Feedback/Run/dispatch | `feedback.changed` + 调用的暂存 | 事务退出前 seal |
| `coordination.enqueue_direct` | Run/turn/dispatch | Run 由本函数直接暂存 `run.created`，dispatch 由 enqueue 暂存 | 事务退出前 seal |
| `controls.control` | Space 控制/动作/Run/dispatch/turn | `space.control_changed`、`action.recorded`、continue 的 run/dispatch | 最终 return 前 seal；`old` 幂等命中不暂存；异常回滚不 seal |
| `controls.reconcile_stops` | Space 停止推进 | `space.control_changed` | 最终事务 seal；每个 Run 由 stop_queued_run 自行提交 |
| `management.recover` | 动作/额度/hold/重试 | `action.recorded`、`budget_changed`（幂等键）、对应重试事件 | 最终 return 前 seal；批量 hold 解除只发一条预算事件并 `invalidate deliveries/runs/actions` |
| `worker.recover_finalizations` | 领取/最终尝试 | `finalization.retry:{n}:claim/deferred` | 领取事务与 finally 事务分别 seal |
| `worker.admit_reviewed` | admission 错误/退避 | `admission.changed` | 最终事务 seal |
| `worker.dispatch_feedback` | feedback 错误/退避 | `feedback.changed` | 最终事务 seal |
| `transport.Delivery.consume` | 收件（经 service.receive） | `delivery.received/quarantined` | 每个 `begin()` 退出前 seal；提交成功才 ACK |
| `routes/super_link.create_space` | Space/初始 Run/turn/dispatch | `space.created`、`run.created`、dispatch | `begin()` 退出前 seal |
| `business_service.business_transaction` | 所有 HTTP 写路径的外层事务 | 由内部函数暂存 | `yield` 返回后、上下文 commit 前统一 seal；异常回滚不 seal |

### 3.2 非提交型函数（调用方拥有事务）

| 文件/函数 | 业务写入 | 暂存 | 最终 seal 位置 |
|---|---|---|---|
| `store.add_run` | 直接 add Run | `run.created` | 调用方（routes/监控/补资料/测试）提交前 |
| `dispatch_outbox.enqueue` | Dispatch；空间停止时把 Run 置 stopped 并建 ABANDONED 行 | `dispatch.changed`，必要时 `run.changed` | 调用方 |
| `dispatch_outbox.mark_dispatched` | Dispatch 状态 | `dispatch.changed` | `dispatch_once` 的第二事务 |
| `dispatch_outbox.mark_submit_failed` | Dispatch 状态/次数 | `dispatch.changed` | `dispatch_once` 失败事务 / 状态查询重试路径 |
| `dispatch_outbox.reclaim_expired` | Dispatch 领取版本 | `dispatch.changed` | `dispatch_once` 首事务 |
| `dispatch_outbox.cancel_pending` | Dispatch 状态 | `dispatch.changed` | rerun 路由 / `stop_queued_run` 调用方 |
| `dispatch_outbox.abandon_for_run` | Dispatch 状态 | `dispatch.changed` | 补资料事务（business_transaction） |
| `coordination.enqueue_automatic` | **直接 add Run**（不经过 `store.add_run`）；turn 由调用方决定 | `run.created`；dispatch 由 enqueue 暂存 | 不 seal；`accept_delivery` / `accept_feedback` / `controls.control` 在各自事务末尾 seal |
| `coordination.enqueue_direct` | Run/turn/dispatch | 同上 | 自带事务，见 3.1 |
| `service.create_pair` | Space/Participants/事件头 | `space.created` | 路由 `create_space` |
| `service.register` | Message | `delivery.registered` | 调用方（工具/路由） |
| `service.publish` | Message 状态/Outbox | `delivery.published` | `runtime.finalize` 外层事务 |
| `service.receive` | Outbox/Inbox/Message | `delivery.received/quarantined` | transport / worker |
| `input_requests.*` | Run/Dispatch/InputRequest/续接 Run | `run.changed`（input_required）、dispatch | business_transaction；worker 补资料路径各自事务 |
| `watch_scheduler.schedule_event` | Run/turn/dispatch/WatchEvent | run/dispatch | 监控循环事务 |
| `monitor_longterm.schedule/defer_launch` | Run/turn/dispatch/WatchEvent | run/dispatch | 监控循环事务 |
| `monitor_longterm.stop_cancelled_launch` | Run/dispatch 取消 | run/dispatch | `claim_due` 的领取事务 |
| `business_archive.delete_research` | 批量作废 dispatch、软删除研究 | 逐行 `dispatch.changed`（先 SELECT id/claim_version）；参与会话 `participant.unavailable` | business_transaction 的 seal |
| `routes/runs` submit/rerun/cancel | Run/turn/dispatch；rerun 直写旧 Run stopped | store/enqueue 暂存 + 直写另暂存 | `_execute` 结束后由 business_transaction seal |
| `orchestrator` 恢复/重算 | 经 store 函数 | 由 store 函数暂存 | 若审计发现直写 Run/Control，改为经 store 或补暂存+seal |

### 3.3 异常与提前提交分支

| 位置 | 行为 |
|---|---|
| `upsert_session_conversation` head 冲突 | 先暂存 `continuity.archived`、seal，再 commit，最后抛 `ContextHeadConflictError` |
| `inspect_delivery` 领取事务内校验失败 | 暂存校验结论并 seal 后 return；事务正常提交 |
| `runtime.finalize` 连续性/来源不完整 | 暂存 failed 并 seal 后 return；事务正常提交 |
| `worker.recover_finalizations` finally | 暂存 deferred，seal 后提交 |
| `controls.control` 幂等命中 | 直接返回旧记录，不暂存、不 seal |
| `dispatch_outbox.stop_queued_run` 无匹配行 | 不暂存，正常退出 |
| `dispatch_once` 直接置 ABANDONED/PENDING 的分支 | 与赋值同处暂存，退出前 seal |
| `business_archive.delete_research` 已删除 | 不暂存；外层 seal 为空操作 |

## 4. 事件目录、键与载荷

统一规则：键按 §2.6 的身份类型；载荷只含状态、计数、摘要与标识，不含正文、prompt、最终答案、私人连续性、令牌、主机/PID 或文件路径。

| 类型 | 键 | `data` 白名单 | `invalidate` |
|---|---|---|---|
| `sl.space.created` | `space:{id}:created` | goal_version, roles | space, participants, runs, deliveries, actions, interventions |
| `sl.space.control_changed` | `space:{id}:control:{version}` | control_state, control_version, paused, has_cutoff | space, runs, deliveries, interventions, actions |
| `sl.action.recorded` | `action:{space}:{idempotency_key}` | action, target_id, outcome | actions, runs, deliveries, interventions |
| `sl.space.budget_changed` | `space:{id}:budget:{idempotency_key}` | limit, used, remaining, affected_holds | space, actions, deliveries, runs |
| `sl.run.changed` | `run:{id}:created` / `:running` / `:terminal:{status}` / `:input_required` | status, pipeline_id, started, finished, stopped, error_code | runs, deliveries, interventions, actions |
| `sl.dispatch.changed` | `dispatch:{row_id}:{claim_version}:{status}` | status, attempt, claim_version, run_id | runs, deliveries |
| `sl.finalization.changed` | `finalization:{run_id}:{phase}:{version}` | state, worker_exited, exit_code, error_code, recovery_attempts | runs, deliveries, actions |
| `sl.delivery.registered` | `delivery:{message_id}:registered` | message_id, request_id, recipient_id, in_reply_to, revises_message_id, goal_version, content_sha256 | deliveries, runs |
| `sl.delivery.published` | `delivery:{message_id}:published` | message_id, request_id, source_run_id, content_sha256 | deliveries, runs |
| `sl.delivery.received` | `receipt:{message_id}:received` | message_id, transport_state | deliveries, runs |
| `sl.delivery.quarantined` | `receipt:{message_id}:quarantined:{code}` | message_id, error_code | deliveries, runs |
| `sl.review.changed` | `review:{message_id}:attempt:{n}:{phase}` / `...:action:{key}` | attempt, verdict, failure_kind, retry_scheduled | deliveries, runs |
| `sl.admission.changed` | `admission:{message_id}:{n}:{state}:{error}` / `...:action:{key}` | message_id, run_id, attempts, held, error_code | space, deliveries, runs |
| `sl.feedback.changed` | `feedback:{message_id}:{attempts}:started`（仅 `accept_feedback`）/ `feedback:{message_id}:{attempts}:{error_code}`（仅 `dispatch_feedback`）/ `...:action:{key}` | message_id, review_number, run_id, attempts, error_code | space（成功）; deliveries, runs, actions |
| `sl.intervention.changed` | `intervention:{control_id}:{status}` | control_id, kind, status, run_id, external_id | interventions, runs |
| `sl.artifacts.changed` | `artifacts:{run_id}:{change_uuid}` | run_id, count, index_sha256 | runs, deliveries |
| `sl.continuity.changed` | `continuity:{run_id}:archived\|committed` | run_id, outcome, source_run_id | runs, deliveries |
| `sl.participant.availability_changed` | `participant:{participant_id}:unavailable` | participant_id, role, available=false, reason | participants, space, runs, deliveries, interventions |

`finalization` 的 `version` 取 `recovery_attempts` 或 `action:{idempotency_key}`；`review/admission/feedback` 的重试键同理。纯状态、无版本可区分往返的记录必须补版本，否则按冲突处理。自动受理与补正成功会消耗空间预算，因此成功事件的 `invalidate` 必须包含 `space`。

## 5. 非目标

- 不实现 `/snapshot`、`/events` HTTP/SSE 接口与前端订阅（T03/T04）、运行实时输出（T05）。
- 不引入事件清理、`min_after` 推进、epoch 轮换管理入口。
- 不修复原生审批/启动通知 best-effort、steer turn 与控制记录分两次保存、Worker 无界队列等既有缺口。
- 不改普通模式提示、工具、默认 SSE、业务表结构或主迁移链。

## 6. 测试与证据

1. `tests/test_super_link_events.py`（SQLite）
   - 顺序分配、空间隔离、信封字段与 `seq` 字符串、游标格式/解析/跨空间拒绝、`read_events` 鉴权/分页/`resync_required`；读头后并发提交的事件不得越过本页 `head_seq`。
   - 相同键跨事务重试（内容一致）复用已有事件且不增序号；内容不同冲突并回滚来源。
   - 未 seal 提交抛错并回滚；seal 后 `stage_change` 拒绝；seal 后 ORM 写入在 flush/commit 时被守卫拒绝。
   - 托管保存点回滚丢弃、释放合并；未托管 `begin_nested()` 内暂存被拒绝。
   - 载荷超限、非 JSON、非法 invalidate、非法 key；监听器重复调用与 `super_link_enabled=false` 的普通会话无副作用。
2. `tests/test_super_link_event_sources.py`（SQLite）
   - 空间创建初始化头并产生 `space.created`；初始 Run/dispatch 在同一事务。
   - register/publish/receive/quarantine、review（含校验失败早退）、admission、feedback、finalization（含失败早退）、dispatch（含停止分支）、Run 生命周期、产物 A→B→A 两事件、连续性三个提交分支、参与方删除。
   - `runtime.finalize` 保存点第二条发布失败：该保存点无 `delivery.published`，外层仅留失败事实。
   - `business_service.business_transaction` 覆盖 rerun/补资料/批量删除的 seal。
   - 普通会话零事件、零事件表查询。
3. `tests/test_super_link_recovery.py`
   - 首次检查阻断 → 受理瞬时失败 → 重试成功：失败与成功事件键不同，成功事件只由 `accept_feedback` 产生，参与方/会话指向补正执行方。
   - 自动受理成功事件与补正成功事件的 `invalidate` 包含 `space`。
4. `tests/test_super_link_notifier.py`
   - 成功标记 `notified_at`；Redis 故障不标记；重启重发；重复发布可去重；启动条件谓词覆盖 readiness/restore_mode。
5. `tests/pg/test_super_link_events.py`（隔离 PostgreSQL，已执行 6 passed）
   - A01：A 先 seal 未提交，B seal 阻塞；A 提交后 B 取更大号；A 回滚后 B 取下一有效号且无残留。
   - 双空间按 UUID 锁序无死锁；事件外键指向事件头，持 Space 行锁不会阻塞事件插入。
   - 事件写失败/头缺失时来源 Run 一并回滚；迁移补齐基线头。

回归：`uv run pytest tests/test_super_link*.py tests/test_web_dispatch_recovery.py tests/test_context_inheritance.py`；定向 Ruff、Pyright。

## 7. 验收映射

| 要求 | 证据 |
|---|---|
| 状态与事件同事务 | 来源测试断言业务行不存在时事件也不存在；事件异常回滚用例 |
| 保存点 | `events.savepoint` 丢弃/合并用例 + finalize 发布失败用例 + 未托管保存点拒绝 |
| 晚提交与回滚（A01） | PG 双连接测试 |
| 跨事务重试幂等 | 相同键内容一致复用、内容不同冲突的回滚用例 |
| seal 后写入 | ORM flush/commit 守卫用例；Core SQL 顺序契约说明 |
| Redis 故障与重启 | 发布器故障注入与重发测试；业务提交不受影响 |
| 来源覆盖 | §3 每类至少一个事件类型/关联 ID 断言，覆盖监控、补资料、重算、批量取消、孤儿恢复 |

## 8. 风险与回滚

- 事件头锁最后取得会增加收尾事务持锁时间；seal 后立即提交，禁止再执行外部调用。
- 遗漏 seal 的提交会被守卫拒绝并在测试暴露；这是有意的失败方式。
- 迁移只新增表并为既有空间补头；回退代码前关闭事件捕获，重新启用需换 epoch（部署阶段执行，不在本批）。
- 业务库不迁移；所有 PG 测试使用隔离库。

## 9. 实施状态

本规格已批准并实施；收尾修复了反馈事件键、事件外键、分页上界与预算失效。SQLite 与隔离
PostgreSQL 验收已执行，未启动服务、未连接或迁移业务库。实现与验证的区分及全量套件基线
归因见计划 §20.8。
