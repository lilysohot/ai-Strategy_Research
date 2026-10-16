# 47 · Web Agent 结构化语义消费接线与真实验收

Status: needs-info
Execution: 未开始
Type: runtime wiring / end-to-end acceptance
Blocked by: 无代码前置；真实消费轮待确定 Web 部署入口与 token ceiling
Real model calls: 0（未授权前保持）
Production database writes: 0

## 问题

现有证据覆盖了三个相邻但不同的能力：

- 108/109：Web HTTP 端点可从生产 structured store 读取 Claims/items；
- 43/112/113：CLI/stateful M_main 能真实消费 `corpus_semantic_query`；
- `server.profile.RESEARCH_TOOL_NAMES` 已静态包含 `corpus_semantic_query`。

这些证据尚未证明**由 Web 会话启动的真实 Agent worker**能在自身进程边界内读取生产 gen-3 structured store、把语义记录送入后续模型上下文并完成报告引用。特别是 server 默认 `sandbox_backend=native`，而 `apodex.semantic_access` 要求生产 store 在 Agent 进程中是只读文件系统挂载；只有工具名出现在 profile 中仍可能在运行时失败。

## 目标

复用现有 `corpus_semantic_query → ConsumptionLedger → corpus_submit_manifest/A4` 链路，让 Web Agent 消费与 CLI 相同的生产 publication。不得另建第二套抽取或语义查询真源。

## 实施范围

1. 从真实 Web session/run API 发起 Agent，而非直接调用 Python 查询函数或 CLI runner。
2. 验证 orchestrator → worker 的最终 `profile_overrides.agent.agent_tools` 含 `corpus_semantic_query`，并由伴随规则绑定 `corpus_submit_manifest`。
3. 为 worker 提供 `CORPUS_STRUCTURED_ROOT`，且在 worker 进程视角中为只读挂载、无可写别名；每次启动前在 writer 侧准备 SQLite WAL 侧车。
4. 保持 publication source/build/gen-3 版本不变；Web HTTP Claims/items 端点继续作为普通客户端读 API，不作为第二套 Agent 证据协议。
5. 补 Web runtime 级回归，覆盖工具缺失、store 未配置、可写挂载、失效 publication 和显式覆盖缺口。

## 预注册验收

- **W1 工具接线**：真实 worker 的最终工具清单包含 `corpus_semantic_query`；语义查询后 `corpus_submit_manifest` 伴随绑定；不得只用 `server.profile` 单元断言代替。
- **W2 正向 Claims**：通过真实 Web 会话回答一条工业源 Claims 有界问题；查询记录实际进入下一次模型请求，最终 semantic reference 为 `delivered + verified`。
- **W3 正向 items**：通过真实 Web 会话回答一条光模块 items 有界问题；同样完成 delivery、context_use 与 A4 引用闭环。
- **W4 缺口语义**：另跑一条已登记缺口问题，收到 `CS_PUBLICATION_EXPLICIT_GAPS` 并明确拒绝把空结果解释为事实或风险不存在；无记录时不得提交伪造 manifest。
- **W5 只读与版本**：Agent 运行前后 structured store 的 attempts、publication heads、manifest/object 集合不变；生产 PostgreSQL `generation/activated_at` 不变。
- **W6 Web 边界**：真实鉴权会话、run 创建、worker 执行与流式/最终响应完整；401/无 store/可写 store 均失败关闭。

## 非目标

- 不做 items 浏览页面或其他 UI；
- 不把 Claims/items 复制进生产 PostgreSQL；
- 不补抽 7+12 个登记缺口，不启动 material_relations；
- 不新增与 `corpus_semantic_query` 平行的语义查询协议；
- 不把 HTTP 端点返回 200 当作 Web Agent 已消费结构化信息。

## 起跑前待定项

1. 指定要验收的 Web 部署入口（本机 server worker、容器环境或实际部署实例）。
2. 具名冻结三道问题文本、每题 `max_turns`、并发数与总 token ceiling。
3. 选择只读边界实现：优先让 worker 复用部署层只读挂载；若部署不能提供该边界，再单独裁定是否经可信 server broker 调用现有查询实现。

## 当前零调用侦察

- `server/profile.py` 已把 `corpus_semantic_query` 放入 `RESEARCH_TOOL_NAMES`，静态工具注册无需从零新增。
- `server/worker.py` 会把 server profile override 交给 stateful workflow，但尚无本专项的真实 Web session 消费证据。
- 现有 `tests/test_web_corpus_read_chain.py` 验的是 HTTP 读端，不是 Web Agent worker；Issue 43/112/113 验的是 CLI M_main，不能互相替代。

