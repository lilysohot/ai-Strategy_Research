# 09 DATA-14 备份、安全与文件引用（恢复核对与恢复模式）

Type: task
Status: resolved
Blocked by: 08

## 目标

- **恢复核对**（`server/restore_check.py`）：恢复后一次核对数据库备份水位（alembic head）、
  Run 目录迁移清单（inputs/ws/outputs/spill/run 轨迹/diff 基线/staging）与跨表引用完整性
  （outbox/快照/事件/Run/补数/通知），缺文件/缺密钥明确报错。
- **恢复/迁移模式**（`restore_mode` 配置，默认 False）：开启时禁止派发与行情消费 ——
  dispatch/monitor/auto 后台循环不启动、运行中循环见到即停、手动提交 Run 拒绝；
  核对水位/文件清单/外部调用尝试后**显式**关闭该模式才恢复后台任务；
  已有待处理监控事件由调度器按有效期/取消状态重新裁决（不盲目重播付费分析）。
- **外部调用水位**：报告 WatchEventRun / watch_budget_usage.runs_created / RunDispatch 计数与
  pending 事件数，供恢复后对照备份快照，避免回滚后重复付费分析。
- **日志不写资金/持仓正文**：审计只记对象标识与变更字段名（既有设计），补测试锁定。

## 验收

- 真 PG + 临时 Run 根：完整恢复核对通过；缺轨迹文件/缺目录/孤立引用明确报错；
  restore_mode 关闭后台任务与手动提交；待处理事件恢复后按有效期/取消重新裁决。
- 审计 detail 不含资金/持仓数值；Ruff/Pyright/import smoke/symbol closure 通过。

## 契约要点

- 恢复核对为只读操作（服务 + CLI，不暴露跨用户汇总的 Web 端点）。
- 后台任务统一入口 `background_tasks_allowed()`；`restore_mode=True` → False。
- 不新建平行文件迁移任务或轨迹数据库（归并存储修复，F01/F07/F15/F17/F18/F19）。

## Comments

2026-10-03：在 DATA-13 收尾后开始。DATA-14 无新增业务表（前批表已纳入同一 PG 库与
alembic 链），本批交付恢复核对、恢复模式与审计锁定。

## Resolution（2026-10-07）

**实现**

- `server/restore_check.py`：`check_restore()` 一次核对五节——①数据库备份水位
  （`alembic_version` vs 迁移链 head）；②Run 目录清单（inputs/ws/ws/outputs/spill/run/
  diff/staging 齐备，非 queued Run 还需轨迹文件）；③跨表引用完整性（8 组孤立引用计数，
  覆盖 RunDispatch/快照/WatchEvent/WatchEventRun/InputRequest/BusinessEvent，含刻意
  不加外键的 `InputRequest.watch_event_id`）；④外部调用水位（watch_event_runs /
  budget_runs_created / run_dispatch_rows / pending_watch_events，对照备份防重复付费）；
  ⑤密钥（任何用户默认 LLM 凭据解密失败列出用户）。AC-18「报告不可读时明确标识」：
  schema 水位先核，其后分节失败把失败记入 `errors` 返回部分报告，不崩溃。CLI
  `python -m server.restore_check [runs_root]` 输出 JSON，exit 0/1。
- `server/config.py`：`restore_mode: bool = False`（SERVER_ 前缀）。
- 恢复模式闸门：`background_tasks_allowed()` 统一入口；`dispatch_loop` /
  `monitor_loop` / `scheduler_loop` 循环开头见模式即停（配置热加载，切换即生效）；
  `app.lifespan` 三任务启动条件加 `not restore_mode`；`POST /api/runs` 手动提交
  503 明确提示核对后显式关闭。待处理监控事件不重播，由调度器按有效期/取消状态
  重新裁决（既有 DATA-10/11 语义）。
- 审计锁定：归档/规则变更审计 detail 仅含对象标识与被暂停规则 id，无资金正文。

**验收**（`tests/pg/test_restore_check.py`，12 项全过；全套 tests/pg 199 passed，
证据 `evidence/data14-pg.log`）

- 完整核对通过（queued Run 无轨迹合法、水位/孤立引用/外部调用/密钥全绿）。
- 缺目录 / 非 queued 缺轨迹 / 孤立 `watch_event_id` / 无法解密密钥 / 水位不符 →
  `ok=False` 且逐项明确报错。
- AC-18：模拟旧备份（downgrade 0015 后缺 0016/0017 表）→ 报告同时给出水位不一致
  与 `restore check incomplete`，不崩溃，核对后迁移还原。
- restore_mode=True → 三循环零调用、手动提交 503；显式关闭 → 循环恢复工作、
  提交恢复 202。
- 归档审计 detail 仅 `{account_id, paused_rules}`，金额不出现。
- CLI 干净库 exit 0。
- 门禁：Ruff check/format、Pyright（本批文件 0 错误）、import_smoke 386/386、
  check_symbols 484 文件、`git diff --check` 全部通过。

**回溯复核**

- 新增表纳入既有备份：无新表，前批 0013–0017 均在同一业务库，`scripts/web_backup.py`
  整库备份自动覆盖，无需改动。
- 服务端日志无资金/持仓正文输出（grep 核对），审计行为测试锁定。
- 目录迁移清单与 `config.build_run_paths` / `diff.DiffRecorder` 对齐；轨迹路径与
  worker 实际落盘一致；不另建平行文件迁移任务。
- 逻辑恢复在原 PG 实例独立库 + 临时目录验证（本批测试即此形态）；实例/卷故障的
  独立故障环境属部署操作，不在代码批次内。
- 已知边界：`user_llm_cred_state` 核对上限 `max_users_for_keys=100`（防全表逐行
  解密拖垮核对；更大规模按需提高参数）；恢复核对为服务/CLI 入口，不暴露跨用户
  Web 端点（避免权限面扩大）。

**2026-10-07 回溯复核补记（开放缺口）**：任务清单 §7 将「保留期/恢复目标与
加密选择」的发布前冻结归属 DATA-14，且 DATA-13 需求要求"发布前定义业务数据、
快照、审计、轨迹、产物和备份的保留/物理删除范围"。本批未承接该项：runs 文件
保留 90 天、备份保留 30 天已由 F07（`deploy/README.md`）定值，但**业务数据
（快照/审计/事件/版本）的保留期限与物理删除流程尚未定义**。登记为开放缺口，
发布前须定值，不因本批恢复核对通过而视为关闭。
