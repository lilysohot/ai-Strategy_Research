# M6 全量测试与独立审核报告

审核对象：当前语料入库重构的 M6（I3 开发验证、最终冻结与重验），不是历史市场闭环计划的旧 M6。审核日期：2026-09-23。代码版本：`480693a`；比较基线：`327505cc4e83a0cc6040b522841f771f5a738ba4`（首次 I3 交付提交 `bbec9f2` 的父提交）。

**结论：冻结链、重建结果和既有测试成绩可以复现，但不能据此认定 M6 的正式产品路径已完整达标。发现 3 项 P1：1 项证据完整性缺陷、1 项正式取证接线缺陷、1 项验收观测构造缺陷。建议重新打开相应验收项，修复并重新冻结、重验。**

现有 U 签认记录确实存在。本报告不改写该历史决定，也不自动修改计划状态。已接受的 `abstain=on` 正例误拒，与本轮新增发现分开处理。

## Standards

### S1 · P1：跨边界补证没有验证内容哈希

位置：`plugins/corpus/preparation/cross_boundary.py:313–321`；三条候选路径还分别在 `:236`、`:261`、`:292` 解包并丢弃 `_chash`。

`aggregate_band_chunks()` 从库中读到 `content_hash`，但补入表头、续接片段、来源注时直接建立 `UnitEvidence`，没有比较原文 SHA-256。普通 `read_pg.fetch_verbatim()` 的完整性门因此没有覆盖这条新增路径。即使新增单元的原文已损坏或被修改，也会作为权威证据进入 band 文本。

独立合成反例调用公开聚合入口，将补入单元的哈希设置为全零。表头、续接片段、来源注三种场景均未抛出 `IntegrityError`：**3 failed，全部 DID NOT RAISE**。这些反例使用模拟连接，没有修改任何数据库记录。

这违反架构 §4.2 的权威原文/冲突拒绝要求和 `docs/plan/corpus-ingestion-rebuild-architecture.md:656` 的坏哈希拒绝验收，也与聚合模块自身文档承诺不符。

建议：补入任何单元前验证内容哈希，将完整性校验与单元装配收敛到共用实现；把三个反例纳入正式回归。

证据：[回归探针](test_integrity_regressions.py)、[失败日志](integrity-regressions.log)。

### 设计判断：Possible Duplicated Code

`read_pg.py:789–834` 的装配器与 `fetch_verbatim:216–268` 重复原文校验、`UnitEvidence` 与区间装配；`cross_boundary.py:313–343` 又实现了一份并漏掉哈希校验。这是值得收敛的设计异味，本身不另计阻塞项。

**Standards：1 项硬性缺陷（P1），1 项非阻塞设计建议。**

## Spec

### F1 · P1：评分通过的联合证据不能通过正式 fetch 回取

位置：`plugins/corpus/service.py:1051–1057` 与 `:1255`。

新增的跨 NOISE 边界、续接片段、表下注释聚合只接在 `search_bands()`。实际 `corpus_search` 调用 `search_with_coverage()` 返回 chunk 句柄，`corpus_fetch` 再调用 `fetch_verbatim()`；后者直接进入 `read_pg.fetch_verbatim()`，没有同样的补证逻辑。

在隔离 PG 上只读比较相同 build/chunk 句柄，独立复现以下冻结证据目标：

| 题目 / 目标 | 评分 band 字符数 | 正式 fetch 字符数 | 缺失内容 |
| --- | ---: | ---: | --- |
| company-007 / e1 | 509 | 506 | 持股句末的“份。”，完整引文无法匹配 |
| company-008 / a-1 | 29 | 6 | 标题部分，仅剩评级文字 |
| industry-008 / a-3、a-5 | 590 | 411 | 注1的统计期间说明 |

正式工具 `corpus_fetch.ainvoke()` 的返回正文与普通 fetch 一致，而非评分的聚合正文。原 authority 检查只验证版本/块身份、非空等条件，没有验证完整证据内容相同。

架构 `:684–686` 明确规定 EvidencePass 必须由返回句柄经 fetch/verify 满足全部证据；`:691` 要求正式 CLI/工具路径取得相同版本证据。因此这不是已接受的拒答开关限制，而是正式取证能力没有接齐。

建议：为联合证据提供统一且可验证的正式取证契约；逐个金标目标经真实工具回取并验证正文、定位及哈希，再重新冻结验收。

证据：[四个目标的精简差异](target-diff.jsonl)、[只读差异探针](m6-spec-fetch-probe.py)、[原始比较结果](m6-spec-fetch-probe-results.json)、[正式工具差分结果](product-path-probe.json)。

### F2 · P1：最终评分没有测量同一实际配置下的完整产品行为

位置：`.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify/i37_score.py:246–273`。独立复核脚本 `m6_rescore.py:198–226` 使用了相同的观测构造方式。

- 正例先将题干转换为词元 OR 查询，再调用 `search_bands(limit=2000)`。
- 六条负例直接根据金标构造 `QueryObservation(..., NO_MATCH, ())`，没有把实际检索结果交给评分器。这使“评分层 FP=0”无法证明产品负例能力。
- 正式 `corpus_search` 默认最多10块、上限20块，调用另一入口，而且没有同样的题干改写。

本轮不依据金标选择查询行为，对全部30题使用统一策略，经真实工具函数 `ainvoke()` 读取：

| 配置 | 正例24题 | 负例6题 |
| --- | --- | --- |
| abstain=off，原始题干，工具 limit=20 | 24/24 零命中 | 6/6 零命中 |
| abstain=off，统一词元 OR，工具 limit=20 | 24/24 均返回20块 | 6/6 均返回20块 |
| 冻结评分脚本 | 24/24 QP/EP | 人工构造空观测 |

第二行只记录实际检索候选数，不把“返回候选”冒称“模型生成错误答案”；本轮没有运行模型答案语义测验。但它足以证明：负例空观测不是这套 OR 检索配置的实际输出。第一行则说明，关闭拒答开关后，原题干的正式工具效果仍与24/24评分不同，不能全部归因于已签认的 abstain 限制。

架构 `:684–691` 要求真实取证路径、正例与负例分别验收。当前实验成绩可复现，但尚不能替代正式产品验收。未发现额外功能范围扩张，主要偏离发生在验收口径与实际调用路径之间。

建议：使用统一、不读取答案标签的查询策略；通过真实注册工具入口、产品允许的限制生成正负例观测；将“实验策略成绩”和“正式工具成绩”分列，禁止用构造的 NO_MATCH 计入产品成绩。

证据：[正式工具差分探针](product_path_probe.py)、[30题结果](product-path-probe.json)、[运行日志](product-path-probe.log)。

**Spec：2 项 P1。最严重的缺口是正式工具无法复现完整证据；评分观测构造又使该缺口未进入原验收结果。**

## 实际执行的验证

| 检查 | 本轮结果 |
| --- | --- |
| 全仓 `pytest tests apodex/tests -q --tb=short -ra` | **2896 passed / 2 failed / 49 skipped** |
| M4 plain | 320 passed / 7 skipped |
| M4 i1守卫 | 320 passed / 7 skipped |
| dev lane | 9 passed / 0 skipped |
| M5 search live | 11 passed / 0 skipped |
| fullchain | 12 passed / 0 skipped |
| M5 hermetic | 74 passed / 0 skipped |
| D2/D6独立临时库 | 73 passed / 0 skipped |
| 沙箱重建/恢复 | 前后两次8/8 published+active，build ID确定性复现；第三库删除 |
| 三个冻结验证器 | 全部exit 0 |
| 冻结评分复跑 | QP/EP 24/24；逐字段与原报告一致；已知abstain正例误拒24/24复现 |
| 恢复后DB独立核验 | 8源、revs重算、3次search/fetch身份回环全部通过 |
| Ruff（CI范围，含server） | 通过 |
| Pyright | 0 errors / 0 warnings |
| import_smoke stage1 / stage2 | 365/365、414/414 |
| check_symbols | 464文件，0 missing-symbol |
| 本轮新增完整性反例 | 3 failed，确认S1缺陷 |

各测试组有重叠，不能把通过数量相加视为独立覆盖数。全仓无DB测试中的部分skip已由隔离PG lanes补测；剩余skip没有宣称通过。

全仓首跑为2894通过/4失败。两项history测试因本审核启动器提供了API key/base URL占位符而漏给模型名，触发了正确的partial-injection拒绝；补齐完整假配置后，重新运行**整个测试集**，结果如上，只剩两项既有失败：

1. `tests/test_market_golden.py::test_market_hit_rate_is_100_percent`：fixture把 `as_of` 写死为2026-09-09，当前日期下超过5天新鲜度阈值，因此预期“无警告”不再成立。
2. `tests/test_research_discipline.py::test_react_profile_binds_the_finance_tools`：仍断言 `get_profile('react').tools()` 包含工具；当前react已改为workflow分派，profile YAML明确说明该factory不再负责绑定。真实 `workflows/stateful_react_agent/profiles/tui.yaml:81` 仍列有两个金融工具。测试断言没有随分派设计更新。

上述相关测试、配置与实现不在本次M6比较区间的变更中；不要把它们当成M6引入的两个产品回归。它们仍使当前全仓测试不能全绿。

详细日志：[全仓结果](full-pytest-corrected.log)、[隔离PG测试汇总](i37-tests-results.json)、[PG运行日志](pg-battery.log)、[DB核验](m6-dbcheck.json)、[冻结评分复跑](m6-rescore.json)。

## 范围与完成度判定

- **已获证**：冻结链可核验、既有验收结果可复现、隔离库完整重建/恢复、基础发布/检索/身份取证、所列静态检查。
- **新增未达标**：坏哈希拒绝、联合证据正式fetch闭合、同一实际产品配置下的完整正负例验收。
- **已签认限制**：abstain=on时24/24正例拒检，不重复报为新bug；宏观旧0/3也不改称已通过。
- **未执行范围**：真实模型preflight/语义答案测试、prose模型重抽、留出材料验收、生产5432库legacy黄金题复跑、I4迁移清理。它们不包含在本轮通过数中；没有把历史报告当成本轮执行结果。

本轮只新增此审核目录的脚本、日志和报告，没有改产品代码、冻结资产或进度台账，没有提交git。开始时已有的 `.codebuddy/memory/MEMORY.md` 用户改动保留。数据库写入仅发生在测试专用543端口沙箱及临时D2/D6库；测试后恢复8份活动来源、删除临时库，并再次核验。模型调用为0。

建议修复顺序：先补完整性拒绝门，再统一正式证据接口，最后以真实产品路径重生成观测和验收；新版本重新冻结后再讨论“完整完成”。
