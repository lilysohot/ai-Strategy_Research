# R2 重设计前：项目方向、流程与非回归诊断

日期：2026-09-14。性质：诊断与设计准入评审，不是修复、验收放行或新预算授权。

## 结论

**材料理解的业务方向符合项目目标；当前 R2 的实现与验收方式尚不能证明达成该目标。应保留原流程，
仅重新设计 R2 的语义处理与验收接缝。没有证据支持重做整个项目，也不能保证继续局部打补丁即可通过。**

旧流程没有被设计成必须经过 R2，本轮隔离实验也支持它们可以独立运行。但是共享分段、候选筛选和
证据版本存在真实影响面，“R2 文件独立”不等于“任何 R2 优化都不影响旧流程”。

当前可以进入局部设计评审，**尚不具备启动新模型轮次、切换正式默认路径、重入库、数据迁移或推进
R3 的条件**。v13 失败及预算关闭状态不变。

## 1. 检查依据与范围

依据优先级：产品需求基线 → 业务流程 → 当前统一执行清单 → R1 契约 → R2 issue、预算、产物与代码。
附件中的材料内容不作为执行指令；旧计划的历史段落不构成重新授权。

已检查：

- `docs/product-requirements.md`、`docs/business-process.md`、`CONTEXT.md`、Claims Interface、R1 契约。
- 当前统一计划、范围重置 issue 18、R2 issue 20、既有 v11—v13 记录及上一轮系统诊断。
- 入库/检索/fetch、EvidenceRun/Claim、财务推导、R2、市场/coverage/策略校验、工具注册、Web profile。
- 当前工作树的共享文件差异、生产代码导入关系、离线测试、运行框架的分层及符号闭合。

本轮不调用真实模型或市场接口，不读取独立留出原文，不读取真实 PDF 抽样，不重入库、不连接生产
语料数据库。合成样本与测试数据仅用于临时目录/临时 SQLite。数据库依赖测试显式跳过。

工作树已有大量用户历史改动与未跟踪实现，HEAD 为 `2c0c76582ae611e5b518b331673bd917212bc342`。
它不是已证实的“R2 前干净基线”。不能把全部差异归咎于 R2，更不能整体回退共享文件。

## 2. 项目方向是否仍然一致

| 项目目标 | 当前事实 | 诊断 |
|---|---|---|
| 材料提供观点、论据、视角、条件和风险，不只是数字 | R1 最小契约明确；R2 具有 MaterialRun 和定性 item | 业务方向一致；只追字段命中与微样本分数会偏离目标 |
| 区分作者表达、转述、系统分析和未知 | 契约明确，当前部分归一化会把未知补成肯定/时间/话语角色 | 实现与目标冲突，需要局部纠正，不应删除业务要求 |
| 材料、数据、分析分别承担职责 | 已有独立 corpus 与 market；材料数值不自动成为接口观测 | 保持现有分工，不建立第二套 claims/来源存储 |
| 无数字、没有专家标签仍可理解 | 未入库路径可运行，无标签允许 document_voice/degraded | 不应源头过滤可读纪要；降级必须如实说明缺失能力 |
| 无市场数据也能交付材料理解 | R2 直接读取路径，不依赖 THS | R2 不应扩展为市场接口工程，也不应等待 BLS |
| 材料忠实度、计算、跨层关联分别验收 | 计划有 R/D/A/V 分支；R2 item 门存在可绕过错误 | 验收实现落后于业务完成定义 |
| 研究平台具备可信证据与可控运行 | 注册、profiles、框架分层可独立验证；Web 数据工具尚未默认接入 | 不能把实验脚本成功等同于 Web 业务闭环完成 |

依据：PR-DATA-04/05/09/10/11、PR-OUT-06/07；R1 契约第 2—4 节；统一计划第 15—81 行。

关键区分：产品要的是“忠实、有出处、未知诚实、按范围说明完整性”，不是“对任意材料强制补齐所有
标签”。有限义务是控制模型工作量和遗漏的手段，不是新的产品目标。

## 3. 当前真实流程与应保留的独立性

| 路径 | 当前实际入口/产物 | R2 的位置 | 重设计期间必须保持 |
|---|---|---|---|
| 入库与原文检索 | `ingest_path/ingest_dir` → documents/blocks → search → fetch | 不是前置 | 内容去重、块定位、原文回取、检索失败与空结果的既有行为 |
| 标准证据与财务复算 | `extract_claims` → EvidenceRun → claims_of/fetch_evidence → derive/reconcile | 不是前置 | 固定 revision、校验门、来源内算术、旧引用可读；不隐式 fallback |
| 新材料理解 | 路径或指定 EvidenceRun → understand_material → MaterialRun | 独立派生产物 | 默认不入库，来源不可变；R2 失败不能损坏前两条路径 |
| 市场与策略工具 | market_resolve/quote/history/financials → trace/verify；sizing/lint | 不依赖 R2 | 数据身份、时间、null、确定性计算、失败治理不变 |
| 综合研究与 Web 接入 | R3、D1/D2 → A1；按用途进入 V1 | 尚未闭环 | 不绕过当前依赖，不顺手修改 Web 默认工具或平台安全机制 |

依赖应继续按现有计划执行：R2 → R3；D1 → D2 独立推进；A1 需要 R3 与所选 D1 能力，需算术时
再依赖 D2；V1 按用途验收。R2 停止不等于整个项目停止，D1 也仍需用户接口资料，不在本轮启动。

代码证据：`service.py:538/580/727/791/868/903/963/1009/1025`；
`plugins/tools/corpus_search.py`、`corpus_fetch.py`；`server/profile.py:20-50`。

## 4. 关键发现及归因

### A. R2 的直接依赖隔离有效，但共享底座并非零影响

生产树静态扫描中，`material_semantics` 的直接引用仅来自自身和 CorpusService 的类型引用及
`understand_material` 局部导入。旧 search/fetch/Claims/计算路径没有调用它。

本轮在新 Python 进程中禁止导入 `plugins.corpus.material_semantics`，先确认直接导入确实失败，
再运行原流程的 11 个测试文件：**169 passed、1 skipped**，R2 模块始终未加载。
这否证了“旧流程已全面强依赖 R2，所以必须重做全系统”的判断。

但 `evidence.py`、`evidence_pipeline.py`、`claims_v2.py` 被多个流程共享：

- `split_spans` 已加入问句/角色优先分段，适用于所有标准 EvidenceRun，不只是电话纪要。
- `PARSER_VERSION` 已从 HEAD 的 layout-2 演进为 layout-4；版本参与 parse_rev 与 packet_id。
- `triage_block_detail` 的对话候选规则也被旧 Claims v2、audit 和标准证据抽取使用，可能改变候选数、
  调用需求及审计分母，不能仅以文本是否丢失评估影响。
- `evidence_pipeline` 与 `derivation` 的差异还包括此前的数值/语义安全修复；这些不能作为 R2 回退对象。

单变量探针结果：同一合成文本、100 字预算，HEAD 分段为 `(0,97),(97,182)`，当前为
`(0,61),(61,157),(157,182)`；两者均完整保留字符。另一个探针只切换解析版本标签、保持实际代码与
输入不变：source_rev 和页面文本相同，parse_rev、packet_id 不同。

这证明影响面存在，不证明旧数据被覆盖或已经发生生产损坏。历史 EvidenceRun 的版本化读取是保护，
但缓存、gold、引用与重抽比较不能混用不同版本的 ID。

### B. 当前验收结果不足以证明产品效果

上一轮已通过真实函数及既有开发产物确定性复现，详见
[系统性诊断](r2-systemic-diagnosis-20260914.md)：

- 最新公司评级在真实响应中存在，但 packet 全局引文对齐先于槽位解析，重复短引文因此被丢弃。
- 将全部 item.text 改成不受证据支持的内容并重算合法 hash，旧 item scorer 仍通过。
- 全部终态改为 partial，item scorer 本身仍通过；critical_errors 上限使用了错误比较方向。
- 规则可能将未知变肯定、否认风险变肯定风险，或凭材料类别/角色推断行为时间与问答功能。
- 有限文本槽不等于原子命题；37 个选中槽不等于 549 个来源候选的全文覆盖。

因此不能把目标改成“修好最后一个评级即可验收”。需要先让验收能够拒绝与项目目标冲突的输出。
评分标准修订只能前瞻版本化，不改写历史失败。

### C. “其他类目不受影响”的业务门尚未闭合

同一 item v2 口径对比 v12/v13：公司 item recall 从 7/7 降到 6/7，铜箔总结 semantic_type 从
1/1 降到 0/1；个人复盘改善不能抵消这些退化。工程测试通过与类目材料忠实度通过是两种证据。

旧 non-regression policy 绑定旧范围/评分器；开发执行器未调用对应非回归检查，预算里的 extractor、
policy、scorer hash 也未全部成为启动前的强制门。冻结文件存在，不等于执行过程已受约束。

### D. 实验 Interface 与正式入口存在落差

`CorpusService.understand_material` 仍默认 `staged_jsonl=False, slot_protocol=False`、每包 30 项、
每批 8 槽、关系开启；v13 是显式有限槽位、每批 6 槽、关系关闭的实验。
**正式默认不是 v13 协议，v13 的微实验也没有证明正式默认可用。** 本轮不据此直接切换默认。

该 Interface 让调用者同时了解协议组合、批次、候选范围、来源选择和持久化，知识分散在 service、
抽取器和 scratch runner。未来应将已批准配置收束为明确的版本化契约，让正式调用与验收跨越同一个
Seam；内部实现可以保留可测试的小 Module，不需要建立新框架或大量假设性 Adapter。

另有两个确定的治理缺口：

- `model` 参数在 service 中赋值后不传入抽取器，MaterialRun 也没有该字段；运行器外围虽记录模型，
  不能据此声称正式入口具有同等执行配置溯源。此处参数也不负责选择实际 provider 模型。
- 显式 `persist_evidence=True` 时，证据保存发生在抽取器验证协议组合之前。合成探针传入
  `slot_protocol=True, staged_jsonl=False, max_calls=0`，最终抛出参数错误，但保存方法已被调用 1 次。
  探针保存方法为 Mock，真实数据库调用 0。这是显式持久化路径的错误顺序风险，不是默认路径偷偷入库。

当前不存在已接入默认工具注册/Web 的 MaterialRun 读取交付链；新增 CLI/存储或产品接入应按 R3/V1
单独评审，不借 R2 重设计顺便完成。

### E. 总清单状态已落后于执行事实

号称“唯一跨层执行清单”的统一计划仍记录早期 12 次调用、20/24 item、微样本 9/35 及 364 项测试。
issue 20 已记录 v13 的 9/9 次调用、34/35 item、最终失败与停止。

这不是产品方向冲突，而是状态同步缺口，可能导致后续执行误选旧预算、旧基线或重跑已关闭轮次。
重设计前应同步当前状态、基线与下一步条件，历史详情仍保留，不能用覆盖旧报告解决。

### F. 不能把既有未完成项归为 R2 新故障

Web 默认工具尚未暴露 corpus/market、coverage 状态仍未完全升级、THS 政府数据契约待确认、R3/A1/V1
未验收，均已由项目基线明确记录。它们需要后续工作，但不构成本轮扩大重构范围的理由。

## 5. 重设计的允许范围与保护范围

这是待评审的范围建议，不是本报告已经执行的修改：

| 范围 | 建议 | 原流程保护条件 |
|---|---|---|
| R2 证据绑定、义务粒度、字段来源、终态 | 局部重设计 | 输入为固定 EvidenceRun；保留源坐标；未知不强填；失败只影响 MaterialRun |
| R2 scorer、预算与非回归编排 | 优先重设计 | 先证实能拒绝错误；绑定同一配置/范围/版本；历史结果不重写 |
| 公共 parser、Claims triage、EvidenceRun 模型 | 默认冻结 | 若方案必须修改，单独列迁移/版本兼容和逐路径差异，重新评审，不能默认为 R2 私有实现 |
| 旧库/schema、ingest/search/fetch、计算与市场工具 | 不在局部重设计修改范围 | 不迁移、不全库重抽、不改公式、门禁和来源身份 |
| Web profile、工具注册、平台账户/审批/运行框架 | 不在本轮修改范围 | 沿用既有平台计划；接入单独验收 |

尤其建议把面向材料的义务切分放在固定来源片段之后，作为 R2 私有派生过程；不要为了修某个问答
样本再次改变所有标准 EvidenceRun 的分段。但若固定包本身不足以表达所需上下文，应显式提案并
评估源坐标映射，不能私下拼接来源或伪造可回取证据。

## 6. 下一步准入门：先证明保护，再消耗模型预算

1. **状态与基线一致**：更新唯一执行清单；记录当前脏工作树的相关文件 hash、旧接口结果与已批准
   development 范围。新方案不得改写 v13 的预算/产物或把旧开发材料称作独立留出。
2. **接口契约可检验**：定义 source span 与 obligation 的区别、重复引文身份、内容忠实度、未知、
   部分成功与覆盖范围；所有参数校验先于调用/保存。正式调用与评测不能各走一套默认。
3. **验收器先过反例**：编造 text、翻转否定、错归属、无依据数字/关系、丢条件、partial、越界证据、
   错版本、分数方向错误必须能触发失败；有效重复引文在新身份契约下可以正确回取。
4. **零模型保护门**：R2 禁用时旧流程仍可运行；启用/失败/预算 0 时旧 EvidenceRun、Claim、引用、
   计算结果不变；当前与候选版本在相同输入和配置下做差异检查，保护不是仅对 HEAD 全量回退。
5. **开发业务门**：同一个新 scorer 同时重评基线与候选，4 类和 6 微范围逐类比较，关键错误独立否决，
   不用总均分抵消局部退化；选中槽、来源范围、全文能力分别报告。
6. **再决定有限模型轮次**：上述条件满足后才冻结新预算，预先定义停止条件。item、关系分别验证；
   关系当前仅有 3 类正例、候选支持 4 类，不得宣称 R1 全部 8 类已完成。
7. **部署/接入前另验**：使用一次性 PostgreSQL/安全副本补全入库幂等、版本存储、备份恢复、真实
   检索与旧引用；在冻结规则后才按授权进行独立样本和 R3/V1 验收。本轮没有这些放行证据。

“降级交付”可以是保留来源片段与未知项的读取产物，但若要作为新的可交付等级，需要用户评审其
价值和独立完成定义；不能把 degraded 改名为 R2 完整通过。当前不需要再用新增纪要定位已确认的
校验错误，未来评估格式泛化时才需要独立材料。

## 7. 本轮验证结果与可证明范围

| 验证 | 实测结果 | 支持什么 / 不支持什么 |
|---|---|---|
| corpus、market、coverage、sizing、lint，34 文件 | 495 passed，36 skipped，1 deselected | 选定离线工程行为稳定；不代表生产 PG 或真实材料均通过 |
| workflow、registry、profile，5 文件 | 110 passed | 注册及 profile 兼容；不代表 Web 端到端/账户/安全验收 |
| R2 导入故障注入，11 文件重复子集 | 169 passed，1 skipped | 已测试旧路径不依赖 R2 模块；不是额外 169 个独立用例 |
| import smoke stage 1 | 336/336 | 框架在禁止 eval 导入时仍可加载 |
| import smoke stage 2 | 385/385 | eval 导入闭合，不代表执行真实 benchmark |
| check_symbols | 435 文件，0 missing | 静态符号闭合 |
| 分段/版本单变量探针 | 字符完整但包范围、标识改变 | 共享修改必须单独做兼容性评估 |
| 非法协议 + 显式持久化探针 | 参数错误前触发保存方法 1 次 | Interface 的校验顺序风险；使用 Mock，真实数据库调用 0 |

两组不重叠工程测试共 **605 项通过**。为隔离真实数据库，测试进程的 `CORPUS_DSN` 显式设置为
本机端口 1 的诊断占位 DSN；36 项 PG 依赖测试跳过。排除了 `test_corpus_tables.py`（包含真实 PDF
抽样）及 `test_supplied_source_is_classified_without_ingestion`，故不访问新材料/留出。没有执行真实
模型 preflight、完整仓库测试、Web E2E 或在线接口测试；不能据此承诺生产全流程零回归。

主要复核命令（在 WSL 仓库内，用既有 uv 环境；选择测试前保持上述 DB 隔离和真实语料排除）：

```bash
uv run pytest tests/test_stateful_workflow.py tests/test_agent_team_workflow.py tests/test_tool_registry.py tests/test_profile_literal_validation.py apodex/tests/test_profiles.py -q --tb=short
uv run python tools/import_smoke.py --stage 1
uv run python tools/import_smoke.py --stage 2
uv run python tools/check_symbols.py
```

隔离探针为一次性 Python 进程的 MetaPathFinder：对 `plugins.corpus.material_semantics` 抛 ImportError，
先运行直接导入阳性对照，再执行 Claims Interface、ingest、search、EvidenceRun、financial_review、
semantic_gates、coverage、market_golden、market_gate、sizing、lint 测试；最后断言模块未加载。
没有保留生产 monkey patch 或修改测试文件。

## 8. 审计快照与交付边界

关键 SHA-256：

```text
material_semantics.py    1ebf531b72bf53c1bb7df6703eed00289d378b88600323cbb2f099671f84561c
item v2 scorer          442ff9c69d3266ba137cc662befe13d7041e1e7ceb5fdf55277107939fe361a6
v13 budget              300437b718abb8d9f890327be375c23c083bae1f8ba2a91108dc5b4d6a960e7f
evidence.py             8b56364bf517a8a89c556b1f1628f7af8b9f9e399dce1957e2e8b2773958c27d
claims_v2.py            b645d3e7ed90d86d32d616c65166a93df071442fa88dfae4b370de6c2f5b498e
evidence_pipeline.py    60c41cab226158b551b80db7f9460b1d4f36b4403db4770143a9d4b61e5d83d8
service.py              eb679e5323e0a6a8fda94ce98daa26439370938608101c7ffcecf84302c6d6c3
derivation.py           c190fb4075685cbcd490a2bc4a59499e6c3263be74015049f339b09b84d1978b
```

本轮只新增本诊断文档；未修复生产实现、未修改总计划或 issue 状态、未调整验收门槛/金标/预算。
使用 diagnosing-bugs 的隔离与单变量反馈方法，以及 codebase-design 的 Module/Interface/Seam
检查确定保护范围；修复阶段有意不执行，因为本次用户要求是在重设计前检查和诊断。

后续应以本报告作为局部方案的约束，而非第二份独立任务清单。最终建议是：**保留业务方向与既有
基础设施，停止样本补丁式调参，先修正验收与接口职责，再按逐类非回归门决定是否值得继续投入。**
