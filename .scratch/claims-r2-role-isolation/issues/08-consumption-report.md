# 08 · 证据消费账、报告清单与 A4 校验适配

Status: ready-for-human
Execution: 已验收（本地功能核验与规范遗漏闭环；不代表阶段放行）
Type: task
Plan: W5 前置接线；R2-S2/S3
Blocked by: 无本地任务依赖（07 已在本对话复验通过）
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

把新查询实际送达的原文证据纳入现有 ConsumptionLedger、corpus_submit_manifest 和最终报告检查，不平行建设报告校验系统。

## 前置与外部门

07 已验收，01 的报告引用/依赖表示已冻结；复用现有 50 项消费账/清单测试作为回归，不把它们当本票新功能已通过的证据。

## 范围与预期文件

- plugins/corpus/ledger.py、plugins/tools/corpus_manifest.py、必要的 workflow 发布调用接缝。
- tests/test_corpus_structured_consumption.py；扩展 test_corpus_ledger.py、test_corpus_manifest_tool.py。
- 新查询活动登记、实际消息送达、语义记录/发布版本和原文范围桥接、伴随清单绑定；报告侧桥接遵守
  `contracts/v1/report-semantic-reference.schema.json`。
- 报告依赖作用 value/period/unit/header/footnote 等与 cite/compare/calculate 许可分开；条件/否定/归属按 01 的受控表示校验。

## 验收条件

- [x] 不伪造 corpus_fetch 事件；只记录真实工具调用与原文范围，抽取成功、记录 ID 或后台 resolver 读取不等于 delivered。
- [x] pending 经实际消息确认后才能变 delivered；裁剪/压缩/缺必要片段不能被已发布状态掩盖。
- [x] 仅新查询活动也绑定清单工具并进入 A4 检查，不因 offered/fetched 旧条件而 skip。
- [x] 报告清单绑定 report_quote、原文多段引用及语义版本；重复引文用精确区间，不按首次命中认定证据已送达。
- [x] 后端仍核对权威原文、引用和报告锚点，并只读检查语义撤回/用途/依赖有效性；不要求 Agent 例行重读原文。
- [x] semantic publication manifest 不能当 report evidence manifest，执行账不能替消费账；原文路径旧报告清单保持兼容。
- [x] 正例 verified；错误句柄、未送达、依赖缺失、撤回和基础设施故障得到真实错误/降级，observe/skip 不冒充过门。
- [x] 保持现有全局 A4 默认观测策略，分别测试 observe/enforce，不借适配修改全局产品阻断策略。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_consumption.py tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py -q
uv run ruff check plugins/corpus/ledger.py plugins/tools/corpus_manifest.py tests/test_corpus_structured_consumption.py
```

resolver 用明确的同版本合成原文 Adapter；不得为通过测试跳过逐字核验、消息送达或 report_quote 检查。

## 非目标

不新增模型裁判，不把确定性 A4 成功当报告语义绝对正确，不修订历史报告或放宽普通 search snippet 引用限制。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
- 2026-10-03：用户要求开始 08；依据同一对话中 07 双轴复验通过（48 项专项、306 项回归）
  解除本票前置依赖。仅执行消费账、报告清单及 A4 适配，不启用 profile、不执行 09—11；
  真实模型和生产库访问额度保持 0。07 文档状态仍待单独回填，本票不修改其历史记录。
- 2026-10-03：实现完成，转 `ready-for-human / 待验收`。勾选项表示实现与本地测试覆盖，
  不替代人工验收，不解除 09 依赖。

### 实现与证据

- `ConsumptionLedger.semantic` 单独记录真实 query 调用、调用 ID、source/build、query/page、
  publication/record、精确原文和送达状态；没有调用 `record_fetch_*` 伪造旧事件。
- 新增 `plugins/corpus/semantic_delivery.py` 的请求确认适配，在 stateful workflow 实际绑定
  `corpus_semantic_query` 时启用；位于消息压缩及 middleware 改写之后，成功 chat 或首个 stream
  响应才核对实际请求。采用独立包装保留原始共享客户端，覆盖 middleware 及两类 fallback。
  仅按同 tool_call_id、publication/query/purpose 和完整 record/evidence/dependencies 确认送达，
  assistant 中相同文字、错误调用、裁剪/改写、未发出/失败请求均不能补成 delivered。
  最后一轮工具返回但没有后续模型请求时保持 pending；旧 finalize/on_loop_end 不改变该状态。
- 新增 `structured/consumption.py` 作为既有 A4 的语义引用 Adapter，不新建报告校验入口。
  复用 `read_semantic` 同版本冻结 source snapshot 和 `query.publication_records` 的确定性投影；
  后台按 build/chunk/unit/[start,end) 核对原文、hash、完整依赖、质量与用途，拒绝撤回/替换版本。
  不用字符串首次 find 定位；重复文本跨 unit 不能互相冒充送达，偏移/句柄/hash 改写被拒绝。
- `corpus_submit_manifest` 支持 `semantic_references`：可提交冻结 v1 完整引用，也可选择
  publication_id/record_id/purpose，由本运行真实 query 回执补齐范围/依赖并落成正式引用。
  报告 report_quote 与 anchor 仍必需；状态全部重算，不信任模型自报 verified/delivered。
  `value/period/unit/header/footnote/condition/negation/attribution` 与 cite/compare/calculate
  分开。旧原文 evidence 清单、拥有者聚合和 A4 发布逻辑保持兼容。
- 仅新查询也伴随绑定 manifest 工具，甚至失败/空查询活动也不再 skip。提示允许完整语义原文路径，
  仍禁止 search snippet 直接引用。后端核验不计作 Agent 阅读，不要求例行 fetch。
- 新专项测试通过真实 snapshot→plan/replay→publish→正式 query/manifest 工具与 run_agent_loop，
  从实际后续请求确认送达并最终获得 verified；observe/enforce 均覆盖。保留 50 项旧回归并扩展
  3 项旧文件测试，另有 34 项新专项测试。负例覆盖 pending、假状态、裁剪、压缩、错误调用、
  错误句柄/区间/hash、必要依赖删除、用途不许可、报告锚点不符、撤回、后到冲突收紧用途与 store 故障。

### 2026-10-03 验证记录

命令均从 WSL `/home/administrator/FrontierAgent` 执行。交付时 HEAD 为
`90e1a6e820ab37ab0c4bbc7944cfeaf6948bf4f8`；工作期间其它任务推进了 HEAD，本任务未提交、
回退或覆盖该提交。新增测试只写 pytest 临时目录，阻断 socket/DNS、HTTP、dotenv 与生产
CorpusService 连接；使用真实文件 Adapter + 合成同版本原文，不绕过逐字核验。

| 命令 | 退出码 | 结果 |
| --- | --- | --- |
| `uv run pytest tests/test_corpus_structured_consumption.py tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py -q` | 0 | 87 passed；本票原样验收命令 |
| `uv run pytest tests/test_corpus_structured_*.py tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py tests/test_corpus_fetch_paging.py tests/test_tool_registry.py tests/test_stateful_workflow.py -q` | 0 | 400 passed，structured 全量及消费账/注册/分页/workflow 回归 |
| `uv run pytest tests/test_research_discipline.py -q` | 1 | 6 passed / 1 failed；下述既有终端 profile 工具断言不适用于 workflow profile |
| `uv run ruff check plugins/corpus/ledger.py plugins/tools/corpus_manifest.py tests/test_corpus_structured_consumption.py` | 0 | All checks passed；本票原样验收命令 |
| `uv run ruff check plugins/corpus/ledger.py plugins/corpus/structured/consumption.py plugins/corpus/structured/query.py plugins/corpus/semantic_delivery.py plugins/corpus/research_discipline.py plugins/tools/corpus_manifest.py workflows/stateful_react_agent/nodes/main_agent.py tests/test_corpus_structured_consumption.py tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py` | 0 | 全部本轮修改路径通过 |
| `uv run pyright plugins/corpus/ledger.py plugins/corpus/structured/consumption.py plugins/corpus/structured/query.py plugins/corpus/semantic_delivery.py plugins/tools/corpus_manifest.py workflows/stateful_react_agent/nodes/main_agent.py` | 0 | 0 errors / 0 warnings |
| `uv run pyright` | 1 | 8 个非本轮修改路径错误：gradio 缺失、run_retention 3 项、server 4 项；未声称全仓过门 |
| `uv run python tools/import_smoke.py --stage 1` | 0 | 383/383 |
| `uv run python tools/import_smoke.py --stage 2` | 0 | 432/432 |
| `uv run python tools/check_symbols.py` | 0 | 0 missing / 482 files |
| `git diff --check` | 0 | 无空白错误 |

已知限制：额外投研纪律回归中的 `test_react_profile_binds_the_finance_tools` 仍按终端 profile.tools()
检查 react 工具，而 HEAD 中 `apodex/profiles/react.yaml` 明确不配置终端 tools，实际绑定由 workflow
profile 提供。该测试及 profile 本轮未修改，不为通过旧断言额外启用/复制工具。此项与上述全仓
Pyright 错误如实保留；09 的实际产品 profile/入口端到端核验、10 的质量召回门与 11 的真实模型门
仍未执行。真实模型调用 0、生产数据库访问 0；未运行真实 preflight，未修改 A4_ENFORCE 默认值。

SHA-256（本轮交付代码）：

- `plugins/corpus/ledger.py`: `78387b3c1fe347da911632e28f9113adfd4a83c98486fd21c4914a3ec95530b3`
- `plugins/corpus/structured/consumption.py`: `75a4a1f7908a5d90e45c90b0cbecb56899e655bcc4db7bc365a2273477fa5c77`
- `plugins/corpus/structured/query.py`: `2de2ef3ec5c3958753f41f96c5be1127e3c3ad4d726c1f65680fa0d3bff0f97a`
- `plugins/corpus/semantic_delivery.py`: `a4147ce32e40f42e5a68dbc95f70396c01e557c3c953093d59fa4d8eb9495816`
- `plugins/corpus/research_discipline.py`: `ae22df28a41414e2efdc9c087666d6bee884edc5f5ce2072e76352fbd7d203c5`
- `plugins/tools/corpus_manifest.py`: `f059ac7f35852042ea9afe6473d62dabf4de87e5b7373c605a6b96f0298441e6`
- `workflows/stateful_react_agent/nodes/main_agent.py`: `6bed01ceef85b3ea0bdf961d097ed689943eae3f92f53c3e92888c651101dc6f`
- `tests/test_corpus_structured_consumption.py`: `0346a833fddd85a56c61dab28050728786340d40905cc4eb1f7a37b03e364a3d`
- `tests/test_corpus_ledger.py`: `e93e9afe2740d200ededaf89cfffaec89c835c257616d050971c72c01c953eb9`
- `tests/test_corpus_manifest_tool.py`: `34327495cb9e064bee0d3ccd2b07b1b9eb97c1403ea27c652748f03c96d5a285`

### 2026-10-03 复核与收尾

- 用户要求回溯审核后，Standards/Spec 双轴核验：Spec 无功能缺陷；Standards 发现
  1 项 P3（5 个公开函数/类型缺 docstring）。用户随后要求继续下一任务；启动 09 前
  已补齐该项，仅增加说明，不改变运行行为。本地验收遗漏已闭环。
- 收尾后重跑本票 pytest：exit 0，87 passed；
  `uv run ruff check plugins/corpus/structured/consumption.py`：exit 0；
  `uv run pyright plugins/corpus/structured/consumption.py`：exit 0，0 errors。
- 审核时扩展回归为 398 passed / 2 failed；两项失败位于 `tests/test_tool_registry.py`，
  来自本票范围外、并行修改的 `plugins/tools/__init__.py` 投资工具注册，不覆盖此前
  400 passed 的历史记录，也不宣称当前全仓全绿。审核时本票 10 个文件均匹配交付指纹。
- 审核时全改动路径 Ruff/定向类型检查通过；import smoke stage 1 为 384/384、stage 2
  为 433/433；符号闭包 0 missing / 483。真实模型、生产库访问均为 0。
- 文档说明补齐后 `plugins/corpus/structured/consumption.py` SHA-256：
  `2ad168701553c658eeaf4a38d3c449419237151ce1b6fcf7a4f739216df4ae52`。
  上节指纹保留为原交付历史；其它 08 代码文件未改。仅解除 09 本地依赖，不宣告 R2 阶段放行。
