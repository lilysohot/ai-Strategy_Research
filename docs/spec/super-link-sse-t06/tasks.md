# SSE-T06 实施任务

| 项目 | 内容 |
|---|---|
| 规格 | [spec.md](spec.md) |
| 状态 | 已执行（2026-11-21）：A03/A04/A07/A09 通过，A05 部分覆盖（浏览器断网重连未实测），A10 代理 blocked；证据见计划 §20.12 |
| 边界 | 不改变空间事实游标/快照/预览协议；不迁移业务库；不干扰现有 8000/5173/4174 进程与共享 Redis |

## 0. 环境与边界

- [x] 向用户确认隔离 PG `apodex_biz_test`、Redis 16379、API 18000、Vite 15173、浏览器；代理先检查镜像
- [x] 确认隔离库 DSN 与迁移 head；禁止使用 `apodex`/`postgres`（仅使用 `apodex_biz_test`）
- [x] 创建并登记临时 `SERVER_RUNS_ROOT` 与测试用户（`/tmp/frontier-t06-runs`；`t06user`、`t06-user-b`）
- [x] 启动专用 Redis 容器 `127.0.0.1:16379`，确认 6379 不受影响
- [x] 确认真实模型端点与模型名可用（`.env` 端点，`deepseek-v4.1-flash`；观察到 intake 45s 超时风险）
- [ ] 代理：本地无 caddy/nginx，`caddy:2-alpine` 拉取失败；A10 标记 `blocked`
- [x] 记录启动命令、环境变量、端口与清理步骤（见 spec §2.1；收口时停止进程与容器）

## 1. 观测指标

- [x] `server/super_link/observability.py`
  - [x] `sse` 计数：opened/closed/rejected/slow_closed/auth_revoked/max_age_closed/active_total
  - [x] `preview` 计数：frames/resets/dropped
  - [x] `notifier` 计数：published/failed
  - [x] `snapshot()` 纯进程内快照，无后台任务
- [x] `stream.py` 接入连接、慢关闭、预览 reset/丢弃计数
- [x] `events.py` 接入通知成功/失败计数
- [x] `GET /api/super-link/spaces/{id}/diagnostics`
  - [x] 所有者校验与 `_enabled()` 语义
  - [x] 返回 process 计数、`events.head_seq`、`unnotified_count`、最老积压年龄
  - [x] 数据库异常 503，不返回伪造零值
- [x] `tests/test_super_link_diagnostics.py`
  - [x] 所有者可见、非所有者 404
  - [x] 关闭功能 404、数据库异常 503
  - [x] 计数在通知路径上递增
- [x] Ruff / Pyright 通过（改动文件）

## 2. 后端自动化

- [x] 隔离 PG：`tests/pg/test_super_link_events.py`、`tests/pg/test_super_link_stream.py`（8 passed；该步骤 TRUNCATE 清空隔离库运行时数据）
- [x] 定向非 PG：输出、流、事件、诊断、运行时、notifier（112 passed）
- [x] 定向非 PG：上下文继承、派发恢复（含普通 single/team、停止与连续性共 143 passed）
- [x] 定向 Ruff / Pyright
- [x] 记录命令、计数与环境（见计划 §20.12）

## 3. 真实 Worker 与输出链路

- [x] 确认真实模型端点可用，记录模型名、延迟与是否返回 reasoning（返回 reasoning；首轮 Team intake 曾 45s 超时）
- [x] Single：真实 Worker 输出，校验预览帧成员/块/序号，最终文本与 trace 一致（Run `f89cd68c8fb140b7b5c0ad4bce7a5aa7`）
- [x] Team：至少一次多成员输出，校验成员归属、交错与空间流不断（空间 2，协调者 + 2 成员，1658 帧预览）
- [x] 无 reasoning 的输出不生成思考块（映射单测覆盖；本次端点返回 reasoning，未复现实测）
- [ ] 模型错误：独立 API/Worker 指向不可达端点，运行失败与连接故障可区分（未启动不可达端点；已观察真实 intake 失败作为业务故障样本）
- [x] 记录 Run ID、模型端点、是否真实模型及未覆盖项（见计划 §20.12）

## 4. 浏览器验收

- [x] 登录隔离测试用户，创建或打开空间
- [x] 多成员实时展示与归档替换（空间 2；`agent_cards.jpg`、`final_status.jpg`）
- [x] A03：关闭/离开页面期间完成运行与交付，返回后状态准确、无重复 Run（事件 18..329 连续，无重复派发）
- [x] A04：两个标签页同时操作；重复暂停/停止与旧版本；刷新不显示假终态（捕获“正在停止”→“已停止”）
- [ ] A05 断线：刷新/断网后重连，新 epoch、归档补齐、预览不残留（仅 API 级新连接与前端单测覆盖；浏览器断网未实测）
- [ ] 审批与补充指令：提交、采纳、刷新恢复（A03 交付加载已覆盖；审批 UI 与补充指令未实操）
- [x] 记录页面状态、接口响应与诊断数值（截图 `/tmp/trae/screenshots/`，证据 JSON 在 `/tmp`）

## 5. 代理链路

- [ ] Caddy 18080 启动，`flush_interval -1`、`encode gzip zstd`
- [ ] `15173 → Caddy → API` 打开空间并建流
- [ ] 验证 `Cache-Control: no-cache`、`X-Accel-Buffering: no`
- [ ] 15 秒心跳与预览帧增量到达（记录时间戳/分片）
- [ ] 停止 API：页面显示连接故障，不显示运行失败；Caddy 行为记录
- [ ] 重启 API：重连、快照补读、无重复执行
- [x] 结论：A10 `blocked`——无本地代理、镜像拉取失败；未用简化代理冒充 Caddy/nginx

## 6. 故障注入

- [x] 慢客户端：30 秒不读，连接有界关闭并释放配额；其他客户端不受影响（4.5MB/约 16s 触发，`slow_closed=1`）
- [x] 高并发连接：每用户上限触发 429 与 `Retry-After`（8 条活跃，第 9 条 429 + `Retry-After: 5`）
- [x] Redis 停止/恢复：事实落库、通知积压、恢复补发；诊断数值变化（积压峰值 4、最老约 27.7s）
- [x] API 重启：事实与归档可读、预览清空、无重复 Run（重启前后 cursor/runs/deliveries/control 一致）
- [x] 跨用户/跨空间：快照、事件、诊断、交付均 404/401
- [x] 令牌失效或用户停用：`sl.auth_required` 并按期关闭
- [ ] 第二实例：记录首版约束与保护行为，不标为多实例通过（未启动第二实例；单所有者约束见计划 §20.12）

## 7. 普通模式回归

- [x] 普通 single：输入、流式输出、工具、产物、停止（输入/流式/停止通过；工具与产物未单独实操，依赖既有回归）
- [x] 普通 team：成员并行、汇总、停止（重试成功，含两个成员轨迹；首次 intake 超时失败记为模型风险）
- [ ] 普通审批：批准/拒绝/超时（未实操；仅相关单测覆盖）
- [x] 上下文连续性：同一普通会话追加提问可读历史（`57b98f0f...` → `b831a364...`）
- [x] `tests/test_run_modes.py`、`tests/test_context_inheritance.py`、
      `tests/test_web_dispatch_recovery.py`、相关审批/停止测试（定向 143 passed）

## 8. 前端与收口

- [x] `cd web && npm test`（170 passed）
- [x] `cd web && npm run typecheck`（通过）
- [x] `cd web && npm run build`（通过，仅 chunk 体积警告）
- [x] 汇总证据：环境、注入点、预期/实际、结果、限制（计划 §20.12）
- [x] 更新计划 §20.2 T06 状态与 §20.12 完成记录
- [x] 记录移交 T07 的部署约束、未支持边界与残留风险（计划 §20.12）
- [x] 清理：停止 T06 进程与容器，删除临时 runs 根，专用 Redis 容器整体移除（未触碰 6379）
