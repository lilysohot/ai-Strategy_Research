# Arthas / DBX MCP 接入评估

日期：2026-09-18。范围：评估两个 MCP 是否应进入 FrontierAgent 的**生产 Agent 主链路**；不评估开发者本机的临时排障/探索用途。

## 结论

当前**不应接入 Arthas MCP，也不应将 DBX MCP 直接裸挂到生产 Agent 工具表**。

- Arthas 仅在本项目需要诊断一台正在运行的 **Java/JVM** 服务时才相关；本仓库是 Python 3.12 的 Agent 框架，当前架构与内置工具没有 Java 运行时诊断需求。因此没有即时价值，反而会把 heap dump、OGNL、动态系统属性/VM 参数、类重定义等高影响能力交给模型。
- DBX 只在项目要让 Agent 访问已配置的数据库（尤其是开发/运维排障的只读查询）时才有价值。当前仓库的数据库访问边界是受控的内置工具/服务；直接引入 DBX 的多数据库、多语句、Redis/Kafka、连接管理和可写工具，会扩大能力面并绕过本项目的统一工具 allowlist、角色过滤、审批与运行留痕契约。
- 两者可保留为**人工本机的、显式启用的开发辅助 MCP**。若未来要进入产品工作流，先用本项目的 `@tool` 包装为少量、只读、固定参数/返回契约的适配器，并将其加入显式 allowlist 与按角色授权；不要把供应商动态发现的完整工具集直接暴露给 LLM。

这与项目已有决策一致：市场数据设计已明确指出，生产主链路不能裸挂 MCP，因为它会绕过 allowlist/审批/留痕；若复用 MCP，必须由受控 `@tool` 包一层。[项目现有 MCP 决策](../../docs/plan/ths-market-data.md#33-本模块定论主链路走自建-rest-toolmcp--sdk-用在对的位置)。`ToolRegistry` 也只暴露显式 `_BUILTIN_TOOLS` 中的工具，并再按角色过滤。[工具注册表](../../plugins/tools/__init__.py)

## Arthas MCP

官方将其标为 **experimental**：它以 Streamable HTTP/JSON-RPC 暴露 29 个 Arthas Java 诊断工具，覆盖 JVM/线程/内存、类加载与反编译、方法 trace/watch/tt、文件查看等。[Arthas MCP Server](https://arthas.aliyun.com/en/doc/mcp-server.html#overview)

- 前置条件：运行 Arthas/Java 应用，设置 `arthas.mcpEndpoint=/mcp`；默认 HTTP 端口为 8563。长时诊断使用默认的有状态 STREAMABLE（HTTP/SSE）；一次性查询可选 STATELESS。[配置与传输模式](https://arthas.aliyun.com/en/doc/mcp-server.html#configuration)
- 安全：只有设置 `arthas.password` 才会启用 Bearer 鉴权；文档的默认端点示例是 `http://localhost:8563/mcp`。`viewfile` 默认能读 `arthas-output` 与 `~/logs`，环境变量还能扩大白名单。[鉴权与文件白名单](https://arthas.aliyun.com/en/doc/mcp-server.html#authentication-configuration)
- 影响：工具包含 heapdump、OGNL 任意表达式/方法调用、修改系统属性/VM options、线程中断、类编译/redefine/retransform；即使是诊断场景也可消耗资源、泄露运行时数据或改变线上进程。[工具清单](https://arthas.aliyun.com/en/doc/mcp-server.html#supported-diagnostic-tools)

**建议：不接入。** 若以后有 JVM 产品服务，建立一个只读、回环监听、强 token、短时会话的专用运维入口；仅代理 `jvm`、`memory`、`thread`、受限 `trace` 等经过审核的命令，明确排除 `ognl`、`heapdump`、`vmtool`、`sysprop`、`vmoption`、`mc`、`redefine`、`retransform` 和扩展 `viewfile` 白名单。

## DBX MCP

DBX MCP 让 AI 使用 DBX 已保存的连接，可列出连接/schema、查询 SQL/Mongo、访问 Redis/Kafka，并可管理连接、执行批量 SQL、发送消息或打开桌面 UI；具体可见工具受构建和权限设置影响。[DBX MCP 工具清单](https://dbxio.com/cn/docs/mcp#工具列表)

- 前置条件：Node.js >= 18.18、已安装 DBX 且至少有一个连接；`npm install -g @dbx-app/mcp-server` 或 `npx -y @dbx-app/mcp-server` 经 stdio 启动。JDBC/Agent 数据库还要求匹配的 Agent、驱动和 JRE。[系统要求](https://dbxio.com/cn/docs/mcp#系统要求)
- 安全基线：权限策略每次请求重新读取；可选择只读/数据读写/完全访问，同时连接只读属性、生产库保护、账号权限、连接/数据库/tool allowlist 是硬上限。DBX Desktop HTTP 默认只监听 `127.0.0.1`，采用 Bearer token；若绑定 LAN，需精确 Host/Origin allowlist。[安全与环境变量](https://dbxio.com/cn/docs/mcp#安全和环境变量) [Desktop HTTP](https://dbxio.com/cn/docs/mcp#dbx-desktop-原生-streamable-http)
- 仍需谨慎：`dbx_execute_batch` 可运行多条语句；只要策略允许，工具集还可写数据、DDL、发消息、管理连接。其自身策略能降低风险，却不能替代 FrontierAgent 的逐角色工具声明、审批、审计返回格式和最小能力面。[批量 SQL 与策略](https://dbxio.com/cn/docs/mcp#批量-sql-执行)

**建议：暂不接入生产链路；可选本机只读辅助。** 只有在有明确的“Agent 读取某个非生产数据库 schema/数据”的产品需求后，再评估一个窄适配器：固定允许的 connection/database，限定 `list_tables`、`describe_table`、参数化只读查询，限制行数/超时，脱敏输出并记录连接标识、SQL 指纹、时点和结果摘要。DBX 侧也应只暴露这些工具、仅授权目标连接/数据库，并保持只读。

## 触发重新评估的条件

1. 新增 Java 服务的受控运行时诊断需求（重新评估 Arthas）。
2. 新增明确的数据库分析/排障用户故事，且能指定非生产数据源、只读范围、数据分级与审计负责人（重新评估 DBX）。
3. 能完成受控适配器、工具 allowlist/角色授权、审批与运行证据留存的端到端测试。
