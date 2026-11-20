# SSE-T06 故障、兼容与观测验收规格

| 项目 | 内容 |
|---|---|
| 版本 / 日期 | v1.0 · 2026-11-21 |
| 状态 | 已执行并收口（2026-11-21）：A03/A04/A07/A09 通过，A05 部分覆盖，A10 代理 blocked；证据与限制见计划 §20.12 |
| 上游依据 | [建设计划 §20.2/§20.4/§20.5](../../plan/super-link-communication-foundation.md#202-执行任务及依赖)；[技术框架 §11.6—§11.9](../../design/super-link-technical-design.md#116-运行输出与持久事实的区别)；[T05 规格 §10](../super-link-sse-t05/spec.md#10-退出条件与移交) |
| 前置 | SSE-T01—T05 已复核收口（T05：2026-11-21） |
| 范围 | 真实浏览器、反向代理、真实 Worker、隔离 PG/Redis、故障注入、观测指标与普通模式回归；不含 T07 发布启用 |

## 1. 目标

在不改变本批协议、游标语义和普通模式行为的前提下，用真实链路证明 T01—T05 的
设计在浏览器、代理、Worker 和故障条件下成立，并留下可复核证据。

必须达到：

1. Team/Single 的可见输出在真实浏览器中按成员、轮次和块归属展示；运行结束后由
   归档内容替换，最终文本与保存轨迹一致。
2. 页面断线、刷新、多标签页和重连后，状态以快照与事实补读恢复；不重复提交、不重复
   派发、不把断线显示成业务失败。
3. 反向代理开启常见缓冲/压缩配置时，SSE 心跳与预览帧仍按增量到达；代理退出和恢复
   可被页面区分为连接问题而非运行结果。
4. Redis 中断、API 重启、非所有者实例和慢客户端下，业务执行不被展示阻塞；关键事实
   可从 PostgreSQL 补读；预览缺失不伪造状态。
5. 连接数、缓冲、预览队列和事件积压有可观察数值与上限；慢连接和超限连接不拖垮
   其他用户。
6. 普通 single/team、审批、停止、补充指令和上下文连续性无回归。
7. 每项证据注明环境、注入点、预期/实际、结果与限制。未支持的多实例、离线监控或
   真实研究质量不得标为通过。

不做：

- 不新增编排引擎、A2A 接入、跨实例输出路由或逐 token 持久化。
- 不改变 `sl1` 游标、事件信封、快照协议、预览帧字段或普通模式运行流。
- 不实现多实例高可用或所有权接管；首版按单 API 所有者验收，第二实例的约束单独
  记录。
- 不迁移、不清空、不写入业务库；不使用共享 Redis 的生产命名空间注入故障。
- 不验收研究内容质量；脚本模型只验证流协议与运行生命周期。

## 2. 环境与安全边界

### 2.1 隔离拓扑

| 组件 | T06 取值 | 约束 |
|---|---|---|
| 业务数据库 | 隔离库 `apodex_biz_test` | 通过 `PG_INTEGRATION=1`、`PG_BUSINESS_TEST_DB=apodex_biz_test` 与对应 DSN 使用；禁止 `apodex`/`postgres` |
| Redis | 专用容器 `127.0.0.1:16379`，逻辑库 15 | 不停止、不写入共享的 `frontier-monitor-redis`（6379）；只清理 `super-link:t06` 前缀 |
| API | `127.0.0.1:18000` | 独立进程与临时 `SERVER_RUNS_ROOT`；不重启或干扰现有 8000/5173/4174 进程 |
| 脚本模型 | 不使用；沿用 `.env` 中的真实端点 | 只验证流协议与运行生命周期；内容质量、成本和延迟不纳入验收 |
| 前端 | Vite 开发服务 `127.0.0.1:15173`，`VITE_API_PROXY=http://127.0.0.1:18000` | 当前无代理可用，先直连 API；A10 代理场景按 §2.3 处理 |
| 反向代理 | 待解决（Caddy 镜像未拉取成功） | 若无法提供 Caddy/nginx 镜像，A10 标记 `blocked`，不声称代理链路通过 |
| 浏览器 | 内置浏览器工具 | 仅访问上述隔离端口；登录隔离库中新建的测试用户 |

启动 API 的关键覆盖项：

```
SERVER_DATABASE_URL=postgresql+asyncpg://...@127.0.0.1:5432/apodex_biz_test
SERVER_SUPER_LINK_ENABLED=true
SERVER_SUPER_LINK_REDIS_URL=redis://127.0.0.1:16379/15
SERVER_SUPER_LINK_NAMESPACE=super-link:t06
SERVER_SUPER_LINK_EVENT_ENV=test:t06
SERVER_RUNS_ROOT=<临时目录>
SERVER_MONITOR_ENABLED=false
SERVER_AUTO_ENABLED=false
```

说明：

- `SERVER_SUPER_LINK_EVENT_ENV` 让通知频道为 `test:t06:super-link:t06:ui-events:v1`，
  与共享 Redis 上的生产频道隔离。
- 业务库迁移只在隔离库执行；不根据历史记录假定业务库版本。
- 真实模型端点沿用 `.env`，不覆盖 `OPENAI_BASE_URL`；模型错误通过单独启动一个指向
  不可达本地端点的 API/Worker 注入，恢复后重跑正常链路。
- 若 Worker 启动检查要求语料只读挂载，使用现有只读挂载或测试替身，不查询业务语料库。

### 2.2 执行前确认

本轮已确认：

1. 使用隔离 PG `apodex_biz_test`、Redis 16379/库 15、API 18000、Vite 15173 与临时
   runs 根；不触碰现有 8000/5173/4174 进程、业务库与共享 Redis。
2. 允许使用内置浏览器访问隔离端口。
3. 真实 Worker 只使用 `.env` 中的真实模型端点，不使用脚本模型。

执行结论：

- 本机未安装 nginx/caddy 二进制；`caddy:2-alpine` 镜像本地不存在，拉取失败。
  A10 代理场景标记 `blocked`，直连 API 的其他场景已执行；未用简化代理冒充
  Caddy/nginx，代理缓冲/压缩留给 T07 前补跑。

### 2.3 代理不可用时的处理

- 保留响应头、心跳和直连增量证据，但不把它们等同于真实代理验收。
- 不自行编写简化代理冒充 Caddy/nginx；如用户后续提供镜像或代理，再补跑 A10。
- 报告中明确“代理缓冲/压缩未验证”，作为 T07 前的残留风险。

## 3. 观测指标与诊断接口

T01 要求把事件积压监测纳入 T06；T03/T05 已有连接与预览上限，但没有可读取的数值。
本规格新增最小观测面，不引入 Prometheus 或后台聚合服务。

### 3.1 进程内计数

新增 `server/super_link/observability.py`：

- `sse`: `opened`、`closed`、`rejected`（配额）、`slow_closed`（缓冲超时）、
  `auth_revoked`、`max_age_closed`、`active_total`。
- `preview`: `frames`、`resets`、`dropped`（写不进连接缓冲）。
- `notifier`: `published`（成功发布的批次）、`failed`（发布异常或 Redis 不可用）。
- `snapshot()` 返回普通 dict，供诊断接口与测试读取；无定时器、无 Redis、无后台任务。

计数只表示本进程，不跨实例汇总；诊断响应必须标明 `scope: "process"`。

### 3.2 空间诊断接口

新增 `GET /api/super-link/spaces/{space_id}/diagnostics`：

- 与现有空间路由相同的 `_enabled()`、用户状态与所有者校验；非所有者 404。
- 只读，不写事件、不推进游标、不改变连接状态。
- 数据库不可用时返回 503 `event_chain_unavailable`，不返回伪造零值。

响应字段：

| 字段 | 含义 |
|---|---|
| `schema_version` | 固定 `1` |
| `scope` | `"process"` |
| `generated_at` | 服务端时间 |
| `process.sse.*` | 3.1 的连接计数与当前用户 `active_for_user`、`limit` |
| `process.preview.*` | 预览帧、reset、丢弃计数 |
| `process.notifier.*` | 发布成功/失败计数 |
| `events.stream_epoch` | 当前事件头 epoch |
| `events.head_seq` | 当前事件头序号 |
| `events.unnotified_count` | 该空间尚未通知的事件数 |
| `events.oldest_unnotified_age_seconds` | 最老未通知事件的年龄；无积压为 `0` |

计数接入点：

- `stream.event_stream()`：获取/释放连接、配额拒绝、慢连接关闭、权限撤销、寿命关闭。
- `stream._produce_previews()`：预览帧发送、reset 发送、入队失败丢弃。
- `events.EventNotifier.publish_once()`：成功批次与异常。

不新增前端页面；指标通过接口与日志读取。

## 4. 验收场景

编号沿用计划 §20.4。T06 负责或需补充证据的部分如下。A01/A02 以隔离 PG 重跑作为
回归，不再扩展新语义。

### 4.1 A03 断线期间完成收尾与交接

1. 浏览器打开空间详情，触发一个 Single 运行；关闭标签页或停止网络读取。
2. 在无 SSE 客户端期间让运行完成，并触发一次交付或审批事实。
3. 重新打开页面，读取快照与补读事件。

预期：运行状态、交付和审批与数据库一致；只有一个目标 Run；归档完整；没有因重连
重新执行模型或重复派发。快照 `cursor` 与后续事件衔接无空隙。

### 4.2 A04 控制幂等与双标签页

1. 用同一幂等键重复提交暂停/停止，模拟首个响应丢失。
2. 用过期 `control_version` 提交一次。
3. 两个浏览器标签页同时对同一空间操作；其中一个先提交。
4. 在停止请求被接受后、真实终态前刷新页面。

预期：原键返回原结果；旧版本 409；只有真实收尾完成后才显示“已停止”；刷新期间
显示“正在停止”而不是伪造终态；不产生第二个 Run。

### 4.3 A05 高速输出、慢客户端、Redis 与 API 故障

| 注入 | 操作 | 预期 |
|---|---|---|
| 高速多成员/长文本 | 真实模型输出较长内容，连续展示 | 预览按成员/块归属；事实可读；执行不被展示阻塞 |
| 慢客户端 | 一个 SSE 客户端 30 秒不读取 | 该连接缓冲有界，超时关闭并释放配额；其他客户端与运行继续；诊断计数增加 |
| SSE 断开 | 浏览器断网/刷新，运行继续 | 重连获得新 `output_epoch`；预览清空并以归档补齐；运行不失败 |
| Redis 中断 | 停止 16379 容器，运行提交事件与控制 | 业务事实仍落库；通知延迟；诊断显示未通知积压；恢复后补发 |
| API 重启 | 运行结束后重启 API | 快照/归档可读；预览消失；无重复 Run、无重复工具执行 |
| 模型错误 | 单独启动指向不可达本地端点的 API/Worker | 页面显示运行失败（业务故障），不是连接断开；事实可补读 |

### 4.4 A07 跨用户、跨空间与令牌失效

1. 用户 B 尝试读取用户 A 的空间快照、事件、诊断与交付：全部 404，不泄露存在性。
2. 使用过期/签名错误的令牌建流：401，不建立长连接。
3. 建流后停用该用户：最长一个权限复核间隔内收到 `sl.auth_required` 并关闭。
4. 源审批记录保存失败注入：不产生已持久化审批事实，不显示可批准入口。

### 4.5 A09 普通模式回归

在 Super-link 启用、空间 SSE 活跃的同一 API 上：

1. 普通 single 运行：输入、流式输出、工具、产物与停止行为不变。
2. 普通 team 运行：成员并行、汇总、停止与恢复不变。
3. 普通审批：批准/拒绝/超时路径不变。
4. 上下文连续性：同一普通会话追加提问能读取本方历史；Super-link 运行不写入普通
   会话的当前 Run 状态。
5. 现有定向回归测试通过。

### 4.6 A10 代理与实例路由

1. 浏览器经 `15173 → Caddy 18080 → API 18000` 打开空间并建流。
2. 验证响应头含 `Cache-Control: no-cache` 与 `X-Accel-Buffering: no`；Caddy 使用
   `flush_interval -1` 且启用 gzip/zstd 时，15 秒心跳与预览帧仍按增量到达。
3. 停止 API：浏览器显示连接中断/重连提示，不把运行标为失败；Caddy 返回 5xx 或断开。
4. 重启 API：页面重连、重新快照并补读；不重复执行。
5. 第二个 API 实例：只在 Super-link 关闭或只读方式下验证事实/归档可见。首版不支持
   多实例同时启用；若缺少所有权锁，记录为发布约束，不能标为多实例通过。

当前代理不可用：先完成直连 API 的第 3—5 项；第 1—2 项标记 `blocked`，待提供
Caddy/nginx 后补跑。

## 5. 故障判定与降级

| 现象 | 分类 | 页面/证据要求 |
|---|---|---|
| SSE 断开、代理 5xx、心跳超时 | 展示链路故障 | 显示连接状态与重试；运行事实仍从快照读取 |
| Redis 通知失败 | 通知延迟 | 诊断显示未通知积压；恢复后补发；不改写业务结果 |
| PostgreSQL 不可用 | 事实链路故障 | 503/连接错误；不显示新事实；不伪造成功 |
| Worker 退出、模型 5xx | 业务执行故障 | 运行终态 `failed` 与脱敏错误；与连接故障分开 |
| 预览队列/连接缓冲溢出 | 展示降级 | 受影响 Run 收到 reset；客户端以归档校正；事实不丢 |
| 非所有者实例 | 首版能力降级 | 无实时预览；事实与归档可用；不声称多实例通过 |
| 用户撤权/令牌过期 | 权限故障 | 关闭连接并提示重新登录；不继续发送内容 |

## 6. 证据与判定

每项证据记录：

- 环境：日期、隔离 PG/Redis、API/前端/代理端口、真实模型端点和模型名。
- 注入点：停止的组件、断线方式、重复请求键、慢客户端行为。
- 预期/实际：可观察结果，不用“应该”描述代替。
- 结果：`pass` / `fail` / `blocked`，附失败原因或阻断条件。
- 限制：未覆盖的浏览器、代理、实例或模型组合。

判定规则：

- 单元/集成测试通过不能替代浏览器与代理证据；浏览器证据也不能替代故障注入。
- 同一场景多次执行时记录重复次数与是否出现乱序、重复或假终态。
- 未支持的多实例、离线监控、真实研究质量标为“未验收”，不能因为其他场景通过而
  整体通过。
- 发现缺陷时先在 T06 记录，再单独修复并复跑受影响场景；不把修复混入验收结论。
- 正式启用仍由 T07 核对迁移、配置、备份与回退后另行执行。

## 7. 测试与命令

自动化（隔离 PG）：

```
PG_INTEGRATION=1 PG_BUSINESS_TEST_DB=apodex_biz_test \
SERVER_DATABASE_URL=<隔离库 DSN> \
uv run pytest tests/pg/test_super_link_events.py tests/pg/test_super_link_stream.py -q
```

定向后端：

```
uv run pytest tests/test_super_link_output.py tests/test_super_link_stream.py \
  tests/test_super_link_events.py tests/test_super_link_diagnostics.py \
  tests/test_context_inheritance.py tests/test_web_dispatch_recovery.py -q
uv run ruff check server/super_link server/routes/super_link.py tests/test_super_link_diagnostics.py
uv run pyright server/super_link server/routes/super_link.py
```

前端：

```
cd web && npm test && npm run typecheck && npm run build
```

真实链路：

- 真实模型 + 真实 Worker：Single 跑通分片、思考（如端点返回）、工具、终态与归档替换；
  Team 至少一次多成员输出，记录成员归属与交错顺序。模型失败通过独立启动的不可达
  端点注入，不修改正常运行的 API 配置。
- 浏览器：A03、A04、A05 断线；A10 代理若仍无可用代理则标记 `blocked`。每个场景保留
  页面状态与接口/诊断响应。
- 故障注入：Redis 停止/恢复、API 重启、慢客户端、令牌失效。
- 普通模式：single、team、审批、停止、连续性各一次。

不执行 T07 的业务库迁移、备份恢复或正式启用。

## 8. 退出条件与移交

T06 完成需同时满足：

- 计划 §20.4 中 T06 负责场景有 `pass` 或明确的 `blocked` 证据；
- 连接/发布/积压指标可读，且慢客户端与超限连接有界；
- 运行展示故障与业务执行故障可区分；
- 普通 single/team、审批、停止和连续性回归通过；
- 真实浏览器、代理与 Worker 链路至少各有一组成功证据；
- 未支持边界（多实例、离线监控、研究质量）明确记录，未被标记为通过。

移交 T07：

- 部署清单需包含 `super_link_alembic_version` 当前版本、`sl_0006_events` 与
  `sl_0005_controls` 顺序、隔离库验证结果、Redis 频道/命名空间与连接上限配置。
- 若 T06 发现所有权锁缺失，T07 必须把“单 API 实例”写入部署约束，或另行实现
  所有权保护后再评估多实例。
- 保留数据回退、功能关闭、备份恢复后 epoch 更换与客户端强制重新同步的检查项。
