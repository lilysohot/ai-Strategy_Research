# Web 运行存储与轨迹追溯缺陷修复报告

| 项 | 内容 |
|---|---|
| 版本 / 日期 | v1.4 · 2026-09-29；纠正环境准备、证据状态与迁移前置范围，F01 仍为必交付项 |
| 状态 | 有效缺陷报告 · 21 项待分诊、待修复；已执行隔离复核，未修改运行代码 |
| 检查基线 | 当前工作区；HEAD `a48cd25eb5c0bb4fa724cee7c69bb5b6e2fa1ed2`，工作区非干净快照 |
| 最新复核 | 上行保留初次检查基线；v1.3 基线、文件哈希、覆盖矩阵及执行结果见[全面存储链路复核](web-storage-chain-audit.md) |
| 执行准备 | [环境准备与执行边界](web-storage-validation-environment.md)：优先复用现有环境；按测试影响范围选择独立库/实例，不统一另建整套服务 |
| 来源 | 本次关于 Web 启动架构、模型/工具追溯及 `server/runs` 存储位置的检查 |
| 范围 | Web 默认 ReAct 链路的运行文件、构建、持久化、轨迹接口、会话准入、上下文与实时/历史展示 |
| 上游要求 | [产品需求](../product-requirements.md)：PR-RUN-02/04、PR-GOV-01/02/03/05/06、PR-BIZ-04/05/06 |
| 本地任务入口 | [修复任务规格](../../.scratch/web-runtime-trace-hardening/spec.md)；每项状态仅在对应 issue 的 `Status:` 行维护 |

## 1. 结论与证据边界

Web 已有按 Run 保存模型响应、工具结果和上下文压缩记录的基础，JSONL 文件本身不是错误选型。
当前问题是生产运行数据与代码目录/构建上下文混用、部署卷与写入路径不一致，以及记录、
传输、展示之间仍有缺口。不能把“已经有轨迹文件”表述成完整、无丢失、已脱敏的审计链。

v1.0—v1.2 完成源码与配置核对；v1.3 已执行隔离 ASGI/SQLite/文件及前端源码方法复核，
新增 29 个契约检查中 26 个失败、3 个通过；已有相关回归 57 个通过。详见全面复核记录。
未修改应用代码、迁移运行数据、重建镜像、操作生产数据库或调用 LLM，未读取真实用户轨迹正文。
下文早期条目的“待执行验证”保留为完整修复验收清单；哪些子场景已复现以最新覆盖矩阵为准，
不能将隔离复现当作生产事故证据，也不能将复现完成当作修复完成。
v1.4 补正：新增检查包含待核定的目标契约，26 个失败不能直接当作 26 个生产缺陷；
最终修复范围按需求适用性和真实链路验证收口。F19 的检查未断开真实 DB，只证明缺少就绪信号。

事实边界：

- Docker 匿名卷不等于容器一重启就丢数据；缺口是显式卷绑定、重建、迁移与恢复的可管理性。
- `server/runs/` 已被 `.gitignore` 排除；没有证据说明它被提交到 Git，但这不能代替 `.dockerignore`。
- `/trace` 已做 Run 所有者校验；缺少服务端脱敏不等于已发现跨用户越权。
- 模型接口未返回的内部推理无法记录；加密推理块不等于可读解释。
- 现有记录器保存已返回的模型轮次，不承诺持久保存所有流式片段或所有失败请求尝试。
- 文档标记备份待开始不证明运维侧绝无备份；缺少的是本仓库可核验的完整恢复契约与验收证据。

## 2. 当前链路

```text
POST /api/runs → Orchestrator → python -m server.worker
→ BenchmarkSession → Scheduler → Stateful ReAct → run_agent_loop
                                   ├─ TrajectoryFileObserver → JSONL / JSON
                                   └─ BridgeObserver → stdout → SSE

轨迹回放：run_dir_for(run_id) → react_agent.jsonl → /trace 或 SSE replay
数据库：用户/研究/Run/消息/用量/产物索引
```

默认路径为 `<repo>/server/runs/<run_id>/run/agent/trajectories/react_agent.jsonl`。
根目录支持 `SERVER_RUNS_ROOT`；默认同时写 JSON 与 JSONL，但格式受环境配置控制。
Web relay 当前固定读取 ReAct 文件名，不代表所有工作流/子 Agent 的轨迹都已被统一接入。

## 3. 问题总览

优先级为本次修复建议：P1 为生产交付前需处理的数据保护/正确性问题，P2 为展示和容量治理问题。
不据此自动改变已有项目排期。F08 是多用户上线阻断项，先于其他修复处理；
当前没有生产影响调查结果，不能把代码缺口直接写成已发生的数据泄露。

| 编号 | 建议优先级 | 发现 | 证据强度 | 任务 |
|---|---|---|---|---|
| F01 | P1 | 运行根目录与显式持久卷不匹配，根目录迁移缺少旧 Run 解析契约 | UUID 定位差异隔离复现；部署覆盖待核验 | [01](../../.scratch/web-runtime-trace-hardening/issues/01-storage-roots.md) |
| F02 | P1 | Web 构建会复制 `server/`，Docker ignore 未排除运行目录 | 已修复并验证（构建探针+真实构建+回归 40 项）；历史镜像调查完毕：受影响集合为空（2026-10-01） | [02](../../.scratch/web-runtime-trace-hardening/issues/02-build-context.md) |
| F03 | P1 | `/trace` 返回原始记录，与 SSE 的脱敏不一致 | 合成凭据经 ASGI 原样返回已复现；全出口待验 | [03](../../.scratch/web-runtime-trace-hardening/issues/03-trace-redaction.md) |
| F04 | P1 | JSONL 请求记录丢弃工具调用 ID，回放与结果可能无法配对 | observer/relay 调用 ID 差异隔离复现 | [04](../../.scratch/web-runtime-trace-hardening/issues/04-tool-call-identity.md) |
| F05 | P2 | 历史轨迹页不展示已保存推理，工具结果仅有短预览 | 模板及截断逻辑确认；浏览器验收待执行 | [05](../../.scratch/web-runtime-trace-hardening/issues/05-history-trace-ui.md) |
| F06 | P1 | 未完成流式响应无持久化保证，完整性状态和文档承诺不准确 | 回调与写入策略确认；故障注入待执行 | [06](../../.scratch/web-runtime-trace-hardening/issues/06-trace-completeness.md) |
| F07 | P1 | 业务库与运行文件的联合备份、保留和删除缺少闭环验收 | 计划待办及设计要求确认；运维现状待调查 | [07](../../.scratch/web-runtime-trace-hardening/issues/07-retention-recovery.md) |

> v1.1 补充复核：原 7 项不能代表完整 Web 审查。新增问题如下，任务总数为 14。

| 编号 | 建议优先级 | 发现 | 证据强度 | 任务 |
|---|---|---|---|---|
| F08 | P1 | 提交 Run 缺少会话归属校验 | 双合成用户 ASGI 越权写入已复现；生产影响未调查 | [08](../../.scratch/web-runtime-trace-hardening/issues/08-session-ownership.md) |
| F09 | P1 | SSE 游标与终态恢复协议存在缺口 | 迟订阅/游标子场景隔离复现；浏览器待验 | [09](../../.scratch/web-runtime-trace-hardening/issues/09-stream-replay-contract.md) |
| F10 | P1 | 流式去重导致文字缺失与用量漏计或重复 | 实际前端源码方法隔离复现；浏览器待验 | [10](../../.scratch/web-runtime-trace-hardening/issues/10-replay-text-usage.md) |
| F11 | P1 | 切换 Run 后旧异步响应可能覆盖新视图 | 实际前端源码方法隔离复现；浏览器待验 | [11](../../.scratch/web-runtime-trace-hardening/issues/11-watch-generation.md) |
| F12 | P1 | 上传校验与运行创建缺少失败清理 | 拒绝批次遗留文件隔离复现；完整补偿待验 | [12](../../.scratch/web-runtime-trace-hardening/issues/12-upload-atomicity.md) |
| F13 | P2 | 轨迹读取与事件缓冲缺少容量边界 | 已修复并动态验证，复核通过已关闭（2026-10-01） | [13](../../.scratch/web-runtime-trace-hardening/issues/13-capacity-bounds.md) |
| F14 | P1 | 排队 Run 的历史上下文没有明确截止点 | 未来消息进入历史隔离复现；真实 worker 待验 | [14](../../.scratch/web-runtime-trace-hardening/issues/14-history-boundary.md) |

## 4. 逐项修复说明

> v1.3 全面复核新增 F15—F21，证据与未验收范围见[复核记录](web-storage-chain-audit.md)。

| 编号 | 优先级 | 发现 | 证据强度 | 任务 |
|---|---|---|---|---|
| F15 | P1 | 运行落账与崩溃恢复缺少一致性及幂等 | 隔离子场景已复现，完整验收待执行 | [15](../../.scratch/web-runtime-trace-hardening/issues/15-finalization-recovery.md) |
| F16 | P1 | 消息序号与关系约束不足 | 隔离子场景已复现，完整验收待执行 | [16](../../.scratch/web-runtime-trace-hardening/issues/16-database-invariants.md) |
| F17 | P1 | 产物根目录与回滚基线可经符号链接越界 | 隔离子场景已复现，完整验收待执行 | [17](../../.scratch/web-runtime-trace-hardening/issues/17-storage-trust-boundary.md) |
| F18 | P1 | 产物索引与回滚后的文件不一致 | 隔离子场景已复现，完整验收待执行 | [18](../../.scratch/web-runtime-trace-hardening/issues/18-artifact-index-consistency.md) |
| F19 | P1 | 存储与迁移故障缺少就绪门禁 | 源码及替身检查确认信号缺口；真实故障未注入 | [19](../../.scratch/web-runtime-trace-hardening/issues/19-storage-readiness.md) |
| F20 | P1 | Run 模型快照与启动状态未接入持久化 | 隔离子场景已复现，完整验收待执行 | [20](../../.scratch/web-runtime-trace-hardening/issues/20-run-metadata-snapshot.md) |
| F21 | P1 | 用户纠正与审批决定缺少持久追溯契约 | 源码确认；动态恢复待验 | [21](../../.scratch/web-runtime-trace-hardening/issues/21-control-history.md) |

### F01：持久卷、数据根目录及历史路径迁移

补充：UUID 校验使用 `uuid.UUID(run_id)`，但文件定位/控制仍沿用原始字符串。
创建 Run 使用 hex，摘要和会话消息返回带连字符 UUID（见
[sessions.py](../../server/routes/sessions.py)），同一 ID 的合法不同写法会通过归属校验，
却可能定位到不同目录或无法找到运行 handle。应统一 ID 规范形式，并验收 API 返回 ID
可直接用于 trace、events、产物、stop/steer 等入口，不能要求前端猜测或手工去掉连字符。

**证据**：

- [server/config.py](../../server/config.py) 的 `ServerConfig.runs_root` 默认位于代码树，
  `run_dir_for()` 每次以当前配置根目录拼接 Run ID。
- [deploy/docker-compose.yml](../../deploy/docker-compose.yml) 的 `api` 将 `agent_data`
  挂到 `/app/agent_data`，未在 Compose 中直接挂到默认 `/app/server/runs`。
- [deploy/Dockerfile.web](../../deploy/Dockerfile.web) 对 `/app/server/runs`、`/app/uploads`
  声明 `VOLUME`，与前述默认配置组合时会依赖匿名卷；宿主 `.env` 可能覆盖根目录，需核验实际部署。
- [server/store.py](../../server/store.py) 保存 `Run.run_dir`，但
  [server/relay.py](../../server/relay.py) 的轨迹读取重新使用 `run_dir_for(run_id)`。

**影响**：难以明确备份哪个卷；更新根目录后历史记录可能仍在旧位置，而 `/trace` 在新位置
找不到文件时返回空列表，看起来像“没有轨迹”。将数据目录移到代码树外本身不会建立安全隔离。

**本次必须整改（用户已明确纳入范围）**：不再把 `<repo>/server/runs` 作为 Web 长期运行数据的
默认位置；本地与生产均采用源码树之外的专用数据目录。JSONL 格式继续使用，目录整改不要求
将全部轨迹转存 PostgreSQL，也不改变 CLI 的 `.apodex/runs` 契约。

以下保留建议目标布局，实施前必须匹配实际运行模式和服务身份，不表示当前已经切换，
也不要求将本机服务改成容器部署：

| 环境 | Web 运行根目录 | 持久化方式 |
|---|---|---|
| Docker Compose | `/var/lib/frontier-agent/web/runs` | 显式设置 `SERVER_RUNS_ROOT`；现有 `agent_data` 命名卷的目标挂载点统一到 `/var/lib/frontier-agent/web`，先盘点卷内容，保留实际卷身份 |
| 本地 Linux / WSL 交互运行 | `${XDG_DATA_HOME:-$HOME/.local/share}/frontier-agent/web/runs` | 由实际运行用户解析；不得固定 administrator 用户名。系统服务另显式设置稳定服务数据目录，不能随 HOME 或账号变化漂移 |
| 自定义部署 | 管理员配置的源码树外绝对路径 | 使用 `SERVER_RUNS_ROOT` 覆盖，明确目录权限、卷和备份落点 |

每个 Run 的 `inputs/`、`ws/outputs/`、`run/`、`spill/`、历史及摘要一同迁移，保持内部相对布局。
现有上传代码实际写入 `<runs_root>/<run_id>/inputs`；`uploads_root` 当前仅声明并创建目录，
不能把改它当成上传迁移完成。实施时盘点仓库顶层 `uploads/` 的遗留内容，确认无消费者后移除
无效配置/自动建目录；如发现真实消费者，则统一接入新数据根目录并迁移，不能直接删掉文件。

Compose、Dockerfile 的旧 `VOLUME` 声明、环境样例和部署说明须同步，避免继续创建旧路径匿名卷。
启动校验目录可写、源码树边界和实际落点；配置错误应明确失败，不静默回落到旧目录。
统一轨迹、产物、输入和 diff 的受控路径解析，不直接信任数据库或请求中的任意绝对路径。

迁移前盘点 Run ID、数据库路径、实际目录和卷；备份并核对文件清单/校验值；迁移窗口内处理活动
Run，避免一半写旧目录一半读新目录。迁移后验证旧/新 Run，可回退后再决定旧卷处置，不直接删除。
迁移工具需支持 dry-run、清单校验和可重入执行；发现新旧同 ID 文件冲突时停止该项并报告，
不覆盖未知内容。数据库中的存储引用与文件迁移保持可恢复的一致性，过渡期只读兼容旧位置；
未完成迁移的记录必须明确提示，不能展示为空轨迹。回退先停止写入并核对切换后的新数据，
不能只把环境变量改回去而丢下新 Run。

**待执行验证**：按环境准备方案选取 E1 正常流程、E2 测试目录迁移及必要的 E3 故障场景。
以实际部署方式验证两次 Run、服务重启/重新部署后历史读取；容器交付另验证卷挂载与重建。
切换测试数据根目录并验证兼容读取或受控迁移。无文件、已清理、损坏和正常空轨迹应返回不同状态。

**验收**：明确持久数据落点，容器部署使用显式可识别持久卷；重启和重新部署后可读；旧 Run 与新 Run 均可追溯；数据库路径与
存储定位一致；越界路径拒绝；恢复/回退有记录。不能仅以“配置变量已改”关闭任务。
此外，新部署及本地默认启动不再向源码树写 Web 运行数据；旧轨迹、输入、产物、历史及摘要
均有迁移清单与校验结果；应用升级/容器重建后可读，F02 镜像排除与 F07 恢复验收共同通过。

### F02：运行数据进入构建上下文及镜像的风险

**证据**：根 [.dockerignore](../../.dockerignore) 未列 `server/runs/`；
[Web Dockerfile](../../deploy/Dockerfile.web) 执行 `COPY server ./server`，再将 build 目录复制到
runtime；[Compose](../../deploy/docker-compose.yml) 的 build context 为仓库根。
[.gitignore](../../.gitignore) 虽排除了运行目录，却不会影响 Docker 构建。

**影响**：在本地已有运行记录的代码树中构建时，轨迹、输入、产物可能进入构建上下文和镜像层。
容器中再挂卷遮住目录不能消除镜像层中的文件。本轮没有确认任何历史镜像已发布或包含真实数据。

**建议**：Docker 构建排除运行文件、上传目录和其他实际运行数据根目录；保留构建所需源码及测试
fixture。检查是否存在其他构建上下文或 Dockerfile 专属 ignore。增加镜像内容回归验证，
生产运行数据与代码分离作为第二道措施。

**待执行验证**：在临时复制的构建目录放置无敏感信息的唯一 sentinel，模拟
`server/runs/<test-id>/...`；构建测试镜像并检查 build/runtime 阶段及相关层中都不存在 sentinel。
不拿真实轨迹做测试，不上传测试镜像。若历史构建确认包含数据，再单独评估镜像/缓存处置。

**验收**：上下文与镜像均不含 sentinel；源码正常打包；ignore 变更由对应测试保护。

### F03：轨迹接口与 SSE 的脱敏和数据最小化不一致

**证据**：[server/routes/runs.py](../../server/routes/runs.py) 的 `run_trace()` 在所有者校验后直接
返回 `trajectory_records()`；[server/relay.py](../../server/relay.py) 则在 SSE replay 出口调用
`redact_deep()`。[server/bridge.py](../../server/bridge.py) 注释及记录器实现明确原始轨迹没有统一
脱敏。[RunDetailView.vue](../../web/src/views/RunDetailView.vue) 在前端做展示脱敏，无法改变已经
通过网络返回的原始 payload。

**影响**：工具输出中偶然出现的凭据可能通过 `/trace` 到达浏览器，即使 UI 隐藏了它。原始
system prompt、文件正文及推理块也没有独立的返回字段策略。现有归属校验仍有效，不能据此推断越权。

**建议**：服务端建立一致的轨迹展示投影，覆盖实时流、回放、详情和导出；明确允许返回字段。
密钥类内容应在存储和出口治理，不能仅靠通用正则保证覆盖。用户自己的资金值可在授权业务视图
中展示，不应为“一律脱敏”而破坏分析，但不得进入非必要日志。原始推理块/签名/加密内容若为
协议回放所需，应受限保存，不直接当人类可读思考返回。

**待执行验证**：用虚构凭据样例嵌入嵌套参数、结果、内容和错误；调用真实服务端序列化路径，
检查网络响应而非只查 DOM。其他用户返回 404。旧轨迹同样经过安全投影。

**验收**：所有出口结果一致；无真实敏感样例进入测试；完整工具结果展开也不绕过脱敏；
权限、持久化与备份中的敏感信息策略明确；不宣称简单正则即可识别所有秘密。

### F04：工具请求与结果丢失共同调用身份

**证据**：[trajectory.py](../../frontier_agent/components/observers/trajectory.py) 的
`on_llm_response()` 写入 JSONL 时仅保留工具 `name/args`；`on_tool_result()` 保存原始
`tool_call_id`。JSON 信封保留 ID，但 Web replay 读的是 JSONL。
[relay.py](../../server/relay.py) 为无 ID 请求生成 `call_<turn>_<idx>`；
[runs.ts](../../web/src/stores/runs.ts) 的 `upsertToolStep()` 按 `callId` 找已有步骤。

**触发例**：模型实际返回 `call_vendor_abc`，结果也用该 ID；回放开始事件却生成 `call_1_0`。
两者不相等，页面可能建立两个卡片或留下未结束卡片。同轮同名工具并行时不能用名称补配。

**建议**：从请求解析后统一保存稳定 ID，贯穿调用、授权/跳过、结果、轨迹和 Web 事件；无原始 ID
时只在同一个权威位置生成一次。增加格式版本和历史兼容读取，旧记录无法唯一匹配时明确标注，
不强行猜配。共享记录器修复涉及 `frontier_agent/`，应显式纳入本项范围。

**待执行验证**：真实 observer 写文件 → relay 转事件 → Web store 的完整链；覆盖任意供应商 ID、
同轮同名两次调用、不同顺序返回、拒绝/跳过、重连回放和旧版无 ID 记录。

**验收**：每个可唯一识别调用只有一个正确终态步骤，参数与结果成对；旧数据不伪造精确归因。

### F05：历史轨迹展示缺少可见推理与完整结果入口

**证据**：记录器会保存 `thinking`，SSE 也传输它；
[RunDetailView.vue](../../web/src/views/RunDetailView.vue) 的 `llm` 模板只展示 content、tool_calls
和 usage，没有展示 `thinking`。`shortResult()` 对工具结果固定截取 300 字符，当前详情模板无
展开全文入口。此结论仅针对该历史详情组件，不等于所有实时路径都未接收推理。

**影响**：文件有内容，用户却无法在历史页面阅读；关键错误或证据可能落在工具结果的第 300
字符之后。展示不完整容易被误认为没有落盘。

**建议**：提供按轮次折叠的“模型返回的推理/说明”，区分缺失、未提供、受限内容；工具结果
支持受控展开/分页读取，明确截断提示。只读取 F03 定义的安全投影，不输出原始受限块。

**待执行验证**：无推理、可见推理、长结果、嵌套结果、错误结果及无权 Run 的浏览器场景；
刷新与历史切换后仍显示一致内容，不仅依赖 Pinia 内存。

**验收**：用户可回看供应商实际提供的可见内容和完整授权工具结果；缺失不显示为“完整思考”；
截断可感知且有继续读取入口；大结果不一次性卡住页面。

### F06：中断后的轨迹完整性契约不足

**证据**：[TrajectoryFileObserver](../../frontier_agent/components/observers/trajectory.py)
在 `on_llm_response()` 保存轮次，在工具结果回调保存结果；没有自己的 token delta 持久化回调。
`_write_jsonl()` 使用 `flush()`，没有每条 `fsync()`；observer 为 `critical=False`。
[BridgeObserver](../../server/bridge.py) 发送可见流式片段，但不落盘。
[技术架构](../tech-stack.md) 多处使用“完整轨迹”“SIGKILL 安全”表述，需收窄。

**影响与边界**：正常已返回轮次通常有记录；在模型仍输出时中止，页面见过的部分内容可能未
进入轨迹。`flush()` 不等于断电后的物理持久保证。磁盘写入失败也不能被用户误解为轨迹完整。
缺少请求尝试记录还意味着“保存了所有成功轮次”不等于每次失败/重试都可回放。

**建议**：先冻结需要保证的级别，再选择实现。最低要求保留尝试/轮次身份和
`complete/partial/unavailable` 等完整性状态，明确缺口；若产品要求中断后恢复已显示文本，
为流式内容加入有边界的增量检查点，不能只靠 SSE。不要逐 token 无限制写盘。
定义磁盘失败反馈、最终写入屏障与恢复规则；不同工作流沿用同一契约，避免平行轨迹真源。

**待执行验证**：隔离进程内模拟正常结束、流式中取消、SIGKILL、写入失败、末尾半行；
验证已完成轮次可读、未完成部分不会冒充完整、缺失状态可见。真实断电耐久另需存储级验证，
不能用普通进程 kill 测试替代。**→ 上述验证已于 2026-10-01 完成（见批次登记
`wsl_closure_20261001_pm`），断电耐久亦已于 2026-10-02 以"持久化链路审计 + fsync 修复 + 断电后果
文件层等价注入"收口**：`worker.persist_summary`（tmp fsync → rename → 目录 fsync + 轨迹终态 fsync，
全部 best-effort）修复审计发现的 summary 原子写无 fsync 与 `fsync_directory` 死代码问题；
`tests/test_web_f06_power_durability.py` 8/8 固定断电残留物语义（半行截断/零字节与残缺 summary/
轨迹缺失/无 fsync 平台/ENOSPC）；PG 侧由事务 + WAL 免疫。整机掉电的硬件级验证仍超出本机能力，
以文件层等价注入收口（artifacts 断电后 404 fail-closed 登记为已知边界）。

**验收**：承诺、实现和 UI 一致；记录缺口有明确状态；有效旧行不因半行损坏而不可读；
JSONL 必需配置缺失可检测；文档不再把“已 flush 的记录”扩大为全部流式或硬件级无丢失保证。

### F07：备份、保留、删除与恢复闭环缺少证据

**证据**：[Web 加固计划](web-platform-hardening.md) 中 T5 备份/T6 清理仍待开始；
[技术架构](../tech-stack.md) 将导出/保留期列为 PR-GOV-05 待办，且要求运行目录使用持久卷。
业务库记录与轨迹/输入/产物位于不同介质，单独恢复数据库并不能恢复完整研究。

**影响**：可能出现 Run 可查但文件缺失、目录持续增长、删除研究后文件长期残留等问题。
本次未检查运维任务、备份仓库或恢复演练记录，不能断言当前部署没有任何备份。

**建议**：扩展既有 T5/T6，不再建平行运维台账。盘点实际库、卷、存储量及密钥；定义分类
保留期、备份频率、恢复目标、删除语义和活动 Run 保护。备份清单关联 Run、存储引用、大小/
校验值及完成状态；最终轨迹可生成清单校验信息，但校验值本身不等于防篡改审计。

**待执行验证**：独立环境从业务库备份和文件备份恢复；检查消息、快照（实现后）、轨迹与产物
关联。演练过期清理、部分文件缺失、密钥不可用和删除恢复边界。任何删除先 dry-run 清单，
不在用户正在使用的数据目录试验。

**验收**：有可重复执行的联合恢复记录；恢复目标经明确并实测；清理不触及活动 Run 或其他
用户；文件不存在与已过期可区分；新业务资料上线前其版本/快照也进入同一恢复契约。

### F08：提交 Run 缺少会话归属校验

**证据**：[runs.py](../../server/routes/runs.py) 的提交入口接受客户端 `session_id`；
[store.py](../../server/store.py) 的 `ensure_session()` 只按主键获取已有会话，不检查
`user_id` 或删除状态；[orchestrator.py](../../server/orchestrator.py) 随后写入该会话，
并在 `_spawn()` 只按会话 ID 读取历史。`_session_uuid("default")` 也未包含用户身份。

**影响**：指定另一用户的会话 ID 可以进入其会话的写入/历史回填路径；两用户直接调用 API
且均省略会话 ID，也会映射到同一个默认会话。Run 自身的所有者校验不能阻止此前混入上下文，
也不能阻止另一用户消息写入原会话。这是代码确认且经双合成用户 ASGI 隔离复现的授权缺口，
没有证据证明生产数据已经泄露。应作为多用户上线阻断项优先修复。

**建议与验收**：创建任何文件、Run 或消息之前校验会话归属与可用状态；外部会话统一 404。
兼容默认会话须按用户隔离，统一规范化会话 ID 后再作为队列键。隔离数据库用 A/B 两名合成
用户验证外部 UUID、默认值、已删除会话、并发首次创建；断言没有文件/消息/Run 副作用，
历史构建不得包含另一用户文本。以假 worker 捕获输入即可，不需调用真实模型。

### F09：SSE 游标与终态恢复协议存在缺口

**证据**：[relay.py](../../server/relay.py) 一行 `llm` 记录会生成多个相同 `seq` 的事件；
[sse.ts](../../web/src/sse.ts) 收到第一个事件即推进到该行，重连从下一行开始。
[orchestrator.py](../../server/orchestrator.py) 的 `steer()` 又把独立的 `steer_seq` 放入
相同 `seq` 字段，客户端会误当轨迹游标。其 `subscribe()` 对已经结束的 Run 仍创建空 live
队列；`_close_streams()` 只通知当时已有订阅者。轨迹 tail 仅看 `summary.json` 退出，
启动孤儿修复只更新数据库。客户端收到 live 终态又会立即停止读取，未等待 replay 排空。

**影响**：同一行内断线可能漏掉后续工具开始事件；steer 次数超过轨迹行数时可能跳过记录；
已完成 Run 的新订阅可能永久等待；无 summary 的异常 Run 即使数据库已终态，仍可能持续轮询。
终态先到也可能使最后一批轨迹未送达。这些是独立于 F06“是否写盘”的传输/恢复问题。

**建议与验收**：分离控制消息序号与轨迹游标；明确一行多事件的确认边界，可采用子事件游标
或整行重放加幂等处理。以持久 Run 状态与轨迹排空边界共同确定结束，终态与订阅必须避免竞态。
覆盖同一行各事件之间断线、steer 序号较大、已结束后订阅、服务重启无 summary、终态先于回放。
审批请求/决策等 live-only 状态能否在刷新后恢复尚需专项核验，不能仅凭正文可回放视为通过。

### F10：流式去重导致文字缺失与用量漏计或重复

**证据**：[runs.ts](../../web/src/stores/runs.ts) 的 `applyEvent()` 一旦发现该轮收到过
任意 live 文本，就直接跳过整条 full replay；这个跳过发生在 usage 处理之前。
[relay.py](../../server/relay.py) 则允许背压时丢弃 live delta。
同一 store 的 `reconcile()` 将服务端整次 Run 的 usage 再用
[accumulateUsage()](../../web/src/utils/statusbar.ts) 加到已有逐轮统计上。

**影响**：只收到一个片段也会拒绝后续完整文本，断线或背压后的缺字无法由已落盘内容修复；
实时接收的轮次可能暂时漏计 usage，已累计的历史轮次又会在最终对账时重复计算。
`finalAnswer` 可补最终答复，但不能补全部中间推理/工具前说明，也不解决用量叠加。

**建议与验收**：按轮次用完整回放校正文本，重复事件保持幂等；文本与 usage 去重分别处理。
最终权威总量应替换或校准，不能当增量相加。合成两轮记录覆盖片段丢失、仅 thinking 片段、
完整回放、重复回放、重复 reconcile；文字恰好完整一次，最终 token 总量等于服务端总量。

### F11：切换 Run 后旧异步响应可能覆盖新视图

**证据**：[runs.ts](../../web/src/stores/runs.ts) 的 `reconcile()` 在 await 获取摘要后，
没有验证当前 `runId` 是否仍为请求时的 ID，就更新共享 status、finalAnswer、usage 等字段。
`watch()` 切换 Run 会复用这些状态；关闭流不会取消已经发出的摘要请求。

**触发例与影响**：A 的摘要请求较慢，用户切换到 B，随后 A 返回，B 的视图被写入 A 的状态、
答复或用量。这是同一前端状态容器的竞态，不等于已经证实后端跨用户越权。

**建议与验收**：为每次 watch 建立订阅代次或独立 Run 状态，所有异步回调提交前核对 ID/代次，
必要时取消旧请求。用可控 Promise 令 A 在 B 之后返回，验证 B 不受影响；同样覆盖 reset、
退出登录和手动重试。流结束但权威摘要获取失败时保留未知/待核实状态，不凭 EOF 推定成功。

### F12：上传校验与运行创建缺少失败清理

**证据**：[runs.py](../../server/routes/runs.py) 在会话处理及创建 Run 前逐个读取、写入上传；
`await part.read()` 读完整文件后才检查字节上限，后续文件超限直接抛错，没有本次目录清理。
文件名扁平化后以 `write_bytes()` 写入，没有重复名或归一化冲突处理。

**影响**：第二个文件超限、数据库/提交失败时，之前写入的文件可能成为无 Run 索引的孤儿；
同名文件会互相覆盖；应用层字节上限不能限制 `part.read()` 的单次内存读取。
代理或 multipart 解析器可能另有限制，实际部署限额仍须核验。

**建议与验收**：先完成身份/会话准入，再分块限额写入暂存区；明确文件/总请求上限，
拒绝冲突名或生成唯一存储名，保留原始显示名。Run 创建与入队失败需有清理/补偿契约。
验证多文件中途超限、重名/扁平化碰撞、取消上传、数据库失败、入队失败；没有未登记残留，
不覆盖已接受文件，不通过真实用户目录试验。清理策略衔接 F07。

### F13：轨迹读取与事件缓冲缺少容量边界

**证据**：[relay.py](../../server/relay.py) 的 `trajectory_tail()` 每 250 ms 从文件开头扫描；
`trajectory_records()` 全量读为列表，async 路由直接同步执行且没有分页上限。
relay 的合并队列及 [orchestrator.py](../../server/orchestrator.py) 的订阅队列均未设 maxsize；
前端 [runs.ts](../../web/src/stores/runs.ts) 将每个收到的事件追加到 timeline。

**影响与边界**：大轨迹、多订阅者、慢浏览器会放大扫描和内存成本；局部丢 delta 不能给整个
缓冲链提供硬上限。本次未做压测，不宣称已发生 OOM 或给出未经测量的容量数字。
仅增加历史页“展开”不能解决服务端已经全量读取的问题。

**建议与验收**：增量文件偏移与断行处理、受控分页、阻塞 IO 脱离事件循环；队列与 UI 缓冲
有边界，背压不丢控制/终态，恢复衔接 F09/F10。用合成大轨迹和慢消费者压测，记录并事先
约定响应延迟、内存、扫描量及并发预算；超过预算可感知降级，取消订阅及时释放资源。

### F14：排队 Run 的历史上下文没有明确截止点

**证据**：[orchestrator.py](../../server/orchestrator.py) 在 `submit()` 中先写用户消息再入队；
`_spawn()` 启动时读取会话全部 turns，仅剔除当前 Run 自己的消息，未限定消息序号截止点。
[history.py](../../server/history.py) 提供 limit，但该调用链未传 limit 或 token 预算。

**触发例与影响**：前一个 Run 仍运行时用户依次排队 A、B；A 启动时 B 的问题已写入，
所以 A 的“历史”会包含尚未轮到执行的 B。后续资金/价格更正可能提前影响 A，
也使“当时依据什么分析”难以说明。全量转录另会随会话增长放大上下文输入；
是否实际超窗取决于工作流压缩策略，不能据此宣称已经超窗。

**建议与验收**：定义请求提交边界、执行时前序结果的纳入规则及历史版本；
排队消息和即时 steer 的语义须不同。记录输入快照/截止序号，明确长会话预算与摘要来源；
真实资金等关键事实按业务版本读取，不能只依赖转录或摘要猜测。
用阻塞假 worker 稳定排队 A/B，断言 A 看不到 B，B 按既定规则看到 A 的结果；
取消、失败、重试和长历史均可复现同一上下文选择规则。

### F15：运行落账与崩溃恢复缺少一致性及幂等

优先级：P1；关联：PR-RUN-01/02、PR-GOV-01/03。

**动态证据**：重启恢复将 summary 中的答复写入 Run，却没有补回会话消息；有轨迹/产物文件时，
usage 与产物索引仍为空。重复处理同一个 `run_finished` 生成两条助手消息。队列首项启动失败后，
后续项不再执行。缺失轨迹被计量为 0，无法区分“未计量”和“确实零用量”。

**代码根因**：[orchestrator.py](../../server/orchestrator.py) 的终态消息、Run、usage、产物分别提交，
`_finished` 在数据库写入前置位；`_drain_session()` 没有单项异常恢复；
`reconcile_orphan_runs()` 只更新 Run。已终态但缺少 usage/产物的 Run 不在启动恢复扫描内。
[worker.py](../../server/worker.py) 先发终态，再生成 diff 和非原子写 summary；summary 没有显式完成版本，
最终文本静默截取 50,000 字符。不能把其存在当作全部落账成功。

**环境准备补查**：启动恢复扫描共享库全部活跃 Run，仅排除本进程 handles；第二个 API
可能将原进程任务误标失败/停止。此项为源码证据，未在现有服务上做双进程故障测试。
在未实现并验收跨进程任务所有权/存活判定前，不支持以多个 API 进程共享业务库来并行验证；
E2 使用独立测试库。正式部署也须核验多 worker、副本及滚动发布是否触发此问题。

**修复/验收**：明确 queued/running/finalizing/terminal 或等价状态契约；先保存可恢复结果，
再发布可供用户确认的完成状态。Run/助手消息幂等，派生索引可补算、有未完成标记；
启动/定期恢复扫描包含“终态但落账不全”。启动失败落失败原因且不阻塞后续 Run。
区分未知用量与零，summary 原子替换、标明完整性/截断；故障注入覆盖每个提交边界。
不要求数据库与文件做不可实现的同一事务，要求可检测、可重试、可恢复。

### F16：消息序号与关系约束不足

优先级：P1；关联：PR-RUN-01、PR-GOV-01/06。

**动态证据**：8 个并发 `append_turn()` 在临时 SQLite 中获得重复 seq；
`PRAGMA foreign_keys` 返回 0。跨用户提交 F08 在各关联实体都真实存在的情况下仍被接受。

**代码根因**：[store.py](../../server/store.py) 使用 `MAX(seq)+1`，Turn 没有
`UNIQUE(session_id, seq)`；SQLite 初始化仅设置 WAL 和 busy timeout。
Run 的会话与用户是两个独立外键，没有约束两者归属一致。
会话串行执行 worker 不等于提交消息串行，不能代替数据库并发控制。

**修复/验收**：事务内分配序号/锁或可靠序列加唯一约束；SQLite 每连接启用外键，
迁移前盘点并修复历史重复/孤儿；Run 与 Session 的归属在服务准入和适当数据库约束中一致。
PostgreSQL 需另做同类并发/约束测试；不能把 SQLite 测试结果称作 PG 生产复现。
现有测试中“随机用户 ID 写会话成功”的行为需要改为完整合法 fixture，不保留绕过约束的惯例。

### F17：产物根目录与回滚基线可经符号链接越界

优先级：P1；关联：PR-GOV-06、PR-RUN-06。

**动态证据**：将合成 Run 的 `ws/outputs` 替换为指向测试外部目录的符号链接，
`resolve_artifact_path()` 接受该外部文件。将 `diff/base/0000.bin` 指向外部合成文件，
真实 revert 接口把其内容复制进 outputs。普通子文件越界符号链接与 `../` 保护仍通过。

**代码根因**：[artifacts.py](../../server/artifacts.py) 用 `root.resolve()` 重新定义可信边界；
[diff.py](../../server/diff.py) 的 baseline 只取 basename 后 `is_file/read_bytes`，
没有拒绝链接或验证基线实际根；revert 的可写根也需同类审计。

**边界**：复现由测试预先构造链接，证明文件读取/回滚边界缺口；
尚未证明普通远程用户可通过当前暴露工具创建这些链接，也未访问任何真实外部文件。
这是“可变目录被信任”的独立问题，移动目录本身无法修复。

**修复/验收**：可信存储根与 Run 根绑定，验证路径各层/禁止关键目录和基线链接，
并考虑检查到打开之间的竞态。输入和可执行工作区与审计/基线的写权限分离。
覆盖根、父目录、基线文件链接及并发替换；真实部署另验进程身份、挂载和 native 权限。
F01 迁移需设服务专用目录权限，不能照搬默认 755 就宣称用户数据隔离完成。

### F18：产物索引与回滚后的文件不一致

优先级：P1；关联：PR-RUN-06、PR-GOV-01。

**动态证据**：真实 revert 接口成功恢复旧文件后，数据库 `Artifact.sha256` 仍是新文件哈希。
文件工具以合法物理绝对路径建立快照后，revert 拒绝同一路径，返回 outside_roots。

**代码根因**：[routes/runs.py](../../server/routes/runs.py) 只调用 revert，不刷新产物索引；
[diff.py](../../server/diff.py) 保存原始路径作为 manifest 键，回滚解析器却只接受
`/workspace`、`/outputs` 别名。迁移目录后物理绝对路径还会失效。
[store.py](../../server/store.py) 的 `record_artifacts()` 只 upsert，没有删除不存在的旧行。
扫描超过 500 个文件只截断，无索引完整性状态；这项为源码确认，未做容量压测。

**修复/验收**：manifest 存储受控相对定位及格式版本；统一记录/回滚路径契约，
兼容旧绝对路径且不信任任意数据库/manifest 路径。回滚后重新计算相关 size/hash、
处理已删除条目并记录产物版本或失效状态；补算可幂等执行。
覆盖恢复、删除、新增、根目录迁移、部分回滚失败；下载内容与索引/版本一致。

### F19：存储与迁移故障缺少就绪门禁

优先级：P1；关联：PR-GOV-01。

**动态证据**：将数据库探活替身设为失败，`/healthz` 仍返回 200/ok。
这是就绪检查缺失，不代表单纯进程存活接口本身必须承担所有探活职责。

**源码证据**：[app.py](../../server/app.py) 吞掉初始化和孤儿恢复异常；现有健康接口恒定成功。
[Dockerfile.web](../../deploy/Dockerfile.web) 默认直接启动 uvicorn，没有迁移前置；
外部部署可能手动执行迁移，本次未调查其操作历史。`create_all` 不能升级已有表。
临时空库通过 Alembic 升级后的表/列集合与 ORM 一致，这是正向验证；未验证 PG 升级锁及恢复。

**修复/验收**：衔接原加固计划 T8，区分 liveness/readiness；数据库不可用、schema 版本不符、
数据根不可写/未挂载时明确不就绪。迁移具有独立步骤和失败阻断，不能吞异常后继续接任务。
验证空库、旧库升级、错版本、只读目录、磁盘满和数据库断连；保留旧版回退/兼容策略。

### F20：Run 模型快照与启动状态未接入持久化

优先级：P1；关联：PR-GOV-01/03、PR-RUN-01。

**动态证据**：配置合成默认模型后提交 Run，`llm_snapshot_json` 仍为空。
真实 frame pump 处理 `run_started` 后，数据库仍 queued，`started_at` 为空。

**源码证据**：[store.py](../../server/store.py) 有 `build_llm_snapshot()` 和相应列，
但 [routes/runs.py](../../server/routes/runs.py) 创建 Run 未传快照；
[orchestrator.py](../../server/orchestrator.py) 到启动时才解析默认连接，也不落启动时间。
因此“表里有列”不能作为快照功能已实现的证据。

**修复/验收**：明确排队期间修改模型配置的语义；按实际执行配置保存不含密钥的模型、
供应商/连接、参数及 workflow/profile 版本或可复现引用；持久化启动、结束、原因及配置来源。
记录 fallback 实际发生情况，不用提交时过期的快照冒充执行配置。
覆盖排队后配置变更、默认连接失效、启动失败、重试，历史 GET 和用量归属准确。

### F21：用户纠正与审批决定缺少持久追溯契约

优先级：P1；关联：PR-RUN-04/05、PR-GOV-02、PR-BIZ-02/06。

**源码确认，尚无完整动态复现**：[orchestrator.py](../../server/orchestrator.py) 的 steer
写 stdin 后发送内存事件；[steer.py](../../server/steer.py) 只在内存排队并注入。
[approval.py](../../server/approval.py) 的请求/决定发实时事件，gate 和授权集合仅驻内存；
`persist` 分支实际也只授权本 Run。未见对应控制动作写入业务消息或审计的路径。
后续 Run 历史只读取 turns，不能保证重新获得先前 steer 中的真实资金/价格纠正。

**影响**：收到/排队/实际采用无法长期区分；刷新可能丢待审批界面，
后续分析可能失去用户纠正。工具结果能够部分反映拒绝，不等于完整记录谁在何时批准了什么。
需审计 runtime 格式能否保留部分注入文本，不能断言所有轨迹格式一律没有该文本。

**修复/验收**：定义控制记录 ID、动作人、Run、请求/采用/拒绝/超时状态与采用轮次，
幂等持久化并支持待处理状态重建；关键事实纠正衔接业务版本/快照。
`persist` 应实现真实跨 Run 规则或改成准确范围文案/API，不扩大已有授权。
断线前后、未采用即结束、审批超时、重启、下一轮历史、权限与脱敏均须验收。

## 5. 修复顺序与职责（v1.4 更新）

0. 先按环境准备方案 E0/E1 核定原部署与真实链路；F08 准入、F17 文件边界优先。
   F15/F18 中影响目录迁移的恢复、定位与索引须修复或提供已验证兼容方案；
   F16/F20 等不全部设为迁移前置。F09/F10 可并行推进，F19 衔接 T8。

1. F02 构建排除、F03 安全出口优先，可独立进行。
2. F01 先盘点/备份/定义兼容方案，再改根目录与挂载；F07 的最低备份能力是迁移前提。
3. F04 修复共同调用身份，再以其为基础完成 F05 历史展示；F05 依赖 F03 的安全返回契约。
4. F06 明确并实现中断完整性；F07 完成保留、清理与联合恢复验收。

复用现有轨迹观察器、业务库、HTTP/SSE 和工作台，不要求重新实现 Agent，也不把全部轨迹塞进
PostgreSQL。多实例/对象存储属于后续架构演进，不是本次全部修复的前置条件。

现有 Web 加固计划声明不修改 framework；F04/F06 的共享记录器问题需要最小范围例外，进入
实施前在任务中写清修改范围与对 CLI、工作流和 benchmark 消费者的回归验证。

## 6. 不归类为本次已证实缺陷的事项

- Web 使用 `BenchmarkSession` 初始化：属于分层整理机会，不是已经证明的运行故障。
- 新增账户、真实资金校验、业务快照、监控唤醒：属于[业务需求规格](../design/web-business-data-prd.md)
  的待建设能力，不能混称现有功能修复已完成。
- 原始轨迹与 native 工具进程的跨用户文件隔离：单纯目录移动不能解决，实际进程身份、挂载和
  权限需专项核验；本轮没有证明存在可利用的跨用户读取。
- 硬编码 ReAct 路径对其他 pipeline 的影响、失败尝试的完整计量：
  在对应契约测试中核查，不凭单处注释宣称已经完成多工作流追溯。
  流式背压后的文字补全已在 v1.1 确认存在实现缺口，移入 F10，不再只列为待调查项。
- 未获取到的模型内部思考不属于可补齐数据；系统不得生成假的推理文本填补空白。

## 7. 后续修复提交的完成证据

每项 issue 需记录修复前复现、修复后验证、涉及文件、历史兼容性、部署/回退影响。文档或静态
检索检查通过，不等于容器、接口、浏览器和恢复场景通过。不得只因代码已合并把未执行的验收勾选。

运行时改动执行对应精确测试与仓库要求的检查；共享 observer 改动补 CLI/工作流兼容回归。
测试使用合成用户、虚构密钥和隔离目录/数据库，不访问真实模型或生产数据作为默认验证方式。
需真实供应商或部署环境的验证，单独声明前提与未完成项。

F11 与 F09 一同验收切换/重连竞态；F12 衔接 F07 清理，F13 提供容量验收边界，
F14 衔接业务上下文快照。上述任务不意味着业务快照、价格监控已经实现。

本报告完成的是发现归档、隔离复现与修复任务准备，21 项问题的实现状态不因此改变。
双用户接口及部分故障/竞态已在隔离环境复现；真实浏览器、PG、容器恢复、磁盘故障和容量验收
仍未完成，不能据此宣称“已无遗漏”或生产验收通过。F15—F21 与迁移的顺序见全面复核记录。

## 8. 修复执行记录（2026-09-30）

本节记录本轮代码修复与验收。上一段“21 项状态不因本报告改变”针对报告 v1.4 当时的结果；
此后已按下表实现并跑通隔离契约检查。

**验收命令与结果**（隔离运行器：临时数据根 + SQLite，禁网络/子进程）：

```bash
.venv/Scripts/python.exe .scratch/web-runtime-trace-hardening/audit/run_audit.py \
  --audit-report <name>.json
```

修复前 `4 通过 / 20 失败`，修复后 **`24 通过 / 0 失败`**（同一批契约检查，未放宽任何断言）。

| 编号 | 实现位置（要点） | 契约检查 |
|---|---|---|
| F08 | `server/routes/runs.py` 提交前完成会话归属准入（外部/已删会话 404 且零副作用）；`server/store.py::ensure_session` 失败即拒绝；`server/orchestrator.py::_session_uuid` 命名空间按用户隔离 | `test_f08_submit_rejects_foreign_session_without_mutation` |
| F01 | `server/config.py::canonical_run_id` + `run_dir_for` 统一 ID 规范形式；`runs.py` 控制/事件路由按同一形式取句柄；**目录迁移（本机）**：`runs_root` 默认移到源码树外（Windows `%LOCALAPPDATA%\frontier-agent\web\runs`，POSIX XDG），移除无消费者的 `uploads_root`；`scripts/run_retention.py migrate-runs-root` 迁移本机 4 个 run 目录 + 更新 DB `run_dir` + 清理 99 个孤儿磁盘目录 | `test_f01_uuid_returned_by_api_reads_same_trace`；迁移后 `inspect_trajectory` 读到 `state: complete`；`server/runs` 清空 |
| F03 | `server/relay.py::trajectory_records_for_egress`：`/trace` 与 SSE 共用同一脱敏出口，记录形状不变 | `test_f03_trace_uses_same_redaction_as_replay` |
| F04 | `frontier_agent/components/observers/trajectory.py` JSONL 记录保留工具调用 ID（framework 最小范围例外，见下） | `test_f04_observer_call_id_survives_jsonl` |
| F12 | `server/routes/runs.py` 上传批次失败即回收整个 per-run 目录，不再遗留孤儿文件 | `test_f12_rejected_batch_leaves_no_uploaded_files` |
| F14 | `server/orchestrator.py::_turns_as_of_submission`：历史以本 Run 提交时刻为截止 | `test_f14_queued_future_message_excluded_from_history` |
| F15 | 终态帧幂等；`_drain_session` 单次启动失败不中断队列且任务结束可自愈；孤儿收口同时恢复消息、产物索引与用量；`server/usage.py` 区分 `complete/partial/unavailable` | 4 项 F15 契约 + `test_queue_continues_after_launch_failure` |
| F16 | `server/store.py` 每连接 `PRAGMA foreign_keys=ON`；`turns` 唯一索引 + `append_turn` 冲突重试；迁移 `0003_turn_seq_unique` | `test_sqlite_declared_foreign_keys_are_enforced`、`test_concurrent_message_sequence_is_unique` |
| F17 | `server/artifacts.py::_trusted_outputs_root` 拒绝符号链接根；`server/diff.py` 拒绝符号链接基线 | `test_artifact_root_symlink_cannot_rebase_containment`、`test_revert_rejects_symlinked_baseline` |
| F18 | manifest 存平台规范显示路径；回滚同时接受规范路径与宿主绝对路径；回滚后 `sync_run_artifacts` 重算索引并清理失效行；显示路径改用 POSIX 语义 | `test_revert_updates_artifact_hash_index`、`test_absolute_file_tool_path_can_be_reverted` |
| F19 | `server/app.py` 健康检查纳入存储探活（503 + `storage_unavailable`）；后半：新增 `server/readiness.py`（head 由 `revision`/`down_revision` 链推出、不 import 迁移模块；打戳必须等于 head，未打戳要求全部 ORM 表在；数据根用真实写探针），`/healthz` 只报连通（`check_db` 改 `SELECT 1`），`/readyz` 追加 schema 与数据根；`app.lifespan` 同一门禁，未就绪且非 `SERVER_DEBUG` 抛 `StorageNotReadyError`（并跳过孤儿 reconcile）；新增 `deploy/entrypoint.web.sh`（`alembic upgrade head` → `exec uvicorn`，`set -e` 阻断），`Dockerfile.web` CMD 改指它；`deploy/README.md` 增迁移与门禁一节 | `test_health_distinguishes_unavailable_storage`；`tests/test_web_f19_schema_gate.py` 16/16（负向对照 6 条失败；新增 `test_data_root_probe_writes_real_bytes`——E3 磁盘满注入发现 0 字节探针在满 tmpfs 上误报 ready）；真实镜像 `frontier-agent-web:f19` 实测：空库启动依次迁移 0001→0004、`alembic current`=`head`、两探针 200；不可达库→exit 1 且 uvicorn 未启动；库停在 0003→`schema_behind` exit 3；debug 下 `/readyz` 503 而 `/healthz` 200；断连→两探针均 503 |
| F20 | 提交时落非密钥模型快照与配置引用；worker `run_started` 帧持久化 `running`/`started_at` | `test_submit_records_nonsecret_model_snapshot`、`test_run_started_event_updates_persistent_status` |
| F09 | `Orchestrator.has_worker` + `server.routes.runs._live_queue_for` 按权威状态判定：本进程无 handle 且行状态非 queued/running → replay-only，不再订阅死队列；本进程结束的流由 `_closed_stream_ids` 兜底（后端契约）；前端游标语义：`Orchestrator.steer` 的 `steer_queued` 改用 `steer_seq`（不再占用轨迹游标 `seq`），`web/src/sse.ts` 新增 `CONTROL_EVENT_TYPES` 使控制帧不推进游标，浏览器端到端仍待验收 | `test_f09_late_subscription_finishes`、`test_f09_finished_in_another_process_replays_and_ends`、`test_f09_active_run_without_a_handle_still_subscribes`、`test_live_queue_decision_uses_the_persisted_status`、前端审计 `F09_steer_sequence_is_not_trajectory_cursor`（由 10 !== 0 转为通过） |
| F07 | 新增 [scripts/run_retention.py](../../scripts/run_retention.py)：`manifest`（逐 run 存储引用 + sha256 + F06 轨迹状态）、`plan`（默认 dry-run，`expired/retained/active/unfinished/missing/out_of_scope` 六类，删除需 `--apply --yes` 且复核包含关系）、`verify`（文件齐全与校验值）、`check`（只读孤儿与行数）；缺失与过期严格区分 | `tests/test_web_f07_retention.py` 20/20（负向对照 5 条失败）；文件侧 CLI 演练四类 run 正确；真实 `pg_dump`→独立库 `pg_restore` 行数逐一一致（**但只建成 4/9 外键**，孤儿阻塞） |
| F10 | [web/src/stores/runs.ts](../../web/src/stores/runs.ts)：按轮保存文本（`turnTexts`），回放的整轮记录**替换**该轮而非被跳过（可修复背压丢帧），`streamedTurns` 移除；usage 计量移到文本判定**之前独立处理**；`reconcile` 用新增的 `usageTotalsFrom()` **替换**总量而非累加（[statusbar.ts](../../web/src/utils/statusbar.ts)） | 前端审计 `F10_full_replay_repairs_missing_live_text`、`F10_live_turn_still_counts_replay_usage`、`F10_final_usage_reconciliation_is_not_additive` 三项 failed→passed（负向对照逐项失败） |
| F11 | [web/src/stores/runs.ts](../../web/src/stores/runs.ts)：订阅代次 `generation`（`watch`/`reset` 递增），`reconcile` 在 `await` 后校验 runId+代次，过期响应整体丢弃；摘要获取失败时给可见「待核实」提示而非按 EOF 推定成功 | 前端审计 `F11_old_run_summary_cannot_overwrite_current_run` failed→passed（负向对照移除校验即失败） |
| F06 | 新增 [server/trajectory_status.py](../../server/trajectory_status.py) 定义并判定 `complete/partial/unavailable`（终端 `{"t":"end"}` 是否存在；半行不掩盖有效行）；`/trace` 返回 `completeness`，历史页在记录旁告警；写入屏障：`TrajectoryFileObserver._close_jsonl` 关闭前 `fsync`（framework 最小范围例外）；[tech-stack.md](../../docs/tech-stack.md) 收窄「完整轨迹 / SIGKILL 安全」四处表述 | `tests/test_web_f06_trace_completeness.py` 10/10（负向对照：判据恒为 complete → 2 条失败）；共享 observer 回归 21/21 |
| F05 | 展示逻辑抽到 [web/src/utils/traceView.ts](../../web/src/utils/traceView.ts)：推理按轮折叠且只展示散文型（缺失/空/加密签名块各有明确文案，不伪造），工具结果 300 字符预览 + 「继续读取」按 2000 字符有界解锁并显式剩余/总数，切片按 code point；`RunDetailView.vue` 消费之，F03 脱敏边界未移动 | 前端审计 `frontend-f05-audit.mjs` 10/10（负向对照 3 条失败）；`tests/test_web_f05_trace_projection.py` 4/4；`vite build` 通过 |
| F02 | 根 [.dockerignore](../../.dockerignore) 排除 `server/runs/`、`uploads/`、`data/`、`server/*.db(+wal/shm)` 及前端产物与本地大目录；附带修 `**/__pycache__/`（原规则只匹配根级）与惰性 `web/.dockerignore`（规则镜像到根） | `tests/test_build_context_ignore.py`（40 项，含负向对照）；真实仓库 `COPY . /ctx` 探针：33.18 MB / 1110 文件，运行数据全 absent、构建输入全 present |
| F21 | 新增 `control_records` 表（`server/store.py` + Alembic `0004_control_records`）与状态机：steer `undelivered/queued/adopted/dropped`、approval `pending/adopted/rejected/expired/abandoned`；父进程落库（worker 仍不 import `server.store`，只发 `control_applied` 帧）；`ApprovalDecision.source` 区分用户拒绝/超时/停止；终态收口接在 `_spawn` 收尾与 `reconcile_orphan_runs`；生效 steer 写成带 `[运行中补充方向] ` 前缀的 `turns` 行（复用 F14 截止点）；`server/routes/runs.py` 新增 `GET /controls`；前端 `steer_applied` 登记进 `CONTROL_EVENT_TYPES`、刷新时用 `GET /controls?status=pending` 重建待审批弹窗；D1 文案修正（「保存为永久规则」→「本次运行内始终允许」）| `tests/test_web_f21_control_history.py` 14/14（负向对照 4 条失败）；`tests/test_web_p3_steer.py` 12/12（含真实 worker e2e：`adopted` + turn 落库）；隔离审计契约 24/24；前端审计新增 F21 ×5（10/10，负向对照 2 条失败）|

**framework 最小范围例外（F04）**：仅改动 `TrajectoryFileObserver.on_llm_response` 的 JSONL
记录字段（新增 `tool_calls[].id`），不动调用协议、不动工具执行、不改其他观察器。
需回归的消费者：Web 轨迹回放（`server/relay`）、CLI/apodex 轨迹读取、benchmark 结果解析。

**随修复一起调整的既有测试**（非新契约，而是原测试编码了旧行为）：

- `tests/test_history_t26.py`、`test_sessions_t27.py`、`test_artifacts_t29.py`、
  `test_web_p2_diff.py`、`test_web_p3_revert.py`、`test_web_p3_approval.py`：补齐 runs/turns 的
  用户、会话与运行父行。它们是“容许未关联实体写入”的用例；PostgreSQL 一直强制外键，
  只有 SQLite 在 F16 前静默放行。
- `tests/test_history_t26.py::test_ensure_session_idempotent`：改为“同属主幂等 + 他人被拒”。

**非 F 清单的可移植性修复**（本机 Windows 复现，随 F 缺陷一并处理）：

- `server/orchestrator.py::_signal_worker`：`os.killpg/getpgid` 缺失时**不发送信号**（显式早返回并记 debug），
  由调用方原有的有界等待 + 升级路径完成回收。原先该调用在回收路径无条件执行，抛出的
  `AttributeError` 逃出 `contextlib.suppress`，使产物索引、用量入账与池槽位释放一并被跳过，
  并终止会话 drain 任务——真实链路实测中每次运行泄漏一个 worker 池槽位，两次后服务无法再启动任何 Run。

  **曾尝试并否决的替代方案**：无进程组 API 时改用 `proc.terminate()/kill()`。它只覆盖 worker 自身、
  无法覆盖其派生的子进程，且在本平台**把编排器收尾卡死**：隔离停止/升级用例
  `tests/test_stop_t28.py` 由「3/3 正常完成（36s）」变为「3 次中 2 次无限挂起」。定位过程：
  二分确认由该改动引入；边界探针显示执行停在信令调用内部（`kill:enter` 之后无后续日志）；
  独立最小复现中 `terminate()` 立即返回，说明失败依赖当时的传输/进程状态而非调用本身。
  判定「进程组是不可分割的回收单位」，故回退为不发信号，保留原语义。

  该修复的直接证据：`tests/test_usage_t211.py` 由修复前 `1 失败 / 9 通过（62s）` 变为
  **`10 全部通过（4s）`**——此前被跳过的池槽位释放使同进程内后续运行无法启动。
- `plugins/tools/_sandbox.py::host_user_token` 与 `_writer_core.py` 同式回退：`os.getuid`
  仅存在于 POSIX，缺失时会让 `resolve_runtime_path` 抛错，静默禁用首次快照与回滚。

**部署注意**：新唯一索引经 `server/alembic/versions/0003_turn_seq_unique.py` 下发，
现有库需执行一次 `alembic upgrade head`（`init_db()` 的 `create_all` 不会改动已存在的表）。
迁移在存在重复 `(session_id, seq)` 时会显式报错而不改数，由人工决定如何重排。

**仍未完成（不得视为已验收）**（2026-10-01 更新：F01 容器实测、F02 真实镜像构建、F07 联合恢复演练与孤儿处置已完成，
下段已按其现状改写）：F02 的**历史已发布镜像是否含数据已调查完毕（2026-10-01 晚：历史受影响镜像集合为空——
修复前从未成功构建过 web 镜像，现存 3 个镜像（全部 2026-10-01 修复后构建）逐层核对 server/runs/uploads/
data/.env/*.db/密钥全部 absent，见 `audit/f02-historical-image-data.json`）**（真实镜像构建已于 2026-10-01 补跑、
镜像层核对通过，registry 阻断系瞬时故障，见
[工单 02](../../.scratch/web-runtime-trace-hardening/issues/02-build-context.md)）、F05 的**浏览器 DOM 层验收已于 2026-10-01 完成**（工单
[05](../../.scratch/web-runtime-trace-hardening/issues/05-history-trace-ui.md) 已 closed：验收中发现并修复一处"已结束 Run 的轨迹页只渲染元信息框、0 条记录"的渲染缺陷）、F06 的**真实故障注入**（SIGKILL 已于 2026-10-01 在 WSL 真实注入通过：mock 流中窗口 kill -9 worker →
API 存活、Run 立即收口 `stopped/killed`、`/trace` `completeness=partial`，协作式取消已在 E1 首批覆盖，见
[工单 06](../../.scratch/web-runtime-trace-hardening/issues/06-trace-completeness.md)）；**运行级磁盘写满已于
2026-10-01 下午完成**（WSL 隔离库 + tmpfs 真实 ENOSPC：在飞 run 不挂起、`/trace` 判定不误报，
但**发现 3 处新缺陷并已修复**——满盘时新提交的 run 永久卡 `queued`（已修：提交路径
消费数据根探针满盘 503 + `_drain_session` 启动失败即写终态 `failed`）、轨迹/用量丢失静默
（已修：干净完成但轨迹 0 字节时助手轮追加「存储降级」可见标记）、0 字节侧车残留
（已修：`summary.json` 原子写 + 清理 `.tmp`/0 字节 spool），回归
`tests/test_web_f22_disk_full.py` 6/6，见
[工单 22](../../.scratch/web-runtime-trace-hardening/issues/22-disk-full-queue-wedge.md)）；
尚余**断电耐久**与**请求尝试身份**（失败·重试是否入契约）——契约已定义并有合成文件证据；
**→ F06 两项均已收口（2026-10-02）**：断电耐久以"持久化链路审计 + `worker.persist_summary`
（tmp fsync → rename → 目录 fsync + 轨迹终态 fsync）+ 断电后果文件层等价注入"完成
（`tests/test_web_f06_power_durability.py` 8/8）；请求尝试身份冻结契约级别为 **summary-only**——
trajectory observer 新增 `on_llm_attempt` 落盘 `t:"attempt"` 身份行（每次 provider 尝试含失败/重试，
不落请求响应体、不进 JSON envelope），relay 出口（SSE + /trace）过滤但物理行号计入游标，
completeness/usage 聚合语义不受扰（`tests/test_web_f06_attempt_identity.py` 4/4，web 全量 200 passed）。
F07 的
**运维备份脚本与异地存放、密钥/缺文件/过期清理的组合恢复、T6 第 2–3 步（`ON DELETE` 与会话删除语义）、保留期定值**
（联合恢复演练与孤儿处置已于 2026-09-30 完成，见
[工单 07](../../.scratch/web-runtime-trace-hardening/issues/07-retention-recovery.md)；**运维备份脚本已于
2026-10-01 晚交付并验证**：`scripts/web_backup.py`（`pg_dump -Fc` 包装 + `pg_restore --list` 校验 +
sha256 清单 + `--keep-days` 保留期 + fail-closed 目标 + `--out-dir` 可指向异地挂载），真实业务库备份
→ 独立库恢复演练 8 表行数一致、外键 12/12、版本 0004，见 `audit/f07-backup-script.json`；
**③④ 已于 2026-10-02（凌晨）隔离复演完成**（`audit/f07-key-ondelete-drill.json`，隔离库 + 隔离 API 零生产写）：
③ 12 外键全 `NO ACTION` 三路硬删全拒 + 会话软删（列表隐藏 / run 存档可达），建议维持现状无需迁移；
④ 错误 `master_key` 复演发现 **F07-KEY-1 缺陷候选**（run 静默改道 server-default 且快照失真，需人工决策是否改为 fail-closed）
与观察项 F07-KEY-2（密文重置无 HTTP 路由）；正确密钥/重置密文路径均恢复生效。**F07-KEY-1 已于 2026-10-02 修复**
（用户批准）：`user_llm_cred_state` 提交门禁（error → 503 零副作用）+ `resolve_user_llm_env` 解密失败抛
`LLMCredentialError`（"无配置"与"密钥丢失"分家，仅前者可回落）+ `_resolve_llm_env` 第二道防线传播；
回归 `tests/test_web_f07_key_gate.py` 6/6、web 套件 184 passed。**F07-KEY-2 亦已闭合**：新增
`PATCH/GET /api/llm-configs/{id}`（重置密文 + masked 读回，所有权校验防 IDOR）——master_key 轮换的
恢复路径全程 HTTP 化，回归 `tests/test_web_f07_key_reset.py` 4/4、web 套件 188 passed。
仍余 ⑤ 定值（推荐：备份 30 天/每日 1 次、
runs 文件 90 天、`SERVER_MASTER_KEY` 进部署清单——当前 live 以默认密钥 debug 运行、异地待挂载）
**——⑤ 已于 2026-10-02 采纳并落地 [deploy/README.md](../../deploy/README.md)**（定值节 + 密钥轮换表
补恢复路径列，定值命令实测通过）。F07 ①②③④⑤ 全部闭环，F01
**容器实测与 `SERVER_DATABASE_URL` 容器覆盖修复已于 2026-10-01 完成**（真实镜像构建 + 卷落点 + 重建后历史 Run 可读；
并暴露并修复缺口：容器内曾解析为 `localhost:5432/apodex`、`/healthz` 503，现比照 `CORPUS_DSN` 增加
`SERVER_DATABASE_URL_DOCKER` 覆盖并实测 200；工单
[01](../../.scratch/web-runtime-trace-hardening/issues/01-storage-roots.md) 已 closed）、
以及 E1 结转项——**POSIX 环境的产物/回滚复验与 F08 越权动态复验已于 2026-10-01 完成**
（E1-WSL 批次：产物索引/下载/diff/回滚真链路全过；B 账号越权提交 404 + 零副作用 + 默认会话隔离；见
[批次登记](../../.scratch/web-runtime-trace-hardening/audit/e1-wsl-batch-registry.json)），
其中**真实供应商格式差异**（浏览器 DOM 层已于 2026-10-01 验收完成，工单 05 closed）亦已验证（见下）。
**真实供应商格式差异已于 2026-10-01 完成验证**（用户批准真实调用 + 用量登记）：火山方舟
`deepseek-v4-flash` 跑 3 个隔离 run（纯问答 / 工具+审批链 / 实时流监听），F04/F06/F09/F10/F13/F15/F20/F21
在真实流下全部按设计工作；5 项真实 vs mock 差异中 4 项为观测面增强或口径差异（token 级分片密度、
thinking 字段、缓存命中 usage、模型幻觉工具被注册表 fail-closed 拒绝后自愈），1 项（server-default
快照不含模型名）登记为可观测性观察项。用量 3 run / 7 calls / 59,445 tokens 入账核对。
见 [证据](../../.scratch/web-runtime-trace-hardening/audit/real-provider-format.json) 与批次登记
`real_provider_20261001`。

**F19 后半（schema 门禁 + 迁移显式步骤）已于 2026-10-01 实现**（`server/readiness.py` + `deploy/entrypoint.web.sh`，
见工单 [19](../../.scratch/web-runtime-trace-hardening/issues/19-storage-readiness.md)）：`/healthz` 只报"数据库是否应答"
（`check_db` 改 `SELECT 1`），`/readyz` 追加 schema 版本与运行数据根可写；启动同一门禁，未就绪且非 `SERVER_DEBUG`
即拒绝服务；容器入口把 `alembic upgrade head` 作为显式失败阻断步骤。**2026-10-01 E3 注入补齐（E1-WSL 批次）**：
真实只读挂载（非 debug 启动 `StorageNotReadyError: data_root_unwritable` exit 3、debug 下 `/readyz` 503 而
`/healthz` 200）、磁盘满注入（**发现并修复探针真缺陷**：0 字节写在满 tmpfs 上仍成功——数据页耗尽而非 inode，
`probe_data_root` 改写真实字节 `b"readyz-probe"`，回归 `test_data_root_probe_writes_real_bytes`，套件 16/16）、
compose `/readyz` healthcheck（`deploy/docker-compose.yml` 新增，镜像内实测 healthy；`caddy` 以
`depends_on: condition: service_healthy` 等待门禁通过后再接流量）。
**已闭环（2026-10-01 下午）**：镜像已重建（`frontier-agent-web:head`，镜像内断言探针写真实字节、
展示投影含 `external_id`）；**旧版镜像回退演练实测通过**（新镜像 entrypoint 迁移空库→`0004`、`/healthz` 200
`/readyz {"status":"ok"}`；上一镜像对同库迁移幂等；schema 超前 `zz_future` 时上一镜像 entrypoint `exit=255`
（alembic 无法定位 revision）、新镜像直起 uvicorn `exit=3` `StorageNotReadyError: schema_ahead`，见
`audit/f19-rollback-drill.json`）；**整栈 compose 就绪门禁实测通过**（不可达库时 compose 报
`dependency failed to start: container e1wsl-api is unhealthy`、`caddy` 容器 `created` 但未启动、站点不可达；
空库就绪后 api `healthy` → caddy 启动 → HTTPS 根 200 且返回前端 `index.html` 标题，见 `audit/f19-stack-gating.json`）。
**已闭环（2026-10-01 晚）**：业务库 `apodex` 已迁移至 **`0004_control_records`（head）**——
0003 走 `alembic upgrade 0003_turn_seq_unique`（预检无重复 `(session_id, seq)` 后建唯一索引）；
0004 的 `control_records` 表因 live API 的 `create_all` 已先建出（含 2 行 E1-WSL 批次审批记录），
已核对列与索引与迁移完全一致后 `alembic stamp 0004_control_records`（不重建、不丢数据）；
迁移前后 `runs=757/turns=1098/sessions=142/users=31` 全不变，live API `/readyz` 由 503 `schema_behind` 翻绿
**`{"status":"ok"}`**。迁移前已 `pg_dump` 备份（`~/backups/apodex-20261001-161402.sql`）。
**T8 真实 PG 重启时序已于 2026-10-01 实测闭环**（隔离 `t8pg`+`t8api`，业务库未触碰，见
`audit/t8-pg-restart.json`）：`docker stop` → `/healthz`/`/readyz` 双双 **503** 全程 fail-closed；
`start`/`restart` → ~2s 内双双翻 **200**；API 进程存活不假死。「停库 503 / 恢复 200」成立。

**F13 容量边界已于 2026-10-01 修复并动态验证**（先基线后修复，证据 `audit/f13-capacity.json`，
工单 [13](../../.scratch/web-runtime-trace-hardening/issues/13-capacity-bounds.md) 转 `ready-for-human`）：
修复前基线（合成轨迹 20,000 行 / 2,328,688 B）证实三处缺陷——`trajectory_tail` 每 250 ms poll 全文件重扫
（2 轮 poll 迭代 40,000 行）、订阅队列无界（灌 10,000 条 delta 后 qsize=10,000）、`/trace` 全量同步读跑在
event loop 上。修复：`server/relay.py` 改字节偏移增量读（`_locate_offset` 把 T3.1 行号游标换算为字节偏移，
断行 defer、终态可解析残尾仍发出、截断/轮转重扫）+ `trajectory_page` 分页（`limit=0` 保持历史全量契约）；
[orchestrator.py](../../server/orchestrator.py) 订阅队列 `maxsize=256`（满时丢 droppable delta、终态/哨兵挂
waiter task）；[runs.py](../../server/routes/runs.py) `/trace` 改 `asyncio.to_thread` + `after`/`limit` 游标。
修复后实测：tail 总字节读 == 文件大小（每字节只读一次）、delta 洪峰队列封顶 256 且 `run_completed`/哨兵必达、
分页无重叠无缺口。回归 `tests/test_web_f13_capacity.py` 8/8；web 套件 206 passed（6 error 为 p2_files FK
既有环境问题）、ruff 全绿、pyright 仅既有错误。测试侧发现并绕开的陷阱：`wait_for(gen.__anext__, timeout)`
会取消 `__anext__` 并向生成器注入 CancelledError 使其终止——断行 defer 只能用真实 sleep 推进 poll 验证。

**F21 已于 2026-10-01 实现**（契约与验收见
[f21-control-history-contract.md](../../.scratch/web-runtime-trace-hardening/f21-control-history-contract.md) §12，
工单 [21](../../.scratch/web-runtime-trace-hardening/issues/21-control-history.md) 转 `ready-for-human`）：
`control_records` 表 + 状态机 + 终态收口 + 生效 steer 写成 `turns` + `GET /controls` + 前端刷新恢复；
**真实重启后观测已于 2026-10-01 完成**（批次登记 `restart_obs_20261001`）：live API 进程 kill + 重启，
以 3 个真实供应商 run 为材料观测——F19 `/readyz` 200、F20 run 详情/usage DB 持久化完整可读、F21 `/controls`
投影从 `control_records` 重建（adopted 审批含 external_id 完整可见）、F09 重连已结束 run 流正常关闭
（exit=0，11 条重放事件与轨迹数学吻合；closed-stream 记忆清空后由 `_live_queue_for` 双事实判定正确路由
replay-only）。F09/F19/F20/F21 真实重启后全部按设计工作，无需代码改动。浏览器 DOM 层复核已于
2026-10-01 完成，见工单 05/21；业务库迁移已于
2026-10-01 晚完成——见上方 F19 段「已闭环」。另修两处既有缺陷：隔离审计夹具随 F01
失效的 `uploads_root` 一行（曾使 24 个检查全部 setup ERROR）、`server/trajectory_status.py` 一处 SIM105 lint。
2026-10-01 E1-WSL 批次补齐真链路证据：`pending → adopted/once`（审批后 `create_file` 真实落盘）与
`pending → expired`（300s 超时 fail-closed，source=timeout 未被记成用户拒绝）均落 `control_records`；
三处 POSIX 用例（approval e2e/upload_t210/stop sigkill）9/9 通过。**遗留观察（已于 2026-10-01 下午随上游提交 `38d73bc` 修复）**：当时 `control_to_dict` 投影不含 `external_id`，刷新页从 `GET /controls` 重建待审批后拿不到 approve 所需 ID；
现已由 `38d73bc` 修复——投影暴露 `external_id`、前端 `resumeForSession` 重建弹窗并优先使用该字段，
浏览器闭环复验通过（Run 0c65cbf3：刷新→弹窗重建→批准→`adopted/once/external_id`），
见[工单 21](../../.scratch/web-runtime-trace-hardening/issues/21-control-history.md)。

**F09 的已知覆盖盲区（已按权威状态修复）**：此前的修复把「已结束的运行流」记在**进程内**的
`_closed_stream_ids`（有界 512 条），因此只覆盖「运行在本进程结束」这一条路径。对**结束于其它进程**
的运行（API 重启后、被启动期 orphan reconcile 收口的运行、或 id 已被窗口淘汰），`run_events` 仍会订阅
并等待一个永不到来的哨兵。已用隔离复现确认：重放事件正常产出、流在 5s 内不结束。

现改为按权威状态判定，不再依赖进程内记忆：`Orchestrator.has_worker` 报告本进程是否持有该 run 的
worker handle；`server/routes/runs.py` 的 `_live_queue_for` 仅在「本进程有 handle」**或**「行状态仍在
`ACTIVE_RUN_STATUSES`（queued/running）」时订阅，否则返回 `None`，由 `sse_for_run` 走 replay-only
分支——只回放轨迹后自然结束（前端把干净 EOF 视为 `completed`，再经 `GET /{run_id}` 对账终态）。
本进程结束的流仍由 `_closed_stream_ids` 兜底，用于「handle 尚在、哨兵刚发出」的窗口。
回归证据：`tests/test_web_f09_stream_termination.py` 四条用例（含「queued/running 且无 handle 仍必须订阅」
的反向守卫）；把判据临时还原为「总是订阅」后，`test_f09_finished_in_another_process_replays_and_ends`
以 15s `TimeoutError` 失败，确认该用例确实抓住修复前行为。
2026-09-30 回溯重跑三项证据均与上轮一致：隔离审计契约 **24/24 通过**（独立报告
`audit/f09-recheck-results.json`，不覆盖 `post-fix-results.json`；注意该契约只覆盖「本进程结束」，
盲区路径由 `tests/` 的回归补上）、盲区回归 **4/4 通过**、前端审计
`F09_steer_sequence_is_not_trajectory_cursor` **仍失败**（10 !== 0）。
2026-09-30 补充：**盲区本体的浏览器/多进程端到端验收已通过**——隔离栈（mock LLM + 同库双 API 进程
8471 + vite 5273 + Playwright/Edge）下，跨进程重订阅已在浏览器内实测 19ms EOF，B 上新 run 活流无回归；
完整记录见 `.scratch/web-runtime-trace-hardening/e2e/e2e-record.md`。  **F09 前端游标语义已于 2026-09-30 修复**（`steer_seq` 独立字段 + 前端控制帧不推进游标），
前端审计断言由 `10 !== 0` 转为通过，双向负向对照确认两侧都真被测到。
工单 [09](../../.scratch/web-runtime-trace-hardening/issues/09-stream-replay-contract.md)
**仅剩真实浏览器端到端验收**（steer 后断线重连不跳行），在此之前维持 `ready-for-human`。本机（Windows 原生）另有既有限制：shell 工具依赖 POSIX 语义、
`test_web_p2_diff`/`test_web_p3_revert`/`test_artifacts_t29` 等仍有与本轮无关的失败，
因此“通过”仅以隔离契约检查与逐文件基线对比为准，不代表整机验收。
