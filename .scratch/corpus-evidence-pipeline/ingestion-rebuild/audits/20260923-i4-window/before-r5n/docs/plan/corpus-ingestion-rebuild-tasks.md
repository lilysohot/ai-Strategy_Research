# 语料入库重构：任务分解与执行清单 v1.1

| 项  | 内容                                                                                |
| -- | --------------------------------------------------------------------------------- |
| 状态 | 有效 · v1.1 执行分解；已补首批交付回溯入口，完成/放行以总台账为准，不代表架构/预算/清理已获批准                             |
| 日期 | 2026-09-15                                                                        |
| 上游 | [重构设计 v1.1](corpus-ingestion-rebuild-architecture.md)——交付与门的唯一依据                  |
| 关系 | 本文是 v1.1 §11 批次的执行分解，不新增门、不提前放行；进度真源仍为[统一执行计划](claims-market-closed-loop-plan.md) |
| 纪律 | 遵守 v1.1 §12.4：不虚构耗时/表数量；I0 产物可推翻本清单对应任务，届时修订本文而非另起平行计划                            |

v1.1 任务分解评审时只修订依赖与验收表达；此后工作区已出现守卫、盘点记录和候选资产，
不能再用“全部待执行”描述现状。保留原任务编号和依赖；表格排列表示建议执行顺序，
不保证编号递增，原评审修订映射见 §6。本次仅补状态回溯，不降低门、不自动推进运行。

## 0. 执行状态入口

**2026-09-24 M7 放行（U 具名签认入链 i0c-r5n）+ M8 启动（I5-1 验证范围批准）。**
U（xyl）2026-09-24 具名签认：**M7 放行**，放行三要件全部达成——①I4 窗口执行完毕
（I4-3→I4-6→I4-2→I4-7→I4-4→I4-5 全绿；reset 阶段 1 七表 + 阶段 2 六表 TRUNCATE 五门全过，
旧九表归零、保留序列与见证不变）；②独立复核闭环（[m7-review-20260924](../../.scratch/m7-review-20260924/report.md)
六项整改 + [m7-rereview-20260924](../../.scratch/m7-rereview-20260924/report.md) F1–F3 修复验证
[m7-finalize-20260924](../../.scratch/m7-finalize-20260924/)）；③U 具名签认
（[signoff-record-m7](../../.scratch/m7-rereview-20260924/signoff-record-m7.md)，r5c 先例：具名签认入链）。
随签认登记已知项：stats/list_documents 迁移残留观察项（旧表查询输出 0/0，归 I5-3 处置）、
全仓 2 既有 failed 与 49 skip 口径同复核基线、abstain=on 正例拒检为 M6 签认已知限制。
同日 U 裁定：**开启 M8（I5 增量与运维）**，I5-1 验证范围批准为**全四场景 × 全部 8 个活动源**
（同源同版本重跑、源变化、新规则 build、复用解析重建索引；源变化/新规则/复用解析在隔离
环境执行，不触碰生产活动来源），与 I2/I3 同场景结果对照。本条为放行与启动记录，
I5-1 执行结果另行回填。

**2026-09-24 M7 二次复核遗留项已修复并冻结（[m7-rereview-20260924](../../.scratch/m7-rereview-20260924/report.md) F1–F3；[m7-finalize-20260924](../../.scratch/m7-finalize-20260924/)；`i0c-r5k`）。**
**F1**：`save_evidence_run()` 对已批准停用的 `public.corpus_evidence_runs` 恒定抛出 `RetiredEvidenceWriteError`，不连库、不建表、不写入；`extract_claims()` 默认 `persist=False`，而 `persist=True` 也只能得到同一 fail-closed 拒绝。运行验收 [f1-retired-evidence-writer-verification.json](../../.scratch/m7-finalize-20260924/f1-retired-evidence-writer-verification.json) 记录零 `psycopg.connect` 调用，回归覆盖同步更新。**F2**：独立一次性库恢复后，归档 crosswalk 的 290 条可解析历史正文与 `public.blocks.text` 全量逐字一致，manifest 25/25 且库已销毁；详见 [g3b-isolated-restore-body-verification.json](../../.scratch/m7-finalize-20260924/g3b-isolated-restore-body-verification.json)。**F3**：`r5k` 将上述脚本/实际报告与本次审查报告绑定到当前代码和测试哈希，同时将早期 M7 电池及默认产品门明确标注为复用历史基线，消除其旧 chain-head 声明与本次执行版本混淆。本条关闭二次复核提出的 F1–F3，不构成 I5 放行。

**2026-09-24 M7 复核修复执行完成（复核 [m7-review-20260924](../../.scratch/m7-review-20260924/report.md) 六项全数落实；修复工作区 [m7-fix-20260924](../../.scratch/m7-fix-20260924/)；r5j 冻结修订随本条入链）。**
U 批准「全部修复，P1 优先」。**G1**：`.env` 交付 `CORPUS_TARGET_DB=postgres`（`.env.example` 同步说明；缺省 fail-closed 语义不变），default 模式验收 30 题 QuestionPass 24/24、EvidencePass 24/24、0 误报、search/fetch 往返正常、counts 前后一致。**S1**：目标库解析去 import 缓存——service/read_pg/search_pg/cross_boundary/cli 全部改为构造/调用时动态解析（显式 `CORPUS_TARGET_DB` 优先；先 import 后加载 .env 的入口恢复生效）。**G2**：旧 ingest 写入口 fail-closed 恒定拒绝（`RetiredIngestError`，不建立任何数据库连接、失败路径同样不写旧表；CLI `ingest` 子命令结构化拒绝 `retired_ingest_entry` exit 2）；新增回归 [tests/test_corpus_ingest_retired.py](../../tests/test_corpus_ingest_retired.py) 断言零 psycopg 连接。**S2**：`search()` 统一委托 `search_with_coverage`（r5e 产品门 24/24 验收口径），删除 `_selected_chunk_hits` 双入口命中分叉；[test_corpus_consumers_pg.py](../../tests/test_corpus_consumers_pg.py) 选择策略断言按统一口径更新（6 源×2 块 → top_k 5 源 × 每源 1 锚点 = 5）。**测试重验**：冻结 PG 电池复放全绿（m4-plain/i1 各 320 passed+7 skip、dev-lane 9、search-live 11、fullchain 12、hermetic 78 零跳、d2d6 73 零跳、恢复确定性+active 指针严格匹配）；全仓 pytest 复核口径 **2931 passed / 2 既有 failed（market_golden stale-quote、research_discipline，与复核基线同）/ 49 skipped**。**lane 契约变化（记录）**：G1 后 `.env` 携带 `CORPUS_TARGET_DB=postgres`，任何 import 到 `frontier_agent.infra.config` 的 lane 进程都会经 `load_dotenv(override=False)` 注入该值——I2 沙箱 lane env 须预置 `CORPUS_TARGET_DB=''` 中和（复放 runner [replay_battery.py](../../.scratch/m7-fix-20260924/replay_battery.py) 已落实，与复核时解析态一致）。**G3**（隔离恢复补验：权限对账/旧引用回环/实测耗时）另行执行；**G4** 窗口关键证据（窗口报告、i4-reset/i4-cutover 双 manifest、I4-7/I4-4/I4-5/I4-6/i4c 阶段报告与执行脚本）随 r5j 首次入链。本条为修复事实回填，不构成 I5 放行；i0c-r5j 冻结修订落章后链头推进。

**2026-09-24 I4 窗口 reset 阶段 2 执行完成（暂缓解除后执行；窗口至此全部执行完毕）。**
U 复核[窗口报告](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/report.md)后批准执行（解除同日「暂缓，先出窗口报告」裁决；暂缓期间现状保留 blocks 1101 / documents 89）。[i4c_reset_phase2.py](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i4c_reset_phase2.py) 守卫 lane 五门全过：门 2 对照件三件 sha 命中（crosswalk 307 行实测）；门 3 前置行数精确匹配（blocks 1101 / documents 89 / 四引用表 0，漂移即停未触发）+ 语句/对象/行数三对账；门 4 单事务逐字执行 manifest phases[2] 单语句（六表同语句、无 CASCADE）；门 5 后置六表全 0，保留序列 docs_id_seq/chinese_docs_id_seq 与见证 docs/chinese_docs 3/3 不变。write-once 报告 [i4c-reset-phase2-report.json](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/i4c-reset-phase2-report.json)（sha `11762f4e…`）。本条为窗口收尾事实回填，不构成 M7 放行；I5 任务另行核定。r5i 冻结修订随本条入链。

**2026-09-24 I4 停写窗口执行完成（I4-3→I4-6→I4-2→I4-7→I4-4→I4-5 全绿；reset 阶段 2 经 U 复核裁决暂缓，另行安排）。**
停写截止点 LSN `0/4FB2BD00`（I4-3 门禁 8/8）；I4-6 最终备份恢复验证 11/11、扩展 4/4；
I4-2 双 manifest 锁定（U 一次具名批准九表两阶段 + 追认 r5g 目标适配），
r5g 入链验证器 exit 0。I4-7 migrate 九表一次受控回滚（首跑验证器漏数 9 个 pkey
支撑索引 → 逐字 DROP SCHEMA corpus CASCADE 回滚，事件落章）后重跑绿色（19 索引、
结构/zhcfg 与沙箱逐一等价、行数零漂移）；reset 阶段 1 七表逐字执行（前置
290/1318/57/1/11 精确匹配、3 owned 序列归零、见证表不变）。I4-4 生产重建
8/8 built/published/active、blocked 0，build_id 与 I3-7 沙箱基线逐一相同
（chunks 834/units 3887）。I4-5 真注册 corpus_search/corpus_fetch 生产往返通过
（cv2 句柄定位、逐字 fetch、spans 复算 text、伪造/旧句柄结构化拒绝、恢复同文），
零模型断言、无双写实测、旧写入口停用记录四条；偏差=无守卫子进程 lane
（I3-7 先例 + 补偿控制），随 r5h 冻结修订登记。reset 阶段 2（blocks/documents
单语句 TRUNCATE）U 裁决「暂缓，先出窗口报告」：现状保留 blocks 1101/documents 89，
前置对照件已导出（旧引用定位 crosswalk 307 对 + doc_id→source 映射 89 行），
执行时回退只靠已验证备份。本条为窗口执行事实回填，不构成 M7 放行；I5 增量
任务另行核定。详见
[I4 窗口报告](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window/report.md)。

**2026-09-23 I4-1 窗口前准备/演练 A 侧完成（M7 已启动；停写窗口批准待 U，未进入 I4-3）。**
获准分支确认 `migrate_then_reset_limited`（i0c_1_branch 冻结裁决）；冻结链验证通过
（链头 **i0c-r5f**，r5e 产品门结论保留）；新建 `i4-inventory` 阶段守卫（仅 5432 只读、
零模型、5 份留出禁读）合成自检 **24/24**；生产只读盘点**零漂移**——corpus schema 确认
不存在（窗口内 DDL 纪律）、重置候选九表行数与 I0A-1/设计复核逐一相等（claims 1318、
claim_block_runs 290、corpus_evidence_runs 57、ingest_runs 11、ingest_failures 1 等）、
零客户端写入者/复制槽/计划任务、dev-manifest 73 源 68/68 哈希匹配（0 变更 0 缺失，
5 份留出仅 stat）；预演备份（**REHEARSAL_ONLY_NOT_FINAL**，WAL 括号 0/4FAFA088→
0/4FB2BA40，dump ~52s，原文 tar 191 文件+5 留出显式排除）sha256 9/9 完整性通过。
回退步骤、窗口操作范围草案与待 U 决定项（窗口时间、写入者区分手段 R1、I4-6 恢复
目标、corpus_app 角色/归档根）见
[I4-1 准备报告](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i41-window-prep/report.md)
与[机读摘要](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i41-window-prep/i41-prep-summary.json)。
本条不构成窗口批准或 M7 放行；defer 未选择，批准缺失不进 I4-3。

**2026-09-23 M6 产品门整改（i0c-r5e）：检索召回、证据完整性与负例拒答已通过。**
沿用冻结 30 题、金标、评分器、95% 阈值、原始题干和 `limit=10`，真实注册
`corpus_search` → `corpus_fetch` 链路为 QuestionPass **24/24**、EvidencePass
**24/24**、6 个无答案负例 **0 误报**、工具失败 0。修复内容包括：自然问题实质词元
OR 候选、来源标题召回与每来源候选上限、同页有界 band 合并、按权威原文序暴露
`context_locators`、cell 对 `unit_id` 的 span 级校验，以及仅对明确语料可用性询问启用的
默认拒答门。金标、评分器、阈值和活动语料均未为结果改写；零模型调用。
真库回归 12 passed，重建后 8/8 published+active；全仓 **2961 passed / 2 个既有失败 /
17 skipped**，CI 范围 ruff、pyright、两阶段 import smoke、symbol closure 均通过。
本次 r5e 取代 r5d 的“产品门未通过”当前结论；r5d 及更早记录保留为历史失败证据。
详见[整改报告](../../.scratch/m6-retrieval-fix-20260923/report.md)和
[机器可读结果](../../.scratch/m6-retrieval-fix-20260923/product-summary.json)。

**2026-09-23 M6 复核整改（i0c-r5d）：三项实现缺陷已修复，当前产品验收未通过。**
补充证据单元已强制校验内容哈希；正式 `corpus_fetch` 与 band 读取在同一只读快照内使用
共同的上下文装配，原先缺失的 4 个证据目标均已取回；新版观测采集器逐题调用真实注册
工具，不读取正负例标签来决定结果。全仓 2912 passed / 2 既有失败 / 49 skipped，隔离 PG
电池全部通过。按未改动的评分器、金标和 95% 门槛，默认原题干、limit=10、abstain=off
为 QP/EP **0/24**；统一显式 OR、limit=20 的诊断为 QP **22/24**、EP **13/24**、
负例误报 **6/6**；abstain=on 的既有正例误拒限制仍在。r5d 冻结修复实现和失败证据，
**不构成新的 M6 放行，不据历史 24/24 推进 I4**。下文 r5c 签认及实验报告保留为历史记录。
详见[修复报告](../../.scratch/m6-repair-20260923/report.md)和
[真实产品评测](../../.scratch/m6-repair-20260923/product-evaluation-summary.json)。

2026-09-23 I3-7 最终重验已执行（零模型、隔离 PG、留出零读取；对 I3-6 冻结版本 **i0c-r4z**）：
重建/索引 teardown+apply+播种+build/check/publish **8/8 published+active**，index/chunk/parse/clean
revs 与冻结报告逐一复现（index-4-zhcfg-2）；评分/取证/负例电池 **14/14 门全绿**——
QuestionPass/EvidencePass 24/24、三类 DocRecall=1、关键题 22/22、评分层 FP=0/伪引用=0、
b5 基线零回退、prune on 非劣化、产品层 abstain=on 负例 6/6（冻结口径）、authority 取证回环全过；
测试电池 **9 门全绿**——m4-plain/i1 各 320、dev-lane 9、search-live 11、fullchain 12 项（照原样）、
hermetic 74、d2d6 73（偏差 lane），恢复后 build_id 确定性复现 + active 指针严格等于 8 源；
legacy 非回归与 I3-5 同口径全过（财务 47+公式 7+负控 PASS、客户表 12/12、正文 2/2、
宏观 0/3 保留单列、golden 19/19、契约门 PASS）。偏差登记：①D2/D6 双重偏差（守卫对
CORPUS_DSN fail-closed 投毒 → 无守卫 lane，零模型由假实现保证；legacy 形态前提 = 无 corpus
schema 第三库 i2_d2d6_corpus，恢复前 DROP）；②守卫 Popen 注入（父 runner 不装守卫、
恢复经 --restore 独立子进程）——均为冻结 fail-closed 行为 + 运行纪律，非产品缺陷。
pending（非 I3-7 门）：abstain=on 下 24/24 正例被拒检（S1「正例不误拒」未获证）待 U 裁决。
静态门 ruff（CI 范围）/import_smoke stage1/pyright 0 err。证据：
[20260923-i37-final-reverify](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/README.md)。
全部结果与冻结版本一致；M6 仍不放行（须独立复核 + U 具名签认）。

2026-09-23 **M6 独立复核与 U 具名签认已完成，M6 放行**。独立复核
（[20260923-m6-independent-review](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-m6-independent-review/review.md)，
全新探针不 import I3-7 脚本，零模型、沙箱只读、留出零读取）：三门验证器 exit 0；r5b 绑定
13 项对账 + 冻结 manifest 62 资产**零漂移**（chain_manifest 冻结时点字节在 git 8ec0cb6 精确
复得，当前 63 快照=冻结面前缀相等+仅追加 r5a/r5b——追加式演进实证非篡改）；独立重评分
30 题逐字段对账**零差异**（QP/EP 24/24、三类 DocRecall=1、FP=0/伪引用=0、b5 零回退、
prune 改善名单一致、abstain 负例 6/6、正例拒检 24/24 独立复现、authority 自选样本回环过）；
DB 直读核验 8 源 active、revs 冻结公式逐 build 重算全对、独立 search→fetch 回环 3/3、
i2_d2d6_corpus 确已 DROP；纪律审计零模型/5432 零触碰/留出零读取全过；静态门复跑
ruff/import_smoke(365/365)/pyright 0 err；README/tasks.md 宣称与产物逐项一致。
**U（xyl）2026-09-23 具名签认：M6 放行**；abstain=on 下 24/24 正例拒检裁决为
**接受为已知限制**（关闭 S1「正例不误拒」设计宣称并登记，负例冻结口径不受影响，
评分层 24/24 不受影响；若日后需恢复该宣称，另立整改任务走版本冻结 + 重验）。
签认记录 signoff-record-m6.{md,json}，签认入链 **i0c-r5c**（r30 先例：具名签认入链）。
M6 后变更须按 I4 前置纪律另立版本冻结与授权。

2026-09-23 I3-6 最终冻结已执行（零模型、零写库、留出零读取）：冻结版本=i0c 链头
**i0c-r4z**（有效绑定以 validate_i0c_freeze.py 核验为准）；不可变最终 manifest
[i3-final-freeze-manifest.json](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-final-freeze-manifest.json)
落 §12.1 拟交付位置，显式哈希 28 实现+4 规则+5 预期/policy+9 守卫+4 基础设施+12 测试锚点
（scoring.py f61573d7 未漂移），运行时配置（REV 常量 + 开关默认值 + M6 负例评测口径
abstain=on）与校准收口声明（三类 DocRecall=100%、QuestionPass/EvidencePass 24/24、
关键题 22/22、FP=0，b5 盘点）入 manifest；核定需重验的 M4/M5 门九组交 I3-7；
待定项核定：prose 重抽取（预算）、真实答案语义测试（授权）、留出 10 格（守卫保护）
均为另立授权型 not_run，**无冻结必需待定项**。证据：
[20260923-i36-final-freeze](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i36-final-freeze/README.md)。
本 manifest 仅冻结版本，M6 不在本轮放行（须 I3-7 重验 + 独立复核 + U 具名签认）。

2026-09-23 I3-5 开发非回归已执行（零模型、原库零写入、留出零读取）：
财务 47/47（茅台 32+广立微 15，tolerance=0）+ 公式 7/7 + 高盛负控 PASS；客户表 12/12
（冻结 run 复验，原文留出不读）；正文冻结 2 例 2/2（冻结 run 复验；重抽取须另立预算
授权 not_run）；宏观 0/3 失败基线保留单列；旧检索 golden **19/19**（O6 按 r27 排除，
旧库 5432 legacy 读链只读重评，无 skip）；零模型审批/投影契约门 32 passed。
guosen_maotai 10 格 held_out_not_run_in_dev（I3-7 口径）。偏差登记：I2-7 后冻结契约
（verify_claims_entry 写原库）不可原样执行，改走 `build_evidence_run` 库级等价路径
（同冻结 gold/容差，任何库零写入）。结果 write-once：
[20260923-i35-legacy-nonregress](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i35-legacy-nonregress/README.md)。
I3-5 不是最终版本放行；I3-6/I3-7 另做。

2026-09-20 校准进展（i0c-r39）：在 r38 已完成 I3-1 后，按预先固定两轮方案实跑
冻结30题。整句基线全无命中；问题词元 OR 候选三类 DocRecall/QuestionPass 均100%，
EvidencePass 分别1/8、2/8、2/8，六个无答案负例全部误报，**I3-3 仍未通过**。
54条缺失证据中34条尚未逐字匹配 kept 页文本、14条未进选中块、6条缺所需坐标。
按两轮停止条件收口，候选未部署、gold/阈值未改；详见
[I3-3 首轮开发校准](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/README.md)。

2026-09-20 根因取证与评分口径修复（只读；不改金标/来源/索引/阈值）：
对 54 条缺失证据做空白规约 + 全文 LCS 取证，重分类为——20 条字节保留（14 块选择 + 6 坐标）、
14 条空白表征差异、2 条被清洗剔除、18 条金标改写/重建表述（全文任意处都不逐字出现）。
评分器 `EvidenceTarget.matches` 引文包含判定改为**空白规约后的码位包含**（与金标本意 `exact()` 一致，
非空白差异仍不命中）。对该轮原 OR 观测**只读重打分**：EvidencePass company 1/8、industry 2/8、
**macro 2/8→5/8**，命中目标 +7。读取器对表格单元无结构化 cell 网格（`cells=[]`/`element=null`），
row:/col: 表头标签按「宁缺坐标不贴错」置为结构不可映射，未接线脆弱解析器。剩余 20 条（18 改写重建 +
2 清洗剔除）在检索/匹配层**不可达**，如实登记、**不改金标**。负例误报/伪造引用 6 条不受本修复影响
（属 OR 过宽的负例策略，不在本次证据修复范围）。**I3-3 仍未通过，M6 不放行**。详见
[I3-3 根因取证与修复收口](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/i33-rootcause.md)。

2026-09-20 ingestion 侧修复可行性预检（只读；按「先只读复现验证再重摄入」）：
对 guide 提出的 FIX-1「x 中心一维聚类分栏」做行级只读重排量测——54 条中 34 条
`exact_quote_not_in_kept_page_text`，单栏流 fresh 行级读 hit 12 / miss 22，加聚类后
hit 14 / miss 20（净恢复 ~2，company-001 第 1 页 x 中心 24→575 连续、全局 18% 阈值
分不出浮动侧栏，`相关研究报告` 仍夹在句内）。**guide「32 条靠摄入侧修复直接转绿」
在该批次页面布局下不成立，34→≤2 前提被证伪**。据此**回退**已试落的 `_split_columns`
侧栏改动与 `reader-pdf-3` 版本号（`git diff` 为空，基线未动），**不 bump / 不重摄入**，
代码与冻结基线一致。只有读证据与结论留档：详见
[I3-3 行级重排预检](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/remediation-line-repro.md)。
**I3-3 仍未通过，M6 不放行**；后续方向待 U 裁决（更细区域隔离 FIX-3，或接受
「摄入侧部分有效 + 匹配侧等价 + 人工诊断」分级账）。

2026-09-20 区域隔离 FIX-3 只读预检（按 U 选区「先验证 FIX-3 再定」）：
行级策略对比 34 条连续命中——before 12/22、x中心聚类 14/20、**x0 左边缘聚类
17/17**、x0+页眉/页脚带隔离仍 17/17。x0 是侧栏分离的正确信号（右栏 x0≈394–524 vs
正文 x0≈41），但最优区域隔离最多把 miss 22→17，**net 仅 ~5 条**；页眉/页脚带零增益，
且 17 条非连续在不动金标/评分器下**本质上不可由阅读顺序修复**（重摄入至多 miss 22→17，
距 guide 的 34→≤2 差 15 条）。**据此判定不值得 bump + 全量重摄入**，回归当前基线。
详见 [I3-3 区域隔离预检](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/remediation-region-repro.md)。
**I3-3 仍未通过，M6 不放行**；结论：接受「摄入侧部分有效 + 匹配侧等价(已合入) +
不可达分级账」收口，待 U 确认是否终结本证据修复簇并转入有界召回/负例策略。

2026-09-20 阅读序改判与实施（已改代码 + 内存回归验证；未写 PG / 未重摄入）：
上述「17 上限、不值得重摄入」的判定被**推翻**——根因不是侧栏/页眉分区，而是 reader 用
全局 `(y,x)` 行重排（`pdf_reader.L405` 发射排序 + `_merge_lines` 内二次 `(y,x)` 排序）打散了
pymupdf 原生块的跨块内聚性。两种独立机制（`blockraw` dict 块序 / `get_text("text")` 阅读序）
在整页连续流上 34 条**全部命中**。据此落地核心修复：`READER_PDF_REV`→`reader-pdf-3`，
发射与段装配改为**保留 pymupdf 原生块→行序**，不再全局几何重排（不改金标/评分器/locator/
单元集合/判据）。真实 reader 全链路只读复算：before 12 → reader-pdf-3 **23 / 11**，
再关闭 `_split_columns` 强制左→右重排可达 **28 / 6**（`_split_columns` 在本批页面为负收益，
因原生序已正确；但影响真实双栏文档，语义风险大，列为后续杠杆未并入）。回归
`pytest tests/test_corpus_*.py` **697 passed / 12 skipped / 0 failed**，ruff/pyright 干净。
剩余 ~6 条（industry-003 a-3 p10、industry-008 a-2 p10、macro-001 a-3 p3、macro-002 e4 p1、
macro-003 a-2/a-4 p1）多属**表格内文本改组**（表结构化重建类），非阅读序类。详见
[I3-3 阅读序改判与落地](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/remediation-coord-deep.md)。
**I3-3 仍未通过，M6 不放行**（须重摄入取 PG kept 文本准数 + 冻结链重绑 + 单一回归才能复核）。

2026-09-20 最新（i0c-r38）：光力 p7 沿用 xyl 已有签认，经源哈希与真实区域框校验后
已发布。批准开发集 **8/8** 发布，company **3/3**、industry **3/3**、macro **2/2**；
13 处缺口均 acknowledged，仍保留原 blocking 默认分级及 scoped coverage。
真实检索/逐字取证全过、审计冲突 0。**I3-1 已完成，可进入 I3-3/4/5 开发阶段**；
M6 仍待最终冻结与重验。见[区域判级收口](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-region-review/README.md)。

2026-09-20 最新（i0c-r37）：xyl 四份具名核验内容已提交并完整保留。现有门接受其中三份、
12 处缺口，均已登记及发布；原批准 8 份现发布 **7/8**，company **2/3**、industry **3/3**、
macro **2/2**，每类≥2 与 PDF/DOCX/MD 格式门均通过，真实 search/fetch/verify 无拒绝、
取证全通过、审计冲突 0。缺口台账不删，coverage 仍 scoped。光力 p7 的人签同页区域说明
已收到并与原 PDF 坐标核对，但现有门只识别页级不相交，仍保留 1 处 blocking；这是程序
精度限制，不是待用户补签。I3-1 数量/格式/E2E 门已过，M6 与其余 I3 任务未据此放行。
见[本轮签署采纳与发布记录](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-signed-release/README.md)。

2026-09-20：I3-1 人工判级机制按用户选择落地（i0c-r36）：新增具名凭证、发布门重验与
不相交反例，默认分级表和守卫不变。4 份受阻 build 的 13 处缺口已生成未签署模板；
真实缺口尚未人工签署，I3-1 / M6 仍未通过。光力 p7 与所需证据 p7 同页时继续阻断。
详见[人工判级实施与签署说明](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-human-gap-review/README.md)。

**查看最新状态：[总计划 · I0 细任务执行台账](claims-market-closed-loop-plan.md#i0-execution-ledger)。**
截至 2026-09-15 深夜的回溯摘要：I0G-1 守卫已按审计修复并重验（反例 run3 12/12、v2 自检 24/24），
U 已放行；I0A-1 复核通过；I0A-2 73 条终态回填（U 裁决）并完成冻结时点重测（89=71+18 零增删改）；
I0A-3 政策 U 批准冻结（v1-20260915）；I0A-4 人工标注完成、冻结门生成不可变金标三件套
（source 23 / query 30）；I0A-5 联合冻结完成（M1 快照 71aa61af…）；I0B-1 备份 + I0B-2 隔离恢复
验证通过（M2 证据齐备）。**M1 达成**：I0A-1～5 交付齐、守卫有效、资产按阶段冻结；I1-8 守卫
绑定与拒绝路径验证通过（i1.json 按 I0A-2 终态回填 6 开发材料 + 3 留出隔离）；I1-1 完成
（contract 数据模型 + 内存 Adapter，17 测试 / Ruff / Pyright 通过）；I1-2 完成（readers 三格式
Adapter，14 测试含空页/多栏/表格/重复标题/短 MD 反例与 6 开发材料 smoke / Ruff / Pyright /
i1 守卫下通过）；I1-3 完成（clean 保真清洗 + 区域台账，13 测试含映射/保真/噪声反例与 6 开发
材料 smoke / Ruff / Pyright / i1 守卫下通过）；I1-4 完成（chunk 结构优先切块，14 测试含句界零丢失/超长复核/跨页分组/
问答关联反例与 6 开发材料 smoke / Ruff / Pyright / i1 守卫下通过）；I1-5 完成（admission 准入
判定，52 测试表驱动 gold 含十问十答 mixed 不阻断、unreadable≠absent、未决不能发布与 6 开发
材料 smoke / Ruff / Pyright / i1 守卫下通过）；I1 复核修复完成（2026-09-16 按[时点复核报告](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1/review.md)
修复 I1-1～I1-5 缺陷 F1—F7，15 反例转正为回归测试：探针 20 passed / corpus 125 passed / 守卫下 144 passed /
Pyright / Ruff / import\_smoke 352/352 全绿）；I1-6 完成（source 接收/源变化检查/内容寻址归档，
17 测试含登记失败恢复、篡改拒覆盖、接收中变化反例与 6 开发材料 smoke / Ruff / Pyright / i1 守卫下
通过）；I1-7 完成（engine 全链编排：plan→execute→publish 收敛、§4.1 rev 绑定、§8.1 job 短路幂等/
FAILED 恢复、未决不发布、排除撤下活动版本、解析读归档副本，13 测试 / Ruff / Pyright / i1 守卫下
155+174 passed / import\_smoke 354/354）；I1 二次复核修复完成（2026-09-16 按[二次复核报告](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1-retest/review.md)
修复 R1—R5 边界缺口：publish 核对 build 决定与幂等重试、fencing 四查门+publish 所有权门+可注入时钟、
PDF 小图/DOCX 表格内图片记账、context\_refs 引用式关联、政策版本绑定；边界反例 9 failed→11 passed、
探针 20 passed、corpus 174 passed、行为变更 REV 升版 \*-2；整改验收与 M4 放行待下次复核确认——已由 2026-09-16 [M4 复核](claims-market-closed-loop-plan.md#m4-review-release) 关闭）；
I1-9 完成（合成夹具三件套 [synthetic-only](../../tests/fixtures/corpus_preparation/)：MD/DOCX 嵌套表+cell 图/PDF 4 页缺口记账 +
[夹具收口测试](../../tests/test_corpus_preparation_fixtures.py) 15 passed + 阶段冻结
[freezes/i1-r1.json](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i1-r1.json)
（write-once，父快照 i0a5，§12.2 九族覆盖映射，M4 不宣告）+ freeze-manifest 索引 + guard selfcheck
24/24；i1 守卫 env -i 九业务文件 170 passed + 探针 20 + 边界 11，普通环境 guard 19 passed /
Pyright / Ruff / import\_smoke 354/354；守卫 tests/fixtures 放行免重绑 i1.json）；
~~I1 全部任务（I1-1～I1-9）完成，I2 可启动~~（超前宣告，2026-09-16 联合复核否定：
C1—C7 未关闭、链路探针 9 failed，见总台账纠正条目）；I1-9 partial，M4 blocked；
I2 not\_ready（须 M3+M4）；I0-C 未启动，M3—M8 未通过。
I1 完整 review 修复轮完成（2026-09-16 按 [full-review](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1-full-review/review.md)

- [i1-9-retest](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1-9-retest/review.md)
  两份报告整改 C1—C7/N1—N4：发布所有权+质量/阶段门 fail-closed、scope 落 clean 层、登记失败终止、
  排除快路径、归档 symlink 核验、检查点保真与恢复跳算、标题独立成块+超长复核、EngineCancelled
  生命周期、PDF 缺口负例/MD generation 正例、反例三件套+发布门回归 10 项、探针协议升级断言不变；
  复验：chain 11+验收 3 = 14 passed（合并旧探针 45 passed）、业务 180、旧探针 31、guard 19、
  pyright 0 / ruff / import\_smoke 354/354，[证据](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-i1-remediation/verification-matrix.txt)；
  冻结链在随后复测中按可信副本修复：历史 [i1-r1.json](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i1-r1.json)
  恢复至索引锚定的原始字节（`d474…`）；[i1-r2.json](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i1-r2.json)
  不改写但仅保留为父锚点错误的审计记录；当前候选为
  [i1-r3.json](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i1-r3.json)，直接父快照为恢复后的 r1，
  由 [validate\_i1\_freeze.py](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i1_freeze.py)
  核验索引、父哈希及全部绑定）；**M4 已独立复核放行并经 U 签认（2026-09-16，见总台账** **[M4 复核](claims-market-closed-loop-plan.md#m4-review-release)）**。I0-C 完成（2026-09-17，[design-review](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/design-review.json) 签认版 + [i0c-r1 冻结](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i0c-r1.json)，见总台账 [I0-C 设计复核](claims-market-closed-loop-plan.md#i0c-design-review)）：九表布局/参数/消费者矩阵冻结 + I1 协议精化 i1-r4，**M3 达成，I2 前置（M3+M4）全部满足可启动**；删除类操作仍零执行。
  I2-2 独立复核整改完成（2026-09-17，见总台账 [I2-2 回溯复核整改](claims-market-closed-loop-plan.md#i2-2-independent-remediation)）：PG Adapter 安全清理门、scope 发布校验、锁后租约时钟、JSONB 幂等、job checkpoint 契约与冻结有效绑定核验均已修复；新增 [i0c-r3](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i0c-r3.json) 作为当前修订。M5 仍 `not_declared`，后续 I2-3～I2-8 与真库并发/消费者接线验收未完成。
  I2-3 完成（2026-09-17，见总台账 [I2-3 FTS 读侧](claims-market-closed-loop-plan.md#i2-3)）：INDEX_REV_V2 定稿进 build_id、search\_text % 归一化、读侧活动范围先筛后排名；DDL r3 重演 26 项全 ok，真库 18 passed 不 skip。
  I2-7 完成（2026-09-17，见总台账 [I2-7 消费者接线（一）](claims-market-closed-loop-plan.md#i2-7)）：CorpusService 写路径代理 preparation Module（ingest\_path/ingest\_dir 唯一走 plan→execute→publish，fail-closed 拒绝非演练目标）、ingest.py 全模块退休、claims\_v2 影子抽取路线退役（共享规则拆至 claims\_detail.py 保留）、derive\_published 禁 doc\_id 前缀派生（唯一日期落点=report\_publication）；新建 i2-verify 守卫阶段（selfcheck 24/24），三门禁真库 26 passed / 4 skipped（skip 均旧直连投毒预期），定向回归 144 passed。M5 仍 `not_declared`，待执行：I2-6（I2-8/I2-4 已完成，见下条 I2-8 + I2-4 条目）。
  I2-8 + I2-4 完成（2026-09-18，见总台账 [I2-8 + I2-4](claims-market-closed-loop-plan.md#i2-8-i2-4)）：
  **I2-8 消费者接线（二）**——新增 [read\_pg.py](../../plugins/corpus/preparation/read_pg.py) 作为读侧唯一
  权威入口（句柄 `cv2:<build_id>` + `chunk:<chunk_id>`；跨发布取回原 build；旧句柄/跨 build/坏哈希
  `archive_required` 拒绝；来源撤销拒绝；§7.3 coverage 三轴），[service.py](../../plugins/corpus/service.py)
  加读链判定 `CORPUS_READ_CHAIN` 并把 search/fetch/document\_text/source\_resolver/coverage 迁到新链，
  [corpus\_search](../../plugins/tools/corpus_search.py)/[corpus\_fetch](../../plugins/tools/corpus_fetch.py)
  返回版本句柄与 coverage 对象（空命中改述"当前已发布范围无匹配"，不自动转 absent），
  [audit.py](../../plugins/corpus/audit.py) 新增 `audit_corpus_chain` 新链完整性审计并纳入 run\_audit
  冲突；golden 依 design-review 归 I3-5，本轮登记不迁移。**I2-4 CLI 六职责**——新增
  [cli.py](../../plugins/corpus/cli.py)：plan/build/check/publish/status/rebuild-plan，一律复用正式编排
  （`check_build_publishable`、`current_revs` 为复用的公开门，不在 CLI 内复制规则）；`publish` 必填
  `--operator` 且操作者与 generation 落入 PUBLISHED job 检查点；退出码 0/2/3/4/5 显式区分。
  证据：真库（i2-verify 守卫 env）**50 passed 零 skip**、普通环境语料全量 **424 passed / 1 skipped**、
  i1 守卫 env **188 passed**、ruff（CI 范围）/pyright/import\_smoke **358/358** 全绿；
  冻结 [i0c-r9](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i0c-r9.json)。
  I2-5 完成（2026-09-17，见总台账 [I2-5 publication\_pg](claims-market-closed-loop-plan.md#i2-5)）：新增
  [publication\_pg 真库测试族](../../tests/test_corpus_preparation_publication_pg.py)（13 用例：双 worker
  并发 acquire/register/过期接管、真实停顿越过 TTL 的接管、陈旧 token 迟到提交五路径、提交丢响应
  幂等、取消与接管、max\_attempts 三条路径边界、并发发布与 retire 竞态、失败阶段恢复、index\_rev
  升级重建与读侧切换）；真库竞态暴露并修复四处 store 缺陷——J1 job 逻辑键 advisory 锁（并发 register/
  接管时行不存在，行锁拦不住并发 INSERT，修复前把 psycopg UniqueViolation 直接泄漏给调用方）、J2 source
  级 advisory 锁（并发发布按「无行」算 generation，后提交者用陈旧值覆盖，丢掉一次递增）、fencing 判定
  次序改为凭据优先判 lease\_lost（接管后旧 worker 迟到写入必须同一语义）、PUBLISHED 终态重新激活不受
  max\_attempts 约束（PG 与内存双 Adapter 同步收敛）；顺带清理 I2-7 遗留的 audit.py/service.py 导入卫生
  问题，使 CI lint 范围恢复全绿。证据：真库（i2-sandbox 守卫 env）31 passed（含 I2-2/I2-3 既有 18）、
  普通环境定向回归 312 passed / 1 skipped、i1 守卫 env 186 passed、ruff/pyright/import\_smoke 356/356；
  冻结 [i0c-r6](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i0c-r6.json)。
  I2-3/I2-7 独立审核整改（2026-09-17，[review](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260917-i23-i27-review/review.md) R1—R6，代码已改、快照待生成）：R3 内容寻址短路仅无显式 review_decision_ids 时生效；R4 发布日期只认显式报告日期声明；R5 FTS 查询侧/写侧共享 normalize_search_text 且 index_rev 升 index-3-zhcfg-2；R2 document_text/fetch/blocks_of 对 cv2: 句柄读 corpus_units；R1 extract_claims 由同源 corpus_units 投影（build_evidence_run_from_units，发布日期读 admission.report_publication），不再二次解析原文件；R6 补绑 publication.py + test_corpus_preparation_publication.py（脚本 `i0c_r7_freeze.py` 生成 i0c-r7）。M5 仍 not_declared。
  M4 独立复核材料已备（2026-09-16，[m4-review 包](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-m4-review/README.md)：复核纲要 + 放行条件核对清单 + 命令矩阵 run\_matrix.sh/verify\_matrix.py；同日按复核意见补齐五项执行控制——前置门 fail-fast（冻结验证器/哈希/可信副本/守卫自检失败即停 exit 2）、JUnit XML 精确核对计数与失败节点白名单、validate\_i1\_freeze.py 去 assert 并校验索引 ID 唯一/r3 条目/血缘 r3→r1→i0a5(M1)、运行后绑定零漂移门+脚本/探针/uv.lock 哈希与关键库版本留痕、受控最小环境（env -i+noconftest+禁插件自动加载，守卫 env 与普通 env 均不触 PG/模型）；修订后演练 16 块全 ok、write-once 拒绝路径 exit 2 实测；复核已于同日执行：16 块命中预期、独立交叉核验（哈希/血缘/逐文件用例数/对抗守卫探针/write-once）通过，[review.md](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-m4-review/review.md) 裁决 M4 放行（无 P1/P2，3 项 P3 不阻断），U 已签认；脚本退出码不构成裁决）。
  I3-0 交付并自验过门（2026-09-18，见总台账 [I3-0 评分器交付](claims-market-closed-loop-plan.md#i3-0-delivery)）：
  [scoring.py](../../plugins/corpus/scoring.py) 三类指标评分器（DocRecall@k 逐题召回率按类宏平均 /
  QuestionPass@k 冻结 any·all / EvidencePass@k 逐目标逐字取证 + verified 门；`Fraction` 精确门槛，
  10 题 95% 即 10/10；负例误报与伪造引用另计；关键题全项否决；零分母与缺必需输入一律计入分母并落
  机读 `blockers`，不静默剔除）；[测试](../../tests/test_corpus_scoring.py) **31 passed**、
  i3 守卫 env **31 passed** + 守卫自检 **24/24**、ruff（CI 范围）/pyright/`import_smoke`（360/360）全绿，
  冻结 **i0c-r19**（纯新增：implementation 组仅 `scoring.py`，验证器强制）→ **i0c-r20**  （当轮发现验证器
  r19 块路径拼装写错、未过门即修，只重绑验证器与台账文字）→ **i0c-r21**（2026-09-18 独立复核 F1—F5 整改，
  只改评分器与测试）+ validate exit 0；
  按纪律待独立复核与 U 签认（实现方不自我宣告 `complete`）。
  **I3-2 已可启动但须先补料**：`query-gold-frozen.jsonl` 30 题缺机器可读 `evidence_targets`，
  评分器按设计阻断（`missing_required_input:<qid>:evidence_targets_absent`）——I3-2 必须为每题补目标
  （可由 source-gold 的 locator/expected_items 映射）或显式 `evidence_required=false`；
  M5 报告 F3（`validate_i1_freeze.py` 既有失配，P3）本轮只登记未修。
  摘要从总台账同步，不是另一套可独立勾选的进度。完整证据见
  [首批交付复核报告](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/2026-09-15-status/review.md)
  与 [I0A-5 冻结报告](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i0a5-freeze-report-20260915.json)。

| 定位任务               | 状态与剩余条件入口                                                                                                                            |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------ |
| I0G-1 守卫（已放行）      | [实现、反例结果与放行裁决](claims-market-closed-loop-plan.md#i0g-1)                                                                              |
| I0A-1 / I0A-2      | [数据库盘点](claims-market-closed-loop-plan.md#i0a-1) / [来源与开发分母](claims-market-closed-loop-plan.md#i0a-2)                                |
| I0A-3 / I0A-4      | [政策冻结](claims-market-closed-loop-plan.md#i0a-3) / [金标与旧基线](claims-market-closed-loop-plan.md#i0a-4)                                  |
| I0A-5              | [逻辑契约与开发基线联合冻结（M1 达成）](claims-market-closed-loop-plan.md#i0-execution-ledger)                                                        |
| I1-8               | [守卫绑定 + 拒绝路径验证通过](claims-market-closed-loop-plan.md#i1-8)                                                                            |
| I1-1               | [contract 数据模型 + 内存 Adapter 完成](claims-market-closed-loop-plan.md#i1-1)                                                              |
| I1-2               | [readers 三格式 Adapter 完成](claims-market-closed-loop-plan.md#i1-2)                                                                     |
| I1-3               | [clean 保真清洗 + 区域台账完成](claims-market-closed-loop-plan.md#i1-3)                                                                        |
| I1-4               | [chunk 结构优先切块完成](claims-market-closed-loop-plan.md#i1-4)                                                                             |
| I1-5               | [admission 准入判定完成](claims-market-closed-loop-plan.md#i1-5)                                                                           |
| I1 复核修复            | [F1—F7 remediation 完成（15 反例转正，探针 20 passed）](claims-market-closed-loop-plan.md#i1-remediation)                                       |
| I1-6               | [source 接收/源变化检查/内容寻址归档完成](claims-market-closed-loop-plan.md#i1-6)                                                                   |
| I1-7               | [engine 全链编排完成（I1 核心任务全部完成）](claims-market-closed-loop-plan.md#i1-7)                                                                 |
| I1 二次复核修复          | [R1—R5 边界收口完成（REV 升版 \*-2）](claims-market-closed-loop-plan.md#i1-retest)                                                             |
| I1-9               | [合成夹具 + 阶段冻结 i1-r1 完成](claims-market-closed-loop-plan.md#i1-9)                                                                       |
| I1 整改复测与冻结链修复      | [R1—R6 边界与不可变冻结收口；当前候选 i1-r3](claims-market-closed-loop-plan.md#i1-remediation-retest)                                               |
| M4 独立复核与放行         | [裁决 M4 放行（i1-r3；16 块命中预期 + 独立交叉核验；U 签认 2026-09-16）](claims-market-closed-loop-plan.md#m4-review-release)                             |
| I0-C 设计复核与冻结       | [I0C-1/2/4 签认 + I0C-3 冻结 i0c-r1；九表布局/参数/消费者矩阵；M3 达成（U 签认 2026-09-17）](claims-market-closed-loop-plan.md#i0c-design-review)           |
| I2-1 隔离库 DDL 演练    | [corpus schema 九表 + 13 索引建于 i2\_sandbox\_corpus；26 项校验全 ok + 负例 3 全拒（I2-2 可启动）](claims-market-closed-loop-plan.md#i2-1)              |
| I2-2 PG repository | [Store 全接口 PG 适配器 + 独立复核 F1—F6 整改；当前冻结 i0c-r3；真库并发与消费者接线仍待 I2-5/7/8](claims-market-closed-loop-plan.md#i2-2-independent-remediation) |
| I2-3 FTS 读侧       | [INDEX\_REV\_V2 + 活动范围先筛后排名；DDL r3 全 ok；真库 18 passed 不 skip](claims-market-closed-loop-plan.md#i2-3)                                                       |
| I2-7 消费者接线（一） | [CorpusService 代理 preparation + ingest/claims\_v2 退役 + 唯一日期落点；i2-verify 守卫 26 passed](claims-market-closed-loop-plan.md#i2-7)                              |
| I2-5 publication\_pg | [真 PG 双 worker/租约接管/并发发布门通过（J1/J2/lease\_lost 次序/max\_attempts 四处修复；真库 31 passed）](claims-market-closed-loop-plan.md#i2-5)                    |
| I2-8 + I2-4         | [读侧版本句柄 + 旧句柄拒绝 + coverage 三轴 + CLI 六职责；独立复核 F1—F11 整改闭环（探针 5 failed→6 passed；重冻 i0c-r11）](claims-market-closed-loop-plan.md#i2-8-i2-4) |
| I2-6 authority + cli\_isolation | [同一权威 Interface + 坏副本/错 cell/坏哈希/悬空引用拒绝 + 真实 CLI 子进程与零模型陷阱（真库 77 passed；i0c-r13）](claims-market-closed-loop-plan.md#i2-6) |
| I2 全链路复核整改 | [F1 缺口分级/坐标（`acknowledged`/`blocking`/`out_of_scope`）+ F2 check/status 机读缺口与恢复路径 + coverage `scoped`；回路 10 passed/2 failed→12 passed，六族仍 71 passed；i0c-r15](claims-market-closed-loop-plan.md#i2-fullchain-remediation) |
| M5 复核与签认 | [矩阵 20 块全绿零 skip + X1—X15 全过；复核报告 F1/F2/F3；独立性偏差已登记并由 U 接受；i0c-r16](claims-market-closed-loop-plan.md#m5-review-signoff) |
| M7 放行签认 | [I4 窗口执行完毕 + 两轮复核修复闭环 + U 具名签认（2026-09-24，i0c-r5n）；M8 启动，I5-1 全四场景×8 源批准](../../.scratch/m7-rereview-20260924/signoff-record-m7.md) |
| I3-0 评分器 | [三类指标评分器 + 合成检验 31 passed；i3 守卫自检 24/24；纯新增冻结 i0c-r19；待独立复核与 U 签认](claims-market-closed-loop-plan.md#i3-0) |
| I3-0 复核整改 | [独立复核 9 红例按 F1—F5 修复不变量关闭；复核探针 10/10、自身 46 passed；i0c-r21](claims-market-closed-loop-plan.md#i3-0-review-remediation) |
| I3-1 三类 E2E | [已完成（i0c-r38）：批准集 8/8 发布、每类≥2、三格式覆盖、13 处人工确认缺口均合法处置；真实检索/取证通过，coverage scoped；r32/r34 为历史轮次](claims-market-closed-loop-plan.md#i31-human-gap-review) |
| I3-1 第二轮 dev lane | [U 裁决 dev lane 纳入 MD/DOCX（8 份 → 可发布 4/8、**§12.1 格式门 true**、`每类≥2` 仍 false）；生产判定不变由 dev lane 反例族 + 预检 fail-closed 反例双证；i0c-r34 入链](claims-market-closed-loop-plan.md#i3-1-dev-lane) |
| M6 判据补齐格式门 | [U 指令：把架构 §12.1 格式门显式写入 M6 判据（与 I3-7 行、§12.1 口径对齐）；只改判据文字，门行为与代码零改动、不新增阻塞；i0c-r35 入链](claims-market-closed-loop-plan.md#m6-format-criterion) |
| I3-2 补料 | [证据目标候选 v7 + **采纳稿落正式金标**（source-gold 36 槽位 = 冻结 23 条逐字节保留 + 采纳 13 槽/49 条；负例近似命中 7 条隔离成库）；目标 54→82（必需 44／补充 20／锚点 18）；`blocked` 2→1（`macro-004` 人工裁定覆盖）；裁决件 40+24+6+1 已落，门 **ready=true**（0 阻断／20 条人工同义 warning），批准投影 79 必需 + 20 补充；验证 30/30 自洽 + 探针 16/16；i0c-r26](claims-market-closed-loop-plan.md#i3-2-evidence-candidates) |

每轮执行结束必须回填总台账，即使失败或只完成草稿；同时记录代码/配置/资产版本、
命令与实际结果、报告链接、未决项及人工决定。不能把“文件存在”“自检通过”或“已写模板”
直接当作任务完成；前置未过不放行下一步。回填与导航同步是交付的一部分，不另增业务任务编号。

## 1. 角色与符号

- **U（用户/人工）**：环境权限/资源确认、准入终态裁决、金标判定、批准签认、维护窗口排定；已有配置可核查复用，不要求在文档或聊天中填写明文凭据。
- **A（Agent）**：脚本、代码、测试、报告生成与文档起草；被执行的基础链路、探查脚本和测试不得发起模型调用，不把开发助手起草的内容冒充人工金标。
- **A+U（联合）**：A 生成候选/结构化产物，U 判定与批准。
- **D0**：I0 启动日；姓名与日历排期待确认。下表只给依赖驱动窗口，不保留未经源量/恢复实测支持的固定天数；耗时在 I0-A/B 后标定，日期不得覆盖前置门。
- 各任务交付物路径见 v1.1 §12.1（`.scratch/corpus-evidence-pipeline/ingestion-rebuild/`）。

“前置”均为完成且证据仍有效，逗号表示 AND，不是任选一项。每阶段任务继承阶段门及守卫要求；
阶段内可以起草，但不得将草稿、部分样本或局部成功记为整项完成。本文不维护第二套完成状态，
任务 ID、状态及证据链接回填总计划；下列 M1—M8 只是放行定义。

## 2. 依赖与里程碑总览

```text
I0G-1 执行守卫
  → I0A-1..5 → M1（逻辑契约 + 开发基线）→ I1 → M4 ─────────┐
       └─ I0B-1..2 → M2；M1 + M2 → I0C → M3 ──────────────┴─→ I2（含旧消费者接线）→ M5
M5 → I3：预期/评分器冻结 → 开发校准 → 最终版本冻结 → 全链重验 → M6
M6 → I4：批准分支 → 停写截止点 → 最终备份/恢复 → 清单锁定 → 清理或迁移 → 核验恢复服务 → M7 → I5 → M8
```

- 当前只确定依赖图，不认定唯一关键路径；人工金标、恢复或设计复核都可能决定总工期。
- 可重叠轨道：I0A-1 后的盘点/标注与备份演练；M1 后内存链可与 I0B/I0C 并行。未满足 M1 不启动 I1 的开发运行。
- 人工作业重项：I0A-2（逐源终态）、I0A-4（金标/出题）、I0C-1（裁决签认）；吞吐在 I0A-1/2 摸清源量后复排。

| 里程碑 | 内容                | 通过条件（引自 v1.1 §11/§12）                                                                                                                                                 |
| --- | ----------------- | --------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| M1  | I0-A 交付齐          | I0A-1～5 全部完成，守卫有效；i0-inventory / dev-manifest / admission-policy / review-queue / source-gold / query-gold 基线 / baseline-bindings + 逻辑契约按阶段冻结；每来源合法终态，构建清单仅 in\_scope |
| M2  | I0-B 恢复报告通过       | i0-restore-report.json 实测恢复成功并记录耗时/错误；不接受"备份命令退出码 0"                                                                                                                  |
| M3  | I0-C 冻结           | M1、M2 与 I0C 全部完成；必需项无未决，否决候选已有获准替代；design-review/冻结版本/代码与配置引用一致，不以填写“待证据”放行 DDL                                                                                       |
| M4  | I1 内存链全绿          | M1 与 I1 全部完成；admission/fidelity/mapping 及接收/编排恢复测试 + 先行零模型守卫；不触真实 PG、不访问留出                                                                                            |
| M5  | I2 PG 门           | M3、M4 与 I2 全部完成，旧消费者在隔离目标接线；publication\_pg/authority/cli\_isolation 实测含租约接管，核心 PG 门不得 skip。**复核材料已备（2026-09-18）**：[M5 复核包](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/README.md)（含命令矩阵与交叉核验清单）。**复核完成并经 U 签认（2026-09-18，见 <a href="claims-market-closed-loop-plan.md#m5-review-signoff">M5 独立复核与 U 签认</a>）**：矩阵 20 块 MATRIX OK（零 failure/error/skip）、X1—X15 全过、`verify_matrix.py --self-test` SELFTEST_OK；复核报告 [review.md](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/review.md) 登记 3 项发现（F1 测试顺序依赖假红已修、F2 备料包锚点过时已按包 v2/i0c-r16 重发、F3 i1 冻结校验器既有失配），并显著登记「复核人 = 制备方会话」的**独立性偏差**（由 U 接受；不予接受则 M5 回到 `not_declared` 另派全新会话重做） |
| M6  | I3 最终版本 E2E + 非回归 | I3-7 对 I3-6 冻结版本重验通过；逐类三指标达冻结目标，关键引用题 100%、适用旧检索/财务基线不退化、已知伪引用负例为 0；宏观 0/3 单列；**声称支持的格式（PDF/DOCX/MD）按架构 §12.1 各有真实已用开发样本、无未处置缺格（dev lane 样本计入但须标注 `dev_lane`）**；缺资产/必需环境不通过                                                                             |
| M7  | I4 切换完成           | 获准分支完成；停写截止点后的最终一致性备份恢复成功、精确切换清单已批准；清理分支另有 reset 清单，迁移分支不强制删除；活动索引无污染且真实 CLI/工具核验通过                                                                                   |
| M8  | I5 退役完成           | 四种重复/变更场景可重复；旧入口退出；无隐藏双写                                                                                                                                              |

## 3. 任务清单

### 3.0 执行守卫（所有运行任务的先决条件，非新增业务里程碑）

| ID    | 任务与关键步骤                                                                  | 所需资源                  | 负责人 | 执行窗口            | 前置 | 验收/质量门                                                                            |
| ----- | ------------------------------------------------------------------------ | --------------------- | --- | --------------- | -- | --------------------------------------------------------------------------------- |
| I0G-1 | 建立/核查阶段化执行守卫：模型客户端/智能解析陷阱，子进程启动和测试收集前生效；开发来源允许清单；分目标网络/文件权限；先用合成反例验证拒绝行为 | 已有守卫、明确目标/配置；无须原文内容探查 | A   | D0，任何探查脚本/测试运行前 | —  | I0 仅批准的只读盘点/隔离恢复目标；I1 无网络/PG；I2/I3 仅隔离 PG；留出不进入开发读取。守卫自身合成检查通过后才运行来源脚本，不自动获得数据库授权 |

I0 的文件清单/hash 与受控备份完整性检查不等于允许读取留出正文。不同操作分别限制来源读取、
备份写入和恢复目标；恢复程序不得挂载可写原库或启动原库后台写入任务。最初目标不明确时仅
核查本地配置并报告缺口，不用真实连接试探环境。守卫配置变化必须重新核验并绑定当前阶段版本。

### 3.1 I0-A 盘点与契约冻结（M1）

| ID    | 任务与关键步骤                                                                                                                                                          | 所需资源           | 负责人 | 起止（估）            | 前置                         | 验收/质量门                                                                  |
| ----- | ---------------------------------------------------------------------------------------------------------------------------------------------------------------- | -------------- | --- | ---------------- | -------------------------- | ----------------------------------------------------------------------- |
| I0A-1 | PG 目标盘点：只读枚举 host/db/schema、表/视图/索引/序列/扩展；识别后台写入任务与全部读写消费者；确认共库；零 DDL/DML                                                                                        | 已确认只读权限、代码库 rg | A+U | 守卫通过后，耗时待盘点      | I0G-1                      | i0-inventory.json 不含凭据；每对象有 consumer 证据或 unknown；相关 unknown 阻断对应物理/清理决定 |
| I0A-2 | 来源与开发分母：显式来源清单、SHA-256/格式/路径、旧人工审核导出；按已确认范围与人工决定登记 in\_scope/excluded\_by\_policy/review\_required；选三类开发材料每类≥2 份并隔离留出；**产出 `format_availability` 对账表（架构 §12.1：声称格式 × 已准入可得性，缺格须显式处置）**                                            | 来源目录、旧库只读      | A+U | I0A-1 后，人工吞吐待标定  | I0A-1                      | dev-manifest/review-queue；每来源合法终态且有依据；进入构建的仅 in\_scope。未决列队，不为凑样本放行；**缺格式格未处置（补料工单或 U 显式改声称）不得进 I3-1 取样**     |
| I0A-3 | 按架构 §5.2 冻结 admission-policy：输入输出、判定次序、feature\_id/匹配表达式/扫描上限/extractor\_rev、正反例、自动决策禁用；校验 I0A-2 记录符合政策                                                          | 本批准入用例         | A+U | I0A-2 后          | I0A-2                      | 枚举一致；冲突退回复核；不得用特征建议代替人工决定；表驱动用例可据此编写                                    |
| I0A-4 | 限本批开发范围：人工 source-gold 标原值/条件/评级/页段/cell；query-gold 每类≥10 条含关键题/any-all/无答案负例；baseline-bindings 绑定适用旧 golden、财务 57/57、公式 7/7、客户表 12/12、正文 3/3、宏观失败资产及旧锚点到来源/证据映射 | 本批人工标注，原文依据    | A+U | I0A-3 后，按实际标注量排期 | I0A-2, I0A-3               | 不扩为全库逐字段标注；不模型出题、不从候选结果倒推答案、不改旧 gold；适用旧检索/关键题/负例均有清单与哈希，缺料阻断 M1        |
| I0A-5 | 逻辑契约与开发基线联合冻结：decide\_admission、引用权威/日期、coverage 三轴、rev、job 状态机；绑定 I0A-1～4 产物形成 M1 阶段快照；物理候选仍待 I0-C                                                              | 逻辑规格及本批资产      | A+U | I0A-4 后          | I0A-1, I0A-2, I0A-3, I0A-4 | 逻辑与测试预期可实现、当前阶段快照不可变；M1 通过才开 I1，不以单独签名或部分样本放行                           |

### 3.2 I0-B 首次归档与恢复演练（M2）

| ID    | 任务与关键步骤                                                                                | 所需资源         | 负责人 | 起止（估）            | 前置           | 验收/质量门                                                         |
| ----- | -------------------------------------------------------------------------------------- | ------------ | --- | ---------------- | ------------ | -------------------------------------------------------------- |
| I0B-1 | 制定并实际生成首次备份：确认来源/隔离目标不相同及足够容量；原文+一致性 PG 快照+人工审核+预算/raw+历史引用/基线；记录对象/哈希/大小/位置/截止点并检查完整性 | 明确备份权限、目标、容量 | A+U | I0A-1 后，可与后续标注重叠 | I0G-1, I0A-1 | 清单覆盖架构 §10；U 确认范围；实际备份存在且可核验，不只交清单。记录一致性方法及在线变化限制；不授权停原库/覆盖旧备份 |
| I0B-2 | 在核定的隔离目标恢复实际备份；验证版本/扩展/权限/对象数量/哈希、抽样取证和可用性；记录耗时/错误/恢复时间及数据损失约束；留出仅受控完整性检查              | 显式恢复目标与权限    | A+U | I0B-1 后，耗时由实测给出  | I0B-1        | i0-restore-report 含证据；禁向原库回灌、禁启旧后台任务；环境不可用则 M2 未通过，不能仅凭备份退出码成功 |

### 3.3 I0-C 设计复核与冻结（M3）

| ID    | 任务与关键步骤                                                                                         | 所需资源            | 负责人 | 起止（估）   | 前置                  | 验收/质量门                                                            |
| ----- | ----------------------------------------------------------------------------------------------- | --------------- | --- | ------- | ------------------- | ----------------------------------------------------------------- |
| I0C-1 | 候选逐条保留/调整/否决/待证据；复用/新建/迁移字段映射；选择 reset（仅精确旧派生对象）/migrate/defer 分支，并明确共享依赖                       | M1/M2 全部证据      | A+U | M1、M2 后 | M1, M2              | design-review 引用真实证据；必需布局未决阻断 M3；清理否决不等于新链也被否决，分项标明，不把“全删”解释为整库删除 |
| I0C-2 | 冻结运行参数：lease\_ttl/heartbeat\_interval/stage\_timeout/max\_attempts、解析资源与归档权限/容量；记录推导依据及 I2 待实测项 | M1 资产规模、M2 恢复证据 | A+U | I0C-1 后 | I0C-1               | heartbeat ≤ TTL/3；缺配置不启动；参数是待真实负载验证的基线，不把备份耗时当解析耗时                |
| I0C-4 | 收敛迁移替代、依赖风险和消费者迁移矩阵；定稿架构及实施分支；退休范围明确到符号/入口/表和保留依赖                                               | 裁决/参数           | A+U | I0C-2 后 | I0C-1, I0C-2        | 必需风险未解则不形成实施冻结版；非阻断风险有责任与适用范围；无平行架构                               |
| I0C-3 | 将本阶段实际存在的源/规则/预期/配置/代码/测试绑定不可变 manifest，关联 M1/M2 父快照；后续阶段另生成新版本                                 | 定稿产物            | A   | I0C-4 后 | I0C-1, I0C-2, I0C-4 | 报告绑定其实际运行快照，而非永远同一文件；未来测试/评分器不得填假哈希，I3 使用前单独冻结，规则见 §5             |

### 3.4 I1 统一解析/清洗/切块内存链（M4；前置 M1；可与 I0B/I0C 并行）

所有 I1 任务继承 M1 和 I0G-1；I1-8 先执行。文件名是候选落点，不为目录齐全制造转发层。
归档仅使用批准的测试暂存目标，不改变正式原文档案；I0-C 后若逻辑决定变化，受影响 I1 结果失效并重验。

| ID   | 任务与关键步骤                                                        | 所需资源                                    | 负责人 | 起止（估）             | 前置                                       | 验收/质量门                                                    |
| ---- | -------------------------------------------------------------- | --------------------------------------- | --- | ----------------- | ---------------------------------------- | --------------------------------------------------------- |
| I1-8 | 将 I0G-1 绑定为 I1 无网络/PG 配置；模型客户端构造/调用陷阱和子进程继承测试；拒绝守卫先于任何模块测试收集   | 现有守卫、合成负例                               | A   | M1 后首项            | M1, I0G-1                                | 拒绝路径验证成功才启动 I1 测试；不是只声明 models\_disabled；后续成功/错误/超时路径继续验证 |
| I1-1 | contract：来源/准入/构建/单元/块/job/coverage 模型、rev 与指纹；内存存储 Adapter    | uv 工具链                                  | A   | I1-8 后            | I1-8                                     | 数据模型与 M1 一致，Ruff/Pyright 通过；测试不构造真实 PG/模型客户端              |
| I1-2 | readers：冻结候选 PDF/DOCX/MD Adapter，输出单元/坐标/状态；表格冲突复核             | 本批允许样本、读取库                              | A   | I1-1 后            | I1-1                                     | fidelity 空页/多栏/表格/重复标题/短 MD 反例通过，不靠装库声称支持                 |
| I1-3 | clean：保真视图、字符/单元映射、区域台账，保护数字/期间/否定/条件                          | 冻结规则                                    | A   | I1-2 后            | I1-2                                     | 每区有状态；映射回到权威原文；不无记录丢失                                     |
| I1-4 | chunk：结构优先切块，800—1200/1800 仅开发起点；问答/表格/上下文分离                   | 冻结起始参数                                  | A   | I1-3 后            | I1-3                                     | 不断单元格/混期间；超长不可分单元显式复核；检索块不当原子义务                           |
| I1-5 | admission：确认清单纯函数、固定判定次序、冲突/未知原因                               | admission-policy                        | A   | I1-1 后            | I1-1, I0A-3                              | 表驱动 gold 全过，同输入同版本同结果，未决不能发布                              |
| I1-6 | source：接收、源变化检查、哈希及内容寻址归档；仅测试暂存/内存登记                           | 批准的测试目录                                 | A   | I1-1 后            | I1-1                                     | 原子置入和重复执行；登记失败可恢复；不覆盖正式原文                                 |
| I1-7 | engine：同一 Interface 的 plan/execute/publish、内存检查点和恢复            | 内存 Adapter                              | A   | 所需实现完成后           | I1-2, I1-3, I1-4, I1-5, I1-6             | 幂等、失败恢复、取消和未准入拒绝均可测；不另建绕过 Interface 的执行入口                 |
| I1-9 | 合成夹具、admission/fidelity/mapping 及接收/归档/engine 恢复测试；运行守卫审计与阶段冻结 | tests/fixtures/corpus\_preparation 候选目录 | A   | I1-7 后收口，夹具可随开发编写 | I1-2, I1-3, I1-4, I1-5, I1-6, I1-7, I1-8 | 全部必需用例通过才 M4；实际实现/测试/配置哈希一致；不触 PG/留出，版权原料不入公开夹具           |

### 3.5 I2 PG 层与 CLI（M5；前置 M3+M4）

所有 I2 任务继承 M3、M4 和 I0G-1 的当前阶段配置，仅写显式隔离目标。I2-7/8 为新增加的
真实消费者接线任务；M5 不接受“新 CLI 通过，但旧 search/fetch 仍读旧 blocks”。

| ID   | 任务与关键步骤                                                                                                                              | 所需资源          | 负责人 | 起止（估）             | 前置               | 验收/质量门                                                     |
| ---- | ------------------------------------------------------------------------------------------------------------------------------------ | ------------- | --- | ----------------- | ---------------- | ---------------------------------------------------------- |
| I2-1 | 按 I0-C 冻结布局在隔离 PG 建 DDL、准备获准分支的迁移/恢复脚本；演练不得操作旧默认库                                                                                    | 明确隔离目标/权限     | A+U | M3、M4 后，耗时待标定     | M3, M4           | 字段映射一致；目标校验 fail-closed；隔离临时对象清理亦须精确范围                     |
| I2-2 | repository：候选写入、活动指针、job 租约/接管、短事务和检查点                                                                                               | 隔离 PG         | A   | I2-1 后            | I2-1             | §8.1 全部规则，lease\_lost 停写不发布，数据库时间和 attempt 幂等              |
| I2-3 | FTS：分词配置版本、search\_text/GIN、身份/领域/日期索引、index\_rev；SQL 先筛活动范围再排名                                                                      | 隔离 PG         | A   | I2-1 后，可与 I2-2 重叠 | I2-1             | 索引升级可重建，不改同名配置却沿用旧版本；不从旧库混查候选                              |
| I2-7 | 消费者接线（一）：CorpusService 代理统一准备 Module；Evidence/EvidenceRun 由同源 units 投影；fetch/document\_text/source\_resolver/元数据读取迁移；拆清仍使用的共享模型/校验依赖 | I0-C 消费者矩阵    | A   | I2-2/3 后          | I2-2, I2-3       | 不二次解析生成主正文；权威引用与来源日期唯一；该实验目标无 legacy fallback；财务/R2 共享能力保留 |
| I2-8 | 消费者接线（二）：真实 corpus\_search/corpus\_fetch、verify、golden/日期调用方与批处理迁移；精确版本句柄、coverage/hint、旧引用归档策略                                      | 实际工具注册、调用者清单  | A   | I2-7 后            | I2-7             | 新句柄可跨发布取回原版本（**文档级与块级同语义**）；未知/旧句柄不静默换正文；测试断言实际读取目标/build，不只断言工具可调用。**2026-09-18 独立复核裁定（RM-I28-0）**：①文档级读取遵循句柄 build 且 `build_id`=实际读取的 build；②撤销文档级返回 `None`（非空串）；③迁移目标 legacy 读路径不可达（显式请求即拒）；④`coverage` 必带 `publication_snapshot_ref`，检索与覆盖同快照；⑤fetch 透出 span；⑥data\_coverage 透出三轴；⑦旧引用归档 manifest **顺延 I4**（precondition=新链重建核对后）；⑧golden **carry-over 至 I3-5**（design-review 矩阵 [6]）；⑨批处理 `scripts/corpus\_holdout\_eval.py`/`truncation\_*.py`/`corpus\_evidence\_pilot.py` 归 **I3-5/I5-3**（评测与退休核验，不属 I2-8 读侧接线）      |
| I2-4 | CLI 六职责：corpus-plan/build/check/publish/status/rebuild-plan；复用正式编排与解析产物                                                              | CLI 宿主        | A   | I2-7 后，可与 I2-8 重叠 | I2-7             | CLI 不复制规则（**parse 复用判定经 `engine.expected\_parse\_rev` 单一来源**）；错误退出码**同因同码**（目标不存在=5、门未过=4、目标拒绝=3、输入非法=2，`argparse` 错误归一为返回码 2）；操作者/generation、精确目标与阶段守卫有效；这些为拟新增命令        |
| I2-5 | publication\_pg：双 worker、过期 token、提交丢响应、撤销、取消、并发发布、恢复和配置升级                                                                           | 真实隔离 PG       | A   | 实现后运行             | I2-2, I2-3       | 全部强制场景，PG 不得 skip，不以内存锁代替；冻结当前配置/实现/结果                     |
| I2-6 | authority + cli\_isolation；按矩阵验证实际消费者都接同一权威 Interface，覆盖坏副本/错 cell/跨 build/坏哈希/子进程                                                   | 同一隔离 PG 与注册工具 | A   | I2-4/8 后          | I2-4, I2-8, I2-5 | 旧来源路径不能兜底；零模型陷阱通过；阶段全部交付有效才 M5。**2026-09-18 完成**：authority 8 + cli\_isolation 5 用例真库零 skip；读侧补 chunk/文档/cell 三路 `content_hash` 核验（文档级原缺）、引用悬空 `IntegrityError`、`fetch_cell`、证据副本权威指纹校验       |

### 3.6 I3 三类开发校准与最终重验（M6；前置 M5）

所有 I3 任务继承 M5/守卫。先冻结预期与评分器，再看本轮业务结果；调参与最终验收分别留报告。
任何规则/代码变化均按 §5 建新版本；M5 受影响时重验其对应门，不能只重跑检索分数。

**M5 前置已解除**：M5 于 2026-09-18 完成独立复核并经 U 签认（矩阵 20 块全绿零 skip、X1—X15 全过，
见 [M5 独立复核与 U 签认](claims-market-closed-loop-plan.md#m5-review-signoff)）；本节从 I3-0/I3-2
（预期与评分器冻结）起步，I3-1 另需其 F1 前置（缺口分级/坐标，已于 i0c-r15 闭环）。

**I3-0 已交付并自验过门（2026-09-18）**：评分器 [scoring.py](../../plugins/corpus/scoring.py) 与合成测试
[test_corpus_scoring.py](../../tests/test_corpus_scoring.py)（31 passed；i3 守卫 env 31 passed）落定，
守卫 [guards/i3.json](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3.json) 自检 24/24，
冻结 **i0c-r19** → **i0c-r20**（仅修验证器路径拼装）→ **i0c-r21**（独立复核 F1—F5 整改；validate exit 0），详见总台账。
**已按 2026-09-18 独立复核整改**（[报告](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i30-review/review.md)：既有 31 项全过、独立反例 9 failed/1 passed）：
F1 集合交集与重复来源拒绝；F2 证据保留来源归属（`EvidenceTarget.source_id`、默认仅认相关集）+ `build_id` 留痕 + `verified` 必须显式提交；
F3 `NO_MATCH` 带 payload 拒绝、`FAILED` 不计成功分；F4 导入器与 `score()` 共用严格校验（多文档 any/all 必须显式、sources 必须是字符串数组）；
F5 直接构造入口同样校验（空 quote 拒绝）。复核探针（原文件未改）**10/10 passed**、自身 **46 passed**；
已复核确认闭环并经 U 签认（i0c-r33）
[I3-0 评分器交付](claims-market-closed-loop-plan.md#i3-0-delivery)；按纪律待独立复核 + U 签认。
I3-2 可启动，但**必须先补机器可读证据目标**（缺则评分器按设计阻断，不得用散文 `evidence_requirement` 顶替，
也不得靠“没写”静默退出 EvidencePass 分母）；M5 报告 F3（`validate_i1_freeze.py` 既有失配）建议随 I3 前置修订理顺。

**I3-1 三类开发 E2E 已真实执行（2026-09-19 深夜，照 U 批准的开发集；**i0c-r32** 首次入链）**：
环境 = 隔离沙箱 `corpus-db`（`127.0.0.1:543`，库 `i2_sandbox_corpus`，`corpus` schema 九表）；
阶段守卫 [guards/i3-e2e.json](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json)
（`config_version=1`、网络 allowlist 仅 `127.0.0.1:543`、零模型、`allowed_source_paths` = 批准集 6 份、
留出根与 `guards/i3.json` 逐字一致），合成反例自检 **24/24**
（[报告](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-e2e-guard-report.json)，
write-once；首冻前发现 `model` 封锁面弱于 `guards/i3.json`——`anthropic` 与 `plugins.corpus.material_semantics`
未被拒，已对齐后重跑）。范围唯一权威源 = `i0a2-adjudicated-20260915.json` 的 `dev_selection_approved`
（U 2026-09-15 批准 6 份 PDF），取样前
[preflight_scope_check.py](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/preflight_scope_check.py)
判 **PASS**；**Agent 自选/换料范围已撤回**（保留
[撤回记录](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-retraction-record.md)，
守卫允许路径 15→6；沙箱数据层 teardown（`residue=0`）+ 重建后按批准集重跑，逐源与矩阵**完全复现**）。
真实结果（[批准集记录](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-approved-set.md)
+ [干净沙箱重跑](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-approved-set-rerun.md)）：
6 份 build 全成功（**4305 单元 / 767 切块**），**可发布 2/6**（company 0/2、industry 1/2、macro 1/2），
阻断缺口 **13 处**（`table_lines_without_extraction` 9 + `image_region_unreadable` 4），检索 `同比` 4 命中、
取证核验全过、被拒句柄 0、`audit_corpus_chain` 冲突 0、coverage `scoped`/`matched`。
**判定：I3-1 未完成** —— `per_class_min_2_satisfied=false`（"三类每类≥2 份"在**现行门 + 现行裁定**下无解：
阻断缺口无合法处置路径）；格式覆盖**仅 PDF**（DOCX/MD 在准入口径下 0 份，§12.1 未满足）。两项**待 U 裁定**：
①阻断缺口的处置路径（补 OCR／人工认可入口／换料／显式登记不覆盖）；②MD·DOCX 是否声称覆盖。
**本轮初步结果不得直接放行 I4**；I3-3/I3-4/I3-5/I3-7 另做（缺口分布 F1—F10 见
[复盘](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/retrospective-i3-1-scope.md)）。

**I3-2 采纳稿已落正式路径并冻结（2026-09-18，A 侧，规则仍 `evidence-mapping-6`；i0c-r26；见总台账
[I3-2 补料](claims-market-closed-loop-plan.md#i3-2-evidence-candidates)）**：U 全文审核 AI 辅助补证与裁决建议后**全部采纳**（署名 `xyl` + `ai_assisted: true`，AI 复核者非人类签名）；新金标版本 = 23 条冻结槽位**逐字节保留** + 采纳 13 槽位/49 条（逐条对账页内切片：页号 + quote 逐字 + quote_sha256），负例的 7 条近似命中外移为
[负例库](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/source-gold-nearmiss-library.jsonl)（不入映射池）；重映射后 30 题 → 目标 **82** 条（必需 44／补充 20／待批准锚点 18）、`machine_ready` 2／`pending_human` 21／`blocked` 1／负例 6；裁决件
[40 要件 + 24 整题 + 6 负例 + 1 状态澄清](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-decisions.json) 落盘后，
[门](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/approval-report.json) **ready=true（0 阻断）**、
[批准投影](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-approved.json) 30 题 = 必需 **79** + 补充 20 条、
[验证](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-verification.json) 自洽 30/30 + 探针 16/16。
四项口径：①AI 核验锚点逐项确认同义（门记 20 条 warning，机器不宣称语义等价）；②无内容词元的纯日期 span 不作承载映射；③chosen 收窄到最小覆盖集（53→35，移出的 18 条记 `supporting_anchors`，不计入 EvidencePass）；④`macro-004` 的 `blocked`（q2 机器检索未登记承载项）由人工裁定覆盖，机器状态原样保留供审计。**仍未宣告 I3-2 完成**：I3-2 其余冻结项、I3-1（E2E）与 I3-5 真实答案语义验收未做；强制零模型、未写生产库、未读候选业务结果。

**I3-2 尾巴收口（r31，2026-09-19，U 授权）**：签认记录 not_covered 的可收项已收口——
① **prose 留出入守卫**：`guards/i3.json` forbidden_roots 4 → 5（追加天风 `5520fab6`），
完成门新增『留出隔离覆盖』判据；② **19 题锚点映射规则级复核关闭**（归一化标题子串唯一命中 +
来源路径在磁盘 + 5 个 doc_id 与已标注 source-gold 同源；`closure.kind=rule_verified_by_authorization`，
非逐题人工通读）；③ **20 条人工同义 warning 作为已接受风险入册**（字面出处机器核验、语义由具名人工承担，
warning 原样保留供抽样审计）；④ 完成门增至 **10 项判据**（新增留出隔离覆盖／映射规则复核／收口记录）。
冻结 **i0c-r31**（parent=r30）。**M5 F3 按诊断稿单列跟踪**（i1 链 13 项 I2 阶段合法漂移，
本轮不动 i1 链，建议后续 i1-r5 重绑）。I3-5/I3-1/I3-7 仍未执行（需环境与预算授权）。

**I3-2 阶段签认（r30，2026-09-19）**：具名审核人 **xyl** 于 2026-09-19 确认[阶段签认记录](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/signoff-record-i3-2.md)
（复核结论：通过，0 fail／1 观察项；签认 4 项 claim，明确 6 项不含）。冻结修订 **i0c-r30**（parent=r29）：
绑定签认记录 + 复核脚本（含『已签记录不得重写』守卫）+ 执行记录 + **生成器入链**
（`generate_p2_p3_p4.py` 与 r28/r29 冻结脚本，修正 r29 登记的『生成器不可追溯』缺陷）+ 两份台账；
完成门新增判据：**阶段签认必须具名且记录已入链**。I3-5/I3-1 仍未执行；prose 留出（天风 5520fab6）
是否纳入 `guards/i3.json` 待定。

**I3-0 阶段签认（r33，2026-09-19）**：具名审核人 **xyl** 确认[I3-0 阶段签认记录](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i30-review/signoff-record-i3-0.md)
（复核结论：通过；签认 4 项 claim，明确 6 项不含）。冻结修订 **i0c-r33**（parent=r32）：
绑定签认记录 + 收口脚本 + 复核报告/独立探针/复跑入口（证据面与裁决面同一）+ 两份台账；
I3-0 独立复核 F1—F5 以修复不变量方式闭环（探针 10/10、自身 46 passed，评分器字节 r21）。

**I3-2 Step 5 针对性复核与整改（r29，2026-09-19）**：复核范围限定『新增派生关系／旧基线范围／初始版本』，
复用既有审批（不重审补料链）。方法为**独立重推**（未复用产物自校验）+ 通用路径可解析检查。
**抓到并修掉 4 处 P4 路径缺陷**：`policy.confirmation` 与 `baseline_mapping.reconciliation`、
`decisions.path`、`approved_projection.path`（含 `source_gold`/`index`/`case_level`）基准目录不一致，
从仓库根解析不到 → 统一为仓库根相对路径并重算 lineage。复核结论：**通过**
（[step5-review.md](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/step5-review.md)），
另 1 项观察项：prose 留出（天风 `5520fab6`）未纳入 `guards/i3.json` 的 `forbidden_roots`（待定，未擅自改守卫）。
冻结修订 **i0c-r29**（parent=r28）：绑 P2/P3/P4 修正件 + Step 5 复核/差异包 + 台账；
**阶段签认记录 `signoff-record-i3-2.{md,json}` 保持 `pending_user_signoff`，待 U 具名签认后再入链**。

**I3-2 Step A—C 整改（r28，2026-09-19）**：按诊断稿 `20260919-i32-diagnosis` 的 Step A—C 完成三项：
① **正式评分输入派生件** `i3-2/query-gold-scoring-v1.jsonl`（`1b018ceb…`，79 必需 + 20 补充、
负例无目标、原字段零改动）+ `scoring-input-manifest.json` lineage + 派生器 `i3s2_scoring_input.py`
（含唯一读入口 `load_scoring_input` 与 6 条变异反例）；审批原件未改（门仍 `ready=true`）。
② **旧基线引用资产入链**：`golden.py`／`derivation.py`／`pilot_manifest.json`／机器记录／
三份报告／`spec.md`／`prose_holdout_manifest.json`／doc_kind CSV／`verify_claims_entry.py`／
`i0a5-doclist`／`i0a4-candidates-v3` 随 r28 绑定，消除『未冻结的必要外部指针』。
③ **旧锚点映射与公式契约**：19 题旧锚点 → 新 source 身份（`i0a5-doclist` 的 `doc_id`）**19/19 唯一命中**、
22/22 `source_path` 在磁盘、其中 5 个 doc_id 与已标注 source-gold 同源，O6 因留出排除
（`legacy-anchor-mapping.json`，`confirmed=false` 待人工复核）；7 条公式的输入指标按
`plugins/corpus/derivation.py` 声明登记；**阶段完成门** `validate_i3_2_completion.py` 已实现并入链。
冻结修订 **i0c-r28**（parent=r27）。**仍未宣告 I3-2 完成**：19 题映射复核、20 条人工同义 warning、
`macro-004` 机器 blocked 覆盖属人工复核项；I3-5/I3-1 未执行。

**I3-2 旧基线冻结（r27，2026-09-19）**：7 类旧基线适用范围与预期全部经 U 逐项圈定并确认（诊断稿
[diagnosis-and-remediation.md](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/diagnosis-and-remediation.md)、
[baseline-case-manifest.md](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/baseline-case-manifest.md)，
status=frozen_r27）：① old_doc_kind_review 以 `c1_full84_doc_kind_review_20260912.csv`（sha d69bbb1d…）为权威版本
（决定件 [json](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i32-diagnosis/decision-old-doc-kind-review-authority-20260919.json) / md）；② legacy_retrieval_golden 冻结 **19 题**、排除 O6
（来源华泰联储加息属留出，golden.py 原题保留）；③ financial_controlled_recalc_57 容差 = 规范化后精确匹配 tol=0，
guosen_maotai_holdout（国信茅台 bbba671e.pdf，10 格）纳入守卫留出链（[i3.json](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3.json)
forbidden_roots 3→4）；④ formula_7 沿用既有 tolerance（1e-6）；⑤ customer_table_12 以报告为准、按历史非回归处置；
⑥ prose_numbers_3 冻结 2 条可复现用例、第 3 条标不可复现；⑦ macro_legacy_fields_0_of_3 以机器记录 2 targets 为准、
previous 移出分母。8 项 blocked 清零，冻结修订 **i0c-r27**（parent=i0c-r26，validate exit 0）。**仍未宣告 I3-2 完成**：
阶段完成门 `validate_i3_2_completion.py` 未实现（已登记为后续前置）、legacy 旧锚点→新 locator 映射仍
`to_be_resolved`、I3-5 真实非回归未执行；零模型、未写生产库、未读留出原文。

**（本节以下为 r25 历史：候选 54 条与审批门 `no_decisions`）**：
**I3-2 补料候选已按复验报告 B1—B5 修复（2026-09-18，A 侧，规则 `evidence-mapping-6`；见总台账
[I3-2 补料](claims-market-closed-loop-plan.md#i3-2-evidence-candidates)）**：
[i3s2_evidence_targets.py](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_evidence_targets.py)
+ [i3s2_textutil.py](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_textutil.py)（共享切分/词元规则）
从 I0A-4 人工标注槽位映射 30 题证据目标（要求覆盖账按段并行登记数值与限定 + 单元格身份 +
required/supplementary/suggested 三层 + 锚点覆盖度与未覆盖词元 + 数值等价入队）→
[候选](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-candidates.json)
（machine_ready 2／pending_human 20／blocked 2／负例 6；目标 54 条 = 必需 35／补充 4／待批准锚点 15）
+ [逐题核对单](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-review.md)
+ [人工裁决单](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-adjudication.md)
（要件 40 + 整题 24 + 负例 6 + 状态澄清 1）
+ [自检三段](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/evidence-targets-verification.json)
（`self_consistency` 0 failed、`regression_probes` 16/16、`completeness_gate` = no_decisions）。
**审批路径**：`evidence-targets-decisions.json` →（[i3s2_apply_decisions.py](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/i3s2_apply_decisions.py)）
→ `evidence-targets-approved.json` + `approval-report.json`；候选文件里的 `adjudication.status`
**不作凭据**（改它不会开门），`驳回` 不删除原题要求、`补标注` 须先有新 source-gold 版本。
**EvidencePass 分母 = 逐题**（架构 §12.3）：item 条数与槽位聚合只作诊断，"逐 item vs 槽位聚合"二选一已作废。
**U 决策事项**：40 项要件裁决 + 24 题整题验收（含 `machine_ready` 题）+ 6 题负例覆盖 + 1 项来源状态澄清。
裁决前**不得**把候选当正式金标，也不得先跑候选业务结果再补答案；`ready=false` 是候选阶段的正确状态。

**r25 修复边界**：来源专属项须绑定指定 source_id；答案约束禁止 chosen 且不得生成证据；
`residual_accepted=true` 禁用，缺证须补标；仅词面差异可用 `lexical_review` 逐项绑定原文。
检索线索提升须 `改选 + anchor_review`，不能把 text/period 元数据当原文。
审批身份、重复项、负例依据及最终投影引用均 fail-closed。
命令、修复前后结果及旧字节归档见
[修复记录](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remediation/review.md)。
本轮只交付修复，不自我宣告 I3-2/M6 放行，也不代替 U 签认。

| ID   | 任务与关键步骤                                                                             | 所需资源              | 负责人 | 起止（估）             | 前置               | 验收/质量门                                                                         |
| ---- | ----------------------------------------------------------------------------------- | ----------------- | --- | ----------------- | ---------------- | ------------------------------------------------------------------------------ |
| I3-0 | 实现/合成测试评分器：DocRecall、QuestionPass、EvidencePass 的分母、any/all、负例与关键题否决；不读候选业务结果        | M3 指标定义、合成例       | A   | M5 后先做            | M5               | 多文档/零分母/缺资产/10 题 95% 等边界正确；不是 LLM judge，缺必需输入不能算通过                             |
| I3-2 | 在本轮候选业务结果可见之前确认 source/query gold、旧基线映射、各类阈值/关键题/负例，冻结评分器与试验初始版本                    | 本批原文、人工依据         | A+U | I3-0 后，I3-1 前     | I3-0             | 不从 E2E 输出改答案；确需修订则保留旧失败、建新金标版本并同口径重评基线/候选；不冒称独立留出                              |
| I3-1 | 三类开发 E2E：每类≥2 份，登记→准入→解析→清洗→切块→build/check/publish→真实 search/fetch/verify           | 冻结开发范围、隔离 PG      | A+U | I3-2 后            | I3-2 + **I2 全链路复核 F1 闭环** | **最新 r38：已完成，8/8 发布、每类≥2、三格式、13 acknowledged/0 blocking，真实取证通过；以下为历史轮次。** 记录领域×格式矩阵，缺格式门未过；本轮初步结果不能直接放行 I4；**前置**：缺口分级/坐标（RM-FC-1/2）闭环——材料含空白页等 `acknowledged` 缺口才可走完 publish，`blocking` 缺口按 `check`/`status` 的 `gaps` 机读处置（补 OCR/换料/转 review\_required）；先用 `corpus-plan` 预检筛料。**2026-09-19 实跑（i0c-r32 入链）**：照 U 批准集 6 份 → 可发布 2/6（company 0/2、industry 1/2、macro 1/2）、阻断缺口 13 处、格式覆盖仅 PDF；`per_class_min_2` 未满足，判定**未完成**，待 U 裁定缺口处置路径与 MD/DOCX 覆盖声称。**2026-09-20 第二轮（U 裁决新建 dev lane，i0c-r34 入链）**：dev lane 纳入 U 指定 2 份（`工业富联_投委会决策报告_20260829.md` / `9月8日 光模块…docx`，材料类型如实为 `internal_committee_report` / `internal_unattributed`），与批准集 6 份合计 8 份真跑 → 可发布 **4/8**；**架构 §12.1 格式门满足=true**（pdf 2/6、docx 1/1、md 1/1 均有可发布样本）；逐类可发布 company 1/3、industry 2/3、macro 1/2 → **『每类≥2』仍为 False（裁定①未解，company 0/2 的 13 处阻断缺口依旧）**；证据 `audits/20260920-i31-dev-lane/i3-1-dev-lane-e2e.{json,md}`；生产判定不变由 dev lane 反例族 + 预检 fail-closed 反例双证 |
| I3-3 | 开发校准：检索/切块参数仅开发集试验；每轮先固定配置再执行 retrieval\_pg，报告数字/单位/语言及三类指标                         | 冻结预期、当前配置         | A   | I3-1 后            | I3-1             | 记录每轮失败和配置哈希，预先限定试验范围/停止条件；不改预期换分数；超过边界停下报告，不无限试探                                **最新 r39：已进入校准，两轮30题均未达标；OR 候选三类 DocRecall=100%，EvidencePass=1/8、2/8、2/8，负例误报6；按预定两轮停止，保留失败，未部署候选。** |
| I3-4 | coverage 开发测试：空库/无匹配/排除/部分/未决/故障/更新失败/并发发布/跨域                                       | 隔离 PG             | A   | I3-1 后，可与 I3-3 重叠 | I3-1             | 三轴及 availability；no\_match 不自动 absent，failed 恒 unknown；最终版本仍须 I3-7 重验          |
| I3-5 | 开发非回归：适用旧检索 golden、财务 57/57、公式 7/7、客户表 12/12、正文 3/3 及正负控，宏观 0/3 另列；答案约束登记/投影保真门 | baseline-bindings、I3-2 批准投影与审批契约测试 | A | I3-1 后，可与 I3-3 重叠 | I3-1 | 按实际绑定资产核验；不得删旧失败题。零模型约束门：运行 audits/20260918-i32-remediation/test_approval_contract.py，确认 answer_constraints 原样保留、chosen 不生成证据、非法引用阻断；I3-5 时须重跑并绑定最终资产。该门不检验生成答案语义；真实答案语义测试须另定输入、人工判据和有限预算，未授权前 not_run，不计作通过。此处不是最终版本放行 **最新 2026-09-23：已执行（audits/20260923-i35-legacy-nonregress/，零模型、原库零写入、留出零读取）**：财务 47/47+公式 7/7+高盛负控 PASS（库级等价路径，偏差已登记——I2-7 后冻结契约 verify_claims_entry 写原库不可原样执行）；golden 19/19（O6 r27 排除，旧库 legacy 读链只读，无 skip）；客户表 12/12（冻结 run 复验，原文 holdout 不读）；正文冻结 2 例 2/2（重抽取 not_run 待预算授权）；宏观 0/3 保留单列；guosen_maotai 10 格 held_out_not_run_in_dev（I3-7 口径）；审批契约门 32 passed。I3-6/I3-7 另做 |
| I3-6 | 结束校准并冻结最终配置、代码、规则、评分器、预期与依赖；生成不可变最终 manifest，核定需重验的 M4/M5 门                         | 开发报告、最终版本         | A+U | I3-3/4/5 后        | I3-3, I3-4, I3-5 | 所有调整显式留档；无必需待定项；仅冻结版本，不复用校准前分数宣称通过 **最新 2026-09-23：已执行（audits/20260923-i36-final-freeze/ + i3-final-freeze-manifest.json，i0c-r5a 入链）**：冻结版本=i0c-r4z 链头；关键资产/运行时配置/校准收口（三类 100%、24/24、关键 22/22、FP=0）入 manifest；M4/M5 重验九组核定交 I3-7；待定项均为另立授权型，无冻结必需待定项。仅冻结版本，M6 不放行 |
| I3-7 | 用 I3-6 版本重新构建/索引并执行三类 E2E、retrieval、authority/取证、coverage、CLI、旧检索/财务非回归及受影响 M4/M5 门 | 最终版本、隔离 PG        | A+U | I3-6 后            | I3-6             | 逐类三指标达冻结目标（候选 ≥95%）；关键引用 100%、适用旧通过基线不退化、伪引用负例 0；分母/格式/必需环境缺失不通过；全部结果与版本一致才 M6；**E2E 基线复用**：I2 全链路回路 12 项（9 链不变量 + check/status 缺口契约，[test\_fullchain\_probes.py](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-fullchain-review/test_fullchain_probes.py)，write-once 不修改）+ [test\_corpus\_gap\_dispositions.py](../../tests/test_corpus_gap_dispositions.py) **最新 2026-09-23：已执行（audits/20260923-i37-final-reverify/，零模型、隔离 PG、留出零读取；对 i0c-r4z 冻结版本）**：重建 8/8 published+active，revs 与冻结报告逐一复现；评分 14/14 门全绿（24/24、三类 DocRecall=1、关键 22/22、FP=0/伪引用=0、b5 零回退、prune on 非劣化、abstain=on 负例 6/6、取证回环全过）；测试电池 9 门全绿（m4-plain/i1 各 320+dev 9+search-live 11+fullchain 12 照原样+hermetic 74+d2d6 73；恢复后 build_id 确定性复现、active 指针严格=8 源）；legacy 与 I3-5 同口径全过；D2/D6 双重偏差与守卫 Popen 注入运行纪律已登记（fail-closed 行为正确非缺陷）；abstain 正例误拒 24/24 登记 pending 待 U 裁决（非本轮门）；静态门 ruff/import_smoke/pyright 0 err。全部结果与版本一致；M6 须独立复核 + U 具名签认，本轮不放行 **最新 2026-09-23 M6：独立复核通过（audits/20260923-m6-independent-review/review.md，零反例）+ U（xyl）具名签认放行；abstain 正例误拒 24/24 裁决为接受已知限制（S1 关闭登记，评分层与负例冻结口径不受影响）；签认记录 signoff-record-m6.{md,json} 入链 i0c-r5c** |

### 3.7 I4 迁移、清理与切换（M7；前置 M6 + 批准 + 维护窗口）

I4 全部继承 M6 和当前目标守卫。分支为 reset/migrate/defer：reset 只清理批准的旧语料派生
对象；migrate 仅执行批准的迁移，不附带整包清理；defer 或批准缺失不得启动维护变更，也不能
算 M7 通过。若只是撤销清理、但迁移可行，应重新明确批准 migrate，而非自动停止整个重构。

最终备份必须覆盖停写截止点。窗口前演练不能替代它；从停写确认到清单执行必须持续禁止写入。
写入恢复、对象/权限/源文件漂移或版本变化均使相关最终证据失效，停止清理并重新核验，不仅检查表名。

| ID   | 任务与关键步骤                                                                                   | 所需资源            | 负责人 | 起止（估）        | 前置   | 验收/质量门                                                                              |
| ---- | ----------------------------------------------------------------------------------------- | --------------- | --- | ------------ | ---- | ----------------------------------------------------------------------------------- |
| I4-1 | 窗口前准备/演练：确认获准分支、当前对象/消费者、M6 最终版本、容量/恢复目标和失败回退步骤；批准停写窗口与预期操作范围                             | M6、I0-C 裁决、用户窗口 | A+U | 窗口前，时长待标定    | M6   | 预演备份明确标非最终备份；defer/缺批准不进下一步；耗时超窗口能力则重排，不强行删库                                        |
| I4-3 | 窗口内停写：暂停批准范围内全部写入任务与默认检索，处理/等待活动写事务，确认无新增提交并记录截止点/源归档清单                                   | 已批准窗口、精确写入者清单   | A+U | 窗口首步         | I4-1 | 可证明写入已停止，持续保持限制；本步不删除。不能证明无写入则停止，不能先备份后补停写                                          |
| I4-6 | 在停写状态取得最终一致性备份并实际隔离恢复：PG+原文归档+人工/审计/raw 同一清单，核验哈希、数量、权限/扩展和历史取证                           | 备份/恢复目标、停写状态    | A+U | I4-3 后，仍在窗口内 | I4-3 | 恢复覆盖已记录截止点；实际耗时在批准窗口内；失败不执行清理，按批准中止路径保留旧服务可恢复                                       |
| I4-2 | 锁定最终切换 manifest：精确目标/对象/保留项/顺序/源与代码版本/截止点/最终备份恢复/批准；reset 分支另列删除清单，migrate 分支列变更清单及禁止附带删除 | I4-6 证据、最新盘点    | A+U | I4-6 后、执行前   | I4-6 | i4-cutover-manifest.json 绑定批准；reset 另绑定 i4-reset-manifest.json；最终核对无漂移，不能只凭 I0 清单签认 |
| I4-7 | 执行获准分支：reset 按精确依赖顺序清理旧派生对象；migrate 按批准步骤迁移，不运行整包 reset；defer 无执行                         | 冻结切换清单          | A+U | 最终清单核验后      | I4-2 | 操作与逐对象审计一一对应；漂移/错误停止，不扩大删除；保留原文、人工结果、共用扩展与无关业务表                                     |
| I4-4 | 重建或验证迁移后的活动集：逐批准来源构建/校验/发布；未准入与失败列账；验证索引/权威引用/版本/计数                                       | 冻结代码与活动来源清单     | A   | I4-7 后       | I4-7 | 无纪要/旧版本污染，无静默缺源；失败从阶段恢复或按批准方案回退，不能失败后直接恢复默认检索                                       |
| I4-5 | 真 CLI/注册工具往返与失败恢复核验后恢复服务；停用已批准旧写入口；记录实际切换/保留对象                                            | I4-4 结果         | A+U | 窗口结束前        | I4-4 | 无双写，最终版本与 M6 一致；reset 后回退靠已验证备份，不靠旧指针。若中止/回退则保留失败，M7 不通过                            |

### 3.8 I5 增量与运维（M8；前置 M7）

| ID   | 任务与关键步骤                                                               | 所需资源          | 负责人 | 起止（估）      | 前置   | 验收/质量门                                                              |
| ---- | --------------------------------------------------------------------- | ------------- | --- | ---------- | ---- | ------------------------------------------------------------------- |
| I5-1 | 复核四种场景：同源同版本重跑、源变化、新规则 build、复用解析重建索引；按批准的验证范围执行，不偷偷改变活动来源            | 已切换环境、明确验证范围  | A   | M7 后，耗时待标定 | M7   | 幂等、版本、缓存及失败恢复正确；与 I2/I3 同场景结果可对照，不将首次正确性验证留到切换后                     |
| I5-2 | 维护说明定稿：增量、恢复、归档/GC、分支实际保留对象、故障交接；草稿可提前编写                              | 实测结果          | A   | I5-1 后定稿   | I5-1 | 覆盖架构 §8/§10；GC 不触原文/已发布版本；无未实现命令冒充可执行说明                             |
| I5-3 | 核验 I2 已完成的解析/消费者归并与 I4 旧入口停用；按 I0-C 矩阵确认旧抽取路径退出，记录尚保留的共享类型/财务验证/R2 依赖 | 逐入口/符号依赖与运行证据 | A+U | I5-1 后     | I5-1 | 无 legacy fallback；不是此时首次归并。只核验/停用已批准范围，不据“claims 退休”删共享模块；新增退休需求另核定 |

## 4. 排期与待用户确认项

1. **D0 与责任交接**：统一使用 D0，不混用 T0；先核查现有配置与资料，只把实际缺少的权限/资源/决定交给用户。
2. **维护窗口**：覆盖停写、最终备份、恢复验证、批准核对、迁移/清理、重建验证和恢复服务的完整链；I0-B 实测后评估，不预设“一两天足够”。
3. **开发清单与人工量**：每类至少两份且格式矩阵明确；I0A-4 只标本批范围，不要求全库全文逐字段标注；旧批准记录符合当前哈希则复用。
4. **隔离目标与权限制约**：I0 恢复/I2 实验和旧默认库分开；提供方式先安全核查，不能在文档打印凭据。
5. **资源标定**：记录来源量、标注量、解析/索引/恢复实测与可用人力；据此重算相对窗口及可能关键路径。并行描述不等于授权新模型、子代理或额外运行。

## 5. 变更纪律

- I0 任一产物推翻候选设计：修订本文对应任务及上游架构文档（§0 流程），不另起平行计划。
- 所有起止均服从阶段门和实际资源，未标定时不承诺完成天数；缺样本/必需环境/审核或 hash 不一致，阶段为未满足，不能以 skip 通过。
- 冻结按**阶段/修订追加不可变快照**：候选路径 `freezes/<phase>-<revision>.json`，含 manifest\_id、parent\_refs（含哈希）、来源/规则/预期/评分器/测试/代码版本与工作区差异指纹。`freeze-manifest.json` 若保留，只是定位当前快照的索引，不能作为可变历史依据。
- 报告直接绑定实际运行快照 ID/哈希、build/配置及代码指纹；I0 不虚构尚未实现的测试/评分器哈希，使用前补冻。代码、规则、源、预期、配置或评分器变化形成子版本并重验受影响门，旧报告不覆盖、不自动继承通过。
- I3-6 后发生影响运行的变化，最终报告失效，回到新的版本冻结与 I3-7；修改金标须有原文依据和人工裁决，保留前轮结果并同口径重评基线与候选。
- 切换记录拟存 `i4-cutover-manifest.json`；reset 才额外使用 `i4-reset-manifest.json`。两者是明确批准的执行载体，不是从本任务文档自动生成的授权。defer 不执行、不假通过。
- I4 前不得破坏旧默认库、原文或人工/审计资产。I0/I2 隔离恢复/迁移测试仅操作已核验临时目标，涉及清理也须精确对象与批准范围，不得用“实验环境”绕过目标检查。
- 基础链路模型授权保持零，真实模型调用另提范围与预算；不执行会真实调用模型的通用 preflight。按影响面做零模型检查，文档更新不等于获准执行本表。

## 6. 本轮评审修订对应表

| 评审问题                | 任务修订                                                 | 放行依据                                |
| ------------------- | ---------------------------------------------------- | ----------------------------------- |
| 最新备份早于停写            | I4-1 只预演；I4-3 停写；新增 I4-6 最终备份/恢复；I4-2 锁清单；新增 I4-7 执行 | 停写截止点、持续写入限制、最终恢复证据                 |
| I1/I2 前置不一致         | I0A-5 联合冻结基线；I1 依赖 M1，I2 全部继承 M3+M4                  | 阶段门优先于任何日期/局部成功                     |
| 旧消费者接线缺失            | 新增 I2-7/8；I5-3 只复核归并/退休                              | 实际 service/tools/verify 同源同版本，无旧库兜底 |
| 零模型守卫过晚             | 新增 I0G-1；I1-8 移至本阶段首项                                | 探查、收集和子进程启动前拒绝策略                    |
| 最终版本未重验             | 新增 I3-0 评分器合成检验；I3-2 前移；I3-3 校准；I3-6 冻结；新增 I3-7 全链重验 | M6 只读最终版本结果                         |
| 关键题/旧检索/负例门遗漏       | I0A-4、I3-5/7、M6 补齐                                   | 关键题全过、旧通过能力不退化、伪引用为零                |
| manifest 语义不清       | I0C-3 改阶段快照，§5 不可变父子版本                               | 每报告绑定自己的运行版本，不追改历史                  |
| 清理被固定成必选            | I0C-1 和 I4 reset/migrate/defer 分支                    | M7 衡量有效切换，不要求发生删除                   |
| 枚举/人工量/备份生成/排期/退休细节 | I0A-2/4、I0B-1/2、§4、I5-3                              | 契约一致、范围有界、真实备份、按依赖标定                |
