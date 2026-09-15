# 清洗与入库回溯：问题归属及局部重设计建议

日期：2026-09-14。状态：**诊断完成，缺陷未修复，数据库未核查或重建。**

## 1. 结论

**清洗和入库治理确有问题，需要局部重设计；没有证据支持更换 PostgreSQL，也不能用重新入库解决
全部 R2 失败。** 应重设计的是“来源版本—解析版本—准入—发布—恢复”契约，使清洗改进能真正
进入默认检索和取证链；不是重新选择存储引擎或全面改写项目。

当前最重要的遗漏是：早期流程把“文件没有重复写入、块可检索”作为入库成功；后来又将其视为
“材料已保真清洗、可完整理解”。与此同时，新证据解析/语义结果通过另一条版本化路径产生，
没有自动更新旧 blocks。**去重成功、清洗完成、语义可用是三件事，当前不能互相替代。**

这不是说早期去重设计没有价值：它满足“首次建库和重复导入不增行”的目标，但不满足现在
“源文件不变、解析规则升级后能重新生成并发布可信数据”的目标。

## 2. 本轮证据与限制

- 构造并实际执行 11 个检查：2 个对照成立，9 个期望契约不满足。诊断重复运行结果一致。
- 检查调用真实的 Python 解析/入库编排/旧 R2 Interface/冻结 P4 解析器；来源为内存合成文本和
  PDF 页面 API 替身，PG 写入用 fake cursor，不连接真实 PostgreSQL。
- 原 P4 仅读取已冻结 plan 与 raw，重放已发送的 8 个普通研报义务；不调用其读取 gold 的 prepare。
- 选定既有测试为 35 passed、5 skipped；5 个 PG 依赖测试在收集前就被离线守卫阻断，不能据此
  判断真实 PG 是否可用，更不能声称 PG 更新/事务已经验收。已有单元测试会创建临时 SQLite 测试库，
  不涉及用户语料库；主诊断的 PG I/O 是替身。
- 未读取真实语料源文件或留出原文，真实模型调用 0、真实 PG 连接 0、生产功能代码修改 0。

**9 个未满足项不是“全库发现 9 处坏数据”。** 它们包含可重放代码缺陷、早期设计不支持的新契约，
以及已知 P4 协议失败；当前全库受影响数量、实际事务状态、真实版式错误率未核验。

诊断命令：

```bash
uv run python .scratch/corpus-evidence-pipeline/diagnose_cleaning_ingestion.py --assert-clean
```

实际输出摘要：

```text
GAP  same_source_new_cleaner_refresh         parser_calls=0, skipped_unchanged=1
PASS changed_source_reaches_parser          parser_calls=1
GAP  single_file_reclean_updates_blocks     second_added=false, block_write_calls=1
GAP  retry_repairs_failed_metadata          failed_after_data_commit=true, metadata_calls=1
GAP  readable_short_text_not_ocr            needs_ocr vs evidence available
GAP  unique_fetch_locator                  2 blocks share locator 风险
GAP  cleaning_preserves_substantive_qualifier  index=false, evidence=true
GAP  mixed_pdf_exposes_unreadable_page       page_chars=[360, 0], status=ok
GAP  default_minutes_exclusion              minutes still discovered
PASS r2_direct_path_database_independent    PostgreSQL calls=0
GAP  p4_protocol_valid_without_database     8 attempted, 4 valid, risk×3/question×1
unmet_contract_count=9; exit_code=1
```

退出码 1 是诊断契约仍不满足，不是脚本崩溃。本轮按诊断技能先建立红色反馈循环，再比较变量；
因用户要求诊断而非修复，不执行修改功能代码的修复阶段，也不把反例改成“通过”来交付。

## 3. 实际链路不是一条贯通的清洗链

```text
原文件
 ├─ 旧入库：ingest.parse_document → 去噪/按页或标题切块
 │          → documents + blocks → corpus_search / corpus_fetch
 │                                → 默认 Agent 的检索与原文读取
 │
 └─ 新证据：evidence.parse_evidence → EvidenceDocument（source_rev / parse_rev / spans）
            → EvidenceRun / MaterialRun → 指定 run 的取证与 R2
            → 可选保存 corpus_evidence_runs；不更新旧 documents/blocks

P4 试验：冻结投影/计划 → 自己的请求与解析器（又不是上述正式 R2 的同一执行链）
```

不同用途采用不同文本视图本身合理：检索可去噪、证据需保真。问题不在“必须只有一段文本”，而在
**它们没有共同的解析版本与发布选择契约**。`save_evidence_run()` 明确不替换旧行；因此新取证或
财务样本通过，不表示 Agent 默认读取的 blocks 已改善。

源码定位：`plugins/corpus/service.py:538/627/791/822/903`；
`plugins/corpus/ingest.py:193/263/303`；`plugins/corpus/evidence.py:417`。

## 4. 清洗层发现了什么

| 问题 | 本轮复现 | 影响与边界 |
|---|---|---|
| 状态判断与文件格式不匹配 | 短 Markdown 含可读标题与正文，旧解析返回 needs_ocr，新证据返回 available | `parse_document()` 对所有格式使用平均字符数阈值；可读少字不等于需要 OCR |
| 平均值隐藏局部缺口 | 两页字符数 360 与 0，整体 status=ok | 对混合文本/图片 PDF 缺逐页状态；ok 不能代表每页都可读。页面替身不是实际 PDF 版式测量 |
| 定位符非唯一 | 两个“风险”标题生成相同 locator | PG 主键是 doc_id+seq，但 fetch 只按 doc_id+locator 取第一行，不能唯一指定第二个块；这是普通 MD/DOCX 报告也可能遇到的模式 |
| 去噪删除整行而无保留映射 | “分析师声明：若需求下降，上述盈利预测失效”被旧去噪删除，新证据保留 | 合成前缀反例证明缺乏保真保障；不能推断真实研报大面积含同样句式，更不能说原文件被删除 |
| 表格/结构降级不可完整审计 | 静态核查：旧 PDF 文本附加重建表格，表格失败可返回空；旧 ParsedDocument 无表格失败/变换台账 | 此项未计入上面 11 个实测探针；可检索表格文本不等于原始单元格引用，也不能据此认定当前库表格都错误 |

需要改的是：原始来源不变、检索清洗视图可重建，去掉的段落可追溯；逐页/逐区状态替代一个
平均字符数状态；定位以来源版本与稳定 span/cell ID 为准，标题只作显示。需要 OCR 的区域必须
显式标记，但不需要因此立即采购或替换 OCR/解析工具。

## 5. 入库层发现了什么

### 5.1 重新入库不是重新清洗

两个现有入口表现不同，但都不提供解析版本升级：

- `ingest_dir()`：路径对应源哈希相同即跳过，解析函数调用数为 0。
- `ingest_path()`：会重新解析，但 `ON CONFLICT(content_hash) DO NOTHING`，重复来源不更新块；
  fake cursor 复现第二次已有 CLEANED_TEXT，块写入仍仅发生一次，保存的仍是 OLD_TEXT。

第二项验证的是实际应用分支与 SQL 调用，不是对线上 PG 执行的持久性检验。代码中同样没有
`parse_rev` 参与 documents/blocks 的版本选择，而新 `EvidenceDocument` 已有对应能力。

**不能靠取消去重、改文件名或改原文字节强迫重跑。** 去重仍要保留，但应该去重源资产；相同源资产
必须允许不同解析版本，且重复执行同一个解析版本仍幂等。

### 5.2 数据落库与元数据完成存在恢复断点

正式入口先提交 documents/blocks，再调用 `refresh_metadata()`。注入元数据失败后，数据提交已发生；
再次入库遇到重复来源，不再次执行元数据补全。这不是“数据库没有事务”，而是业务完成被拆在两个
阶段，却没有一个可恢复状态机保证后续阶段完成。

已有 `refresh-metadata --doc ...` 可显式补元数据；问题是当前普通重入库不会自动修复该中断。
本轮没有向真实库注入故障，也没有确认当前库存在缺元数据行。

### 5.3 新范围的准入尚未进入默认流程

`iter_corpus_files()` 只按扩展名、隐藏文件和 README 排除；主入库和 search SQL 没有材料准入
策略或活动版本条件。合成“会议纪要.md”仍被扫描。这个结果是**上轮新需求尚未实现**，不是早期
允许纪要时的规则错误，也不意味着可以只靠文件名正则解决类型识别。

必须在默认准入、索引发布和批次抽取共用一份决定，历史 audit/fetch 保留显式访问；仅删除模型
分母里的纪要，旧检索依然可能把它作为主线资料返回。

### 5.4 源内容版本与默认活动版本需要区分

现有文件内容发生变化可以产生新 doc_id，但旧版本也保留；源码已有同一 source_path 多版本的
缺口提示。当前 `_known_hashes()` 从同路径多行生成一个字典，search 也没有明确活动版本策略。
本轮没有用真实库统计重复版本，因此只将其列为入库重设计需核查的历史版本治理项。

## 6. 为什么不能把 R2 全归因于入库

本轮禁用真实 PG 后：

1. 正式 `understand_material(path=..., max_calls=0)` 能基于内存来源构造 MaterialRun，没有查询
   documents/blocks。零调用不证明语义合格，但证明这个入口不是必须先入库才能执行。
2. 原 P4 的 8 个已发送义务仍解析为 4 条合法、4 条非法（risk 3、question 1）。只读取冻结 plan/raw，
   数据库根本不在该协议失败的执行路径上。

因此“清库重入后 P4 枚举错误自然消失”的假设被排除；无 gold 规划、字段来源契约和错误评分等
问题仍应在 R2 执行与验收中修复。新入库能确保喂给模型的是正确来源版本，但不能代替模型遵循
字段协议或独立语义裁决。

## 7. 是否重新设计：需要，但只重设计局部契约

结合 codebase-design 的 Interface/Seam 检查，建议共用一个来源准备 Module，内部保留检索与
保真两种视图；读写调用者跨同一 Interface，生产 PG 与测试替身作为 Adapter，不再复制清洗流程。

| 逻辑对象 | 必须表达的内容 | 可复用的现有基础 |
|---|---|---|
| 来源资产 | 完整内容哈希、不可变原文、来源位置/版本；内容相同去重 | 现有来源哈希、文档身份及源文件归档约定 |
| 准入决定 | 材料类型、研究领域、纳入/排除/待复核、政策版本和人工依据 | 现有元数据及人工领域覆写；需补材料类型准入 |
| 解析版本 | 来源哈希、parser/cleaner 版本、参数和依赖；原文/结构/清洗映射与局部缺口 | EvidenceDocument、parse_rev、spans/cells、EvidenceRun 存储 |
| 活动发布版本 | 当前准入且通过清洗门的版本；切换原子、失败不污染旧活动集 | 现有 PG 事务、全文索引与运行台账；需补版本选择/发布契约 |
| 语义产物 | 引用确切解析版本、模型/契约版本、逐项结果和覆盖；与清洗成功分开 | MaterialRun / EvidenceRun 及已有预算/审计能力 |

这是逻辑职责，不要求新建五套物理库或机械增加五张表。现有 JSONB 证据版本可复用；具体 schema
应在列清调用者后决定。允许实验表重整，不等于立即删除旧表、文档或人工结果。

建议的发布链：

```text
登记源资产 → 准入 → 保真解析/清洗 → 局部质量检查
→ 写入候选解析版本与索引 → 核验保存/回取一致性 → 切换活动版本
→ 模型语义处理（独立门禁）
```

必须有四种不同操作语义：首次导入、同版本幂等重试、相同原文重新解析、相同解析结果重新抽取。
另有元数据补全和活动版本切换；不能统称“重新入库”让调用者猜会发生什么。

## 8. 对上一版实施方案的补充建议

总体方向仍成立，但应把入库契约设计提前，不能直到 S5 真重建时才决定：

1. **S0**：除了三类范围清单，盘点解析/清洗/活动版本的现状，以及所有 blocks/EvidenceRun 消费方。
   先定义重跑语义和状态，明确哪些字段是清洗结果、哪些只是旧检索视图。
2. **S1**：逐页/区状态、唯一定位、无损清洗映射；正式 Interface 下锁定本文最小反例。
3. **S2—S3**：将新解析版本贯穿保存、检索取证和 R2，补发布/恢复状态与离线故障注入。
   新旧视图可不同，但来源/定位/版本一致；无 gold 与业务 scorer 修正仍是独立必需门。
4. **S5**：在确切实验 PG 目标上做真实事务、索引、幂等、恢复和版本切换测试，再按清单影子重建。
   不能把 fake cursor 或跳过的 PG 测试作为这一步的替代。

核心回归必须包含：源文件不变但解析升级会生成新版本；重复同版本不增行；发布失败旧版本仍可读；
元数据失败可补完；新旧引用均可核验；纪要不在默认活动集；公司评级、行业问答及宏观原值不退化。
同花顺、财务受控计算、审批/沙箱与 Web 不因这次入库重设计扩展职责。

若暂时无法完成版本贯通，应维持旧检索能力并明确其限制，不宣称“新清洗已对默认 Agent 生效”。
当前不建议立即全库重入；先解决版本与发布契约，再重建，才有可检验的意义。

## 9. 产物与可复核性

- [诊断脚本](diagnose_cleaning_ingestion.py)，SHA-256
  `f145531f84d84b9ecd8c9eff1062bea66994a7e8f27c356364767e5dfcf8a887`。
- [逐项结果及源码哈希](cleaning-ingestion-diagnosis-v1.json)，SHA-256
  `0a991322dca0287e09ae55d65826ab3f4d917b1e78f75242425e1c7065fb2714`。
- [既有测试记录](cleaning-ingestion-existing-tests-v1.xml)，SHA-256
  `7bd9ecd0764f13126cbafdad7a715387faf35b1be0112ed542f27b7bce82afd2`。

脚本 Ruff 通过、Pyright 0 errors；本轮没有新增模型预算，没有修改历史 P4 资产，也没有修复上述
反例。建议与当前[三类研报清洗方案](../../docs/plan/research-report-cleaning-scope-plan.md)一起审阅。
