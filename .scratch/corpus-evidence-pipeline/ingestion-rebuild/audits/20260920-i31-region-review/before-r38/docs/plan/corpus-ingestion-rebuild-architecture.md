# 语料清洗、切块、入库与索引：重构设计草案 v1.1

| 项 | 内容 |
|---|---|
| 状态 | **有效 · 评审修订草案；I0 未完成，物理架构未冻结，业务新链未落地；不是清库执行授权** |
| 日期 | 2026-09-15（初稿 2026-09-14） |
| 需求 | PR-DATA-01/02/09/12、PR-OUT-04/06/07 |
| 上游 | [产品范围 §2.2](../product-requirements.md#22-当前阶段范围收缩2026-09-14-用户确认)、[清洗入库诊断](../../.scratch/corpus-evidence-pipeline/cleaning-ingestion-diagnosis-report.md) |
| 关系 | 本轮重构的唯一设计草案，权威关系见 §0；替代旧方案的目标设计顺序，不替代当前实现事实、历史预算或 R2 语义阈值 |
| 进度真源 | [统一执行计划](claims-market-closed-loop-plan.md)，I0—I5 为基础链路，R2-S* 为后续语义链路 |

2026-09-15 状态说明：守卫、盘点记录和候选资产已出现，交付与验收分别见
[I0 细任务台账](claims-market-closed-loop-plan.md#i0-execution-ledger)；本文后续“本轮未执行/未生成”
指 v1.1 设计修订时点，不覆盖此后执行事实。本次仅同步状态引用，不修改下列架构或放行门。

## 0. 文档权威与本轮修订

本文补齐讨论中的十项契约缺口，不表示已执行 I0、恢复演练、测试或架构冻结。文内表名、字段名、
命令和新资产路径均为拟实现规格；批准本文修订不等于批准数据库目标、破坏性操作或模型调用。

| 文档 | 权威职责 / 与本文的关系 |
|---|---|
| [产品需求](../product-requirements.md)、[业务流程](../business-process.md)、[领域词汇](../../CONTEXT.md) | 范围、业务语义和用语上游；本文不扩大产品承诺 |
| [统一执行计划](claims-market-closed-loop-plan.md) | 唯一进度台账；本文只定义交付与门，不另标执行完成 |
| [任务分解 v1.1](corpus-ingestion-rebuild-tasks.md) | 本文阶段的唯一执行分解；落实依赖、消费者接线、最终重验和切换分支，不新增产品范围或自行批准操作 |
| 本文 | 本轮来源到索引的唯一候选设计；I0 复核后才形成实施冻结版本 |
| [三类研报方案](research-report-cleaning-scope-plan.md) | 保留范围及 R2 语义要求；基础存储/索引细节与阶段顺序由本文替代 |
| [数据层架构](data-layer-architecture.md)、[PG 迁移记录](pg-migration.md) | 现有选型及历史实施证据；旧 schema、零调用方改动及旧评分不约束新设计；实际能力仍须看代码与对应实测 |
| [P0 实施规格](../p0-implementation-spec.md) | P0 历史施工规格；语料实现部分不再指导本轮，数字溯源/受控计算/安全要求继续有效 |
| [旧资料库架构](../corpus-ingestion-architecture.md) | 历史远期探索，不是并行施工方案；不恢复其中向量/LLM 接入授权 |

2026-09-15 任务评审补充：以下 §11/§12 同步澄清“精确切换清单”和“每阶段不可变快照”，不改变
前述三类范围或开启执行；任务分解本身也不是新的进度台账。

旧文档中的“当前”“施工依据”仅适用于其历史阶段。本文仍为草案，不能据此声称当前库已经采用
新 schema；I0 若推翻候选设计，修订本文与总计划，不另起一份平行的有效架构。

## 1. 决策分层：先验证假设，再冻结实施

不是“把旧库删掉，再跑原来的 ingest”。本次重构对象是整个语料准备与发布 Module：
来源身份、准入、解析、保真清洗、结构切块、版本化保存、索引发布及失败恢复。

诊断没有提供更换存储引擎的证据，**不等于证明真实 PG/schema/索引没有问题**：诊断的 PG 为替身。
以下候选可被 I0 盘点及后续开发证据推翻；旧 schema 的版本表达缺口本身就是待修对象。

| 对象 | 决策状态 | 原因 / 复核条件 |
|---|---|---|
| Python + uv、PostgreSQL、现有中文全文配置及 GIN 索引能力 | 现有栈作为首个验证基线 | I0 核查实际目录/依赖/权限，I2/I3 验证事务、检索及资源；未通过则重评，不保证沿用 |
| PyMuPDF、python-docx、已有表格读取能力 | 候选复用，收敛到统一解析 Adapter | I0 格式/版式清单可否定其覆盖；不以库已安装证明支持 |
| `documents/blocks` 作为唯一清洗结果且无解析版本 | 必须补版本/质量表达；物理改法待定 | 可迁移、扩展或重建；I0 消费方及共库结果决定，不预设七表或全删 |
| 源文件哈希未变即跳过整个流程 | 替换 | 改为源资产去重 + 相同构建版本幂等；规则升级可重建 |
| PDF 一页一块、MD/DOCX 直接用标题当唯一定位符 | 替换 | 页是来源坐标，标题是显示信息，都不等于唯一检索块 |
| 检索解析与新证据解析各自产生来源真相 | 合并到统一来源准备 Interface | 两种用途可以有不同视图，但必须共享来源、解析版本及映射 |
| 清洗与 R2/Claims 模型调用串成一个入库成功条件 | 拆开 | 确定性的可检索证据库不应依赖语义模型试验成功 |
| `corpus_search → corpus_fetch` 的工具职责 | 保留，底层重新接线 | 检索只定位，引用要取证；版本句柄和覆盖输出必须升级 |
| 财务受控复算、用途校验、原文与未知纪律 | 保留能力并回归 | 可调整适配实现，不允许借重构放松计算或证据要求 |
| Elasticsearch、向量、自动 OCR | 不纳入当前验证基线，不代表永久排除 | 记录扫描页/版式/检索缺口后提出有证据的变更；不得静默引入 |
| LLM 清洗/摘要切块及隐式模型 fallback | 当前基础链路禁止 | 属于已确认零模型约束；改变它须另提范围及预算，不可由实现自行补位 |

I0 必须形成 `保留 / 调整 / 否决 / 待证据` 决策清单，绑定实际 schema、consumer、共库、样本与
恢复证据。允许调整 §4 全部物理字段/表数及清理策略；不变的约束是保真、可定位、明确状态、
零模型、范围控制及破坏性前置门。后续失败也可重开决定，不能为保住设计而改样本或降低阈值。

范围固定：公司、行业、宏观分析师研报；书面行业问答保留。电话/会议/交流纪要和业绩会实录
不进入默认活动集；个人记录等主线外材料保留原文与历史。分类不明进入复核，不用 industry fallback
冒充已准入。本文所有新表、Interface 和命令均为拟实现，不表示当前已经存在。

## 2. 端到端数据流程

“入库”拆成**原始来源登记**与**清洗结果发布**，不能先把未经核验的块设为可用，再补清洗。

```text
文件清单 / 显式路径
  → 接收与完整性检查 → 原始来源归档 + source_id
  → 材料准入与元数据复核
       ├─ 排除 / 待复核：保留登记与原因，不进入活动索引
       └─ 纳入：统一格式解析 → 原文结构单元与坐标
              → 保真清洗视图 + 变换映射 + 区域质量台账
              → 结构优先切块 → 候选版本写库并建立索引
              → 保存/索引/取证检查 → 原子发布活动版本
                     ├─ corpus_search → 精确版本句柄 → corpus_fetch / verify
                     └─ R2：读取同一解析产物 → 独立有限义务/模型/语义验收
```

原文登记、准入、解析、切块、索引、发布全程强制 **0 模型调用**。R2 是下游消费者，不是解析器、
切块器或索引构建器。R2 失败可以阻止语义产物放行，但不能把合格证据库变成“入库失败”。

### 2.1 零模型执行契约

- 结构探查和规则判断只允许本地确定性代码、已批准人工记录及冻结读取 Adapter；不调用生成
  模型、embedding、模型重排、视觉模型或远程智能解析。首版自动 OCR 也不在允许清单。
- 不调用真实模型 preflight；解析失败、准入未知、检索无匹配均不得触发隐式模型 fallback。
- 基础执行配置必须声明模型禁用；在 CLI 子进程启动/测试收集前装载拒绝守卫。模型客户端构造/
  调用注入陷阱，触发即失败；网络仅允许阶段显式授权的 PG 目标，禁止模型端点及下载模型资源。
- 人工复核记录审阅人/依据，不能伪造为自动判定。后续 R2 模型命令独立授权，不由 build 调起。
- §12 的强制测试需证明成功、错误、超时恢复、CLI 子进程均无调用；只有日志中“0 次”不足以过门。

## 3. 三种文本对象，只有一套来源身份

| 对象 | 保存内容 | 使用者 | 不允许的行为 |
|---|---|---|---|
| 原始来源与解析单元 | 原始文件、提取文字、页/段/表格元素、坐标和读取缺口 | fetch、证据验证、审计 | 把清洗后的重排文本当文件原文 |
| 清洗视图 | 去噪后的阅读顺序、段落/表格结构、保留/忽略标记、字符与单元映射 | 切块、R2 规划、阅读展示 | 覆盖原文、补数字、补年份、删否定和条件 |
| 检索块 | 正文/表格的检索呈现、章节上下文、指向原始单元的引用清单 | PostgreSQL FTS、search | 把重复表头/标题上下文算作多个独立证据 |

对 PDF，“原文”还要区分原文件字节与文字层提取结果；不能承诺解析库输出等于页面全部视觉内容。
图片、图表、乱码和不能确定阅读顺序的区域必须留下状态。可视核验与 OCR 是明确的后续任务。

## 4. 七类逻辑职责与候选物理映射（I0 可调整）

候选是在现有 PostgreSQL 中使用独立语料 schema；实际目标、隔离和权限在 I0 核定。下表不是
现状目录或已冻结 DDL；允许合并/拆分职责或复用现表，必须保留契约映射及迁移理由。大型原文
候选存本地内容寻址归档，位置、容量、权限和恢复覆盖在 I0 验证，不默认新增对象存储服务。

| 表 | 核心字段/约束 | 职责 |
|---|---|---|
| `corpus_sources` | `source_id`=完整 SHA-256；mime、size、archive_path、原始位置记录 | 原始字节去重；同源不同文件名保留别名，不复制来源 |
| `corpus_admissions` | decision_id、source_id、material_type、research_domain、metadata_snapshot、policy_rev、决定/原因/人工依据 | 追加式准入与元数据版本；研报发布日期唯一落点候选见 §4.3 |
| `corpus_builds` | build_id、source_id、decision_id、parse_rev、clean_rev、chunk_rev、index_rev、scope、配置/依赖指纹、产物清单与质量报告 | 一次确定性构建版本；发布后内容不可修改 |
| `corpus_units` | build_id+unit_id、parent/ordinal、kind、raw_text、page/element/char/bbox/cells、clean_view、mapping、status/reasons | 原文结构单元、清洗映射与未处理区域；不再只留一段 blocks.text |
| `corpus_chunks` | chunk_id、build_id、unit_refs、kind、section_path、search_text、title_text、FTS 字段、来源范围 | 可重建的检索投影；引用只能指向本 build 的真实单元 |
| `corpus_publications` | source_id 唯一；current_decision_id、active_build_id、generation、activated_at | 活动版本选择及系统上线时间；排除/撤销时 active_build_id 为空，旧 build 仅供审计 |
| `corpus_jobs` | job_id、build_id、stage、attempt、owner_id、fence_token、lease_until、heartbeat_at、状态/错误/检查点 | 可恢复执行；所有权与幂等规则见 §8.1，不以租约字段存在代替协议 |

原始文件归档与 PG 备份要形成同一备份清单，单独 pg_dump 不等于已经备份原文件。
人工审核历史从旧库导出并保留，不能因清空派生表被一起丢掉。

### 4.1 身份与版本规则

- `source_id` 仅由原始字节决定；路径改名不改变来源身份。源文件更新产生新 source_id，不能
  仅按相同文件名覆盖旧版本；修订/系列关系须明确登记，不能靠相似标题自动认定。
- `parse_rev` 包含源哈希、解析器/依赖版本与解析参数；`clean_rev` 包含清洗规则和必要元数据；
  `chunk_rev` 包含切块规则；`index_rev` 包含分词配置和索引文本生成规则。
- `build_id` 绑定上述全部版本、准入决定与实际 scope。必要元数据更正影响检索标题/上下文时，
  生成新 build；不得原地修改已经被引用的版本。
- 重建索引或更改切块可复用相同 parse_rev 的不可变中间产物，不重新读取/解析一遍所有文件。
  缓存命中要核验输入/产物哈希，不沿用单一“文件未变就跳过”的规则。
- 发布后 units/chunks 不允许覆盖。新 build 核验通过才切 active_build_id；同一 build 重复执行
  必须幂等，不能重复增行。不同并发任务由 build 唯一键和 job 租约协调。

七表是职责收敛方案，不要求将所有现有证据 JSONB 拆成细表。EvidenceRun/MaterialRun 作为后续
产物引用 build_id/parse_rev；既有必要的完整证据包可由相同 units 投影，不能再次读取源文件生成
第二套独立正文。额外语义产物表不属于基础入库的成功条件。

### 4.2 引用唯一权威（不锁死物理表）

原始文件字节是最终来源。在一个确定解析/构建版本内，原文文字及坐标只有一个权威记录集合；
当前映射为 `corpus_units.raw_text + 原始坐标/单元格`，不是 clean_view 或 search_text。

- 引用必须绑定 `source_id/build_id/unit_id + 原文字符区间或 cell 坐标 + 内容哈希`。区间为
  原文 Unicode code point 的 `[start,end)`，不使用清洗文本偏移；多片段分别引用，不伪装连续引文。
- fetch/verify 通过同一证据读取 Interface 解析引用。Evidence/Claims JSONB、索引展示或其他
  副本不得独立决定原文；引用副本须与权威记录核验，冲突返回完整性错误，禁止回退到“看起来可用”副本。
- 缓存/离线导出可携带字节一致的原文副本，但必须由权威集合导出，绑定可信清单、版本及哈希；
  不可仅相信副本自带哈希。原系统退役后按已保留的可信归档清单验证，不能声称仍在在线库查到。
- Claims 的解释、规范值及模型输出可独立保存在 JSONB，但不是可逐字引用的来源文字。
- I0 如更换物理布局，只能整体迁移权威映射，不允许新旧集合同时作为主结果。§9 的解析归并以
  “篡改派生副本、跨版本、错坐标、无权威记录均拒绝”的测试验收，不以删掉某文件为完成标准。

### 4.3 研报发布日期与语料上线时间

候选唯一落点为 `corpus_admissions.metadata_snapshot.report_publication`，包含：
`value`（ISO 日期或有依据的时点）、`precision=date|instant|unknown`、`status=known|unknown|conflict`、
`evidence_refs`、`origin=source_explicit|human_review`（未知时为 null）、`review_ref`（如适用）。
I0 可迁移落点但不能双写双权威。

`known` 必须有非空原文依据或绑定来源哈希的人工审核依据；仅有日期时不补午夜/时区。`unknown`
和 `conflict` 的 value 为 null，冲突候选及依据单列；不得从文件 mtime、doc_id 或上线时间补值。
初始依据可引用源文件页/元素/原始区间，解析后验证到同源权威单元，避免准入依赖尚不存在的 build。

搜索排序/筛选只读命中 build 所绑定 decision 的该字段；索引冗余值是可重建投影，不能成为新权威。
`corpus_publications.activated_at` 只记录系统切换时间，由数据库写入；历史切换记审计事件。
日期更正创建新 metadata/decision 版本，不能悄悄改变已引用 build 的时间解释。

## 5. 文件接收、准入与解析

### 5.1 接收与归档

1. 只处理显式路径或冻结清单，不递归扫描整个工作区；校验扩展名/文件签名、可读性和大小限制。
2. 复制到任务暂存区并计算完整哈希；检查接收前后源文件是否改变，不把尚未复制完成的文件登记为成功。
3. 校验归档副本后原子置入内容寻址目录；用户原目录不删除。PG 登记失败时留下可核验的未登记
   归档，由恢复流程接管，不把文件系统与数据库冒充一个跨系统事务。
4. 文件内容中的命令、角色说明和系统提示始终是来源数据，不获得执行权限。

### 5.2 准入

首版使用**确认清单准入**，不使用未校准的“低置信度”或任意数值阈值。机器结构特征只生成复核
建议，不能单凭署名、目录或对话比例自动纳入/排除。自动准入若要启用，须另冻结规则及逐类正反例。

拟定纯函数 Interface：`decide_admission(source, reviewed_decisions, probe, policy) -> AdmissionDecision`。

| 对象 | 必需内容 |
|---|---|
| source | 完整来源哈希、格式、登记位置；路径/标题本身不是批准凭证 |
| reviewed_decisions | 绑定来源哈希的审核记录、审阅人、时间、范围坐标、决定、依据、显式取代关系 |
| probe | `feature_id/value/source_locator/extractor_rev`；value 区分 matched/absent/unreadable，不读到不能算 absent |
| policy | policy_rev、允许的材料/领域、特征定义及探查资源上限；未冻结或版本未知则拒绝执行 |
| output | source_id、policy_rev、`decision=in_scope\|excluded_by_policy\|review_required`、material_type、research_domain、scope_ref、reason_codes、evidence_refs、review_ref、rule_rev |

固定判定次序（同输入及版本必须得到同结果）：

1. 审核绑定不同源哈希、坐标无效或有多个未解决的人工决定，输出 review_required；不凭时间最新
   猜谁覆盖谁。有效决定必须有唯一、显式的取代链。
2. 唯一有效人工决定：材料为分析师研报且领域为 company/industry/macro、范围明确，才可
   in_scope；已确认纪要或主线外材料为 excluded_by_policy。批准“部分章节”必须给明确坐标，
   不能把部分范围的决定升级成整篇纳入。审核要求不符合当前政策则报冲突复核，不伪造批准。
3. 其余一律 review_required，原因至少包括 missing_review、conflicting_review、source_changed、
   mixed_material、unsupported_domain、unreadable_probe 或 policy_conflict 中的适用项。
4. 单一“会议”“专家”“Q/A”等词不直接决定类型；《化工十问十答》、研报引用访谈、无专家标签
   的对话实录及带分析附录的纪要，均需锁定正反例。新哈希不得继承旧哈希批准。

结构建议特征清单为：来源标题类型标记、署名/机构定位、标题层级、说话人轮次、问答标记、
转写/实录声明。每个 feature_id 的匹配表达式、扫描范围/数量上限、版本与预期输出写入 §12 的
`admission-policy.json`；不能只写“形态相似”。未读区域留 unreadable。本轮不填未经验证的表达式。

复核队列每条包含 source_id、绝对路径、争议原文定位、特征及原因、建议决定（非批准）、
待填写的最终类型/领域/scope、审阅人/时间。已有有效人工决定与新机器建议冲突时仅列复核，
不得静默覆盖；撤销当前批准必须在显式决定生效时原子撤下活动版本，旧任务不得重新发布。

I0 的“无歧义”指每条来源均有合法终态，待复核有原因和责任交接；不要求把全部材料强行分类。
进入构建的清单只能含 in_scope。`corpus-check` 验证规则、依据及清单一致性，材料语义分类的
正确性由锁定人工样本验证，不能声称自动检查器能够替代人工判断。

**准入与格式声称的对账（2026-09-20 补，I3-1 复盘缺口）**：§5.3/§12.1 声明的格式能力与本节
的材料准入白名单**必须显式对账**——见 §12.1 的「格式可得性对账」。历史上两者各自成立、互不
引用，导致「声称支持 PDF/DOCX/MD」与「语料内 MD/DOCX 全部因材料类型/署名被排除」长期并存而
无人负责。判定责任链固定为：准入只按材料类型/领域/范围判，**不按文件后缀判**；格式可得性是
§12.1 的对账项，不是准入的豁免项。

**开发验证的 dev lane（2026-09-20 补，U 裁决）**：生产语料治理口径（合规、可引用）与开发验证
口径必须分层。唯一允许的例外是显式 **dev lane**：一份独立政策文件（`scope=dev` +
`production_in_scope_unchanged=true`）逐源列出 U 指定的来源，允许其以**如实的**材料类型进入
`in_scope`；装载需调用方显式开关（CLI：`CORPUS_DEV_LANE=1`），否则 fail-closed 拒绝。
硬约束：①dev lane **不得改变任何生产 `in_scope` 判定**（v1 政策逐字不改，生产路径不装载）；
②`material_type` **不得伪写**为 `research_report`（伪写即类型失真，等同伪造凭证）；
③放宽只对清单内来源生效，未列入者按冻结语义拒绝；④dev 判定必须在证据中带 `dev_lane=` 标记，
并在 `corpus_admissions.policy_rev` 上留下 dev 政策版本以便审计区分。以上四条由反例测试锁定
（`tests/test_corpus_preparation_admission.py` 的 dev lane 族）。

### 5.3 按格式解析

| 格式 | 处理方式 | 失败/降级 |
|---|---|---|
| PDF | 读取页、文本块/词坐标、列布局、表格候选；保留提取次序及重建阅读次序 | 空文字页、疑似图片/乱码、多栏顺序不可靠分别标记；不按全文平均字符数放行 |
| DOCX | 按正文元素顺序读取段落、标题、列表和表格，记录 element/paragraph/cell 坐标 | 重复标题不影响唯一 ID；图片、文本框等未可靠读取内容列缺口，不假定 document.paragraphs 已覆盖全文 |
| Markdown | 保留原始换行/偏移，识别标题、段落、列表、表格和引用块 | 短小可读文字正常处理；重复标题使用不同单元 ID，不标 needs_ocr |

PDF 表格读取能力作为受控 Adapter：不同读取结果冲突则进入复核，不静默拼接两份可能重复的正文。
表格提取失败与“原文没有表格”分开；原有表格识别能力按真实三类开发样本确认，不许仅凭依赖安装
成功声称表格支持。

## 6. 保真清洗与切块的具体规则

### 6.1 保真清洗

- 页眉页脚按重复内容、几何位置及规则共同判定，不凭单个词删除整页/整行。
- 目录、免责声明、分析师名单、评级说明标为检索噪声；保留原单元和原因。实际评级、风险提示
  和条件句不得因为相似前缀被删除。
- 合并断行、空白、连字符或分栏次序时保留来源映射；无法安全判定则保留原状或复核，不猜写。
- 不修改原数字、符号、单位、期间、指标名；规范值是附加投影，不能覆盖原字段。
- 表格标题、列头、单位、脚注、A/E/F 等实际/预测标志保留关联。
- 每个来源区域必须归入已保留、已标噪声、待复核、需 OCR 或明确不在 scope；不存在无记录消失。

### 6.2 结构优先切块

首版参数作为**开发起点**，不是经过模型或检索实测的最佳值：正文目标 800—1200 个 Unicode
字符，常规块上限 1800，短标题/评级可以远小于目标。I3 只在开发集校准后冻结，不用留出调参数。

| 结构 | 切块方式 |
|---|---|
| 正文 | 先章节，再完整段落，再安全句界；不默认一页一个检索块，不跨报告拼接 |
| 标题/短评级 | 与所属段落关联；无后文时独立保留，不按最小长度删掉有效信号 |
| 列表/风险条目 | 保留引导句与条目归属；超过上限按完整条目拆分 |
| 行业书面问答 | 问与答建立结构组；答案长时分段，但显式关联同一问题，不将问题变成陈述 |
| 表格 | 以行或安全行组为主，携带必要列头/单位/标题/脚注引用；不能切断单元格或混合不同期间 |
| 跨页表格 | 只有表头、列结构及延续关系明确时连接；否则分开并记录不确定，不靠位置猜接 |
| 超长不可安全拆分单元 | 保留原单元，标 oversized/review_required；不截断后宣称完整，不自动发布常规块 |

默认正文核心区域不重叠，避免重复计数；章节标题、相邻句或表头可以作为引用式 context 附加。
context 不属于新的来源正文，也不制造额外 item。fetch 可展示上下文，但必须分别标出证据片段、
来源坐标与辅助展示内容。

**检索块 ≠ R2 原子义务。** R2 可以从同一 units/结构关系中生成有限候选，也可以按需扩展上下文；
不能将每个检索块强制当作一个命题，不能通过“全部块执行完”推断语义召回完整。

## 7. 索引、检索与取证

### 7.1 第一版索引

- PostgreSQL 中文全文检索作为首个候选基线，复用当前配置与 GIN 能力实测；不是盘点前冻结选型。
- 针对 chunk 的 search_text 建正文索引，标题/章节作为有来源标记的检索字段；为 build_id、
  source_id、chunk_id、研究领域及发布日期建立必要关联/筛选索引。
- 排序先沿用现有标题权重、AND→OR 兜底及按文档去重策略作为对照起点，按新切块重新校准。
  旧“Recall@5=100%”实际含逐题通过口径，不自动转移到新索引；按 §12 区分指标并逐类验收。
- 数字、小数、负数、百分号、代码、单位词及中英文混合查询必须有固定测试。若 FTS 召回不足，
  先记录具体失败，再评估现有 trigram/精确匹配补充；不默认引入新搜索系统。
- 候选 build 可以有已建索引，但默认 search 只连接 current admission 下已发布的 active build。
  不执行“先查所有历史块再在客户端过滤”，避免旧版本或纪要占满 top-k。
- 配置版本升级不可原地改变同名分词配置却沿用旧 index_rev；新索引版本、重建和重新校准要联动。

### 7.2 精确版本句柄

工具名称 `corpus_search/corpus_fetch` 保留。返回字段可增加 source_id/build_id/coverage，
但原有“doc_id + locator”必须升级为可唯一解析的版本句柄：

- 新结果 `doc_id` 使用 `cv2:<build_id>`，表示一个确切文档构建版本；稳定的原始来源身份另放
  `source_id`。不是把数据库逻辑主键偷偷塞回旧日期/hash 规则。
- `locator` 使用 `chunk:<chunk_id>`，页码/标题另作显示。句柄可原样复制，不要求模型生成 ID。
- fetch 校验 chunk 属于该 build，返回原文片段及 span/cell 定位。清洗/拼接展示不能作为一整段
  “逐字引文”；引用必须来自某个真实片段或明确的多片段 evidence。
- search 与 fetch 之间发生新版本发布，旧句柄仍读取旧不可变 build，不静默切换。scope 撤销与
  访问权限另行检查；历史可审计不等于默认准入。
- `verify/source_resolver`、策略产物、golden、覆盖查询、批处理和日期提取调用方一起迁移。
  不再从 doc_id 前缀推发布日期；使用有依据的 metadata_snapshot。
- 旧数据库清除后旧句柄不映射到新结果。历史引用由离线归档解释，或明确返回 archive_required；
  不承诺继续在线兼容全部旧 doc_id。

这保留工具交互方式，但不是“调用方零改动”：返回契约、hint、验证器和已有测试需要一起更新。
`corpus_search` 当前空命中提示会直接声称无相关研报，新实现必须改成“当前已发布范围内无匹配”。
若存在准入未决、构建失败、库未发布或故障，覆盖为 unknown；只有明确检索范围完成且查询成功，
才可报告该范围无匹配，不能外推整个来源集合不存在相关资料。

**I2-8 独立复核裁定（RM-I28-0，2026-09-18）——以下四条为本节的规格补充，实现与规格一致：**

- **文档级读取遵循句柄版本**：`document_text` / `source_resolver`（经同一权威读取 Interface）
  与块级 `fetch` 同语义——按 `cv2:<build_id>` 绑定的 build 返回原文，跨发布**不换正文**；
  返回对象的 `build_id` 必须等于**实际读取的 build**，不得回填句柄值。
- **撤销的文档级信号**：来源撤销/排除时文档级返回 `None`（显式不可服务），不得用空串
  冒充“合法空文档”（零单元 build 才是 `""`）；块级仍抛 `WithdrawnError`，两者语义对齐。
- **迁移目标无 legacy fallback**：目标库已承载 corpus schema 时，任何配置不得回退旧
  `blocks`（显式请求 `legacy` 直接拒绝）；`new` 在无 corpus schema 的库上同样 fail-closed；
  `auto` 仅作未迁移旧库的过渡兜底，不得用于迁移目标。
- **旧引用归档策略**：`doc_id→source_id` 映射 manifest 属 I4 停写窗口交付件
  （design-review `reset_scope_candidates` 前置为「新链重建并核对后」）；在此之前只提供
  `archive_required` 拒绝路径，不提前生成该件、不以新正文冒称旧引用。

**I2 全链路复核裁定（RM-FC-5，2026-09-18）——拼接语义落规格：**

- **块级与文档级文本的拼接语义**：`ChunkEvidence.text` 与 `DocumentEvidence.text` 都是所引
  单元 `raw_text` 的确定性 `"\n"` 拼接，**不是源文件的字节还原**——源文件中的空行分隔在拼接
  中不保留（源 `A\n\nB` → 文本 `A\nB`）。逐字性按**单元**成立（每个单元的 `raw_text` 逐字出自
  源文件）；跨单元引文必须按单元取证，不得把拼接结果当原文切片。文档级 `DocumentEvidence`
  的 `text` 与 `build_id` 同源（同一 build 的全量单元，按 `ordinal` 排序）。
- 空文档与撤销必须可区分：零单元 build 才是 `""`，撤销/排除抛/返回不可服务信号（见上）。

### 7.3 准入、处理覆盖、查询结果三轴契约

`coverage` 不再是未定义字符串，而是包含以下字段的返回对象；类型/枚举/非法组合由同一
Interface 校验，未知枚举拒绝，不 fallback 为成功。

| 轴 / 字段 | 取值域 | 含义 |
|---|---|---|
| 单来源 admission.decision | in_scope / excluded_by_policy / review_required | §5.2 决定，不是查询结果 |
| coverage.processing | full / scoped / unknown | 相对于 requested_scope 的处理完成程度，不是语义正确率 |
| query_status | matched / no_match / failed | 在实际 effective_scope 内的查询执行结果 |
| availability | available / absent / unknown | 与既有“覆盖状态”衔接；针对明确用途和范围，不覆盖前两轴 |

coverage 必带 `requested_scope_ref/effective_scope_ref/publication_snapshot_ref/reason_codes` 及
来源数、已发布数、排除数、待复核/失败数；计数定义与分母绑定同一 scope 清单及查询快照，不能
从另一时刻的全库 stats 拼接。检索并发发布时的结果和覆盖元数据读取同一数据库快照。

`publication_snapshot_ref`（I2-8 落地定义）：当前发布集合的稳定指纹——
对 `(source_id, active_build_id, generation)` 全集做确定性 md5 聚合，与各项计数在**同一条 SQL**
内求值（因此二者同快照）；发布、撤销或 generation 变化都会改变它，可用于把 coverage 绑定到
具体发布时点。检索侧的「同快照」由 `read_pg.search_with_coverage` 实现：命中与覆盖在同一个
REPEATABLE READ 事务内读取，并发发布下不会出现「覆盖报零已发布来源、却返回了命中」。

- full：请求范围内必需区域均已完成、可定位且发布；不证明全部视觉内容或模型语义完整。
- scoped：只覆盖请求范围的一个明确且已获准的真子集，子集内无未决必需区域；须返回剩余范围。
  用户若明确请求该子集且全部完成，可相对这个新请求报告 full，不能仍称整篇 full。
- unknown：请求所需区域有未决/读取失败/未发布/权限或系统故障；比 scoped 优先。被范围排除
  的来源单列，不能把 excluded 塞进处理完整度或冒充 no_match。没有有效 scope/快照也为 unknown。
- matched 且有可核验的证据可返回该证据范围 available，但不能掩盖其余范围 unknown。
- no_match 只允许表述“该已查询范围无匹配”；映射 absent 还必须满足范围闭合、查询成功及
  明确可判定的数据存在性条件。自由文本 FTS 无命中通常仍为 availability=unknown，不足以
  推断材料没有相关内容。failed 恒为 unknown，不能携带“全范围无数据”结论。
- 新构建失败不自动否定仍合法的旧活动版本：若请求允许旧版，返回其精确快照及更新失败说明；
  若请求最新版本而最新版未通过，则该需求为 unknown。禁止静默用旧版满足“最新”的要求。

必测组合：空库且 scope 未登记、已完成范围的无匹配、排除材料、部分范围、未决准入、PG 故障、
旧版可用但更新失败、查询期间发布及跨域聚合。该映射不修改市场数据的业务含义。

**I2 全链路复核裁定（RM-FC-0，2026-09-18）：缺口分级与 `scoped` 可达**

§7.3 的 `scoped` 允许发布「已获准的真子集」，但读取缺口（`quality_report.gap_regions`）
此前恒阻断发布且无坐标，使 `scoped` 在实现上不可达（缺口区域 `ordinal=None`，既不能参与
scope 判定，也不可能被证明「在请求范围之外」）。本裁定选定 **A + C 组合**：给缺口一个
**裁决 seam**（默认分级即 `disposition`，并可被 scope 判定降为 `out_of_scope`），同时
**补齐缺口坐标**。任何路径下缺口都**必须保持可见**，不得回退为静默丢弃。

缺口身份沿用既有台账编码 `issue:<code>:<location>`（`quality_report` 形状不变，仍为
`gap_regions`/`oversized_chunks` 两键）。坐标取自 reader 的 `location`：`page:N` → 页坐标；
`body[i]` / `…:tbl[n]/row[r]/cell[c]` → 元素坐标；`char:a-b` / `char:a-` → 字符区间；
其余显式标 `unlocatable`（无法证明在获批范围之外）。

| 缺口码 | 合成区域状态 | 默认分级 |
|---|---|---|
| `empty_page` | review_required | **acknowledged**（无文字层且无图片，未丢失任何正文） |
| `image_region_small` | noise | **acknowledged**（阈值内装饰图，已按噪声记账） |
| `unterminated_code_fence` | review_required | **acknowledged**（文本已消费到文件尾，仅围栏结构未闭合） |
| `image_only_page` | needs_ocr | **blocking** |
| `image_region_unreadable` | needs_ocr | **blocking** |
| `table_extraction_failed` | review_required | **blocking** |
| `table_lines_without_extraction` | review_required | **blocking** |
| `unreadable_element` | review_required | **blocking** |
| `unknown_body_element` | review_required | **blocking** |
| 词表外/键不可解析 | — | **blocking**（fail-closed：看不见的缺口比误阻断更危险） |

判定顺序与发布口径：

1. **scope 优先**：缺口坐标可证落在获批 `char:` 区间之外（与任一区间无重叠）→ 生命周期
   判为 `out_of_scope`：不阻断发布、不计入剩余范围（该区域本就不在请求范围内）。
   部分重叠/无 `char` 坐标 → **不可证范围外**，回落默认分级。
2. **默认分级**：`blocking` → 拒绝发布（错误文案仍含 `gap_regions`，原因机读）；
   `acknowledged` → 允许发布，但必须进 `quality_report`、`check`/`status` 的 `gaps` 输出与
   `coverage.reason_codes`。
   **具名人工判级入口（2026-09-20，i0c-r36，`gap-policy-2`）**：上表默认分级逐项不变。
   对具体 build，人工签署 `human-gap-review-1` 凭证后可将仍阻断缺口的生命周期判为
   `acknowledged`，但 `disposition` 仍为 `blocking`。凭证绑定 source_id、build_id 和
   完整 build 指纹（含准入决定、各 rev、scope、质量台账），并包含 reviewer、带时区
   reviewed_at、逐缺口 rationale、获批所需证据完整集合 required_locators、其
   evidence_scope_ref 与 scope_rationale。审核人必须显式签署
   `human_verified_complete_scope_and_nonintersection`，确认集合完整且已逐处查看原始内容；
   不得拿检索命中或机器选出的少量 locator 代替所需证据全集。与 admission 凭证相同，
   这是受信任人工操作者提交的具名记录，不是密码学身份认证；内容哈希只用于绑定和追溯。
   该凭证既签认本 build 的目标证据范围，也逐处判级；scope_ref 字段不得因此扩大。

   `corpus gap-review --build <id>` 只导出空签署模板；人工填写后以
   `--record <signed.json>` 登记。登记与发布/check/status 都重验：所有仍 blocking 的
   已知缺口必须逐处具备理由；所需证据非空、已保留；缺口与每个 required locator
   必须可证不相交。首版支持正页号 `page:N` 和有界半开区间 `char:a-b`；同页、字符
   重叠、跨坐标类型、无坐标、未知码、缺字段/重复 JSON 字段、旧版本/错绑定一律拒绝。
   不把页级缺口凭空缩成页内框，不以人工签署覆盖不相交校验。光力科技 p7 与金标 p7
   重叠时仍 blocking；不得事先宣称 13 处全可放行或 I3-1 已通过。

   一份 build 一份完整凭证，登记前可修改草稿；登记后同内容幂等，异内容拒绝覆盖。
   存储复用 corpus_source_checkpoints 的保留命名空间 `human-gap-review:<build_id>`，
   该命名空间只允许专用追加入口，普通可覆盖检查点 API 拒绝写入；PG 以唯一键冲突
   比较保证并发首写不覆盖。修改已登记裁决须退役该发布并以新的构建/准入身份重审，
   不提供删除或 last-write-wins 豁免。PUBLISHED 记录保存 human_gap_review_id；
   发布重试/回滚也重新检查凭证，丢失、损坏、旧版本或绑定变化仍拒绝。
3. **coverage 如实反映**：活动 build 的缺口台账非空（含 `acknowledged`/`out_of_scope`）时，
   该来源的已发布集合只是**真子集** → `coverage.processing=scoped` 且 `reason_codes` 含
   `gap_regions_present`；缺口清单（含坐标与恢复路径）即「剩余范围」的机读形式。无缺口仍为
   `full`；未决/失败/零发布仍优先 `unknown`。
4. **依据与记录人**：默认分级表即依据（当前 `gap-policy-2`；历史为 `gap-policy-1`），记录人为 `publish --operator`
   （写入 PUBLISHED job 检查点 `publish-record-1` 的 `acknowledged_gaps`/`gap_policy_rev`）。
   按码的个别豁免（政策 override）留待 I3 校准后外置为策略配置（policy v2），不在本裁定内。
   具名人工判级的依据是独立凭证的 review_id，审核人来自 reviewer，不以发布操作者冒充。
5. **CLI 可见性**：`corpus-check`（含被拒时）与 `corpus-status` 都必须输出结构化 `gaps`
   （码/坐标/状态/分级/恢复路径）与 `recovery`（可执行恢复路径），不得只给自然语言 `error`；
   `corpus-plan` 的预检与 `check` 共用同一分级与判定实现（不得各算一套）。

## 8. 构建、入库与发布状态

```text
registered → admission_decided → parsed → cleaned → chunked
→ staged → indexed → verified → published
```

这表示阶段顺序，不是一个布尔 success。job 可以 failed/retryable，区域可以 needs_ocr/review，
准入可以 excluded；它们各有记录。发布状态与语义质量状态分开。

1. 解析/清洗不持有数据库长事务。产物按哈希落到暂存区，写入候选 build/units/chunks 后
   核验数量、映射、外键、来源哈希及全文查询。
2. 字段缺失如未知作者/日期可显式 unknown，不必阻断引用；必需正文区域未读、关键表格不完整、
   定位不唯一则阻止常规发布。首版不自动发布部分文档；明确用户批准章节 scope 时只发布该 scope，
   输出 scoped，不称全文完成。
3. 发布采用短事务：锁定 source 的 publication，核对当前准入决定及 generation，确认 build
   完整且通过检查，再切换活动指针。旧任务不能覆盖更新后的决定或较新的人工批准。
4. stage、索引或 metadata 失败都留下检查点；重试只做未完成阶段。发布前失败保持旧活动版本可读。
   首次构建失败则没有可用版本，报告 unknown，不能捏造空库正常。
5. 回滚为切换到经核验且仍符合当前准入的旧 build；不得通过回滚重新放行已排除来源。
6. 原文、已发布 build 及语义引用不在普通清理任务中删除。垃圾回收限于无引用暂存产物，另设
   明确目录/对象与保留期限，不与本次旧库整体退役混用。

### 8.1 job、attempt、租约与接管

逻辑 job 唯一键候选为 `(build_id, stage)`；重试/接管增加 attempt，不新造 build。job 状态为
queued/running/succeeded/failed/cancelled；失败是否可重试及原因单列，attempt 历史追加保存。
作业允许重复计算，但最终写入效果幂等，不承诺进程“只执行一次”。

1. 取得所有权必须在短事务中原子判定 queued、允许重试的 failed 或已过期 running；running
   未过期不得抢占。每次取得所有权递增 attempt 与 fence_token，写入 owner_id 与 lease_until。
   正常重试不自动复活 cancelled；同 build 已成功的阶段返回原检查点。
2. 租约时间只取数据库时间。配置必含 `lease_ttl_seconds/heartbeat_interval_seconds/`
   `stage_timeout_seconds/max_attempts`；heartbeat 必须小于 TTL，且不超过 TTL/3。开发候选为
   TTL=120 秒、heartbeat=30 秒，不是已测保证；I0 冻结各阶段上限/参数，I2 用停顿/延迟实测。
   缺配置不启动，stage 超时与 max_attempts 均有限，不能无限续租重试。
3. 心跳仅在 owner/token 匹配、状态 running 且 lease_until 大于数据库当前时间时续租。
   过期不能原地续命；需要重新竞争并取得新 token。同步解析须有独立心跳执行路径，不能只在
   解析结束后续租；无法维持心跳则该阶段失败，不放宽所有权检查。
4. 任意权威写入、检查点/完成提交都在同一事务校验 running、未过期及当前 token。更新零行
   即 lease_lost：停止/尽力取消工作，不写数据库，不发布。旧 worker 恢复运行也不能覆盖接管者。
5. 文件暂存按 job/attempt/token 隔离；失去所有权后残留文件不是可发布产物。被复用的产物
   必须由当前持有者核验完整哈希。相同 build 的不同输出哈希为确定性冲突，拒绝覆盖，保留调查。
6. 提交已成功但客户端未收到响应：重试读取已提交检查点，不重复增行。发布任务另外核验当前
   admission/generation；只有新 job token 不代表获得更新来源决定或活动指针的权限。

I2 必须实际验证双 worker 竞争、续租/过期恰好临界、旧 worker 恢复、连接断开、提交响应丢失、
取消后接管和新准入撤销；不得用内存锁测试代替 PG 条件写入测试。token 丢失不等于允许回滚
他人已提交结果，资源回收也不得删除另一 attempt 的文件。

## 9. Interface、CLI 与代码落点

公开编排 Interface 收敛为 `plan → execute → publish`，内部处理全部阶段与恢复，CLI 不自行复制
逻辑。PostgreSQL 和内存测试 Adapter 跨相同存储 Seam；真实 PG 用例验证事务和 FTS，不能用
内存替身代替。文件读取和解析器可注入测试替身；纯切块/映射规则直接测行为。

建议代码落在现有 `plugins/corpus/`，不改通用 Agent 内核：

| 落点（拟） | 职责 |
|---|---|
| `preparation/contract.py` | 构建配置、版本、状态及产物模型 |
| `preparation/engine.py` | plan/execute/publish 与恢复编排 |
| `preparation/source.py`、`admission.py` | 接收、归档、准入和元数据依据 |
| `preparation/readers/` | PDF/DOCX/MD 统一格式 Adapter |
| `preparation/clean.py`、`chunk.py` | 保真视图、映射、结构切块与质量台账 |
| `preparation/repository.py` | PG 候选写入、活动指针、job、索引及事务；不是另一套业务规则 |
| `service.py` | 保留业务入口并代理新 Module，接旧消费者迁移 |
| `plugins/tools/corpus_search.py`、`corpus_fetch.py`、语料 verify | 新版本句柄、覆盖状态及证据读取 |

文件划分是实现建议；没有独立复杂度时合并内部文件，不为了目录齐全增加转发层。
`ingest.py/evidence.py` 的解析逐步归并，不让两条解析路径继续写两套主结果。`claims.py/claims_v2.py`
中的共享模型、LLM 和校验先拆依赖再退休旧抽取；财务公式与用途验证继续接相同来源证据。

拟在现有 CLI 增加的命令职责如下，**目前不可当作已有命令执行**：

| 命令 | 作用 / 默认写入 |
|---|---|
| `corpus-plan --manifest ...` | 校验显式清单、源/配置版本、预计工作量；无模型，无 PG 写入 |
| `corpus-build --plan ...` | 执行来源归档与候选构建/恢复；写显式目标，不自动发布 |
| `corpus-check --build ...` | 核验产物/索引/取证/状态；只读 PG 与来源归档 |
| `corpus-publish --build ...` | 检查门通过后切活动版本，记录操作者和 generation |
| `corpus-status --build ...` | 显示该 build 的逐阶段状态、失败、缺口与可执行恢复路径 |
| `corpus-rebuild-plan --manifest ...` | 比较 parse/clean/chunk/index 版本，决定可复用阶段；不直接全库重跑 |

**I2 全链路复核裁定（RM-FC-6，2026-09-18）：** `corpus-status` 的参数以**实现为准**统一为
`--build <build_id>`（该命令逐阶段展示一个 build 的 9 个阶段台账，「阶段+attempt」是展示
粒度而非查询键）；本节原 `--job` 用词作废，其余命令的 `--build`/`--manifest` 不变。另：
`corpus-plan` 增加**只读可发布性预检**（同一缺口分级与判定实现，无 PG 写入、无模型），
输出每份材料的预计缺口与「按当前口径是否可发布」的预判；预检是预判，发布门仍是唯一权威。

旧 ingest 停止自动写旧表；切换期间可以显式提示迁移，不保留静默 legacy fallback。清库/退役是
独立维护操作，必须读精确 reset manifest，不能由日常 ingest 的一个隐含参数触发。

## 10. 盘点、恢复证据与清理候选策略

清除旧派生数据是候选切换策略，不是已冻结删除方案。I0 可依据共享依赖选择更小范围迁移或
撤销清理提案；实际执行必须有精确目标、最终清单及批准。本轮没有读库、备份演练或清库。

1. **I0 盘点**：确认 host/database/schema、表/视图/索引/序列/扩展、后台写入任务、所有消费者，
   以及是否与用户/会话/市场数据共库。不得按名称模糊匹配后 DROP CASCADE。
2. **I0 首次归档与恢复演练**：保存原文件、人工决定、预算/raw、历史引用与基线；数据库备份
   在显式隔离目标恢复验证。覆盖、版本/扩展、角色权限、对象数量/校验值、抽样取证、可用性、
   实测恢复耗时及错误均进入恢复报告，不接受“备份命令退出码 0”代替恢复成功。留出原文在备份/
   恢复目标仍隔离；仅可做受控完整性校验，不能用于开发查询、人工标注或解析试验。
3. **空 schema 验证新链**：使用三类开发清单，从零建立新 schema、构建、索引、查询、取证和恢复。
   可与旧库短期并存用于验证，最终不保留双写或双主。
4. **I4 最新备份与维护窗口**：暂停全部批准范围内的写入者和默认检索，记录截止点，取得覆盖
   实际切换对象的新一致性备份。绑定原文归档/PG/人工审计同一清单，复核相对 I0 的新增对象、
   权限、扩展与恢复工具变化；最新备份须在隔离目标恢复核验，不能只依赖几天前的演练。
   只有最新恢复证据、资源/时间窗口和批准的 reset manifest 匹配，才按清单清理旧语料派生记录
   及其专属结构/索引；保留共用 PG 扩展与无关业务表。任何漂移或核验失败均停止清理。
5. **重建活动集**：按批准的公司/行业/宏观来源清单生成新结果，校验后发布；纪要仍留在原始档案，
   不回灌活动索引。未准入和处理失败来源进入可操作清单。
6. **恢复服务并退役旧入口**：真实工具与 CLI 往返成功后恢复。中断可从阶段继续；必要时由已验证
   备份恢复旧系统。清空后不能再承诺仅切一个旧指针即可回滚，旧在线数据已不存在。

初次清库后的旧历史引用只由归档解释；新系统内部后续版本回滚则按 §8 工作。这两种恢复不可混为
一谈。全量重建成本拆为确定性解析/索引与模型抽取，前者不自动授权后者。

I0 恢复报告必须记录实际覆盖截止点、可接受的数据损失与恢复时间约束及核验人；这些值由环境和
用户约束核定，不凭空承诺。恢复环境不可用则 I0 恢复门未通过；不把“待定耗时”写成已演练。
纯内存解析工作可按 §11 的独立条件继续，但不得因此跳过恢复门进入 PG 切换。

## 11. 执行批次与过门

| ID | 交付 | 通过条件 |
|---|---|---|
| I0 | A：实际目录/消费者/共库/来源与测试基线；B：首次恢复演练；C：基于 A/B 的设计复核 | A/B/C 分别记录；物理布局可否决/调整；未决项可阻断对应门，不能仅交盘点计划就算完成；不执行删除 |
| I1 | 统一解析、清洗、切块及内存执行链 | I0-A 的逻辑契约/开发基线冻结后可做纯内存工作；反例/映射通过，不冒充 I0-B/C 完成 |
| I2 | 经 I0-C 冻结的 PG 布局、索引、候选写入、发布与恢复 | I0 全部通过 + I1；在显式隔离 PG 实测含租约接管，核心 PG 门不允许 skip |
| I3 | 公司/行业/宏观至少各两份已使用开发材料的 CLI/工具 E2E | 样本格式/查询/证据 gold 按 §12 锁定；逐类清洗/检索/取证及财务非回归通过，强制零模型 |
| I4 | 经复核批准的迁移/清理、活动数据重建及切换 | I3 + 停写截止点后最终一致性备份恢复 + 精确切换清单/批准；reset 分支另需删除清单，migrate 不强制清理；defer 阻断切换，活动索引无污染且可恢复 |
| I5 | 增量、重新解析、重新切块/建索引和维护说明 | 四种重复/变更情况均可重复，旧入口退出，无隐藏双写 |

I0—I5 是“可用证据库”的交付，不等待 R2 item/关系模型验收。R2-S* 可在新 Interface 稳定后做
零模型接线，真实调用仍须其独立前置门与预算。R2 语义正确、数据计算和跨层分析分别放行。
Web 暂缓，不在此基础重构中复做 Web。

I0-A 必须交实际对象/消费方清单、每来源准入终态、测试资产与开发分母，以及 §4/§5/§7/§8 的
逻辑契约。I0-B 交恢复报告而非演练待办。I0-C 逐条记候选的保留/调整/否决理由、字段级映射、
迁移替代方案、未解决风险和冻结清单哈希；没有证据不得把七表图直接转为 DDL。

## 12. 测试资产、验收定义与冻结条件

### 12.1 资产位置与冻结方式

下列路径为**拟交付位置，本轮未创建或填造样本/金标/测试文件**。相对项目根目录；资料缺失须
列出缺口交人工，不访问留出补齐开发分母。当前已有金标不原地改写。

| 位置（拟） | 内容与冻结阶段 |
|---|---|
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i0-inventory.json` | I0-A 的真实 PG 目标/对象/共库、读写消费者、定时任务、权限/扩展及依赖；不含凭据 |
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/dev-manifest.json` | I0-A：source_id、绝对路径、SHA-256、领域/格式/版式、准入/审核、历史开发属性、预期范围与用途 |
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/admission-policy.json` | I0-A：§5.2 输入输出枚举、特征提取规则/上限、判定次序、反例引用、自动决策禁用配置 |
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/review-queue.json` | I0-A：实际未决项与审核字段；空队列也须由盘点证据支持，不伪造人工完成 |
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/source-gold.jsonl` | I0-A/I1 前：人工确认原值、条件、评级、页/段/表格/cell、应保留或噪声、合法映射；不可用被测解析器输出自证正确 |
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/query-gold.jsonl` | I0-A 初始基线/I3 前最终冻结：query_id、领域、请求范围、问题、相关 source 集/证据范围、关键题标志、人工依据与审核 |
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/baseline-bindings.json` | 原 golden 及已通过财务资产的哈希、适用/排除清单、旧锚点到新 source/证据的审核映射；新旧口径分别报告 |
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i0-restore-report.json` | I0-B 的备份清单、恢复目标/过程、哈希/数量/取证、权限/扩展、耗时和失败，不得仅写 passed |
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/design-review.json` | I0-C：实际证据引用、候选决策/DDL 映射、资源/租约参数、变更原因、批准人与冻结版本 |
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/<phase>-<revision>.json`、`freeze-manifest.json` | 每阶段/修订追加不可变快照，绑定源/规则/预期/测试/评分器/代码差异/配置哈希及父快照；报告引用其实际运行快照 ID/哈希，后者仅可作当前版本索引，不能追改历史 |
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i4-cutover-manifest.json` | I4 停写与最终备份恢复后冻结：reset/migrate/defer 决定、精确对象/顺序/保留项、截止点/版本/恢复证据及批准；defer 不执行 |
| `.scratch/corpus-evidence-pipeline/ingestion-rebuild/i4-reset-manifest.json` | 仅批准 reset 分支在清理前冻结：精确待清理/保留对象、依赖顺序、批准、截止点后的最终备份及恢复引用；不是迁移分支必选动作 |
| `tests/fixtures/corpus_preparation/`、`tests/test_corpus_preparation_*.py` | 拟新增合成 MD/DOCX/PDF 小夹具及确定性/PG/CLI 契约测试；真实版权资料不复制到公开夹具 |

query-gold 从已准入开发材料的实际原文出题，公司/行业/宏观每类至少 10 条，覆盖原值、条件/
观点、表格、时序与跨文档需求；不由模型出题，也不从候选搜索结果倒推“正确答案”。每类至少
两份真实开发来源；PDF/DOCX/MD 每种声称支持的格式均需真实已用开发样本，领域×格式×版式
矩阵记录实际覆盖和空缺，不捏造九格全覆盖。缺格式样本则该格式真实门未通过，不能静默缩范围。

**格式可得性对账（2026-09-20 补）**：冻结开发范围**之前**必须产出一张「声称格式 × 已准入语料
可得性」表（唯一落点 `dev-manifest.json` 的 `format_availability`），逐格式给出：已准入真实样本数、
版式覆盖、缺口。缺格的格式**只允许两种处置，且必须显式登记其一**：（a）补料工单（谁/何时/什么料，
来源须可引用）；（b）由 U 显式修改本节的声称范围（**不得静默缩范围**）。该表由
`preflight_scope_check.py` 在取样前核对：缺格未处置即视为该阶段**前置未满足**。
样本进入 dev 构建的例外口径见 §5.2 的 dev lane；dev lane 样本**计入**本节的格式门，但必须在
矩阵与证据中标注 `dev_lane`，且其材料类型如实登记。

规则/评分器在查看候选验收结果前冻结。开发发现问题可新建修订，保留失败报告并在同一新口径
重评基线与候选；不能移动预期、删除失败题或覆盖历史报告来制造非回归。留出另设独立清单，
开发运行的文件允许清单不包含留出内容。任何必需资产/hash/PG 条件缺失，阶段为未满足，不是通过。

### 12.2 测试矩阵

| 测试族 / 拟文件后缀 | 方法与必需反例 | 验收对象 |
|---|---|---|
| admission | 表驱动黄金用例：明确研报/纪要、书面问答、引用访谈、无专家标签实录、混合、源变更、审核冲突、政策冲突 | §5.2 判定/原因/人工优先级，未决不能发布 |
| fidelity | 人工来源黄金差异 + 合成负例：短 MD、重复标题、混合 PDF 空页、多栏、跨页表格、预测标记/脚注、超长单元 | 原值/条件保留，缺口可见，不能只用相同解析结果比对自身 |
| mapping | 固定种子生成/参数化性质检查：每条引用有唯一 source/build，原文区间合法；rename 不改源身份；规则升级改 build；核心区不重复覆盖 | 结构单元/字符映射、幂等与唯一性；无需为性质检查强行引入新依赖 |
| authority | 篡改 JSONB 副本、错误 cell、跨 build、未知 unit、坏哈希、清洗拼接伪引文、导出清单不可信 | fetch/verify 同一权威 Interface 拒绝；导出复用也须验证 |
| publication_pg | 真 PG：两 worker、过期令牌、提交丢响应、撤销准入、取消、并发发布、失败恢复、索引配置升级 | §8.1 和活动指针；必需 PG 不允许 skip |
| coverage | 请求/有效范围组合、空命中、未知库、排除、部分处理、故障、更新失败、查询快照漂移 | §7.3 三轴及 availability，不把 no_match 自动转 absent |
| retrieval_pg | 固定 query/source gold 与 scope，数字/小数/负号/单位/混合语言，文档与证据分别计分 | §12.3 指标，FTS 展示命中不代替取证 |
| cli_isolation | 真实注册工具 + CLI 子进程往返、模型调用陷阱、网络允许清单、重启续跑、未知句柄、错误退出码 | §2.1/§9 真 Interface 与零模型，而非只测私有函数 |
| legacy_regression | 经清单绑定的旧财务/公式/客户表/正文证据正负控；保留历史失败，不只比总体均值 | 已通过能力不退化；宏观旧规范字段失败另列 |

既有回归入口包括 `tests/test_corpus_ingest.py`、`tests/test_corpus_metadata.py`、
`tests/test_corpus_evidence_pipeline.py`、`tests/test_corpus_layout_recovery.py`、
`tests/test_corpus_financial_review.py`、`tests/test_corpus_semantic_gates.py`、
`tests/test_corpus_golden.py`。I0 逐个核定实际来源/副作用/依赖；不能直接全套运行以探测真实 PG 或留出。
旧 golden PG 不可用/锚点缺失的 skip 机制不适用于本次必需验收门。

### 12.3 指标定义与通过条件

必须通过的确定性检查：

- 相同原文/相同版本重复执行不增行；规则升级生成新 build，原文不改。
- 每个结构区有状态；短文本不假判 OCR；混合 PDF 的缺页显式可见；重复标题仍能唯一取证。
- 冻结开发范围内关键原值、符号、单位、期间、评级、否定和条件保留 100%；表格跨列错配为 0。
- 所有 chunk 引用均回到对应 build/source，未知或跨版本引用拒绝；检索展示不冒充原文。
- 原值/条件保留率以人工 source-gold 的预期条目为分母；必需条目 100%，错列/错期间为 0。
  没有人工标注的区域不得因自动台账齐全被计作“原文准确率已验证”。
- 旧检索黄金题仍在三类范围的部分不得退化，剔除范围单列；旧 `plugins/corpus/golden.py` 的
  recall 是逐题通过比例（多文档题含 require_all），历史报告保留原名但不能当作标准集合召回。
- 新检索分别计算：`DocRecall@5=|Top5文档∩相关文档集|/|相关文档集|`（非空相关集，逐题再
  按类宏平均）；`QuestionPass@5` 是满足该题预先冻结的 any/all 文档要求的题数/有答案题数。
  多文档查询需冻结 any/all，超过 5 个必需文档时另设 top-k，不能删相关目标硬凑 Recall@5。
- `EvidencePass@5` 是前五检索文档返回的证据句柄及明确上下文引用，经 fetch/verify 后满足
  该题所需全部原文证据的题数/证据题数。只命中文档标题、但返回块没有答案，文档可命中而
  证据题失败；不得依赖模型额外搜索把一次失败补算成功。
- I0 待冻结开发目标：每类 DocRecall@5、QuestionPass@5、EvidencePass@5 均 ≥95%，关键
  引用题和适用旧基线 100%。若逐题指标只有 10 题，≥95% 就要求 10/10；不声称统计泛化已验证。
  无答案负例另计误报数，已知无证据却伪造引用为 0；不混入召回分母提高分数。
- 真实 PG 验证发布原子性、并发幂等、失败恢复、索引可用和权限；fake 通过不能代替。
- 同一问题通过正式 CLI/真实工具注册路径拿到相同版本证据；空命中、未完成和数据库故障不混淆。
- 历史财务表 57/57、公式 7/7、客户表 12/12、正文数字 3/3 等适用能力按冻结资产重新核验；
  宏观旧规范字段 0/3 仍单列，不伪装为已经通过的基线。

原始区域保留 100% 不等于语义召回 100%；自动结构检测也不是全视觉内容已经解析。需人工核验
的版式、准入和金标在 I0/I3 明确列出。独立留出在规则冻结后另验，不通过不得用其调参后再称留出。

### 12.4 尚未通过的冻结门

实际 PG 目录/共库/消费者、三类样本及查询、解析资源/租约参数、原文归档容量/权限均待 I0-A
核定；首次备份恢复的过程与实测时间是 I0-B 必交证据，不是可推迟到清库后的“未定项”。I0-C
依据这些事实调整或否决物理设计。I4 仍须实际窗口、最新一致性备份恢复及对象批准。

本轮仅修订文档；上述新资产、测试和恢复报告均未执行生成。不得虚构表数量、耗时或一次通过。
当前模型授权仍为零，I0 未完成；所有“拟”字段须在设计复核中定稿后才能据此实施。

## 13. 本轮十项评审的落实索引

| 评审项 | 本次文档处理 | 后续验证门 |
|---|---|---|
| 1 决策顺序 | §1/§4 改候选，I0 可推翻字段/表数/清理策略 | I0-A/B/C |
| 2 准入规格 | §5.2 确认清单首版、确定性次序/输入输出、冲突复核，未校准特征不放行 | admission + 人工 source gold |
| 3 引用权威 | §4.2 原文权威集合与派生缓存/可信导出规则 | authority + CLI |
| 4 租约语义 | §8.1 所有权令牌、接管、续租、旧 worker、提交幂等 | publication_pg |
| 5 时间权威 | §4.3 唯一来源日期/依据与系统 activated_at 分开 | metadata/排序/历史引用 |
| 6 coverage | §7.3 准入/处理/查询三轴及旧三态映射 | coverage |
| 7 恢复提前 | §10/§11 I0 首次演练 + I4 最新备份恢复双门 | I0-B + I4 |
| 8 测试资产 | §12 路径/矩阵/hash/指标定义，明确缺资产不可过门 | I0-A、I1—I3 |
| 9 文档权威 | §0 与旧文档页首互相指向，目标设计不冒充现状 | 文档一致性检查 |
| 10 零模型 | §2.1 强制禁用、异常 fallback 拒绝及子进程守卫 | cli_isolation |
