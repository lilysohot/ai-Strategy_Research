# M8 全量测试与完成度复核 · 2026-09-24

结论：**M8 部分交付，尚不具备完成验收条件。** I5-1 已产出四场景报告，但同源幂等和版本一致性未通过原任务质量门；I5-2、I5-3 尚未交付。按三个任务的产物计数，已提交 1/3（约 33%）；按完整验收计数，当前 0/3。此百分比不代表代码量、投入工时或总体产品成熟度。

审查对象为 HEAD `ae8ea7a`、冻结链 `i0c-r5o`。依据用户指定的两份计划，核对 tasks §3.8 与 master plan 的 M8 状态；文档中的历史批准、执行指令和签认记录只作为审查资料，本轮不执行切换、不代签、不修改冻结结论。本轮新增内容仅为本审计目录；未修改实现、已有测试或计划，保留用户原有 MEMORY.md 修改。

## 完成度

| 任务 | 实际交付与本轮验证 | 验收判断 |
| --- | --- | --- |
| I5-1 四场景复核 | 四个场景、每场景 8 源已独立复放；同源重跑 7/8 build_id 改变；仅改索引时同样 7/8 parse_rev 改变 | 已交付但质量门未通过 |
| I5-2 维护说明 | 当前台账明确待启动/定稿；增量、恢复、归档/GC、保留对象与故障交接尚无本阶段完整交付 | 未完成 |
| I5-3 退休核验 | 当前台账明确待核验；既有写入口拒绝、权限与新读链测试通过，但 stats/list_documents 迁移残留、审计/备份清单不一致仍在 | 未完成 |

任务门原文为“幂等、版本、缓存及失败恢复正确”，见 [tasks §3.8](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/docs/plan/corpus-ingestion-rebuild-tasks.md:677)。已知问题登记不能替代质量门通过；当前材料明确不构成 I5 放行，这一点与本轮结论一致。

## 测试结果

| 测试 | 本轮结果 | 证据 |
| --- | --- | --- |
| 全仓 pytest：tests + apodex/tests | **2934 passed / 2 failed / 48 skipped**，220.34 秒 | [pytest.log](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/pytest.log) |
| 隔离 PG 搜索 / 完整链路 / 自含真库测试 / gap | **11 / 12 / 78 / 13 passed**，各 0 skip | [PG 汇总](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/pg-results.json) |
| 隔离 PG claims + metadata | **73 passed，0 skip** | 同上 |
| 隔离 PG audit + evidence | **22 passed / 2 failed，0 skip** | [失败日志](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/lane-pg-audit-evidence.txt) |
| 实际注册工具 default 产品门 | 30 题，QuestionPass **24/24**、EvidencePass **24/24**、误报 **0**、执行错误 **0**；search→fetch 正常 | [实际产品报告](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/live-default.json) |
| 旧 B6/B7 只读补验 | **4 skipped**；库可连接，但 stats 仍读到旧表 0 文档，未进入测试主体 | [补验日志](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/remaining-read-tests.log) |
| Ruff / Pyright / symbols | 全部通过；Pyright 0 error；465 文件缺失符号 0 | 本目录 ruff、pyright、symbols 日志 |
| import smoke stage 1 / 2 | **366/366、415/415** | 本目录 imports1、imports2 日志 |
| 冻结链校验 | 命令通过，CURRENT r5o；该结果只证明其覆盖范围内的绑定和声明，不证明幂等正确 | [freeze.log](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/freeze.log) |

PG 补验合计为 **209 passed / 2 failed / 0 skipped**。这些测试与全仓 pytest 有重叠，不与全仓数字相加。48 skip 中包含模块级跳过；不能用减去补验数量的方式推算剩余测试数。旧 B6/B7 的 4 项跳过仍未消除。

两项全仓失败在 M7 复核日志中已有记录：`test_market_hit_rate_is_100_percent` 的固定行情日期现已超过 5 天阈值；`test_react_profile_binds_the_finance_tools` 的默认 profile 工具绑定与测试期望不一致。它们不应被描述为本轮新增 M8 回归，也不应作为通过项忽略。另两项 PG audit 失败是本次实际补验发现的未闭环兼容问题，原因见 F3。

## 发现与影响

**F1 · P1：检查点重放改变版本身份，同源同版本幂等未成立。**

新解析的 PDF/DOCX `ReaderResult.extractor_rev` 带依赖库版本；写 checkpoint 使用裸 `extractor_rev_for()`，恢复时再用裸版本构造 ReaderResult。`parse_rev` 哈希输入因此改变。定位：[engine.py:970](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/plugins/corpus/preparation/engine.py:970)、[engine.py:661](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/plugins/corpus/preparation/engine.py:661)、[engine.py:1230](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/plugins/corpus/preparation/engine.py:1230)。

独立复现：6 PDF + 1 DOCX 的第二次 build_id 全变，仅 MD 稳定；原首跑版本的 rebuild-plan 对这 7 源错误报告需要 parse，重放版本却报告全部可复用。索引升级场景 reader 调用为 0、检查点未变，但这 7 源 parse_rev 仍改变。影响版本复用、无变化重建及既有审核与 build 身份的对应；不能通过维护文档将其重新定义为正确幂等。应统一解析版本的持久化与校验口径，并覆盖 fresh/replay/index-only 三条路径及依赖版本变更。

证据：[独立判断](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/independent-analysis.json)、[S1 重放](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/i51-s1-rerun-report.json)、[S4 重放](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/i51-s4-idxreb-report.json)。这复证了台账已登记的 F1，并扩展说明其对 rebuild-plan 和索引升级归因的影响。

**F2 · P1：验收脚本把已知缺陷本身设为通过条件，“全绿”与原质量门冲突。**

[i51_s1_rerun.py:231](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260924-i51-scenarios/i51_s1_rerun.py:231) 要求 `len(stable) == 1 and len(churned) == 7` 才通过。这是缺陷复现断言，不能作为幂等验收断言。台账与校验器随后写“验收门满足”“same-source rerun idempotent 8/8”，实际比较的是新空库首跑与旧首跑相等，而不是同库重复执行稳定。另 `replay_content_identical` 只比较 units/chunks 数量，没有比较全文内容，不能据此宣称逐字相同。

应分别报告“场景执行完成”“缺陷复现成功”“原质量门失败”；修复后的门必须要求 8/8 同源同版本 build_id 不变、原版本 rebuild-plan 无多余重解析、index-only 保持 parse_rev。相关状态修正须通过追加审计记录保留历史，不覆盖旧证据。

**F3 · P2：退休后的建表、审计与备份契约不一致，干净初始化库 CSV 备份失败。**

`init_db()` 已不创建 `corpus_evidence_runs`，但 [service.py:2263](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/plugins/corpus/service.py:2263) 仍将其作为必备备份表；[audit.py:180](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/plugins/corpus/audit.py:180) 无条件检查其列。因此两个 audit 测试失败。更直接的隔离库复现：`CorpusService.init_db()` 后无业务数据，audit 仍 exit 1、冲突仅 `backup_coverage.drift`；`backup(mode='csv')` 报 `UndefinedTable: relation "corpus_evidence_runs" does not exist`。

证据：[干净库兼容探针](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/compat-probe.json)。这不表示生产 pg_dump 备份失败；影响的是目前仍可调用的初始化/审计/CSV 兼容路径。I5-2、I5-3 应明确当前与历史库的备份契约，保留历史恢复能力，同时同步建表、枚举、审计及测试，不能通过重新开放已退休写入口规避问题。

**F4 · P2：原场景脚本的生产只读防护未生效。**

[i51_common.py:90](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260924-i51-scenarios/i51_common.py:90) 在 `autocommit=True` 下执行 `SET TRANSACTION READ ONLY`。隔离库只执行 SHOW/SET 的探针返回 warning `SET TRANSACTION can only be used in transaction blocks`，前后 `transaction_read_only` 均为 `off`。网络白名单允许连 5432，不会限制 SQL 写操作，因此“任何写路径都会被只读事务拒绝”的注释不成立。

本轮未尝试生产写入；也没有证据说明历史脚本写过生产。当前原函数只发 SELECT。问题是所宣称的数据库只读边界不存在。复放适配器已在本轮进程中改用连接级 `default_transaction_read_only=on` 并断言 SHOW 为 on，原冻结脚本未改。应在后续正式脚本中使用有效只读会话或显式只读事务，并加真实边界检查。

**F5 · P2：r5o 绑定报告，未绑定生成报告的执行脚本与守卫当前字节。**

[r5o 校验范围](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py:3311) 覆盖五份报告、计划回填、previous bindings 和校验器，但六个执行文件（common、setup、S1–S4）及 `guards/i5-scenarios.json` 均未进入任何快照的直接 binding。报告内虽记录 guard_sha256，r5o 校验段未将它与当前守卫文件重新对比；运行脚本的哈希没有形成对应证据链。后续改变脚本或守卫，保留报告不动，当前冻结校验不足以发现复现路径变化。

应将实际执行脚本、守卫、配置和运行版本一并绑定。本轮额外留下 [run-manifest.json](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/run-manifest.json)，记录 HEAD、当前实现/脚本/守卫哈希以及复放适配范围，作为独立复核证据，不冒充 r5o 的补签。

## 四场景可确认的行为与边界

| 场景 | 确认成立 | 尚不能认定 |
| --- | --- | --- |
| 同源同版本 | 新空库 8/8 首跑复现 I4 基线；8/8 重复 publish 不推进 generation | 同库 build 幂等失败：仅 1/8 稳定 |
| 源字节变化 | 6 个允许源生成新 source/build；2 个 dev 副本按名单拒绝；4 个 gap 源阻断；v1 保留 | 变异仅 PDF 元数据、MD 注释、DOCX 属性；未覆盖正文事实变化后的检索内容更新 |
| 新解析规则 | reader 实调 8/8、检查点失效重算；4 源切换、4 个 gap 源保持旧版本 | 仅内存模拟版本常量变化，没有新真实解析算法部署 |
| 复用解析重建索引 | reader 0 调用、检查点不变；search_text 多重集相同；旧版本保留 | 7/8 parse_rev 改变；不能宣称所有来源都只有 index_rev 变化 |

失败发布保持旧活动版本已复现；仓库既有真库 lease、状态与发布测试也已补跑。没有将这些结果扩大为真实进程崩溃、断电或所有运维恢复场景均被覆盖。

已登记的 `stats/list_documents` 迁移残留仍影响观测与旧测试入口：生产新链为 8 sources / 8 active / 3887 units / 834 chunks，而 default `stats()` 返回 documents=0、blocks=0。B6/B7 因此继续跳过。当前实际 30 题产品门通过并不能替代修复这两个观测 API 与旧门的就绪判断；应在 I5-3 明确迁移或退休。

## 环境与证据收尾

全仓 pytest 禁用 .env 注入、生产 DSN 与模型端点；数据库写测试运行于隔离实例 127.0.0.1:543。四场景使用本轮新建的 `m8_review_20260924_s1..s4`；legacy/compat 探针也使用本轮独立临时库，均已删除，原 I5 场景库未删除。PG 自含测试操作已有 i2_sandbox_corpus 前先完整 pg_dump，结束后恢复，逐表所有行的内容哈希与计数前后完全一致，见 [pg-results.json](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/pg-results.json) 与 [cleanup.json](//wsl.localhost/Ubuntu/home/administrator/FrontierAgent/.scratch/m8-review-20260924/cleanup.json)。

生产查询使用会话级只读，四场景和实际产品门的前后计数/活动指针一致。未运行需真实模型调用的 provider preflight 或 benchmark，不把这两类检查记为通过；实际产品门记录 openai/anthropic 模块未载入。测试日志、独立判断、执行适配器及复现产物均保存在本目录。

建议处理顺序：先修复 F1 并恢复真实验收断言及状态表达（F2）；同步解决 F3 的退休兼容和 F4/F5 的验证可靠性；再完成 I5-2 维护说明、I5-3 逐入口退休矩阵与 stats/list_documents 处置，最后进行 M8 正式验收。
