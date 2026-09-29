# 01 · 原文与表格的取回和消费（A0–A4）

> 修订：v3 · 2026-09-28。状态：A0–A4 已实施；A4 按评审修订契约重做（C1–C7、S1/S2），清单生产者与全发布出口已落地，**A4_ENFORCE 默认关闭（观测模式），阻断默认启用暂缓**——评审结论：A4 尚不能作为可信的默认发布门。B 组未实施。
> 关联：[总览](README.md)、[准备侧方案](02-fragment-chunking.md)。

目标是让 Agent 取得足以支持当前结论的原文，并能识别标题、表体、未读范围和解析缺口。在相同证据质量下，减少元数据占用、重复补取和逐块调用成本。

## 1. 当前实现与设计边界

| 位置 | 已有行为与本次设计的约束 |
|---|---|
| [service.py](../../plugins/corpus/service.py) 的 `_selected_context_hits` | 按来源汇总多个选择区间，再按原文序合并位置；多个区间可能不连续 |
| [search_pg.py](../../plugins/corpus/preparation/search_pg.py) 的 `_enrich_hits` | 页码／单元格来自首个引用单元；不能当作全部邻接块的完整表结构 |
| [corpus_fetch.py](../../plugins/tools/corpus_fetch.py) | 当前接受 `doc_id` 和单个 `locator`；已有 kind 和结构字段，但正文位于大量元数据之后 |
| [meta.py](../../plugins/tools/meta.py) | `corpus_fetch` 的工具级 `max_result_chars=0`，不代表其他层也不限长 |
| [_runtime.py](../../workflows/stateful_react_agent/_runtime.py) 的 `ReactToolResultPostProcessor` | 存在默认 6,000 字符后处理预算，`corpus_fetch` 不在直接透传名单中 |
| [_overflow.py](../../plugins/tools/_overflow.py) | 单轮结果聚合预算为 200,000 字符；预算仍可能作用于批量返回 |
| [verify.py](../../plugins/corpus/verify.py) 的 `verify_card` | 面向策略卡；历史运行生成 Markdown 报告，不能靠只改此处覆盖实际输出 |

历史样本有 36 个上下文 locator，实际取回 10 个，遗漏包含 15 个 table chunk。它证明存在消费缺口，不证明这些块对应 15 张表，也不证明所有问题都必须读取全部上下文。

## A0 · 正文优先与端到端预算

### A0.1 两种返回视图

先为现有单块返回调整字段顺序，使正文先出现；保留原有字段和语义。随后增加显式 `compact` 视图，并在工作流测试通过后让 Agent 优先使用。`full` 保留诊断所需信息，避免一次替换破坏现有消费者。

紧凑视图包含：

- `text`、`locator`、`kind` 和固定的 `build_id`；多项返回中每个 item 也按正文优先组织。
- 引用所需的最小原文映射、页码／单元身份和结构状态。
- 分片范围、错误和续取游标等控制字段；它们不因节省预算而被删除。
- 完整定位元数据的可解析引用。验证器可以内部按引用解析，不要求主模型每次接收全部几何信息。

完整元数据引用必须固定到同一 build 和内容身份，明确字符偏移单位，并能够还原当前文本片段。只给一个不可解析的 ID 不满足溯源要求。

表格展示可以附加基于已验证行列关系的网格视图，但必须与原文分开。合成的 `|`、补齐空白或重复表头属于展示内容，不能进入逐字引文。无法恢复关系时保留原文并标记结构缺失，不让模型猜测列归属。

### A0.2 三层预算必须共同成立

1. **接口预算**：按最终序列化 JSON 的字符数计算，包括转义、元数据、错误和游标；不能只按正文长度分页。
2. **工作流预算**：ReAct 的后处理须识别结构化分页结果，避免按字符硬切 JSON。不能仅凭工具名无限透传，必须验证其预算协议。Agent Team 的实际后处理路径也需单独接入和验证。
3. **单轮聚合预算**：调度前分配各调用预算并预留控制字段空间，使单项预算与本轮剩余额度兼容。初期可以顺序取证，不能假定并行调用各自合规就不会合计超限。

有效页预算应取上述可用预算的下限。预算不足以容纳最小合法响应时，返回可识别的预算错误或延后调用，不返回残缺正文，也不生成永远不前进的游标。

历史 `body:0005` 用作回归样本：核对最终模型消息能见到其正文、定位与续取信息；记录是否还需要 `recover_result`。正文先出现能改善暴露顺序，但只有端到端预算处理才能解决完整性。

## A1 · 有依据的上下文结构清单

### A1.1 清单的范围与来源

清单绑定一个不可变的 `scope_id` 和 `build_id`，其成员是本次选出的有序 locator 集合。保留每个成员所属的实际选择区间，允许区间不连续。去重规则确定，不引入两个区间之间原本未选中的块。

为所有成员读取其自身可用的 chunk／unit 元数据；不把搜索锚点的首个引用单元复制给邻接块。清单字段至少包括：

| 字段 | 含义与约束 |
|---|---|
| `scope_id`、`build_id` | 范围与快照身份 |
| `total_chunks`、`by_kind` | 对整个范围的块数量统计；与成员集合核对 |
| `locator`、`kind`、`page_range` | 块身份及可证明的页面范围，无法证明时为空 |
| `region_ids` | 所属实际选择区间，不以首尾包络代替 |
| `table_ref` | 有持久化表身份或可靠关系时才填写；否则为空 |
| `structure_status` | `verified`／`partial`／`unknown`，并说明缺失依据 |
| `covered_rows`、`header_refs`、`label_path` | 当前块确实覆盖的结构，不冒充整表 |
| `table_rows`、`table_cols` | 只有掌握完整表网格时才填写，未知为 null 而非 0 |

表格数量按可靠 `table_ref` 去重统计；无法建立身份时只报告 table chunk 数，不展示未经证实的“共有几张表”。不得通过 `max(cells)` 推算整表行列数。

清单过大时也分页：总数和当前页成员分别标识，使用与 A2 共用的游标校验机制，但游标类型必须区分 `inventory` 和 `content`，禁止混用。不能为了展示结构清单再次挤掉正文。

### A1.2 消费提示

提示应表达：“这些块是本次检索提供的上下文候选；标题不包含表体；按问题选择证据范围，涉及表中结论时补齐必要表头、期间、单位及脚注。”

不把提示写成无条件读取所有表。完整阅读整篇研报的任务可以选择全范围；查询某个已明确定位的指标可以选择局部范围。选择及后续缩小范围均进入 A4 账本。

## A2 · 单一批量分页接口

### A2.1 入口和兼容性

扩展已有工具，不同时新建第二套 `band:<start>-<end>` 入口。以下为待实现的接口草案：

```python
async def corpus_fetch(
    doc_id: str,
    locator: str | None = None,
    locators: list[str] | None = None,
    cursor: str | None = None,
    view: str = "full",
    max_chars: int = 6000,
) -> str:
    ...
```

`locator`、`locators`、`cursor` 三者恰选其一。空列表、混合 build、跨文档句柄应明确拒绝。批量输入按首次出现去重并固定顺序；由 A1 清单构造请求时沿用原文序。

保留既有两参数调用及其单块字段语义。小结果可以维持原响应形状并追加控制字段；超限结果必须显式分片或返回错误，不悄悄改写为“已取得全文”。批量和游标模式采用一致的分页信封。`max_chars` 是请求上限，服务仍需按实际运行路径的有效预算收紧。

不承诺一次调用覆盖全部内容。总调用数取决于内容量、预算、超大单元和失败重试；优化目标是减少可避免的逐块往返和重复补取。

### A2.2 页信封和游标契约

页信封至少包含 `schema_version`、`scope_id`、`build_id`、`page_id`、`items`、`item_errors`、`next_cursor`、`exhausted`、`fetch_complete` 和 `unresolved`。

- `items` 包含正文、定位、完整／分片状态及结构状态。分片使用明确的 `[start, end)` 源字符范围，约定按 Unicode 码点计数，并附完整块内容身份供校验。
- `exhausted=true` 只代表这轮游标遍历到终点；有失败、缺失或未完成片段时，`fetch_complete` 仍为 false。
- `fetch_complete` 只描述固定请求范围的取回完成情况，不代表解析无缺陷、整篇研报已读完，或已送达模型。
- 解析缺页、表结构不完整等来源缺陷另行保留，不能因所有已生成 chunk 取完而消失。

游标由服务生成并校验完整性，绑定协议版本、文档、build、请求集合及顺序、视图、当前位置和块内片段位置。续取时不能修改这些绑定项；预算可以在允许范围调整，不得改变源范围。为兼容工具默认参数，游标模式的 `view` 由游标决定，调用方不得借该参数切换视图。

新 build 发布后，旧游标仍只读取旧 build；旧 build 不可用、源已撤回或访问权限改变时，返回相应错误，不自动跳转到新版本。固定游标和相同有效预算重放，应得到同一页内容与 `page_id`；预算变化形成不同页切分时，以源范围去重，不能仅以页序号判断已读。

### A2.3 超大块、失败和前进性

| 情况 | 要求 |
|---|---|
| 普通文本块超出预算 | 优先在已有段／句边界分片，必要时按可映射字符边界分片；每片可独立定位，无遗漏或隐式改写 |
| 表格块超出预算 | 优先按完整行或既有结构单元分片，携带表头引用与必要上下文；不能硬切半个单元格 |
| 最小原子单元仍超限 | 返回 `unit_too_large` 及所需容量／可用替代定位；不空转，也不宣称完整。后续提升受支持预算或专门单元读取须显式请求 |
| 一个成员可恢复失败 | 返回逐项错误，可以继续处理其他成员；该成员保留在 `unresolved`，不得靠游标前移当作成功 |
| 重试失败成员 | 显式创建只包含未解决项的请求，关联原范围；验证器去重后更新原范围状态 |
| 内容身份或 build 不匹配 | 拒绝受影响内容，不混入其他版本；记录错误供重新发起请求 |
| 调用中断／重复续取 | 同一页可安全重放，消费记录幂等，不把重复页计成新增覆盖 |

每个成功页必须推进成员或片段位置；不能推进时必须给出终止性的可处理错误。续取结束、请求取全和最终送达是三个分别计算的状态。

## A3 · 标题身份和可信内容关联

`kind=heading` 保留原始标题文本，并返回 `content_role=heading_only`。标题只证明标题被取回，不能用于证明表体、章节内容或数值已读取。

关联使用列表，允许一对多：每项包含目标 locator／表身份、关系类型、`verified` 或 `candidate` 状态，以及关系依据。依据可以来自明确的结构树、表题归属或持久化关系；候选可以来自同章节邻接信息，但必须与已确认关系分开。

不得把“后面的第一张表”固定为 `points_to`。跨章节、多个附表、跨页续表及无法判定关系时，返回候选或 `unknown`。只读到标题与候选链接时，不能自动满足任何表体依赖。

## A4 · 消费账本与结论证据校验

### A4.1 四种集合和两类完整性

| 状态 | 来源 | 不能混同为 |
|---|---|---|
| `offered` | 检索提供的完整候选范围 | 用户或 Agent 已要求读取的范围 |
| `requested` | Agent 显式选定并请求的范围及原因 | 已取回 |
| `fetched` | 服务成功返回的块／片段范围 | 已完整送达模型 |
| `delivered` | 最终模型请求中，经过后处理和聚合后仍完整存在的块／片段 | 已理解，或上下文压缩后仍保留 |

账本按 source、build、locator、片段范围及内容身份记录。`delivered` 必须在最终消息组装边界核验；只能观测工具返回而无法核验后续截断时，标记未知，不能推断为已送达。引用过的原文与映射持久关联，必要时在上下文压缩后重新取回。

分别计算：

- **范围完整性**：指定范围的必需片段是否全部取回／送达，有没有未解决错误和已知解析缺口。
- **结论证据充分性**：该结论所需的原文、期间、单位、表头和必要脚注是否齐备。有效正文也可以支持财务结论，不要求 locator 类型必须为 table。

跳过块记录为 `skipped`，它仍使原范围不完整。需要缩小范围时创建关联的新范围，保留原范围及变更理由，不能修改分母把遗漏抹掉。全篇阅读任务不能靠缩小范围宣布完成。

历史审计的 `all_returned_context_fetched` 继续作为“提供范围是否全部取回”的指标，与新账本交叉核对；它不是 `delivered` 指标，也不是全部结论的通过条件。

### A4.2 面向实际报告的接入

新增报告证据清单，描述结论 ID、结论文本位置、使用的源／build、引文片段、必要依赖、证据用途及未解决限制。状态由验证器根据账本和原文重新计算，不能接受模型自报的 `complete=true`。

共用校验逻辑必须接入实际报告工作流：

```text
取证与送达账本
  → Markdown 草稿 + 结论证据清单
  → 原文／映射／依赖检查
  → 修正、降级或移除无支持结论
  → 发布经校验报告及对应最终回复
```

现有策略卡路径可以复用校验器，但仅改 `verify_card` 不算接入完成。普通 Markdown 报告、最终回复和输出文件的发布状态都要有验证；缺少清单的产物可以保存为草稿，不得标成“已通过证据完整性校验”。约束放在相应研究工作流，不把通用文件写入工具改成领域校验器。

机器能够证明来源和已声明依赖被覆盖，却不能单靠清单证明模型列出了全部必要依赖。结论语义、表头理解和遗漏率仍需人工金标或独立评估。先记录状态并观察误报，再对明确可判定的缺口启用阻断。

局部报告可以发布，但必须限定范围，对证据不足的结论做修正、降级或删除；不能只附一句“可能不完整”便保留无支持的结论。

### A4.3 实施落点（已接入，观测模式；评审修订契约已落地）

账本与校验器落在 [ledger.py](../../plugins/corpus/ledger.py)，不依赖工作流层：

- **四集合**：`offered`（`corpus_search` 的 `context_locators` + `scope_id`）、
  `requested`（`corpus_fetch` 调用参数）、`fetched`（服务成功返回的块／片段身份）、
  `delivered`（在消息边界按片段文本的 JSON 转义形式核验，完整=``delivered``、
  半截=``truncated``、核验不到=``unknown``；跨路径合并只取更强状态，不因某一路径
  看不到而降级）。`ConsumptionLedgerObserver.on_turn_end` **每轮增量核验**送达快照
  （评审 C3：`last_finalized_turn` 区分「已核验未送达」与「新取片段待边界核验」）。
- **两类完整性分开算**：范围完整性由账本按 `offered` scope 复算（含 `skipped`／
  `unresolved`／`item_errors`；`all_offered_fetched` 作为历史指标交叉核对）；结论证据
  充分性由 :func:`verify_manifest` 重算。
- **校验器不信任落盘字段**：每条结论的状态由账本 + 权威原文重算，模型自报
  `complete=true` 只被记录、不参与判定；缺清单的产物只能标 `draft`。引文区间按
  **已送达片段区间并集**覆盖判定（评审 C1：只读首段 ≠ 整块送达）；非 dict 证据／
  结论条目一律拒绝（评审 C2）；校验基础设施故障整体记 `verification_error`，
  与确定性缺口 `source_unresolvable` 分离（评审 C7）。
- **接入实际路径**：`ConsumptionLedgerObserver` 同时挂到 stateful_react 主循环与
  agent_team 的子代理／主代理观察者列表，共用同一 run 账本；**全部发布出口**统一接
  `publish_boundary`（评审 C5）——agent_team 的 `agent_team_reporter`、agent_team 主
  代理直出／reporter 失败回退、stateful_react 最终答案。skip 条件 = 无 corpus 活动；
  内部 fail-open（异常记日志不阻断），确定性判定结果才降级；enforce 路径追加
  **锚定限定块**（逐条列出问题结论及其锚点）并把 `complete` 压为 `partial`（评审 C6），
  由 `A4_ENFORCE` 显式开启，**默认关闭**。
- **清单生产者已实现**（评审 C3/C4）：[`corpus_submit_manifest`](../../plugins/tools/corpus_manifest.py)
  ——入口 schema 先行（非法条目即拒绝）、**每次提交独立落盘**
  `<APODEX_RUN_DIR>/corpus/manifests/manifest-NNN.json`（多代理／多次提交互不覆盖，
  边界汇总校验聚合、多文件时结论 id 加拥有者前缀防撞）、即时回验逐条返回问题驱动
  **环内修正**（新取片段标 `pending_delivery`，下一轮重新提交确认）、**报告绑定**
  （`report_quote` 逐字锚点 + `report_sha256`；锚点不在最终报告记 `not_in_report`
  压 partial）。绑定语料检索工具即**伴随绑定**清单生产者并注入提示附注
  （与 `web_fetch`→`download_file` 先例同构，profile 少配不静默降级）。
- **落盘为独立 JSON 工件**：`<APODEX_RUN_DIR>/corpus/` 下的 `ledger.json`、
  `manifests/*.json` 与 `manifest_verification.json`；报告只引用 id，验证器读 JSON
  重算。所有写盘／解析失败都吞掉记日志，**绝不阻断运行**。

已知未实现（不得据本文件声称已闭环）：

1. ~~**清单提交的环内修正闭环未经真实模型验证**~~ → **2026-09-29 已在真实模型运行中验证**
   （`company-003` 三档；探针与逐帧证据见
   [.scratch/a4-loop-20260929/report.md](../../.scratch/a4-loop-20260929/report.md)）：
   自然档模型**主动提交清单**（1 次，环内即 `verified`）；引导档与早提交档复现
   「反馈 → 修正 → 重新提交 → 环内 `verified`」，且**含补取分支**——早提交档 t4 提交得
   `partial`（`not_delivered`+`missing_dependencies`），模型据反馈补取 13 次 `corpus_fetch`
   后于 t13 重新提交收敛为 `verified`。**闭环成立**，但验证同时暴露两项边界缺口，故
   `A4_ENFORCE` 仍默认关闭（阻断默认启用继续暂缓）：
   （a）~~**发布边界汇总把被取代的旧候选并入**~~ → **2026-09-29 已修复**（校验语义变更，
   含回归测试）：`write_manifest_file` 现写入代理实例的 `owner_role`（取
   `ExecutionScope.task_id`，每个代理实例一个、跨该代理多次提交不变），
   `_merge_manifests` 改为**跨拥有者并集、同拥有者取最新**，`load_manifest_files` 按
   提交序号数值排序。确定性前后对照（零模型、真实 run 产物
   [replay_f2_fix.py](../../.scratch/a4-loop-20260929/replay_f2_fix.py)）：同一 run 由
   `partial`（supported 2／partial 2，4 条并集）→ `verified`（supported 2，2 条取最新）；
   多代理仍跨拥有者并集（回归测试覆盖）。
   （b）`report_quote` 锚点仅在边界检查、环内不可见，模型无法在环内修正该类问题（见下条）。
2. **`report_quote` 锚点缺环内反馈（F3）**：自然档 4/4 结论在边界记 `not_in_report` 并压
   `partial`，而环内工具（按设计）不做报告绑定检查，模型看不到、无法在环内修正。要让
   该类问题可环内修正，需让工具端拿到（或近似）最终文本锚点，或把锚点检查前移——属
   产品／契约决策，未实施。
3. **`corpus_inventory` 驱动的范围不计入 `offered`**。清单信封按页返回成员，只有当前页
   可见；若据此登记 `offered` 会得到偏小的分母，因此仍以 `corpus_search` 的
   `context_locators` 为唯一提供源。仅用 `corpus_inventory` 直接构造请求的场景下，范围
   完整性无法计算（不冒充通过）。
4. **显式「跳过」无信号**。工具契约里没有「为什么放弃某块」的字段，`skipped` 只能记录
   游标模式下的 `unresolved`／`item_errors`；Agent 主动不取回的块只体现为 `missing`。
5. **模型行为方差（F4，2026-09-29 修复后复核发现）**：同口径重跑三档，模型的清单行为
   差异很大——引导档**整轮零提交**（显式要求下仍未调用清单工具 → 边界 `draft`）；
   自然档**自发 8 次重提且无进展**（同一条 `missing_dependencies` 始终未修，1240.7s／
   1.45M input token）＝ thrashing。这意味着**「是否默认启用阻断」不能只看校验机制**：
   本轮三档会有 2/3 被降级，且原因在模型行为层（不提交 / 不修正），不是机制缺陷。
   启用阻断前需先解决合规与收敛（提示强化、重提上限、或对「未提交」与「已提交未通过」
   分级处理）。复核记录见 [.scratch/a4-loop-20260929/round2_review.md](../../.scratch/a4-loop-20260929/round2_review.md)。

### A4.4 隔离库检索回放与消费侧接缝缺陷（本轮）

按 §2「三类结果分开报告」，本轮先做**隔离语料库检索回放**（30 道冻结题、零模型、PG 只读），
复现脚本见 [.scratch/a4-replay-20260928/replay.py](../../.scratch/a4-replay-20260928/replay.py)
与产物 `replay.json`。回放把「检索提供了什么」到「模型最终看到什么」这条链路上的接缝缺陷
暴露为可复算的计数，共四个 + 一个次级问题：

| 编号 | 缺陷 | 状态 | 落点 |
|---|---|---|---|
| D1 | `corpus_search` 结果超出工作流预算时被按字符**硬切**，成非法 JSON、丢句柄 | 已修 | `corpus_search` 纳入 `structured_result_fit` 分派（[`fit_search_payload`](../../plugins/tools/corpus_search.py)）；两个后处理器给有界预算 20000（覆盖实测最大体 ~18.6K） |
| D2 | `corpus_fetch` 转分页信封后 item 不含 `source_id`／`semantic_cells`，行／列证据在分页路径不可恢复 | 已修 | 单成员信封附信封级 `block_evidence`（整块 `source_id`／`units`／`spans`／`semantic_cells`，块坐标），item 附 `source_id`；消费者 [corpus_product_observations.py](../../tools/corpus_product_observations.py) 跟游标拼回整块后走同一权威校验，产品门 qp/ep 恢复可执行 |
| D3 | `full` 视图的 `units` 单元清单撑爆 `max_chars`，报错无可执行退路 | 已修 | [corpus_fetch._page](../../plugins/tools/corpus_fetch.py) 固定字段超预算时**自动回退 compact** 重试一次（item 标 `view_fallback`），错误文案换成可执行退路 |
| D4 | 分页信封同样以 `ok: true` 开头，被 `fit_structured_payload` 当单块结果压缩，`items`（正文＋句柄＋游标）整个丢失 | 已修 | [`fit_structured_payload`](../../plugins/tools/corpus_fetch.py) 按 `items` 判形；信封只去诊断性的 `units`、保留正文与 `next_cursor`；仍装不下则返回带 `next_cursor` 的预算错误，绝不丢正文 |
| — | `_page` 的片段预算按**原始字符数**算，而信封序列化后换行转义为两字符，正文含多换行时信封略超自身 `max_chars`（实测 ~0.6%） | 已修 | 片段预算改按**序列化转义后**长度记账（`_escaped_len`／`_largest_escaped_cut` 二分求切点），与页信封实际开销同口径；回归测试断言每页 `len ≤ max_chars` 且拼回即整块 |

D2 预算承载的实测边界（决定契约形态的关键约束）：`block_evidence` 与单块 full 视图的
诊断字段内容相同，而分页信封固定开销（游标／`page_id`／`hint`）恒高于单块形状，故
「单块装不下 → 一页 full 信封装得下」对**带派生单元格的表格**在 6000 预算内不成立
（单元格证据随行数膨胀，数值列为含字母文本时 col 标签还会级联取上一行全文）。因此契约
分两层：`block_evidence` 装得下时 full 档整体携带（表格 mid-size 或正文块）；装不下时
诚实回退 compact（整块证据随 compact 省去），超大表由 compact＋产品门 fail-closed 兜底，
回放量化了这一降级面。

回放 v5 结果（D1/D2/D3/D4＋转义记账全部修复后）：`questions=30`、`questions_with_hits=24`、
`offered_locators=5793`、`fetch_calls=5793`、`fetched_fragments=5793`、`delivered=5793`、
`truncated=0`、`unknown=0`、`incomplete_locators=0`、`duplicate_fetches=0`、`errors=0`、
`compact_fallback_items=257`、`questions_all_offered_fetched=24`、
`questions_search_envelope_broken_of_with_hits=0`、`cell_evidence_bearing_calls=684`、
最终消息输入 token 代理 `final_tokens_estimate≈5.08M`。
`compact_fallback_items` 从 v4 的 28 升至 257：D2 的整块证据参与预算探针后，更多大块按
预期走了诚实 compact 回退（不是丢失——`delivered` 仍全量）。

**评审修正（回放 v6）**：v5 的 `cell_evidence_bearing_calls=684` 是跨形状单一总数，
不能用于判断分页路径的实际恢复比例（评审 §5.5）。v6 把单元格证据统计按**响应形状与
回退状态分层**（`cell_evidence_layers`）：单块 684/5536 次调用携带；**分页信封路径
0/257**——257 个信封 item 全部 compact 回退（与 `compact_fallback_items=257` 吻合），
整块证据按设计随 compact 省去。即在本语料／6000 预算下，分页路径的行／列证据实际
恢复比例为 0，依赖 compact＋产品门 fail-closed 兜底；「分页路径恢复单元格证据」在
该预算约束下不成立，提升恢复比例需另立工作项（预算或证据分档），不得引用 684 宣称
分页修复生效。逐项见 `replay.json` 的 `findings`（v6）。

**真实模型冒烟（`replay_model.json` v1，3 题，glm-5.3-flash／react／每题独立会话）**：
复现脚本 [replay_model.py](../../.scratch/a4-replay-20260928/replay_model.py)。选题每
domain 一道 answerable、优先金标带 row/cell 约束的表格题：company-003（财务预测表）、
industry-001（化工景气表）、macro-001（非农叙述题对照）。金标用于**分层选题和事后
评分**（逐字引文空白归一后的取回侧／答案侧覆盖），不进入模型检索决策；**金标参与了
选题与评分，因此这不是独立盲测**（评审 §5.4，原「不参与选题」表述已收敛）。

| 题 | 取回侧覆盖 | 答案侧覆盖 | input tok | 墙钟 | 账本（offered/fetched/delivered） |
|---|---|---|---|---|---|
| company-003 | 6/6 | 6/6 | 504,792 | 552s | 14 / 17 / 17 |
| industry-001 | 5/5 | 3/5 | 139,724 | 200s | 14 / 1 / 1 |
| macro-001 | 2/3 | 2/3 | 177,085 | 96s | 5 / 7 / 7 |

三题合计 821,601 input／27,271 output token、27 轮 LLM、32 次工具调用、墙钟 847.5s；
量级参照：75c6 基线单题（茅台技术面任务）input 855,662／output 34,651、20 轮、35 次
工具调用。两点观察：① 两个表格题金标引文**全部**出现在取回语料中，D2 修复后的分页
路径与单块路径都能承载行／列证据；industry-001 仅 fetch 1 块即覆盖全部 5 个金标引文，
说明检索命中率而非取回量决定成本。② macro-001 唯一缺口 a-3（page:3 表格列）是 agent
未发起对该页的 fetch——真实检索缺口，属 B0（准备侧）要回答的问题，不是消费侧接缝。
另注意评分口径：`fetched_coverage` 按「金标引文解析自 trace 工具结果后子串匹配」计，
初版因二次序列化把换行变成字面 `\n` 而全量假阴性，已修正（trace 结果先解析再展平）。

**A4 状态的诚实读数（评审 §5.3 修正后）**：`replay_model.py` 曾误读 `verification.json`
（实际工件名 `manifest_verification.json`，字段应为 `status`/`conclusions`），导致三题
验证路径恒空。修正重算后，三题验证状态如实为 **`draft`**——这些 run 早于清单工具
存在，模型未提交清单，验证器按「缺清单 = 草稿」标注；不能据此宣称 A4 校验在真实
运行中通过或失败。

### A4.5 评审修订契约（C1–C7、S1/S2，本轮）

评审报告（[.scratch/a4-review-20260928/report.md](../../.scratch/a4-review-20260928/report.md)，
基准 HEAD e4f4e23）结论：**A4 当前不能作为可信的默认发布门；默认启用暂缓**。
按评审 §7 优先级完成的修复与反例回归：

| 编号 | 评审指出 | 修复 | 回归测试 |
|---|---|---|---|
| C1 | 引文区间只按「locator 出现过」判送达，只读首段 ≠ 整块送达 | `_evidence_delivery`／`_covers_interval` 按**已送达片段区间并集**覆盖判定引文 `[start,end)`，缺口记 `not_delivered` | 两片段账本只送达首段的反例 |
| C2 | 非 dict 证据／结论条目被静默跳过，空有效清单伪装通过 | `invalid_evidence`／`invalid_conclusion` 拒绝，属 `_UNSUPPORTED_CODES` | 反例两条 |
| C3 | 即时回验无修正闭环；退出时补账诱发无效补取 | `on_turn_end` 增量核验送达快照；工具侧 `pending_delivery`（新取片段待下一轮边界核验）与 `not_delivered` 分开 | `test_on_turn_end_moves_pending_to_delivered` 等 |
| C4 | 无报告绑定；多代理共享单文件被整体覆盖 | `report_quote` 锚点 + `report_sha256`（不在报告记 `not_in_report` 压 partial）；子清单独立落盘 `manifests/manifest-NNN.json`，边界聚合加拥有者前缀 | 锚点反例 + 子清单聚合/legacy 回退 |
| C5 | 直出／失败回退出口无门 | `publish_boundary` 统一接 reporter、agent_team 直出／回退、stateful_react 三出口；skip=无 corpus 活动；内部 fail-open | 边界四态测试 |
| C6 | 整体标签不能代替逐条处理 | enforce 路径追加**锚定限定块**（逐条问题结论+锚点，只加不删），`A4_ENFORCE` 显式开启、**默认关闭** | `test_enforcement_flag_parsing` 等 |
| C7 | 异常吞掉使 fail-open 失效、缺口误判 | `_is_infra_error` 分类：基础设施故障 → 整体 `verification_error`（不得给已校验结论）；确定性拒绝 → `source_unresolvable` | 两类反例 |
| S1 | full 视图合法原子行装不下时直接报错 | probe 循环按视图候选（full→compact）重试，原子粒度与视图无关；全部失败才报 `unit_too_large`（含 `views_tried`） | 两项分页回归 |
| S2 | 错误响应自身可超预算（无界 `item_errors`） | 错误信封渐进降级：摘要化 → 计数化 → 游标最后丢弃并标记 `cursor_omitted` | 两项截断回归 |

配套：清单生产者 [`corpus_submit_manifest`](../../plugins/tools/corpus_manifest.py) +
伴随绑定 + 提示附注；分层约束修正（评审发现旧稿 `workflows/_shared/corpus_gate.py`
会让 plugins 反向 import workflows，已删除，逻辑并入 `plugins/tools/corpus_manifest.py`）。
测试：[test_corpus_ledger.py](../../tests/test_corpus_ledger.py) 34 项、
[test_corpus_manifest_tool.py](../../tests/test_corpus_manifest_tool.py) 11 项、
S1/S2 回归等 A4 相关 130 项全绿；ruff／pyright／import_smoke／check_symbols 通过。

两点**显式声明的语义边界**（评审 §4 要求明确，不得含糊）：

- **enforce 档的草稿保留是较弱产品目标（评审 C6）**。原方案（本文件 A4.2，原
  v1 §177）要求对具体无支持结论**修正、降级或移除**；当前 enforce 档选择「原文
  保留 + 追加锚定限定块 + 整体压为 partial」——读者仍能看到原强断言，只是旁边带
  定位锚点的未验证声明。这比原方案的语义弱，是显式选择的过渡档：确定性、无 LLM
  调用、可复算，但不等于已完成原方案的逐条处理。若要对齐原方案，需逐条改写或
  移除（LLM 参与或更严格的确定性模板），属后续工作项。
- **报告文件与最终回复的同步边界（评审 C5）**。发布边界的校验对象是**最终发布
  文本**：reporter 路径即报告全文（边界改写后的同一文本流向 `final_answer` 与
  trace 终态，二者天然同步）；stateful_react 路径即最终回复。`/outputs` 下由文件
  工具另行写入的报告文件**不在边界校验范围内**——其内容与最终回复的一致性当前
  不由 A4 保证，清单的 `report_sha256` 只绑定边界校验的那份文本。这是已知边界，
  归入 B 组前的待办（输出文件状态验证属原方案 A4.2 的未覆盖部分）。

## 2. 验收与交付顺序

| 测试类别 | 关键场景与通过条件 |
|---|---|
| 预算与展示 | `body:0005`、转义字符、大元数据、多个并行返回；最终模型消息仍是合法结构，正文和游标完整 |
| 范围与清单 | 不连续区间、重复成员、未知表身份、首单元不含全表；成员和统计可复算，不引入中间块 |
| 分页 | 超大文本、超大表格行、最小预算、末页、页重放、部分失败、源撤回、旧游标；无静默缺失和无限续取 |
| 标题关系 | 标题无正文、多表、跨章、跨页续表；候选不能冒充确定归属或已读取 |
| 消费判定 | 服务取回但后处理截断、只读部分片段、显式跳过、范围缩小；各状态严格区分 |
| 结论证据 | 正文已有有效财务证据、缺单位／期间／脚注、表头错配；既不误拒绝有效正文，也不接受缺依赖结论 |
| 工作流 | 从检索到普通 Markdown 报告及最终回复；复现未通过检查的产物不能被标记为已校验 |
| 成本对照 | 固定同等证据范围和正确性标准，比较工具调用数、重复补取、模型输入 token 与延迟 |

先用固定返回和模拟模型请求验证协议与工作流接线，再进行隔离语料库回放，最后做真实模型效果评估。三类结果分别报告，模拟通过不等于真实运行通过。

交付顺序为 A0 → A1／A2 → A3 → A4 约束启用。A0–A3 与 A4 的账本／校验器／双路径接入均已实施并有协议样例与失败样例（见 [tests/test_corpus_ledger.py](../../tests/test_corpus_ledger.py)）；A4 当前为**观测模式**，阻断约束须待固定任务回放与成本对照取得基线后再启用。B0 及后续准备侧改动尚未实施，本文件不能据此声称已完成准备侧质量改进。
