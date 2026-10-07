# 07 DATA-12 业务事件与通知（C 阶段）

Type: task
Status: resolved
Blocked by: 06

## 目标

- **事件完整**：触发、补数、自动分析排队/结果/错误、状态（规则失效/预算达限）→ 持久化通知；
  保留对象身份、规则版本、来源 Run 与变化来源（BusinessEvent.kind/detail）。
- **通知队列**：最近未读优先的持久化视图（未读是视图不是状态）；等级 low/medium/high/urgent；
  按等级/类型/已读过滤；已读是用户明确操作；隐藏只是隐藏不改业务事实。
- **去重**：同一对象同一次触发（dedup key）不重复通知；事件错误不触发重复通知。
- **阅读进度与实时**：最近读取游标、SSE 游标重放（复用 B 阶段 /events/stream）+ 长期存活测试。
- **通知设置**：每用户类型/等级开关（默认全开）。
- 事件产生器挂接监控链（DATA-10/11）：触发 → `watch_triggered`；排队 → `auto_analysis_queued`；
  完成/失败 → `watch_analysis_completed/failed`；预算达限 → `watch_budget_blocked`；
  规则失效 → `watch_rule_inactive`；补数沿用 `input_required`（DATA-07 已有）。

## 验收

- 真 PG：触发/补数/分析排队/结果/错误/状态事件完整且去重；通知最近未读优先；按等级/类型/已读
  过滤；已读与隐藏幂等且不改变业务事实；SSE 游标重放与心跳；阅读进度；设置读写；所有者隔离。
- Ruff/Pyright/import smoke/symbol closure 通过。

## 契约要点

- `BusinessEvent` 追加 `level`（默认 medium）、`dedup_key`（可空，per-user 唯一）、`hidden`。
- 通知去重键：触发 `watch_trigger:{event.id}`；分析 `watch_analysis:{event.id}:{generation}`；
  终态 `watch_analysis:{event.id}:{generation}:done`（完成/失败互斥）；预算 `watch_budget:{event.id}`；
  规则失效 `watch_rule_inactive:{event.id}`。
- 新端点：`GET /notifications`（最近未读优先+过滤+unread_count+read_progress）、
  `POST /notifications/{id}/hide`、`GET/PUT /notifications/settings`。
- 未读优先排序：`(read_at IS NULL) DESC, cursor DESC`；隐藏项默认不返回。

## Comments

2026-10-03：在 DATA-11 收尾后开始。B 阶段（游标重放/已读/SSE 基础）已存在并通过
`test_input_requests.py` 验收；本批补 C 阶段视图与事件产生器。

2026-10-03：实现完成。
- 模型与迁移 `0017_business_notifications`：`business_events` 追加 `level`（默认 medium）、
  `dedup_key`（per-user 唯一，可空=不去重）、`hidden`；新增 `notification_settings`
  （muted_kinds/muted_levels，默认全开）。
- 事件产生器（挂接监控链）：`watch_eval.evaluate` 触发 → `watch_triggered`（dedup=事件身份）；
  `watch_scheduler.schedule_event` → `auto_analysis_queued` / `watch_budget_blocked` /
  `watch_rule_inactive`（expired）；`reconcile_event_runs` → `watch_analysis_completed/failed`
  （完成/失败共用终态去重键）；补数沿用 DATA-07 `input_required`。
- 通知服务 `business_events`：`add_event` 支持 level/dedup_key（保存点兜底并发去重）；
  `list_notifications`（最近未读优先 `(read_at IS NULL) DESC, cursor DESC` + kinds/levels/read
  过滤 + total/unread_count/read_progress）；`hide_event`（隐藏不改业务事实，游标重放仍可见）；
  `get_read_progress`；`get_settings`/`set_settings`；`stream_events` SSE 生成器（游标重放 +
  live tail + 可取消，路由薄包装）。
- 端点：`GET /notifications`、`POST /notifications/{id}/hide`、`GET/PUT /notifications/settings`、
  `GET /events/read-progress`。
真 PG 验收 `tests/pg/test_business_notifications.py` **13 passed**（原 166 项无回归，全套
179 passed）；迁移 0017 降级/升级往返通过；Ruff、Pyright、import_smoke（386/386）、symbol
closure（484 文件）通过。证据见 `../evidence/data12-pg.log` 与环境基线 §4.8。

2026-10-03 回溯复核：
- **SSE 测试方式修正**：httpx ASGITransport 会缓冲完整响应，无法对无限 SSE 流做 HTTP 端到端
  断言（`client.stream` 永不返回）。把流生成逻辑提取为 `business_events.stream_events`
  （路由仅做 `request.is_disconnected()` 薄包装），测试直接消费生成器验证游标重放、live tail
  与可取消（aclose）。无代码缺陷，属测试可测性重构。
- 通知设置按"存储偏好 + 显式过滤"落地：写入不静默丢弃（丢弃会丢业务事实），UI 按
  settings/过滤条件展示；安全类通知不因设置缺失而漏存。
其余复核项（触发/排队/结果/错误/预算/规则失效事件、去重、未读优先、已读/隐藏幂等、阅读进度、
所有者隔离）无剩余阻断项。
