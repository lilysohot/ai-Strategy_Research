# CLI 终端 → Web 端复刻方案

| 项 | 内容 |
|---|---|
| 版本 / 状态 | v1.3 · 阶段一至阶段三全部实施；回溯审计补全 2 处遗漏（终端 run 事件 + 失败原因/运行目录） |
| 上游文档 | [产品需求基线](../product-requirements.md) · [业务流程](../business-process.md) · [tech-stack.md](../tech-stack.md) · [tui-user-guide.zh-CN.md](../tui-user-guide.zh-CN.md) |
| 复刻基准 | `apodex/tui/` + `apodex/observers.py`（TerminalObserver）+ `docs/tui-user-guide.zh-CN.md` |
| 状态图例 | ✅ 已有 · ⚠️ 部分具备 · ⬜ 缺失 |

> **文档职责修正**：本文最初是方案，现作为阶段一至阶段三的实施与回溯审计记录保留。
> 当前工作台交互以 [前端交互规格](../design/investment-research-workbench-prd.md) 为准，当前产品状态以
> [产品需求基线](../product-requirements.md) 为准。

---

## 1. 目标与范围

把 CLI 终端（`apodex/`，Textual TUI）的**展示内容**与**业务流程**在 Web 端（`web/` + `server/`）等价复刻，让浏览器用户获得与终端一致的可观测性与控制力。

**复刻原则**

1. **以终端为基准，但不照搬交互形态**——终端是键盘驱动 + 分栏，Web 是鼠标驱动 + 抽屉/Tab。信息密度与语义对齐，交互形态按 Web 习惯重设计（如审批弹窗替代终端选择框，按钮替代 `y/n/m/a`）。
2. **唯一真源不变**——运行时 trajectory（`react_agent.jsonl`）仍是回放与计量的唯一真源，Web 不自建事件日志。
3. **实时性优先**——终端是进程内直连观察者，天然实时；Web 跨了一层子进程，必须先打通实时通道（§4），否则其余复刻都是"事后回放"，达不到终端体验。

**不在本次范围**

- `agent_team` 的 sub-agent 并行编排（Web 侧目前只跑 `stateful-react-agent` 单 Agent）
- 附件 `@` 补全、`/fork`、SSO 等（见 plan.md P2 清单）

---

## 2. CLI 终端能力清单（复刻基准）

来源：`docs/tui-user-guide.zh-CN.md` + `apodex/tui/` 实现。

### 2.1 界面布局

```text
┌──────────────────────────────────────────────────────────────┐
│ workflow · session · workspace                          F2  │  顶部
├─────────────────────────────────┬────────────────────────────┤
│ transcript                      │ Plan │ Activity │ Files │ Diff│
│ 用户任务 / 思考 / 工具调用 /     │                            │
│ 审批结果 / 最终报告              │ 当前 Tab 内容               │
├─────────────────────────────────┴────────────────────────────┤
│ 状态 · 耗时 · workflow · model · context · tools · queued     │  状态栏
│ 附件 | 输入框                                                 │
└──────────────────────────────────────────────────────────────┘
```

- 终端宽度 < 100 列时右侧栏自动隐藏；`Ctrl-B` 恢复。
- 状态栏字段：`阶段 · 耗时 · workflow · model · context 余量 · tools 数量 · queued 干预数 · 文件变更统计(+新增/-删除)`。

### 2.2 右侧四个 Tab

| Tab | 回答的问题 | 内容要点 |
|---|---|---|
| **Plan** | 现在要做什么、做到哪一步 | `react` 显示 todo 工具维护的步骤；`agent_team` 显示 coordinator 任务。图标区分待处理/进行中/完成/取消；标题显示 `已完成数/总数`；无计划时 `no plan yet`。**只读**，提交新任务自动回到此 Tab |
| **Activity** | 谁在做什么、工具是否成功、花了多久 | 每行：状态图标 + 名称 + 持续时间 + 摘要。状态：成功/失败/跳过/中断/运行中。`Space` 展开详情（state/duration/call ID/details）。`agent_team` 下分 `SUB-AGENTS`（queued/running/ready/failed）与 `COORDINATOR` 两组 |
| **Files** | Agent 产出了哪些文件 | 交付物列表 + 只读预览（源码/文本/Markdown/CSV/PDF/Word/Excel/PPT/Notebook/图片/压缩包/部分 3D）。顶部显示宿主机交付路径，Docker 模式另显挂载路径。单独 `Work:` 行指向中间工作目录，不混入交付列表。`final-report.md` 自动保存 |
| **Diff** | 磁盘上产生了哪些变更 | unified diff，绿 `+`/红 `-`，新建/删除用 `/dev/null` header。基线 = 会话首次触碰该文件前的内容（排除无关的脏改动）。无变更时 Tab 隐藏。标题显示变更文件数，顶部/底部显示总 `+新增/-删除` 行数 |

**Diff 的两个来源与 `/revert` 边界**（关键语义，必须复刻）：

- **第一类（显式）**：文件工具（`write_file`/`file_editor`/`delete_file`）声明了目标路径 → 直接快照 → `/revert` 可撤销。
- **第二类（扫描）**：非只读 `bash` 不声明写入目标 → 工具前后各扫一次工作目录，只保留真变化的文件。**扫描只能看出"树变了"，看不出"是谁改的"**，同时间窗内用户编辑器/watcher/dev server 的写入无法区分，一并还原会毁掉无关工作 → **只展示，不 revert，`/revert` 单独列出交人工处理**。
- 二进制与超大文件跳过（留不下可比较基线）。

### 2.3 业务流程

**一次任务的标准流程**

1. 底部输入任务 → Enter
2. Plan 看拆解与进度
3. Activity 看工具调用
4. 出现审批窗口 → 检查命令/diff → 决定
5. 需调整方向 → 底部直接输入文本 → Enter（steer）
6. 完成 → `Ctrl-G` 跳最终报告 / `Ctrl-O` 看文件
7. 继续提问，保留会话上下文与已修改 workspace

**审批窗口**（写文件或需确认的命令）

| 键 | 含义 |
|---|---|
| `y` | 仅批准这一次 |
| `n` / `Esc` | 拒绝 |
| `m` | 本会话自动批准 bash（仅 Docker/可信环境） |
| `a` | 本会话允许所有普通审批 |
| `A` | 持久记住并允许这一类命令 |
| `e` | 拒绝并输入替代指令 |
| `Ctrl-U` / `Ctrl-D` | 翻阅长命令或 diff |

- **默认选中 `No`**，避免误按 Enter 执行。
- 高风险操作不接受单键 `y`，必须完整输入 `yes`。
- Native runtime 不是 OS 沙箱，获批命令拥有当前用户权限。

**运行中的异步干预（steer）**

- 异步排队，**不终止**正在进行的 LLM 请求或工具调用。
- `react` → 交给当前 Agent；`agent_team` → 交给 coordinator（已派出的 sub-agent 不被直接打断）。
- 到达太晚（任务已结束）不丢失，作为紧接着的 follow-up 运行。
- 多条排队，指令要短且明确。
- 状态栏 `queued` 计数增加，transcript 显示 queued 提示。
- 立即停止请按 `Ctrl-C`（保存到最近一个已完成 turn），不要发"停止"。

**transcript 导航与整理**

| 操作 | 用途 |
|---|---|
| `Alt-J` / `Alt-K` | 在可见 block 间移动 |
| `Alt-Enter` | 展开/收起 thinking / process block |
| `Ctrl-G` / `/report` | 跳到最新最终报告 |
| `Ctrl-Y` / `/copy` | 复制最新最终报告 |
| `/filter thinking\|tools\|errors\|report\|all` | 过滤 transcript |
| `/find <文字>` | 搜索 transcript |
| `/compact` | 压缩较早内容 |

**会话与 workflow 命令**

```text
/attach <path>   /attachments   /detach <name>
/workflow react|agent_team      /new   /fork   /rename   /resume
/context         /config        /log   /revert
```

- 切换 workflow 会重置对话上下文，应在新任务开始前切换。
- 输入 `@` + 文件名片段可搜索附件与 `--cwd` 下文件，`Tab` 补全。
- 粘贴多行/超长文本显示紧凑 `[Pasted text …]` 标记，Enter 后一次性发送。

---

## 3. 现状差距矩阵

### 3.1 展示内容

| CLI 能力 | Web 现状 | 说明 |
|---|---|---|
| 用户消息气泡 | ✅ | `ChatView.vue` |
| 助手回答（Markdown） | ✅ | `markdown-it` + DOMPurify + 脱敏 |
| **回答逐 token 流式** | ⬜ | **核心缺失**，见 §4 |
| 思考过程 thinking | ⚠️ | 已有折叠块（`RunStep.thinking`），但非流式、依赖整轮落盘 |
| 工具调用卡片（名称/状态） | ✅ | `tool_started`/`tool_finished` 聚合 |
| 工具参数 input | ⚠️ | 事件已带 `input`，UI 未展示 |
| 工具结果 output | ⚠️ | 事件已带 `output`，UI 未展示 |
| 工具耗时 ms | ⚠️ | 事件已带 `ms`，UI 未展示 |
| **Plan / todo 看板** | ⬜ | 完全缺失（§5.2） |
| **Activity 时间线（终端式）** | ⚠️ | 只有简单工具卡片，无持续时间/摘要/状态图标/详情展开 |
| **Files 预览** | ⚠️ | `ArtifactPanel.vue` 只有列表 + 下载，无内容预览 |
| **Diff** | ⬜ | 完全缺失（§5.4） |
| 最终报告面板 | ⚠️ | 仅作为普通助手消息，无独立定位/复制（`/report`） |
| Sub-agent 状态卡 | ⬜ | 缺失（`agent_team` 未上 Web） |
| **状态栏**（context/tokens/tools/queued/耗时） | ⚠️ | 只有 run 状态标签，无 context/tokens/tools/queued |
| transcript 过滤 / 搜索 | ⬜ | 缺失（§5.5） |
| 错误 / 失败面板 | ⚠️ | 有 failed/stopped 标签，无结构化错误面板 |
| 上下文压缩提示 | ⚠️ | `compaction` 事件已映射为 warning，UI 未呈现 |

### 3.2 业务流程

| CLI 能力 | Web 现状 | 说明 |
|---|---|---|
| 提交任务 | ✅ | `POST /api/runs` |
| 停止（Ctrl-C） | ✅ | `POST /api/runs/{id}/control`，含 loading/409 |
| 多轮会话 | ✅ | `history.py` + `sessions.ts` |
| 产物下载 | ✅ | `ArtifactPanel.vue` |
| **人工审批门** | ✅ | P3.2 已落地（§6.1） |
| **运行中干预 steer** | ✅ | P3.1 已落地（§6.2） |
| **`/revert` 回退** | ✅ | P3.3 已落地，仅第一类（§6.3） |
| `/compact` | ⬜ | 缺失 |
| 会话命令（rename/fork/workflow 切换） | ⚠️ | 有 rename/新建/删除，无 fork、无 workflow 切换 |
| 附件上传 | ✅ | T2.10 已落 `inputs/` |

---

## 4. 核心架构改造：打通实时事件链路

**这是所有复刻的地基。** 终端的 `TerminalObserver` 与 Agent 循环同进程同事件循环，观察者回调直连 UI，天然逐 token 实时。Web 的 worker 是**独立子进程**，观察者队列在子进程内存里，父进程读不到——必须显式架一条跨进程实时通道。

### 4.1 当前链路与断点

```text
[worker 子进程]                          [server 父进程]              [浏览器]
agent_loop ──on_llm_delta──▶ BridgeObserver(queue=None) ✗ 丢弃
     │                                        ▲
     │                                        │ stdout JSONL 帧（只有 run_started/run_finished/stop_ack）
     │                                        │
     └──▶ TrajectoryFileObserver ──写文件──▶ react_agent.jsonl ──0.25s 轮询──▶ relay ──SSE──▶ 前端
```

三个断点，缺一即无流式：

| # | 断点 | 位置 | 证据 |
|---|---|---|---|
| **B1** | 运行时**根本没产生增量** | `frontier_agent/core/runtime/loop/agent_loop.py` | `stream_llm_tokens = bool(...) or any(getattr(o, "wants_llm_delta", False) for o in obs)`；随后 `on_delta=_on_delta if stream_llm_tokens else None`。`BridgeObserver` **未声明** `wants_llm_delta` → `on_delta=None` → 阻塞式整段返回 |
| **B2** | 增量被桥接层丢弃 | `server/worker.py` | `bridge = BridgeObserver(queue=None)`；`server/bridge.py::_emit` 首行 `if self._queue is None: return` |
| **B3** | 队列跨不过进程边界 | `server/orchestrator.py` | worker 经 `create_subprocess_exec` 启动；父子唯一通道是 stdout 帧，而帧类型只有 `run_started`/`run_finished`/`stop_ack` |

**补充**：即便绕过 B1–B3，SSE 仍是 `trajectory_tail` **每 0.25s 轮询**文件，而 `TrajectoryFileObserver` 是**整轮 LLM 响应完成后**才写一条 `t="llm"` 记录——答案仍要等整轮跑完才出现。

> 文档佐证：`deploy/huggingface/README.zh-CN.md` —「observer 必须声明 `wants_llm_delta`，否则运行时判定不需要流式，答案会一次性弹出」。
> 反例参照：`apodex/observers.py` 的 `TerminalObserver` 声明了 `wants_llm_delta = True`，这正是终端能流式的直接原因。

### 4.2 目标链路

```text
[worker 子进程]                                    [server 父进程]                    [浏览器]
agent_loop ──on_llm_delta──▶ BridgeObserver(queue) ──▶ _bridge_pump
                                     │                      │ stdout {"type":"event","payload":{...}}
                                     │                      ▼
                                     │              orchestrator._pump_frames
                                     │                      │ 识别 event 帧 → _publish(run_id, payload)
                                     │                      ▼
                                     │              subscribers[run_id] = {Queue, ...}   ← relay.subscribe()
                                     │                      │
                                     ▼                      ▼
                             TrajectoryFileObserver    relay.sse_for_run
                             react_agent.jsonl ──────▶ 合并双源（去重）──▶ SSE ──▶ 增量渲染
```

### 4.3 改造点

| 层 | 文件 | 改动 |
|---|---|---|
| 运行时开关 | `server/bridge.py` | `BridgeObserver.wants_llm_delta = True` |
| 增量内容 | `server/bridge.py` | `on_llm_delta` 发 `text`（内容）+ `thinking_text`（推理）+ `turn`；`on_tool_call`/`on_tool_result` 带 `tool_call_id`、`ms`、`output` |
| 跨进程泵 | `server/worker.py` | 新增 `_bridge_pump(queue)`：把队列事件逐条 `_frame("event", payload=...)` 写 stdout；`run_once` 传入真实队列并创建泵任务；`finally` 用 `_drain_bridge` 排空（哨兵 `None` + `wait_for(10s)`）后关闭 |
| 订阅分发 | `server/orchestrator.py` | 新增 `_subscribers: dict[str, set[Queue]]`；`subscribe(run_id)` / `unsubscribe` / `_publish`（`put_nowait`，绝不阻塞帧读取）/ `_close_streams`（推 `None` 哨兵）；`_pump_frames` 识别 `event` 帧调 `_publish`，帧流结束调 `_close_streams` |
| 中继合并 | `server/relay.py` | `sse_for_run` 改为**双源并发**：实时源（订阅队列）与回放源（`trajectory_tail`），`asyncio.merge` 后统一 yield；回放源的 `assistant_delta` 打 `full=True` 标记 |
| 前端 | `web/src/stores/runs.ts` | 增量文本按 `turn` 累积到正在渲染的块；对已流式渲染过的 turn，忽略回放源的 `full` 事件（去重） |

### 4.4 关键设计决策与风险

1. **背压**：实时队列用 `put_nowait` + 无界队列。Agent 循环绝不能因 UI 慢而阻塞；delta 极小，可接受堆积。压力下允许丢 delta（trajectory 有完整 content 兜底），但**生命周期事件不丢**。
2. **去重（最大风险）**：实时增量与轨迹回放会产出**同一段文本**（实时是分片、回放是整段）。必须按 `turn` 去重，否则答案重复拼接。约定：回放事件带 `full=True`，前端对"已流式渲染过"的 turn 跳过回放。
3. **thinking 缺失**：运行时 `LLMDeltaContext` 的 `thinking_delta` 并非所有 provider 都给；无 thinking 时前端不显示该块（不报错）。
4. **开启流式的行为变化**：`wants_llm_delta=True` 会让 `call_llm` 从阻塞改流式，激活首 token 超时、重试时丢弃已发增量等逻辑 → **需回归测试**（`tests/test_web_m1.py` 等）。
5. **脱敏不能漏**：增量同样要过 `redactSecrets`——建议在 worker `_bridge_pump` 出口统一脱敏，而非逐个事件处理（防止新增事件类型时漏掉）。

---

## 5. 展示层复刻设计

### 5.1 布局映射

| 终端 | Web 方案 |
|---|---|
| 顶部（workflow · session · workspace） | 顶部栏：会话标题 + pipeline 标签 + 工作目录（可折叠） |
| 左侧 transcript | 主对话区（现有 `ChatView`），升级为"步骤流"（思考/文本/工具/审批/报告） |
| 右侧四 Tab | 右侧抽屉 / 可折叠面板：`Plan` `Activity` `Files` `Diff`（现有「详情」抽屉已有 `el-tabs`，扩展为四 Tab） |
| 底部状态栏 | 对话区下方常驻状态条（现有运行状态条升级） |
| `Ctrl-B` 隐藏右侧 | 抽屉开合按钮 |

### 5.2 Plan / Todo 看板

- **数据源**：todo 工具调用。终端从 todo 工具的调用参数/结果解析步骤与状态。
- **方案**：后端从 trajectory 的 `t="result"` 记录中筛出 todo 类工具，解析出 `{id, content, status}`，产出 `plan_updated` 事件（或在前端从已有 `tool_finished` 的 `output` 解析）。
- **展示**：`PlanPanel.vue`——步骤列表 + 状态图标（待处理/进行中/完成/取消）+ `已完成数/总数`；空态 `no plan yet`。
- **依赖**：需确认当前 `tui` profile 的 `agent_tools` 是否包含 todo 工具（见 §9 前置调研）。

### 5.3 Activity 时间线

- **数据源**：实时 `tool_started` / `tool_finished`（含 `tool_call_id`、`input`、`output`、`ms`、成功/失败）。
- **展示**：`ActivityPanel.vue`——每行 `状态图标 + 工具名 + 持续时间 + 摘要`；可点击展开详情（state / duration / call ID / details / 完整 input-output）。
- **状态集**：running / done / error / skipped / interrupted（对应终端的成功/失败/跳过/中断/运行中）。
- **耗时**：`running` 行用前端计时器实时累加（后端只给终态 `ms`）。

### 5.4 Files 预览 与 Diff

**Files 预览**

- 现有 `ArtifactPanel.vue` 只有列表 + 下载，需加**只读预览**。
- 新增后端端点：`GET /api/runs/{id}/artifacts/preview?path=` → 返回 `{kind: text|image|binary|unsupported, content?, truncated}`。
- 服务端做类型判定与大小/行数截断（终端有预览上限，语义对齐：完整内容以磁盘文件为准）。
- 复用现有 `resolve_artifact_path()`（唯一路径解析点，已防越界），**不新增路径解析逻辑**。
- 前端：文本类走 `renderMarkdown`/代码高亮，图片直显，二进制/unsupported 显示"不支持预览，请下载"。

**Diff**

- 终端基线语义：以**会话首次触碰该文件前**的内容为基线。Web 需等价实现——在文件工具首次写入前快照原内容（或不存在记 `/dev/null`）。
- 新增后端能力：run 结束后产出 `diff` 数据（unified 格式 + `+新增/-删除` 统计）。
- 与第一类（文件工具）保持一致；第二类（bash 扫描）**本次建议先只做展示、不做 revert**，与终端语义一致。
- 新增：`GET /api/runs/{id}/diff` → `{files: [{path, status: added|modified|deleted, hunks, additions, deletions}]}`。
- 展示：`DiffPanel.vue`——文件列表 + unified diff（绿 `+` / 红 `-`）+ 顶部统计。无变更时 Tab 隐藏。

### 5.5 transcript 导航（过滤 / 搜索 / 定位报告）

纯前端能力，无需后端改动：

- 过滤：`thinking` / `tools` / `errors` / `report` / `all`（对应终端 `/filter`）。
- 搜索：`/find <文字>` → 对话区内文本搜索 + 高亮 + 上一个/下一个。
- 跳最终报告：按钮（对应 `Ctrl-G`）/ 复制（对应 `Ctrl-Y`）。
- 展开/收起 thinking 块（已有 `<details>`，对齐终端 `Alt-Enter`）。

### 5.6 状态栏升级

现有只显示 run 状态。需补齐（对齐终端 `阶段 · 耗时 · workflow · model · context · tools · queued`）：

| 字段 | 数据源 |
|---|---|
| 阶段 | `run_started` / `run_completed` 等生命周期事件 |
| 耗时 | 前端计时器（run 开始 → 终态） |
| workflow / pipeline | `run_started.pipeline_id` 或提交参数 |
| model | `run_started.model_name` |
| context 余量 | 需后端提供（`compaction` 事件 + 累计 tokens / 上下文窗口） |
| tools 数量 | `run_started.tool_names.length` |
| queued | 前端本地计数（steer 队列长度，见 §6.2） |
| 文件变更统计 | 来自 Diff（§5.4） |

> `context 余量` 与 `usage` 口径需与 T2.11 计量一致（聚合 trajectory 每轮 `usage`，cache 读/写分开）。

---

## 6. 业务流程复刻设计

### 6.1 人工审批门（human-in-the-loop）

**终端语义**（§2.3）：写文件或需确认的命令触发审批；默认选中 `No`；选项 `y/n/m/a/A/e`；高风险必须输 `yes`。

**Web 方案**

- **机制**：worker 侧已有的审批钩子（apodex `permissions.py` / `fsguard.py` 的批准门）需在子进程内**挂起等待**，通过 stdin 控制通道（已有 `{"action":"stop"}` 的 JSONL 通道）回传决定。
- **事件契约**（新增）：
  - `approval_requested`：`{approval_id, tool_name, target, reason, preview, risk: normal|high}`
  - 决策写入：`POST /api/runs/{id}/approve` `{"approval_id", "decision": "once|reject|session_bash|session_all|persist", "replacement_command"?}`
- **UI**：`ApprovalDialog.vue`——展示目标、原因、命令或 diff 预览；**默认焦点在「拒绝」**（对齐终端默认 No）；高风险操作需输入 `yes` 才启用批准按钮；`e` 对应"拒绝并输入替代指令"输入框。
- **安全约束（必须继承）**：
  - 硬拒绝项（hard denials）不能被 `a`/`A` 覆盖（apodex `fsguard` 语义）。
  - Native runtime 不是 OS 沙箱 → 弹窗需明示"获批命令拥有当前用户权限"。
  - 审批挂起时应有超时兜底，避免 worker 永久阻塞。

### 6.2 运行中干预（steer）

**终端语义**（§2.3）：异步排队；不终止当前 LLM/工具调用；`react` 给当前 Agent，`agent_team` 给 coordinator；太晚则作 follow-up；多条排队。

**Web 方案**

- **机制**：复用已有 stdin JSONL 控制通道，新增 `{"action":"steer","message":"..."}`；worker 侧转成运行时的 `Intervention`（对齐 `apodex/steer.py` 语义），在下一个安全 turn 边界注入。
- **端点**：`POST /api/runs/{id}/steer` `{"message": "..."}`。
- **UI**：输入框在运行中可用（现在可能已禁用，需检查）；发送后显示 `queued` 提示；状态栏 `queued` 计数 +1。
- **语义约束**：不改变"停止"语义——停止仍走现有 `/control`，不通过发"停止"文本实现。

### 6.3 `/revert` 回退

- 终端语义（§2.2）：**只撤销第一类**（文件工具显式记录的改动）；扫描发现的文件只展示、交人工处理。
- **Web 方案**：
  - 依赖 §5.4 的 Diff 数据，区分 `source: tool | scan`。
  - 新增 `POST /api/runs/{id}/revert` `{"paths": [...]}`，只允许 `source=tool` 的路径；`scan` 类返回明确错误并提示需人工处理。
  - UI：Diff 面板里 `tool` 类可勾选 revert，`scan` 类灰显并给出解释文案（必须保留终端的解释，否则用户会疑惑为何不能撤销）。

### 6.4 其余命令映射

| 终端命令 | Web 方案 | 优先级 |
|---|---|---|
| `/compact` | 新增 `POST /api/runs/{id}/compact` 或会话级压缩 | P2 |
| `/context` | 状态栏 context 余量（§5.6） | P1 |
| `/config` | 模型配置页（T3.4 已有，脱敏展示） | ✅ |
| `/log` | 详情抽屉显示 run_dir / trace 路径 | P2 |
| `/new` `/rename` `/resume` | 会话管理（T3.3 已有） | ✅ |
| `/fork` | 暂不实现 | P2 |
| `/workflow` 切换 | 提交时选择 pipeline | P2（当前只有 `stateful-react-agent`） |
| `/attach` 等 | 附件上传（T2.10 已有） | ✅ |

---

## 7. SSE 事件契约（新增/变更）

现有（`server/events.py`）：`run_started` `assistant_delta` `tool_started` `tool_finished` `run_completed` `run_failed` `run_stopped` `artifact_created` `warning`。

| 事件 | 状态 | 载荷 | 来源 |
|---|---|---|---|
| **`assistant_delta`（实时）** | **变更** | `{text, thinking_text, turn}` | bridge（新增字段） |
| `assistant_delta`（回放） | 变更 | `{content, thinking, turn, tool_calls, usage, full: true}` | trajectory |
| `tool_started` | 变更 | `{tool_call_id, tool_name, name, turn, input}` | bridge / trajectory |
| `tool_finished` | 变更 | `{tool_call_id, tool_name, name, ok, detail, output, ms, turn}` | bridge / trajectory |
| **`plan_updated`** | **新增** | `{steps: [{id, content, status}]}` | trajectory（todo 工具结果） |
| **`approval_requested`** | **新增** | `{approval_id, tool_name, target, reason, preview, risk}` | worker |
| **`approval_resolved`** | **新增** | `{approval_id, decision}` | worker |
| **`steer_queued`** | **新增** | `{seq, message}` | server |
| **`usage_updated`** | **新增** | `{prompt, completion, cache_read, cache_write, reasoning, llm_calls}` | trajectory（T2.11 聚合） |
| **`compaction`** | 已有 | 现映射为 `warning` | trajectory |

**通用约定**

- 所有事件带 `seq`（回放游标，来自轨迹行号）；实时事件无 `seq`。
- 所有 LLM 相关文本在**出口统一脱敏**（§4.4 第 5 点）。
- 新增事件必须同步更新 `web/src/types.ts` 的 `SseEvent` 与 `stores/runs.ts` 的 `applyEvent`。

---

## 8. 新增接口与组件清单

### 8.1 后端

| 端点 | 方法 | 用途 | 依赖 |
|---|---|---|---|
| `/api/runs/{id}/events` | GET | SSE（改为双源合并） | §4 |
| `/api/runs/{id}/steer` | POST | 运行中干预 | §6.2 |
| `/api/runs/{id}/approve` | POST | 审批决策回传 | §6.1 |
| `/api/runs/{id}/diff` | GET | 文件变更 | §5.4 |
| `/api/runs/{id}/revert` | POST | 回退（仅 tool 类） | §6.3 |
| `/api/runs/{id}/artifacts/preview` | GET | 产物预览 | §5.4 |

### 8.2 前端

| 组件 / 模块 | 用途 | 依赖 |
|---|---|---|
| `stores/runs.ts` | 流式累积 + 去重 + steps 扩展 | §4 |
| `components/PlanPanel.vue` | Plan / todo 看板 | §5.2 |
| `components/ActivityPanel.vue` | Activity 时间线 | §5.3 |
| `components/DiffPanel.vue` | Diff 展示 | §5.4 |
| `components/ApprovalDialog.vue` | 审批弹窗 | §6.1 |
| `components/StatusBar.vue` | 状态栏升级 | §5.6 |
| `ArtifactPanel.vue` | 加预览能力 | §5.4 |
| `views/ChatView.vue` | 布局 + 四 Tab + 过滤/搜索 | §5.1 / §5.5 |

---

## 9. 分阶段实施计划

**前置调研（实施前必须确认）**

1. 当前 `tui` profile 的 `agent_tools` 是否含 todo 工具（决定 Plan 看板可行性）。
2. `LLMDeltaContext` 的 `thinking_delta` 在目标 provider（GLM-4.5-Flash）是否可用。
3. worker 侧审批钩子在当前 pipeline 下如何挂入（`permissions.py` 是否生效于非 TUI 路径）。

### 阶段一：实时化（地基，必须先做）

| # | 任务 | 要点 |
|---|---|---|
| P1.1 | bridge 声明 `wants_llm_delta` + 增量带 turn/thinking | §4.3 |
| P1.2 | worker 桥接泵 + stdout `event` 帧 + 排空 | §4.3 |
| P1.3 | orchestrator 订阅分发 | §4.3 |
| P1.4 | relay 双源合并 + 去重标记 | §4.3 |
| P1.5 | 前端增量渲染 + 去重 | §4.3 |
| **验收** | 回答逐 token 出现；无重复拼接；回归 `tests/` 全绿（重点 `test_web_m1.py`） |

### 阶段二：展示层

| # | 任务 | 要点 |
|---|---|---|
| P2.1 | Activity 时间线（参数/输出/耗时/状态/展开） | §5.3 |
| P2.2 | 状态栏升级（耗时/model/tools/usage/context） | §5.6 |
| P2.3 | Files 预览 | §5.4 |
| P2.4 | Plan / todo 看板 | §5.2 |
| P2.5 | Diff 面板（先只读） | §5.4 |
| P2.6 | transcript 过滤 / 搜索 / 定位报告 | §5.5 |
| **验收** | 右侧四 Tab 与终端信息等价；状态栏字段齐全 |

### 阶段三：流程闭环

| # | 任务 | 要点 |
|---|---|---|
| P3.1 | steer 干预 | §6.2 ✅ 已实现 |
| P3.2 | 审批门 | §6.1 ✅ 已实现 |
| P3.3 | `/revert`（依赖 P2.5 的 source 区分） | §6.3 ✅ 已实现 |
| **验收** | 运行中可干预；写文件触发审批且默认拒绝；revert 只撤销 tool 类 |

P3.3 完成记录（2026-09-04）：
- 后端：`server/diff.py` 新增 `revert_paths()`——以 `DiffRecorder` 落盘的
  `diff/manifest.json` 为唯一允许清单（同一份基线即 §2.2 第一类），
  `resolve_run_display_path()` 把 `/workspace`、`/outputs` 别名映射到 run 自身目录树
  （worker 侧的 `resolve_runtime_path` 依赖只有 worker 进程才有的
  `FRONTIER_AGENT_*_DIR`，服务端不能复用，故按 run 布局等价推导并**二次校验包含性**，
  符号链接/越界一律 fail-closed）；`POST /api/runs/{id}/revert`（`routes/runs.py`）
  带所有权 404 + 终态校验（运行中 409，避免与仍在写的 worker 抢树）+ 逐路径结果。
- 两种还原结果：`restored`（有基线，写回）与 `removed`（基线为 `/dev/null`，删除即还原）。
  `bash_scan` 类逐路径返回 `rejected` + 面向用户的解释文案，不静默跳过。
- 回滚后从 `diff.json` 摘除已还原项（等价于 `write_diff` 对 base==current 的处理），
  不重算整份 payload——重算需要 worker 的环境变量，在服务端会把每条都算成 deleted。
- 前端：`web/src/utils/revert.ts`（7 tests）+ `types.ts`/`api` 接线 +
  `DiffPanel.vue`（`file_tool` 行可勾选批量回滚，`bash_scan` 行灰显并带"扫描发现…
  需手动处理"解释），回滚成功后由 `ChatView` 刷新 Diff/产物/轨迹。
- TDD 见 `tests/test_web_p3_revert.py`（18 tests）。

回溯审计记录（2026-09-04）：
- **发现 1（§5.6 / T3.1 实测缺口）**：SSE 桥（`server/orchestrator.py` `_bridge_event`）
  只转发 `RUN_STARTED/RUN_STOPPED/STEP*`，**不转发 `RUN_COMPLETED`/`RUN_FAILED`**。
  后果：失败的运行在状态栏被当作 `completed` 显示（只因 SSE 关闭猜测成功）。
  **已修复**：`_persist_run_result` 在落库后按 `ok/error/stopped_by` 补发
  `RUN_COMPLETED`/`RUN_FAILED` 终态事件（stop 已由其独立事件覆盖，不重复发）。
- **发现 2（§5.7 失败可追溯 / §6.4 P2）**：流式事件**不带失败原因文本**，且缺乏
  单 run 权威视图（运行目录、失败原因、用量）。**已修复**：新增
  `GET /api/runs/{id}`（`RunSummaryResponse`，含 `run_dir`/`error`/`stopped_by`/
  `usage`），前端 `runsApi.get` + store `reconcile()` 在 `onDone` 后对齐真相；
  `ChatView` 失败横幅、`RunDetailView` 运行目录+失败原因。
- 验证：`pytest tests 1118 passed 3 skipped`；前端 `vue-tsc` 0 错、单测 63 passed、
  `vite build` 通过。

P3.2 完成记录（2026-09-03）：
- 后端：`server/approval.py`（ApprovalGate fail-closed 超时 300s + ApprovalObserver 复用
  apodex `assess_with_rules`，硬拒绝在事件发出前拦截）、`POST /api/runs/{id}/approve`
  路由、worker stdin `approve` 帧；TDD 见 `tests/test_web_p3_approval.py`。
- 前端：`web/src/utils/approval.ts`（12 tests）+ store `pendingApproval`/`approve` 接线 +
  `ApprovalDialog.vue`（默认焦点拒绝、高风险须输 `yes`、替代指令、native 非沙箱明示）。
- 顺带修复：① orchestrator slot 泄漏（run 结束未释放并发槽，新增回归
  `test_completed_run_releases_worker_slot`）；② stop×审批门死锁——stop 原本使 worker
  的 stdin 读取线程退出，导致其后到达的 approve 帧无人读取、审批门挂满 300s；现改为
  stop 时对挂起审批 fail-closed reject 且读取线程继续存活（`server/worker.py`）；
  ③ 6 个 P3.2 之前的 e2e（mock 脚本含 `create_file`）补 `_spawn_approver` 走真实
  approve 路由应答，未引入任何绕过点。

---

## 10. 风险与验收

### 风险

| 风险 | 影响 | 缓解 |
|---|---|---|
| **实时与回放重复渲染** | 答案重复拼接（最易踩） | 回放事件打 `full=True`，前端按 turn 去重；单测覆盖 |
| 开启流式改变运行时行为 | 首 token 超时/重试语义变化 | P1 完成后跑全量回归，重点 M1/M2 用例 |
| 审批挂起导致 worker 阻塞 | 运行永久卡住 | 审批超时兜底；超时按拒绝处理 |
| 增量泄漏敏感信息 | 密钥进浏览器 | worker 出口统一脱敏（§4.4） |
| Diff 基线实现偏差 | 误把用户无关改动算到 Agent 名下 | 严格对齐"会话首次触碰前"基线语义 |
| 上下文余量口径不一致 | 状态栏数字与计量页不符 | 复用 T2.11 `aggregate_usage`，单一口径 |

### 全局验收标准（"完美复刻"的判据）

1. **实时性**：回答逐 token 到达，与终端观感一致，无重复。
2. **可观测**：Plan / Activity / Files / Diff 四 Tab 信息量与终端一一对应。
3. **可控制**：运行中能 steer、能停止；写操作能审批且默认拒绝。
4. **可解释**：思考过程、工具输入输出、耗时、错误原因全部可见。
5. **安全不退化**：脱敏覆盖全部新增路径；路径越界防护不新增解析点；审批硬拒绝不可绕过。
6. **回归通过**：`uv run pytest tests -q` 全绿 + `vue-tsc --noEmit` 0 错 + `vite build` 通过。
