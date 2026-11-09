# B0 文档身份审计：登记文件名已存在，未进入历史工具回执

本轮确认了一个具体的信息传递缺口：系统保存了目标来源的登记文件名，但 B0 成员收到的语料工具回执没有交付它。这是已证实的身份元数据缺口；它是否导致继续广搜，尚须 D3 干预验证。

## 查到了什么

目标仍是 B0 的 `cv2:c5370b93f2af2f9181ba248076d5b0224b128c5bd3b58eebf16df9bef6ea3267`。

数据库 `corpus.corpus_sources.original_names` 中登记的是：

```text
2026-11-06_深度_太空算力：SPCX_有望在_2028_年实现_1_GW_在.pdf
```

末尾确实是 `_在.pdf`，没有擅自补成正文标题中的“在轨算力”。这与正文完整标题 `深度|太空算力：SPCX 有望在 2028 年实现 1 GW 在轨算力` 不同。正文标题、章节标题、登记文件名不是同一个字段。

本次通过受保护的只读数据库连接核验：build 仍绑定基线同一 source_id，且来源与发布准入均为 in_scope；当前活动 build 与目标相同。归档 PDF 大小 10,957,643 字节，SHA-256 与 source_id 一致。272 个原文单元的内容哈希逐一通过核验，整篇单元集合指纹与 B0 相同；历史 document 首次回执的 5 个单元文本也逐一一致。

名称取自当前源记录，**不是历史时点的数据库快照**。归档哈希证明文件内容与来源身份绑定，不证明某个文件名天然唯一、永远不变或出现在原 PDF 正文里。系统登记字段是本次事实来源。

## 模型当时拿到了什么

重新扫描 B0 冻结成员消息中的 19 条 corpus 工具回执（14 search、3 fetch、1 inventory、1 manifest）：登记文件名精确字符串出现 0 次；扫描的 original_names、original_filename、filename、document_title、source_path 字段出现 0 次。主协调器没有直接的 corpus 工具回执。

这项检查针对保存的消息，不扩大为“任何隐藏上下文都不可能存在”。原始调用级临时附加消息仍是基线已声明的未知项。

## 当前代码中的断点

1. `plugins/corpus/preparation/source.py` 的来源登记保存 original_names；`contract.py::Source` 和 PostgreSQL repository 均承载该字段。
2. `plugins/corpus/retrieval/native_live.py::refresh_on` 从来源表读取 original_names，保存为内部 names 并用于日期推断；构造 SearchHit 时，title 取自命中块的 title_text。
3. `plugins/tools/corpus_search.py` 序列化 SearchHit，`plugins/corpus/search_refs.py::compact_hit` 再构造 v2 回执，均没有交付 original_names。不能简单归因于最后一次裁剪：字段在前面的命中对象转换阶段就未作为名称交付。
4. `plugins/tools/_corpus_document.py` 的全文分页信封只携带文档/来源身份及正文单元，没有登记名称。扩大全文读取量并不保证读出外部文件名。
5. 后端 `CorpusService.list_documents()` 已能使用 original_names 返回目录 title，但这是另一条接口；B0 成员绑定的工具中没有该方法。不能把“后端存在能力”当成“本次模型获得该信息”。

代码路径证据来自当前工作区，历史字节级代码版本仍按 B0 的限制处理；已核验冻结源文件指纹和本轮 tracked diff 未变化。

因此，当前有依据的修复候选是**传递已存在的文档身份字段**，不需要靠改切块正文来猜文件名。是否能改善收敛，仍不应在测试前下结论。

## 已准备 D3，等待审核

A 保持原始边界输入；B 只在目标 document 回执中增加：

```json
{"original_names": ["2026-11-06_深度_太空算力：SPCX_有望在_2028_年实现_1_GW_在.pdf"]}
```

保持原派工条款、原工具描述、正文和其余回执字段，不叠加 D1/D2 删除。增加 71 个 Unicode 字符，回执从 2532 到 2603 字符，仍低于原 max_chars=3000。没有“现在停止”或“这已经足够”等指令，也不把文件名当正文引文证据。

若补齐真实名称后更常转向交付或必需校验，支持身份信息缺失在该边界有作用；若仍广搜，只能说明补齐名称单独不足，不能直接证明“选择标准提高”是唯一根因。它也可能受既有派工、历史或其他要求影响。

新增模型测试尚未执行。具体 A/B 消息、工具 schema、差异、来源指纹和评分规则见 `results/b0-identity-audit-20261109T065403Z/proposal-B0-D3/REVIEW.md`。

本轮模型调用 0、数据库写入 0、生产代码修改 0。完成的是只读取证、原始文件哈希核验及可审核输入准备。

## 产物

权威取证包：`results/b0-identity-audit-20261109T065403Z/`。

- `identity.json` / `audit.py`：当前登记元数据、内容绑定、只读事务及生产读目标守卫回执。
- `historical-exposure.json`：逐条历史工具回执的名称曝光检查。
- `code-evidence.json`：关键代码片段、路径、行号和文件指纹。
- `prepare-proposal.py`：离线生成测试输入，不调用模型。
- `proposal-B0-D3/`：待审核的单字段对照。

早先只读探查收据 `results/b0-identity-audit-20261109T065207Z/identity.json` 保留；最终证据使用随后通过生产读目标守卫的同目标复核，二者名称、源文件哈希、文档指纹一致，不构成模型重跑。
