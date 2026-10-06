# 05 DATA-10 行情判定与防重复唤醒

Type: task
Status: resolved
Blocked by: 04

## 目标

- **监控观测契约**：独立于 `Quote`（float + 回退本地时间）的判定真源 —— 精确 `Decimal` 价格、
  供应商观测时间/本地接收时间分开、时间来源与可信度标记（`vendor`/`unknown`）、去重身份。
  真实适配器只能给 float 时标 `precision_limited`，不得把 `now()` 冒充实时新行情。
- **判定引擎**（纯函数、固定时钟可测）：上穿/下穿/区间，精确数值比较，**不用浮点相等**；
  重复报价去重、乱序/陈旧报价忽略。
- **单次触发资格持久化**：`armed`（一次资格）+ `baseline_price` 随规则版本复位（改版不复用
  旧版基线与触发资格）；触发后消耗资格，分析失败不恢复成未触发。
- **事件原子保存**：观测/资格消耗/事件同一事务；事件唯一身份 = 规则版本 + 一次触发资格，
  并发判定与重复投递不重复消耗；C 阶段一个规则版本至多一个事件。
- **创建时已达标 / 重启首次报价 / 行情恢复**分别执行 `on_create_already_met` 与
  `disconnect_recovery` 策略；不能凭空补造断线期间的穿越。
- 常驻 monitor 轮询：普通程序复用市场服务/适配器，**监控链模型调用数为零**；限频/退避/批上限
  可配置；行情不可用时保持不可用/待核定，不伪装实时。

## 验收

- 固定时钟 + 行情序列：19.99→20.02 上穿触发一次；阈值附近往返只触发一次；一直越线不反复；
  重启后不重复触发；乱序/重复报价忽略；暂停/取消不判定；并发判定只消耗一次资格。
- 事件记录规则版本、前后价、观测/接收时间、触发原因；状态 `pending`（DATA-11 消费）。
- 监控链模型调用数为零；真 PG 覆盖上述场景；Ruff/Pyright/import smoke/symbol closure 通过。

## 契约要点

- `MonitoringObservation`：`thscode, market, currency, price(Decimal), observed_at_ms|None,
  received_at_ms, time_source(vendor|unknown), precision_limited, source_ref`。
- 事件唯一：`(rule_id, rule_version)`（C 单次模式）；`trigger_reason ∈ {initial_met,
  recovered_met, up_cross, down_cross, enter_range}`；状态 `pending`。
- 触发状态在 `watch_rules` 指针行：`armed`、`baseline_price`、`last_triggered_at`、
  `last_suppressed_reason`；编辑（新版本）复位 `armed=True, baseline=NULL`。
- 上穿：`prev < threshold <= cur`；下穿：`prev > threshold >= cur`；区间：从带外进入带内。
- monitor 后台进程按 DATA-00 §5 登记：启动/退出/心跳/健康；默认 `monitor_enabled=false`，
  部署时显式开启；不可用时保持待核定。

## Comments

2026-10-03：按 DATA-09 收尾后开始执行。判定语义以 DATA-01 契约 §9、DATA-10 任务文与
PRD §7.2/7.3 为准；C 阶段只实现单次触发资格状态机。

2026-10-03：实现完成。
- 观测契约 `server/watch_eval.py::MonitoringObservation`（精确 Decimal 价格 + observed/
  received 毫秒时间 + time_source(vendor|unknown) + precision_limited），`QuoteSource` 端口 +
  `FuyaoQuoteSource` 保守包装（float 源标 time_source=unknown + precision_limited，不宣称实时）。
- 判定引擎：`condition_met`/`classify_cross`（上穿 `prev<thr<=cur`、下穿、进入区间，精确比较
  不用浮点相等）；`_decide_trigger` 单次模式状态机（创建时已达标/断线恢复/常规穿越）。
- 模型与迁移 `0015_watch_monitoring`：`watch_rules` 指针行追加 `armed`/`baseline_price`/
  `last_triggered_at`/`last_suppressed_reason`；新增 `watch_observations`（去重 hash 唯一）与
  `watch_events`（`(rule_id, rule_version)` 唯一 = 事件身份，status=pending 待 DATA-11）。
  编辑（新版本）在 `watch_rules.update_rule` 复位 armed/baseline，改版不复用旧版资格。
- `watch_eval.evaluate` 原子保存观测/资格消耗/事件；重复投递去重、乱序忽略、暂停/取消不判定、
  标的/币种不符不判定；事件唯一约束为并发判定库级兜底。
- 常驻轮询 `server/monitor.py::monitor_tick/monitor_loop` + 配置（`monitor_*`，默认
  `monitor_enabled=false`，部署显式开启；DATA-00 §5 后台进程登记），lifespan 接入。
真 PG 验收 `tests/pg/test_watch_eval.py` **17 passed**（原 138 项无回归，全套 155 passed）；
迁移 0015 降级/升级往返通过；Ruff、Pyright、import_smoke（386/386）、symbol closure
（484 文件）通过；SQLite create_all 含新表与 armed 列。证据见 `../evidence/data10-pg.log`
与环境基线 §4.6。供应商时效/权限核验、事件→Run 调度属 DATA-10 供应商项与 DATA-11。

2026-10-03 回溯复核：发现并修复一项遗漏后 **18 passed**（全套 156 passed）：
- **有效期未强制**：`expires_at` 只在规则版本里保存，判定未执行有效期检查，过期规则仍可能
  触发。现 `watch_eval.evaluate` 在判定前检查 `now > expires_at` → 返回 `expired`，不再记录
  观测或建事件（规则本身未取消，UI 可续期改版）。补充 `test_expired_rule_does_not_trigger`。
- 另补 `watch_rules.rule_view` 暴露 DATA-10 触发状态（armed/baseline_price/last_triggered_at/
  last_suppressed_reason），供 UI-08 展示触发/抑制状态，不反复建分析。
其余复核项（上穿/下穿/区间、去重、乱序、暂停/取消、并发单次消耗、断线恢复、改版重新布防、
零模型调用、迁移往返）无剩余阻断项。
