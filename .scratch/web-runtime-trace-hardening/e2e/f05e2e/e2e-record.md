# F05 / F06 / F21 浏览器 DOM 层验收记录

Date: 2026-10-01
Scope: 报告 §8「仍未完成」中三个纯前端页面验收项（F05 历史轨迹页、F06 完整性告警、F21 待审批弹窗与插话呈现）
Isolation: 全部流量指向隔离栈；未触碰 8000 真实 API / PG 业务库 / WSL 部署

## 环境与隔离证明

| 项 | 值 |
|---|---|
| 被测代码 | Windows 工作区（含本次 `RunDetailView.vue` 渲染修复，见下） |
| mock LLM | `deploy.huggingface.mock_llm --port 8018 --no-auth`（F05/F06 阶段纯文本；F21 阶段切换为 `.scratch/.../f05e2e/mock_llm_approval.py`：`create_file` confirm 级脚本） |
| API | `uvicorn server.app:app --port 8471`，`SERVER_DATABASE_URL=sqlite+aiosqlite:///C:/Users/Administrator/AppData/Local/Temp/f05e2e/e2e.db`，`SERVER_RUNS_ROOT=C:/Users/Administrator/AppData/Local/Temp/f05e2e/runs`，独立 `SERVER_MASTER_KEY`/`SERVER_JWT_SECRET`，`SERVER_DEBUG=1` |
| 前端 | vite `--port 5273 --strictPort`，`VITE_API_PROXY=http://127.0.0.1:8471` |
| 浏览器 | Playwright CLI 0.1.22 + 系统 Edge（channel msedge），登录用户 `f05e2e`（仅存在于隔离库） |
| 隔离证明 | 全部 Run 落盘于 `%TEMP%\f05e2e\runs\`；测试数据构造文件 `craft_trace.py` 只写隔离运行根 |
| 健康探针实测 | 用错驱动名（`sqlite:///`）启动时 `/healthz`、`/readyz` 均 503（`database_unavailable`）；改为 `sqlite+aiosqlite:///` 后 200 —— 顺带在真实进程复核了 F19 门禁行为 |

## 发现并修复的缺陷：已结束 Run 的轨迹时间线完全不渲染

**现象**：打开历史 Run 的「轨迹」页，只显示「运行目录」元信息框，`0` 条记录、无空态说明；
但页面内 `GET /api/runs/{id}/trace` 返回 10 条记录且 `completeness=complete`。

**根因**：`RunDetailView.vue` 模板中 `run-detail__meta`（运行目录/失败原因）是
`v-if` 链头，`el-empty` 是 `v-else-if`，时间线 `timeline` 是 `v-else` —— 只要
`runStream.runDir` 或 `errorMessage` 有值（reconcile 对每个已结束 Run 都会填 `runDir`），
时间线分支即不可达。

**修复**：`el-empty` 改为独立 `v-if="!loading && !hasContent"`，meta 块脱离条件链，
并加注释说明原因。回归：`vue-tsc --noEmit` 0 错误、`npm run test` 70/70、
修复后真实浏览器中 10 条记录全部渲染。
（该缺陷由本次浏览器层验收发现，正是 F05 工单「未做 DOM 验证」所担心的类型。）

## F05 验收结果（Run 8225c4bd，构造 `full` 轨迹：10 条记录）

| 场景 | 断言 | 结果 |
|---|---|---|
| 时间线渲染 | `.tl-item` = 10（meta 与时间线并存） | ✅ |
| 散文推理折叠 | `.tl-thinking` `<details>` 默认收起；summary 可聚焦、Enter 切换 open；展开后正文为逐字原文 | ✅ |
| 无推理字段 | 「该轮未记录可见推理」 | ✅ |
| 空推理 | 「该轮记录了空的推理」 | ✅ |
| 仅加密签名块 | 「该轮仅有加密/签名推理块（用于协议回放），不可作为可读推理展示」，不伪造散文 | ✅ |
| 300 字符截断 | 长结果（2343 字符）首屏 `pre` 恰 300 字符，`【关键错误】`（第 301+ 字符）首屏不可见 | ✅ |
| 继续读取 | 按钮「继续读取（还有 2043 字符，共 2343 字符）」→ 解锁后错误文本可达 → 读满后按钮消失、长度恰等于总数 | ✅ |
| 多字节边界 | 299×A + 😀 + 50×B：预览恰好 300 个 code point（301 个 UTF-16 单位），无 U+FFFD，😀 完整 | ✅ |
| 短结果 | 无「继续读取」按钮 | ✅ |
| 完整性告警（complete） | 无 warning alert | ✅ |

刷新/切研究场景说明：刷新后 `runStream.runId` 归零且 UI 无重开历史 Run 的入口
（见 F21 缺口同源问题），「刷新后一致」以切换 Run（runId 变化触发重载 + 展开状态重置，
见下）与重新拉取 `/trace` 验证；「刷新后重新打开历史 Run」受同一 UI 缺口影响，已如实记录。

## F06 验收结果

| 场景 | 断言 | 结果 |
|---|---|---|
| partial（Run e7dbbfb8，去掉 end 终止行） | warning alert 文案 = 服务端 reason「运行未正常结束，已保存的记录可读，但可能缺少最后一部分内容」；9 条记录仍全部可读（告警在记录旁，不替代记录） | ✅ |
| unavailable（删除轨迹文件） | warning alert「轨迹文件不存在（运行可能未产生输出）」+ 空态「暂无轨迹记录」+ 0 条记录 | ✅ |
| Run 切换重置 | 由 full→partial 切换后 `.tl-result__more` 恢复初始计数（展开状态不跨 Run 泄漏） | ✅ |

## F21 验收结果

真实审批门链路（Run d4433a01，mock 脚本 `create_file /outputs/answer.md`）：

| 场景 | 断言 | 结果 |
|---|---|---|
| live 审批弹窗 | `[data-testid=approval-dialog]`「等待你决定：create_file」、目标/原因正确、警示「当前运行时不是操作系统级沙箱」、默认聚焦「拒绝」 | ✅ |
| D1 文案修正 | 按钮为「本次运行内允许」「本次运行内始终允许」（不再写「保存为永久规则」） | ✅ |
| steer 生效呈现 | 状态栏出现「插话 1」「插话已生效 1」；消息流出现 `[运行中补充方向] 补充：产出文件标题请用中文` | ✅ |
| 控制记录持久化 | `GET /controls?kind=steer` → `adopted`；`kind=approval` → `adopted, decision=session_all` | ✅ |

**刷新恢复待审批弹窗 —— 发现实现缺口（未通过）**：

- 复现：Run 6681061f 停在审批门（弹窗在前端可见）→ 浏览器刷新 → 会话自动恢复、
  消息可见，但 **无弹窗、无「等待你决定」、无任何 Run 标识**（等待 11s 后仍无）。
- 服务端数据完好：`GET /api/runs/6681061f…/controls?kind=approval&status=pending`
  返回完整 pending 记录（tool_name/target/reason/risk 齐全）。
- 根因：`loadPendingApproval()` 只在 store 的 `watch()` 内调用，而 `watch()` 只被
  `ChatView` 的「发送消息」路径调用；刷新后 `runStream.runId` 为 null，
  且 UI 没有任何入口（消息点击/运行列表/`retry()` 需要非空 runId）能对
  「正停在审批门的运行」重新订阅 —— 恢复数据可达但前端永不消费。
- 证据截图：`f21-refresh-no-dialog.png`。
- 修复方向（供工单 21 使用）：会话恢复时识别「存在 pending 控制记录 / 运行仍活跃」
  的最新 Run 并 `runStream.watch(run_id)`；或对活跃会话在 `restoreSession` 后
  查询 pending controls 并就地重建弹窗（无需完整订阅流）。
- 该缺口同时解释了 F05「刷新后重开历史 Run」不可达：`watch()` 是唯一入口。

备注：测试八的运行最终由审批门 300s 超时 fail-closed 收口（未人工干预）。

## Console

全程页面 console 无被测功能错误（出现的 error 均为验收脚本自身注入的
401/404 探测请求）。

## 清理说明

- 隔离数据保留在 `%TEMP%\f05e2e\`（9 个 run、SQLite 库），可随时删除；
- 三个后台进程（mock 8018 / API 8471 / vite 5273）验收后应关闭；
- 启动脚本与数据构造脚本保留于本目录（`start-mock.cmd` / `start-api.cmd` /
  `start-vite.cmd` / `mock_llm_approval.py` / `craft_trace.py`），可复现本次验收。
