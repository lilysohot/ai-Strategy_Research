# SSE-T05 实施任务

| 项目 | 内容 |
|---|---|
| 规格 | [spec.md](spec.md) |
| 状态 | 复核通过，已收口（2026-11-21） |
| 边界 | 不改空间事实游标/快照协议/普通运行流；不启动服务、不迁移业务库 |

## 服务端

- [x] `server/super_link/output.py`
  - [x] `preview_items()`：映射 content/thinking/tool/notice/terminal，拆帧、脱敏、限长
  - [x] `OutputSubscription`：有界队列、溢出合并 reset、关闭唤醒
  - [x] `RunOutputHub`：按会话订阅/退订/可见性/发布，同步非阻塞
- [x] `server/config.py`：`super_link_sse_output_queue_frames` 默认 256
- [x] `server/super_link/management.py`：`participant_session_ids()`
- [x] `server/super_link/stream.py`
  - [x] `PREVIEW_EVENT`/`OUTPUT_RESET_EVENT`/`output_reset_frame()`
  - [x] `FrameBuffer.put_preview()`：非阻塞、预览最多占一半容量
  - [x] `event_stream(session_ids=...)`：epoch、订阅、预览生产者、清理
  - [x] `_produce_previews()`：按 Run 序号、reset 优先、缓冲不足丢弃
- [x] `server/routes/super_link.py`：建连读取参与者会话并传入
- [x] `server/orchestrator.py`：`_publish` 旁路调用输出 Hub，保留原订阅者行为

## 前端

- [x] `web/src/superLink/live.ts`
  - [x] `LiveState`/`LiveBlock` 类型与空状态、克隆
  - [x] `applyPreview`：epoch、序号、块累加、成员归属、终态、截断
  - [x] `applyReset`、`clearLive`
  - [x] `visibleBlocks`：按归档记录过滤重复块
- [x] `web/src/superLink/stream.ts`：`onPreview`/`onOutputReset` 分发
- [x] `web/src/superLink/sync.ts`
  - [x] `SpaceSyncState.live` 与 `emptySpaceSyncState`/`copyState`
  - [x] 回调接入、80ms 合并、事实前刷新
  - [x] 建流关闭/重同步/停止清空
  - [x] 预览不推进游标、不修改列表与 `hasUpdates`
- [x] `web/src/views/RunDetailView.vue`
  - [x] 可选 `live`/`liveActive`，默认行为不变
  - [x] 终态重载归档、轮询依据 `liveActive`
  - [x] 实时块按成员展示、归档过滤、缺片提示、空状态
  - [x] 运行目录/错误仅在全局流属于当前 Run 时显示
- [x] `web/src/views/SuperLinkView.vue`：抽屉计算并传入预览与活动状态

## 测试

- [x] `tests/test_super_link_output.py`
- [x] `tests/test_super_link_stream.py` 预览帧、reset、隔离、释放
- [x] 编排接线：原订阅者帧不变，仅订阅会话收到预览
- [x] `web/src/superLink/live.test.ts`
- [x] `web/src/superLink/stream.test.ts` 新事件分发
- [x] `web/src/superLink/sync.test.ts` 预览集成与边界

## 验证与收口

- [x] `uv run pytest tests/test_super_link_output.py tests/test_super_link_stream.py -q`
- [x] 定向 Ruff / Pyright
- [x] `cd web && npm test && npm run typecheck`
- [x] 更新计划 §20.2 T05 状态与 §20.11 完成记录
- [x] 明确移交 T06 的真实浏览器、代理、多标签页与多实例验收项

结果（2026-11-20）：后端定向 pytest 46 passed；Ruff、Pyright 0 错误；
前端 `npm test` 166 passed、`npm run typecheck` 通过。未启动服务、未访问业务库、
未执行真实模型/浏览器链路；T05 待复核通过后收口，正式启用仍以 T06 为准。

复核修复（2026-11-21）：P1 普通模式轮询（显式 `liveMode` + `shouldPollRunDetail`）、
P2 首帧保留 reset 缺片标记、P2 缓冲排空唤醒待发 reset、P2 Single 成员身份归一、
P2 每条预览执行 Run 缓存淘汰均已修复。复跑：后端定向 47 passed；Ruff/Pyright 0 错误；
前端 170 passed、typecheck 通过。用户复验确认五项闭环及 Vue 属性解析正常，T05 收口；
未启动服务或访问业务库。正式启用仍以 T06 真实浏览器、代理与多实例验收为准。
