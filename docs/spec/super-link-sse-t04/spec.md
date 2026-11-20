# SSE-T04 前端关键状态闭环 实施规格

| 项目 | 内容 |
|---|---|
| 状态 | **已实施（2026-11-20）**；前端单测 135 passed、typecheck 与生产构建通过；未修改服务器逻辑、未启动服务、未连接业务库，真实浏览器与代理链路留待 T06 |
| 依据 | [技术框架 §11.5—§11.9](../design/super-link-technical-design.md#115-快照与订阅接口)；[SSE 设计稿 §4.4—§4.5](../design/super-link-sse-design-notes.md)；[T03 规格](../spec/super-link-sse-t03/spec.md)；[建设计划 §20](../../plan/super-link-communication-foundation.md#20-sse-状态同步执行计划2026-11-20) |
| 任务 | SSE-T04：Super-link 独立订阅与状态管理 |
| 前置 | T03 已完成：`/snapshot` 与 `/events` 可用，快照与游标同一事务边界，HTTP 错误矩阵固定 |
| 本版定案 | 快照接流、事实事件只推进游标并按 `invalidate` 合并、旧响应丢弃、离线性重同步、离开页面释放连接；普通模式与 `openRunStream` 行为不变 |

## 0. 本版要解决的关键问题

1. **快照接流不能有缝。** 页面必须先用 `/snapshot` 得到一致状态与游标，再用该游标建立
   `/events`；不得先订阅再猜位置，也不得用列表接口的分页游标代替事件游标。
2. **事实事件是“失效信号”，不是完整状态。** 客户端收到 `sl.fact` 只推进游标、记录
   `invalidate` 视图，再按视图批量重读快照并合并；不能把事件 `data` 直接当最终状态渲染。
3. **旧响应必须可丢弃。** 并发快照、慢请求、切换空间和重新同步都可能让较旧响应晚到。
   只有“当前空间 + 当前请求序号 + 游标不倒退”的响应可以写入状态。
4. **历史阅读不被抢页。** 用户加载较早记录后，新事件只累计“有新更新”提示，不自动
   prepend/重排列表，不覆盖对话框、未提交输入或控制表单。
5. **断线不等于业务失败。** 连接中断、寿命到期、`sl.unavailable` 只表示展示层待同步；
   保留最近一次已确认状态并退避重连，只有鉴权失效或空间不存在才终止。
6. **离开即释放。** 切换空间、路由离开、组件卸载必须 abort fetch、取消定时器、忽略迟到
   回调；不把旧空间的订阅或状态带入新空间。

## 1. 目标与完成定义

1. 新增独立于普通模式的前端空间同步模块：初始快照 → SSE 订阅 → 按 `invalidate` 刷新 →
   重连/重新同步 → 释放。
2. `SuperLinkView.vue` 的空间详情改用该模块，不再用 5 秒轮询拼三个独立列表接口。
3. 审批/控制/交付列表进入同一同步状态：待审批、活动运行、恢复操作由快照与事件驱动，
   控制面板不再以自有轮询作为唯一事实来源。
4. 历史分页继续可用：运行、交付、恢复操作可加载更早记录；加载后不被实时更新挤走。
5. 页面离线期间完成的收尾、审批、交付与交接，在返回后通过快照 + 补读恢复准确；不触发
   任何额外模型执行或重复派发。
6. 普通 single/team、`openRunStream`、会话页与既有控制表单行为不变。
7. 不新增后端接口、不新增迁移、不改变 T03 契约；只消费已冻结的字段。

## 2. 复用边界（先盘点再实现）

| 现有位置 | 当前事实 | T04 处理 |
|---|---|---|
| [sse.ts](../../../web/src/sse.ts) `openRunStream` | 运行级流：数字 `seq`、终态帧结束、内部重试 | **不复用整个函数**。空间流游标是 `sl1` 字符串、没有业务终态、控制帧决定重同步，语义不同 |
| [sse.ts](../../../web/src/sse.ts) `extractFrames` / `parseFrame` / 退避 | 纯函数，适合两种流共用 | 抽到 `web/src/utils/sseFrames.ts`；`sse.ts` 改为导入，行为不变；新增 `event`/`id` 字段返回，运行流忽略 |
| [SuperLinkView.vue](../../../web/src/views/SuperLinkView.vue) | 5 秒轮询 `space` + `runs` + `deliveries`；三个请求无共同游标 | 空间详情改为快照 + SSE；列表页 `/spaces` 保持原加载/手动刷新 |
| [SuperLinkControls.vue](../../../web/src/components/SuperLinkControls.vue) | 每 3 秒轮询 `/interventions`，自己保存 pending/active/recent | pending/active 改由父级同步状态传入；保留 30 秒低频 `/interventions` 兜底，仅用于 `recent` 与旧接口兼容 |
| [api/superLink.ts](../../../web/src/api/superLink.ts) | 有空间、运行、交付、审批接口，无快照类型 | 增加 `snapshot()` 与 `SpaceSnapshot`/`SnapshotPage`/`SnapshotQuery` 类型；旧接口保留 |
| `api/client.ts` | 统一 bearer、`ApiError.status/detail` | 快照请求复用它；SSE 用 token provider，不新建第二套认证 |

`openRunStream` 的调用方（`stores/runs.ts`、ChatView）**不得修改**。抽取帧解析属于纯机械
移动，以现有测试、typecheck 和 build 作为回归门槛。

## 3. 客户端接口契约

### 3.1 快照请求

`GET /api/super-link/spaces/{space_id}/snapshot`

```ts
interface SnapshotQuery {
  min_cursor?: string
  limit?: number
  runs_after?: string
  deliveries_after?: string
  pending_after?: string
  actions_after?: string
}
```

使用规则：

| 场景 | 参数 | 结果处理 |
|---|---|---|
| 首次进入空间 | 无 `min_cursor`，`limit=50` | 全量替换本地状态，记录 `cursor` |
| 已建流后刷新 | `min_cursor=<本地 cursor>`，`limit=50` | 只合并 `invalidate` 命中的列表；游标只前进 |
| 加载更早记录 | 仅对应 `*_after`，`limit=50` | 追加，不修改事件游标 |
| 重新同步 | 无 `min_cursor`，`limit=50` | 全量替换并重开流 |

`cursor` 必须解析为 `sl1:<space>:<epoch>:<seq>`；空间不符、格式错误或
`schema_version !== 1` 的快照整份丢弃，并按 `resync` 处理。

### 3.2 事件流

`GET /api/super-link/spaces/{space_id}/events?after=<cursor>`，只接受 `sl.fact` 与三个
控制事件：

| 帧 | 客户端行为 |
|---|---|
| `sl.fact` | 校验 `schema_version=1`、`space_id`、`stream_epoch`、`seq`；推进游标；聚合 `invalidate` |
| `sl.auth_required` | 停止重连，状态 `auth_required`，提示重新登录 |
| `sl.resync_required` | 关闭当前流，取全量快照，从新游标重开 |
| `sl.unavailable` | 保留状态，按退避重连；达到上限后 `unavailable` + 手动重试 |
| 注释帧 / 心跳 | 忽略，不推进游标 |
| 未知事件名或坏 JSON | 忽略该帧；连接继续 |

游标推进规则：

1. 只接受同空间、同 epoch、`seq` 严格大于本地已处理 `seq` 的事实。
2. `seq` 相同或更小视为重复/迟到，忽略整帧（不重复触发刷新）。
3. epoch 变化不在客户端猜测合并；直接进入 `resync`。
4. 游标在“已安全登记失效”后才写入本地，重连始终用该游标；不使用 `Last-Event-ID`。

### 3.3 `invalidate` → 视图映射

服务端 `VIEWS = {space, participants, runs, deliveries, interventions, actions}`。

| 视图 | 本地更新 |
|---|---|
| `space` | 空间目标、状态、版本、预算、`can_control`、`delivery_cutoff` |
| `participants` | 参与方与 `available` |
| `runs` | 运行第一页 + `active_run_ids` |
| `deliveries` | 交付第一页 |
| `interventions` | 待审批第一页 |
| `actions` | 恢复操作第一页 |

同一轮多个事件按并集合并，**150ms 防抖**后只发一次快照请求。事件没有 `invalidate` 时按
`space + runs + deliveries` 处理（保守刷新），不静默忽略。

## 4. 状态模型

```ts
type SyncStatus =
  | 'idle' | 'loading' | 'live' | 'reconnecting' | 'resyncing'
  | 'unavailable' | 'auth_required' | 'not_found' | 'stopped'

interface SyncList<T> {
  items: T[]
  total: number
  next_after: string | null
  loadedMore: boolean   // 已加载第一页之后的历史
}

interface SpaceSyncState {
  status: SyncStatus
  stale: boolean             // 非 live 且已有数据
  error: string
  cursor: string | null
  epoch: string | null
  seq: number
  asOf: string | null
  space: Space | null
  participants: Participant[]
  runs: SyncList<LinkRun>
  deliveries: SyncList<Delivery>
  pendingInterventions: SyncList<RunControlRecord>
  actions: SyncList<RecoveryRecord>
  activeRunIds: string[]
  history: boolean           // 用户正在阅读较早记录
  hasUpdates: boolean        // 历史模式下累计的新更新
  updatedAt: number | null   // 本地收到确认状态的时间
}
```

- `total` 始终使用服务端精确总数，不随已加载条数缩小。
- 列表身份键：运行 `run_id`、交付 `message_id`、待审批 `control_id`、操作 `id`。
- 待审批在界面上不做历史分页：每次刷新**整页替换**第一页，避免已审批记录残留；
  `pending_total > 已加载数` 时显示“另有 N 条”，由用户处理当前项或刷新。快照的
  `pending_after` 保留给 T06，不在本轮 UI 暴露。
- 运行、交付、操作做历史合并：实时刷新替换第一页并保留已加载的更早记录。

## 5. 关键算法

### 5.1 首次接流

1. `status=loading`；请求快照（无 `min_cursor`）。
2. 校验并整体替换状态；`status=live`，`stale=false`。
3. 用快照 `cursor` 建流；`onOpen` 后清空重试计数。
4. 建流失败按 §6 处理；已有数据时 `stale=true`，不清空列表。

### 5.2 事实刷新（非历史模式）

1. 事实帧通过 §3.2 校验后写入 `cursor/epoch/seq`，聚合 `invalidate`。
2. 防抖到期后请求快照，携带 `min_cursor=本地 cursor`。
3. 丢弃条件（任一满足即整份丢弃）：
   - 请求发出后空间已切换或同步已停止；
   - 已有更新的全量快照请求发出（请求序号不是最新）；
   - 响应游标与本地同 epoch 且 `seq < 本地 seq`。
4. 接受后按命中视图合并；快照游标若更新则推进本地游标（不倒退）。
5. 丢弃后若 `invalidate` 仍有未消费项，重新调度一次，避免“丢了响应也丢了更新”。

### 5.3 第一页合并与历史合并

```text
mergeFirstPage(existing, page, key):
  merged = page.items + existing.items 中不在 page.items 的项（保持原顺序）
  total = page.total
  next_after = existing.loadedMore ? existing.next_after : page.next_after
```

- 第一页对象以新响应为准，已加载的更早记录保留，不重复、不重排。
- `loadMore(kind)`：用 `next_after` 请求对应 `*_after`；追加去重；`loadedMore=true`；
  只更新该列表的 `next_after`/`total`，**不修改事件游标**。
- 每个列表维护独立请求序号；旧的分页响应晚到不得覆盖新 `next_after`。
- `loadMore` 成功进入 `history=true`；之后实时合并只累计 `hasUpdates`。
- `returnToLatest()`：`history=false`、`hasUpdates=false`，请求全量快照并整体替换，
  恢复第一页；滚动位置由浏览器保持，不强制跳顶。

### 5.4 重新同步

触发：`sl.resync_required`、快照 410、快照/建流 400 `invalid_cursor`、epoch 变化。

1. `status=resyncing`；关闭现有流；作废进行中的快照/分页请求。
2. 请求无 `min_cursor` 的全量快照；成功后整体替换、清空 `history/hasUpdates`、重开流。
3. 失败进入 §6 的重连/不可用路径；保留旧状态但标记 `stale`，不把重新同步失败显示为
   业务状态变化。
4. 未提交输入（新建目标、补充指令、审批表单）属于组件本地状态，不因重同步重置。

### 5.5 连接生命周期与退避

| 事件 | 行为 |
|---|---|
| 建流成功 | `live`、`stale=false`、重试计数归零 |
| 普通 EOF / 寿命到期（5 分钟） | `reconnecting`，从最后游标重连；首次延迟 0—500ms |
| 网络错误 / 5xx / `sl.unavailable` | `reconnecting`，指数退避 + 抖动，500ms 起、15s 封顶 |
| 429 | 使用 `Retry-After`（缺省 5s）退避；不视为业务失败 |
| 401/403 | `auth_required`，不再自动重连 |
| 404 | `not_found`；`detail=super_link_disabled` 时显示未启用文案 |
| 连续 8 次失败 | `unavailable`，保留数据，提供“重试”按钮 |
| `stop()` / 卸载 / 切空间 | 终止流、取消定时器、请求序号失效；迟到回调全部忽略 |

页面重新可见不自动全量重拉：连接仍在则依赖心跳与事件；连接已断则按上述退避重连。若
浏览器在后台挂起较久导致游标过期，服务端会发 `sl.resync_required`，按 §5.4 处理。

## 6. 错误映射

| HTTP / 来源 | 状态 | 用户文案 | 是否清空数据 |
|---|---|---|---|
| 401/403 | `auth_required` | 登录状态已失效，请重新登录 | 否 |
| 404 `not_found` | `not_found` | 未找到这个协作空间，或你没有访问权限 | 否 |
| 404 `super_link_disabled` | `not_found` + 禁用文案 | Super-link 尚未启用，原有工作台可正常使用 | 是（首次加载） |
| 400 `invalid_cursor` | 先 `resync` 一次；再失败 → `unavailable` | 正在重新同步 | 否 |
| 410 `resync_required` | `resync` | 正在重新同步 | 否 |
| 429 | `reconnecting` | 连接较多，稍后重试 | 否 |
| 503 `event_chain_unavailable` / 网络 0 | `reconnecting` | 状态同步暂时中断，显示最近记录 | 否 |
| 其他 4xx | `unavailable` | 状态同步暂不可用 | 否 |

`stale=true` 时 `SuperLinkStudio` 显示“等待同步”，不显示为运行失败或已停止。

## 7. 文件与实现点

| 文件 | 变更 |
|---|---|
| `web/src/utils/sseFrames.ts` | **新增**：`extractFrames`、`parseFrame`（返回 `data/event/id/retry`）、`backoffDelay`、`sleep` |
| `web/src/utils/sseFrames.test.ts` | **新增**：分帧、多行 data、注释/心跳、event/id 解析、跨块半帧 |
| `web/src/sse.ts` | **修改**：删除本地帧解析/退避副本，改为导入；`openRunStream` 逻辑与导出不变 |
| `web/src/api/superLink.ts` | **修改**：`Space` 补 `delivery_cutoff` 与参与方 `available`；新增 `SnapshotPage<T>`、`SpaceSnapshot`、`SnapshotQuery`、`superLink.snapshot()` |
| `web/src/superLink/stream.ts` | **新增**：`openSpaceStream()`，单次 fetch + 帧分发 + abort；HTTP/EOF/错误通过回调上报，不内置重试 |
| `web/src/superLink/stream.test.ts` | **新增**：事实/控制/心跳分发、HTTP 状态、abort、EOF 只回调一次 |
| `web/src/superLink/sync.ts` | **新增**：`createSpaceSync()` 纯 TS 状态机与 `parseSpaceCursor()`；依赖注入快照加载、开流、计时、随机数 |
| `web/src/superLink/sync.test.ts` | **新增**：§8 场景 |
| `web/src/superLink/useSpaceSync.ts` | **新增**：Vue composable，绑定 `superLink.snapshot`、`openSpaceStream`、auth token、`shallowRef` 状态；`watch(spaceId)` + `onUnmounted(stop)` |
| `web/src/views/SuperLinkView.vue` | **修改**：空间详情改用 `useSpaceSync`；移除 5 秒轮询定时器；`more()` 改用同步模块；新增同步状态条、历史提示、“查看最新更新”、重试按钮；列表页保持原逻辑 |
| `web/src/components/SuperLinkControls.vue` | **修改**：新增可选 `pending`/`activeRunIds` props；有 props 时以父级状态为准；`/interventions` 降为 30 秒低频兜底（仅 `recent`）；审批/控制提交后 emit `changed`，由父级 `refreshNow()` |
| `docs/plan/super-link-communication-foundation.md` | 实施完成后更新 §20.2 T04 状态并新增 §20.10 完成记录 |

不修改：`server/**`、迁移、`openRunStream` 调用方、`stores/runs.ts`、ChatView、普通模式
配置与默认参数。

## 8. 测试计划

### 8.1 纯单元测试（Node + `node:test`）

`web/src/utils/sseFrames.test.ts`

- 多帧拆分与半帧保留；`data:` 多行合并；`: heartbeat` 无 data 返回 null；
  `event`/`id` 正确返回；`retry` 解析。

`web/src/superLink/stream.test.ts`（注入 fake fetch / `ReadableStream`）

- `sl.fact` 顺序回调；`sl.resync_required`、`sl.auth_required` 回调；
- 非 200 上报状态与 `Retry-After`；EOF/网络错误只 `onClose` 一次；
- `stop()` 后不再回调、body 被取消。

`web/src/superLink/sync.test.ts`（注入 fake 快照、fake 流、假计时器）

1. 快照 → 建流使用快照游标；事实推进游标；`invalidate` 去重、150ms 合并为一次快照。
2. 并发刷新旧响应晚到被丢弃，游标不倒退；丢弃后未消费失效重新调度。
3. 历史模式：事实只置 `hasUpdates`，列表不变；`returnToLatest` 恢复第一页并清标记。
4. 分页合并：加载更早运行/交付/操作后，实时刷新保留历史、不重复、不覆盖 `next_after`；
   待审批刷新整页替换。
5. 重新同步：`sl.resync_required` / 410 / epoch 变化 → 关闭旧流、全量快照、从新游标重开；
   旧请求结果不写入。
6. 断线恢复：EOF 后从最后游标重连；离线期间事实在重连补读后按失效刷新，状态准确；
   429 遵守退避；连续失败进入 `unavailable`，手动重试恢复。
7. 空间切换/stop：旧流 abort、定时器取消、迟到事实与快照忽略；新空间状态不继承。
8. 控制帧：`auth_required` 停止重连；`unavailable` 保留数据并重连。
9. 控制命令不直接改写 `space.control_state`；只有快照/事件确认后才显示停止/暂停。

### 8.2 前端回归

在 `web/` 下运行：

```bash
npm test          # 现有 utils 测试 + 新增测试
npm run typecheck # vue-tsc，覆盖 .vue 与新模块
npm run build     # 生产构建
```

不启动本机服务、不连接数据库。真实浏览器、代理链路、多标签页配额与心跳行为留给 T06。

### 8.3 后端回归

T04 不改后端；为确认消费契约未漂移，复核 T03 的 stream 测试仍通过（不重复全量回归）：

```bash
uv run pytest tests/test_super_link_stream.py -q -p no:cacheprovider
```

## 9. 验收对照

| 计划项 | T04 证据 |
|---|---|
| SSE-A02 快照/实时重叠、游标过期 | 8.1-1/2/5：去重、旧响应丢弃、`resync` 全量重建 |
| SSE-A03 断线期间完成交接 | 8.1-6：EOF 后从旧游标重连，补读事件触发刷新，快照恢复准确；无额外执行 |
| SSE-A04 停止响应丢失/重复提交/双标签页 | 8.1-9：前端不伪造状态；幂等键、`expected_version` 仍由现有控制面板负责 |
| SSE-A08 切换空间/旧页/未提交输入 | 8.1-3/7：释放旧连接、历史模式不顺移、组件本地输入不被同步重置 |

## 10. 明确不做

1. 不做运行文本/思考/工具逐 token 展示（T05）。
2. 不改变 Team/Single 执行、审批门、停止语义、幂等键或控制版本规则。
3. 不新增服务端字段、快照参数或迁移；不把 `/interventions` 的 `recent` 搬进快照。
4. 不做离线队列、Service Worker 或页面关闭后的后台同步；页面关闭不决定协作完成。
5. 不做多实例 SSE 路由验证与代理调优（T06）。
6. 不删除旧列表/审批接口，保留 T06 故障对照与回退能力。

## 11. 已知边界

- 每用户最多 8 条空间连接；同用户开更多标签页会收到 429，客户端退避而非报业务失败。
- 服务端单连接最长 5 分钟，正常使用中每 5 分钟发生一次无感重连。
- 首次与刷新快照 `limit=50`；超过 50 条待审批只展示第一页并提示剩余数量，不在本轮做
  待审批历史分页。
- 事件 `data` 仅用于失效提示；正文与附件仍按需读取，避免把大内容塞进事件流。
- `as_of` 是服务端快照时间；界面“状态更新于”使用本地收到确认的时间，两者不混写为业务
  发生时间。
