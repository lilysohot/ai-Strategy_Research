# SSE-T04 复核清单

复核日期：2026-11-20。依据 [spec.md](spec.md)、[tasks.md](tasks.md) 与
[建设计划 §20.10](../../plan/super-link-communication-foundation.md#20-sse-状态同步执行计划2026-11-20)；
本批只改 `web/` 与文档，未启动服务、未连接业务库。

- [x] 快照接流：首次用 `/snapshot` 的 `cursor` 建立 `/events`，刷新带 `min_cursor`，
      未发送 `Last-Event-ID`。证据：`sync.ts` 的 `loadInitial`/`openStreamConnection`；
      `stream.test.ts` 请求头与 `after` 断言。
- [x] 事实处理：`sl.fact` 只校验 schema/space/epoch/seq、推进游标并累计 `invalidate`，
      150 ms 后合并快照；不直接把事件 `data` 写入业务状态。证据：`sync.test.ts`
      合并、去重与“事实不直接改控制状态”用例。
- [x] 旧响应丢弃：请求序号、游标单调、空间代次三重校验；离线或跨空间迟到响应不写入。
      证据：`sync.test.ts` 旧刷新、游标倒退、`stop()` 后迟到用例。
- [x] 重连与重同步：EOF/网络/5xx 从最后游标重连；`sl.resync_required`、410、400、
      epoch 变化重新全量快照；401/403、404、429 与 8 次失败映射符合规格 §5.5/§6。
      证据：`sync.test.ts` 对应用例。
- [x] 分页与历史：运行/交付/恢复操作可续页；成功后才进入 `history`，失败不困在历史；
      历史模式只置 `hasUpdates`，`returnToLatest` 全量替换；待审批整页替换。
      证据：`sync.test.ts` 15 项（含新增失败回退用例）。
- [x] 页面接入：详情不再调用旧 `space/runs/deliveries`，5 秒定时器已移除；列表页保留
      旧 REST 加载与分页；`more` 分别走旧列表分页与 `loadMore`；同步状态条、重试与
      历史提示可见。证据：`SuperLinkView.vue`；typecheck 与生产构建。
- [x] 控制面板：可选 `pending`/`pendingTotal`/`activeRunIds`/`actions`/`actionsNext`
      优先于自有轮询；`/interventions` 降为 30 秒兜底且仅用于 `recent`；审批、控制、
      恢复与补充指令提交后 emit `changed` 并由快照确认；审计分页走
      `loadMore('actions')`。证据：`SuperLinkControls.vue`、`SuperLinkView.vue` 传参。
- [x] 未提交输入与本地状态：审批按 `control_id`、`steerText` 按 `run_id` 保留；
      同步刷新不重建控制面板；交付/运行抽屉的 epoch 防串页检查保留。
      证据：`SuperLinkControls.vue` 的 props 更新与 key；`SuperLinkView.vue` 的抽屉逻辑。
- [x] 释放与隔离：卸载、路由离开、空间切换调用 `stop()`，旧流、定时器与迟到回调
      不写入；旧空间数据不进入新空间。证据：`useSpaceSync.ts`；`sync.test.ts`
      `stop()` 用例。
- [x] 现有行为：`openRunStream` 与普通模式调用方未改；幂等键、`expected_version`、
      `sessionStorage` 待确认请求与“停止需真实收尾”语义保留。证据：`sse.ts` 只改导入；
      `SuperLinkControls.vue`。
- [x] 回归：`cd web && npm test` 135 passed；`npm run typecheck` 通过；
      `npm run build` 通过；后端
      `uv run pytest tests/test_super_link_stream.py -q -p no:cacheprovider` 26 passed。
- [x] 文档与移交：计划 §20.2/§20.6 已更新、§20.10 已新增；spec/tasks 状态与复选框
      已收口；T06 的列表并发测试补强已登记。
