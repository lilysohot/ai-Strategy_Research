# 07 · 只读语义查询、快照分页与完整证据交付

Status: ready-for-human
Execution: 已验收
Type: task
Plan: W5 前置接线；R2-S2/S3
Blocked by: 无本地任务依赖（06 已验收）
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

通过生产调用方同一查询 Interface 返回可直接消费的证据单元，避免抽取正确但检索/分页/裁剪丢失必要限定。

## 前置与外部门

06 已验收；01 已固定工具名、输入/输出 Schema、错误码与游标契约。此票实现工具逻辑与裁剪接缝，产品 profile 启用和完整 loop 验收归 09。

## 范围与预期文件

- 语义查询固定落在 `plugins/corpus/structured/query.py::query_semantic`，只读工具名固定为
  `corpus_semantic_query`；返回 `corpus-semantic-query-page-v1`，首轮排序版本固定为
  `semantic-lexical-sort-v1`。
- plugins/tools/_overflow.py、workflows/stateful_react_agent/_runtime.py 的协议交付接缝；不在框架通用内核内硬编码业务。
- tests/test_corpus_structured_query.py、tests/test_corpus_structured_delivery.py；现有 test_corpus_fetch_paging.py 回归。
- 固定 source/build/发布版本、用途、检索与排序版本；首轮词法/字段检索，不增加 LLM 改写或重排。

## 验收条件

- [x] 命中核心条目时必要条件/否定/表头/脚注/归属成组返回，即使依赖不含查询词；关联未知明确标缺口。
- [x] 查询只读已发布范围，永不触发抽取/自动修复；返回记录 ID、语义版本与可解析原文句柄/区间。
- [x] 未抽取、查询无匹配、有匹配但未翻页、已检查但未抽出支持条目可区分，均不能直接推出全文无风险。
- [x] 游标绑定 query/排序/发布版本，跨页不混版；撤回/用途收紧使受影响续页明确失效，需显式重查。
- [x] 必要证据单元放不下则少返回或给预算缺口，不发送裸数值作完整证据，不截断 JSON/游标。
- [x] 工具层与运行时层重复裁剪均保护协议；在实际请求消息中核验内容，而不只看函数返回值。
- [x] 独立风险/反方可检索，排序不只保留支持性观点；检索规则与响应预算纳入版本和 10 的交付召回验收。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_query.py tests/test_corpus_structured_delivery.py tests/test_corpus_fetch_paging.py -q
uv run ruff check plugins/corpus plugins/tools workflows/stateful_react_agent tests/test_corpus_structured_query.py tests/test_corpus_structured_delivery.py
```

测试默认拒绝模型调用；引用、缺口、预算错误都按正式返回协议验证。

## 非目标

不允许用户问题改变后台抽取范围，不新增 Agent 自主抽取工具，不把诊断 raw 响应公开成普通研究证据。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
- 2026-10-03：用户明确要求开始执行 07。前置核查确认 06 已验收，解除本地依赖；本票进入
  `ready-for-agent / 执行中`。继续只使用合成 replay、临时 store 和 fake 工具消息，真实模型调用
  与生产数据库访问保持为 0；不顺带执行 08—11，也不启用产品 profile。
- 2026-10-03：实现完成并转 `ready-for-human / 待验收`。新增
  `plugins/corpus/structured/query.py::query_semantic` 与只读工具 `corpus_semantic_query`。查询只从
  `read_semantic` 的当前 accepted publication 投影 Claims/items/relations，不调用 plan/execute/replay，
  不执行抽取或自动修复。词法与固定字段过滤采用 `semantic-lexical-sort-v1` 确定性排序；query hash
  同时冻结 purpose、字段过滤、`semantic-query-rule-v1`、`semantic-query-budget-v1` 和响应预算。
- 2026-10-03：证据投影返回 `corpus-semantic-query-page-v1` 的 record ID、用途、质量/映射状态及
  `cv2:<build>#chunk:<chunk>` + Unicode code-point 精确区间；沿 snapshot dependency closure 成组加入
  value/period/unit/header/footnote/condition/negation/attribution 全单元。合成用例验证“收入”命中时
  不含该词的条件句仍随主记录交付；未关联映射显式为 `unlinked`，缺失/歧义依赖会降低 context 状态，
  不把未知关联表述成一致。
- 2026-10-03：游标新增独立 `semantic_query` 类型，绑定 query hash、排序版本、publication ID、
  generation 和 position；查询/预算变化、篡改、发布切换或撤回均返回
  `cursor_stale + CS_CURSOR_STALE`。`not_published`、`not_extracted`、词法 `no_match`、已检查但无支持记录、
  `more_available` 与 `budget_limited` 使用不同状态/错误组合，任何空结果都只描述固定发布范围。
- 2026-10-03：工具自身按完整 record/evidence/dependency 单元装箱，预算不足时少返整条或返回
  `CS_BUDGET_EXHAUSTED`；`plugins/tools/_overflow.py` 和 stateful runtime 的显式 6K 接缝重复调用同一
  协议 fitter，禁止通用字符硬切。集成测试通过真实 `run_agent_loop` fake LLM 两轮消息核验第二次
  请求内的 tool message 仍是可解析协议页，且没有截断 evidence、dependency、JSON 或 cursor。
  工具已加入中央 allowlist、终端解析和只读元数据，但依照本票非目标没有加入任何产品 profile。

### 2026-10-03 实现验收证据

所有命令从 WSL `/home/administrator/FrontierAgent` 执行；业务测试的 autouse blocker 在导入后仍
阻断 socket/DNS、HTTP transport、dotenv 和生产 `CorpusService._connect`，只使用合成 snapshot、
显式 replay、临时 SQLite store 与 fake LLM。

| 命令 | 退出码 | 结果 / 范围 |
| --- | --- | --- |
| `uv run pytest tests/test_corpus_structured_query.py tests/test_corpus_structured_delivery.py tests/test_corpus_fetch_paging.py -q` | 0 | 39 passed；1 条既有 optional PySocks 依赖 warning；本票原样验收命令 |
| `uv run ruff check plugins/corpus plugins/tools workflows/stateful_react_agent tests/test_corpus_structured_query.py tests/test_corpus_structured_delivery.py` | 0 | All checks passed，本票原样验收命令 |
| `uv run pytest tests/test_corpus_structured_*.py -q` | 0 | 261 passed，全部 structured 回归 |
| `uv run pytest tests/test_tool_registry.py tests/test_corpus_structured_contracts.py tests/test_corpus_structured_publication.py -q` | 0 | 48 passed，注册/冻结契约/发布回归 |
| `uv run pyright plugins/corpus/structured/query.py plugins/tools/corpus_semantic_query.py` | 0 | 0 errors / 0 warnings |
| `uv run pyright` | 1 | 8 个非 07 路径错误：gradio 缺失、run_retention 3 项、并行编辑中的 server 3 项、orchestrator 1 项；本票定向检查通过 |
| `uv run python tools/import_smoke.py --stage 1` | 0 | framework 381/381 |
| `uv run python tools/import_smoke.py --stage 2` | 0 | eval 430/430 |
| `uv run python tools/check_symbols.py` | 0 | 0 missing / 480 files |
| `git diff --check` | 0 | 无空白错误 |

当前 SHA-256（退出 0）：

- `plugins/corpus/structured/query.py`: `9086de2d0bdfc494a24704409105590d31ce22512e2d46b8ea5d039c3675d9e9`
- `plugins/tools/corpus_semantic_query.py`: `2a0156be4c421721e5c75d420256d861fc5fb5ddd5583febc4982061d5cd5d67`
- `tests/test_corpus_structured_query.py`: `4983bd841481ca818ab40d5230855e85e0fe31a7ac59e131c1aee93ef44f9001`
- `tests/test_corpus_structured_delivery.py`: `cc18113fa885ccf05239f06ea1964bc7f4f998dd693b0fed6d86e22e039e6f4c`
- `plugins/corpus/cursor.py`: `29c4d0a856a7c3fffaccd2302db818a32f4d4f0938f2dca9770d3912f8b808df`
- `plugins/corpus/structured/store.py`: `cc89ce56d571eea81d86cfdfd14319c547bd77730ef76a0e8930eaa17c9294f9`
- `plugins/tools/_overflow.py`: `58e316b084aba66882bacf51017b7f6c6d40642ccd990b493ea8de3e3ba3f3b6`
- `workflows/stateful_react_agent/_runtime.py`: `898aaf349731200fc11e131b41d547b1f229103de2f3f1e081c594019a83b95f`
- `plugins/tools/meta.py`: `b5c5823227a1f6aa0aa1df78c8c5377c4f7e8cc40475073363f7c9557f4245af`
- `plugins/tools/__init__.py`: `bab25c2361f7a7aed9fff440776e48823dd6f642a0bc8abd775e0217ac53ddbf`
- `apodex/agent_tools.py`: `95e86d466def111aa42e372d9fd3951ea3834b2d36803d56dcef04944d8057a6`
- `tests/test_tool_registry.py`: `34f1c1059d0d1b44a3a4d7dbda3f0a638d579c19776ca39b40659059b0aa6184`

限制与外部门：本票证明确定性检索、快照分页和协议交付，不证明真实语料的语义召回率；该项仍由 10
的冻结样本与 11 的正式门禁验收。没有启用产品 profile，没有执行 08—11，没有访问未授权真实样本；
真实模型调用 0、生产数据库访问 0，按 spec §5 未运行真实模型 preflight。当前仅提交待人工验收证据，
未代替用户签认，也未解除下游依赖。全仓 Pyright 的 8 项失败均不在 07 修改范围；其中
`server/business_service.py`、`server/input_requests.py`、`server/investment_snapshot.py` 属于当前工作区的
并行用户改动，本票未覆盖或改写。07 新增的 query/tool 定向 Pyright 为 0 errors / 0 warnings。

### 2026-10-03 审核修复记录

此前审核未通过，发现：下游裁剪后游标跳过未交付记录；跨角色 eligible 掩盖指定角色的已检查无支持
状态；relations 仅可按类型检索；多条 mapping 的首条覆盖后续 conflict；交付测试复制记录且清空
cursor，未证明真实分页链路。用户随后要求“开始修复”。上述初次实现证据和指纹保留为历史，当前
状态以本节为准：修复完成、等待复验，不标已验收，不解除下游依赖。

- 中间页按裁掉的完整记录数回退 cursor.position，保留 query/sort/publication/generation 绑定，
  连续两层裁剪、非首页裁剪和一条也放不下均不跳过未交付记录。
- 末页没有 generation/position token，不能凭空重建游标；裁剪时返回空 records、null cursor、
  `budget_limited + CS_BUDGET_EXHAUSTED + CS_CURSOR_STALE`，明确要求降低 limit/按交付预算重新查询。
  这不是查询完成或全文无结果。保持冻结 v1 Schema，不增加隐式存储访问或后台抽取。
- 已检查无支持状态按请求角色判定；词法未命中仍与该状态分开。关系索引纳入关系原文证据及端点
  文本；映射状态按 `conflict > suspected > unlinked > confirmed` 保守汇总，不依赖数组顺序。
- query rule/budget 内部版本递增为 `semantic-query-rule-v2` / `semantic-query-budget-v2`，旧查询
  游标不能静默沿用改变后的检索/预算语义；冻结 Schema 和 `semantic-lexical-sort-v1` 不变。
- 交付测试删除复制 record ID 的假页，使用 16 条通过 replay/publish 的真实合成记录、正式注册的
  `corpus_semantic_query` 和 `run_agent_loop`。从实际后续 fake LLM 请求消息读取每页，核对完整
  evidence/dependencies、记录集合、无重复无跳页；覆盖中间页回退后适配 limit 完成遍历，以及
  超大末页收到显式缺口后重新查询完成遍历。fake LLM 不接网络。

本轮修复限于 query/tool、两份专项测试和本票记录；保留 06 及工作区其它并行改动。测试继续阻断
真实网络、dotenv 与生产 CorpusService 连接。真实模型调用 0，生产库访问 0，未运行真实 preflight，
未启用 profile 或执行 08—11。

本轮验证（WSL 仓库根目录）：

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `uv run pytest tests/test_corpus_structured_query.py tests/test_corpus_structured_delivery.py tests/test_corpus_fetch_paging.py -q` | 0 | 48 passed |
| `uv run pytest tests/test_corpus_structured_*.py tests/test_tool_registry.py tests/test_corpus_fetch_paging.py -q` | 0 | 306 passed，structured 全量及注册/正文分页回归 |
| `uv run ruff check plugins/corpus plugins/tools workflows/stateful_react_agent tests/test_corpus_structured_query.py tests/test_corpus_structured_delivery.py` | 0 | All checks passed |
| `uv run pyright plugins/corpus/structured/query.py plugins/tools/corpus_semantic_query.py` | 0 | 0 errors / 0 warnings |
| `uv run pyright` | 1 | 仍为上述 8 项非 07 路径错误；没有将全仓门禁记为通过 |
| `uv run python tools/import_smoke.py --stage 1` | 0 | 381/381 |
| `uv run python tools/import_smoke.py --stage 2` | 0 | 430/430 |
| `uv run python tools/check_symbols.py` | 0 | 0 missing / 480 files |

`git diff --check` 与四个本轮 Python 文件的 `uv run ruff format --check` 均退出 0。

修复后 SHA-256：

- `plugins/corpus/structured/query.py`: `44ccd738fd00cf8f78039e4ea99d6f686afd0241c1bc30cbf9b64a3672c90dbc`
- `plugins/tools/corpus_semantic_query.py`: `d1ec7d4b432d570a28847c979e407ab086e1522f19be8a8897b447963a10cba1`
- `tests/test_corpus_structured_query.py`: `c5c04073478ff2795cd4d320e9999f6bc994342104081250231bb2031f6d2c44`
- `tests/test_corpus_structured_delivery.py`: `cae37d9432155dc10d247a0f6cb5182b496ce2d0837e334772aa0fd45ae592f6`

### 2026-10-03 最终复验与闭环

用户要求执行下一个任务时，06 已验收，07 是依赖顺序中唯一仍处于“审核修复完成、待复验”的票据；
08 已验收，09 存在独立在途改动。本轮没有重做已完成实现，也没有覆盖 09 文件，仅按 07 的冻结契约
复验当前调用面和共享工具接缝。

- 原样验收命令通过：`48 passed`；指定 Ruff `All checks passed`；query/tool 定向 Pyright
  `0 errors / 0 warnings`。
- structured 全量、工具注册与正文分页回归为 `357 passed`；framework/eval import smoke 分别为
  `384/384`、`433/433`；symbol closure 为 `0 missing / 483 files`；`git diff --check` 通过。
- 四个交付文件 format check 通过。复验确认中间页 cursor 回退、末页显式重启、指定角色无支持、
  relations 原文/端点检索、mapping 冲突保守聚合及多页真实 tool-message 交付均有通过用例；没有发现
  新的 07 阻断项。查询仍只读、零抽取、零自动修复，真实模型调用和生产数据库访问均为 0。
- 当前复验指纹：`query.py`
  `2de2ef3ec5c3958753f41f96c5be1127e3c3ad4d726c1f65680fa0d3bff0f97a`；
  `corpus_semantic_query.py`
  `65361a3e6c0259cc4ae8dcbc38dd9b1172e237d1a096493485180c33d8bdbdda`；
  `test_corpus_structured_query.py`
  `c5c04073478ff2795cd4d320e9999f6bc994342104081250231bb2031f6d2c44`；
  `test_corpus_structured_delivery.py`
  `cae37d9432155dc10d247a0f6cb5182b496ce2d0837e334772aa0fd45ae592f6`。
  共享 tool 文件当前含 09 的恢复说明增量，该增量已随本轮 07 门禁通过，但其 09 验收归 09 票据。

07 达到全部验收条件并闭环；这只表示确定性查询、分页和证据交付接缝验收通过，不替代 10 的语义
召回质量门、11 的真实模型试验或主计划阶段签认。

### 2026-10-03 最新对话问题修复与复验

用户要求修复最新审核发现。本轮重新打开 07 后修复三个遗漏，并以新增回归先复现、后通过：

- `material_relations` 发布工件按角色隔离，不再错误地从关系工件自身的空 `items` 取端点；查询现在从
  同一 accepted publication 的已发布 `material_items` 建立端点索引。关系可按完整端点文本命中，交付
  证据同时包含关系证明和两个端点证明，不能在缺少端点上下文时标成完整证据。
- 补齐冻结调用面的 `python -m plugins.corpus.structured.cli query` 子命令，支持 source/build、purpose、
  query text、limit、cursor、响应预算、重复字段过滤和显式 store root；成功、未发布、游标不可用及输入
  非法映射到冻结退出码。跨进程、跨 cwd 测试同时核对 SQLite mtime/size，证明查询只读。
- 为公开的 `SemanticQueryRecord.validate_references` 补充文档字符串；新增关系端点全文与 CLI 进程级
  正/负路径回归。没有改变 v1 页面 Schema、排序版本、发布事务或产品 profile。

复验结果（WSL 仓库根目录）：

| 命令 / 范围 | 退出码 | 结果 |
| --- | --- | --- |
| 两条新增回归 | 0 | 2 passed |
| query/delivery/fetch/CLI 专项 | 0 | 54 passed |
| 07 原样测试验收命令 | 0 | 48 passed |
| Git 已跟踪 `test_corpus_structured_*.py` | 0 | 327 passed |
| 工具注册与正文分页回归 | 0 | 36 passed |
| 本轮 5 个修改文件 Ruff + format check | 0 | All checks passed；5 files already formatted |
| 验收范围内全部 Git 已跟踪 Python 文件 Ruff | 0 | All checks passed |
| query/CLI/ledger/tool 定向 Pyright | 0 | 0 errors / 0 warnings |
| import smoke stage 1 / stage 2 | 0 / 0 | 386/386；435/435 |
| symbol closure | 0 | 0 missing / 484 files |
| `git diff --check` | 0 | 无空白错误 |

原样目录级 Ruff 和未限定的 structured 通配测试在复验期间会纳入任务 10 正在并行创建、尚未被 Git
跟踪的 `plugins/corpus/structured_scoring.py` / `tests/test_corpus_structured_scoring.py`；前者当时报告该
在途文件的 Ruff 项，后者当时因该文件尚未导出 `EvaluationReadiness` 在收集期停止。本轮没有改写、
删除或掩盖这些任务 10 文件；改用等价的 Git 已跟踪范围复验 07，结果如上。这一并行状态不构成 07
回归通过的虚假证据，也不阻断已隔离的 07 验收。

本轮交付指纹：

- `plugins/corpus/structured/query.py`: `ac19677e146adbecb53413faad88cfcf7c1e317e3c135878dffbb22a8b280558`
- `plugins/corpus/structured/cli.py`: `388687ed1ebb8283cb176b36c00281b1d79fce3498426e4d81f45f65432042bc`
- `plugins/corpus/structured/ledger.py`: `0c8b46f5715bc1a6c9998e979e14845b811854248def6b34882da24d4416898e`
- `tests/test_corpus_structured_query.py`: `24741b0324b13a52b7cccb2677cfc501dc0631ded2171c9b1d07e220bcfa991f`
- `tests/test_corpus_structured_cli.py`: `7f79880d4473017d6f63dff98a1452f3ff4b6edef6d199da023fdc9a360da30a`

真实模型调用 0、生产数据库访问 0，未运行真实 preflight。上述三个最新审核问题均已修复并有失败
前/通过后的回归覆盖；07 再次达到验收条件并闭环，不替代任务 10/11 的独立门禁。
