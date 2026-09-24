# M7 全量测试与目标符合性复核（2026-09-24）

**结论：I4 的数据库迁移、8 源发布及旧表清理事实获证；M7 尚不能判定完整通过。**
当前默认启动无法检索生产库，旧 ingest 写入口没有真正退出；此外冻结全链路测试有一项稳定失败。
显式配置生产目标后，30 道冻结题仍通过，不能将上述问题归因为全部检索或取证能力失效。

范围：当前 HEAD `1f69be1df7caeae7660c06ddc0d1da4d8470b20a` 加开始复核时已有的未提交 r5i 工作区；
M7 差异基线 `be74cbf8fb40b94d97b3702ca987712e832b13ad`。两份用户指定文档作为规格资料，
并对照任务分解与实际批准/执行记录；没有将文档内历史命令当作本次执行指令。
没有修改产品源码、冻结链或历史报告，没有写生产库，没有执行真实模型 preflight。
新增脚本与证据仅放在本目录；PG 测试写入仅发生在既有隔离实例 `127.0.0.1:543`。

## 测试结果

各行存在重复覆盖，**不能相加作为唯一测试数量**。

| 检查 | 本次结果 | 证据 |
|---|---|---|
| 全仓 `pytest tests apodex/tests -q --tb=short -ra` | **2929 passed / 2 failed / 49 skipped**，236.13 秒 | [pytest.log](pytest.log) |
| M4 普通/零模型 i1 守卫测试 | 各 **320 passed / 7 skipped**；跳过的 PG 用例另补验 | [普通](lane-m4-plain.txt)、[守卫](lane-m4-i1.txt) |
| dev lane | **9 passed** | [日志](lane-dev-lane.txt) |
| 真 PG 检索 | **11 passed** | [日志](lane-m5-search-live.txt) |
| 冻结全链路 12 项 | **11 passed / 1 failed**；单独重跑同一失败 | [完整](lane-fullchain-12.txt)、[复现](lane-fullchain-confirm.txt) |
| PG 发布/存储/权威读取/CLI/消费者/入库检索 | **78 passed，零跳过** | [日志](lane-m5-hermetic.txt) |
| D2/D6 真 PG | **73 passed，零跳过** | [日志](lane-m5-dsn-d2d6.txt) |
| 缺口 CLI/状态补验 | **13 passed，零跳过** | [日志](lane-supplement-gap.txt) |
| 审计/证据/CSV 备份恢复补验 | **24 passed，零跳过** | [最终日志](lane-supplement-audit-evidence-ready.txt) |
| 生产库冻结 30 题，原题干、limit=10、真实注册工具 | 显式目标配置下 **QP 24/24、EP 24/24、负例误报 0/6、工具失败 0** | [结果](live-explicit.json)、[逐调用](product-trace.json) |
| 默认配置真实工具 | **失败**，目标 postgres 被当作 sandbox 校验 | [结果](live-default.json) |
| CI 范围 Ruff / Pyright / 符号闭包 | 全通过；Pyright 0 错误；465 文件 0 缺失符号 | [ruff](ruff.log)、[pyright](pyright.log)、[symbols](symbols.log) |
| 两阶段 import smoke | **366/366、415/415** | [阶段一](imports1.log)、[阶段二](imports2.log) |
| r5i 冻结验证器 | exit 0；其证据覆盖限制见下文 | [日志](freeze.log) |
| 最终备份原清单哈希复核 | **25/25 一致** | [日志](backup-integrity.log) |
| corpus 格式检查，仅检查不改文件 | 2 个历史文件不合格式 | [日志](format.log) |

补验的首轮审计/证据组为 23 passed / 1 failed：新建临时旧链数据库缺 `public.zhcfg`，
跨两个临时 schema 恢复时找不到配置。按真实旧库前置条件初始化公共检索配置后，原测试不改即 24/24；
保留[首轮日志](lane-supplement-audit-evidence.txt)，不将它当作 M7 新回归。

原全仓的 49 个跳过包含模块级跳过；核心 PG 家族、D2/D6、审计、备份恢复、gap 门已另跑。
旧 golden/B7 的就绪检测依赖 legacy `stats().documents`，本次没有靠篡改该检测把旧测试计作通过；
生产 30 题及新权威取证测试是独立覆盖，不等同于旧 golden/B7 已通过。

## Standards

### S1 · P2：目标配置在导入时缓存，之后加载配置不能生效

`plugins/corpus/service.py:110`、`preparation/read_pg.py:38`、`search_pg.py:44` 在 import 时保存目标，
但 `pg_target.py:31` 在每次调用时读取当前授权变量。无网络反例：先 import，再设置
`CORPUS_TARGET_DB=postgres`，即时解析已经是 postgres，三个消费者仍保存 i2_sandbox_corpus。
现有 `scripts/corpus_holdout_eval.py:24/241` 确实先导入服务再 load_dotenv，故仅补 `.env` 并不保证所有入口恢复。
依据是新配置接口自身“显式目标优先”的承诺；不是风格偏好。
建议在构造服务/存储实例时统一读取并传递目标，避免模块常量与动态授权分离。
证据：[counterexamples.json](counterexamples.json)；本次未运行留出脚本或读取留出材料。

### S2 · P2：两个检索入口的选择逻辑分叉，冻结回路测试不再通过

`service.py:1054–1073` 的 `search_with_coverage()` 使用 retrieval_query 和 `_selected_context_hits()`；
`service.py:1330–1345` 的 `search()` 使用原查询和 `_selected_chunk_hits()`。
相同合成语料、查询“产能利用率”、limit=5：service 首条取回营业收入/净利润段，工具首条取回产能利用率问答。
冻结 `test_fullchain_probes.py:200` 连续两次失败。此处是**命中选择语义不一致**，
不是同一个版本句柄返回不同正文，也没有发现原文被篡改。
依据：任务分解 I3-7/I4-5 的旧回路非回归要求，以及 service 对共同新链接口的承诺。
建议复用一套检索选择逻辑；若有意让两种接口具有不同语义，应明确修订契约并重新验收，不能忽略原门失败。
该分叉在 M6 r5e 已出现，本次才由重跑揭示，不能归因为 r5g 新增目标变量。

本轴 2 项，最高 P2；没有把工具已覆盖的格式问题或纯风格猜测列入本轴。

## Spec

### G1 · P1：窗口脚本成功，日常默认服务尚未恢复

任务分解 I4-5（`docs/plan/corpus-ingestion-rebuild-tasks.md:621`）要求真实路径核验后恢复服务。
当前环境与 `.env` 没有 `CORPUS_TARGET_DB`，默认仍为 sandbox；独立新进程加载当前 corpus 配置后，
真实 `corpus_search` 返回 `ok=false`：`current_database='postgres' ≠ 'i2_sandbox_corpus'`。
窗口 `i45_tool_roundtrip.py:155–161` 强制额外设置目标，只证明该特别环境能工作。
显式 `CORPUS_TARGET_DB=postgres` 后生产 30 题通过，准确定位到切换配置/启动接线缺口。
建议交付正式运行环境配置，并以真实启动过程、新进程默认配置重验 search→fetch；同时处理 S1。

### G2 · P1：“旧写入口停用”没有落实到入口或权限

I4-5 要求“停用已批准旧写入口”，切换 manifest 还禁止 public 旧表写入。
`i45_tool_roundtrip.py:224–232` 以只读调用前后旧表零行，声明 ingest/evidence 写入口停用。
但 `service.py:3215` 仍从旧 ingest 命令调用 `run_ingest()`；`:2720` 在新链入库前先 `_ledger_start()`，
`:2758` 插入旧 `ingest_runs`。模拟真实连接接口后，入库因缺配置失败（exit 2），仍执行 INSERT、UPDATE、两次 commit。
证据：[counterexamples.json](counterexamples.json)，真实数据库连接数为 0。
建议对已批准退休入口显式拒绝或迁移台账至 corpus_jobs，并增加“失败路径也不能写旧表”的验收。
仅保留共享类型/财务验证代码不与此冲突，也不要求删除全部历史模块。

### G3 · P2：恢复门的现有报告超出其实际记录的验证范围

任务分解 I4-6（`:617`）要求哈希、数量、权限/扩展、历史取证与窗口内耗时。
`i46-restore-verification.json` 记录 pg_restore --no-owner、11 表数量、4 扩展与词典，
没有恢复后权限对账、历史证据引用回环及实测恢复耗时；窗口报告却称历史取证核验通过。
本次已独立核对备份 25/25 哈希，**不能据此推断缺失验证已完成，也不能据缺记录断言备份不可恢复**。
建议补一次有权限及旧引用往返证据的隔离恢复记录，再判完整满足 I4-6；本次未重新恢复生产备份。

### G4 · P2：冻结链通过不能证明全部窗口证据已绑定

架构及任务分解 `:644` 要求报告绑定实际快照、版本及代码指纹。
`i45-tool-roundtrip.json` 未绑定执行代码快照；r5i 只绑定 tasks.md、validator 和 previous-effective-bindings。
`validate_i0c_freeze.py:2910–2913` 检查的是 tasks.md 中报告文件名与八位哈希文本，
不是该报告实际文件的完整哈希。因此 exit 0 不能替代窗口关键证据一致性验收。
部分记录已有完整绑定：i44 报告绑定 cutover manifest/r5g，phase2 报告绑定 reset manifest；
本次没有观察到这些已记录哈希失配。缺口是关键工件未全部被有效冻结检查覆盖。
建议新增修订绑定窗口报告、两份 manifest、阶段结果及执行脚本，并重验实际文件；不改写历史快照。

本轴 4 项，最高 P1（默认服务未恢复、旧写入口未关闭）。

## 其他观察与边界

- 当前生产实际为 sources/builds/publications 各 8、chunks 834、units 3887，旧九表全部 0，
  保留 docs/chinese_docs 各 3。显式工具测试前后计数与活动指针完全一致。
- `service.py:2612` 的 `stats()` 以及 `:2301` 的 `list_documents()` 仍查旧表。
  显式生产目标配置下 stats 仍输出 documents=0、blocks=0，与 8 个活动来源相反；旧 golden/B7 也因此跳过。
  这是消费者迁移残留，需在后续归并/运维说明中明确处理，不能把旧统计当新链覆盖证据。
- r5g 在 M6 后改变七个运行文件，原记录未提供对应完整 I3-7 重验。此次已补跑受影响测试与生产产品门，
  S2 证明不能自动继承“全绿”结论；尚未代替正式冻结和放行记录。
- 两份 dev lane 和合计八源均在已批准切换清单内，本次不把“没有发布全部 73 源”误判为漏做任务。
  I5/M8 四场景及运维说明尚属后续任务，不在本次要求内。
- 全仓两项既有失败与 `.scratch/m6-repair-20260923/full-pytest.log` 相同：
  `test_market_golden.py:257` 的固定报价日期触发 5 天过期告警；
  `test_research_discipline.py:41` 断言 profile 绑定财务工具，实际集合为空。
  本次不是首次失败；它们仍使全仓不能称全绿。
- 格式检查提示 evidence_pipeline.py、preparation/admission.py 两个旧文件；本次不自动格式化冻结源码。
- 隔离 PG 最终恢复成功：8/8 active，build_id 与原基线逐一相同，临时 D2/D6 数据库已删除。
  见 [主电池](i37-tests-results.json)、[补验恢复](supplement-results.json)、[最终临时库清理](supplement-ready.json)。

## 复现入口

本环境 uv 位于 `/home/administrator/miniconda3/bin/uv`，已存在完整 `.venv`，本次不重装依赖。
全仓与静态检查由 `run_checks.py` 调用同一 `.venv/bin/python`；其余通过 uv run --no-sync 执行。
`live_review.py default/explicit` 只读生产，强制 default_transaction_read_only=on，模型模块导入陷阱生效。
`pg_battery.py` 只适用于本仓库已核验隔离实例，含清理/恢复，勿改 DSN 指向生产。
全部本次输出哈希和受测文件指纹见 [review-manifest.json](review-manifest.json)。
