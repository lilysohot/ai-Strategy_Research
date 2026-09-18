# I2-3 / I2-7 独立审核（2026-09-17，当前 i0c-r6 工作区）

## 结论与范围

- I2-3 方向正确，已交付版本化 FTS 查询与活动版本筛选，但百分比查询存在实测漏召回；不能把当前测试通过扩大为数字查询契约已完整成立。
- I2-7 仅部分完成。写入代理和共享规则拆分已交付，但“Evidence 由同源 units 投影”“fetch/document_text/source_resolver 迁移”尚未满足；把这些推到 I2-8 与现有任务清单 I2-7 的职责不一致。这不是单纯实现细节，而是完成状态高估。
- 保留既定架构，不增加模型预算、不扩文档范围。先修接线、准入重评、日期依据和冻结覆盖，再继续依赖这些能力的验收。
- 当前工作区另含 I2-5/r6 改动，本次按实际最新状态检查两项任务，不对 I2-5 作完整独立验收。

本次只新增审核探针和报告；未修改实现/正式测试/台账/冻结文件，未执行 TRUNCATE、DDL、DML、重建或清库。没有模型调用、真实来源或留出正文读取。采用 diagnosing-bugs 的最小反例方法验证缺口；不是修复任务。

## 本次实测

| 核验 | 结果 | 解释 |
|---|---|---|
| 当前冻结验证器 | exit 0 | 已修旧继承绑定问题，但遗漏新 publication 模块，见 R6 |
| 上轮 I2 独立反例 | 7 passed / 0 failed | 上轮 F1—F6 在原探针范围已闭合，不重复判为未修 |
| preparation 11 业务文件 + 新日期文件 | 192 passed，29.77s | i1 无网络守卫，env -i，未跑真库写测试 |
| claims_detail / evidence_pipeline / metadata | 33 passed、6 skipped，0.65s | 不将 skip 算作通过，也不宣称完整财务/R2 非回归已验收 |
| 新增零数据库反例 | 7 failed、1 passed，0.57s | 2 条新 review、2 条日期、旧正文读取、二次解析、冻结漏绑定失败；明确报告日期对照通过 |
| 隔离 PG 只读 FTS 表达式 | 百分比漏召回复现 | default_transaction_read_only=on，核对库名/生产反证；只 SELECT，不读业务行 |

## R1 · P1：Evidence 仍然二次解析，未落实 canonical units 投影

任务清单 `docs/plan/corpus-ingestion-rebuild-tasks.md:215` 要求 Evidence/EvidenceRun 从同源 units 投影且不二次生成主正文。

实际路径：`service.py:903` 的 extract_claims → `evidence_pipeline.py:599` 的 build_evidence_run → `evidence.py:447` 的 parse_evidence。后者仍直接读取 PDF/DOCX/MD，产生独立 raw_pages/packets、16 位 source_rev 和自己的 parse_rev。删除 ingest.py 并把辅助函数内联到 evidence.py 不等于统一解析真源。

探针 `test_extract_claims_does_not_reparse_source` 调用实际 CorpusService.extract_claims，persist=False、max_prose_calls=0、合成 MD；spy 证实 parse_evidence 仍被调用。未调用模型或保存 Evidence。

影响：新 corpus_units 与 Evidence 仍可能文本、坐标、版本分叉，重演之前“双主结果”问题。保留历史独立解析作兼容研究工具可以讨论，但必须显式隔离，不能让它作为已迁移的 canonical extraction 入口。

修正验收：新 Evidence 以 source/build 标识从 Store 取 units；禁止重开原文件解析来生成独立权威正文；断开旧 parser 的测试仍能完成同源 Evidence 投影，并逐项核对引用哈希/坐标/build。

## R2 · P1：基础读取仍访问旧 PG blocks，并非仅剩 I2-8 工具包装

`service.py:803-831` 的 fetch/document_text/blocks_of 仍 SELECT 旧 blocks；`source_resolver` 返回 document_text。`_connect` 走构造时 self._dsn，写路径 `_preparation_context` 却另读 CORPUS_I2_DSN，未统一目标。文档将旧读侧概括为 sqlite 也不准确：这里是 PG。

探针传入新式 cv2 句柄，假连接记录实际 SQL，仍然是 `FROM blocks WHERE doc_id=...`。没有访问真实旧库。

影响：新链写入成功后，原服务读取/取证不能取得新 units；若 self._dsn 与写 DSN 不同，写读还可能落到不同数据库。A1 测试的“service.ingest_path + 独立 search_chunks”组合不能证明 service.fetch/document_text 已接线。

修正验收：完成 I2-7 明列的这些基础读取迁移；只把工具封装、coverage/提示与更高层批处理留给 I2-8。旧句柄需显式归档策略，不允许静默读取另一套正文。

## R3 · P1：按源字节提前短路会忽略新的审核决定与版本需求

`service.py:613-623` 只要同 source_id 有 active_build_id，就直接返回 in_scope/skipped，不检查显式传入的 review_decision_ids、当前决定、scope 或新 index_rev。

两条最小反例分别传新排除决定 ID、新范围决定 ID，实际连 planner 都未调用。假 Store 仅模拟已有发布；探针证明“新决定未被求值”，并未伪称已执行某个真实人工决定。

影响：调用者明确要求重新裁决时被静默跳过；升级索引后的相同字节来源也可能继续保留旧 build。同源身份稳定不等于处理状态、授权范围和构建版本永远不变。

修正验收：通过正式 plan/engine 判断完整目标身份，只有相同有效准入/范围/配置/rev 的状态才短路；保留检查点复用以避免重复解析。补“已发布→新排除”“已发布→缩小范围”“同源→新 index_rev”服务入口测试，而不只测直接 Store 方法。

## R4 · P1：发布日期误认，直接污染 I2-3 日期过滤

有两个独立来源错误：

1. `engine.py:201-210` 将 descriptor.title（来自 planned.original_name）拼到探查 title 前面。publication.py 把开头日期标为 source_explicit。无任何正文日期，仅文件名 `2026.08.17-某券商-公司研究.md` 就得到 known 2026-08-17。
2. `publication.py:53-69` 把头部/正文遇到的首个有效日期都视为发布日期。合成正文“公司于2020年1月2日成立，本报告回顾其发展历史”被写为发布日期 2020-01-02。

两条反例均失败；“报告发布日期：2026年9月17日”对照通过。仅删除 doc_id 前缀派生并没有消除文件名派生；文本中有日期也不等于明确声明研报发布日期。

修正验收：日期探查只接权威 units 中可定位的原文候选，不混入登记文件名；区分报告日期字段与事件日期，歧义保留 unknown/复核。evidence_refs 应能回到 unit/具体位置，而不只是包含日期值的说明字符串；覆盖成立日、财报截止日、正文历史事件、多日期冲突和文件改名。

## R5 · P2：FTS 写侧去掉百分号，查询侧不做对应处理

`chunk.py:251-253` 把 search_text 的 `%` 替换成空格；`search_pg.py:115-125` 原样传 query 给 websearch_to_tsquery，导致双方 token 不一致。

本次在明确隔离库以只读连接运行实际 zhcfg 表达式，索引文本为实际代码规则处理后的“同比增长23.5 ”：

| 查询 | 实际 tsquery | matched |
|---|---|---|
| 23.5 | '23.5' | true |
| 23.5% | '23.5%' | false |
| 增长 23.5% | '增长' & '23.5%' | false |
| 同比增长 | '同比' <-> '增长' | true |

这不是猜测或普通“词典边界”：写侧主动规范化后，原文常见查询表达反而不能匹配。现有测试只断言裸数字成功，未覆盖含百分号查询。

修正验收：定义索引与查询一致的规范化契约，保留原文百分比语义，不能为修搜索去改 units；处理 websearch 的引号、OR、负号等语法，避免粗暴替换引入新错误。补正负数、小数、百分号/全角符号、单位与中英混合查询。若更改索引文本规则，另起 index_rev 与冻结修订。

## R6 · P1：新增日期实现和测试未纳入当前冻结

当前快照绑定未包含 `plugins/corpus/preparation/publication.py` 和 `tests/test_corpus_preparation_publication.py`，但 engine 已导入并使用前者生产入库元数据。

本次只在内存中模拟 publication.py 字节漂移，现行验证器依然输出成功，磁盘文件未修改。与上轮不同：上轮是继承绑定没查；本轮是新文件根本没进绑定。旧的 engine 漂移探针现已通过，所以不应笼统判“上次未修”。

修正验收：补全当前可达实现/测试依赖清单，新版 manifest 明确覆盖新文件，增加“新增模块漏绑定”反例；保留历史快照，不追改其哈希。绑定存在且逐项匹配不等于清单完整。

## 工程观察（不扩大为已实测缺陷）

- FTS 日期过滤按 ISO 字符串比较，应补不同 precision、同一天 timestamp 上界、非法/逆序范围的行为契约；这次没有真实库业务行实测，不作为新增已复现问题。
- search_pg 的空元组返回可作为底层查询结果；coverage 和空命中解释属于后续 I2-8，不能因尚无 coverage 单独判 I2-3 偏离。
- claims_v2→claims_detail 的共享规则拆分方向合理，定向测试通过不代表所有财务/旧黄金集已完成非回归。删除旧测试应有逐项替代覆盖清单，不以测试数下降或新测试全绿推断等价。
- 当前总计划同一处重复列 I2-5 完成/待执行的不同阶段叙述，建议明确历史时点与当前状态；M5 仍未声明这一点正确。

## 建议推进顺序

1. I2-7 回填为“部分交付、独立复核待整改”，完成基础读取与 Evidence 的 canonical units 接线，不擅自更改任务分工。
2. 修服务入口的新审核/rev 重评、发布日期依据；这些都是服务核心契约，不应留给金标调参掩盖。
3. 修 FTS 双向规范化并补固定查询用例；完整绑定新模块、正式回归和现行审计测试，生成新冻结修订。
4. 对修订版运行两层验收：Store/PG 核心测试 + 同一个 CorpusService 的 ingest→search→fetch→Evidence 链；跨 build 引用还需 I2-8/I2-6 继续验。

无需新研报、重新标金标或追加模型预算。本审核不授权重建、清理或改写正式库。

## 可复现入口

同目录 `test_review_probes.py`：在仓库根用 i1 守卫运行 pytest（env -i、PYTHONPATH=仓库根、PYTEST_DISABLE_PLUGIN_AUTOLOAD=1、CORPUS_GUARD_PHASE=i1、CORPUS_GUARD_CONFIG=guards/i1.json，完整相对路径；pytest `--noconftest -c /dev/null -p no:cacheprovider -p plugins.corpus.preparation.guard_pytest`）。当前预期 **7 failed / 1 passed**，红色是应整改的规格断言。

同目录 `fts_readonly_probe.py`：仅使用隔离库 127.0.0.1:543/i2_sandbox_corpus；凭据在运行时读取且不输出；脚本主动安装 i2-sandbox 守卫、开启只读事务与 3 秒超时，并验证目标。仅运行 SELECT，不读取业务行或修改对象。
