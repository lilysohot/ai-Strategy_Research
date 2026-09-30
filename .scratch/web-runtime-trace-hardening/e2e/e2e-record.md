# F09 浏览器 / 多进程端到端验收记录

Date: 2026-09-30
Scope: 报告 §8「F09 已知覆盖盲区」的动态验收（真实浏览器 DOM + 多进程拓扑）
Isolation: 全部流量指向隔离栈；未触碰 8000 真实 API / PG 业务库 / WSL 部署

## 环境与隔离证明

| 项 | 值 |
|---|---|
| 被测代码 | Windows 工作区（含 `Orchestrator.has_worker` + `_live_queue_for` 修复） |
| mock LLM | `deploy.huggingface.mock_llm --port 8018 --no-auth`（仅 loopback） |
| API 进程 A | `uvicorn server.app:app --port 8471`，`SERVER_DATABASE_URL=sqlite:///%TEMP%\f09-e2e2\e2e.db`，`SERVER_RUNS_ROOT=%TEMP%\f09-e2e2\runs`；监听进程身份经 `Win32_Process` 核验为本工作区 uvicorn |
| API 进程 B | 同端口、同库、同运行根、同 JWT/master key；A 被强制终止后启动 |
| 前端 | `vite --port 5273 --strictPort`，`VITE_API_PROXY=http://127.0.0.1:8471` |
| 浏览器 | Playwright CLI 0.1.22 + 系统 Edge（channel msedge） |
| 隔离证明 | 浏览器提交的 run 落盘于 `%TEMP%\f09-e2e2\runs\72c61374…`（真实 `server/runs` 无新目录）；登录账号仅存在于隔离库，经 5273 代理登录成功 |
| 端口选择说明 | 首次尝试的 8001/5174 被 IDE 端口转发代理占用并指向真实 API，导致一轮误写（见工单 09 评论 2026-09-30 条目，用户已确认无需删除）；本次改用 8471/5273 并先行验证监听进程身份与数据落点 |

## 步骤与结果

### 1. 进程 A：本进程结束 + 活流（回归）

- 浏览器注册/登录 `f09-iso` → 新建研究 → 发送「用一句话介绍你自己…」。
- run `72c613740aa44420a6c34c347ddc367b`：worker 正常启动，活流（delta）实时渲染，结束后 UI 到达终态「已停止」，不转圈。
- 行状态 `stopped`（`stopped_by=no_tool`，E1 已知的纯文本收尾归类，与 F09 无关），usage 完整（total_tokens=142）。
- 证据：`e2e-01-finished-in-process.png`

### 2. 多进程切换：结束于其它进程的 run（F09 盲区本体）

- `taskkill /F /T` 终止进程 A → 启动进程 B（同一隔离库/运行根）。
- B 侧核验：`GET /api/runs/72c61374…` 返回 `status=stopped`、`finished_at` 非空；B 无该 run 的 worker handle → 权威状态判定的前置条件成立。
- 浏览器重载页面：回答由轨迹重放渲染，UI 正常收尾。
- 协议级断言（页面内 fetch 读 `/events?after=0` 至 EOF）：

  ```json
  {"http":200, "ended_ms":19, "chunks":1, "bytes":685}
  ```

  流在 19ms 内自然结束——修复前该场景为订阅死队列、永不结束（审计基线：重放正常产出、5s 不结束）。
- 证据：`e2e-02-cross-process-replay.png`

### 3. 重启后的进程 B：新 run 活流（反向守卫的端到端面）

- 浏览器再次提交新任务：run `d93fd9418fcb435189f2a0b7c5b822b3` 活流正常、终态正常。
- 证明「无 handle 且行状态非终态（本进程新 run）」仍走订阅路径，未被误判。
- 证据：`e2e-03-live-after-restart.png`

## 结论

- F09 后端盲区（结束于其它进程 → 订阅死队列）在**真实浏览器 + 多进程拓扑**下验收通过；
- 本进程结束 / 新 run 活流两条既有路径无回归；
- 页面 console 全程 0 error。
- **工单 09 仍不关闭**：前端游标语义（`steer_seq` 被当作轨迹游标，`frontend-audit.mjs` 仍失败）未修复。

## 遗留说明

- 隔离临时数据保留在 `%TEMP%\f09-e2e2\`（两个 run、SQLite 库），可随时删除；
- 误写入真实库的测试数据（f09-e2e 用户/config/session/run/turns）经用户确认**保留不删**；
- WSL 部署（`/home/administrator/FrontierAgent`，端口 8000）**不含本修复**，其代码同步与重启由用户决定。
