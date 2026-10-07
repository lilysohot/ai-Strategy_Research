# 06 DATA-11 自动分析、合并与预算

Type: task
Status: resolved
Blocked by: 05

## 目标

- **事件→自动 Run 调度**：消费 `watch_events`(pending)，按**执行时**最新有效业务版本冻结快照
  （source=watch_event，与手动提交冻结分开），建 Run + outbox 派发意图**同一事务**；与手动
  Run 共用 dispatch_outbox 的研究级串行与租约恢复。
- **事件→Run 幂等**：每事件每代次唯一（`watch_event_runs.(event_id, generation)`）；重复调度
  返回原 Run，不重复建。
- **校验与失效**：调度时重新核对规则状态/版本（改版、暂停、取消使旧版未启动事件失效 →
  expired）、规则有效期、最大排队延迟（`analysis_expires_at`）；取消/归档与领取竞争不启动失效任务。
- **缺字段转补数**：resolve 失败（`PurposeRequirementError`）→ 建 DATA-07 补数请求
  （`watch_event_id` 关联、无来源 Run、带续接信息），事件 `needs_input`。
- **预算**：每规则版本 `watch_budget_usage`（runs_created/runs_attempted）原子预留并记账；
  `budget.max_runs` 达限 → `blocked_budget` 并说明原因，不建 Run；结算幂等。
- **合并**：同研究同标的同意图（action）的待派发事件合并到最早一条（merged + merged_into），
  保留原事件与合并去向，不跨用户/研究合并。
- **终态对账**：Run 终态（completed/failed/stopped）对账写入事件 completed/failed，保留旧终态。

## 验收

- 触发后无需再点确认即在原研究排队；事件查询所有者隔离（`GET /api/business/watch-events`）。
- 缺字段、预算竞争、改版失效、合并、幂等重放均可追溯（事件状态 + detail + 代次链路）。
- 真 PG 覆盖；监控/调度链零 LLM 调用；Ruff/Pyright/import smoke/symbol closure 通过。

## 契约要点

- 事件状态（契约 §9）：pending → dispatching → completed/failed；另有 needs_input /
  blocked_budget / merged / expired。
- 自动 Run 快照 `source="watch_event"`；手动 `source="manual"`。
- 预算上限取规则版本 `budget_json.max_runs`；`auto_max_delay_seconds` 默认 0 = 发布前未冻结。
- 常驻调度循环 `auto_enabled`（默认关闭，部署显式开启；DATA-00 §5 登记）。

## Comments

2026-10-03：实现完成。
- 模型与迁移 `0016_watch_auto_analysis`：`watch_events` 追加 run_id/generation/merged_into_id/
  budget_reason/analysis_expires_at/scheduled_at/attempted_at/completed_at；新增
  `watch_event_runs`（(event_id, generation) 唯一）与 `watch_budget_usage`（(rule_id, version)
  唯一，runs_created/runs_attempted）。
- 调度服务 `server/watch_scheduler.py`：`schedule_event`（校验→预算→解析→快照→Run+outbox 原子
  建→事件 dispatching）、`merge_pending`（按 (研究, 标的, action) 合并）、
  `reconcile_event_runs`（Run 终态对账）、`schedule_cycle`、`scheduler_loop`（lifespan 接入，
  `auto_*` 配置，默认关闭）。缺字段经 `_needs_input` 建带续接信息的 DATA-07 请求。
- `watch_eval.evaluate` 事件创建时写 `analysis_expires_at`；`event_view` 暴露调度字段；
  `GET /api/business/watch-events` 列表端点（所有者隔离）。
真 PG 验收 `tests/pg/test_watch_scheduler.py` **9 passed**（原 156 项无回归，全套 165 passed）；
迁移 0016 降级/升级往返通过；Ruff、Pyright、import_smoke（386/386）、symbol closure
（484 文件）通过。证据见 `../evidence/data11-pg.log` 与环境基线 §4.7。
预算的 token 级记账与"重新分析 +1 代次"入口、事件通知展示属 DATA-12 C / DATA-15 联合验收。

2026-10-03 回溯复核：发现并修复一项遗漏后 **10 passed**（全套 166 passed）：
- **notify 规则误建自动 Run**：`action=notify`（仅提醒）的规则触发后，调度器原会把事件建成
  自动 Run，违反"提醒规则不调用模型、不擅自开启模型分析"（契约 §9 / PRD §7.1）。现
  `schedule_event` 对非 `auto_analyze` 事件直接置 `completed` 并标记 `notify_only`，不建 Run、
  不记账。补充 `test_notify_rule_does_not_create_run`。
其余复核项（触发→自动 Run、快照 watch_event 冻结、幂等重放、缺字段转补数、预算达限、
改版/暂停失效、合并去向、终态对账、事件所有者隔离）无剩余阻断项。
