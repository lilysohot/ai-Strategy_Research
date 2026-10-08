# 04 Agent 主动补数触发与字段集合

Type: task
Status: resolved
Blocked by: 02
Labels: ready-for-human

## 目标

- Agent 识别研究标的后、准备给出价位/仓位结论且必填项缺失时创建补数请求；材料阅读不触发。
- 字段由服务端按用途推导；无主账户时带账户创建引导；同一 Run 不重复建请求。

## 结论：按方案 A 实施（2026-10-08 用户裁决）

worker 只表达**最小意图**，落库由持库凭据的 API 侧完成；worker 不写库、不指定 owner 与字段。

## 实现（2026-10-08）

- **worker 侧**
  - 新增 `plugins/tools/investment_input_request.py`：`request_investment_input(use_case, reason)`
    只把意图写入进程内可变槽（ContextVar 持 dict，与 `_METRICS` 同模式，跨子任务可见）；
    用途限 `plan_analysis`/`holding_cost`，非业务 Run 未绑定槽时不产生请求。
  - `server/worker.py`：业务 Run 启动时 `bind_input_intent()`；收尾 `_finalize_input_intent()`
    把意图原子写到 Run 目录 `input-request.json`（`schema_version=input-request/1`）。
  - 白名单与 profile：`plugins/tools/__init__.py`、`server/profile.py`（业务 Run 可见 + 策略文案
    要求"缺料时调一次、不要编数值、纯阅读不要请求"）。
- **API 侧**
  - `server/input_requests.py::materialize_worker_intent(session, run_id)`：读意图 → 取该 Run
    冻结快照 → 按**意图用途**（覆盖快照用途）用 `snapshots.resolve_for_run` 裁决 →
    `PurposeRequirementError.fields` 归一化后 `create_request`（幂等键 `worker-intent:<run_id>`）→
    来源 Run 置 `stopped/input_required`；无意图/无快照/字段齐全时返回 None。
  - `create_request` 新增 `enforce_snapshot_use_case: bool = True`；续接 Run 的 `use_case` 取
    **本次请求的用途**（Agent 识别出按新用途给结论时，快照用途可能更早）。
  - `server/orchestrator.py`：`_persist_run_result` 落终态前调用 `_materialize_input_intent`
    （best-effort，失败不影响终态；先建请求 → Run 被置 input_required → `update_run_result`
    防复活分支保留该原因）。

## 验收

- 新增 `tests/pg/test_worker_input_intent.py`（2 项）：意图落库一次且幂等（重复调用不产生第二条）、
  用途取自意图、字段由服务端推导（含 `plan.allocated_capital`）、`source_run_id` 关联、
  来源 Run 终态为 `stopped/input_required`；无意图时零请求。
- 全套 `tests/pg`：**214 passed**；Ruff 本批文件 0 错误；import smoke 387/387；
  symbol closure 485 文件 0 缺失。证据：`evidence/04-pg.log`。

## 未覆盖（登记缺口，不放行）

1. **真实 worker 子进程端到端未验**：没有用真实 worker + mock 模型"真的调用该工具"跑完整链路；
   当前只验证了工具/意图文件的纯逻辑与 API 侧落库，`request_investment_input → 文件 → 落库`
   尚未在子进程内贯通验证。
2. **收尾路径接线**（2026-10-08 补做，已收口）：三条路径统一到 `_materialize_input_intent`
   —— 正常帧与兜底 `summary.json` 都走 `_persist_run_result`（后者由 `_synthesize_terminal_frame`
   复用），`_recover_finished_run` 已补调用。全套 `tests/pg` **214 passed**（含既有孤儿恢复回归），
   Ruff 本批 0 错误，import smoke 387/387。
   **仍缺**：专门覆盖"恢复时存在意图 → 补建请求"的用例（当前只验证了函数幂等与正常路径）。
3. 无主账户时"引导创建账户"的提示语未实现（当前仅按用途推导字段）。
