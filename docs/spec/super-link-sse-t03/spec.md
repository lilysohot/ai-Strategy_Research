# SSE-T03 空间快照与 SSE 接口 实施规格

| 项目 | 内容 |
|---|---|
| 状态 | 已实施并验证；证据见 §10。未启动本机服务、未连接或迁移业务库 |
| 依据 | [技术框架 §11.5—§11.9](../../design/super-link-technical-design.md#115-快照与订阅接口)；[SSE 设计稿](../../design/super-link-sse-design-notes.md)；[建设计划 §20](../../plan/super-link-communication-foundation.md#20-sse-状态同步执行计划2026-11-20) |
| 任务 | SSE-T03：独立空间快照/订阅接口、补读、鉴权、心跳、连接释放和有界缓冲 |
| 前置 | SSE-T02 已完成：事件账本、空间序号、`sl1` 游标、`read_events`、Redis head 提示均可用 |
| 本版定案 | 快照与游标同一提交边界；`after` 必填；先补读后观察；通知只加速、数据库为准；错误矩阵与连接资源上限 |

## 0. 本版要解决的关键问题

1. **快照切流无空隙。** 快照必须在同一只读事务内同时读取事件头与空间视图，返回的游标恰好
   覆盖该事务看到的状态；不能先读状态再读游标，也不能为 SSE 长连接保留事务。
2. **`min_cursor` 是“至少看到这里”的下界。** 只接受同空间、同 epoch、且不超过当前事件头的
   游标；不满足时明确失败，不自动夹到当前值。
3. **SSE 先补读、再观察。** 建连时从 `after` 之后按空间序号逐批补读；补读完成后才等待通知或
   周期核对。Redis 通知丢失、迟到或重复都不影响正确性。
4. **Run 终态不是空间终态。** 单个 Run 完成、失败或停止只产生事实事件，不关闭空间订阅；
   空间进入停止状态、控制状态变化也不关闭观察。下一次 Run、审批、交付仍可在同一连接上到达。
5. **错误与生命周期分开表达。** HTTP 建连错误（400/401/404/410/429/503）与流内控制帧
   （`sl.auth_required`、`sl.resync_required`、`sl.unavailable`）语义固定；寿命到期、慢客户端
   和普通 EOF 只表示需要重连，不发明业务失败状态。
6. **连接资源有界。** 每连接缓冲 256 帧且不超过 1 MiB；心跳 15 秒、权限复核 15 秒、单连接
   最长 5 分钟、每用户最多 8 条空间连接。慢客户端只影响自己的连接；多个 Run 与标签页共用
   一条空间连接，服务端不为每个标签页重复执行研究。
7. **不扩大 T02 事务边界。** 本批不新增表、不新增迁移，不改事件捕获、seal 顺序或业务写入。

## 1. 目标与完成定义

1. 新增 `GET /api/super-link/spaces/{space_id}/snapshot`：返回一致快照、精确总数、分页继续
   位置和事件游标。
2. 新增 `GET /api/super-link/spaces/{space_id}/events?after=<cursor>`：SSE 补读与持续观察。
3. 快照读取使用短生命周期只读 `REPEATABLE READ` 事务；读取结束立即释放，SSE 期间不持有
   数据库事务。
4. 复用 T02 的 `read_events`、游标解析、事件信封、错误码与 Redis 频道；不复制第二套事件
   读取逻辑。
5. 建连鉴权与流中复核均校验用户状态和空间归属；跨用户、跨空间、过期游标、事件链不可用
   有确定响应。
6. 每条连接有独立有界缓冲；慢客户端触发重连提示并释放资源，不阻塞其他连接或数据库。
7. 只在 `super_link_enabled=true` 时可达；关闭时保持普通模式零查询、零监听器副作用。

## 2. 接口契约

### 2.1 快照

`GET /api/super-link/spaces/{space_id}/snapshot`

| 参数 | 规则 |
|---|---|
| `space_id` | 路径 UUID；必须属于当前用户且用户状态为 `active` |
| `min_cursor` | 可选 `sl1:<space>:<epoch>:<seq>`；见 §3.3 |
| `limit` | 每个列表独立分页，默认 50，范围 1—200 |
| `runs_after` | 可选 UUID；上一页 `runs.next_after` |
| `deliveries_after` | 可选 UUID；上一页 `deliveries.next_after` |
| `pending_after` | 可选 UUID；上一页 `pending_interventions.next_after` |
| `actions_after` | 可选 UUID；上一页 `actions.next_after` |

续页锚点必须属于当前空间（待审批需是该空间的审批记录，即使它已不再 pending）；锚点
不存在或跨空间返回 400 `invalid_cursor`。四个列表可独立续页，互不影响。

成功响应 `200 application/json`：

```json
{
  "schema_version": 1,
  "cursor": "sl1:11111111-1111-4111-8111-111111111111:22222222-2222-4222-8222-222222222222:42",
  "as_of": "2026-11-20T04:00:01Z",
  "durability_scope": "committed_records",
  "space": {
    "space_id": "11111111-1111-4111-8111-111111111111",
    "goal": "共同研究目标",
    "goal_version": 1,
    "paused": false,
    "control_state": "active",
    "control_version": 0,
    "delivery_cutoff": null,
    "can_control": true,
    "automatic_budget": {"used": 0, "limit": 20, "remaining": 20}
  },
  "participants": [
    {
      "participant_id": "33333333-3333-4333-8333-333333333333",
      "session_id": "44444444-4444-4444-8444-444444444444",
      "role": "team",
      "available": true
    }
  ],
  "runs": {"items": [], "total": 0, "next_after": null},
  "deliveries": {"items": [], "total": 0, "next_after": null},
  "pending_interventions": {"items": [], "total": 0, "next_after": null},
  "actions": {"items": [], "total": 0, "next_after": null},
  "active_run_ids": [],
  "capabilities": {"replay": true, "live_output": "local_owner_only"}
}
```

- `cursor` 是快照事务看到的事件头位置；客户端必须用它作为 SSE 的 `after`。
- `as_of` 是服务端生成快照的时间；超时、连接健康等展示信息不写成已落库事实。
- `space` 与现有空间详情字段一致；`automatic_budget` 复用 `automatic_budget(session, space)`。
- `participants` 返回该空间全部参与方；`available` 由参与研究会话是否软删除推导，不新增
  可写业务状态。
- `runs` / `deliveries` / `actions` 按 `created_at DESC, id DESC` 排列；`pending_interventions`
  按 `created_at ASC` 排列。`total` 是完整列表的精确总数（不随续页缩小），`next_after` 是本页
  最后一项的 ID；没有更多项时为 `null`。
- `runs.items` 直接使用 `management.run_status`，与现有 Run 列表/详情字段一致；`deliveries.items`
  直接使用 `management.delivery_status`，与现有交付接口一致。本批不新造第二套摘要 schema，
  避免前端和测试同时维护两种投影。
- `pending_interventions.items` 使用 `store.control_to_dict`；只包含
  `kind=approval`、`status=pending` 且 Run 仍为 `running` 的记录。
- `active_run_ids` 使用 `controls.active_runs`，即 `queued/running` 的 Run ID。
- `durability_scope` 固定为 `committed_records`：只保证已提交记录；用量、token 与实时文本
  不在此快照的一致性范围内。

### 2.2 空间事件流

`GET /api/super-link/spaces/{space_id}/events?after=<cursor>`

| 参数 | 规则 |
|---|---|
| `space_id` | 路径 UUID；必须属于当前用户且用户状态为 `active` |
| `after` | **必填** `sl1` 游标；缺失、格式错误、跨空间、超过当前头均拒绝 |

成功响应 `200 text/event-stream`，响应头包含：

```text
Cache-Control: no-cache
X-Accel-Buffering: no
```

事实帧格式：

```text
event: sl.fact
id: sl1:11111111-1111-4111-8111-111111111111:22222222-2222-4222-8222-222222222222:43
data: {"schema_version":1,"event_id":"...","type":"sl.run.changed","space_id":"...","stream_epoch":"...","seq":"43","cursor":"sl1:...","transaction_id":"...","recorded_at":"...","source":{"kind":"run","id":"..."},"participant_id":"...","session_id":"...","run_id":"...","data":{},"invalidate":["runs"]}

```

- `id` 与 JSON `cursor` 相同；`seq` 是十进制字符串。
- 客户端显式保存“已成功处理或已安全登记失效”的游标，重连时用 `after`。
- **不接受** `Last-Event-ID` 作为第二套隐式游标；请求头存在时忽略。
- 空行分隔帧；JSON 使用紧凑编码，正文换行由 JSON 转义，不破坏 SSE 分帧。
- 心跳使用 SSE 注释帧：`: heartbeat\n\n`，不带 `id`，不推进业务游标。

流内控制帧（均不带 `id`，不推进游标）：

| 事件名 | 触发 | `data` 最小字段 |
|---|---|---|
| `sl.auth_required` | 用户停用、空间归属失效或凭据复核失败 | `{"schema_version":1,"reason":"auth_lost"}` |
| `sl.resync_required` | epoch 变化、`after < min_after`、游标跨空间或在流中失效 | `{"schema_version":1,"reason":"cursor_expired"}` |
| `sl.unavailable` | 事件头缺失、数据库错误、事件链不可用 | `{"schema_version":1,"reason":"event_chain_unavailable"}` |

控制帧发送后连接关闭；客户端按控制帧决定重新认证、重新取快照或退避重连。单连接达到
最长寿命或慢客户端缓冲溢出时直接关闭连接，不新增协议控制帧；两者都按普通传输结束处理，
客户端用最近已处理游标重连。普通 EOF 不是业务终态。

### 2.3 HTTP 错误映射

| 条件 | 状态码 | 响应体 |
|---|---|---|
| 未提供或无效 bearer 凭据 | 401 | 既有统一认证错误 |
| 功能关闭 | 404 | `super_link_disabled`（沿用路由级 `_enabled`） |
| 空间不存在、不属于用户、用户非 `active` | 404 | `not_found`；不返回事件头或游标范围 |
| `after` / 续页锚点缺失、格式错误、跨空间、`seq > head.last_seq` | 400 | `invalid_cursor` |
| epoch 不符或 `after < head.min_after` | 410 | `resync_required` |
| 超过每用户连接配额 | 429 | `too_many_connections`，`Retry-After: 5` |
| 事件头缺失、迁移未完成、数据库不可用 | 503 | `event_chain_unavailable` |

快照与 SSE 建连使用同一套映射；SSE 建连错误必须在返回 `StreamingResponse` 之前产生，不能
先返回 `200` 再在流内用错误文本冒充 HTTP 状态。

## 3. 一致快照

### 3.1 事务边界

新增 `server/super_link/stream.py`：

```python
@asynccontextmanager
async def snapshot_session() -> AsyncIterator[AsyncSession]:
    """Short-lived read-only transaction; never held by an SSE connection."""
```

- 打开一个 `AsyncSession` 并显式 `begin()`。
- PostgreSQL 在上面的第一条语句执行
  `SET TRANSACTION ISOLATION LEVEL REPEATABLE READ`；SQLite 及其他测试方言不执行该语句，
  但仍使用单一事务读取。生产部署以 PostgreSQL 为一致性目标。
- 先读取 `super_link_event_heads` 建立快照边界，再在**同一 session**内读取空间、参与方、
  Run、交付、待审批与操作列表。查询函数不得内部另开 session。
- 读取完成后正常提交/退出并释放连接；不取行锁、不写库、不执行外部调用。
- 事件头不存在视为 `event_chain_unavailable`（503），不返回空游标或从 0 开始猜测。

`snapshot_payload(session, *, user_id, space_id, min_cursor, limit)` 是纯读取函数，接收调用方
session；`read_snapshot(...)` 负责打开 `snapshot_session()` 并返回 payload。拆开是为了让
PostgreSQL 测试能在同一事务内插入并发提交并验证快照边界。

### 3.2 无空隙保证

设快照事务看到的事件头为 `(epoch, C)`，返回游标 `sl1:<space>:<epoch>:C`。任何在快照事务
快照点之后提交的事件，其序号必然大于 `C`，因此 `read_events(after=快照游标)` 会返回它们。
客户端必须使用快照返回的游标切流；不得使用另一 epoch 的游标，也不得先订阅再从响应头
猜测位置。

如果快照生成后、SSE 建连前又提交了事件，补读会从 `C+1` 开始逐批返回；这是正常路径，不是
重同步。重复提交或重复通知不会产生重复帧，因为读取条件固定为 `seq > after`。

### 3.3 `min_cursor`

`min_cursor` 只用于“客户端已经看到某个位置，要求新快照至少不早于它”：

1. `parse_cursor` 失败或空间不符 → 400 `invalid_cursor`。
2. epoch 与当前头不同，或 `seq < head.min_after` → 410 `resync_required`。
3. `seq > head.last_seq` → 400 `invalid_cursor`；不自动夹到当前头。
4. `seq <= head.last_seq` 时继续读取；返回的 `cursor` 是本次快照头，通常大于等于
   `min_cursor`。快照必须从主库读取，不使用复制延迟的只读副本。

客户端收到事件 42 后发起快照刷新：若旧请求返回游标 40，客户端丢弃旧响应；只有覆盖 42 的
快照才替换当前确定状态。快照不包含完整历史事件，事件历史仍按需用 `after` 补读。

### 3.4 分页与旧响应

- `next_after` 是“读取当时的当前状态”的继续位置，不是旧快照的一部分；后续分页响应带自己的
  时点，前端不得用旧分页覆盖较新快照。
- 快照的 `runs_after`/`deliveries_after`/`pending_after`/`actions_after` 与
  `/interventions` 的 `pending_after` 都是可用的续页入口；每次响应都带自己的 `cursor`。
- 续页只按 `(created_at, id)` 稳定边界推进；同一秒/同一毫秒内的多条记录由 `id` 打破平局，
  不重复也不跳过。SQLite 下按毫秒归一化比较，避免 `CURRENT_TIMESTAMP` 的秒精度与服务端
  绑定参数格式不一致；PostgreSQL 保留原生微秒精度。
- 前端不得把未加载项视为已删除；历史阅读保留滚动位置（前端行为在 T04 验收）。
- 待审批列表独立分页，不受 Run/交付分页影响。

## 4. 事件流实现

### 4.1 建连顺序

1. 路由解析 bearer 用户；`management.owned_space` 校验归属与用户状态。
2. 校验 `after`：调用一次 `events.read_events(..., limit=1)`（或等价的游标校验）以复用
   T02 的 `invalid_cursor` / `resync_required` / `not_found` / `event_head_missing` 语义。
3. 申请连接配额；失败返回 429。
4. 返回 `StreamingResponse`；生成器启动后严格按以下顺序运行：
   - 注册空间通知监听（含共享头核对）；
   - 从 `after` 开始按 200 条一批补读，直到读到该次读取头；
   - **再次核对事件头**：若头已前进，继续补读；直到某一轮补读后头未变化；
   - 将补读到达的位置登记为已同步，等待通知或周期核对；
   - 重复直到连接终止。

先注册监听再补读是允许的：即使通知先到，补读仍以数据库为准，不会漏读或重复。最后一步
“再次核对头”用于收口补读期间的新提交，不能省成“读空一批就直接等待”。

### 4.2 补读与等待

- 每批一个短只读事务，复用 `events.read_events`；每批重新校验空间归属、epoch 与
  `min_after`，避免清理、恢复或换 epoch 后静默跳读。
- 每批最多 200 条，按 `seq` 升序发送；`next_cursor` 推进到最后一条。
- 一批返回 200 条时立即继续下一批；不足 200 条后执行一次头核对，头未变化才进入等待。
- 后台按**活跃空间共享**核对头：每 2 秒对全部活跃空间做一次事件头查询，发现
  `(stream_epoch, last_seq)` 变化才唤醒该空间的连接；不是每条连接各查一次。
- 连接等待共享提示；收到提示后补读。通知只含 `space_id`、`stream_epoch`、`head_seq`，
  不含正文或令牌；解析失败、重复或空间不符时忽略。通知丢失只增加同步延迟，由共享周期
  核对修复。
- 共享核对查询失败时，向该空间连接发送“需要确认”的内部提示；连接自行补读一次，确认失败
  才发送 `sl.unavailable`，不能因一次轮询失败伪造不可用。

### 4.3 心跳、权限复核与寿命

生产者循环在每次醒来时检查；**每批发送前**也检查复核是否到期或是否已知撤权：

| 检查 | 默认 | 行为 |
|---|---|---|
| 空闲心跳 | 15 秒 | 无事实帧可发时发送 `: heartbeat` 注释帧 |
| 权限复核 | 15 秒 | 重新读取用户状态与空间归属；失败发送 `sl.auth_required` 并关闭 |
| 单连接寿命 | 5 分钟 | 直接关闭连接，客户端重新鉴权并从已处理游标重连 |

- 权限复核使用短事务，不读取模型上下文；数据库暂时不可用时只记录并继续，下一次补读会走
  `sl.unavailable`，不能把查询失败误判为撤权。
- bearer token 的有效期在建连时校验；流中复核以账号状态、空间归属为主，token 过期由 5 分钟
  重连重新校验，传播上界为最长连接寿命。
- 心跳与权限复核都不能推进游标；控制帧不带 `id`。寿命到期直接关闭，不新增协议帧。
- 寿命是**整个响应迭代**的上限：无论卡在网络发送还是数据库读取，到期都会取消生成器并
  执行其 `finally`，释放连接配额与 Hub 订阅；响应层对单次发送另有 15 秒上限。
- 空间 `control_state` 变为停止、Run 进入终态或交付完成，都不结束观察。

### 4.4 有界缓冲与慢客户端

每条连接使用独立 `FrameBuffer`：

- 上限：256 帧或 1 MiB（以先到者为准）。
- 生产者任务负责补读与等待，将已格式化帧放入缓冲；网络消费生成器按 FIFO 取出并 `yield`。
- 缓冲满时：生产者等待消费者腾出空间；等待超过发送上限（且不超过剩余寿命）才清空并
  直接关闭连接，不新增协议控制帧。客户端用最后已处理游标重连，未发送事实仍可从数据库
  补读。
- 缓冲只影响该连接；不建立全局帧队列，不按客户端速度反压模型或数据库。
- 事实载荷上限沿用 T02 的 16 KiB；本批不引入预览帧或逐 token 数据（T05）。

### 4.5 通知与共享头核对

新增进程内 `SpaceHintHub`：

- 首个订阅者出现时惰性启动一个 Redis Pub/Sub 监听任务和一个共享头核对任务；最后一个
  订阅者释放后停止两者。
- 频道使用 `events.event_channel(cfg)`；消息格式与 T02 发布器一致。
- 共享核对每 2 秒对全部活跃空间查询一次事件头，按空间比较 `(stream_epoch, last_seq)`；
  变化时唤醒该空间订阅者。查询使用短事务，不为连接持有事务。
- 按 `space_id` 唤醒对应订阅者；epoch 不符也唤醒，让连接在补读时得到
  `sl.resync_required`。
- Redis 连接失败、断开或消息损坏时记录并退避重试（初始 2 秒）；共享核对继续工作。
- 测试使用 `SpaceHintHub(listen=False)`、直接调用 `dispatch`/`poll_once`，或注入假
  sessionmaker，不依赖真实 Redis。

### 4.6 连接配额

- 进程内 `ConnectionLimiter`：按用户计数，默认最多 8 条空间连接。
- 达到上限返回 429，`Retry-After: 5`；不进入流、不注册监听。
- 生成器 `finally` 释放配额、取消生产者、注销监听并关闭缓冲；客户端断开或服务取消同样释放。
- 首版单 API 运行所有者（T01），进程内计数即满足约定拓扑；多实例路由不在本批承诺。

## 5. 模块与配置

| 位置 | 变更 |
|---|---|
| `server/super_link/stream.py` | 新增：`snapshot_session`、`snapshot_payload`、`read_snapshot`、`FrameBuffer`、`ConnectionLimiter`、`SpaceHintHub`、`event_stream` |
| `server/routes/super_link.py` | 新增 snapshot/events 路由；错误映射；不改变现有路由 |
| `server/config.py` | 新增 SSE 参数（见下） |
| `server/super_link/events.py` | 不改读取语义；必要时只补内部复用的小辅助函数，不改变已验收行为 |
| 迁移 | 无新增表、无新迁移 |
| `server/app.py` | 不改；Hub 惰性启动，不新增启动任务 |

配置默认值：

```python
super_link_sse_heartbeat_seconds: float = 15.0
super_link_sse_poll_seconds: float = 2.0
super_link_sse_auth_recheck_seconds: float = 15.0
super_link_sse_max_age_seconds: float = 300.0
super_link_sse_max_connections: int = 8
super_link_sse_buffer_frames: int = 256
super_link_sse_buffer_bytes: int = 1_048_576
super_link_sse_send_timeout_seconds: float = 15.0
```

均为正数；测试可调小以缩短等待。它们是实现初值，不是性能验收结论；T06 测量后可调整，
但不改变有界、补读与恢复语义。

## 6. 测试与证据

### 6.1 SQLite：`tests/test_super_link_stream.py`

快照：

- 完整字段、`cursor == head`、空间/参与方/预算/活动 Run；列表排序、`total`、`next_after`、
  `limit` 上下界。
- 快照游标切流：取快照 → 提交新事件 → `read_events(after=snapshot.cursor)` 只返回新事件，
  证明无空隙。
- `min_cursor`：同空间同 epoch 且不超前成功；格式错误/跨空间/超前返回 400；epoch 不符或
  小于 `min_after` 返回 410。
- 归属：其他用户 404；功能关闭 404；事件头缺失 503。
- 数据库异常：注入 SQLAlchemy `OperationalError`/`ProgrammingError` 时，快照与 SSE 建连
  均返回 503 `event_chain_unavailable`，不漏成 500。
- 续页完整性：4 条 Run 与 4 条待审批各以 `limit=1` 逐页遍历，快照与 `/interventions`
  两个入口都无重复、无遗漏；续页响应携带自己的 `cursor`。
- 待审批独立分页，不被 Run/交付分页影响。

SSE：

- `after` 缺失/坏格式/跨空间/超前 → 400；epoch 过期/`after < min_after` → 410；
  其他用户 → 404；事件头缺失 → 503。
- 建连补读：游标 0 起依次收到 `sl.fact`，`id` 与 JSON `cursor` 一致，`seq` 为字符串。
- 重复去重：以已处理游标重连只收到之后的帧。
- Run 终态事件到达后连接继续；空间 `control_state` 变为停止后连接仍继续；随后提交的新事件
  仍可收到。
- 补读收口：补读期间提交的事件在“再次核对头”时被继续读出，不要求客户端立刻重连。
- 空闲心跳：调小间隔后收到 `: heartbeat` 注释帧。
- 权限复核：流中停用用户或移除空间归属，收到 `sl.auth_required` 并关闭。
- 流中 epoch 变化/`min_after` 推进：收到 `sl.resync_required` 并关闭。
- 数据库读取异常/事件头缺失：收到 `sl.unavailable` 并关闭，游标不前进。
- 最长寿命：调小后连接直接结束（无额外协议帧），客户端可从已处理游标重连。
- 有界缓冲：`FrameBuffer` 帧数/字节上限、满载时生产者等待、消费者取帧后唤醒、
  超时关闭、消费者能退出。
- 大载荷积压：100 条 × 12 KB 合法事件、64 KiB 连接缓冲，快速消费者仍能逐帧前进到当前
  事件头，游标不丢失。
- 慢客户端释放：ASGI send 永久阻塞时，响应层按单次发送超时与总寿命中止发送，生成器
  `finally` 仍释放连接配额与 Hub 订阅。
- 读取挂起释放：`read_events` 永不返回时，总寿命仍会取消整个响应迭代并释放配额与订阅。
- 列表一致性：`/runs`、`/deliveries`、`/recovery-actions`、`/interventions` 在同一
  `snapshot_session` 内先读事件头再读内容，项目投影期间提交的新事件不会让返回游标新于
  内容。
- 旧列表续页：`/runs` 等 newest-first 入口使用与快照相同的方言感知时间键；数据库默认
  时间（同秒）下第一页、第二页不再返回同一 `run_id`。
- 共享头核对：同一空间多个订阅者只触发一次头查询；`poll_once` 在头变化时唤醒全部订阅者，
  头未变时不唤醒；轮询查询失败时不伪造不可用。
- Hub 缓存边界：无订阅空间的通知不写入 `_known`；只保留活跃空间，退订后不残留。
- 配额：预占 1 条后第二条请求 429；生成器结束后配额释放。
- 关闭 Super-link 时路由 404，且不启动 Hub、不查询事件表。

### 6.2 隔离 PostgreSQL：`tests/pg/test_super_link_stream.py`

- `snapshot_session()` 的 `REPEATABLE READ` 边界：事务内先读事件头建立快照 → 另一连接提交
  `space.control_state` 与事件 → 本事务内继续调用 `snapshot_payload`，仍看到旧状态与旧游标；
  事务结束后新快照看到新状态与新游标；`read_events(after=旧游标)` 返回该事件。
- 不新增 PG 并发模型，不连接业务库；使用既有 `PG_INTEGRATION=1`、`apodex_biz_test` 与
  可选迁移夹具。

### 6.3 回归

- `uv run pytest tests/test_super_link*.py tests/test_web_dispatch_recovery.py tests/test_context_inheritance.py`
- 定向 Ruff；定向 Pyright（新增模块与路由）。
- 普通 Single/Team、审批、停止与既有 Run SSE 不因新路由改变；不启动服务。

## 7. 验收映射

| 计划场景 | 本批证据 |
|---|---|
| SSE-A02 快照读取期间持续变化、历史与实时重叠、游标过期 | 快照切流测试；PG REPEATABLE READ 边界；410 重新同步 |
| SSE-A05 高速事件、慢客户端、SSE 断开、Redis 故障 | `FrameBuffer` 上限与溢出；Hub 失败后周期核对；断开释放 |
| SSE-A07 跨用户/空间订阅与补读、令牌失效 | 404/400/410 断言；流中撤权 `sl.auth_required`；无跨空间事件 |
| Run 终态/空间停止不关闭空间观察 | 终态与停止帧后继续提交并接收新事件 |
| 普通模式兼容 | 关闭功能路由 404；既有回归通过 |

## 8. 非目标

- T04 前端订阅、状态管理、分页与旧响应丢弃；T05 实时文本/思考/工具预览；T06 代理链路、
  真实 Worker、指标与容量验收；T07 部署与启用。
- 不支持 `Last-Event-ID`，不新增第二套游标。
- 不做事件清理、`min_after` 推进或 epoch 轮换管理入口。
- 不做多 API 实例的实时输出或控制路由；首版仍为单 API 运行所有者。
- 不修复 T01 登记的既有原生来源持久化缺口与 Worker 无界队列。

## 9. 风险与回滚

- 长连接会占用连接配额与内存；通过心跳、15 秒复核、5 分钟寿命、每用户 8 条和每连接有界
  缓冲限制。慢客户端直接断流并由客户端补读，不无限堆积。
- 快照对 50 条 Run/交付逐项调用现有投影可能产生较多查询；共享头核对只查事件头，不读取
  业务列表。T06 测量后再决定是否批量优化，本批不改变已有投影语义。
- Redis 不可用只延迟通知，不影响补读正确性；不把 Pub/Sub 当权威。
- 本批无数据库变更；回退只需移除新路由/配置并恢复前端不使用新接口，不删除已提交事件或
  业务数据。

## 10. 实施状态

已实施并验证（2026-11-20）。`server/super_link/stream.py` 提供一致快照、SSE 补读/观察、
有界缓冲、连接配额与共享头核对；`server/routes/super_link.py` 新增快照与事件流路由；
`server/config.py` 增加八项 SSE 参数。未新增表或迁移。

验收收尾（同日）补齐了六项契约：

- 读进度：`FrameBuffer.put` 在满载时等待消费者并带超时，批次背压推进；100 条 × 12 KB
  合法事件在 64 KiB 缓冲下仍可完整送达。
- 连接释放：`SSEStreamingResponse` 对每次 ASGI send 施加上限，并叠加总寿命 deadline；
  send 阻塞时中止响应并 `aclose()` 生成器，配额与 Hub 订阅同步释放。
- 错误映射：快照与 SSE 建连把 `SQLAlchemyError` 映射为 503 `event_chain_unavailable`。
- 分页：快照四个列表接受 `*_after`，`/interventions` 接受 `pending_after`/`limit`；
  `total` 为完整列表数，各响应带自己的 `cursor`；SQLite 按毫秒归一化时间键，PostgreSQL
  保留微秒精度，续页不重复、不跳过。
- 列表一致性：`/runs`、`/deliveries`、`/recovery-actions`、`/interventions` 统一走
  `snapshot_session`，先读事件头再读内容；旧 `/runs` 等 newest-first 续页也复用同一
  方言感知时间键，不再原地重复。
- 连接寿命：响应层 deadline 覆盖整个迭代；数据库读取永久挂起时同样取消生成器并释放
  配额与订阅。
- Hub 缓存：只为有订阅的空间写 `_known`，退订即清空。
- 测试：上述路径均已加入 `tests/test_super_link_stream.py`。

验证结果：

- SQLite `tests/test_super_link_stream.py`：26 passed。
- 隔离 PostgreSQL `tests/pg/test_super_link_stream.py`：2 passed
  （`PG_INTEGRATION=1`、`apodex_biz_test`，覆盖 REPEATABLE READ 边界与 `min_cursor`）。
- Super-link 非 PG 回归 `tests/test_super_link*.py`：142 passed。
- `tests/test_context_inheritance.py`、`tests/test_web_dispatch_recovery.py`：83 passed。
- 定向 Ruff 与 Pyright（新增模块、路由、配置）通过。

限制：未启动本机服务，未连接或迁移业务库；真实 Redis Pub/Sub、代理链路、浏览器与真实
Worker 留待 T06。按规格 §8，本批不宣称 SSE 已可正式启用。完成记录见计划 §20.9。
