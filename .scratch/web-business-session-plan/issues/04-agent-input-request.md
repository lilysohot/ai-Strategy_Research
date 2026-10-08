# 04 Agent 主动补数触发与字段集合

Type: task
Status: open
Blocked by: 02
Labels: needs-info

## 目标

- Agent 识别研究标的后、准备给出价位/仓位结论且必填项缺失时，创建补数请求，复用
  `input_requests.create_request`；模型不能指定 owner 或研究以外的对象。
- 材料阅读不触发。
- 字段集合：规划资金（必需）+ 承受风险 + 期望盈利（可后补），单位与币种按契约。
- 无主账户时请求带账户创建引导；无来源 Run 沿用 continuation。
- 触发幂等：同一 Run 内不重复建同用途请求。

## 落点（初判）

`server/input_requests.py`、`plugins/tools/`、`server/worker.py`、`tests/pg/test_input_requests.py`

## Comments

2026-10-08 核查发现（阻塞原因，需决策）：

1. **worker 无法直接写库**。业务工具跑在 worker 子进程；DATA-08 明确 worker 只拿该 Run 的最小
   上下文并隔离平台数据库 DSN（`server/worker.py` 将 `SERVER_DATABASE_URL` 置为私有内存库、
   移除 Docker DSN）。因此“Agent 工具直接调用 `create_request`”在当前架构下不成立。
2. **上下文缺 `user_id`**。绑定给工具的 Run 上下文（`server/investment_context.py`）含
   `run_id`/`research_id`/`use_case`/`values`，**不含 owner**；而 `create_request` 需要
   `user_id` 与数据库会话。owner 也不允许由模型或请求体决定（契约 §1.4）。
3. 结论：需要一条 **worker → API 的补数意图通道**，由持库凭据的 API 侧落库，而不是在 worker 内写库。

## 候选取向（待用户裁决后实施）

| 取向 | 做法 | 代价 |
|---|---|---|
| A（推荐） | worker 在 Run 目录写结构化意图 sidecar（`use_case`/`fields`/`reason`/`account_missing`），Run 以 `input_required` 结束时由 API 侧终态收尾逻辑读取并创建 `input_request`（复用 DATA-12 事件）；旧 Run 语义不变 | 需定义意图文件契约与「领取/幂等」边界；不新增网络通道 |
| B | worker 经 loopback HTTP + 服务令牌回调 API 创建请求 | 引入 worker→API 鉴权与失败重试；与最小权限原则冲突面更大 |

## 未完成

- 工具/通道均未实施；字段集合与幂等规则未落到代码。
- 05 前端弹窗依赖本项确定的接口形态，故一并顺延。
