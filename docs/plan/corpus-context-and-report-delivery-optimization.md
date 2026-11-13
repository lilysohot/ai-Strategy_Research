# corpus_search 与 corpus_fetch 上下文精简执行方案

状态：**第一步、第二步代码已实施；导航模式于 2026-11-12 按用户要求改为默认开启，供 Web 端 E2E 验证（此前默认关闭）**。第三步已做小范围 Web 端真实模型实测，见 §8；引用纪律与 manifest 回传修复见 §10；身份交付与失败信封补漏见 §11。2026-11-12，v2.6。对应需求：PR-DATA-01、PR-DATA-12、PR-OUT-06、PR-OUT-07。

首阶段目标：**只精简定位与诊断字段，保持现有原文交付和补读决策，不要求所有 search 后都执行 fetch。** search 已实际送达的合格原文足够时直接使用，需要更多内容时再 fetch。文档版本、内部坐标和校验信息由后台保存、解析，不在模型上下文中反复展开。

后续可选流程：search 提供候选与读取句柄，fetch 交付原文与引用句柄。先对指定文档深读等适合场景验证收益，再决定启用范围，不自动全局替换当前模式。

本版替代 v1.1 的实施安排，首阶段只处理这两个工具及其必要消费者。后续 §11 仅补齐已确认的最终交付边界，不扩展通用团队调度、收尾恢复或报告页面重构。减少工具元数据可以改善报告输入，但不能单独解决成员报告拼接等交付问题。

## 1 核心决定

| 问题 | 本轮决定 |
|---|---|
| search 是否只返回一个句柄 | 首阶段保留现有合格原文与必要引用；后续导航模式返回句柄、标题、必要日期和短预览 |
| search 预览能否作为证据 | 新导航模式下不能；需要支持结论时通过 fetch 阅读原文 |
| fetch 返回什么 | 原文、必要的来源信息、引用句柄、续读入口及影响理解的缺口 |
| 定位数据放在哪里 | 复用现有 receipt 存储，完整保留在后台；模型只复制必要句柄 |
| 是否先建设短别名系统 | 不需要。先复用现有持久句柄，每个对象只出现必要的一次；短别名另行评估 |
| 如何实施 | 先精简可见字段且不新增必需工具轮次，再打通句柄读取，按实测结果决定导航模式的启用范围 |

“定位数据不进入上下文”指隐藏内部坐标、版本哈希和重复身份字段。模型仍需持有调用与引用所需的最少句柄。标题、页码、章节、表头、期间、单位和脚注属于理解材料所需的信息，不能一起删除。

## 2 目标工具返回

以下为后续导航模式的目标接口示意，不代表第一步会删除 search 原文，也不代表当前工具已经支持这些参数；占位句柄由后台生成，模型不得自行构造。

### search 返回候选

```json
{
  "hits": [
    {
      "ref": "<持久候选句柄>",
      "title": "报告标题",
      "published": "2026-11-06",
      "preview": "用于判断相关性的短预览"
    }
  ],
  "limitations": []
}
```

每个命中文档保留一个句柄。预览采用检索片段的短展示，初始上限为每项 200 个 Unicode 字符，不生成摘要或另起模型调用；按命中相关性选择，显式标记省略。日期未知时不猜测；日期来自文件名等推断且影响时效判断时保留简短说明。

后台保存该句柄对应的文档版本与命中候选块集合。模型无需再接收 `doc_id`、`build_id`、`source_id`、完整 `context_locators` 和逐摘录 `eref`。无命中、检索降级或筛选范围不完整时，返回简短状态，避免把“没搜到”理解成“库中不存在”。

### fetch 根据句柄读取

目标调用：`corpus_fetch(ref="<候选句柄>")`；默认读取该命中的候选块及必要结构上下文。指定文档深读时使用 `scope="document"`，从该版本的文档顺序开始阅读。两种范围明确区分，候选块读完不表示全文读完。

```json
{
  "source": {"title": "报告标题"},
  "scope": "document",
  "items": [
    {
      "evidence_ref": "<持久引用句柄>",
      "location": "第 3 页",
      "text": "实际送达模型的原文"
    }
  ],
  "next_cursor": "<续读句柄或 null>",
  "fetch_complete": false,
  "limitations": []
}
```

每个独立可引用片段保留一个 `evidence_ref`，后台映射到原文和精确位置。来源信息在本次返回中集中展示；不要求模型额外生成坐标、哈希或引用原文副本。页码不可用时不伪造。续读只传游标，由后台恢复文档版本与读取范围。

fetch 提供原文查证，不代表材料陈述已被独立验证。正文保持逐字内容；分页保留必要表头、单位和脚注。解析缺失、未读完、局部失败等限制仍须可见。`fetch_complete` 只说明请求范围内入库文本的读取情况，不证明原 PDF 提取完整。

## 3 后台保留与模型可见内容

| 信息 | 模型可见 | 后台保留 |
|---|---|---|
| 标题、相关日期、可读页码或章节 | 保留必要部分 | 完整保存 |
| search 命中预览 | 短预览，不作为引用依据 | 保存候选和检索记录 |
| fetch 原文及影响理解的结构 | 保留，按预算分页 | 保存原文和精确映射 |
| 候选句柄、证据句柄、续读句柄 | 按用途各保留最少数量 | 解析及校验 |
| 文档与构建 ID、来源 ID、校验哈希 | 隐藏重复字段，由句柄承载 | 完整保存 |
| chunk、unit、offset、spans、几何坐标 | 隐藏内部定位字段 | 完整保存 |
| 排序分数、索引身份、诊断统计、长协议提示 | 默认隐藏 | 留在审计记录中 |
| 检索范围受限、缺失内容、读取失败 | 保留简短可操作说明 | 保存完整详情 |

按结构生成模型可见视图，不对序列化 JSON 做字符串裁切。完整记录保存成功后才能发出依赖它的句柄。存储或解析失败时明确报错；若保留现有自包含降级路径，必须标明降级且继续执行原有校验，不能返回失效句柄。

### 3.1 如何裁切定位数据

裁切在 corpus 工具返回模型之前完成，采用**字段白名单生成新对象**。不修改数据库原文，不原地删除内部结果字段，也不把完整结果先塞入模型上下文再让模型忽略。

处理顺序为：`取得完整内部结果 → 确定本页正文及范围 → 保存引用与完整元数据 → 构造可见对象 → 序列化并检查预算 → 返回模型`。预算若要求重新分页，重新生成对应正文和引用；最终消息送达后，账本再确认 delivered。

| 返回位置 | 构造可见对象的具体规则 |
|---|---|
| search 每项命中 | 从完整命中生成 `ref/title/published/preview`；必要时补日期依据。`ref` 复用 `sref:<64 位摘要>`，不同时返回 `doc_id` 与 `scope_ref` 两套身份 |
| search 外层 | 保留成功或失败状态、候选列表和必要限制；将 coverage 中影响检索结论的状态转成简短限制，完整 coverage 和排序诊断留在后台 |
| fetch 每个片段 | 从完整 item 生成 `evidence_ref/location/text`；`location` 从已有页码或章节生成。`locator/source_id/units/spans/source_ranges/fragment/semantic_cells` 等内部坐标不复制到可见对象 |
| fetch 外层 | 集中保留来源、读取范围、续读游标、完成状态及必要错误说明；隐藏 `build_id/document_sha256/scope_id/page_id/block_evidence` 等机器字段，`doc_id` 由新句柄入口和游标承载 |
| 结构与错误信息 | 表头、单位、脚注、内容归属和未解决的结构依赖保留为可读内容或限制；失败项的内部 locator 留后台，模型获得失败说明及可操作的重试句柄 |

例如，一个完整 fetch item 含 `locator、text、spans、fragment、evidence_ref`，可见 item 只含 `text、location、evidence_ref`。后台仍保存 `fragment.start/end`，引用解析时据此恢复精确范围。不能通过删除 `text` 中看起来像坐标的字符串完成裁切，原文中的编号或数值可能本身就是证据。

实现使用两个明确的投影函数，例如 `project_search_result(full)` 和 `project_fetch_result(full)`；内部观察器使用完整结果，模型消息使用投影结果。未知新增字段默认不进入模型视图。第一步兼容期额外保留旧调用必需字段，第二步句柄入口可用后再移除。

### 3.2 裁切的数据保存在哪里

Web 运行的保存根目录是 `<run目录>/run/corpus/`。本次样本对应：

```text
/home/administrator/.local/share/frontier-agent/web/runs/7c159a49f0294c85b936ef2e6889765e/run/corpus/
├── search-refs/<64位摘要>.json   完整 search 命中，已有
├── tool-refs/<32位摘要>.json     ce 引用、cpage 游标，已有；cmeta 元数据快照待新增
└── ledger.json                  读取与送达记录；关联元数据快照的字段待新增
```

| 保存对象 | 内容与恢复方式 | 当前状态 |
|---|---|---|
| `sref:<digest>` | `search-refs/<digest>.json` 保存 `{version, target, hit}`；`hit` 包含文档版本、候选 locator 集合、原始摘录及其校验信息 | 已有；新增仅凭 sref 恢复 doc_id 的受校验入口 |
| `ce:<digest>` | `tool-refs/<digest>.json` 的 `kind=ce`，保存 doc_id、locator、quote、source_start/end；用于恢复某段引用 | 已有；**不含全部 fetch 元数据** |
| `cpage:<digest>` | 同目录的 `kind=cpage` 记录保存完整编码游标，恢复版本、请求集合或文档顺序、当前位置等 | 已有；新增无需模型另传 doc_id 的续读入口 |
| `cmeta:<digest>` | 同目录新增 `kind=cmeta`，保存本次完整工具返回及协议版本；search 外层 coverage、fetch 页内完整定位和结构信息都保留在这里 | 待新增；不返回模型，由账本按 tool_call_id 关联，快照中保留对应 sref/ce/cpage |

`cmeta` 复用现有内容寻址、临时文件写入和原子替换机制，扩展 `tool_refs.py` 的类型校验与读取入口；不增加新的数据库或模型工具。它保存本次已生成的完整结果，不额外复制整份文档。超过单记录容量时必须分拆保存并记录关联，或明确失败；不能静默丢掉定位数据后仍声称可恢复。

Web worker 已设置 `CORPUS_SEARCH_REF_ROOT` 和 `CORPUS_TOOL_REF_ROOT` 指向上述目录。未设置时，默认分别是仓库的 `data/corpus-search-refs/` 和 `data/corpus-tool-refs/`。后台读取受控目录，不允许模型提供任意文件路径。

原文主体继续存放在 PostgreSQL 的 `corpus.corpus_units.raw_text`；单元位置与内容哈希也保留在数据库，chunk 的映射位于 `corpus.corpus_chunks`。receipt 是定位、引用与审计记录，不是新的全文库。现有 `ce` 中的 quote 是已返回片段的引用副本。

同会话跨轮沿用现有 receipt 继承机制，并补测新增记录及账本关联的恢复。现有继承有文件数和容量上限；若引用依赖未继承齐全，应明确报不可用，不能当作成功恢复。旧句柄仍被会话使用时不能单独清理它依赖的 receipt。

### 3.3 fetch 如何通过句柄取得原文

以目标调用 `corpus_fetch(ref="sref:<digest>")` 为例，模型只传候选句柄，以下步骤全部由后台完成：

1. **还原候选。**校验 sref 格式，在当前 `search-refs` 目录读对应 JSON；校验文件摘要、记录版本、目标数据库绑定，以及 `doc_id == "cv2:" + build_id`。从 `hit` 取出 doc_id 与有序 `context_locators`。当前 `resolve_scope` 仍要求 doc_id，实施时需增加从 receipt 取得并校验 doc_id 的入口。
2. **确定读取范围。**默认按候选 locators 去重后进入现有批量分页路径，不重新搜索。`scope="document"` 则只复用候选中的文档版本，进入全文顺序读取路径。两者都执行来源准入、权限和任务 unit_range 检查。
3. **读取权威原文。**候选路径复用 `CorpusService.fetch_verbatim(doc_id, locator)` 及现有 reader 分派，根据版本、chunk 映射和单元范围读取 `corpus_units.raw_text`；全文路径复用 `document_page` 和 `service.document_units(doc_id)`，按单元顺序读取同一版本。现有 reader 负责校验内容哈希与映射，不能拿 search 的 preview 或清洗后的检索文本充当原文，也无需重新解析 PDF。
4. **分页并保留定位。**沿用现有正文分片与结构依赖处理，得到本页逐字正文及完整坐标；生成并保存 ce、cpage 和完整元数据快照，再按 §3.1 输出模型可见对象。
5. **继续阅读或引用。**目标续读调用 `corpus_fetch(cursor="cpage:<digest>")`：先读 tool-refs，解码游标恢复 doc_id、范围与位置，再进入相同读取路径。报告使用 ce 时，引用解析器恢复原文及坐标，并结合原有来源校验和实际送达账本检查；无需让模型重写定位字段。

```text
模型的 sref
  → search-refs JSON：恢复 doc_id + 候选 locators
  → 现有 reader：按固定版本从 PostgreSQL 读取原文
  → tool-refs：保存 ce 引用、cpage 游标、cmeta 完整元数据
  → 模型：原文 + 可读出处 + ce + 续读状态
```

新增 `ref` 和独立 cursor 入口时，`doc_id` 参数需改为可选，并在入口按请求类型严格校验；旧 `doc_id + locator/locators/scope` 调用继续兼容。`sref` 用于首次选读，`cpage` 用于续读，`ce` 用于引用，三者不混用。任一步解析或校验失败，返回相应错误，不通过标题重新搜索并替换原文。

## 4 现有实现与必须同步适配的地方

现有 `native-search-evidence-v2` 已将完整命中存入 `search-refs`；fetch 已有 `tool-refs`、引用句柄与游标。复用这些能力，不另建证据库。

当前 fetch 接受 `doc_id` 与 locator、locators、cursor 或文档范围；`excerpts.ref` 可以作为 locator。**当前 `scope_ref` 需要先经 corpus_inventory 展开，不能直接传给 fetch。** 因此目标流程需要新增句柄入口，并在后台完成版本、候选集合和范围解析；不能仅删字段就切换。

| 适配位置 | 必须保持的行为 |
|---|---|
| [search 工具](../../plugins/tools/corpus_search.py)、[search 引用](../../plugins/corpus/search_refs.py) | 提供导航视图，完整候选落盘；预览不进入已读证据集合 |
| [fetch 工具](../../plugins/tools/corpus_fetch.py)、[文档阅读](../../plugins/tools/_corpus_document.py)、[工具引用](../../plugins/corpus/tool_refs.py) | 增加句柄读取入口，输出正文视图；保留分页、引用及原有版本绑定 |
| [证据账本](../../plugins/corpus/ledger.py)、[范围判定](../../plugins/tools/_corpus_scope.py) | 后台有记录不等于模型已读；仅最终实际送达的原文取得对应引用资格；范围限制继续生效 |
| [上下文复用](../../plugins/corpus/context_reuse.py)、[进度判定](../../plugins/corpus/progress.py) | 从内部记录取得版本与位置；不能因可见字段减少而误判重复读取、完成或无进展 |
| 工具说明、结构化预算处理与发布引用解析 | 同步支持新返回，接受句柄并解析原文；不要求模型补回隐藏字段 |
| [跨轮 receipt 继承](../../server/corpus_receipts.py) | 同会话恢复后句柄仍可用；延用运行隔离、权限与完整性检查 |

完整内部结果与模型可见视图必须分开。现有观察器可能先于结果后处理运行，账本又会检查最终消息；实施时同时适配两端，不能只在最后删字段，也不能只靠后台保存成功就标记 delivered。后续预算裁切若移除正文，对应引用不能继续算作本次已送达。

句柄锁定原文版本，不随新版本发布静默漂移；句柄解析仍执行现有访问控制、来源准入和任务读取范围检查。无效、过期、跨运行不可用或越界句柄返回明确错误，不自动改读新版本或扩大范围。

## 5 执行顺序

### 第一步 精简现有返回

保留现有工具参数和引用语义，为 search、fetch 提供面向模型的精简视图，先移除诊断与重复定位数据。此阶段仍保留当前调用下一步所需的 `doc_id`、摘录引用或游标；search 已实际送达的合格原文仍沿用原有引用规则。

不得通过删掉 search 原文、修改提示或发布门规则来强制新增 fetch。后台投影、保存与句柄解析是内部函数，不增加模型可调用工具；第一步验收需包含“search 原文足够、无需 fetch 即可引用”的路径。

先补齐 §3.2 的完整元数据快照，再启用字段投影；同步适配账本、预算处理、复用与进度判定，确保工具外部不再依赖被隐藏字段。保留既有存储记录与审计语义，不在通用运行内核中加入 corpus 专属逻辑。

### 第二步 打通候选句柄到原文

为 fetch 增加 `ref` 入口，与旧输入方式互斥；解析现有 search receipt，支持候选范围读取和显式全文读取。游标独立恢复续读状态。提供第 2 节的可选导航返回，在该模式中删除对模型多余的逐段引用与文档身份字段，暂不全局切换默认行为。

新导航协议必须有明确版本标记，由内部记录与消费者识别，不能沿用旧协议而改变证据含义。同步缩短工具说明：search 负责选择，fetch 负责原文读取，引用只使用实际读到的内容。已知文档并已有可用句柄时，直接 fetch，无需重复 search。

### 第三步 回放验收后切换

使用指定文档深读和开放问题搜索两类任务，对比旧流程、仅字段精简、导航加 fetch 三组结果。第一步只需完成前两组，不以导航模式完成为前置。确认下节条件后按场景启用；旧入口和旧 receipt 保持可用。回退仅恢复工具视图与流程配置，不删除已产生的引用记录。

此前[内容保留方案](corpus-search-evidence-delivery-redesign.md)和[search 与 fetch 契约](corpus-search-fetch-contract.md)允许直接使用 search 原文。本方案在第一步保持该规则，第二步只对新导航结果改为 fetch 后引用；实施切换时同步更新相关契约、工具提示和测试。历史已送达的合格 search 证据继续有效。

## 6 验收条件

- **实际减少上下文：**记录模型最终收到的 search、fetch 返回字符数和可得 token 数，分开统计正文与元数据；同时比较完成同一任务的总工具调用数、总输入量与耗时，避免单次 search 变短却使整体成本增加。
- **读取与引用闭环：**search 句柄可直接 fetch；候选与全文范围不混淆；续读无丢失、无静默跳过；引用可还原到同一版本、同一段实际送达原文。
- **裁切可恢复：**逐项核对被隐藏的定位字段能从 receipt 或其绑定的数据库记录还原；完整快照与投影中的正文一致。模型消息中不得混入 cmeta 或完整坐标；模拟记录缺失、损坏、存储失败及跨轮继承容量不足，检查错误路径。
- **关键限制不丢失：**覆盖长文本、表格、预算裁切、局部失败、无命中、降级检索、无效句柄和读取越界；缺内容时不能报告完整。
- **现有流程可继续：**覆盖单 Agent 与 Agent Team 工具调用、发布引用解析、上下文复用、跨轮恢复及旧 receipt。无需让协调者额外获得新的原文读取权限，亦不减少现有成员交付正文。
- **报告正文可读：**样例报告使用可读来源与必要引用，不因工具提示而展开版本哈希、unit 清单或诊断 JSON；若仍出现成员报告直接拼接，单列为交付问题，不扩大本轮改造范围。

验收以实测结果判断收益，不预设固定节省比例。未证明导航模式的整体收益前，保留现有 search 原文模式；定位数据隐藏可独立启用。

### 性能基线对比的范围

本次引入轻量的性能基线对比，不新增 benchmark 框架、公共评测集、评分模型或运行时工具，不向生产执行链插入评测步骤。复用现有 corpus 测试及工具回放方式，评测依赖不进入运行包。

| 检查 | 如何执行 | 能说明什么 |
|---|---|---|
| 固定结果回放，第一步必做 | 使用同一份 search/fetch 完整结果、相同正文预算，分别运行旧返回与新投影；用临时目录保存 receipt，比较可见字段、正文、引用和序列化大小 | 能否减少元数据且不损失原文或引用；固定回放不能证明模型实际会少调用工具 |
| 后台耗时与存储，第一步必做 | 相同样本和机器交替重复执行，区分首次写入与已有 receipt；记录投影、保存、解析的耗时及写入字节/文件数，报告样本数、中位数和尾部耗时 | 新增代码和磁盘操作的成本；不把本地回放冒充数据库或模型端到端耗时 |
| 实际任务对比，导航模式启用前完成 | 固定任务、资料版本、模型配置、预算与并发，分别运行现有模式和候选模式，覆盖 search 已足够与确需深读两类问题 | 比较总墙钟时间、模型轮次、search/fetch 次数、输入 token、引用正确性和回答完整性；记录缓存条件和重复运行波动 |

本次文档整理不执行真实模型评测。第一步的本地回放不调用模型、不收费；真实任务对比留到实现后执行，样本运行记录仅作为选例和历史参考。功能回归失败不得启用；性能数据报告实际差值，不用单次工具变快推导整个任务提速，也不把时间阈值做成易受机器负载影响的普通单元测试断言。

## 7 实施记录（2026-11-11）

- **第一步（默认启用）：** `plugins/corpus/projection.py` 提供 `project_search_result` / `project_fetch_result` 两个字段白名单投影，在 `ReactToolResultPostProcessor.process` 与 `SwarmToolResultPostProcessor.process` 的消息边界执行，位于结构化预算裁切之后。`on_tool_result` 观察器仍取得完整结果；通用循环内核无 corpus 专属逻辑。投影不删除任何 `text` 或 `items`，兼容期保留 `doc_id`、摘录引用、`scope_ref`、`locator`、`next_cursor` 等旧调用必需句柄。
- **完整元数据快照：** `tool_refs.py` 新增 `kind=cmeta`，复用内容寻址与原子替换，按可见消息摘要绑定；`ConsumptionLedger.metadata_snapshots` 按 `tool_call_id` 落盘关联；`stage_corpus_receipts` 沿用既有 32-hex 继承。写入/容量失败时回退到完整自包含结果并标记 `corpus-visible-unavailable`；收据缺失、损坏或跨轮继承不足时消费者显式报不可用，不猜测隐藏字段。
- **必要消费者：** 账本 `finalize` / `_delivered_corpus_refs` 从后台完整结果计算引用签名，并要求正文仍出现在可见消息中；进度、覆盖与上下文复用观察器改为读取后台结果；`content_acquisition`、`_corpus_handoff` 等 `on_tool_result` 观察器无需改动。
- **第二步（`CORPUS_NAVIGATION_MODE` 默认开启，显式 `off/0/false/no` 可关闭）：** `corpus_fetch` 新增 `ref`（`sref:` 由 `resolve_scope_by_ref` 还原版本与候选块集合，支持 `scope="document"`）、仅传 `next_cursor` 的独立续读，并校验互斥与版本绑定；`corpus_search` 导航返回只给句柄/标题/日期/不可引用短预览；导航 fetch 视图只保留 `source/scope/items[evidence_ref,location,text]/next_cursor/fetch_complete/limitations`。两套结果带 `corpus-visible-v1` / `corpus-navigation-v1` 版本标记；Web profile 复用同一开关，开启时追加导航说明。
- **验收：** `tests/test_corpus_visible_projection.py` 覆盖字段投影、正文一致、裁切可恢复、送达闭环、预算省略不误判、快照失败与跨轮继承、固定结果回放基线（字符数/正文/引用、投影与解析耗时中位数与尾部、写入字节与文件数）；`tests/test_corpus_navigation.py` 覆盖 ref 候选/全文、独立游标、互斥与无效句柄、分发范围、导航视图和引用闭环。真实模型任务对比属于第三步；后续已补做 Web 端小范围实测，结论与遗留风险见 §8。

## 8 默认开启与 Web 端实测（2026-11-12）

按用户要求把导航模式改为**默认开启**：`plugins/corpus/projection.py::navigation_enabled()` 统一判定，「未设置」视为开启，仅 `off/0/false/no` 显式关闭；`server/profile.py::build_prompt_addenda` 复用同一函数，避免工具视图与提示词开关分叉。离线回归在 `tests/conftest.py` 显式钉为 `off` 以保留第一步协议断言，导航测试显式设 `on`，另加默认开启/显式关闭的回归用例。Web 后端已按新代码默认重启（不设置任何环境变量）。

Web 端实测（`results/web-ab/report.md`）：通过 `POST /api/runs` 走真实产品链路，题面为资料库文章文件名，默认臂与导航臂各 3 次。导航臂 `system_prompt` 3/3 含导航策略、两臂均触发 `corpus_search`/`corpus_fetch`，链路有效。结果：默认臂 3/3 `completed` + `publish_status=verified` + `manifest_verified`；导航臂仅 1/3 `completed`，1 次 `exhausted`（第 30 轮 LLM 超时撞 `wall_deadline`）、1 次 `429 AccountQuotaExceeded`（月度配额耗尽，无最终报告、`publish=draft`）。导航臂耗时/token 中位数偏低是失败样本提前终止的假象，`corpus_fetch` 次数并未减少。

**遗留风险（E2E 需重点观察）：** ① `RESEARCH_DISCIPLINE_ADDENDUM` 要求 `doc_id`+`locator` 引用，与导航策略「禁止重建内部坐标」冲突，曾在 CLI 实测中导致 1/3 报告仍写出 `cv2:`；② 导航臂出现 `answer_status=partial` / 清单 `draft` 的报告交付问题；③ 配额耗尽会中断样本，复测需等重置或换端点。默认开启是**为端到端验证服务**，不等于已通过 §6 的收益验收条件。

## 9 文档身份修复：文件名不再是可裁元数据（2026-11-12）

**问题：** 导航版 search/fetch 把文档身份与哈希、坐标一起裁掉，导致「找某篇资料、给出文件名」类任务只能拿命中的章节标题顶替。Web 端对照中，开启臂把《SpaceX：模型能力落后，但算力资源雄厚》（正文小节标题）当成了文件名，而该名字在 220 篇文档标题中不存在。

**修复：**

- `plugins/corpus/service.py` 新增 `document_titles(doc_ids)`：按 `doc_id` 从 `list_documents()` 解析原始文件名，返回 `{"filename", "document_title"}`，30 秒进程内缓存、失败即省略字段（离线测试与 DB 抖动不阻断工具）。
- `corpus_search` 导航视图每命中改为 `ref / filename / document_title / section_title / published / preview`：删掉语义含混的 `title`，`section_title` 只表示命中章节；后台 cmeta 完整结果同步带上身份字段。
- `corpus_fetch` 返回前经 `_attach_document_identity()` 注入身份字段，保证收据与两种可见视图一致；`projection` 的 `_FETCH_OUTER_KEYS` / `_SEARCH_HIT_KEYS` / `_FETCH_ITEM_KEYS` 与导航 fetch 的 `source` 均保留这些字段。
- `NAVIGATION_READ_POLICY` 与 `NAV_SEARCH_HINT` / `NAV_FETCH_HINT` 明确三者的区别：回答文件名用 `filename`，不得用 `section_title` 代替。
- 测试：`tests/test_corpus_navigation.py` 校验导航 search 的文件名与章节标题不同、`title` 已移除、导航与兼容 fetch 视图都保留身份字段。

**验证：** 真实语料检索（`SpaceX`，4 条命中）全部解析到文件名；`2026-11-05_Deep_LLM...pdf` 的 `section_title` 为「SpaceX：模型能力落后，但算力资源雄厚」，与 `filename` 明确区分。`tests/test_corpus_navigation.py` + `tests/test_corpus_visible_projection.py` 29 项、语料回归 223 项通过；`ruff`（CI 范围）、`pyright`（13 项既有）、`import_smoke --stage 1/2`、`check_symbols.py` 通过。Web 后端已按默认开启重启加载本次修复。

## 10 引用纪律与 manifest 回传修复（2026-11-12）

本轮修复引用协议冲突及校验回执重新暴露坐标的问题，与报告交付问题中的“内部信息再次进入上下文”重叠；不能据此断言所有 `partial/draft` 或报告过长问题均已解决。

- **统一引用纪律：** Web 协调者与成员按当前模式使用引用规则，移除强制返回 `doc_id + locator` 的要求。CLI 投研纪律按实际返回协议分流，并区分完整策略卡与报告清单：导航引用已读原文的 `evidence_ref`；兼容模式仍允许直接使用合格 search 原文，仅缺引用句柄时复制已返回的旧坐标。不得仅为凑齐坐标重复 fetch。
- **裁切 manifest 回执：** `manifest_view.py` 在既有 `projection` 边界生成导航回执，保留结论 id、状态、活动结论集、缺失依赖、证据序号和修正建议；语义引用保留送达、版本、质量、校验状态，不展开范围与依赖记录。schema 错误、解析异常和报告绑定错误均不回传后台路径或原始异常详情。兼容模式沿用原回执。
- **保存与校验：** 完整提交清单仍在 `<APODEX_RUN_DIR>/corpus/manifests/`；完整工具回执复用 `cmeta` 存储，位于 `CORPUS_TOOL_REF_ROOT`（未设置时为仓库 `data/corpus-tool-refs/`），通过可见消息摘要恢复。未新增模型工具、数据库或模型调用。导航 manifest 快照写入失败时显式报错，不退回完整内部数据；送达、版本、原文、报告锚点及发布核验不放宽。`supported` 不等于结论语义已证实。
- **防止长回执绕过裁切：** 单 Agent 和团队先对完整 manifest JSON 投影，再进入模型消息；不再先按通用字符预算截断。完整结果仍供内部观察器审计。其他工具保持原有预算流程。
- **文件名补漏：** fetch 优先保留自身身份字段与 `original_names`，缺失时才查目录；目录缺项不覆盖已有文件名，均不可用时明确提示缺失，不用章节标题代替。

**定向验证：** 89 passed，1 deselected（无关的金融工具绑定测试）。范围为 `test_corpus_manifest_projection.py`、`test_corpus_manifest_tool.py`、`test_corpus_navigation.py`、`test_research_discipline.py`、`test_corpus_visible_projection.py`，以及 `test_run_modes.py` 的团队提示和单 Agent 提示拼接用例。同步修正了后者遗漏已有 `ROUND_SCOPE_POLICY` 的旧预期。修改文件的 Ruff 检查通过。

本轮按要求未执行全量测试、真实模型端到端评测或新增 benchmark，也未重启服务。上述结果证明局部协议和校验链路符合预期；实际运行时间、重复 fetch 次数及报告交付质量留到后续统一验证。


## 11 身份交付与失败信封补漏（2026-11-12）

本次仅处理两条运行轨迹暴露的交付与错误回执问题，不增加模型工具，不要求 search 后必做 fetch。

- **统一身份契约：** search/fetch 实际返回的文件名、文档标题和有明确依据的发布日期记入现有消费账本 `document_identities`。最终答案只能逐行精确匹配这些原值（可加行内反引号），后台自动生成并验证身份绑定。夹带正文判断、伪造值、未知日期依据或改变版本均不能走此分支。身份校验不是全文事实校验；仅身份且通过时保持 `complete`，不追加证据横幅。绑定仍落在 `corpus/manifests/`，核验仍在 `corpus/manifest_verification.json`，未新建存储体系。
- **单 Agent 入口：** 在 `no_tool` 退出之前检查身份或现有正文清单。缺清单/绑定不通过时最多给一次补正机会；最后一轮不额外重试，未补正仍沿用发布降级。正文的原文、送达、依赖和报告锚点校验保留。
- **团队入口：** 复用相同身份判断。收齐成员报告、满足前置条件后开放 `deliver_answer(content, updates)`，无需先单独 `update_task`；协调者可判断证据不足并继续协调。接受交付后才关闭这条可选路径，强制检查、文件发布、事务回滚及截止时的收尾逻辑保留。
- **失败 fetch：** 补齐 `ok=false` 分页信封及带机器错误码的读取失败路径，导航投影在通用错误直通之前执行；公开工具也遵守有效的 `max_chars` 预算。保留错误类型、错误/未解决项数、恢复建议与未完成状态，不把读取故障伪装成正文超预算。完整内部信封先保存到既有 `cmeta` 工具快照；快照失败显式报错。参数校验等非结构化错误不在这次改动范围内。
- **用途字段：** 不改 schema、不把 `cite` 映射为依赖作用；只澄清证据 `purpose` 可省略及其允许值，身份答案不再填这张依赖清单。通用提示词去重、文风与子代理成本另行处理。

**定向验证：** 244 个相关测试通过（分批执行、去重计数），覆盖新增的身份/退出前补正/错误预算测试、团队原子交付与生命周期、清单和消费账本、导航及 fetch 分页、工具结果裁切；修改 Python 文件的 Ruff 检查通过。脚本模型验证纯身份单 Agent 一次生成完成、混入正文时获得一次补正、团队一次调用同时提交答案与任务处置。

对 `ef93c84325924125863be9d40d8eee40` 的真实失败回执离线重放：6294 字符、17 条错误的内部 JSON，生成 236 字符导航回执，原始信封可从临时快照完整恢复。此为错误回执大小验证，不是整次运行 token 或耗时 benchmark。

未运行全量测试、真实模型 E2E 或新增 benchmark，未重启服务。单 Agent 正常身份交付只增加本地校验；需要补正时最多增加一次纠正机会。团队减少一轮的条件已通过脚本验证，真实运行耗时与 token 收益留待统一全量验证。

## 12 六项收敛与贯通验收（2026-11-13）

本轮修复审查发现的断点；不新增模型工具、不强制 search 后 fetch，不处理无关全量失败。

| 收敛项 | 最终行为 |
|---|---|
| 分页预算、版本与范围 | v2 按原文字符和最终可见 JSON 双预算装页；单 Agent、团队共用 12000 可见上限。聚合预算按展示视图计量，后台坐标不挤占额度；仍保留每轮总上限。无 ppv 的旧游标走 v1 信封预算，未知版本拒绝；页身份绑定版本、原文摘要、范围、位置、预算和展示模式，v2 游标绑定读取范围。 |
| 最终送达边界 | 有调用 ID 的 fetch 仅通过配对最终消息、可恢复快照、原文区间与引用完整性确认送达，覆盖与引用资格使用该结果；visible_chars 在最终消息处计量。快照拒绝内容被改写的消息。去重首份未送达时，模型收到明确重试回执。内核不再凭任意 protocol 字段跳过恢复处理。 |
| 完整检索映射 | native 检索为每个 context locator 生成完整 native_slices，随 search-refs 保存，消费账本从句柄恢复。document-only 读取也可折算检索覆盖。fetch 的完整 native_target_slices 与本页 native_slices 分开；映射记录升级 native-document-map-v2，旧 v1 记录不冒充完整目标范围。 |
| OCR 展示 | 导航视图传递内容与结构状态；相同默认状态集中在外层，可靠分组仅输出证据句柄列表。unit、offset、row 等内部坐标留后台，不由相邻碎片推断表格关系。 |
| 文档身份 | document_identities 按文档版本合并，保留字段来源及冲突；冲突值不自动取得身份交付资格。导航视图省略与 filename 相同的 document_title，续页不再以 cv2 值回填来源。 |
| 表格统计语义 | search 明示 table_chunks_scope=retrieved_chunks_classified_as_table，source_table_count=null；零个命中表块不表示源 PDF 无表格。 |

两项判据已经定下：配对缺失保持 unconfirmed，并记录 pairing_mismatch 原因，不新增独立状态；只删除诊断字段、保留原文、引用和续读契约的预算视图可以完整送达。

**定向验证：** 389 项相关回归、22 项无网络结构化 ReAct 回放、2 项文档分页评测契约回归通过，共 413 项。新增 `tests/test_corpus_delivery_closure.py` 覆盖两条工作流真实后处理、旧游标与范围绑定、最终送达与覆盖一致性、逐 context 映射、身份合并、聚合预算、快照内容绑定及去重失败提示。修改源文件 Ruff / Pyright 检查通过；两阶段 import_smoke 和 check_symbols 通过。未运行全量测试、真实模型 preflight / E2E，未重启服务。

**真实产物离线贯通：** 对 `70b1e00cc32247e79eefb72a6e46f527` 的历史源文重建后，经过单 Agent 与团队后处理及送达账本，17 份历史页回执（含重复）变为 5 页；272 个单元、17,997 原文字符全部送达，入库文本覆盖率 1.0。五页可见字符合计 48,615，每页均不超过 12000；这不是实际模型总 token 或墙钟时间收益。详情保存于 [.scratch/corpus-context-closure-20261113/replay.json](../../.scratch/corpus-context-closure-20261113/replay.json)。

原 PDF 提取完整性仍为 unknown。按目标文档过滤历史 search receipt 后，26 个检索块仍无权威映射，不补造；此前 34 个包含其他文档范围。离线 retrieval_scope 的 ratio 明确只针对已映射区间，有 unmapped 时 complete 必为 false。后续新检索生成完整映射；旧记录须有权威坐标才能补表。全量回归与真实模型任务比较留待用户统一安排。
