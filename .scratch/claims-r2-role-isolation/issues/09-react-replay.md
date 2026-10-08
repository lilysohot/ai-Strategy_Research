# 09 · react/tui 产品接线与零模型端到端验收

Status: ready-for-human
Execution: 两项 P2 已修复并通过本地回归；待复验签认；真实 M_extract 候选已在 11 运行，但发布后经 react/tui 进入 M_main 的真实消费仍未完成
Type: task
Plan: W5 回放；R2-S3
Blocked by: 无本地实现依赖；待独立复验签认，以及通过质量门并发布的真实候选供 M_main 消费验收
Real model calls: 0
Production database access: 0

依据：[实施规格](../spec.md)、[设计报告](../report.md)、[唯一主计划](../../../docs/plan/claims-market-closed-loop-plan.md)。本票遵守 spec 第 5 节全局约束；新增文件/测试是待交付项，不表示当前已存在。

## 目标

证明从快照到报告校验的最小链路确实经过用户使用的 react/tui 入口，而不只是内部函数可调用。

## 前置与外部门

08 已验收；01—08 的传递依赖证据齐全。主计划 S3 的 I3 等外部门另行核对；本票回放通过不单独宣告阶段放行。主线和抽取都使用 fake/replay，不需要用户真实 .env。

## 范围与预期文件

- plugins/tools/__init__.py、workflows/stateful_react_agent/profiles/tui.yaml、nodes/main_agent.py、apodex/profiles/react.yaml 的实际绑定路径。
- plugins/corpus/research_discipline.py、corpus_manifest.py 的提示词/工具说明。
- tests/test_corpus_structured_react_replay.py、受控 CLI/loop 回放夹具。
- 在明确实验 profile/配置下接通只读工具 `corpus_semantic_query`；根目录只从
  `CORPUS_STRUCTURED_ROOT`/显式参数取得，不擅自为所有用户默认开启，其他产品入口保持未验证。

## 验收条件

- [x] 录制真实 workflow 的工具名单，查询、原文回退和伴随报告清单按契约绑定；不在终端 profile 重复维护无效 tools 列表。
- [x] 充分语义证据成为合法引用路径，旧 search snippet 仍不可直接引用；提示词不强迫每条再 fetch。
- [x] 通过正式调用链生成/保存/发布合成两路工件，关闭写端，从新研究 run/cwd 查询并经过全部后处理进入主线消息。
- [x] 消费观察者核验送达，主线回放提交报告清单，经 pending/确认/最终锚点检查，正例最终 verified。
- [x] 仅新查询活动不 skip，无后台模型请求、无真实主线模型请求，充分证据路径无例行 Agent fetch。
- [x] 缺脚注、坏句柄、预算裁剪、目录不可见、撤回、resolver 故障分别触发对应缺口/修订/原文回退；不能以未检查状态出具成功。
- [x] 原文研究路径回归，关闭新查询后旧入口仍可运行；市场响应固定，不以真实行情变化影响结果。
- [x] 输出验收 trace、工具名单、模型/网络拒绝记录、调用次数、发布/报告验证结果及输入版本；标为“回放接通”，不是“真实模型接通”。

以上勾选只代表本地零模型自测证据齐全，不代表独立签认、真实模型验收、PG 验收或阶段放行。

## 验收命令

```bash
uv run pytest tests/test_corpus_structured_react_replay.py tests/test_corpus_cli_isolation.py tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py -q
uv run python tools/import_smoke.py --stage 1
uv run python tools/import_smoke.py --stage 2
uv run python tools/check_symbols.py
```

另对实际改动执行 Ruff、类型检查。所有回放请求由假 Adapter 接收，业务网络/生产库禁止；不能手工往账目填 delivered。真实 preflight 留给 11，不在本票执行。

## 非目标

不支持全部 Agent Team/终端路径，不进行真实模型或独立留出试验，不把文件回放当生产 PG 验收。

## 验收记录与后续

交付后追加命令、退出码、结果/工件指纹、未通过项和外部门证据；未验收不得解除下游依赖。更新本票状态，不在 report/spec 中复制一份进度。

### 2026-10-03 本地交付证据

- 显式接线：新进程设置 `REACT_WORKFLOW_PROFILE=tui-semantic`，从 `tui` 派生，
  仅增加只读查询；默认仍为 `tui`。发布目录只读自显式 `CORPUS_STRUCTURED_ROOT`。
  配置及边界说明见 `workflows/stateful_react_agent/README.md`。
- 产品链：正式 snapshot / plan / replay / publish → 写进程退出 → 新 cwd 的
  `TerminalSession(mode="react", tui_mode=True)` → 实际 Scheduler / main_agent /
  loop / 后处理 / 消费观察者 / manifest / 最终 A4。fake 只位于外部模型、PG 原文与
  市场传输接口，不手工确认 delivered。并未操作 Textual UI，也不是 OS 隔离认证。
- 17 项产品回放覆盖 observe/enforce 正例、pending→delivered、请求预算与最终消息
  6000 字符裁剪、缺脚注、坏句柄、撤回、resolver 故障、缺根配置、根目录未挂载、
  关闭实验后的原文路径、固定市场响应。缺脚注在正式路由/发布前被拦截，最终为 draft；
  坏句柄为 unsupported、撤回为 partial、resolver 为 verification_error。
  observe/enforce 均记录失败，仅 enforce 在用户报告中追加 A4 降级说明。
- 实际发现并修复：后处理交付合法结构化 JSON 后，循环层仍追加纯文本恢复提示。
  改为经已有工具端结构化分派识别协议结果并保留其游标/缺口信息，普通文本恢复提示保留。
  补充模型可见的缺口/重新查询/原文回退说明。

验证命令与结果（退出码均为 0；单列的初次证据目录错误除外）：

```bash
# 已确认 basetemp 路径此前不存在；不可覆盖已有证据目录重跑。
mkdir -p .scratch/claims-r2-role-isolation/evidence
env -u CORPUS_I2_DSN uv run pytest tests/test_corpus_structured_react_replay.py tests/test_corpus_cli_isolation.py tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py -q --basetemp=.scratch/claims-r2-role-isolation/evidence/09-product-replay-20261003-final --junitxml=.scratch/claims-r2-role-isolation/evidence/09-product-replay-20261003-rerun-junit.xml
# 70 passed, 1 skipped；缺隔离 PG DSN 的模块级 skip 不等于 PG 验收。
env -u CORPUS_I2_DSN uv run pytest tests/test_corpus_structured_*.py tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py tests/test_corpus_fetch_paging.py tests/test_stateful_workflow.py tests/test_site3_recovery.py apodex/tests/test_profiles.py -q --junitxml=.scratch/claims-r2-role-isolation/evidence/09-expanded-20261003-junit.xml
# 444 passed
uv run ruff check tests/test_corpus_structured_react_replay.py tests/corpus_structured_replay_runner.py workflows/stateful_react_agent/profile.py plugins/tools/corpus_semantic_query.py frontier_agent/core/runtime/loop/agent_loop.py
uv run pyright workflows/stateful_react_agent/profile.py plugins/tools/corpus_semantic_query.py frontier_agent/core/runtime/loop/agent_loop.py
# Ruff clean；0 errors, 0 warnings
uv run python tools/import_smoke.py --stage 1
uv run python tools/import_smoke.py --stage 2
uv run python tools/check_symbols.py
# 384/384；433/433；483 files / 0 missing symbols
```

初次持久化命令因证据父目录尚不存在而在 tmp_path setup 失败（退出 1，70 errors），
没有执行产品断言；原始失败 XML 保留在 `evidence/09-product-replay-20261003-junit.xml`。
补建父目录后执行上述 rerun 成功，没有以失败记录冒充通过。

工件入口：

- [完整回放目录](../evidence/09-product-replay-20261003-final/)：各用例的 write/research
  `replay-result.json`、正式 publication/store、`.apodex/runs/` trace 和 corpus 清单/校验。
- [正例写端](../evidence/09-product-replay-20261003-final/test_product_react_cross_proce0/write/replay-result.json)
  与 [正例研究端](../evidence/09-product-replay-20261003-final/test_product_react_cross_proce0/research/replay-result.json)。
  研究端保存完整工具名单、实际请求消息和每次响应前的送达状态；仅调用 query/submit，
  fake 主线调用 3 次、Agent fetch 0 次、真实模型/生产库 0 次，4 类拒绝探针通过，
  unexpected_access 为空。最终 verified，报告 SHA256 为
  `3b3f5921555acf33d0fed6bbad557b7efe8c358fb5689518423279c27ce6ae03`。
- 合成输入 source_id 为 64 个 `7`，build_id 为 64 个 `8`；snapshot_id
  `sha256:017a5a6850a3c5ba0d32ba5f67778a9eb2cfcfbe40cdf7029aca44ffaa961354`；
  plan_sha256 `sha256:a30a34425279396a172a3328f6418afab5823574d74fd867a035eb816a1e6b1d`；
  publication_id `sha256:a860512c6dba01435cfa195e044afae21da5fcebfa15102ca7b4769799496ce0`。
- 测试时 HEAD 为 `bc0b5f9`；工作树存在本票未提交改动，故以文件指纹为准。

关键 SHA256：

| 文件 | SHA256 |
|---|---|
| `frontier_agent/core/runtime/loop/agent_loop.py` | `b273d366e7e86c4846e9999a3f2d84d6a740cf26b45a8bfbe302c23c9d24cfc1` |
| `plugins/tools/corpus_semantic_query.py` | `65361a3e6c0259cc4ae8dcbc38dd9b1172e237d1a096493485180c33d8bdbdda` |
| `tests/test_corpus_structured_react_replay.py` | `796d93977ac44c7112cdd9ab40b1e4ecb82471fede64327c6ca698d299512649` |
| `tests/corpus_structured_replay_runner.py` | `9006e4e1863482be159c48011499593f42bc92e7123ffeb1e9e51ce917781a1e` |
| `apodex/profiles/react.yaml` | `78448485d40f54c02b16395eaac475ab0da0dea92c9f8dd6e97720db6ab0ab1e` |
| `workflows/stateful_react_agent/profile.py` | `6892f137b2db884db3f26364ef4ec0c49512cea2531d3c9e947454095efb178e` |
| `workflows/stateful_react_agent/profiles/tui.yaml` | `26e220c0d146f09ad49c466d52fa801dab7f6470e56aa9e04d42cc0659a31c6e` |
| 专项 rerun JUnit | `6de926654df7ca6375714a947fd6e2d694e3d462aa393e1b70b7b6df664df96d` |
| 扩展 JUnit | `c710feb2b99868e97e1f6939835397f0ef07b04f060399bf6a1c6c54b695edf6` |

未完成：用户提出的真实模型测试仍需明确模型、数据范围及调用/金额/时间预算；
回放写/读子进程拒绝真实 .env 和外部请求；没有运行真实 preflight 或访问生产 PG。
上述拒绝证据不扩大为 pytest 父进程的全局配置读取审计：现有共享 fixture 会初始化
server 配置后将数据库/运行目录改为临时路径；父进程是否加载 .env 不在本票探针范围。
未开展独立验收，不解除
11 的依赖、不改变主计划阶段门，不将此次结果标为“真实模型接通”。

## Comments

- 2026-10-02：仅编制任务，尚未执行。真实模型与生产库额度均为 0。
- 2026-10-03：用户再次明确“执行09任务”，按本票正式入口与发布/消费接口推进接线及
  安全回归。用户另要求真实模型测试：该验收要求保留，但具体模型、来源、请求/金额/时限
  尚未明确，本轮不发送真实请求、不将回放成功当真实模型验收通过。
- 2026-10-03：用户要求继续下一任务，启动 09 前置核查。08 的 P3 docstring 遗漏已补齐，
  87 项专项测试及 Ruff/定向类型检查通过，解除本地依赖；07 的复验通过证据在本对话中，
  其历史票据仍待单独回填。未修改主计划阶段状态。
- 已确认实际入口为终端 react profile → stateful-react-agent/tui，工具绑定由 workflow
  profile 负责；新工具须显式实验配置启用，不在终端 profile 复制 tools 列表。
- 按 tdd 技能先请求用户确认测试边界：正式快照/回放/发布接口，以及 react/tui 实际工具
  绑定、消息送达、最终 A4 结果。确认前未新增测试、未修改 09 产品代码。
- 外部门按主计划公开台账核对：历史 I3-1 未完成描述已被后续记录取代，主计划已记录
  M6/M7 放行；但 R2-S3 仍为待执行，本票回放不能代替阶段签认。未读取任何真实样本。
- 票据列出的 `tests/test_corpus_cli_isolation.py` 依赖隔离 PG 的 `CORPUS_I2_DSN`，
  未配置时会模块级 skip；该 skip 不能当作零模型文件回放或 PG 验收通过。

### 2026-10-03 · 审核遗漏修复（追加记录）

用户要求针对审核问题修复。此前记录及指纹保留为历史基线；本节覆盖本轮交付版本。

1. **Standards P2 / 白名单覆盖顺序**：先派生实验 profile 默认工具，再应用 caller
   overrides。公开 `load_react_profile` 的空列表和 `['read_file']` 回归先失败、修复后通过。
   这里验证 profile 合并结果，不将空列表解释为运行时所有工具的禁用开关。
2. **Spec P2 / 研究端写权限**：`TerminalSession.run_task` 在实验 profile 下先检查
   发布根目录的只读挂载及嵌套挂载，可写时在任何模型请求前拒绝；不接受同 UID 可修改的
   chmod 权限位作为替代。正常回放整体运行在 bubblewrap 只读宿主树中，仅研究 cwd 可写，
   PID/网络 namespace 隔离，不提供写端路径的可写别名；不改用户宿主文件权限。
   实际 bash 工具探针验证索引/WAL/SHM、manifest、objects 拒绝写打开，目录拒绝创建，
   文件拒绝 chmod。没有 bubblewrap 时测试失败，不静默降级或跳过。
3. **只读 WAL 兼容**：新增写端 `prepare_readonly_access`，在写连接关闭后准备只读
   SQLite 所需 WAL/SHM；业务行不变。读端不代写、不使用 `immutable=1`，避免掩盖后续
   撤回。撤回由 namespace 外固定的合成写进程执行，随后重新准备 sidecars；研究进程
   仅通知测试控制器并等待确认，不能自己切换为写端。最终撤回结果仍为 partial。
4. 隔离后曾因 tokenizer 缓存不可写而触发词表下载尝试（网络探针已拒绝，并非模型请求）。
   已在外部词表下载接口显式禁用传输，使用实际估算器已有离线分支，单独记录
   `tokenizer_downloads_refused`。新证据所有研究运行 `unexpected_access=[]`；调试日志已清理。

使用 tdd 的 red→green 流程及 diagnosing-bugs 的最小失败回放定位；不进行真实模型调用。
发布目录及启动方式见 `workflows/stateful_react_agent/README.md`。检查只覆盖实验终端入口；
部署必须排除同一 store 的可写别名，不声称整个 native 模式获得通用安全认证。

复验命令（全部退出 0）：

```bash
# basetemp 确认此前不存在；后续复验必须另选新目录，不能覆盖本次证据。
env -u CORPUS_I2_DSN PYTHON_DOTENV_DISABLED=1 uv run pytest tests/test_corpus_structured_react_replay.py tests/test_corpus_cli_isolation.py tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py tests/test_site3_recovery.py -q --basetemp=.scratch/claims-r2-role-isolation/evidence/09-readonly-fix-20261003 --junitxml=.scratch/claims-r2-role-isolation/evidence/09-readonly-fix-20261003-junit.xml
# 96 passed, 1 skipped（仅隔离 PG 未配置，不视为 PG 验收）
env -u CORPUS_I2_DSN PYTHON_DOTENV_DISABLED=1 uv run pytest tests/test_corpus_structured_*.py tests/test_corpus_ledger.py tests/test_corpus_manifest_tool.py tests/test_corpus_fetch_paging.py tests/test_stateful_workflow.py tests/test_site3_recovery.py apodex/tests/test_profiles.py apodex/tests/test_terminal.py apodex/tests/test_features.py apodex/tests/test_native.py apodex/tests/test_cli_overrides.py -q --junitxml=.scratch/claims-r2-role-isolation/evidence/09-readonly-expanded-20261003-junit.xml
# 589 passed
uv run ruff check apodex/semantic_access.py apodex/task_runner.py workflows/stateful_react_agent/profile.py plugins/corpus/structured/store.py plugins/tools/corpus_semantic_query.py frontier_agent/core/runtime/loop/agent_loop.py tests/test_corpus_structured_react_replay.py tests/corpus_structured_replay_runner.py
uv run pyright apodex/semantic_access.py apodex/task_runner.py workflows/stateful_react_agent/profile.py plugins/corpus/structured/store.py plugins/tools/corpus_semantic_query.py frontier_agent/core/runtime/loop/agent_loop.py
# clean；0 errors, 0 warnings
uv run python tools/import_smoke.py --stage 1
uv run python tools/import_smoke.py --stage 2
uv run python tools/check_symbols.py
git diff --check
# 385/385；434/434；483 files / 0 missing symbols；无空白错误
```

本轮共有 22 项产品接线/回放测试。证据保存在
[只读修复回放目录](../evidence/09-readonly-fix-20261003/)：

- `test_product_research_tools_ca0/research/replay-result.json` 含实际 bash 拒写响应
  `READONLY_CONFIRMED`，其后 query/manifest 正常，最终 verified；对应完整 trace 位于
  同目录 `.apodex/runs/`。
- `test_product_refuses_writable_0`（根可写）与 `..._1`（嵌套 objects 可写）均记录
  startup_error，fake 模型请求数也为 0。
- 原正例 observe/enforce 均 verified；仅 query/submit、fake 请求 3 次、无例行 fetch。
  坏句柄 unsupported、撤回 partial、resolver 故障 verification_error、缺脚注 draft。
- 真实模型/生产 PG 访问仍为 0。只读修复通过不替代用户要求的真实模型试验；不修改
  11 依赖和主计划阶段状态，保留待复验签认状态。

本轮 HEAD 仍为 `bc0b5f9`，文件与 JUnit 的 SHA256：

| 文件 | SHA256 |
|---|---|
| `apodex/semantic_access.py` | `4f944a064a1d54cfdb20a275652615c8b5cacaf8d811d2a466224a9e358c35fc` |
| `apodex/task_runner.py` | `0dbaf2ce5ee1c5e44279875f03f9ca24783b863a68fa4c79e0c76471d378eb65` |
| `workflows/stateful_react_agent/profile.py` | `85ec8ed095cea6d6b86d2f87c9ba2992171b1d8f394ccaddca5662fba51d1e2e` |
| `plugins/corpus/structured/store.py` | `9db2bb5d663b028b7d7a38c53a1ceca1000c088b8a2a56144b0bcd64bdb7a8b7` |
| `tests/test_corpus_structured_react_replay.py` | `46dea62fffd61f295b65c6196aa9004d981c721247e8a32d2dcf14576b8e2a8f` |
| `tests/corpus_structured_replay_runner.py` | `c3bcf857b0f380e03fc2ef013d18bbcae8785f2b633b1c5e2a2667b9bc4923f1` |
| 本轮专项 JUnit | `23ac506e0a6acb2235c2ded2bfee4aaa0ba8df8d052c2dd2ff6586e847282a7c` |
| 本轮扩展 JUnit | `0ead356d69dfa3af3e28f3fc80be2b23583a00c3db51f96b9b95deaf5549ef3d` |

### 2026-10-08 · 状态回填

11 已在独立授权下完成真实 M_extract 的 Claims preflight 和第 1 页 R2 候选抽取，因此此前
“模型/来源/调用预算尚未明确”的阻断已解除。该执行没有发布候选，也没有启动 M_main，不能替代
本票要求的真实产品消费验收。09 仍保持 `ready-for-human`：本地零模型回放和 P2 修复证据齐全，
待独立复验签认；真实端到端部分等待 10 的质量门、正式发布及新研究运行。
