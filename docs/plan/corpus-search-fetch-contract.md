# search / fetch 原文交付契约（待审核）

日期：2026-10-23。按用户指示完成本地代码修改，供审核；未重启服务、未切换默认索引。

后续更新：已加入 [Native search 结果提纯](corpus-search-purity.md)。下文“字段与排序不变”描述契约改造阶段；提纯阶段允许筛掉弱相关来源、改变展示片段。保留来源在同一候选池中的句柄、上下文成员及范围身份不变，原文取证与 fetch 协议不变。

## 1. Agent 应采用的流程

1. 先 search。带 `evidence_contract="native-search-evidence-v1"` 的命中，其 `evidence_spans` 标记的原文区间可用于逐字引用。
2. 只引用实际送达的区间，并使用同一命中的 `doc_id` 与 `context_locators[span.member-1]`。展示的证据可能来自第二个或更后面的块，不能一律引用首 `locator`。
3. 原文已足以支撑结论时，无需例行重复 fetch。缺论证、限定条件、指代、表头、期间、单位、脚注或更多正文时，按原句柄 `corpus_fetch(view="compact")` 补读。
4. 旧版 snippet、未标记的文字、索引说明和句内节选不能直接作证据。句内节选先补读；分页按 `next_cursor` 续读。

完整句段只说明展示未在句内裁断，不保证所有语义依赖完整，也不等于整块、整篇已读。多个节选不得拼成一段连续原文。检索结果只能说明本次允许范围内找到的资料。

## 2. 返回字段与兼容性

保留既有 `doc_id`、`locator`、`build_id`、`chunk_id`、`scope_id`、`context_locators`、snippet 及来源字段。句柄算法、检索排序、版本回读、fetch 参数和分页协议均未修改。

仅原生、经过原文单元验证且有完整节选的命中新增两个字段：

| 字段 | 含义 |
|---|---|
| `evidence_contract` | `native-search-evidence-v1`；旧结果没有此标识，不自动升级 |
| `evidence_spans[].member` | `context_locators` 的一基成员序号 |
| `start` / `end` | 该块权威原文中的节选区间 |
| `snippet_start` / `snippet_end` | 同一节选在解码后 snippet 中的区间，排除展示标签 |
| `text_chars` | 整块正文长度，用来区分片段覆盖与整块覆盖 |
| `text_sha256` | 整块原文摘要 |
| `quote_sha256` | 此节选的原文摘要 |

所有偏移按 Unicode 字符计数，零基、左闭右开。正文仍只存一份：元数据指向 snippet，不再重复返回一份 text。可引用标记与正文由同一次展示选择生成；上下文说明只进索引，不参与证据装配。

单条命中的 snippet、元数据和上下文句柄共同保留；预算不足时继续按既有规则整条省略尾部命中，或返回预算错误，不硬切 JSON。

## 3. 账本与引用校验

- `offered` 继续登记完整候选范围。search 交付的原文片段进入已有 `fetched` 集合；此字段表示服务取回的原文，并非专指调用 fetch。
- 增加 `retrieved_via` 来源记录。search 不伪造 `requested` 或 fetch 调用；重复 search 可以在同一范围追加不同节选。
- 最终工具消息中，句柄、原文区间、长度与摘要同时匹配才认定 search 片段已送达。预算省略、损坏 JSON、仅有同文但句柄不同、用户或模型复述，均不能据此认定送达。
- 已送达片段才参与引用区间覆盖。resolver 仍按版本句柄回查权威原文；撤回、失效、原文不匹配不因 search 标记而放行。后台核验读取不算 Agent 的 fetch 消费。
- 同步修复两个与节选交付直接相关的问题：首尾片段之间有空洞时不再误判整块完整；同一引文多次出现时，允许核对真正已送达的那次出现。
- 保留现有清单与发布规则，不修改 `A4_ENFORCE` 开关；账本接入不代表自动启用新的发布阻断策略。

## 4. 验证结果与审核关注点

### 固定输入回放

12 个查询、31 条原始命中，通过实际 search 序列化和预算处理器回放。

- 20,000 字符预算：31 条全部保留，所有原有命中字段、正文与顺序逐项不变。
- 12,000 字符预算：保留 29 条；Q5 从 5 条减到 3 条，其余查询命中数不变。保留命中的身份和正文不变。108 个节选通过原文回切、消息送达及引用范围校验，无 Agent fetch 登记。
- 12,000 预算下，总返回字符从 73,653 增至 105,874（约 +43.7%）。这是相对上一轮内容增强版本的增量，主要来自证据范围、摘要与新提示。未提高现有预算。

**审核需关注元数据开销。** 当前 workflow 的 search 后处理预算为 20,000；聚合预算收紧时仍可能省略尾部命中。不能把“句柄与排序算法不变”解释成“任意预算下返回条数都不变”。

回放明细：[replay.json](../../.scratch/corpus-search-contract-20261023/replay.json)，复现脚本：[replay.py](../../.scratch/corpus-search-contract-20261023/replay.py)。

### 两道真实查询

显式使用上下文索引实验包、只读检索与原文核验；未改默认配置。

| 样例 | 完整工具返回字符 | 核验节选 | 引用校验 |
|---|---:|---:|---|
| 茅台双锚定价 | 8,691 | 10 | verified，无 Agent fetch 登记 |
| 光模块系统瓶颈与可靠性 | 4,694 | 2 | verified，无 Agent fetch 登记 |

主命中与答案正文保持一致。跨实时调用时观察到上下文数组非首位成员顺序变化，`scope_id` 随之变化：一次茅台结果中第 11、12 个成员交换位置；最终记录中的光模块结果也存在上下文顺序差异。本轮没有修改排序路径，但未定位这些跨调用差异的来源，不能声称实时输出恒定。每次返回的标记均绑定该次数组，并已逐字回查。

记录：[live.json](../../.scratch/corpus-search-contract-20261023/live.json)、[首次顺序差异](../../.scratch/corpus-search-contract-20261023/live-differences.json)、[复现脚本](../../.scratch/corpus-search-contract-20261023/live_verify.py)。

### 自动检查

- 238 项相关测试通过，覆盖原生检索、展示、旧路径、预算、分页、账本、清单及结构化交付。
- 修改文件 Ruff lint / format 通过；核心新逻辑定向 Pyright 通过。
- 全库 Pyright 尚有 21 个错误：其中 service.py 的 3 个 `RankingSession` 类型问题在 HEAD 原文件中同样复现，其余位于本轮未改的部署、清理脚本和监控文件。未将全库类型检查记为通过。
- import smoke：framework 416/416、eval 465/465；符号闭包 514 文件、0 缺失；真实单次模型 preflight 通过。

这些检查验证的是原文交付、身份、范围与契约接线。尚未做真实 Agent A/B，不据此宣称 fetch 次数、总 token、时延或最终回答质量已经改善。

## 5. 审核入口

| 文件 | 本轮职责 |
|---|---|
| [corpus_search.py](../../plugins/tools/corpus_search.py) | 工具文档、返回提示、新字段及预算保留 |
| [corpus_fetch.py](../../plugins/tools/corpus_fetch.py) | 从例行必经取证改为按缺口补读的工具说明 |
| [research_discipline.py](../../plugins/corpus/research_discipline.py) | Agent 统一引用纪律 |
| [display.py](../../plugins/corpus/retrieval/display.py) / [native_live.py](../../plugins/corpus/retrieval/native_live.py) | 一次展示选择同时生成正文和范围标记 |
| [search_evidence.py](../../plugins/corpus/search_evidence.py) | 范围、身份、摘要解析，兼容旧结果 |
| [ledger.py](../../plugins/corpus/ledger.py) | 消费登记、最终消息校验、区间完整性 |
| [service.py](../../plugins/corpus/service.py) | SearchHit 的默认空元数据字段 |
| [test_corpus_search_evidence.py](../../tests/test_corpus_search_evidence.py) | 新契约正反例、真实样例回放与边界回归 |
