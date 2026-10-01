# F21 最小契约草案：用户纠正与审批决定的持久追溯

| 项 | 内容 |
|---|---|
| 版本 / 状态 | v1.0 · 2026-10-01 · **已按本契约实现并跑通隔离契约；真实部署迁移未执行** |
| 对应工单 | [21 用户纠正与审批决定缺少持久追溯契约](issues/21-control-history.md) |
| 决策记录 | D1/D2/D3 均取本草案建议（用户「开始执行」指令，2026-10-01），即 §9 (a)/(a)/(a) |
| 报告正文 | [修复报告 F21](../../docs/plan/web-runtime-trace-repair-report.md) |
| 上游需求 | PR-RUN-04/05（P0）、PR-GOV-02/06（P0）、PR-BIZ-02/06（P0/P1，仅追溯契约部分） |
| 代码基线 | HEAD `x-画面更新` 分支；下述行号与函数名以 2026-10-01 工作区为准 |
| 本文性质 | 冻结「记录什么、什么状态、在哪个钩子写」三件事；§1—§11 为实现前冻结的契约，§12 为实现与验收记录。不含业务快照/价格版本 |

## 0. 一句话目标

把「谁在哪个 Run、对哪个工具调用、在何时、做了什么控制决定，以及该决定是否真的生效」
变成可查询、可恢复、可幂等的**业务事实**，而不是只活在内存与 SSE 里的即时事件。

## 1. 范围与不做什么

**做**：

- 一次控制动作一条持久记录（`steer` 与 `approval` 两类），覆盖「收到 → 排队/待审 → 生效 / 未生效」。
- 刷新/断线后可重建**待处理**状态（当前 `approval_requested` 是 live-only）。
- 已被采用的 steer 文本进入**后续 Run** 的历史输入（报告 F21 验收句「下一轮历史」）。

**不做**（写清边界，避免范围膨胀）：

- 不实现跨 Run 的审批规则库：`persist` 决策维持现状语义（仅在本次 Run 内生效），只把「范围=本 Run」如实记录并修正文案（报告 §F21 禁止扩大既有授权）。
- 不实现 PR-BIZ-02/04 的业务快照、价格版本、资金事实库 —— 那是[业务需求](../../docs/design/web-business-data-prd.md)待建设能力；本项只保证「用户说过什么」可追溯。
- 不改注入时机语义：steer 仍在「有工具调用的轮次结束」边界注入（`SteerObserver.on_turn_end`）。**只要求把「未被注入」如实记录为未生效**，不改成"任何轮次边界都注入"。
- 不把控制记录写进 JSONL 轨迹、不新增第二份事件真源（PR-GOV-02）：轨迹仍是过程回放真源，控制记录是业务事实，只经 HTTP 查询，不经 SSE 重放。
- 不做多 API 进程的跨进程控制（F15 已限制单进程验证口径，本项沿用）。

## 2. 现状（当前控制链路与缺口）

```text
steer:    POST /api/runs/{id}/steer → Orchestrator.steer (orchestrator.py:315)
            ├─ stdin {"action":"steer"} → worker._stdin_watch (worker.py:143)
            │    → SteerInbox.enqueue → SteerObserver.on_turn_end (steer.py:58)
            │        └─ 仅当本回合有 tool_calls 才 drain 并 inject_messages
            └─ handle.steer_seq += 1 → SSE steer_queued（仅内存）

approval: POST /api/runs/{id}/approve → Orchestrator.approve (orchestrator.py:351)
            └─ stdin {"action":"approve"} → ApprovalGate.resolve (approval.py:107)
                 → ApprovalObserver 发 approval_requested / approval_resolved
                 → worker live_events → stdout event 帧 → Orchestrator._publish（仅内存）
```

| # | 缺口 | 位置 |
|---|---|---|
| G1 | 控制动作零持久化：`steer_queued` / `approval_requested` / `approval_resolved` 只 fan-out 到 SSE，DB 无痕 | `orchestrator.py:337`、`approval.py:192` |
| G2 | 「收到但无 worker」（HTTP 409）也零留痕 | `routes/runs.py:382`、`orchestrator.steer` 返回 `None` |
| G3 | **静默丢弃**：注入只在"有工具调用的轮次结束"发生，纯文本收尾轮排队的 steer 永远不会被 drain，也没有任何状态说明它没生效 | `steer.py:58` |
| G4 | 审批状态是 live-only：刷新页面后 `pendingApproval` 为空，无恢复来源 | `web/src/stores/runs.ts:291` |
| G5 | 已生效的 steer 文本从不进入 `turns`，下一轮 Run 的历史（`_turns_as_of_submission`，`orchestrator.py:93`）看不到用户的纠正 | `orchestrator.py:560` `_spawn` |

## 3. 记录字段

新增一张表 `control_records`（Alembic `0004_control_records`）。**单一表、两种 kind**：
两者共享「谁/何时/哪个 Run/什么状态」骨架，差异集中在 `request_json` 与决策列。

| 列 | 类型 | 空 | 说明 |
|---|---|---|---|
| `id` | UUID (pk) | 否 | 服务端生成的 control id，客户端可见（用于幂等与查询） |
| `run_id` | FK `runs.id` | 否 | 控制动作所属 Run；同时确定所有者（经 `runs.user_id`） |
| `session_id` | FK `sessions.id` | 否 | 服务端从 run 行派生（**绝不取自请求体**）；为 §7 按会话取已采用 steer 而反规范化 |
| `user_id` | FK `users.id` | 否 | 动作人，服务端从 JWT 绑定（PR-BIZ-04：所有者由服务端绑定） |
| `kind` | String | 否 | `steer` \| `approval` |
| `external_id` | String | 是 | `approval` 用 worker 的 `approval_id`（`approval.py:87` 的 uuid4 hex）；`steer` 为 NULL |
| `status` | String | 否 | §4 状态机；合法取值按 kind 区分 |
| `request_json` | JSON | 是 | **已脱敏**的请求事实。`steer` → `{"message": "<redacted>"}`；`approval` → `{"tool_name","target","reason","preview","risk"}`（`approval.py:192` 的字段子集） |
| `decision` | String | 是 | `approval` 专用：`once` \| `reject` \| `session_bash` \| `session_all` \| `persist` |
| `replacement_command` | Text | 是 | `approval` 专用，脱敏后存（拒绝时的替代指令，`approval.py:48`） |
| `resolved_at` | DateTime(tz) | 是 | 进入终态的时刻（含超时/收口） |
| `adopted_turn_seq` | Integer | 是 | 实际生效位置：steer 注入轮次对应的 `turns.seq`（去重与「生效在哪一轮」的答案） |
| `detail_json` | JSON | 是 | 补充事实：`{"gate_timeout_s":300}`、`{"closed_by":"run_finished"}`、`{"http":"409"}` 等 |
| `created_at` | DateTime(tz) | 否 | server_default now() |
| `updated_at` | DateTime(tz) | 否 | 同 store 既有风格 |

约束与索引：

- `UniqueConstraint("kind", "external_id")` —— 审批决策可幂等重复投递（NULL 在 PG/SQLite 中互不冲突，`steer` 不受影响）。
- 索引：`(run_id)`、`(session_id, status)`。
- 外键行为沿用 F16 口径（先不加 `ON DELETE`，删除语义待 T6 第 2/3 步定）。

**为什么不复用 `audit_log`**：`audit_log` 是账号/密钥类安全审计（`store.py:321` 的 docstring 明确列举 register/login/…），
控制记录是**用户内容 + 状态机**，需要按 Run 查询、需要终态收口、需要脱敏正文；
混入会让两类语义都不清楚。二者关系：本项**不**要求同时写 `audit_log`（保持审计表不膨胀）。

**为什么 worker 不写库**：`server/worker.py` 目前不 import `server.store`（已核），
DB 写入全部由父进程（API 进程）承担。本契约维持该分层：worker 只发控制帧，父进程落库。

## 4. 状态机

`status` 一列，按 kind 取不同值域。

### 4.1 `steer`

```text
                 ┌─(无 live worker, HTTP 409)→ undelivered ─┐
收到 POST ───────┤                                          ├→ 终态
                 └─(stdin 写入成功)→ queued ────────────────┤
                                          │                │
                                          ├─(轮次边界真正注入)→ adopted  ← 终态
                                          └─(Run 终止时仍未注入)→ dropped ← 终态
```

| 状态 | 含义 | 写入时机 |
|---|---|---|
| `undelivered` | 收到但无 live worker，未投递 | `routes/runs.py::run_steer` 得到 `None` 时（先落记录再返回 409） |
| `queued` | 已投递给 worker，等待轮次边界 | `Orchestrator.steer` stdin 写成功后 |
| `adopted` | 已在某轮次边界注入，记 `adopted_turn_seq` | worker 发 `control_applied`（新增帧）→ 父进程落库 + 写 turn（§7） |
| `dropped` | 已投递但 Run 终止前未被注入 | Run 终态收口（`_persist_run_result` / `_finalize`），`detail_json.closed_by` 记原因 |

### 4.2 `approval`

```text
(worker 发出 approval_requested 帧) → pending
                                        ├─(用户批准 once/session_*/persist)→ adopted
                                        ├─(用户拒绝，含替代指令)───────────→ rejected
                                        ├─(gate 300s 超时 fail-closed)────→ expired
                                        └─(停止/worker 死亡，仍有待审)────→ abandoned
```

| 状态 | 含义 | 写入时机 |
|---|---|---|
| `pending` | 待用户决定；**是刷新恢复的唯一依据** | 父进程收到 `event` 帧 `type="approval_requested"`（`_pump_frames`，`orchestrator.py:758`） |
| `adopted` | 用户批准且该工具调用按此决定执行 | 父进程收到 `approval_resolved` 帧，`decision != "reject"` |
| `rejected` | 用户拒绝（可带 `replacement_command`） | 同上，`decision == "reject"` 且由用户提交 |
| `expired` | 超时 fail-closed（内部 decision 也是 `reject`） | `detail_json.timeout_s` 有值 / 决策到达时已超时；**必须与用户拒绝区分** |
| `abandoned` | 停止或 worker 死亡时仍在待审（`reject_pending()`，`approval.py:128`） | 停止路径与 Run 终态收口 |

### 4.3 跨 kind 规则

1. **幂等**：`(kind, external_id)` 唯一；同一 `approval_id` 的决策重复到达时**不新增记录、不重复进入终态**（调用方得到既有状态）。
   `steer` 无客户端幂等键：每次 POST 落一条，重试即两条（如实记录，不猜配 —— 与 F04 的"不强行猜配"同口径）。
2. **只前进**：状态一旦进入终态不再回退；`queued`/`pending` 是仅有的非终态。
3. **收口责任在父进程**：Run 终态时，该 run 所有非终态记录一律收口（`steer→dropped`、`approval→abandoned`），
   与 F15 的"终态落账必须可检测、可重试、可恢复"一致；被孤儿扫描（`reconcile_orphan_runs`）收口的 Run 同样适用。
4. **不做时序推断**：`adopted` 必须由**实际生效**的事件驱动，绝不由"已批准/已排队"推定。

## 5. 接入点（逐文件）

| 文件 | 改动 | 说明 |
|---|---|---|
| `server/store.py` | 新增 `ControlRecord` 模型与帮助函数：`create_control` / `resolve_control` / `record_steer_adopted` / `list_controls(session_id, status?)` / `close_open_controls(run_id, status)` | 唯一落库点；全部调用方在父进程 |
| `server/alembic/versions/0004_control_records.py` | 建表 + 唯一约束 + 索引 | 与 `0003_turn_seq_unique` 一并 `alembic upgrade head`（`create_all` 不升级已有表） |
| `server/routes/runs.py` | ① `run_steer`：落 `queued` / `undelivered`；② `run_approve`：**不**按请求体记事实（只转发，事实以 worker 帧为准），返回体附 `control_id`；③ 新增 `GET /api/runs/{run_id}/controls?kind=&status=`（先 `_run_visible`，跨用户 404） | 路由层只做准入与投影，不推断状态 |
| `server/orchestrator.py` | ① `steer()`：stdin 写成功后 `create_control(status="queued")`，并把它广播给 SSE；② `_pump_frames`：`approval_requested` → `pending`；`approval_resolved` → 终态；`control_applied` → `adopted` + 写 turn；③ 终态收口（`_persist_run_result`/`_finalize` 内）| 事件 → 记录的唯一转换层 |
| `server/worker.py` | ① stdin 报文增 `control_id`；② `SteerInbox` 存 `(control_id, text)`；③ `SteerObserver` 注入成功即 `_frame("control_applied", kind="steer", control_id=..., turn_index=...)`；④ **不新增 DB 依赖** | 只把"真的注入过"这一点报上去 |
| `server/events.py` | 把 `steer_queued` / `approval_requested` / `approval_resolved` 登记进 `EVENT_TYPES`（现为裸字符串），新增 `steer_applied` | PR-RUN-04 要求界面区分"已排队 / 已在下一边界生效" |
| `web/src/types.ts`、`stores/runs.ts` | 处理 `steer_applied`；刷新时用 `GET /controls?status=pending` 重建 `pendingApproval`（G4） | F09 遗留的"live-only 状态刷新后可恢复"由此闭合 |
| `server/relay.py` | **不改**：控制记录不进 JSONL、不作为 replay 源 | PR-GOV-02 边界 |

## 6. HTTP / SSE 契约（最小面）

- `POST /api/runs/{id}/steer` → 现返回 `{"run_id","queued":true,"seq"}`，**新增 `control_id`**；409 时响应体附 `control_id`（已留痕）。
- `POST /api/runs/{id}/approve` → 现返回 `{"run_id","approved":true}`，**新增 `control_id`**。
- `GET /api/runs/{id}/controls` → `{"controls":[{...}]}`，字段为 §3 列的子集（`request_json` 已脱敏）；
  未终结的记录按 `created_at` 升序，终态记录附 `resolved_at`。
- SSE 新增 `steer_applied`：`{type, ts, control_id, steer_seq, turn_index}`，**必须加入 `web/src/sse.ts::CONTROL_EVENT_TYPES`**（否则会推进轨迹游标，重演 F09 缺陷）。

## 7. 下一轮历史如何看到用户的纠正

**选定方案 A：生效的 steer 由父进程写成一条 `turns` 行。**

- 时机：收到 `control_applied` 帧后 —— 只有真的注入过才写。
- 形态：`role="user"`，`content` 带稳定前缀 `[运行中补充方向] `（UI 可据此渲染为"纠正"而非新提问），`run_id=本次 Run`。
- 去重：以 `control_records.adopted_turn_seq` 为准；帧重复到达不得写第二条（F15 的重复终态教训）。
- 截止点：**不需要改 `_turns_as_of_submission`**。steer turn 排在本 Run 自己的 user turn 之后，
  故对本 Run 被排除（本 Run 已通过注入看到），对后续 Run 自动纳入 —— 与 F14 的提交时刻截断天然一致。

**为什么不用方案 B（在 `orchestrator._spawn` 里 join `control_records` 拼历史）**：
`history.py` 的 docstring 明确"唯一喂给下一个 Run 的是渲染后的历史"，join 会造出 turn 之外的第二种历史真源，
且 F14 的截断逻辑要写第二遍 —— 正是 F14 已经踩过的坑。

**硬规则**：`undelivered` / `queued` / `dropped` 的 steer 文本**绝不**进入任何后续 Run 的历史
（否则等于把用户从未生效的话当成既成事实 —— 与 F21 的"不伪造"原则一致）。

## 8. 脱敏与权限

- 写入前一律 `redact_deep`（`server/bridge.py`，与 SSE 出口**同一个函数**）；`request_json`、`replacement_command` 都要过。
- 正文按用户自身数据对待（PR-GOV-06）：`GET /controls` 先做 `_run_visible`，非所有者一律 404（与 stop/steer/approve 同口径）。
- 不记录 IP、令牌、完整环境变量；`approval` 的 `preview` 沿用 `approval.py:190` 的取值（命令文本，落库前再脱敏一次）。
- 控制记录**不**接受客户端提交的 `user_id` / `session_id`（服务端派生），避免重演 F08/F16 的归属不一致。

## 9. 需要拍板的 3 个决策点（已于 2026-10-01 按建议口径执行）

| # | 决策 | 选项 | 决定 |
|---|---|---|---|
| D1 | `persist` 的真实语义 | (a) 只如实记录"范围=本 Run"并修正文案；(b) 同期实现跨 Run 规则库 | **(a)**。报告禁止扩大既有授权；跨 Run 规则库应另立需求 |
| D2 | 生效 steer 是否写成 `turns`（方案 A） | (a) 写 turn + 前缀标记；(b) 不写 turn、仅在 orchestrator 拼历史；(c) 写 turn 但不加标记 | **(a)**：单一历史真源 + 截止点复用 F14 |
| D3 | 刷新/重启后的待审批语义 | (a) worker 仍活 → 可继续审批，worker 已死 → 显示"已因重启失效"；(b) 一律只读展示 | **(a)**，与 F15「终态可检测」一致 |

## 10. 验收（隔离 SQLite/ASGI + 合成用户，逐条对应报告 F21 验收句）

| # | 场景 | 断言 | 负向对照 |
|---|---|---|---|
| A1 | 断线前后 | 断流重连后 `GET /controls` 仍见记录与状态 | — |
| A2 | **未采用即结束**（G3） | 纯文本收尾轮的 steer → `dropped`，`detail_json.closed_by` 有值 | 去掉收口 → 永远停在 `queued` |
| A3 | 无 worker 提交（G2） | 409 且库中有 `undelivered` 记录 | 不在 409 分支落库 → 断言失败 |
| A4 | 审批超时 | `expired`，**不**写成用户 `rejected` | 把超时并入 rejected → 断言失败 |
| A5 | 停止/重启时待审 | `abandoned`；父进程重启后 `pending` 不复存在 | 取消收口 → 残留 `pending` |
| A6 | 下一轮历史 | Run A 的 `adopted` steer 文本出现在 Run B 的历史输入；`dropped` 的不出现 | 去掉 `control_applied` → B 看不到纠正 |
| A7 | 幂等 | 同一 `approval_id` 重复决策 → 单条记录、单次终态 | 去掉唯一约束 → 两条 |
| A8 | 权限 | 用户 B 读 A 的 controls → 404 且零副作用 | 去掉 `_run_visible` → 200 |
| A9 | 脱敏 | 含合成密钥的 steer 文本，落库与返回均已脱敏 | 绕过 `redact_deep` → 原文可见 |
| A10 | 前端游标 | `steer_applied` 不推进轨迹游标 | 不加进 `CONTROL_EVENT_TYPES` → 游标跳行 |

回归：`tests/` 现有 F14/F15/F16 用例、共享 observer 回归、`npm run test` + `vue-tsc --noEmit` + `vite build`。
部署注意：新表经 `0004_control_records` 下发，现有库需 `alembic upgrade head`（与 `0003` 合并为一次升级）。

## 11. 与既有修复项的边界

| 项 | 关系 |
|---|---|
| F14 提交截止点 | §7 复用，不修改其逻辑 |
| F15 终态落账/幂等 | 非终态记录随 Run 终态收口；幂等约束同源 |
| F16 外键与唯一约束 | 新表沿用 `PRAGMA foreign_keys=ON` 与唯一索引策略；迁移前仍须确认无孤儿 |
| F09 前端游标 | 新事件必须登记进 `CONTROL_EVENT_TYPES`，否则重演游标跳行 |
| PR-GOV-02 单一真源 | 控制记录是业务事实、非事件副本；不进 JSONL、不做 replay |

## 12. 实现与验收记录（2026-10-01）

### 12.1 实现清单

| 位置 | 内容 |
|---|---|
| `server/store.py` | `ControlRecord` 模型 + `control_*` / `create_control` / `get_control` / `get_control_by_external_id` / `list_controls` / `resolve_control` / `close_open_controls` / `control_to_dict`；状态常量与 `control_is_open` |
| `server/alembic/versions/0004_control_records.py` | 建表 + `uq_control_records_kind_external` + 两个索引；**现有库需 `alembic upgrade head`**（与 `0003` 合并为一次升级） |
| `server/routes/runs.py` | `run_steer` 先落 `queued`（失败降级 `undelivered`，均回传 `control_id`）；`run_approve` 回传 `control_id`；新增 `GET /api/runs/{id}/controls?kind=&status=`（先 `_run_visible`）。三处落库均为 best-effort，记账失败不影响用户动作 |
| `server/orchestrator.py` | `steer(..., control_id=)`；`_pump_frames` 处理 `approval_requested`/`approval_resolved` 事件帧与 `control_applied` 帧；`_approval_status`；`_record_steer_adopted`（写 turn + 标记 adopted + 广播 `steer_applied`）；`_close_control_records`（`_spawn` 收尾与 `reconcile_orphan_runs` 两处调用） |
| `server/worker.py` | stdin 的 `control_id` 透传；`SteerObserver(on_adopted=…)` → `control_applied` 帧（**worker 仍不 import `server.store`**，落库全在父进程） |
| `server/steer.py` | `SteerLine(control_id, text)`；`drain()` 保持返回文本（兼容既有调用），新增 `drain_lines()`；`SteerObserver.on_adopted` 仅在真正注入时回调 |
| `server/approval.py` | `ApprovalDecision.source`（`user`/`timeout`/`stopped`/`unknown`）；`approval_resolved` 事件增加 `source` 与 `replacement_command`（附加字段，既有消费者不受影响） |
| `server/events.py` | 四个控制事件登记进 `EVENT_TYPES`/`EventType`；新增 `steer_applied` |
| `server/history.py` | `STEER_TURN_PREFIX = "[运行中补充方向] "` |
| `web/src/sse.ts` | `steer_applied` 加入 `CONTROL_EVENT_TYPES`（不推进游标） |
| `web/src/api/index.ts`、`types.ts`、`utils/approval.ts`、`stores/runs.ts`、`components/RunStage.vue` | `runs.controls()`；`RunControlRecord(s)` 类型；`approvalRequestFromRecord()`；`steerApplied` 计数 + `loadPendingApproval()`（带 F11 代次守卫）；状态栏显示「插话已生效 N」 |
| `web/src/components/ApprovalDialog.vue`、`ApprovalCard.vue` | D1 文案修正：`persist` 按钮原写「保存为永久规则」、`session_all` 原写「本次会话内允许」，而 `ApprovalGate` 实际只在**本次 Run 内**记住（`approval.py` §6.1 明示本发行版无跨 Run 规则库）→ 改为「本次运行内始终允许」/「本次运行内允许」 |

### 12.2 验收结果

| 验证 | 结果 |
|---|---|
| `tests/test_web_f21_control_history.py`（A1—A9 契约） | **14/14 通过** |
| 负向对照（临时去掉 `_approval_status` 的 source 分支、`resolve_control` 的终态守卫、`close_open_controls` 的 steer 分支） | **4 条失败**，确认判据非空 |
| `tests/test_web_p3_steer.py`（含真实 worker e2e：steer 注入后记录为 `adopted` 且 turn 落库） | **12/12 通过**（修复前 9/12：3 条 `test_steer_route_*` 因 fixture 缺 session 父行在 F16 后报错，已补 `ensure_session`） |
| 隔离审计契约 `audit/run_audit.py` | **24/24 通过**（另修复该夹具中随 F01 失效的 `uploads_root` 一行；报告 `audit/f21-recheck-results.json`） |
| 后端相关回归（分批实跑，未跑全量套件——全量在本机有既有挂起） | `f05`/`f06`/`f09`/`orphan_reconcile`/`history_t26` 与本项合计 **57 通过**；`test_web_p3_steer` **12 通过**；`test_web_p3_approval` **27 通过 / 1 失败**；`sessions_t27`/`pagination`/`auth_t22`/`llm_config_t23`/`startup_secrets`/`upload_t210` **86 通过 / 1 失败**；`test_stop_t28` **1 通过 / 1 失败**。3 处失败均为既有限制（§12.3） |
| 前端 `npm run test` / `vue-tsc --noEmit` / `vite build` | 70/70 / 0 错误 / 构建通过 |
| `audit/frontend-audit.mjs`（F21 ×5） | **10/10 通过**；负向对照（移除 `steer_applied` 登记、移除代次守卫）两项均失败 |
| `ruff`（CI 范围含 `server/`） | 通过（另修 `server/trajectory_status.py` 一处既有 SIM105） |

### 12.3 未完成（不得视为已验收）

- **真实部署迁移**：新表尚未在业务库 `apodex` 上执行 `alembic upgrade head`（`0003` 亦未应用）；本轮全部验证在隔离 SQLite/ASGI 与临时目录内完成，业务库未触碰。
- **浏览器端 DOM 验收**：刷新后重建待审批弹窗、`插话已生效` 的界面呈现，仅在 store 层与审计脚本中断言，未做真实浏览器复核。
- **多进程/重启下的控制记录**：`reconcile_orphan_runs` 收口的用例为隔离直调，未做真实"重启后再观测"。
- 两处与本次无关的既有限制（同为**本机 Windows 环境**问题，见[环境方案 §2.2](../../docs/plan/web-storage-validation-environment.md)）：`test_approval_end_to_end`、`test_upload_t210` 断言 `create_file` 产物落盘，本机 shell/文件工具不可用；`test_stop_t28::test_sigkill_recovers_stopped_run` 依赖 `signal.SIGKILL`（Windows 无此常量）。三者均需 POSIX 环境复验。
- `uv run pyright` 在 `server/orchestrator.py:296` 报 1 处**既有**类型错误（`_session_queues` 的元素类型与 `_drain_session` 形参不一致），不在本次改动行上，未修（属字段标注取舍）。
- PR-BIZ-02 的真实资金/价格事实库、D1 的跨 Run `persist` 规则仍不做——本项只保证"用户说过什么、是否生效"可追溯。
