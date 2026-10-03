# 05 · 调度、持久执行账、原子预算与只读核查

Status: ready-for-human
Execution: 待验收
Type: task
Plan: W2/W3；R2-S2/S3
Blocked by: 无本地任务依赖（04 已验收）
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

提供显式计划/执行/核查入口，保证每次真实请求只能经预留入口发出；在中断和并发下保持可对账，而不建设第三条处理链。

## 前置与外部门

04 已验收；01 已选定持久账的事务方案和 CLI 契约。复用 _r2_runtime/_r2_audit 的经验不等于把其私有 fake/replay 路径直接宣称为生产实现。

## 范围与预期文件

- 调度/持久账固定落在 `plugins/corpus/structured/ledger.py`，CLI 固定为
  `plugins/corpus/structured/cli.py`；按需复用 plugins/corpus/_r2_plan.py、_r2_runtime.py、
  _r2_audit.py 的逻辑，不污染旧实验协议。持久账为根目录 `index/structured.sqlite3`，使用
  WAL + `BEGIN IMMEDIATE` 原子预留，不得使用 no-op EventStore。
- tests/test_corpus_structured_execution.py、tests/test_corpus_structured_cli.py。
- 计划记录初始任务、关系派生规则/上限及角色配置；计划生成不发模型请求。
- 真实并发默认 1；假响应覆盖并发竞争。账目只写指定临时/实验根目录，不使用 no-op EventStore 做持久化。

## 验收条件

- [x] 角色与批次预算在一个事务内检查/预留；最后一个额度并发争用只能批准一个 attempt。
- [x] task、attempt、batch 身份稳定；关系依赖就绪后先登记派生任务再调用，恢复不重复登记逻辑任务。
- [x] 预留后中断、收到响应但未落盘、协议失败等结果保留真实状态，未知 outcome 不自动重发、不回收为确定零成本。
- [x] 每次兼容请求/获准重试都独立获准留账；SDK 无隐藏请求；费用按模型/供应商/价格/币种分项，缺项为未知。
- [x] 只读核查覆盖计划—任务—请求/响应—产物引用；不补发、不改账、不替语义质量打分。
- [x] CLI plan/check/replay/execute 的已冻结行为、参数校验和退出码有进程级测试；配置失败先于请求，查询没有 execute 副作用。
- [x] 取消/截止、恢复、无候选、未就绪、关系关闭和超预算分别可辨；不以缺日志断言进程死亡。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_execution.py tests/test_corpus_structured_cli.py -q
uv run ruff check plugins/corpus tests/test_corpus_structured_execution.py tests/test_corpus_structured_cli.py
```

测试含独立进程中断恢复及并发预留；真实网络/模型在测试中拒绝。进程级调用固定为：

```bash
uv run python -m plugins.corpus.structured.cli plan --snapshot SNAPSHOT.json --out PLAN.json
uv run python -m plugins.corpus.structured.cli execute --plan PLAN.json --store-root ROOT --allow-model
uv run python -m plugins.corpus.structured.cli replay --plan PLAN.json --responses RESPONSES --store-root ROOT
uv run python -m plugins.corpus.structured.cli check --batch-id BATCH_ID --store-root ROOT
```

## 非目标

不启动常驻监控，不自动修复，不引入模型复判，不把统一计账解释为统一模型或统一 token 单价。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
- 2026-10-03：用户授权核查达标后闭环 04；规范/规格补漏及 269 项 fake/mock 回归通过，
  04 已验收，解除本地依赖，转 ready-for-agent。Execution 仍为未开始；本次未启动本票。
  后续接入 04 的 `RoleRequest`/`RoleCallResult`/dispatcher 接缝完成原子预留和持久对账，
  不把现有角色回执等同于本票执行账已交付。验收证据见 [04](04-role-execution.md)。
- 2026-10-03：用户明确要求执行 05；本票已认领并进入实现。继续限定为合成夹具与
  fake/replay，真实模型调用和生产数据库访问保持为 0；不顺带执行 06。
- 2026-10-03：实现完成并转 `ready-for-human / 待验收`。新增持久执行账与四个公开入口，
  使用 `index/structured.sqlite3`（WAL、FK、FULL、`BEGIN IMMEDIATE`）原子预留批次/角色/任务
  额度；响应、payload 与角色工件按 SHA-256 不可变保存。计划冻结逐单元路由理由、角色配置、
  规则与预算；关系任务在调用前登记并可恢复去重；单批 OS lease 防止两个 runner 并行推进，
  进程退出自动释放。unknown outcome 不重发，配置失败在请求前阻断，check 使用 SQLite
  `mode=ro` 并回扣冻结任务、attempt 身份、响应、工件、派生关系及预算计数器。费用按
  provider/model/currency/kind/price_version 分项，缺失保持 unknown。授权拒绝仅透传白名单化
  状态码，未泄漏异常内容。
- 2026-10-03：精确验收命令通过：`28 passed`；指定 Ruff 命令 `All checks passed`。
  扩展结构化/角色/语义回归 `261 passed`；定向 Pyright `0 errors`；format check 6 文件通过；
  import smoke 为 framework `378/378`、eval `427/427`；symbol closure 为 `0 missing` / 477 文件。
  独立进程测试覆盖预留后 `os._exit(77)`、跨 cwd replay/check、退出码和只读 mtime；所有执行测试
  显式拒绝网络、默认 HTTP transport、生产 CorpusService 连接及仓库 `.env`。
- 2026-10-03：交付指纹：`ledger.py` `db2f78614209333f35db7ce670885d948329dd1a3333ed01f6e7807d51af6916`；
  `cli.py` `632e5b7a5ea220d6fc42d12bf15006db94363619f76c705504d1118276d24bdc`；
  `test_corpus_structured_execution.py` `bf2d9038f38e95ee63f86460a23b1948de17e0659038d3b488537a7de5bb9408`；
  `test_corpus_structured_cli.py` `1208dde0813e04ea0b6aa13f7b82671decd51c97f0b528b3aa5a31f8fed3498a`。
  本次真实模型调用 0、生产数据库访问 0。
- 2026-10-03：额外全仓测试结果为 `3476 passed, 20 skipped, 3 failed, 6 errors`；失败均可独立
  复现且不在 05 变更路径：黄金集目标库为 `postgres` 而要求 `i2_sandbox_corpus`、PDF reader
  已为 v11 而测试仍断言 v10、React profile 工具集合为空、Web preview fixture 创建 run 时用户
  外键缺失。它们不影响本票精确验收，但作为仓库既有外部门保留，不在本票越界修复。05 未经
  人工验收前不解除 06 依赖。
