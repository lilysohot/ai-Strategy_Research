# SSE-T05 真实运行输出适配规格

| 项目 | 内容 |
|---|---|
| 版本 / 日期 | v1.0 · 2026-11-20 |
| 状态 | 复核通过，已收口（2026-11-21） |
| 上游依据 | [技术框架 §11.6](../../design/super-link-technical-design.md#116-运行输出与持久事实的区别)；[建设计划 §20.2/§20.4](../../plan/super-link-communication-foundation.md#202-执行任务及依赖) |
| 前置 | SSE-T04 已复核通过（2026-11-20） |
| 范围 | Team/Single 可见运行输出的实时展示、成员归属、缺片修复、最终文本与归档衔接 |

## 1. 目标与边界

在不改变空间事实游标、快照协议和普通模式运行流的前提下，把 Team/Single 运行的
可见文本、思考与工具进度以独立预览帧接入空间 SSE，并让页面在运行结束后以归档
轨迹替换预览内容。

必须达到：

1. Team 主 Agent 与成员、Single 的实际可见输出能在 Super-link 运行详情中实时显示。
2. 文本、思考、工具进度能按 Run、成员和块身份归属，不跨块拼接，不混淆并发成员。
3. 实时片段缺失或连接更换时，客户端清空该 Run 的预览并从已有归档重新对齐；不得
   静默拼接残缺文本。
4. 运行终态后，页面以 `/api/runs/{id}/trace` 的保存内容为准，最终文本与归档一致。
5. 模型未提供思考流时不生成思考块，页面只展示实际内容。
6. 预览只是只读旁路：不调用工具、不写业务状态、不推进空间游标、不触发交接。
7. 首版继续限定单 API 运行所有者；非所有者实例只提供事实与归档，不伪造实时输出。

不做：

- 不新增跨实例运行输出路由、Redis Pub/Sub 文本广播或逐 token 持久化。
- 不改变 `openRunStream`、普通 ChatView 的运行流和 `stores/runs` 的语义。
- 不把预览帧用于运行状态判断、审批、交付或队列决策。
- 不重放历史上未归档的输出；断线后只保证归档完整块与后续新片段。

## 2. 现状与复用点

| 位置 | 当前事实 | 本规格处理 |
|---|---|---|
| [bridge.py](../../../server/bridge.py) `BridgeObserver` | `assistant_delta` 携带 `text`/`thinking_text`/`turn`；`tool_started`/`tool_finished` 携带 `tool_call_id`、`turn`、`detail`（已脱敏、400 字）；成员通过 `source_meta` 带 `agent_id`/`agent_kind` | 直接消费现存事件字段，不新增 Worker 输出通道 |
| [orchestrator.py](../../../server/orchestrator.py) `_publish` | 已经把上述帧扇出给普通运行 SSE 订阅者；终态帧在权威记录保存后发布 | 在同一位置旁路复制给 Super-link 输出 Hub，不改原订阅者行为 |
| [relay.py](../../../server/relay.py) / `/api/runs/{id}/trace` | 归档轨迹提供 `agent_id`/`agent_kind`/`turn`/`content`/`thinking`/`tool_calls`/`result` 与完整性 | 作为预览结束后的权威替换来源，不新增归档接口 |
| [super_link/stream.py](../../../server/super_link/stream.py) | 空间 SSE 已有事实帧、控制帧、心跳、有界 `FrameBuffer` 与单生产者 | 增加独立预览生产者；预览只能占用缓冲的一半，不得挤占事实帧 |
| [RunDetailView.vue](../../../web/src/views/RunDetailView.vue) | 普通模式按全局 `runStream` 状态轮询归档；SuperLink 抽屉中该状态不指向空间 Run | 增加可选预览属性、显式 `liveMode` 与 `liveActive`；普通模式默认 false，行为不变 |

`RunHandle.session_id` 是参与会话 UUID；空间 SSE 建连时已能读取该空间的参与者会话。
首版一个参与会话只归属一个空间。

## 3. 拓扑与降级

1. 运行由其 API 所有者进程启动；预览 Hub 是进程内对象，只接收本进程 `_publish` 的帧。
2. 空间 SSE 由同一实例提供时，连接按参与者会话集合订阅预览。
3. 页面连接由其他实例提供时，事实帧和归档读取仍然可用；预览不会到达，页面保持
   归档轮询并提示“实时输出仅在执行实例可用”。快照能力字段继续为
   `live_output: "local_owner_only"`。
4. 不使用 Redis 广播预览，避免在未验证的多实例路由下产生重复或乱序文本。

## 4. 预览帧契约

### 4.1 `sl.run.preview`

```
event: sl.run.preview
data: {"schema_version":1, ...}
```

不带 `id:`，不参与空间游标、`min_cursor` 或事实补读。公开字段：

| 字段 | 类型 | 说明 |
|---|---|---|
| `schema_version` | int | 固定 `1` |
| `space_id` | uuid string | 连接所属空间，客户端必须校验 |
| `run_id` | uuid string | 来源 Run |
| `session_id` | uuid string | 参与会话 |
| `output_epoch` | uuid string | 每条空间 SSE 连接一个，重连即更换 |
| `output_seq` | int | 同一连接内按 `run_id` 从 1 严格递增 |
| `member` | object | `{agent_id, agent_kind}`；Single 可为空字符串 |
| `turn` | int \| null | 来源轮次 |
| `block_key` | string | 服务端生成的稳定块身份，客户端只按此累加 |
| `kind` | enum | `content` / `thinking` / `tool` / `notice` / `terminal` |
| `text` | string | `content`/`thinking` 增量；单帧最长 4096 字符，超长拆帧 |
| `tool` | object? | `tool` 帧：`call_id`、`name`、`state`（`started`/`finished`）、`ok`、`skipped`、`detail`、`ms` |
| `status` | string? | `terminal` 帧：`completed`/`failed`/`stopped` |
| `stopped_by` | string? | `terminal` 帧的停止来源 |
| `error` | string? | `terminal` 帧的脱敏错误摘要 |

约束：

- 后缀 `_key = "<agent_kind>|<agent_id>|<turn>|<kind>"`；工具块为
  `"tool|<agent_kind>|<agent_id>|<tool_call_id>"`，缺失 id 时回退到名称与轮次。
- 一帧不得同时承载 content 与 thinking；两者都非空时由服务端拆成两帧，序号递增。
- 不复用 `output` 全量工具结果；只传已脱敏的 `detail`。
- `terminal` 帧不携带 `final_answer`；最终文本只从归档读取。
- 所有字符串再次经过脱敏与长度限制，未知类型不生成预览。

### 4.2 `sl.output_reset`

```
event: sl.output_reset
data: {"schema_version":1, "space_id":"...", "run_ids":["..."], "reason":"preview_overflow"}
```

同样不带 `id:`。表示指定 Run 的预览已不连续，客户端必须清空这些 Run 的预览块并
以归档重新对齐；`output_seq` 不因控制帧推进。服务端在预览队列溢出或预览帧无法
写入有界缓冲时产生该帧；reset 优先于新的预览，若暂时无容量则等待响应循环排空缓冲，
容量恢复后立即补发，不依赖后续新输出，也不静默丢弃 reset。

## 5. 服务端实现

### 5.1 `server/super_link/output.py`

- `preview_items(run_id, payload)`：纯函数，把 `assistant_delta`、`tool_started`、
  `tool_finished`、带 `compaction` 的 `warning` 与终态帧映射为预览条目；不读库、
  不调用工具、不修改输入。
- `OutputSubscription`：每连接有界队列。溢出时清空待发预览，合并为一个
  `OutputReset` 条目（包含所有受影响 Run），保证下次唤醒先发 reset。
- `RunOutputHub`：按 `session_id` 维护订阅集合，提供 `subscribe`/`unsubscribe`/
  `observed`/`publish`；`publish` 同步非阻塞，未订阅会话直接跳过。
- 模块级 `HUB` 供路由与编排层共用；不启动后台任务、不访问 Redis。

### 5.2 `stream.py`

- `FrameBuffer.put_preview()`：非阻塞入队；预览最多使用一半帧数与字节额度，给
  事实帧留出容量；失败不关闭连接。
- `event_stream(..., session_ids=())`：
  - 建连时创建 `output_epoch = uuid4()`；
  - 有参与者会话时订阅 `OUTPUT_HUB`，启动 `_produce_previews`；无会话则跳过；
  - `_produce_previews` 为每个 Run 维护 `output_seq`，将预览条目包装为信封；
  - 若某 Run 处于待 reset 状态，先尝试发 reset，再发当前预览；reset 发不出去时
    用 `FrameBuffer.wait_preview_space()` 等待 `get()` 释放容量后重试，缓冲关闭才退出；
  - 连接结束时取消生产者、退订并释放配额。
- 新增 `PREVIEW_EVENT` / `OUTPUT_RESET_EVENT` 常量与 `output_reset_frame()`。

### 5.3 路由与归属

- `management.participant_session_ids(session, space_id)` 读取该空间的参与者会话。
- `GET /spaces/{id}/events` 在既有鉴权读取中一并取得会话 ID，传给 `event_stream`。
- `orchestrator._publish` 在保留原订阅者扇出后，按 `handle.session_id` 调用
  `OUTPUT_HUB.publish`；只对可解析的 UUID 会话生效，Hub 无订阅时零额外构造。

### 5.4 默认参数

- `super_link_sse_output_queue_frames = 256`（每连接预览队列上限）。
- 单帧文本上限 `4096`；预览最多占用连接缓冲的一半。

## 6. 前端实现

### 6.1 帧解析

[stream.ts](../../../web/src/superLink/stream.ts) 增加 `onPreview` 与
`onOutputReset` 回调；未知事件仍被忽略。预览与 reset 不进入 `onFact`/`onControl`。

### 6.2 状态模型

新增 [live.ts](../../../web/src/superLink/live.ts)，提供纯函数与类型：

- `LiveState`：`epoch`、每个 Run 的 `blocks`、`lastSeq`、`active`、`needsArchive`。
- `applyPreview`：
  - 校验 `space_id`、UUID、`output_seq` 为正整数；
  - epoch 改变时清空全部预览并以新 epoch 重新开始；
  - 同一 Run 的序号不连续时清空该 Run 的块并标记 `needsArchive`，以当前帧为新基线；
  - 按 `block_key` 累加 content/thinking，更新 tool 状态与 notice；
  - `terminal` 只标记非活动，不写入最终文本；
  - 单块文本超过 500,000 字符后停止追加并标记截断。
- `applyReset`：只清空指定 Run，标记 `needsArchive`。
- `visibleBlocks`：按成员与轮次过滤已出现在归档中的块，避免与归档重复。
- `cloneLive`：供 `copyState` 使用，保证响应式引用更新。

[sync.ts](../../../web/src/superLink/sync.ts) 接入：

- `SpaceSyncState` 增加 `live`；`emptySpaceSyncState`/`copyState` 同步处理；
- `openStreamConnection` 注册两个新回调，并受既有代次/连接令牌保护；
- 预览合并按 80ms 合并 emit，事实 `emit()` 会先清掉待发预览定时器；
- 建流关闭时清空预览（重连后的新 epoch 会重新建立），重同步/停止同样清空；
- 预览不得修改 `cursor`、`seq`、列表或 `hasUpdates`。

### 6.3 页面

- `SuperLinkView.vue` 抽屉读取 `sync.live[selectedRun]`，用 `activeRunIds` 与预览
  `active` 计算 `liveActive`，传入 `RunDetailView`。
- `RunDetailView.vue`：
  - 新可选 props `live`、`liveMode`、`liveActive`；`liveMode` 默认 false，普通模式
    不依赖空间标志轮询（Vue 会把未传 Boolean 解析为 false，不能用 undefined 判断）；
  - 空间模式下 `liveActive` 决定轮询；变为 false 时立即重新加载归档；
  - 在归档时间线前显示“实时输出（未保存）”，按成员分组；内容经 Markdown 清洗，
    思考按纯文本，工具显示名称与状态；
  - 归档已包含的成员/轮次块不重复显示；Single 的空成员与归档 `single/<id>` 归一；
  - 空成员归一、每条预览触发 Run 缓存淘汰、reset 先于首帧时保留缺片标记；
  - `needsArchive` 时显示“部分片段缺失，正在以归档内容校正”；
  - 无归档且无预览时才显示空状态；
  - 只有全局运行流确实指向当前 `runId` 时才展示其运行目录/错误信息。

## 7. 归档衔接与最终文本

1. 打开详情先读取 `/trace`；运行中只显示已保存轮次与实时未保存块。
2. 归档轮次出现后，同成员同轮次的预览块隐藏；工具结果以归档记录为准。
3. 收到 `terminal` 预览或事实显示 Run 非活动时，`liveActive` 变为 false，详情立即
   重新读取归档；最终文本、思考与工具结果全部来自保存记录。
4. 连接断开或 epoch 更换会清空预览；页面保留归档内容并显示同步状态，不把断线
   显示为运行失败。
5. 预览缺失不影响 Run 事实、交付、旁路或审批状态。

## 8. 故障与验收对照

| 场景 | 预期 | 对应 |
|---|---|---|
| 多成员高速输出 | 文本按成员/轮次/块累加，不串块；慢连接只影响预览 | A05 |
| 预览队列/连接缓冲溢出 | 受影响 Run 收到 reset；客户端清空并标记需归档；事实不丢 | A05 |
| SSE 断开/重连 | 预览清空；新连接新 epoch；归档补齐完整块 | A05/A06 |
| Run A 结束、Run B 启动 | 两个 Run 的块不混合；A 非活动、B 继续；空间流不断 | A06 |
| 无思考流 | 只显示 content/tool，不生成思考块 | A06 |
| 文本片段缺失 | `sl.output_reset` 或序号缺口触发整体重置，不拼接残文 | A06 |
| 最终文本 | 终态后从 `/trace` 替换预览，内容一致 | A06 |
| 非所有者实例/API 重启 | 无预览，事实与归档可用；不重复执行工具 | A05 |
| 普通模式 | `openRunStream`、ChatView、`stores/runs` 无行为变化 | 回归 |

## 9. 测试策略

后端：

- `tests/test_super_link_output.py`：映射、成员归属、拆帧、脱敏/截断、无 thinking、
  终态不含 final_answer、Hub 按会话隔离、溢出 reset、输入不变。
- `tests/test_super_link_stream.py`：预览帧无 `id`、序号与 epoch、reset 顺序、
  非参与者会话不可见、连接释放、事实与预览共存、缓冲预留不关闭连接。
- 轻量编排接线测试：`_publish` 仍向原订阅者发送原帧，同时只向已订阅会话产生预览。

前端：

- `live.test.ts`：累加、成员隔离、epoch 切换、序号缺口、reset、无 thinking、
  归档过滤、截断、终态。
- `stream.test.ts`：分发 `sl.run.preview`/`sl.output_reset`，未知事件忽略。
- `sync.test.ts`：预览不推进游标、切空间/重同步清空、关闭连接清空、80ms 合并、
  迟到旧连接帧被代次丢弃。

验证命令：

```
uv run pytest tests/test_super_link_output.py tests/test_super_link_stream.py -q
uv run ruff check server/super_link/output.py server/super_link/stream.py \
  server/routes/super_link.py server/super_link/management.py server/orchestrator.py \
  tests/test_super_link_output.py tests/test_super_link_stream.py
uv run pyright server/super_link/output.py server/super_link/stream.py
cd web && npm test && npm run typecheck
```

不启动本机服务、不迁移业务库、不执行真实模型或浏览器链路；这些留待 T06。

## 10. 退出条件与移交

T05 完成需同时满足：

- Team/Single 可见输出可实时展示，成员归属正确；
- 缺片可 reset，最终文本与归档一致，无思考流正常；
- 预览只读，不重复执行工具，不推进空间游标；
- 非所有者实例明确降级为归档；
- 后端定向测试、前端单测与类型检查通过。

移交 T06：真实浏览器、反向代理、多标签页、真实 Worker/模型流式端点、Redis 故障、
API 重启与多实例路由；页面组件级交互和代理缓冲仍需实测，不以本规格的单元测试
替代端到端验收。
