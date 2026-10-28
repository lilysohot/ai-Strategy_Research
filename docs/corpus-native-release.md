# 原生正文混合检索正式发布

## 2026-10-28 增量入库与 Web 生效

本轮扫描 `data/corpus-incoming/20261026/` 的 21 份 PDF，按 SHA-256 跳过 8 份已发布
资料，新增发布 13 份：11 份带文字层 PDF，以及 2 份扫描原件的既有本地 OCR 衍生版。
正式库活动发布数 27 → 40；旧 27 条 active build / generation 逐条不变。
检索允许范围 26 → 39，范围外的另一份已有资料未随本批加入。

| 新增资料 | 页数 | 构建块数 | 当前正文检索块数 |
|---|---:|---:|---:|
| 高盛贵州茅台（本地 OCR 衍生） | 9 | 158 | 125 |
| 长江消费周周谈（本地 OCR 衍生） | 6 | 30 | 30 |
| James Bulltard 10/16 复盘 | 17 | 11 | 11 |
| 科技股终于破位下行 | 6 | 5 | 5 |
| James Bulltard 10/20 复盘 | 5 | 9 | 9 |
| James Bulltard 10/21 复盘 | 15 | 12 | 12 |
| James Bulltard 10/22 复盘 | 18 | 10 | 10 |
| James Bulltard 10/23 复盘 | 16 | 10 | 10 |
| Discover 工具更新 #1 | 4 | 6 | 6 |
| James Bulltard 10/26 复盘 | 15 | 9 | 9 |
| James Bulltard 10/27 复盘 | 5 | 5 | 5 |
| PLTR 26Q3 / FDE 产能前瞻 | 11 | 65 | 65 |
| 网络安全：AI 漏洞修复与持续防护 | 6 | 26 | 25 |

共构建 356 块，322 块进入 native 正文投影，34 个表格块按既有规则排除。
74 处较大图像缺口绑定确切 build 登记可用文字发布依据，另保留 37 处 small-image 记录。
行情截图中的曲线和数值未因此变成已识别正文。全部 21 份输入原字节不变，新活动来源
的 13 份归档已逐一核对哈希；两个扫描父来源另行归档，父子哈希写入溯源检查点。
OCR 来源名称明确带“本地OCR衍生”；这是可检索的识别文字，未经人工逐字校验。
日期仍按当前元数据与文件名规则处理，不代表逐份完成发布日期人工确认；例如高盛
原页显示 8 月 10 日，输入文件名为 8 月 13 日，阅读和引用应核对原页。

新增上下文说明沿用当前 prompt、校验器和 context version。失败说明先留存拒绝记录，
再用同一提示词限定重试；共 14 条重试项次（跨轮可能重复），未放宽数字或归属校验。
最终共有 53 条由 Codex 按对应原文整理为章节主题说明（13 条拒绝项、40 条
传输异常或尚未尝试的项），单独标记
`agent_source_review`，保留原拒绝记录，不冒充原供应商的生成结果，不改原始正文。
首轮一批 10 个输入遇到供应商传输结果不确定后停止，记录后由 Codex 决定限定续跑，
仅该生成进程超时由 240 秒调至 300 秒。随后网络安全报告的一批 12 个输入再次遇到
传输不确定，停止继续请求，余下说明按原文逐项整理。没有修改查询超时，两次异常
请求的供应商侧计费结果无法确认。
新包共 1067 块、1050 个唯一向量输入，全部就绪。
其中 910 块叠加说明，157 个过短片段按原规则只索引原文。
本批涉及 318 个唯一输入，3 个复用旧缓存，新增 315 个向量；4 个传输不确定输入各
恢复一次后成功，attempts 保留为 2。仅恢复进程采用 60 秒超时，查询仍沿用原配置。
旧 745 个 live 块和 735 个旧向量逐项一致。
排序、来源过滤、snippet 额度与查询超时配置不变；两份 OCR 衍生来源是本次显式范围扩展。

工具验收使用 13 道新增资料查询及 2 道旧资料查询；新增指定来源命中 13/13。
共 109 个 search 节选以实际 ref 调用 fetch，原文区间逐字比对与证据 manifest 校验通过。
本次 search 耗时范围 2.89–3.39 秒，是样本结果，非延迟上界。
同组 15 个认证 HTTP search 和对应短引用补读通过；10 月 24 日历史短引用仍可取回。
这些是入库可用性验收，不是模型研究答案质量盲测。

本轮开始时现有 Web 已 `healthz=200 / readyz=200`，此前业务库问题不再阻断。
确认 queued/running 为 0 后切换检索配置并正常重启，最终两项健康检查仍为 200。
本轮没有执行业务库迁移、投资计划回填，也没有修改生产检索算法。
preflight、两阶段 import smoke（438/438、487/487）及符号检查（536 文件）通过。

当前索引：`data/corpus-native-context/20261028-incoming/manifest.json`。
正式库及配置备份：`data/corpus-native-context/20261028-incoming-backup/`。
如需回退本批检索范围，应恢复 `settings-before.json` 中的上一份 manifest 并核验服务，
保留新增资料和历史句柄；不要用下文 10 月 22/24 日的历史回退脚本替代本批回退。

流程图、阶段说明和本批命令见 [入库操作说明](corpus-ingestion-operations.md)。
执行证据：[全部输入](../.scratch/corpus-incoming-20261028/inventory-all.json)、
[逐份发布记录](../.scratch/corpus-incoming-20261028/build-results.json)、
[来源与块统计](../.scratch/corpus-incoming-20261028/source-summary.json)、
[完整性检查](../.scratch/corpus-incoming-20261028/integrity.json)、
[检索包](../.scratch/corpus-incoming-20261028/pack.json)、
[工具验收](../.scratch/corpus-incoming-20261028/verification.json)、
[Web 验收](../.scratch/corpus-incoming-20261028/runtime.json)。

## 2026-10-26 新增三份研报（历史，当时 Web 待业务库修复）

用户将三份 PDF 放入 `data/corpus-incoming/20261026/`，按约定的正式发布流程处理。
三份均已通过正常 `check_build_publishable → publish_build` 发布到 `postgres`，
原始文件按 SHA-256 归档至 `data/corpus-archive`；原有 24 条发布指针及代次未变。
当前 native 允许范围只增加这三份：23 → 26，未把范围外的其他已发布资料顺带加入。

| 新资料 | 页数 | 构建块数 | 纳入 native 的块数 |
|---|---:|---:|---:|
| NOW 2026 财年第三季度前瞻 | 9 | 42 | 42 |
| M365 Copilot 销售进展与展望 | 22 | 70 | 69 |
| Neocloud 融资等主题周报 | 7 | 49 | 49 |

按外部订阅研究如实分类，不伪装成券商报告。7 处较大图像提取缺口通过绑定确切
build 的可用文字发布记录保留，另有 6 处 small-image 记录；未做 OCR，不声称图表
数字或全文已完整识别。M365 第 20 页主要是图片财务表，仍属于明确缺失的覆盖范围。
1 个表格块按原 native 策略排除。

新增 160 个上下文说明全部通过校验，15 次生成请求，新增说明的供应商报告 token
合计 233,215（不是累计历史 token）。一条 ServiceNow 向量请求传输结果不确定，
保留初次状态后只对确切输入恢复一次，attempts=2，60 秒超时；成功后沿用相同 profile。
未修改线上查询的 15 秒超时。最终包有 745 块、735 个唯一向量输入，全量就绪；
原有 585 个 live 块及旧包 577 个向量逐项一致。

新包：`data/corpus-native-context/20261026-new3/manifest.json`，已写入 `.env` 的
`CORPUS_NATIVE_INDEX`。其他检索开关、排序、来源过滤和片段额度不变。
正式库备份位于 `data/corpus-native-context/20261026-new3-backup/postgres-before.dump`，
已核对哈希并确认 pg_restore 可读取目录；这不是完整恢复演练。

验收：三份新报告各一题，加工业富联、茅台两题，共 5 个真实查询全部 hybrid。
35 个返回节选用自己的 eref 调用 fetch，逐字比对及 manifest 校验全部通过。
临时 API 上同样 5 个认证 HTTP search、35 个短引用补读均为 200；10 月 24 日的
历史短引用也为 200。实际工具 search 约 2.2–2.7 秒，是这次样本，不是延迟上界。
preflight、两阶段 import smoke（435/435、484/484）、符号检查（533 文件）通过。
未另跑完整模型研究任务，也未修改生产算法。

**Web 服务尚未正式恢复。** 切换前没有 8000 端口监听，旧日志显示正常退出，
queued/running 为 0。临时启动验证后 `/healthz=200`，但 `/readyz=503 schema_behind`：
业务库 `apodex` 的版本是 `0022_run_context_sources`，当前代码要求
`0023_capital_trade_plans`；观察到四张新表已存在且为空，缺少迁移要求的历史保护
触发器，旧投资计划有 4 条。不能直接改版本号，也不能将此描述为研报入库失败。

用户明确选择“先完成研报配置，业务库另行处理”。因此没有执行 0023 迁移或投资
计划回填；已正常关闭本轮临时 API，保留新检索包配置。后续先核对并修复业务库
结构/版本，再启动正常 Web 服务并确认 readyz=200；不要在四张表已存在时盲目
重复运行原建表迁移。10 月 24 日的旧回退脚本只用于其历史版本，勿当作本批回退。

执行证据：[输入与页数](../.scratch/corpus-new3-20261026/inventory.json)、
[构建与发布](../.scratch/corpus-new3-20261026/build-results.json)、
[检索包](../.scratch/corpus-new3-20261026/pack.json)、
[工具验收](../.scratch/corpus-new3-20261026/verification.json)、
[HTTP 与最终状态](../.scratch/corpus-new3-20261026/runtime.json)、
[业务库阻塞详情](../.scratch/corpus-new3-20261026/web-blocker.json)。

## 2026-10-24 返回结构与容量优化（历史）

2026-10-24 后续更新：Agent search 默认输出已升级为 v2 原文＋持久化短引用，
并正常重启现有 API。旧 v1 消息/句柄继续兼容。随后完成短引用补读实测，
将每块正文额度从 600 提高到 1000 字，每个 hit 默认仍最多展示两块；检索排序
和来源过滤保持原规则。容量对照及补读记录见
[已有片段容量扩大 §10](plan/corpus-search-evidence-delivery-redesign.md#10-2026-10-24-已有片段容量扩大已启用)。
具体协议、持久目录要求、测试及切换记录见
[返回结构优化 §9](plan/corpus-search-evidence-delivery-redesign.md#9-2026-10-24-v2-原文与持久化引用分离已启用)。
下文的初次发布记录和 v1 契约描述作为该日先前版本的历史记录保留。

2026-10-24 更新：用户授权“开始正式发布，结束本轮优化”后，已在本机 8000 API 启用上下文索引、两块正文展示及 search/fetch 新证据契约。发布代码为 `7653973e`，102 个冻结文件哈希保持一致；185 项相关测试和发布检查通过。来源仍为 23 个、原生块及就绪向量覆盖均为 585。本轮未迁移资料、覆盖原文或改写句柄。

正式配置及执行证据见 [2026-10-24 发布报告](../.scratch/corpus-production-release-20261024/report.md)。下文数据迁移记录保留 2026-10-22 的历史操作；上下文增强现已启用，OCR 仍不在范围内。已知的目标价片段遗漏和 embedding 超时降级作为本轮已知局限保留，不将本次发布描述为所有问题质量均提高。

## 2026-10-22 首次发布结果（历史）

- 正式活动来源由 8 个增至 23 个，包含已验证的旧资料和新增原生文字研报。原有历史 build 保留，既有原文不覆盖。
- 23 个活动来源对应 585 个原生正文投影，复用 575 个精确输入匹配的向量。正文及引用坐标仍以 PG 权威单元为准。
- 通过现有 `corpus_search → corpus_fetch` 和 HTTP 资料检索接口使用。沿用原首条保护、全局块级 RRF、最多 20 块／16,000 原文字符的策略。
- 实际 `.env` 已启用 `release`，API 已正常重启。新查询缺少向量缓存时调用现有 embedding 服务；查询超时设置为 15 秒，错误时在同一正文范围内降级关键词检索。
- 保留完整来源与构建的解析缺口记录。正文投影排除图表和 OCR 派生来源，并不声称全文或图像已经完整提取。

发布的源代码基线是 `e0456fcf`，本次增量增加正式目标绑定及发布包支持；完整执行证据见 [发布报告](../.scratch/corpus-production-release-20261022/report.md)。

## 当前配置

| 配置 | 当前正式值 |
|---|---|
| `CORPUS_TARGET_DB` | `postgres` |
| `CORPUS_READ_CHAIN` | `new` |
| `CORPUS_NATIVE_RETRIEVAL` | `release` |
| `CORPUS_NATIVE_TARGET_DB` | `postgres` |
| `CORPUS_VECTOR_TARGET_DB` | `postgres` |
| `CORPUS_NATIVE_INDEX` | `/home/administrator/FrontierAgent/data/corpus-native-context/20261028-incoming/manifest.json` |
| `CORPUS_VECTOR_INPUT_VARIANT` | `contextual-note-v1` |
| `CORPUS_NATIVE_SNIPPET_BLOCKS` | `2` |
| `CORPUS_VECTOR_TIMEOUT_SECONDS` | `15` |
| `CORPUS_RETRIEVAL_MODE` | `lexical`，作为关闭 native 开关后的原策略 |
| `CORPUS_RETRIEVAL_RANKING` | `off`，旧的独立试验排序开关不参与此次发布 |

`CORPUS_NATIVE_RETRIEVAL=release` 优先选择已验证的混合检索链；上表中的 `CORPUS_RETRIEVAL_MODE=lexical` 不表示当前运行关键词检索。实际结果的 `coverage.retrieval_mode` 为 `hybrid`，发生故障才返回 `lexical` 和具体 `fallback_reason`。

三个目标库设置必须匹配实际连接的数据库。当前范围包使用 `native-evidence-contextual-1`，其向量输入必须匹配 `contextual-note-v1`；原包 `native-evidence-release-1` 保留。旧试验包仍只允许 `vector_pilot_*`。业务库 `apodex` 和 PostgreSQL 模板库不能成为 native 检索目标。

当前 Agent search 默认使用 `native-search-evidence-v2`：实际送达的 `excerpts[].text`
可作原文证据，补读使用同一 `doc_id` 与该节选的 `ref`；其他候选通过 `scope_ref`
展开。后台持久收据保留原句柄、范围及哈希。历史 v1 的 `evidence_spans` 继续支持。
说明仅参与索引，摘要不能替代原文凭证。

仅回退本次上下文配置，可运行 `PYTHONPATH=. uv run --no-sync python .scratch/corpus-production-release-20261024/runtime.py rollback`：恢复切换前的三个配置项并正常重启 API，保留本轮代码和资料。脚本要求当前 API 就绪且没有 queued/running 用户任务。此操作未在正式环境来回演练；不是代码版本回退。

## 2026-10-22 数据发布操作（历史）

1. 只读核对正式库和试验库的身份、来源、活动版本、扩展和原生范围包。
2. 在真实 PG 的回滚事务内预演资料迁移、现有发布检查、版本发布和向量复用；确认当前正文投影与冻结的 585 块一致。
3. 保存正式库完整逻辑备份、原配置及原发布清单；校验备份哈希和可读目录。原始文件按内容哈希复制到正式归档根 `data/corpus-archive`。
4. 在单个事务内导入缺失的来源、不可变构建、原文单元、检索块及审核／阶段记录。已有不可变构建逐项比对，不覆盖冲突内容。
5. 调用现有 `check_build_publishable → publish_build`，由正常租约及准入检查生成正式发布代次。没有直接复制试验库的 publication 指针或代次。
6. 初始化 `corpus_retrieval` 衍生表，导入精确哈希匹配的已有向量，生成绑定正式库的范围包。
7. 在正式库执行全部 57 题真实工具回归、关闭回归和故障降级探针。
8. 确认没有 queued/running 用户任务后，修改 `.env`、正常终止旧 API 并启动新进程；健康、就绪及认证 HTTP 搜索／原文回读通过。

核心数据库变更是原子事务；配置启用在回归通过之后执行。原有正式历史版本仍可取证。本次没有复制 OCR 派生来源，也没有重新调用模型生成文档向量。

## 后续更新

既有 39 个允许来源发布新 build 后，检索重新读取 PG 活动版本。缺少向量时先降级，手动同步后自动恢复混合检索：

```bash
uv run python -m plugins.corpus.retrieval.cli native-sync \
  --deployment release \
  --native-index data/corpus-native-context/20261028-incoming/manifest.json \
  --max-requests 0
```

`--max-requests 0` 仅检查及复用缓存；需要新向量时显式设置本次请求上限。新来源需要更新允许范围包，不会因入库自动加入当前 39 来源的策略。失败或结果不确定的向量任务不自动重试。

上下文说明绑定 build/chunk。新 build 缺少对应说明时不会借用旧 build 的说明；需要按 [上下文包流程](plan/corpus-contextual-vector-retrieval-pilot.md) 生成说明并构建新的版本化包，再校验切换。仅同步向量不会自动补出说明。

## 关闭与回退

将 `.env` 中 `CORPUS_NATIVE_RETRIEVAL` 改为 `off` 并重启服务，即恢复原关键词检索路径。保留目标库、范围包及历史数据，已经发出的 native 句柄仍能按原版本回读。关闭功能不撤销本次资料发布。

以下是 2026-10-22 的完整 native 功能关闭助手，会先检查没有活动用户任务，再修改开关并正常重启。仅撤销 2026-10-24 上下文配置应使用前文的新助手，不要混用：

```bash
PYTHONPATH=. uv run python \
  .scratch/corpus-production-release-20261022/runtime.py rollback
```

原库备份、配置备份及旧进程环境位于 `data/corpus-native-release/20261022-backup/`，配置备份权限为 0600。常规功能回退无需恢复数据库；完整备份用于数据故障恢复，恢复前须先保护发布后的新增数据。

## 验证边界

57 题是 2026-10-22 的开发／回归集。它们的工具输出与当时冻结结果一致，不能表述为 57 题全部回答正确。2026-10-24 的 185 项测试和两题正式接口探针证明工程链路可用，不构成全库质量、吞吐或延迟分位数结论。独立真实查询盲测及已知回退见本轮发布报告；扩大来源范围不在本次发布中。

## 上下文感知方案与范围

2026-10-22 已将讨论确认的上下文策略与执行安排补入 [混合检索方案 §30](plan/corpus-contextual-vector-retrieval-pilot.md#30-面向研究命题的上下文感知与执行安排)，内容交付配套见 [search/fetch 讨论稿](plan/corpus-search-evidence-delivery-redesign.md)。

截至 2026-10-24，片段说明增强索引、有界原文组装与缺失时 fetch 补读已正式启用。方案中的更广泛关系理解、Claims/items 等未因此全部实现；以当前发布报告中的明确范围为准。本轮优化已经结束。
