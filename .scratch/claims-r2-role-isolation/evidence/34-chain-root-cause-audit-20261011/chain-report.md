# items 数据链路根因报告（Issue 34 汇总重算）

- 日期：2026-10-11
- 口径版本：`items-chain-accounting-v1`
- 状态：**结论报告**，零调用、只读，未改动任何冻结物、未发起任何模型调用
- 性质：本文是分析汇总，**不是交付物、不入冻结链**；可入冻结链的只有 §7 中标注为代码/契约/门的条目
- 覆盖票号：Issue 28（门）、29（金标审计）、30（契约补签）、31（run-1/run-2）、32（v6 重冻结门）、33（评分门 Stage 1）、34（链路审计）、35（金标回溯）
- 修订：r1（2026-10-11，**签认前**补记，同样零调用只读）：新增 §1 第 6–8 条、§2 五条实测输入哈希、§3 L9 补记、§5.4–§5.7、§6 末段限定、§7 第 7–9 项、§9 两行裁定项。既有结论、既有输入哈希与 §8 范围外清单**未改动**。
- 修订：r2（2026-10-11，**签认前**补记，零调用）：据 `evidence/36-l9-redo-and-baseline-20261011/` 实测修订 §3 L3 行、§5.2 表第 2 行、§6 与 §7-8 状态，新增 §5.8。修订依据为产物哈希，见 §5.8 表。
- 修订：r3（2026-10-12，**签认前**补记，零调用）：据 `evidence/37-store-baseline-and-route-decision-20261012/` 实测**收回 r2 的 EC-1 与「route a 无法产出契约形态记录」两条**（其候选基线取自门 33 工作台投影，非生产端产物），新增 §5.9 与 §7-10，§9 增路线裁定行。
- 修订：r4（2026-10-12，**签认前**补记，零调用）：执行 §7-10，产出 `evidence/38-gate33-workbench-rebuild-20261012/`（工作台 v2 严格超集），新增 §5.10，§7-10 标为已完成。

## 0. 口径声明（先声明谓词，再看数字）

此前同一问题在不同轮次得出不同节点数，根因是**谓词未声明**。本报告所有计数一律按三元谓词给出：

> **层级（L1–L9）× 性质（缺陷／事件／未做／已闭合）× 是否阻塞出分**

三条硬规则，此后不再例外：

1. **"测量"不算节点。** L9 是对 L3∩L7 的可执行验证，不构成第三个坏节点。
2. **"非根因"不等于"无问题"。** 未被证明是根因，只能记 `not_root_cause`，不得写成"通过"。
3. **"已修"不等于"已过门"。** v6 消除根因（有双臂实测）与门 32 未通过（`structural_fail`）是两条并列事实，不得互相替代。

**同一问题在各谓词下的确定答案：**

| 问法 | 答案 |
|---|---|
| 根因接缝有几个 | **1**（L3 ≡ L7，同一接缝两侧） |
| 阻塞出分的位点有几个 | **3** |
| 执行链（生产端）未闭合有几个 | **1 缺陷 + 1 事件** |
| 评分链未闭合有几个 | **2 + 1 项结构性不可执行** |
| 已闭合的有几个 | **2** |
| 记账/判据/口径缺陷有几个 | **4** |
| 明确非问题有几个 | **5** |

## 1. 结论摘要

1. **链路不是全坏，只坏在一个接缝**：抽取侧字段契约与评分侧字段契约描述的是两种记录（L3 ≡ L7）。源、快照、槽位粒度、协议、校验、装配经实测均成立。
2. **接缝之外还有两类真实问题**：一起基础设施事件（1 个包 = 7 条 critical 金标）、一个我方缺陷（2 槽信号标注过强，连带丢 2 条已产出条目）。
3. **出分被三件事同时卡住**：接缝未定修复路线；Stage 2 人工裁定按现行契约**结构上不可执行**（`unresolved_candidates_max = 0` 而草案阶段仍有 203 条 unresolved）；7 条 critical 已被物理丢失。
4. **决定性量化结论**：即使接缝修得完美，**四项门槛同方向不可达**（分源召回 0.682 < 0.80、md 分源接受数上限 15 < 20、risk/condition 0.762 < 0.95、critical 5/12）。补跑那一个包是必要条件，不是可选项。
5. **契约是三方记录形态中的孤例**：生产端不产出它、金标也不完全使用它。权威侧是金标，不是契约字段清单。同一病灶在阈值上重现：评分器不读契约也不读门，另存一套阈值（0.95/0.90 vs 权威 0.85/0.80）。
6. **金标"有问题"只在记账层（r1 补记）**：语义层经审计成立——48/48 逐字可回取、0/48 缺契约必需字段、condition 角色全部带 `condition` 载体、xyl 签认、Issue 29 判 `gold_meaning_sound=true`；确有问题的是契约绑定／`validation-report`／manifest 输入哈希三处（§5.3）。**修复方向不是改金标字节。**
7. **L9 的 `19/48` 不构成"路线 a 便宜"的证据（r1 补记）**：该臂的候选"规范字段"由金标字段直接注入，属契约 `matching.projection` 明文禁止的做法；且金标有 3 个字段（`attribution`／`source_stance`／`estimate_status`）不是候选字段的函数。详见 §5.4、§5.5。
8. **本报告的修复方案不是天然普遍的（r1 补记，§5.7）**：只有机制层（评分器读契约 + 阈值单源 + 冻结链校验契约绑定）修完通用；读路径规则**有条件**普遍；补跑那 1 个包与 L6 两槽属本案、不推广。

## 2. 输入清单（只读，sha256 实测）

| 产物 | sha256 |
|---|---|
| 48 条非表格金标 `10-quality-gold-freeze-20261008-r2/frozen-gold.json` | `603de5e6…a7de2` |
| 评分契约 v3 `10-quality-gold-expansion-20261008-r2/scoring-contract.json` | `d9bc51f2…5a7ce` |
| 门 28（再绑定后）`28-…/r0-zero-call/preregistered-gate.json` | `987772e9…b2684`（文件哈希；其 `quality_requirements_status=signed`、`metric_basis=…-v3`、`high_risk_item_assertions_required` = 16 条，均已核对） |
| 门 32 冻结清单 `32-…/r0-zero-call/freeze-manifest.json` | 内部自哈希 `1a0e008a…142f5` |
| 门 32 门哈希（内部） | `6fb47e79…fba8` |
| 门 32 判定 `32-…/live/gate-decision.json` | `66946411…33a65` |
| 门 32 treatment 候选 `32-…/live/candidates.json` | `7a09c9e3…c7a70b` |
| 门 32 残差归因 `32-…/live/residual-attribution.json` | 内部 `4197d1a4…25ea4c7` |
| 门 33 Stage 1 工作台 `33-…/workbench.json` | `e00d8ae6…a489777` |
| 门 33 草案预览 `33-…/draft-preview.json` | `2337a1ab…e8f6b2e` |
| 链路审计 `34-…/r0-zero-call/chain-audit.json` | `55ad2fac…207041` |
| 链路审计（可读）`34-…/chain-audit.md` | `05bbd3db…12f16ff` |
| 金标回溯审计 `35-…/r0-zero-call/gold-audit.json` | `2802b614…34c2bca` |
| 金标回溯审计（可读）`35-…/gold-audit.md` | `54f1c5e1…ae1ef18` |

> r1 补记新增的实测输入（sha256 实测、只读；上文既有哈希未改动）：
> 33 裁定草案 `33-…/r0-zero-call/adjudications.draft.json` = `972acca8…4e89e`；
> 33 草案生成脚本 `33-…/r0-zero-call/build_adjudication_draft.py` = `7d839413…998a6`；
> 本报告审计脚本 `34-…/r0-zero-call/audit_chain.py` = `86f840e2…efc1b`；
> 评分器 `plugins/corpus/structured_scoring.py` = `172ce465…874f1`；
> items 生产端协议 `plugins/corpus/material_semantics.py` = `1305dba1…67a5e`。

> r2 补记新增产物（零调用只读，sha256 实测）：
> `36-…/r0-zero-call/preregistered-l9-redo.json` = `d1c5672e…f74fd`；
> `36-…/r0-zero-call/l9-redo.json` = `acd268f2…93f99`；
> `36-…/r0-zero-call/baseline-control.json` = `fc4a47cb…cb93`；
> `36-…/r0-zero-call/l9_redo.py` = `12fc694f…9187`（11 条输入哈希见其 `MANIFEST.json`）。

> r3 补记新增产物（零调用只读，sha256 实测）：
> `37-…/r0-zero-call/preregistered-store-baseline.json` = `54195990…2ad00`；
> `37-…/r0-zero-call/store-baseline.json` = `e5133654…a3fc0`；
> `37-…/r0-zero-call/route-decision.json` = `4760e199…351747`；
> `37-…/r0-zero-call/store_baseline.py` = `3227d132…9fb4c`；
> 输入含 store 运行对象 `5164a8c1…`（md）与 `08fe8d9e…`（docx），见其 `MANIFEST.json`。

> r4 补记新增产物（零调用只读，sha256 实测；取代门 33 `workbench.json` `e00d8ae6…a489777`，后者字节未变）：
> `38-…/r0-zero-call/preregistered-workbench-rebuild.json` = `72c7cb1c…d9538`；
> `38-…/r0-zero-call/workbench-v2.json` = `0bd9e660…36558`；
> `38-…/r0-zero-call/workbench-v2.md` = `6acda8a7…b72f6e`；
> `38-…/r0-zero-call/rebuild_workbench.py` = `fb7aca19…11d0e`。

> 记账：`evidence/34-chain-root-cause-audit-20261011/` 与 `evidence/35-gold-audit-20261011/` 当前**未入库**（`git status` 为 `??`）。

## 3. 逐层实测（修订版）

| 层 | 期望 | 实测 | 判定 |
|---|---|---|---|
| L1 源 → 快照 | 与金标同源同 scope | md：10 units / 10 packets / 76 槽 / 22 金标；docx：14 / 14 / 114 槽 / 26 金标；金标 evidence 全部对得上 | 成立 |
| L2 槽位粒度 | 一个金标命题应能落到候选槽 | 42/48 落在单槽、6 条跨 2 槽、**0 条落空** | 成立（粒度基本对齐） |
| L3 字段契约 | 候选应携带契约必需字段 | 缺 `proposition`/`attribution`/`source_stance`/`speaker_ref`（r2 修订：原记 3 个，实测候选无 `speaker_ref`）；候选另有 5 个契约未要求的字段；condition 角色还缺 `condition` 载体 | **缺陷（接缝·生产侧）** |
| L4 提示词/协议 | 无自相矛盾、格式可控 | v6 下 **0** 次协议违规；v5 对照 **11** 次（md 3 / docx 8） | 成立（**但见 §4.3**） |
| L5 校验/解析 | fail-closed 不放大错误 | 未放宽；v5 对照臂的 82 个失败槽即 `items_error:ValueError`，属按设计放大 | 成立 |
| L6 装配 | 产出可用条目 | 222 条（md 88 / docx 134）；未产出 9 槽 = 7 基础设施 + 2 我方信号；连带丢 2 条 | **须拆：1 事件 + 1 我方缺陷** |
| L7 评分契约 vs 评分器 | v3 要求 condition 载体 + `compound_condition` 子条件计分 | 评分器只有 `(role, source_id, origin, semantic_fields)` 的**严格 identity 相等**；v3 三项要求一条未实现；全仓无任何代码读取评分契约，阈值硬编码于 `plugins/corpus/structured_scoring.py` | **缺陷（接缝·评分侧）** |
| L8 金标构成 | — | 48 条：condition 角色 10、critical 12、risk_or_condition 21；两个条件组同处 `char:5246-5537` | **打击面加权（见 §5.1）** |
| L9 可执行实测 | 语义等价即匹配 | 同 19 条候选：金标字段形态 → `19/48`；候选原生字段形态 → `tp 0 / fp 19 / fn 48`、`recall 0/1` | **证据，非节点**（两条臂均为构造量，见 §5.4） |

L9 原文结论（`chain-audit.json.L9.reading`）：

> the same 19 candidates score 19/48 when expressed in the gold field shape and 0/48 when expressed in the candidate's own schema … adjudication is not "confirm equivalence" but "rewrite the candidate into the contract field set" first — and the fields that rewrite needs (proposition, condition, attribution, source_stance) do not exist on the candidate at all.

> **r1 补记**：上段引文的两臂均为构造量——金标形态臂是把金标 `semantic_fields` 注入候选（§5.4），候选原生形态臂是只手选 6 个字段（§5.4）。故引文中"接缝存在（所需字段在候选上不存在）"成立，但"rewrite 到契约字段集"这一步的**可执行性未获证明**。该修正只动路线 a 的可行性，不动接缝的存在性。

## 4. 对上一版层表的四处修订

### 4.1 L9 不是第四个坏节点
L9 是对 L3∩L7 的**测量**。把它计入节点数会重复计算同一处接缝。因此四个标记（L3❌ / L6⚠️ / L7❌ / L9❌）中，真缺陷只有 **2 个**（且是同一接缝两侧）。

### 4.2 L6 必须拆开：它不是"事故"
- **7 槽 = 基础设施事件**：1 次 `TransportOutcomeUnknown`（`items_error:LlmCallError`，零自动重试），整包作废，`payload_items_kept=0`。
- **2 槽 = 我方缺陷**：`our_contract_signal_overlabelling`，reviewer nuance 记明 "our forecast signal was too strong" / "our evidence signal was too strong, and two already-produced items were discarded with the slot"。零调用可修，但属协议变更，须单独裁定。

### 4.3 L4 的"成立"不能读成"过门"
门 32 终态为 `structural_fail`，未满足 4 项：`protocol_status_valid`（因 items task 未成功而 `not_checked`）、`failed/partial/invalid/duplicate == 0`、`completed_min`、`execution_status_succeeded`。同一产物又记 `root_cause_status = "eliminated"`。**两个结论并列且未规定哪个代表本次执行结论——这正是此前判断漂移的直接来源。** 正确读法：L4 关于"根因"的结论成立；门的"结构完备性"结论不成立；两者不得互相替代。

### 4.4 L8 不只是"放大器"，它决定了修复的可行性
见 §5.1 与 §6：字段缺口与传输缺口**打在完全相同的 7 条记录上**，且这 7 条占 12 条 critical 的 58%。

## 5. 前版未记的发现（§5.1–§5.3 原版；§5.4–§5.7 为 r1 补记）

### 5.1 同一批 7 条记录被两个缺口同时打中

被传输事件丢掉的 unit 是 `char:5246-5537`，而金标的两个条件组恰好都在这个 unit 内：

```json
{"group_id": "opening_watch_position", "target": "NT-I14",
 "conditions": ["NT-I42", "NT-I13", "NT-I43"], "locator": "char:5246-5537"}
{"group_id": "stop_loss", "target": "NT-I16",
 "conditions": ["NT-I15", "NT-I17"], "locator": "char:5246-5537"}
```

- 这 7 条（NT-I13/I14/I42/I43 + NT-I15/I16/I17）**全部是 critical**；
- 契约 v3 的 `condition_role_read_path` 正是为条件组设计的 → **数据被传输丢掉，读路径缺口又让它们即使有数据也匹配不上**；
- 因此它们是链路上受损最重的记录，且受损原因有二。

### 5.2 契约是三方记录形态中的孤例

| 记录形态 | 字段数 | 差异 |
|---|---|---|
| 契约 `role_required_fields` | 9 | 基准 |
| 候选 `semantic_fields` | 10 | r2 修订：缺 **4**（`proposition`/`attribution`/`source_stance`/**`speaker_ref`**）；多 5（`text`/`value`/`behavior_status`/`temporal_frame`/`unknown_fields`）。原记 11/缺 3 系把 `speaker_ref` 计入候选侧，实测 `key_present=0` |
| 金标 `semantic_field_keys` | 13 | 比契约**多** 4（`behavior_status`/`condition`/`estimate_status`/`temporal_frame`） |

即：**契约描述的记录形态，生产端不产出、金标也不完全使用。** 而金标是 48/48 逐字可回取、xyl 签认、Issue 29 判定 `gold_meaning_sound=true` 的一方。故修复方向的权威侧应为**金标**，而非契约现有字段清单。此项修订了此前"接缝两边不一致"的表述。

### 5.3 记账与口径缺陷 4 条（游离于链路之外，但会污染结论）

| 项 | 实测 | 出处 |
|---|---|---|
| 契约绑定漂移 | 金标冻结链记录 `2eb24be7…`（v2），实际签认 `d9bc51f2…`（v3），`match=False`；freeze-manifest 输入哈希仅 **7/8** 匹配 | `gold-audit.md:6,8` |
| 签认链空缺 | `validation-report: status=valid_review_draft, human_accepted_counts={}`，却与 frozen-gold 的"48/48 accepted"并存 | `gold-audit.md:7,11` |
| 门 32 判据与被测对象不同轴 | 用"结构完备性"判据去测"协议修复"，一次与协议无关的传输抖动即可使 `protocol_status_valid = not_checked`，结论无法被确认 | `gate-decision.json:28-62` |
| **阈值双源不一致**（与 §5.2 同一疾病） | 门 28（signed，权威）items 口径为 `target_recall_overall_min=0.85`、`candidate_precision_min=0.80`；评分器却硬编码 `RoleThreshold(MATERIAL_ITEMS, 19/20=0.95, 9/10=0.90)`、`risk_condition_recall_min=19/20`。评分器既不读契约也不读门，阈值另存一份 | `preregistered-gate.json.quality_requirements`；`structured_scoring.py:334-339` |

> §5.2 与上表第 4 行是同一病灶的两个样本：**接缝处存在多份"真相"**（记录形态 3 份、阈值 2 份），而评分器不读任何一份外部真相。

### 5.4 L9 两条臂都是构造量，`19/48` 不构成路线 a 的可行性证据（r1 补记）

- `19/48` 那一臂的"候选规范字段"是**从金标直接注入**的：`build_adjudication_draft.py` 对被预填为 `accepted` 的候选写入 `canonical_observed_fields = canonical_fields(gold_row["semantic_fields"])`（`build_adjudication_draft.py:98-100`，`canonical_fields` 见同文件 `:41-47`），即先取该候选被指派到的金标记录、再把该记录自己的 `semantic_fields` 抄成"候选观察字段"。这恰好是契约 `matching.projection` 明文禁止的"不得将目标字符串直接赋给候选并宣称自动语义评分"。
- 因此 `19/48` 只证明"字段完全相同时严格 identity 匹配成立"（定义真），**不证明**任何真实读路径能把候选恢复成契约形态；`accepted=19` 本身也是草案预填的下游结果（`PRE_FILL_CONFIDENCE = {high, medium}`，同文件 `:30`）。
- `tp 0 / fp 19 / fn 48` 那一臂同样被构造：`audit_chain.py:311-319` 只手选了 `text/semantic_type/statement_role/speech_role/perspective/polarity` 六个字段，不是候选的真实字段形态（真实形态见 §3 L3 的 11 个语义字段）。
- 结论（**不改变** §3 的 L3/L7 判定）：接缝存在成立——契约所需字段（`proposition`/`attribution`/`source_stance`，condition 角色另需 `condition` 载体）在候选上确实不存在；但报告 §3 L9 原文自己写的"must state how equivalence is evidenced"**至今是空的**，故"路线 a 便宜"目前无可执行证据。此处修订的是路线 a 的**可行性**，不是接缝的**存在性**。

### 5.5 有三个契约字段不是候选字段的函数（r1 补记）

实测金标取值（`frozen-gold.json`，48 条 `material_items`）：

| 字段 | 实测取值分布 | 能否由候选现有字段派生 |
|---|---|---|
| `attribution` | 报告作者 22 / 未署名讲者 19 / 讲者转述的未明确来源 4 / 材料转述的公司 2 / 材料转述的德科立 1 | 需先定义一套与金标同义的归属分类词表；候选无对应字段 |
| `source_stance` | reported 44 / **challenged 4** | **不能**。NT-I45 的 `challenged` 只能从 `context_evidence` 原文（"渗透率反正都是吹牛的，都没准数的"）读出，候选 schema 无承载字段 |
| `estimate_status` | `uncertain` 3 / 空 45 | 候选无此字段；契约只在 `claims` 角色列它为必需 |

即：即使把读路径规则写到最细，`source_stance`、`estimate_status`（以及 `attribution` 的取值）仍须**重抽或按原文判定**。路线 a 的适用范围应被限定为"`proposition`／`condition` 载体 + 枚举字段可覆盖的记录"，不得整体宣称便宜。

### 5.6 claims / material_relations 的同型接缝未验证（r1 补记）

- 本次只测 `material_items`。契约对 `claims` / `material_relations` 另立必需字段清单（`role_required_fields.claims` 含 `subject/metric/period/unit/value/factuality/attribution/source_stance/estimate_status/qualifier`），生产端字段清单按角色各自冻结在提示词字符串里（items 清单见 `material_semantics.py:174-175`，其中确无 `proposition/attribution/source_stance`）。
- 判定：同型接缝在另外两个角色上**结构条件具备，但未实测**，记为 `not_verified`。不得据 items 单角色结果推断"也坏"（那是把推测写成结论），也不得写成"通过"（那是把未测写成已过）。须按 §7-9 做零调用同型审计后方可下结论。

### 5.7 普遍性评估：按本报告修复是否可推广（r1 补记）

| 层 | 内容 | 是否普遍 |
|---|---|---|
| 机制层 | 评分器读契约（现状：全仓零命中，阈值硬编码 `structured_scoring.py:332-340`）、阈值单源、冻结链校验契约绑定 | **普遍**：换数据集／角色／契约版本均受益 |
| 读路径规则 | 写成与记录 ID 无关的字段语义规则则普遍；沿用契约 `review_assertions` 那种逐条 `NT-Ixx` 硬编码则**不**普遍 | **有条件** |
| 案例层 | 补跑被传输事件丢掉的那 1 个包、L6 两个信号槽、Stage-1 助手、`unresolved_candidates_max=0` | **不普遍**，仅本案 |

三条使修复具备普遍性的硬要求（已进入 §7 与 §9）：

1. 读路径规则必须**与记录 ID 无关**，并逐字段给出"候选字段 → 契约字段"的可核验映射与**不可派生反例清单**（§5.5 即首批反例）。
2. 任何读路径必须用**留出记录**实测等价性，且**禁止把金标字段注入候选**——现行 L9 违反此条，须重做（§5.4、§7-8）。
3. 跨角色须各自实测（§5.6、§7-9），不得以 items 单角色结果推断其余角色。

### 5.8 L9 重做与基线实测结果（r2 补记）

> **r3 收回声明**：本节的候选基线取自**门 33 工作台投影**，不是生产端产物。故本节的 EC-1（"4 个字段零载体"）与"route a 无法产出契约形态记录"两条**已由 §5.9 收回/限定**。本节其余结论（EC-2 循环量、EC-3/EC-4 口径、B-1~B-3）不受影响。

产物：`evidence/36-l9-redo-and-baseline-20261011/r0-zero-call/`（零调用只读；幂等可重跑、支持 `--no-write`；预注册先于运行落盘）。

| 产物 | sha256 |
|---|---|
| 预注册 `preregistered-l9-redo.json` | `d1c5672e…f74fd` |
| 结果 `l9-redo.json` | `acd268f2…93f99` |
| 基线 `baseline-control.json` | `fc4a47cb…cb93` |
| 脚本 `l9_redo.py` | `12fc694f…9187` |
| 清单 `MANIFEST.json`（含 11 条输入哈希） | — |

**四臂（现有评分器，严格 identity 相等）**：A 原生形态 `tp 0 / fp 222 / fn 48`；B 金标注入（复现旧 L9）`tp 19 / fp 0 / fn 29`（`recall 19/48`）；C 路线 a 投影（无金标输入）`tp 0 / fp 222 / fn 48`；D 对称字段对齐 `tp 0`；D2 词法包含（探索性、不参与判据）`tp 0`。

> **EC-2 成立**：B 与 C 之差（19 vs 0）即旧 L9 的循环量——`19/48` 全部来自金标字段注入。

**载体可得性（按记录，48 条）**：`proposition` 与 5 个枚举字段 39/48；`speaker_ref`／`attribution`／`source_stance`／`estimate_status` **0/48**；`condition` **1/10**。

> **EC-1 触发并扩大**：零载体必需字段为 **4 个**（含 `speaker_ref`），故 route a 无法产出契约形态记录——记录级上界（strict）= **0/48**。
> **EC-4**：仅按有载体字段计为 **35/48**，其中 9 条为「覆盖槽位内无候选」（全部属 md）。两个数字不得合并表述。

> **归因口径（必须随数字给出）**：载体可得性按「设计意图的覆盖槽位」统计（与 §3 L1/L2 同法）。identity 匹配**不含槽位**，故 39/48 属**受限口径**；不受限口径（源内任一候选）下 proposition 与 5 个枚举字段均有候选。**两份口径都不改变 EC-1**（4 个字段在两份口径下都是 0/48）。据此**不得**用 39/48 断言 overall recall 不可达。

**backlog（判据外新发现，不回流本次）**：

- **B-1**：覆盖槽位内无候选的 md 记录为 **9** 条，而非 §6 假定的 7 条——除丢包区 `char:5246-5537` 的 7 条外，另有 **NT-I06**（`char:1393-1655`）与 **NT-I41**（`char:5055-5071`）；二者未出现在 residual-attribution 的 9 个未产出槽位归因里，须单独裁定性质。
- **B-2**：D／D2 均为 0，但两臂要求 5 个枚举字段逐字相等，故 0 无法区分「枚举值不一致」与「命题文本不一致」；该区分未预注册，须下一轮预注册后再测。
- **B-3**：条件载体在实践上近乎不存在（1/10），契约 v3 新增的 `condition_role_read_path` 几乎没有可读数据。

**基线（control 臂，诊断口径）**：现状评分器在原生候选上 `rate_gate_passed=False`、`live_trial_ready=False`、`risk_condition_recall=0`、12 条 critical 全缺；评分器硬编码策略（0.95/0.90）与门 28 权威阈值（0.85/0.80/20）两套 blockers 已分别落档。

### 5.9 store 层基线：收回 EC-1，给出路线 a/b 的裁定依据（r3 补记）

产物：`evidence/37-store-baseline-and-route-decision-20261012/r0-zero-call/`（零调用只读；幂等、支持 `--no-write`；预注册先于运行落盘）。候选基线改用**生产 store 产物**：`32-…/live/treatment-store/<slug>/objects/…`（`material-semantics-32`，md 88 items/76 slots、docx 134/114；item→slot 按证据跨度包含，与门 33 的分配一致 222/222，未可归属 0）。

**收回 1：零载体必需字段不是 4 个，是 1 个。** store 有两层：

| 层 | 内容 | 语义字段 |
|---|---|---|
| layer A | `understanding.items`（生产端产物） | 11，**含 `speaker_ref`** |
| layer B | `structured/store.py::_material_records`（store 自身投影，实测调用） | 7，**含 `attribution`、`condition`** |
| 门 33 工作台投影 | 裁定用工作台 | 10，**丢 `speaker_ref`** |

契约 9 个必需字段的载体：`proposition`（`text` 承载）、`semantic_type`/`statement_role`/`speech_role`/`perspective`/`speaker_ref`/`polarity`（layer A）、`attribution`（layer B，**口径过粗**：值域仅 `document_voice`/None）、**`source_stance` 无载体**。
⇒ **零载体必需字段 = `{source_stance}`。** r2 的"4 个"是把门 33 投影当成了生产端。

**收回 2：`route a 无法产出契约形态记录`不成立。** layer B 已具备契约形态所需的 `attribution`/`condition` 派生（我方代码，零调用可复用）。

**新结论：口径差是主因，不是字段缺失。** 逐字段「任一覆盖槽位候选与金标相等」的记录数（raw → 归一化后）：

| 字段 | raw | 归一化后 | 口径差可消 | 抽取差剩余 |
|---|---|---|---|---|
| `perspective` | **0**/48 | 32/48 | **+32** | 16 |
| `speech_role` | 34/48 | 39/48 | +5 | 9 |
| `polarity` | 32/48 | 32/48 | 0 | 16 |
| `semantic_type` | 27/48 | 27/48 | 0 | 21 |
| `statement_role` | 21/48 | 21/48 | 0 | 27 |

金标 `perspective` 为 `unknown`41/`quoted_other`7（**无 `source_explicit`**），store 为 `source_explicit`220/`quoted_other`2（**无 `unknown`**）——**同一轴两侧默认值相反**。金标 `speech_role` 全 `statement`，store 有 question/answer。

⇒ **归一化后 5 元组对齐仅 7/48**（md 3 / docx 4）；2 元组（`semantic_type`+`statement_role`）14/48。**路线 a 结构上可行，但自动化只能覆盖 15% 的记录，其余须人工裁定或重抽。**

**`attribution`/`speaker_ref` 不可派生（粒度不足）**：gold 需 5 类区分（且 gold 内 `attribution` 与 `speaker_ref` **1:1 冗余**），store 侧只有 `document_voice`/`quoted_source` 共 2 类、`display_name` 全空；layer B `attribution` 与金标 raw 一致 **0/48**。

**门 33 工作台缺陷（新增）**：工作台相对 store 丢 `speaker_ref`，**影响全部 222 条**；⇒ Stage 2 裁定者读不到该轴，**人工裁定同样不可执行**，报分前必须先重建工作台（零调用）。

> **预注册弱阈值声明**：EC-A6a 的触发条件是"对齐记录数 ≥ 1"（偏弱），故"branch = EC-A6a"只表示**结构可行**，不表示够用；实质数字是 **7/48**。此点与 r1 的 EC-3 同属预注册设计不足，记 backlog。

### 5.10 门 33 工作台 v2：Stage 2 重新可执行（r4 补记，§7-10 已完成）

产物：`evidence/38-gate33-workbench-rebuild-20261012/r0-zero-call/`（零调用只读；幂等、支持 `--no-write`；预注册先于运行落盘）。

| 产物 | sha256 |
|---|---|
| 预注册 `preregistered-workbench-rebuild.json` | `72c7cb1c…d9538` |
| `workbench-v2.json` | `0bd9e660…36558` |
| `workbench-v2.md` | `6acda8a7…b72f6e` |
| 脚本 `rebuild_workbench.py` | `fb7aca19…11d0e` |

**做法**：以门 33 `workbench.json`（`e00d8ae6…a489777`）逐条为基准**增强**（join key = `item_id`），不重新生成候选、不重算 Stage-1 建议。

**超集自检（全部通过）**：`candidate_id` 集合与顺序一致 = **True**；v1 既有字段逐条不一致 = **0**；槽位分配交叉校验分歧 = **0**（v1 slot ↔ 证据跨度包含 ↔ store `coverage.slot_ledger` 三方一致）；序列化后建议与候选仍逐条 == v1 = **True**；门 33 目录字节未变（`workbench.json` 哈希不变）。

**补齐的字段覆盖（/222）**：`speaker_ref` **222**、`attribution` 220、`condition`（layer B 开关）221、`factuality` 222。

**契约视图覆盖（/222）**：`proposition` 222、`semantic_type`/`statement_role`/`speech_role`/`perspective`/`polarity` 各 222、`speaker_ref` 222、`attribution` 220、`condition` 6、**`source_stance` 0（显式标 `requires=source_read`，非留空）**。

**每个契约字段的前置条款**（取自 §5.9 实测）：`proposition`→`normalization`；`semantic_type`/`statement_role`/`speech_role`/`perspective`/`attribution`/`condition`→`caliber_clause`；`speaker_ref`→`id_mapping_or_exclusion`；`polarity`→`none`；`source_stance`→`source_read`。

⇒ **Stage 2 的"读不到字段"这一阻塞已解除**；剩下的阻塞是 §7-11 的口径条款与 §9 的路线裁定，不是工具问题。

## 6. 量化天花板（诊断口径，非生产报分口径）

分母 = 48 条已签认金标；命中数取自门 33 Stage 1 **草案建议**（**未经人工裁定，precision 依契约记 N/A**）。阈值取门 28 `quality_requirements`（signed，权威）。

被传输事件丢掉的 7 条全部属 **md** 源（`industrial-fulian-md` 第 8 包，`char:5246-5537`），故分源计算：

| 门槛 | 权威阈值 | 不补跑时的天花板 | 结论 |
|---|---|---|---|
| `target_recall_overall` | 0.85 | 48 − 7 = 41/48 = **0.8542** | 可达，但**零余量**：其余 41 条必须全中 |
| `target_recall_per_source` | 0.80 | md = (22 − 7)/22 = **0.682** | **不可达** |
| `accepted_records_per_source_min` | 20 | md 可接受上限 = **15** | **不可达** |
| `risk/condition` recall | 19/20 = 0.95 | 21 − 5 = 16/21 = **0.762** | **不可达** |
| `critical` | 缺失即 `rate_blocker`（`structured_scoring.py:656-659`） | 已匹配 1 + 可救 4 = **5/12**，仍缺 7 条 | **不可达** |
| `unresolved_candidates_max` | 0 | 草案阶段仍有 **203** 条 unresolved | **不可达**（受 §7-3 结构阻塞） |
| `candidate_precision` | 0.80 | **N/A**（契约禁止排除 unresolved 后报通过） | 无法报分 |

**结论：不补跑被传输事件丢掉的那一个包，评分门的四项门槛（分源召回、分源接受数、risk/condition、critical）同方向不可达；补跑是必要条件，而非可选项。** 另需注意：即使补跑成功，`unresolved_candidates_max = 0` 仍要求 Stage 2 结构性阻塞先被解除。

> r1 限定：本表的量纲是"数据是否存在"（分母 48，命中取自草案建议），**不依赖读路径是否可实现**。故 §5.4 对 L9 的修正**不改变本节结论**；反之本节也不得被读作"读路径可行"的证明。

## 7. 修复依赖序

| 序 | 事 | 为什么必须在前 | 性质 | 是否需授权 |
|---|---|---|---|---|
| 1 | 定接缝路线：以**金标形态为权威**定义读路径（路线 a），或扩协议字段并重抽（路线 b，需重跑） | 不定这条，评分恒为 0（L9） | 契约 v4 修订 | 需裁定 |
| 2 | 补跑被传输丢掉的 1 个包（带重试/幂等策略） | 否则 §6 四项门槛不可达 | 新门 + 真实调用 | 需授权 |
| 3 | 解 Stage 2 结构性阻塞：明确"候选 → 契约字段"由谁负责、以什么为凭据 | 现行契约禁止以改写充当裁定，人工步骤**不可执行**；且 `unresolved_candidates_max = 0` | 契约条款 | 需裁定 |
| 4 | 裁定 L6 的 2 个我方信号槽（forecast / evidence） | 我方缺陷，连带丢 2 条已产出条目 | 协议变更 | 需裁定 |
| 5 | 修 Stage-1 助手，或明确裁定全人工 | `19/48` 量的是助手（high 3 / medium 17 / low 146 / none 56），不是抽取质量；且该数两臂均为构造量（§5.4） | 工具，零调用 | 否 |
| 6 | 记账与口径一致性：契约哈希 v2→v3 绑定、`validation-report` 空缺、门 32 判据与被测对象同轴、评分器阈值与门 28 对齐 | 否则任何"契约已绑""协议已验""阈值即口径"的陈述都不可信 | 记账，零调用 | 阈值变更需具名签认 |
| 7 | 读路径规则写成**与记录 ID 无关**的字段语义规则，并逐字段给出"候选字段 → 契约字段"映射 + 不可派生反例清单（§5.5） | 否则修复只对本批 19 条成立、不可推广（§5.7） | 契约 v4 条款 | 需裁定 |
| 8 ✔ | **已完成（2026-10-11，授权后）**：用留出记录重做 L9、禁止金标注入；结论见 §5.8 | 现行 `19/48` 是循环量，不能作为路线 a 的可行性证据（§5.4） | 零调用 | 否 |
| 9 | 对 `claims` / `material_relations` 做同型 L3 零调用审计 | 另两角色的同型接缝未验证，不得以 items 单角色推断（§5.6） | 零调用 | 否 |
| 10 ✔ | **已完成（2026-10-12）**：重建门 33 工作台 v2（严格超集，补回 `speaker_ref` 与 layer B 字段），结论见 §5.10 | 现行工作台缺该字段（影响 222/222 条），Stage 2 人工裁定**不可执行**（§5.9） | 零调用，工具 | 否 |
| 11 | 定枚举**口径归一化条款**（`perspective`／`speech_role` 等） | 金标与生产端同轴默认值相反；不立此条款，任何匹配恒为 0（§5.9） | 契约条款 | 需具名签认 |

1 与 3 是同一处契约修订的两面，应合并为一轮；2 独立于 1，可并行。第 6 项中的阈值统一**必须具名签认**（阈值/粒度变更的既有约定）。**第 7 项应并入第 1/3 那一轮**（同一份契约 v4）；第 8、9 项为零调用，可在该轮内先做，其中第 8 项是判定第 1 项是否成立的前置。

## 8. 范围外／不做

- 不改冻结金标（`frozen-gold.json` / `freeze-state.json` 字节不变）、不新增金标、不放宽阈值；
- 不放宽 fail-closed 校验与解析（L5 保持原行为）；
- 不就地修改门 28/32/33 的既有产物；修订以新版本记录，旧哈希留存可追溯；
- 不改动 L1/L2/L4/L5（已实测成立）；
- 本报告不发起任何模型调用、不访问生产库、不发布；
- 不把本文的数字表述为"生产默认口径"或"完整文档覆盖"。

## 9. 待裁定项

| 项 | 选项／参数 | 裁定人 | 日期 |
|---|---|---|---|
| 接缝路线 | ☐ 路线 a（读路径，以金标为权威）　☐ 路线 b（扩协议字段重抽） | | |
| 补跑授权 | 授权人／日期／模型／`attempts_max`／节流 | | |
| L6 我方信号 2 槽 | ☐ 修正信号规则　☐ 维持现状并登记为已知损失 | | |
| Stage 2 阻塞条款 | 由谁负责候选→契约字段规范化、凭据是什么 | | |
| Stage-1 助手 | ☐ 修　☐ 接受全人工 | | |
| 阈值统一 | ☐ 以门 28 为权威（0.85/0.80）　☐ 维持评分器现值（0.95/0.90）并改门 | | |
| 读路径普遍性（§5.7 三条硬要求） | ☐ 接受三条并写入契约 v4　☐ 只修本批数据 | | |
| 跨角色范围 | ☐ items-only　☐ 每角色各建读路径（先做 §7-9 审计） | | |
| B-1 两条 md 记录（NT-I06／NT-I41） | ☐ 纳入补跑范围　☐ 判为模型 `no_supported_item`　☐ 关联方法差异（非损失） | | |
| 路线 a/b 最终裁定（r3 依据） | ☐ route a（零调用：修投影 + 复用 layer B 派生 + 口径归一化条款；自动对齐 7/48，余靠人工）　☐ route b（重抽统一口径，作废门 32 冻结）　☐ a + 定向补跑 | | |
| 枚举口径归一化条款（§7-11） | ☐ 以金标口径为准（`source_explicit→unknown` 等）　☐ 维持生产端口径并改金标　　须具名签认 | | |

## 10. 签认栏

- 复核人：　　　　日期：
- 结论：☐ 认可本口径　☐ 退回修改
- 备注：
