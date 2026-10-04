# 04 DATA-09 监控规则持久化与管理

Type: task
Status: resolved
Blocked by: 03

## 目标

- 规则模型 + 不可变版本行：标的/市场/币种/报价口径、阈值/方向、有效期、次数模式（C 阶段仅
  single）、研究归属、该研究所属计划、分析意图（action/task/budget）、创建时已达标策略、
  断线恢复策略；归属一致性下沉到数据库。
- 生命周期操作：创建/编辑（新版本）/暂停/恢复/取消，全部带版本、幂等与归属校验；改版不复用
  旧版报价基线与触发资格（由 DATA-10 判定侧消费，本任务保证旧版本行不可变、不静默改阈值）。
- 记录最近检查及有效行情时间（`record_check` 服务，供 DATA-10 写入）。
- 查询：按研究列出规则、规则详情、版本历史；重启后规则及状态存在。

## 验收

- 真实 PostgreSQL：创建/编辑/暂停/恢复/取消及版本历史可追溯；同键重放不产生新版本/新副作用；
  expected_version 冲突返回 409；他人规则 404；已取消规则不可再编辑/暂停/恢复（409）。
- C 阶段只开放 `trigger_mode=single`；重复模式（repeat）明确拒绝，不静默接受。
- 计划改版不静默修改已保存阈值；规则阈值只随规则自身版本变化。
- Ruff、Pyright、相关 PG 测试通过；验收证据登记到环境基线 §4.5。

## 契约要点（以 DATA-01 契约 §9 为准）

- 字段：symbol / market / currency / quote_basis / direction(up|down|range) /
  threshold（up/down 单值，range 需 low+high 且 low<high）/ expires_at / trigger_mode(single) /
  action(notify|auto_analyze) / task / budget{max_runs} / on_create_already_met(trigger_now|wait_requalify)
  / disconnect_recovery(trigger_once|wait_requalify)。
- 每次编辑产生新 version；暂停/恢复/取消改变指针行 status（active|paused|cancelled），不产生
  配置版本；状态操作带 expected_version 与幂等键。
- 提醒规则（action=notify）不调用模型；auto_analyze 才创建 Run（Run 创建属 DATA-11）。
- 端点：
  - POST /api/business/sessions/{research_id}/watch-rules（创建）
  - GET  /api/business/watch-rules（列表，可选 research_id/status）
  - GET  /api/business/watch-rules/{rule_id}（详情）
  - PATCH /api/business/watch-rules/{rule_id}（编辑，带 expected_version）
  - GET  /api/business/watch-rules/{rule_id}/versions（版本历史）
  - POST /api/business/watch-rules/{rule_id}/pause
  - POST /api/business/watch-rules/{rule_id}/resume
  - POST /api/business/watch-rules/{rule_id}/cancel

## Comments

2026-10-03：按 DATA-08 收尾后开始执行。字段/API 以 DATA-01 契约 §9 为准，C 阶段只开放单次模式。

2026-10-03：实现完成。模型 `server/store.py::WatchRule(+WatchRuleRevision)`，迁移
`0013_watch_rules`（表）+ `0014_watch_rule_history`（版本行 UPDATE/DELETE 拒绝，沿用 0010 触发器）；
写入/生命周期服务 `server/watch_rules.py`（创建/编辑新版本/暂停/恢复/取消，全部带 expected_version、
幂等键与归属校验，`record_check` 供 DATA-10 记录最近检查与有效行情时间）；路由
`server/routes/business.py`（`/api/business/.../watch-rules` 系列 8 个端点）。C 阶段拒绝
`trigger_mode=repeat` 与冷却/重新布防字段（unknown_field_rejected），不静默接受。
真 PG 验收 `tests/pg/test_watch_rules.py` **23 passed**（原 113 项无回归，全套 136 passed）；
迁移降级/升级往返通过；Ruff、Pyright、import_smoke stage 1（386/386）、symbol closure
（484 文件）通过；SQLite create_all 路径含不可变触发器正常。证据见
`../evidence/data09-pg.log` 与环境基线 §4.5。
