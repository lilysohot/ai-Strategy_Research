# 新增 7 份资料发布执行说明

执行日期：2026-10-21。执行者：Codex，依据本会话用户明确发布指令。

## 实际结果

本批 **7/7 份已发布**到 `vector_pilot_clean7_20261021`：5 份原生文字 PDF，2 份保留原图的本地 OCR 衍生 PDF。
扫描原件仅作归档和追溯；对应 OCR 衍生版以独立 source_id 活动发布，不重复计成两份可检索内容。
共新增 **392 个检索块**，其中原生文字 204 块，OCR 衍生文字 188 块。
隔离库活动来源 **18 → 25**，活动 chunk **684 → 1076**。
向量就绪 **1076/1076**。这属于隔离检索资料发布，不是公开网站发布或生产部署。
原 `postgres` 与 `vector_pilot_corpus_20261020` 的发布指针未变；已有 18 份来源的 active build 和 generation 未变。
没有修改 `.env`，没有切换日常服务默认库或排序开关，没有运行主 Agent 回答评测。

| 资料 | 页数 | 新活动块 | 结果 |
|---|---:|---:|---|
| 高盛：贵州茅台市场化改革方案六 | 9 | 158 | 已发布 OCR 衍生版，未人工逐字校验 |
| 中泰：贵州茅台双锚定价（双语版） | 8 | 55 | 已发布 |
| 中金：DS V4.1 Flash 与国产算力 | 1 | 2 | 已发布 |
| 长江消费周周谈 20260928 | 6 | 30 | 已发布 OCR 衍生版，未人工逐字校验 |
| FundaAI：FCC 光模块规则 | 10 | 41 | 已发布 |
| 研究：DeepSeek V4.1-Flash-1017 | 8 | 19 | 已发布；接受 5 处图像缺口 |
| 研究：OCP 2026 光互连 | 37 | 87 | 已发布；接受 29 处图像缺口 |

两个扫描件的区别：高盛 9 页只有首页 58 个无意义字符，其余页无文字；长江 6 页全部没有文字层。
已渲染首页核对原页存在可读内容。问题是没有机器可检索的正文，不能用文件名或乱码冒充已发布内容。
本轮为这两份执行了本地 OCR。它们的全部原始字节已通过正式接收入口归档登记；OCR 衍生版另行归档。
发布名称明确带有“本地OCR衍生”，不将 OCR 字符当作经过人工校对的原版逐字文字。

## 1. 冻结批次与确认目标

从 `data/corpus/` 精确选择用户刚新增的 7 个 PDF，不递归导入其他资料。
逐份计算完整 SHA-256、文件大小、页数及每页文字量；渲染首页，保存 [inventory.json](inventory.json)。
67 个现有 PDF 的完整哈希互不重复；本批 7 个 source_id 均按原始字节确定。
原文件不改名、不覆盖；文件名里的日期不能自动当成报告发布日期。例如高盛文件名是 8 月 13 日，首页显示 8 月 10 日。

运行环境为 WSL Ubuntu，目录 `/home/administrator/FrontierAgent`，使用已有 `uv` 环境。
连接凭据只从现有环境加载，不写入清单、报告或日志。进程内显式固定目标库。
范围及用户原话见 [authorization.json](authorization.json)，输入清单见 [manifest.json](manifest.json)。

## 2. 发布前快照与备份

读取目标库、旧试验库和生产库的 `source_id / active_build_id / generation`，保存 [before.json](before.json)。
对目标库运行只读 `pg_dump -Fc --no-owner --no-privileges`，得到：

`/home/administrator/FrontierAgent/data/vector-pilot-clean7-20261021/pre-new7-20261021.dump`

大小：13483588 bytes；SHA-256：`5d2c615cf0186392798668d8c4c0976b204ca360c6795ae4a84cb275e69a57cd`。
这是本批执行前的完整目标数据库备份；原文件归档独立保留。未把备份恢复到生产库。

## 3. 准入与原文件归档

用户已明确允许新增资料和个人／外部订阅研究。为本批冻结 `v3-dev-20261021` 来源清单，
只对列出的来源装载，调用时须显式 `allow_dev_lane=True`。
券商资料保留 `research_report`；FundaAI、DeepSeek 研究与 OCP 研究保留
`personal_or_external_subscription`，没有为通过准入而改标成券商研报。
DeepSeek 两篇按 AI／半导体行业研究处理，没有从标题推断成公司财务报告。

通过 `ReviewedDecision` 登记本次用户指令的准入依据；操作者注明由 Codex 记录，
资料类型和领域为 Codex 分类，不声称用户逐页完成了人工完整性复核。
旧准入账本和其他 17 份订阅资料没有批量改写。政策见 [policy.json](policy.json)。

正式接收链路双读原文件并复核哈希，再原子写入：

`data/vector-pilot-clean7-20261021/archive/<sha256前两位>/<sha256>.pdf`

归档后登记 `corpus_sources`。7 份原件及 2 份衍生件均有独立哈希和归档副本。
[pending-archives.json](pending-archives.json) 是 OCR 前的扫描原件登记快照，不能据此判断最终批次仍未完成。
扫描父来源没有活动正文，其衍生来源活动发布；来源登记总数与活动文档数因此不是同一个计数。

### 两份扫描件的本地 OCR

使用 Ubuntu 官方包提取到本批 `ocr-runtime/` 的 Tesseract 5.5.0；没有全局安装软件或更换项目依赖。
逐页以 300 DPI 渲染，高盛用 `eng`，长江用 `chi_sim+eng`，共 15 页。
保存每页 TXT、TSV 和带不可见文字层的 PDF，再按原页尺寸合并成独立衍生 PDF。
原件不覆盖，衍生文件保存在 `data/vector-pilot-clean7-20261021/ocr-derivatives/`。
核对每页都有可用文字，并目视核对原件和衍生件首页。没有执行逐页逐字人工校对。

[ocr-provenance.json](ocr-provenance.json) 记录父/子 SHA-256、路径、识别版本、语言和每页文字量；
相同记录写入衍生来源的 `local-ocr-provenance-1` 检查点。准入清单见 [policy-ocr.json](policy-ocr.json)。
抽查已发现个别错字和数字/字母混淆，例如 Moutai 可能识别成 Moutal、Q4 可能识别成 04。
OCR 提供可检索线索，但表格结构、图中关系和精确数字仍须回看原页。
原图保留不代表 OCR 已正确理解原图，也不意味着本轮建立了通用 OCR 自动入库服务。
本次 OCR 是为两份缺少正文文字层的扫描件补充检索入口，**不是所有带图片/表格 PDF 的发布前置条件**。

## 4. 解析、清洗与切块

通过正式 `plan_builds → execute_builds` 执行读取、准入、clean-7 清洗、切块和暂存。
PG `corpus_units.raw_text` 保存该构建的权威提取文字，chunk 是检索投影；单元、原文哈希、页码和引用关系保留。
对于 OCR 衍生版，这里保存的是识别文字，不能由“与数据库逐字一致”推导为“与扫描原页完全一致”。
本轮没有生成式摘要清洗、图片向量或 Claims/R2 抽取。

FCC 光通信双语报告首次构建有一个 2,093 字符的英文段落被判为超长。
原因是旧切块规则不识别英文句号。补充保守英文句界：跳过小数、U.S. 等首字母缩写和常见缩写，
只在符合规则的句界切分；保持字符、原文单元引用和 1,800 字符上限。
切块版本升到 chunk-6，只重建这份尚未发布的 FCC 报告；其他既有活动版本不重建。
旧失败构建保留在 [oversized-build-history.json](oversized-build-history.json)。
新版 FCC 仍为 41 块，但块边界已调整，超长检查通过。两份 OCR 构建也使用 chunk-6；
其余 4 份原生文字构建使用先前冻结的 chunk-5。不能把本批所有构建统称为 chunk-6。

## 5. 缺口处理与发布检查

新增 `text_publication.py`，支持显式的“只发布可用文字，承认覆盖不完整”。
记录绑定 source_id、build_id、构建指纹、完整缺口清单、操作者、时间及用户授权引用；不可覆盖修改。
它与原有 `human_gap_review` 完整性凭证分开，**不声称缺失图像已经识别或经人工证明与所有问题无关**。

只允许接受有页码的已知图片／表格提取缺口；未知缺口、无有效保留文字、失败的处理阶段、
原文引用错误及超长块仍被拒绝。原缺口的默认分级、`quality_report`、单元状态和原文不删除。
`check/status` 返回接受依据；检索 coverage 继续标记范围不完整或未知，不自动宣称全文覆盖。

DeepSeek 接受 5 处图像缺口；OCP 接受 29 处。OCP 另有 2 个原规则认可的小图记录，
所以总缺口为 31。中泰双语版的 8 个记录均为原规则的小图记录，无本轮特别放行。
图中独有数字和关系仍不可作为已取回的文本证据。
OCR 衍生 PDF 的原图记录被现有检测器归入 `image_region_small`，这不证明原页图像只是装饰，
也不证明识别准确；本批没有据此声称全文完整。该检测器对 OCR 衍生 PDF 的分级仍有局限。

逐个调用 `check_build_publishable`，再通过 `publish_build` 完成租约、版本和准入检查，
切换该来源的 active build，并写入 PUBLISHED job。
发布记录包含操作者、generation、缺口清单和 `text_publication_id`；重复发布不增加 generation。
逐来源 build ID 和检查结果见 [build-results.json](build-results.json) 与 [ocr-build-results.json](ocr-build-results.json)。

## 6. 发布后的向量增量

继续使用既有 `published-search-text-v1`、Doubao embedding、2048 维及原 profile。
只读取当前活动 build 的 chunk；内容与模型参数相同的输入复用缓存。
本批 392 个新块：原生文字阶段有 201 个未缓存输入，OCR 阶段有 181 个，其他块复用；
不重新计算原有 684 个块的成功向量。
外部 embedding 接收到的是检索文字，不包含原始 PDF 或图片。

截至生成本报告：累计新增请求尝试 386 次，成功响应报告用量 84123 tokens，
当前就绪 1076/1076。
传输超时结果记为 `uncertain`，不伪装成功；已成功项保存并复用。
超时请求是否计费未知，报告用量不代表全部账单。
过程见 `vector-initial-result.json`、`vector-run-*.json` 和 [vector-final.json](vector-final.json)。
以上用量是文档向量增量，不含混合验证的查询向量或 preflight；查询用量随每个 `hybrid-*.json` 保存。

## 7. 验证与边界

- 7/7 个新发布来源通过公开检索服务的针对性词法查询及真实混合查询定位。
- 新增 392 个 chunk 均经 `CorpusService.fetch_verbatim` 取回；逐单元与对应 PG 提取文字核对一致。
- 7 份原件及 2 份衍生件的归档 SHA-256 全部匹配；两份衍生来源的父子关系检查点也核对一致。
- 既有来源 active build / generation、生产库及旧试验库发布指针保持原值。
- 入库流水没有遗留 running job。带缺口发布、幂等、拒绝未知缺口及凭证丢失等回归通过。
- 向量完成后再次运行增量入口：新增外部请求为 0，复用全部 1,076 个块，见 `vector-idempotent.log`。
- 162 项相关测试通过，4 项原有条件性测试跳过；Ruff、所改模块 Pyright、diff 检查通过。
- import smoke：407/407、456/456；符号闭合：505 文件、零缺失；廉价 LLM preflight 通过。

证据见 [verification.json](verification.json) 和 [verification-hybrid.json](verification-hybrid.json)；
本轮定位探针不是独立题集，也不是检索准确率、召回率或主 Agent 回答效果验收。
双语材料保留输入中的中英文／重复文字，本次没有声称已完成翻译一致性或去重质量验收。
全库 coverage 仍可能返回 `unknown`，并带 `admission_pending / partial_published / gap_regions_present`：
库中保留了未活动的历史来源、两份扫描父来源和原有缺口。这与本批 7 份活动正文可查并不矛盾，
不能把它改写成“整个资料库已完整覆盖”。最终批次机器清单见 [batch-result.json](batch-result.json)。

## 8. 实际执行入口与复跑

以下命令均在 WSL 项目目录执行，原始运行输出保留在同目录日志中：

```bash
uv run python .scratch/corpus-new7-20261021/inspect_batch.py
uv run python .scratch/corpus-new7-20261021/run_batch.py prepare
uv run python .scratch/corpus-new7-20261021/run_batch.py build
# 首次发现英文超长段落，修复和测试通过后执行：
uv run python .scratch/corpus-new7-20261021/run_batch.py retry_oversized
uv run python .scratch/corpus-new7-20261021/run_batch.py publish
uv run python .scratch/corpus-new7-20261021/run_batch.py archive_pending
uv run python .scratch/corpus-new7-20261021/ocr_scans.py
uv run python .scratch/corpus-new7-20261021/publish_ocr.py
uv run python .scratch/corpus-new7-20261021/index_vectors.py
uv run python .scratch/corpus-new7-20261021/verify.py
uv run python .scratch/corpus-new7-20261021/verify.py --hybrid
uv run python .scratch/corpus-new7-20261021/write_report.py
```

`prepare` 遇到冻结 manifest 会复用，备份文件已存在时不会覆盖；`build` 跳过已记录来源。
`publish` 对本批已有构建重验并幂等发布；不会扫描或发布其他原文件。
OCR 所需 deb 包已在本批工作目录内保存，脚本会解压使用；不要为查看结果重新生成衍生 PDF，
因为 PDF 元数据或依赖版本变化可能产生新的文件哈希。已发布结果以冻结 provenance 为准。
`index_vectors.py` 正常续跑复用成功向量并跳过不确定项；仅在明确决定重试时才使用
`--retry-uncertain`，可能产生重复计费。不得删除缓存来重跑。
上面的发布命令已执行，不需要为了阅读这份说明再次执行。

只读查看向量状态：

```bash
CORPUS_VECTOR_TARGET_DB=vector_pilot_clean7_20261021 \
uv run python -m plugins.corpus.retrieval.cli status
```

显式试用该库（会调用一次查询 embedding）：

```bash
CORPUS_VECTOR_TARGET_DB=vector_pilot_clean7_20261021 \
CORPUS_RETRIEVAL_RANKING=body-constraints-v1 \
CORPUS_RETRIEVAL_RANKING_TARGET_DB=vector_pilot_clean7_20261021 \
uv run python -m plugins.corpus.retrieval.cli query --mode hybrid --query 'DeepSeek V4.1 Flash 1017'
```

如需撤回本批，应按 manifest 对新增来源执行版本化撤回，保留原件和审计记录。
备份恢复应先恢复到另一个隔离数据库核验，不能直接覆盖当前库或生产库。
本次没有执行撤回或恢复，也没有顺带发布此前的 11 份缺口研报及 17 份订阅 PDF。

## 9. 后续评估优先级

本批完成的是可检索资料发布与入口验证，尚未证明新增领域的检索质量。
下一步用白酒/茅台与 DeepSeek 新材料补充独立问题及原页证据标注，覆盖跨报告、同实体不同日期、
近似错配和不可回答问题，比较词法、向量、混合检索及首条证据质量。
两份 OCR 资料的精确数字问题需先人工核对标注原页；来源/机构/报告日期元数据仍需单独核验，
当前 reviewed-context 元数据只有此前 18 份，不把文件名日期直接写成已核验发布日期。
这些属于后续质量评估，不撤销本批已发布的可用正文。
