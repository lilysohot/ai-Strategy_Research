# M7 修复后独立复核（2026-09-24）

**结论：六项中 S1、S2、G1 已关闭；G2、G3、G4 部分关闭。仍有 1 项 P1 和 2 项 P2，暂不建议宣告 M7 全部通过。**

本轮没有新增产品代码变更。对照上轮 `1f69be1`、当前 r5j 冻结版本及修复材料，重新运行全仓、
隔离 PG 电池、默认配置生产 30 题、静态检查和独立反例。起始 HEAD 为 `d897d8f`，
期间新增提交 `9f436b5` 将原已暂存的 ingest 退休测试及审查工件提交；受测产品代码未因此改变。
起止两次冻结验证均通过；受测文件与工件哈希见 [review-manifest.json](review-manifest.json)。

## 逐项关闭情况

| 原编号 | 结论 | 本次独立证据 |
|---|---|---|
| S1 导入时缓存目标 | **关闭** | 先 import、后设置目标，新建 service 与 read/search 缺省检查都使用 postgres |
| S2 检索入口分叉 | **关闭** | 新链 search 委托同一组合检索；原冻结全链路测试 **12/12**，未修改该探针 |
| G1 默认服务未恢复 | **关闭** | 当前 `.env` 默认配置直接 search→fetch 成功；30 题 QP/EP **24/24**、负例 **0/6** |
| G2 旧写入口未停用 | **部分关闭** | 旧 ingest 零连接拒绝成立；已登记停用的 evidence 写入口仍能写旧表，见 F1 |
| G3 恢复验收不足 | **部分关闭** | 已补耗时、权限、引用键、七表台账内容；缺恢复证据正文的验收，见 F2 |
| G4 证据冻结不完整 | **部分关闭** | 原九件窗口证据已绑定；新增修复验收报告仍缺实际版本绑定，见 F3 |

## 本次测试

各行有重复覆盖，不相加作为唯一用例数量。

| 检查 | 结果 | 日志 |
|---|---|---|
| 全仓 pytest | **2931 passed / 2 failed / 49 skipped**，223.06 秒 | [pytest.log](pytest.log) |
| M4 普通 / i1 守卫 | 各 **320 passed / 7 skipped**（PG 部分另跑） | [普通](lane-m4-plain.txt)、[守卫](lane-m4-i1.txt) |
| dev lane / 真 PG 检索 | **9 / 11 passed** | [dev](lane-dev-lane.txt)、[search](lane-m5-search-live.txt) |
| 冻结全链路 | **12 passed**，原失败已消失 | [日志](lane-fullchain-12.txt) |
| PG 发布/存储/取证/CLI/消费者 | **78 passed，零跳过** | [日志](lane-m5-hermetic.txt) |
| D2/D6 | **73 passed，零跳过** | [日志](lane-m5-dsn-d2d6.txt) |
| 默认配置生产产品门 | **QP 24/24、EP 24/24、负例误报 0/6、工具失败 0** | [结果](live-default.json)、[调用轨迹](product-trace-default.json) |
| Ruff / Pyright / symbol closure | 全通过；0 类型错误；465 文件 0 缺失符号 | [ruff](ruff.log)、[pyright](pyright.log)、[symbols](symbols.log) |
| import smoke 1 / 2 | **366/366、415/415** | [一](imports1.log)、[二](imports2.log) |
| r5j 冻结检查 | 开始、结束均通过 | [开始](freeze.log)、[结束](freeze-after.log) |
| 内存篡改负控 | 已绑定阶段二报告的哈希变化被拒绝（exit 1） | [结果](freeze-negative-controls.json) |

全仓两个失败仍是原有的 `test_market_hit_rate_is_100_percent`（固定报价日期过期）与
`test_react_profile_binds_the_finance_tools`（profile 财务工具集合为空）；没有新增全仓失败。
全仓没有向生产库开放写测试；PG 核心族通过单独隔离电池补验，49 skips 不表述为全部通过。
旧 golden/B7 的 legacy stats 就绪问题仍存在，本轮未改其 skip 条件来取得绿色结果。

## Standards

S1、S2 的实现修复符合上轮建议：目标解析移至构造/调用时；`search()` 复用 `search_with_coverage()`。
独立[运行探针](runtime-counterexamples-confirm.json)及真 PG 全链路均确认生效。
消费者测试从“每来源多块”调整为“每来源一个锚点”，与现有工具的 context_locators 合同一致，
且未修改原冻结全链路测试；没有发现靠更改该探针掩盖 S2 的情况。
本轴新增问题 **0**，上轮两项关闭。

## Spec

### F1 · P1：G2 只关闭 ingest，已登记停用的 evidence 写入口仍可执行

位置：`plugins/corpus/service.py:1524`（`save_evidence_run`），`:1580`（`persist=True`），
`:1620`（落库调用），`:2845`（CLI extract-claims 的调用路径）。

当前 `save_evidence_run()` 仍执行 `CREATE TABLE IF NOT EXISTS corpus_evidence_runs` 和
`INSERT INTO corpus_evidence_runs`，没有切换后停用检查。
独立合成反例（无模型、禁止真实网络和数据库连接）成功返回 run_id，并记录建表、旧表 INSERT。
主审再次运行结果相同：[反例](runtime-counterexamples-confirm.json)。
生产只读权限核查还确认当前用户具有该表 INSERT/UPDATE 权限，且没有用户触发器阻断写入；
**本次没有向生产执行这些写语句**：[权限证据](privileges.json)。

依据：I4-5 要求停用已批准旧写入口；切换 manifest 的 `forbidden[1]` 要求 public 旧表零写入；
`i45_tool_roundtrip.py:228–232` 明确把 `save_evidence_run` 登记为停用。
现有两条新测试只证明 ingest 拒绝，不能覆盖此入口。
建议对切换后的已批准退休写路径执行明确拒绝，并覆盖 `extract_claims(persist=True)`；
若业务确需保留写入，应正式修订实际保留范围和验收口径，不能同时宣称入口已停用。
这不要求删除共享 EvidenceRun 类型、离线计算或财务验证能力。

### F2 · P2：G3 的“历史取证”尚未检验恢复后的原文正文

位置：`.scratch/m7-fix-20260924/g3_isolated_restore_verify.py:165–184`、`:279`。

新增报告的恢复计时 **1.433 秒**、11 表计数、4 扩展、当前单 postgres 默认权限对账，
以及 1318 个引用键、七表台账双向 EXCEPT 均有对应执行逻辑，相关缺口已补。
但引用核验只检查 `(doc_id, locator)` 是否存在；逐行对账七表不包含 `blocks/documents`。
正文 MD5 的信息性计算没有与归档原文基线比较，也不进入 `loop_ok`。
因此保持引用键和台账不变而把恢复块正文改错，该历史取证门仍可通过。

依据：I4-6 的“历史取证”要求。建议使用已有归档 crosswalk 的 `block_text`，
从恢复库按旧句柄取回正文并逐字比较，至少覆盖抽样历史引用；将这一比较纳入通过条件。
**这是验收覆盖不足，不是发现备份损坏。**本次仅审查补验代码与记录，没有重跑该建库/恢复脚本。

### F3 · P2：新增验收报告仍未绑定修复后的实际运行版本

位置：`.scratch/m7-fix-20260924/i37-tests-results.json:4–7`、
`g3-isolated-restore-verification.json:170`、`freezes/i0c-r5j.json` 的 binding。

新电池报告仍声明 `chain_head_declared=i0c-r4z` / `chain_binding_revision=i0c-r5a`，
实际执行的是修复后代码。r5j 的 19 项绑定覆盖修复代码、测试和旧窗口九件证据，
却不包含本轮 `live-default.json`、电池结果、G3 补验及其执行脚本；G3 还明确写“不绑入冻结链”。
本次通过内存拦截读取验证：旧阶段二报告哈希变化会使冻结验证失败，
但验证器不读取新 G3/电池结果的哈希，仍 exit 0；未修改任何冻结文件。

依据：任务分解 `docs/plan/corpus-ingestion-rebuild-tasks.md:647` 要求报告直接绑定实际快照、配置、代码指纹。
建议新增修订绑定新验收材料和生成脚本，报告中区分“复用的历史测试基线”与“本轮受测版本”。
原 G4 的 token-only 问题已修，不能因此推断新增验收结果也已经完整入链。

本轴剩余 **3 项：最高 P1 为 F1；F2/F3 为 P2 验收证据缺口**。

## 状态与边界

生产默认 search 返回 4 个命中，fetch 成功取回 18 单元；30 题运行前后计数及活动指针一致，
仍为 8 个活动来源、834 chunks、3887 units，旧九表零行。既有 stats/list_documents 仍查询旧表，
stats 输出 0 文档/0 块的迁移残留尚未处理；这是上轮观察项，不在本轮另加严重级别。

隔离电池通过全部门，结束后 8/8 活动来源和 build_id 严格恢复，临时 D2/D6 库已删除；
见 [电池结果](i37-tests-results.json)。沙箱进程显式设置空 `CORPUS_TARGET_DB`，
防止新的生产 `.env` 配置被 dotenv 注入测试进程；不修改真实运行配置。

本轮只新增审查目录工件，未修改产品、测试、冻结链或历史报告，未写生产库，未调用真实模型。
没有代替用户作 M7 放行或推进 I5。
