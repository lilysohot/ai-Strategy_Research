# Web 业务资料 · 共用数据与操作契约（DATA-01）

| 项 | 内容 |
|---|---|
| 版本 / 日期 | v0.1 · 2026-10-02 · 首次冻结草案 |
| 状态 | **契约冻结中**：本文确定的语义即实现口径；§11 的待定项在冻结前不得被客户端或实现静默填值 |
| 需求依据 | [产品需求](../product-requirements.md) §4.7、PR-BIZ-01—06、PR-WATCH-01—04、PR-DATA-13 |
| 上级设计 | [Web 业务资料需求规格](web-business-data-prd.md) v0.6（§8 的“拟议”接口由本文收口） |
| 任务依据 | [持久化任务清单](../plan/web-business-persistence-tasks.md) DATA-01；[页面任务清单](../plan/web-business-ui-tasks.md) §5 |
| 环境依据 | [环境基线与验证入口](../plan/web-business-data-env-baseline.md) |

本文是 UI、Agent 工具与 JSON/multipart 提交共用的**唯一**协议。页面不得另立一份字段协议，
也不得通过解析自然语言回复判断业务提交是否成功。服务端为归属、字段、版本和幂等的强制方。

## 1. 通用约定

### 1.1 数值、单位与缺失

| 规则 | 约定 |
|---|---|
| 传输形式 | 金额/价格/数量/比例一律为**十进制字符串**，匹配 `^-?(0\|[1-9]\d*)(\.\d+)?$` |
| 禁止形式 | 科学计数法（`1e9`）、千分位、前导 `+`、尾随空格、`NaN`/`Infinity`、JS Number 直传 |
| 缺失 | JSON `null`。**缺失不是 0**，也不得写成空串或 `0.0` |
| 存储类型 | 金额/价格/数量 `NUMERIC(30,10)`；汇率 `NUMERIC(24,12)`；比例/盈亏比 `NUMERIC(20,10)` 且必须带 `unit` |
| 比例单位 | `unit ∈ {percent, ratio, amount, currency}`；`2%` 与 `2` 不得混用 |
| 币种 | ISO 4217（首批 `CNY/HKD/USD`）；多币种不自动求和，换算须带汇率来源与时点 |
| 精度来源 | 最小报价单位与数量步长由资产规则给出；首批资产未核定前不得套用任一市场规则（见 §11） |

### 1.2 值状态与来源

`status ∈ {user_provided, draft_pending, pending_clarification, external_observed, system_computed, absent}`

| 状态 | 含义 | 可否进入依赖计算 |
|---|---|---|
| `user_provided` | 用户作为自己的真实资料提交 | 可 |
| `draft_pending` | 用户主动提交但字段不完整，服务端持久保存、刷新可读 | **不可**（用于受影响的计算） |
| `pending_clarification` | 假设/估计/疑问/歧义，或未解决更正 | **不可** |
| `external_observed` | 行情/接口观测，带观测与接收时间 | 按用途使用，不是用户资料 |
| `system_computed` | 确定性计算，带 `formula_version` 与输入引用 | 可，须标注为系统计算 |
| `absent` | 明确无值 | — |

`source`：`{kind: form \| chat \| attachment_extract \| market \| system, ref, captured_at}`。
“用户明确提供”表示用户声明，**不表示平台已外部核验**；UI 不得显示成已核验。

### 1.3 时间

全部以 UTC 存储、ISO 8601（`…Z`）传输，UI 本地化渲染。四类时间不得互相冒充：

| 字段 | 含义 |
|---|---|
| `as_of` | 业务时点（用户资料“截至何时”） |
| `recorded_at` | 服务端记录时间 |
| `observed_at` / `received_at` | 行情供应商观测时间 / 本地接收时间 |
| `analysis_started_at` | 分析开始时间 |

缺少可靠 `observed_at` 时以 `observed_at=null` + `time_source=unknown` 表示，不得用 `now()` 冒充实时行情。

### 1.4 归属与标识

- `owner` 由认证（JWT）绑定；**请求体不接受 `user_id`/`owner_id`**，出现即 `400 owner_not_settable`。
- 对象 `id` 为 UUID 字符串；`revision` 为对象内单调整数，版本行不可变。
- 所有修改类请求必须带 `expected_revision`（新增除外）。
- 无权访问与不存在统一 `404 not_found`，不泄漏差异。
- 归档对象 `archived=true`：不可被新分析采用，历史快照仍可读。

## 2. 错误信封与状态映射

```json
{
  "error": {
    "code": "revision_conflict",
    "message": "对象已被其他窗口修改",
    "fields": { "total_capital": "需要十进制字符串" },
    "current": { "revision": 7, "archived": false, "updated_at": "2026-10-02T09:12:00Z" },
    "retryable": false,
    "remedy": "reload_and_resubmit",
    "operation_id": "op_01HQ..."
  }
}
```

| HTTP | code | 触发 | retryable |
|---|---|---|---|
| 400 | `validation_error` | 字段格式/单位缺失，定位到 `fields` | 否 |
| 400 | `purpose_requirement_unmet` | 用途必需字段缺失或状态不是 `user_provided` | 否（补字段后可重试） |
| 400 | `assumption_rejected` | 假设/估计/疑问候选值或“本次假设覆盖” | 否 |
| 400 | `unknown_field_rejected` | 业务子结构出现未知字段，或客户端试图设定 owner | 否 |
| 404 | `not_found` | 不存在**或**无权（不区分） | 否 |
| 409 | `revision_conflict` | `expected_revision` 与当前版本不一致 | 是（按新版本重提） |
| 409 | `idempotency_key_reuse` | 同键不同请求摘要 | 否 |
| 409 | `request_already_answered` / `request_cancelled` / `request_expired` | 补数请求终态已变 | 否 |
| 409 | `archived` | 对归档对象做新分析采用 | 否 |
| 429 | `quota_exceeded` | 预算/次数/并发额度达限，附 `reason` | 按响应给定 |
| 503 | `dependency_unavailable` / `storage_unavailable` | 依赖不可用，附带可重试条件 | 是 |

`remedy ∈ {fix_fields, clarify_value, reload_and_resubmit, retry_same_key, wait, contact_support}`。
客户端按 `code` 分支，**不解析 `message` 文本**做业务判断。

服务端实现落点：`server/business_service.py`（异常类 → `code`/HTTP 映射、`to_payload()` 即上表信封）。
另增加 `operation_pending`（同一幂等键的上一次写入尚未确定结果，先查询再决定是否重发）。

## 3. 幂等与操作结果

| 规则 | 约定 |
|---|---|
| 键 | 写操作必须携带 `Idempotency-Key`（UUID 或 `<scope>:<uuid>`），作用域为用户 + 操作类型 |
| 同键同摘要 | 返回原结果，`replayed=true`，不产生第二次副作用（不重复写版本、不重复建 Run、不重复派发） |
| 同键异摘要 | `409 idempotency_key_reuse` |
| 结果查询 | `GET /api/business/operations/{operation_id}`；`GET /api/business/operations?recent=1&scope=<type>` 查自己最近操作 |
| 键未知 | `404 operation_unknown`；UI 展示“结果待核定”，**不盲目重发** |
| 保留期 | 24h（可配置 `SERVER_IDEMPOTENCY_TTL_H`，见 §11）；清理不得导致原动作再次执行 |
|  attachments | 带附件提交分阶段回执：`uploading → validating → committing → dispatching`；同名冲突就地提示，重试复用已登记附件，不静默覆盖 |

## 4. 用途 → 必需字段 → 可调用能力

服务端为准；客户端与模型不得降低要求。未列出的用途按 `general_reading` 处理。

| use_case | 必需（`user_provided`） | 允许值约束 | 可调用计算 | 缺失时行为 |
|---|---|---|---|---|
| `general_reading` | 无 | — | 材料阅读、检索、非个性化分析 | 不阻断 |
| `plan_analysis` | 账户：`currency`、`capital_basis`、`as_of`、总资金/可用资金（按口径至少一项）；计划：`symbol`、`market`、`direction`、`plan_price` 或 `plan_price_low/high`、`target_price` | 未成交时 `actual_price` 必须为 `null` | `position_sizing`（按计划价）、`strategy_lint` | `400 purpose_requirement_unmet` + 字段定位；**不调用**依赖资金/成本的工具 |
| `holding_cost` | 上者 + 成交记录（side/qty/price/currency/fees/traded_at）或持仓快照（qty、cost_basis、as_of），且 `purchased=true` | 必须 `user_provided` 的实际成交价 | `position_sizing`、成本/收益计算 | 缺实际价 → `pending_clarification`，阻断该计算 |

## 5. 对象读写契约

| 对象 | 归属与约束 |
|---|---|
| 账户 `accounts` | 归用户；可被多个研究引用；第一版一个研究至多引用一个账户 |
| 计划 `plans` | **必须且只能属于一个研究**；从研究会话内创建，自动归属，页面不提供会话选择器；跨研究复用意图须新建计划并保留来源 |
| 当前主计划 | 研究的属性，只能从该研究所属计划集合中选择 |
| 持仓快照 `position_snapshots` | 账户 + 标的 + 数量 + 成本口径 + `as_of` + 来源；手工录入不自动叠加重算资金 |
| 成交 `trade_records` | 更正保留前值并创建新版本；不触发任何交易执行 |
| 策略版本 `strategy_versions` | 保存生成 Run 与产物引用；采纳后在**当前研究**创建/修改计划，不变成用户已成交事实 |

修改回执：`{object_id, revision, prev_values, next_values, changed_fields[], saved_at, operation_id}`。

## 6. 分析提交（JSON 与 multipart 同一契约）

```json
{
  "message": "按当前计划给出仓位建议",
  "session_id": "...",
  "investment_input": {
    "use_case": "plan_analysis",
    "account": { "id": "...", "expected_revision": 3 },
    "plan": { "id": "...", "expected_revision": 5 },
    "declared": {
      "total_capital": { "value": "100000", "currency": "CNY", "unit": "currency", "as_of": "2026-10-02", "status": "user_provided" }
    },
    "idempotency_key": "analyze:9f1c..."
  }
}
```

| 规则 | 约定 |
|---|---|
| 仅保存 | 业务对象端点保存，**不创建 Run** |
| 保存并分析 | 业务变更 + 版本/审计 + 快照 + queued Run + 待派发记录**同一事务**；返回 `{saved, run{id,status,snapshot_id}, dispatch{status,attempt}, operation_id}` |
| 状态区分 | `save_failed` / `saved_dispatch_pending` / `running` / `failed` 四类不得合并；派发延迟不得显示为资料丢失 |
| multipart | 业务结构以表单字段 `investment_input`（JSON 文本）随文件提交，**必须解析**；不得被旧解析器静默忽略 |
| 旧客户端 | 不含 `investment_input` 的请求保持原行为（非业务研究），不做业务校验 |
| 未知字段 | 业务子结构内未知字段一律 `400 unknown_field_rejected` |
| 假设覆盖 | 出现 `assume`/`scenario_override` 或候选值 → `400 assumption_rejected`；本产品不支持“仅本次假设覆盖” |
| 对象引用 | `account`/`plan`/`trade`/`position` 均为 `{id, expected_revision?}`；`expected_revision` 与当前版本不符 → `409 revision_conflict` |
| 一致性 | 计划必须属于提交的那个研究；成交/持仓必须与账户一致；跨研究与混用账户一律 `404 not_found` |
| 幂等 | `investment_input.idempotency_key` 为建 Run 必填；同键重放返回原 Run 与原 `snapshot_id`，不产生第二个分析 |

实现落点：`server/investment_snapshot.py`（解析、校验、冻结）与
`server/routes/runs.py`（`POST /api/runs` 同事务冻结、`GET /api/runs/{id}/investment-snapshot`、
`POST /api/runs/{id}/rerun`）。

## 7. Run 快照、状态与重算

| 规则 | 约定 |
|---|---|
| 快照内容 | `schema_version`、账户/计划/持仓/成交的**对象版本**、解析后的完整有效值、来源与明确状态、缺失与待澄清项。只存 ID 不算快照 |
| 冻结时点 | 手动 Run：**提交时**冻结；自动事件：**调度创建 Run 时**按当时最新有效版本冻结。两者创建后都不可变 |
| 读取 | `GET /api/runs/{id}/investment-snapshot`（按 Run owner 授权）；缺失返回 `404 snapshot_absent`，**不得用当前资料回填** |
| 结束原因 | 补数结束原因 `input_required`：`status=stopped`、`stopped_by=input_required`（不是 `failed`） |
| 派发状态 | 与 Run 状态分离：`not_required \| pending \| dispatched \| claimed \| retryable_failed \| abandoned` |
| 重算 | 提交“停止 + 关联新 Run”操作，新 Run 用新快照；旧轨迹、旧快照与来源关系保留；同研究串行 |
| 排队中 | 已排队手动 Run 保持原快照；用户通过取消重提采用新资料，不暗中替换 |
| 附件 | 上传先入受控暂存区并记持久清单（`run_uploads`，`staged`）；worker 领取前校验文件存在且 `sha256` 一致才发布到 `inputs`（`published`），否则不投递 |
| 队列上限 | 逐研究未完成派发意图数达上限 → 新建/重算返回 `429 quota_exceeded`（`remedy=wait`）；重算取代的旧 Run 不计入 |
| 停止超时 | 重算等待旧 worker 确认退出（`dispatch_stop_timeout_seconds`）；超时只报告，新 Run 仍由研究互斥串行，绝不并发执行 |

实现落点（DATA-06）：`server/store.py::RunDispatch` + `server/dispatch_outbox.py`
（领取/租约/回收/取消、逐研究队列上限，研究级互斥基于库判定）；附件见
`server/store.py::RunUpload` + `server/uploads.py`（暂存、清单、发布校验）；业务 Run 的
提交事务同时落 session/run/turn/快照/附件清单/outbox；派发经
`GET /api/runs/{id}/dispatch` 可查，旧客户端直投路径返回 `not_required`；派发循环随
API 进程启停，多进程共享派发由 `SKIP LOCKED` 领取 + 租约保证，不重复投递。

## 8. 补数请求与回答

```json
{
  "id": "irq_...",
  "research_id": "ses_...",
  "source_run_id": "run_...",
  "watch_event_id": null,
  "use_case": "holding_cost",
  "status": "pending",
  "revision": 1,
  "fields": [
    { "name": "actual_price", "unit": "currency", "currency": "CNY", "known_value": null, "reason": "未成交与已成交未明确" }
  ],
  "expires_at": "2026-10-09T00:00:00Z"
}
```

| 规则 | 约定 |
|---|---|
| 归属 | 每条请求**必须且只能属于一个研究**（`research_id` 非空）；`source_run_id` 与 `watch_event_id` 可为空（自动事件在创建 Run 前缺数时为空） |
| 状态 | `pending \| answered \| cancelled \| expired` |
| 保存顺序 | 请求先持久保存再通知；不依赖活 worker 等待；原 Run 以 `input_required` 结束 |
| 明确回答 | 保存业务变更 + 新快照 + 后续 Run，**同一请求只生成一次续接**（幂等）；返回 `follow_up_run_id` |
| 部分/歧义回答 | 只记 `answer`，请求保持 `pending`，返回 `pending_clarification`；不展示为“分析已继续” |
| 版本冲突 | 回答期间资料被改版 → `409 revision_conflict`，不覆盖更新；用户可明确沿用新值并记为回答来源 |
| 终态冲突 | 已回答/已取消/已过期/研究已删除 → 对应 409 |
| 通道 | 走补数端点，**不复用工具审批 `/approve`** |

## 9. 监控、事件与通知

```json
{
  "id": "wr_...", "research_id": "ses_...", "version": 2,
  "symbol": "600519.SH", "market": "CN", "currency": "CNY", "quote_basis": "last",
  "direction": "up", "threshold": "20.00",
  "expires_at": "2026-10-31T00:00:00Z", "trigger_mode": "single",
  "action": "auto_analyze", "task": "触发后按当前计划重算仓位", "budget": { "max_runs": 1 },
  "on_create_already_met": "trigger_now"
}
```

| 规则 | 约定 |
|---|---|
| 版本 | 每次编辑产生新 `rule_version`；改版不复用旧报价基线与触发资格 |
| 改版/暂停/取消 | 旧版**未启动**的派发失效；恢复按新观测重新校验，不补发积压旧触发；历史事件保留；已启动 Run 不改写，是否停止由明确操作决定 |
| 提醒 vs 分析 | 仅要求提醒时 `action=notify`，不得擅自开启模型分析；`action=auto_analyze` 才创建 Run |
| C 阶段 | 只开放 `trigger_mode=single`；重复模式及其冷却/重新布防在 D 阶段 |
| 事件身份 | `rule_version + 一次触发资格`；重复投递、并发判定不重复消耗 |
| 冷却中穿越 | 只记录抑制原因，**不在冷却到期时补发**；冷却到期本身不是触发 |
| 事件状态 | `pending \| dispatching \| running \| completed \| failed \| expired \| merged \| blocked_budget \| needs_input`，与“分析成功/失败”分开 |
| 时点 | 事件固定记录 `observed_at`/`received_at` 与触发报价；分析另存开始时行情，UI 展示两时点与延迟 |
| 通知 | `GET /api/business/events?after=<cursor>&limit=` → `{items, cursor, cursor_expired}`；SSE `/api/business/events/stream?after=`；已读状态服务端保存；游标过期要求全量同步；事件按 ID 去重；owner 隔离 |
| 已启动 Run | 沿用 per-run SSE；HTTP 查询是恢复真源，连接存在不等于后台在线 |

## 10. 协议样例（有效 / 缺失 / 歧义 / 冲突 / 幂等重放 / 超时重试 / 无权）

1. **有效保存**：`POST /api/business/accounts` → `201`，`{"account":{"id":"acc_..","revision":1},"operation_id":"op_.."}`
2. **缺失**：`declared.total_capital` 为空且 `use_case=plan_analysis` → `400 purpose_requirement_unmet`，`fields.total_capital="请填写真实总资金（十进制，含币种与时点）"`
3. **歧义/假设**：`"大概 20 元"` / `"先按 8 万算"` → `400 assumption_rejected`，写入回答记录，字段保持 `pending_clarification`
4. **版本冲突**：`expected_revision=5`，当前 `7` → `409 revision_conflict`，`current.revision=7`，`remedy=reload_and_resubmit`
5. **幂等重放**：同键同摘要重发 → `200` + `"replayed":true`，无新版本、无新 Run
6. **超时重试**：客户端丢响应后用同键重试 → 返回原 `operation_id` 与原 Run；键已清理→ `404 operation_unknown`，UI 显示“结果待核定，请查询最近操作”，不重发
7. **无权/不存在**：`GET /api/business/plans/{他人id}` → `404 not_found`（不区分两种原因）
8. **补数回答**：完整明确 → `200` + `follow_up_run_id`；含歧义 → `200` + `status=pending`；资料改版 → `409 revision_conflict`

## 11. 待定项与冻结门槛（发布前必须确定，禁止静默填值）

| 待定项 | 冻结责任 | 未定时的行为 |
|---|---|---|
| 首批资产/市场、行情口径与盘中权限 | DATA-09/10 | 不满足时效的监控能力禁用并说明原因 |
| 采样间隔、报价有效期、最大排队延迟 | DATA-10/11 | 展示为“待定”，不得默认 3 秒/10 分钟 |
| 重复规则：冷却、重新布防、确认持续时间 | DATA-10（D 阶段） | C 阶段不开放重复模式 |
| 预算：每规则/每用户次数、并发、token 上限与重试上限 | DATA-11 | 达限保留触发并说明原因 |
| 幂等键保留期、事件/版本/快照保留期、恢复目标 | DATA-01/14 | 采用本文 24h 默认并在实现登记 |
| 字段加密选择与密钥管理 | DATA-14 | 不得只加密当前表 |
| 资产精度、最小报价单位与数量步长表 | DATA-02 | 不得套用任一市场默认规则 |

讨论中的示例数值（`19.90`、`3 秒`、`10 分钟`、`10 万`、`8 万`）**只用于测试样例**，不是产品默认值。

## 12. 与页面的交接

页面消费结构化错误、版本、幂等结果和状态；不解析自然语言推断提交成功；不自行降低用途要求；
不把 `draft_pending` 显示为“可用于分析”；不把 `user_provided` 显示为“已外部核验”；
未在 §11 冻结的配置不显示为既定产品行为。接口路径可在实现中调整，语义与错误结果不得改变。
