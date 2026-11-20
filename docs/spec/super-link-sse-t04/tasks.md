# SSE-T04 实施任务

| 项目 | 内容 |
|---|---|
| 状态 | **已实施并完成竞态修复（2026-11-20）** |
| 规格 | [spec.md](spec.md) |
| 边界 | 只改 `web/` 与文档；不改服务器、迁移、`openRunStream` 调用方与普通模式 |
| 完成定义 | 快照接流无空隙；事实去重与合并可靠；旧响应丢弃；重连/重新同步可恢复；离页释放连接；历史与输入不被抢 |

## T4.1 帧解析复用

- [x] 新建 `web/src/utils/sseFrames.ts`：迁移 `extractFrames`、`parseFrame`、
      `backoffDelay`、`sleep`；`parseFrame` 增加 `event`/`id` 返回，`data`/`retry` 语义不变。
- [x] `web/src/sse.ts` 改为导入上述纯函数，删除本地副本；`openRunStream` 的游标、终态、
      重试、`stop()` 行为与导出保持不变。
- [x] 新建 `web/src/utils/sseFrames.test.ts`，覆盖 spec §8.1。
- [x] 运行 `npm test`、`npm run typecheck`，确认普通模式无回归。

## T4.2 快照 API 与类型

- [x] `web/src/api/superLink.ts`：新增 `SnapshotQuery`、`SnapshotPage<T>`、`SpaceSnapshot`
      与 `superLink.snapshot(id, query)`；`Space` 补 `delivery_cutoff`，参与方补
      `available`；复用 `LinkRun`、`Delivery`、`RunControlRecord`、`RecoveryRecord`。
- [x] 查询参数映射：`min_cursor`、`limit`、`runs_after`、`deliveries_after`、
      `pending_after`、`actions_after`；`undefined` 由现有 client 丢弃。
- [x] 不删除旧接口；列表页与 `recent` 兜底继续可用。

## T4.3 空间事件流客户端

- [x] 新建 `web/src/superLink/stream.ts`：`openSpaceStream({ url, token, after,
      signal, fetchImpl, callbacks })`；单次连接，不内置重试。
- [x] 请求头带 bearer、`Accept: text/event-stream`、`Cache-Control: no-cache`；
      非 2xx 上报 `status` 与 `Retry-After`；显式忽略 `Last-Event-ID`。
- [x] 复用 `sseFrames` 分帧；只分发 `sl.fact` 与三个控制事件；注释/心跳/坏帧忽略。
- [x] `stop()` abort 并取消 body；`onClose` 在非主动停止时只回调一次。
- [x] 新建 `web/src/superLink/stream.test.ts`（注入 fake fetch / `ReadableStream`）。

## T4.4 同步状态机

- [x] 新建 `web/src/superLink/sync.ts`：`parseSpaceCursor()`、
      `createSpaceSync({ spaceId, loadSnapshot, openStream, onState, timing })`。
- [x] 状态与列表结构按 spec §4；首次快照整体替换并用其 `cursor` 建流。
- [x] 事实校验（schema/space/epoch/seq）、重复忽略、`invalidate` 聚合、150ms 防抖。
- [x] 快照请求序号、空间代次与游标单调校验；旧响应整份丢弃并重新调度未消费失效。
- [x] `mergeFirstPage` 保留历史；`loadMore` 支持 runs/deliveries/actions，追加去重且
      不修改事件游标；待审批整页替换。
- [x] `history` 模式只累计 `hasUpdates`；`returnToLatest` 全量重建并清标记。
- [x] `sl.resync_required` / 410 / 400 / epoch 变化 → 关流、全量快照、从新游标重开。
- [x] 错误映射与退避按 spec §5.5/§6；8 次失败进入 `unavailable`，`retry()` 可恢复。
- [x] `stop()` 取消流、防抖与重连定时器，递增代次，迟到回调全部忽略。
- [x] 新建 `web/src/superLink/sync.test.ts`，覆盖 spec §8.1 的 9 类场景（注入假计时器）。

## T4.5 页面接入

- [x] 新建 `web/src/superLink/useSpaceSync.ts`：绑定 `superLink.snapshot`、
      `openSpaceStream`、`auth.token`；`watch(spaceId, immediate)`；卸载/切换时 `stop()`。
- [x] `SuperLinkView.vue` 空间详情改用同步状态：`current`、`runs`、`deliveries`、
      待审批、活动运行、恢复操作均来自 `state`。
- [x] 移除空间详情的 5 秒轮询定时器；列表页 `/spaces` 保持原加载、分页和手动刷新。
- [x] `more('runs'|'deliveries')` 改走 `sync.loadMore`；空间列表分页保持旧接口。
- [x] 增加同步状态条：加载/已同步/重连/补齐/不可用/鉴权失效；`stale` 传给
      `SuperLinkStudio`；`unavailable` 提供“重试”。
- [x] 历史模式显示“正在查看较早记录”和“有新更新，查看最新”；不在历史模式自动插入新项。
- [x] 保留交付详情、运行详情、新建对话框的本地状态与既有 epoch 防串页检查；同步更新
      不重置未提交输入。
- [x] 页面卸载、路由离开、空间切换后旧流无回调；不把旧空间数据带入新空间。

## T4.6 控制面板同步

- [x] `SuperLinkControls.vue` 新增可选 `pending`、`activeRunIds` props；有 props 时不再
      用自有轮询结果覆盖待审批与活动运行。
- [x] `/interventions` 改为 30 秒低频兜底，仅用于“最近 100 条”与旧接口兼容；保留错误提示。
- [x] 审批、控制、恢复提交后 emit `changed`；父级调用 `sync.refreshNow()`，由快照确认
      新状态；前端不直接改写 `control_state`。
- [x] 保持 `expected_version`、幂等键、`sessionStorage` 待确认请求与“停止需真实收尾”的
      现有行为不变。
- [x] 确认 `steerText`、审批表单等本地输入在同步列表更新时不被清空。

## T4.7 回归与验证

- [x] `cd web && npm test`：新增测试与既有 utils 测试全部通过，记录通过数。
- [x] `npm run typecheck`：`.vue`、新模块与旧接口类型通过。
- [x] `npm run build`：生产构建通过。
- [x] 复核 T03 契约未被消费端误读：
      `uv run pytest tests/test_super_link_stream.py -q -p no:cacheprovider`。
- [x] 不启动本机服务、不连接/迁移业务库；浏览器与代理链路验证留给 T06。
- [x] 如发现需要改后端的缺口，先记录并暂停，不在本任务内扩大接口。

## T4.8 文档与移交

- [x] 更新计划 §20.2：SSE-T04 状态改为“实现完成，前端单测/类型/构建通过”，写明未做
      真实浏览器验收。
- [x] 新增 §20.10 T04 完成记录：变更文件、命令、通过数、限制、未验证项、基线对照。
- [x] 更新 §20.6 文档完备性结论中“T04—T07 尚未实施”的表述。
- [x] 移交 T06 的测试补强：在隔离 PG 的列表并发测试中，除推进事件头外同时提交业务状态
      （如审批完成），验证返回内容与返回游标属于同一快照边界；该任务不阻塞 T04。

## T4.9 复核竞态修复

- [x] [P1] 拆分事件消费游标与快照版本：局部 `applyRefresh` 只推进内部 `appliedSeq`，
      不再推进 `state.cursor/seq`；未合并视图的迟到事实仍按 `invalidate` 刷新。
- [x] [P1] scoped 刷新串行化：同一时间只允许一个请求在途，新失效排队；被全量替换
      取代的请求在替换序号未变时重新入队，避免不同视图交错时丢失刷新。
- [x] [P2] `returnToLatest` 带 `min_cursor` 并校验快照 `seq` 不倒退；旧快照返回时保留
      `history`、`hasUpdates` 与未合并失效，只提示稍后重试，不修改列表。
- [x] [P2] `shutdown()` 递增代次，作废所有在途快照的成功/失败回调与流回调；owner
      标记避免旧请求的 `finally` 清除新请求标志。
- [x] [P2] 实时刷新落地前重新检查 `history`；历史开始后返回的响应只重新排队并置
      `hasUpdates`，不追加或覆盖历史列表。
- [x] `sync.test.ts` 新增 5 项竞态回归（共 20 项）；`npm test` 140 passed、
      `npm run typecheck`、`npm run build` 通过；后端 stream 26 passed。

## T4.10 请求作废边界收尾

- [x] 全量替换入口 `loadInitial`、`requestResync`、`returnToLatest` 统一调用
      `invalidateRefresh()`：递增 `refreshOwner` 并释放 `refreshInFlight`；被放弃请求的
      `finally` 不再清除新周期的标志，重同步成功后后续事实可正常刷新。
- [x] `loadRefresh` 的成功与失败路径都校验 `request === latestFullRequest` 与 owner；
      被取代请求的迟到 410/401/404 不再关闭正常连接或触发重同步；仅当替换未发生时
      将其失效标记重新排队。
- [x] 新增 2 项回归（重同步释放旧刷新、被取代错误不关流），`sync.test.ts` 共 22 项；
      全量 `npm test` 142 passed、`npm run typecheck`、`npm run build` 通过。

## T4.11 全量请求作废统一

- [x] 新增 `claimReplace()`：`loadInitial`、`returnToLatest`、`requestResync` 接管时递增
      `replaceOwner`、作废局部刷新，并释放旧 `replaceInFlight`；`runResync` 持有并校验
      自己的 owner，旧全量请求的 `finally` 不再影响新周期。
- [x] 四条全量路径（首次加载、“查看最新”、重同步及其失败分支）的成功、错误与清理回调
      都校验请求编号与 owner；被取代请求迟到的 410 不再触发重同步，404 不再改写
      `not_found`，成功响应也不覆盖新状态。
- [x] 新增 2 项全量交错回归（重同步释放旧“查看最新”、迟到 410/404 不关流），
      `sync.test.ts` 共 24 项；全量 `npm test` 144 passed、`npm run typecheck`、
      `npm run build` 通过。

## T4.12 失败恢复后的失效唤醒

- [x] 新增 `wakeRefresh()`：被取代请求把失效范围重新入队后，仅在当前周期可刷新时
      （`live`、无 resync/replace/refresh 在途）安排 0ms 刷新；历史模式只置更新提示，
      接管进行中则由接管者负责唤醒。
- [x] `loadRefresh` 的成功与失败两条被取代分支在 `requeue(scopes)` 后统一调用
      `wakeRefresh()`，避免旧 owner 的 `finally` 跳过调度后失效永久滞留。
- [x] 新增“全量 B 失败 → 重连完成 → A 最后返回”回归；`sync.test.ts` 共 25 项，
      全量 `npm test` 145 passed、`npm run typecheck`、`npm run build` 通过。
