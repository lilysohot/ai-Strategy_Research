# 08 DATA-13 归档、删除与取消联动

Type: task
Status: resolved
Blocked by: 07

## 目标

- **账户/计划归档**：置 `archived=True`（幂等、审计），停止新采用（resolve 已拒绝归档对象）；
  暂停引用该账户（经研究绑定）或该计划（直接绑定或研究主计划）的监控规则。
- **删除研究级联**：软删除会话（`deleted_at`，软删除≠擦除）→ 取消该研究所有活动规则、
  过期其待派发监控事件、取消其待补数请求、作废其待派发 outbox（不再启动新任务）、
  归档该研究所属计划（保留历史、停止新采用）；**共享账户与成交不随单一研究删除（AC-17）**。
- **取消与调度竞争**：级联在单一事务内完成；重复删除/归档幂等（重试不复活已取消任务）。
- **引用保留**：通知/补数/快照/Run 引用已归档或已删除对象不崩溃、可定位（不写死引用）。

## 验收

- 真 PG：归档账户/计划幂等且暂停相关规则；删除研究后规则 cancelled、事件 expired、
  补数 cancelled、计划 archived、共享账户仍可用；重复删除返回幂等回执；引用已删除对象的
  通知/补数查询不崩溃；归档对象不能再被新分析采用；快照与已启动 Run 不受归档影响。
- Ruff/Pyright/import smoke/symbol closure 通过。

## 契约要点

- 端点：`POST /api/business/accounts/{id}/archive`、`POST /api/business/plans/{id}/archive`、
  `DELETE /api/business/sessions/{rid}`（业务级联；通用会话删除路由保持原样）。
- 幂等键头 + 事务：归档/删除全部带 `Idempotency-Key` 与归属校验。
- 软删除不等于擦除：不物理删除业务事实、快照、审计；事件/通知保留引用。

## Comments

2026-10-03：在 DATA-12 收尾后开始。归档字段（accounts/plans.archived）与
`store.delete_session` 已存在但无业务级联；本批补写入端点与删除级联。

2026-10-03：实现完成。
- 服务 `server/business_archive.py`：`archive_account`/`archive_plan`（幂等、审计；暂停引用
  它们的监控规则）、`delete_research`（同一事务内：取消该研究活动规则、过期待派发事件
  （research_deleted）、取消待补数、作废待派发 outbox（PENDING/RETRYABLE_FAILED →
  ABANDONED）、归档该研究所属计划、软删除会话；共享账户/成交不随研究删除（AC-17））。
  全部走 `run_write` 幂等键 + 归属校验；重复删除/归档返回幂等回执，重试不复活已取消任务。
- `watch_scheduler.schedule_event` 增补 `ObjectArchivedError` 兜底：归档对象不能成为新分析
  有效选择时事件过期（object_archived），不再无限重试。
- 端点：`POST /api/business/accounts/{id}/archive`、`POST /api/business/plans/{id}/archive`、
  `DELETE /api/business/sessions/{rid}`（业务级联；通用 `/api/sessions/{id}` 删除保持原样，
  UI-10 对研究删除应走本业务端点以触发级联）。
真 PG 验收 `tests/pg/test_business_archive.py` **8 passed**（原 179 项无回归，全套 187 passed）；
Ruff、Pyright、import_smoke（386/386）、symbol closure（484 文件）通过。证据见
`../evidence/data13-pg.log` 与环境基线 §4.9。DATA-13 无新增迁移（复用 archived/deleted_at/status
列）。运行中 worker 让其完成当前 Run（不再启动新的），物理删除范围与保留策略属 DATA-14/15。

2026-10-03 回溯复核：
- 归档后调度实际先命中 `rule_inactive`（归档会暂停引用规则）而非 `object_archived`；
  `object_archived` 兜底仍保留供直接解析/竞争路径，测试按实际可达行为断言。
- 快照与已建 Run 事实在归档/删除后保留；待派发 outbox 作废（不再启动新任务）。
- 引用保留：通知/补数/快照/Run 引用已删除对象不崩溃、可定位。
其余复核项（幂等、AC-17 共享账户、所有者隔离、删除级联各状态）无剩余阻断项。
