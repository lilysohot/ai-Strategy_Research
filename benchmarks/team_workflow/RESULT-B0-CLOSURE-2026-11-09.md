# B0-CLOSURE-1：名称可达性检查结果

**确认全文读取回执未提供准确原始文件名；搜索与目录两条路径未完成评估。整体可达性检查不完整，不应宣称三条路径全部失败，也不应宣布已找到续搜的唯一根因。**

## 实际执行

按审核稿执行 G1、G2；G1 没有返回目录所需句柄，因此 G3 按预定规则跳过。未重试、未追加查询、未执行后续模型 A/B。Agent 模型调用 0 次。生产工具通过原始 Tool.ainvoke 接口执行；没有修改工具返回值或注入原文件名。此次不含完整 Agent 循环、成员终止或协调员交付。

| 检查 | 结果 | 可以得出的结论 |
|---|---|---|
| G1 corpus_search(query="SpaceX", limit=10) | ok=false，4.974 秒 | 严格只读事务拒绝 CREATE TABLE；名称可达性未评估 |
| G2 corpus_fetch(目标 doc_id, scope="document") | ok=true，0.023 秒 | 返回 17/272 个正文单元、来源与版本身份，但无原始文件名 |
| G3 corpus_inventory | 未调用 | G1 没有提供目标 scope_ref/context_locators；没有猜测句柄 |

G2 使用审核稿的默认 max_chars，因此返回 17 个单元；此前单步模型实验的冻结回执是 5 个单元。两者不是相同完整输入，不能直接比较模型行为。本轮没有模型行为比较。

## 可验证的断点：正文读取链路遗漏名称

G2 的 doc_id、source_id、document_sha256 均与此前身份审计一致；整个原始回执没有准确登记名，也没有任何明确表达原文件名的其他字段。首个标题是带日期的截短正文标题，不能据此恢复准确的下划线和扩展名。

此前只读身份审计已确认同一源记录保存了：

`2026-11-06_深度_太空算力：SPCX_有望在_2028_年实现_1_GW_在.pdf`

这里沿用先前封存的源记录证据，没有额外查询数据库元数据，也没有声称该元数据在本轮被重新读取。

当前代码进一步定位到具体边界：

- `plugins/corpus/preparation/document_read.py:21` 的 DocumentUnits 仅包含 source_id、build_id、active、units。
- `plugins/corpus/preparation/document_read.py:54` 查询关联了 corpus_sources，但选择的是来源 ID、当前版本和准入状态，没有选择 original_names。
- `plugins/tools/_corpus_document.py:125` 的 render 信封输出来源、版本、正文及进度，不输出原文件名。

因此，对“需要准确原始文件名”的目标，**此条正文读取路径存在明确的信息传递缺口**。分页范围、全文单元数量和原文件名属于不同信息；继续阅读全文不能替代正式的来源名称字段。这不证明所有工具都不可提供名称，也不证明该缺口解释了所有收敛问题。此前补入名称后仍常续搜，已经说明决策行为还需单独评估。

## 搜索失败属于测试隔离限制

G1 的实际回执是：

> 检索失败（语料库可能未就绪）：cannot execute CREATE TABLE in a read-only transaction

静态代码核对显示 `plugins/corpus/retrieval/native_pg.py:149` 的 `_prepare` 创建连接级 TEMP TABLE native_dates / native_chunks，并将候选数据写入临时表；查询随后使用 pg_temp.native_chunks。

本轮执行器对全部连接设置 default_transaction_read_only=on，将临时表创建也一并拦截。这种隔离比“持久语料只读”更严格，造成与真实检索流程不兼容。**不能把它写成生产检索会修改持久语料的证据，也不能用 G1 推断搜索回执没有名称。** 未捕获异常堆栈或失败 SQL；临时表来源的定位由静态调用路径支持，错误回执本身只证明 CREATE TABLE 被拒绝。

此前方案没有先确认检索的临时表依赖，这是本轮测试设计的缺口。按已冻结的“不重试”规则保留失败，不临时放开连接权限、更换实现或重跑成有利结果。

## 调用成本与完整性

- Agent 模型调用：0；后续 A/B：0。
- 生产公开工具实际调用：2；成功：1；工具错误：1；依赖跳过：1。
- 搜索后端调用 embedding：1 次，HTTP 200，回执 prompt_tokens=32、total_tokens=32。不能将本轮称作零模型服务成本。
- 5 个数据库连接均验证 transaction_read_only=on，目标数据库检查通过。
- 引用状态隔离到本轮临时目录；副本保留在结果包 isolated-references，未复制回生产引用目录。
- Python 文件写入边界未记录越界；工具数据返回未发生脱敏替换，保存的 raw.txt 为原始内容。
- 审核包、原始回执哈希、生产源码指纹、原 cases.json 与 tracked diff 均通过离线核对；未修改生产代码或提示词。

结果包为 `results/b0-closure-20261109T094008Z/`，含审核协议、实际参数、原始回执、执行记录、连接及 embedding 计数、代码证据、assessment.json、audit.json 和 CHECKSUMS.json。manifest 的 completed 只代表执行计划结束；assessment 明确标记整体检查 incomplete。

## 下一步范围

暂不启动随机模型测试。已确认的修复候选应收敛到**来源身份信息从读取层到公开回执的传递**，保持真实名称与 doc_id/source_id/build_id 绑定，不从正文标题猜测，不改写提示词。修复本身尚未执行。

搜索/目录的验证若继续，需要先形成能允许连接级临时状态、同时禁止持久语料写入的测试边界，再按新审核方案补测。不能直接取消只读保护重跑，也不应因为本轮隔离限制转去调整模型提示词。
