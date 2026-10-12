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
- 修订：r5（2026-10-12，**签认前**补记，零调用）：执行 §7-9，产出 `evidence/39-roles-l3-audit-20261012/`，新增 §5.11 与 §7-12，§7-9 标为已完成，§9 增 relations 契约缺陷裁定行。
- 修订：r6（2026-10-12，**签认前**补记，零调用）：产出 `evidence/40-route-ab-decision-inputs-20261012/`（同量纲成本-收益表 / 冻结影响清单 / route b 受控实验预注册草案），新增 §5.12 与 §7-13、§7-14，§9 增两行裁定项。
- 修订：r7（2026-10-12，**签认前**补记，零调用）：U 裁定"222 条全量裁定（选项 a）"；产出 `evidence/45-contract-v4-draft-20261012/`（契约 v4 草案，含 OPEN-1/OPEN-2）与 `evidence/42-stage1-suggester-upgrade-20261012/`（Stage-1 助手 v2），新增 §5.13、§5.14，§7-5/§7-6/§7-11 状态更新，§9 增审阅行。
- 修订：r8（2026-10-12，零调用）：**契约 v4 已签认并落地**（OPEN-1=A、OPEN-2=C），产出 `evidence/43-scoring-contract-v4-signed-20261012/`；撤销本报告 §10 的误填签认；为生成脚本加签认护栏；对账发现并行 v4 草案有 18 条独有叶子（含 3 条核心条款）。详见 §5.13.1。
- 修订：r9（2026-10-12，零调用）：P07 消编号歧义——本会话证据目录 `41-contract-v4-draft-20261012` 改号为 `45-contract-v4-draft-20261012`，引用同步修复并重跑（见 `45-…/rename-record.json`）。
- 修订：r10（2026-10-12，零调用）：P10 完成——产出契约 **v4.1 草案**（`evidence/46-contract-v41-draft-20261012/`），以已签 v4 为基只增不删地并入并行草案独有叶子。详见 §5.13.3。
- 修订：r11（2026-10-12，零调用）：**契约 v4.1 已签认并落地**（`evidence/47-scoring-contract-v41-signed-20261012/`）；并行草案标 superseded；出 **P12/P13 记账提案**（`evidence/48-rebinding-and-basis-proposals-20261012/`，零就地改动）。详见 §5.13.4。
- 修订：r12（2026-10-12，零调用）：**Wave 0 开工**——P01 装配器已实现并通过证据运行（`evidence/49-p01-assembler-20261012/`）；P02 设计说明待 U 审阅（`evidence/50-p02-matcher-design-20261012/`）。详见 §5.14。
- 修订：r13（2026-10-12，零调用）：**P02 评分器匹配改造已完成**（legacy 四臂逐字段不变；`evidence/53-…`）；**P07 编号歧义已收敛**（41 归 Issue 41；`evidence/52-…`）。详见 §5.14。
- 修订：r14（2026-10-12，零调用）：**P08 已完成 ⇒ Wave 0 收口**（32/33/34/35 的 r0 回填 MANIFEST；41 声明不补；`evidence/54-…`）。详见 §5.14。
- 修订：r15（2026-10-12，零调用）：出 **P12/P13 签认件**（`48-…/rebinding-signoff-review.md`，`3fa1385f…`），并扩展 P12 范围至 3 处绑定点（新查 `freeze-state.json` 两处）。详见 §5.13.4。
- 修订：r16（2026-10-12，零调用）：**P12/P13 已签认并落地**（U 签 `06ca5279…`；新增记录 `565a680b…`／`8cc11bcc…`）；**P14 已落地**（新增对齐记录，`validation-report.json` 字节不变）；**P16 冻结链校验器已建成并首跑**（`drift 0`，1 项待 U 裁定）。详见 §5.13.4。
- 修订：r17（2026-10-12，零调用）：U 对校验器拦下项裁定 **(a)** ⇒ 出 **契约 v4.2 草案**（只改 3 处 authority pin，`unexpected_changed = 0`，阈值逐字不变；`evidence/57-…`，待签）；**P06 护栏修两处机制误报**（空白模板/空 signoff 占位被误判已签，`51-…/guard-fix-record.json`）。详见 §5.13.6。
- 修订：r18（2026-10-12，零调用）：**契约 v4.2 已签认并落地**（U 签 `215a3490…`；`58-…/scoring-contract-v4.2.json`）；**P12 同轮再绑定 v4.2**（`rebinding-v4.2-20261012.json`，`8fa7f8bb…`）；**冻结链校验器全绿**（`ok 11 / covered 5 / drift 0 / needs_ruling 0 / exit 0`）。详见 §5.13.7。
- 修订：r19（2026-10-12，零调用）：**P03 阈值单源落地**（`evidence/59-…` 设计＋评估、`60-…` 验证；组合 1-A＋2-C＋3-A′）。详见 §5.13.8。

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

> r5 补记新增产物（零调用只读，sha256 实测）：
> `39-…/r0-zero-call/preregistered-roles-l3.json` = `8f970041…ba25a`；
> `39-…/r0-zero-call/roles-l3-audit.json` = `5a446a54…90b096`；
> `39-…/r0-zero-call/roles-l3-audit.md` = `91ee96f9…e82b3`；
> `39-…/r0-zero-call/roles_l3_audit.py` = `c7018773…a3fa7`。

> r6 补记新增产物（零调用只读，sha256 实测）：
> `40-…/r0-zero-call/preregistered-ab-inputs.json` = `97979128…271b8`；
> `40-…/r0-zero-call/ab-cost-benefit.json` = `c32a4509…7d2e0`；
> `40-…/r0-zero-call/freeze-impact.json` = `a2200c5f…dea3dd`；
> `40-…/r0-zero-call/route-b-experiment-protocol.json` = `88fddc8c…f43786`（草案，未执行）。

> r7 补记新增产物（零调用只读，sha256 实测）：
> `41-…/r0-zero-call/proposed-scoring-contract-v4.json` = `506f2e39…d02d2c`（**草案，未签认**）；
> `41-…/r0-zero-call/contract-v4-diff.json` = `a7ad7bc3…ce75b1`（机器计算）；
> `41-…/r0-zero-call/contract-v4-open-decisions.json` = `15378de9…27a457`；
> `42-…/r0-zero-call/suggestions-v2.json` = `7fa2fdc9…03a4bb`；
> `42-…/r0-zero-call/suggester-v2-report.json` = `2fc2896d…61a970`。

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
- **r5 更新**：§7-9 已完成，结论见 §5.11 —— `material_relations` = **不同型**（协议范围外 + 契约含金标主键致结构性不可评分）；`claims` = **疑似同型但仅 code_level**（无产物，四个"归属/来源态度/估计状态"族字段无载体）。"未实测"状态对 claims 仍然成立。

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

### 5.11 claims / material_relations 同型 L3 审计（r5 补记，§7-9 已完成）

产物：`evidence/39-roles-l3-audit-20261012/r0-zero-call/`（零调用只读；幂等、支持 `--no-write`；预注册先于运行落盘）。

| 产物 | sha256 |
|---|---|
| 预注册 `preregistered-roles-l3.json` | `8f970041…ba25a` |
| `roles-l3-audit.json` | `5a446a54…90b096` |
| `roles-l3-audit.md` | `91ee96f9…e82b3` |
| 脚本 `roles_l3_audit.py` | `c7018773…a3fa7` |

金标三角色齐备：`claims` 20、`material_items` 48、`material_relations` 24。

**① `material_relations`：不同型——协议范围外 + 契约结构性不可评分。**
- 实测两源 treatment 的 `understanding.relations` 均为 **0 条**（协议明文：`MATERIAL_ITEM_JSONL_PROMPT`"本阶段只抽 speakers 和 items，不输出 relations"）⇒ 属**范围外**，**不是字段错配**（按 §0 规则：非根因不得写成通过，范围外也不得写成缺陷）。
- **新增缺陷（EC-B4）**：契约 `role_required_fields.material_relations` 含 `from_gold_record_id` / `to_gold_record_id`，即要求候选携带**金标主键**。严格 identity 匹配要求候选字段逐字等于金标 ⇒ 该角色在现评分器下**恒为 0**，与模型能力无关。

**② `claims`：疑似同型，但只在 code_level（未在数据上验证）。**
- 本工作流无 claims 运行产物（gate-32 为 items-only）。
- code_level：`plugins/corpus/claims_detail.py::ClaimRecord` 对契约 11 个必需字段中，`subject`/`metric`/`unit`/`value` 直接同名、`period`/`qualifier` 为派生、`factuality` 为别名 `kind`（**取值域未核验**），而 **`attribution`/`perspective`/`source_stance`/`estimate_status` 四个字段无任何承载字段**——与 items 缺的正是**同一族**字段。
- ⇒ 记 `not_observed_on_data` + `code_level`；**不得**写成"同型接缝已确认"。

**③ §7-11 建议（EC-B5）**：口径条款应写成**每角色通用的读路径机制**，但本期只对 items 落地（claims 缺产物、relations 属范围外），机制留接口——否则将来必然在 claims 上重做一次。

### 5.12 路线 a/b 的裁定输入（r6 补记）

产物：`evidence/40-route-ab-decision-inputs-20261012/r0-zero-call/`（零调用只读；幂等、支持 `--no-write`；预注册先于运行落盘）。

| 产物 | sha256 |
|---|---|
| 预注册 `preregistered-ab-inputs.json` | `97979128…271b8` |
| 同量纲表 `ab-cost-benefit.json` | `c32a4509…7d2e0` |
| 冻结影响 `freeze-impact.json` | `a2200c5f…dea3dd` |
| 实验草案 `route-b-experiment-protocol.json`（未执行） | `88fddc8c…f43786` |

**① 同量纲表（单位：模型调用／人工裁定条数／冻结修订／门次／零调用代码改动）。**

| 维度 | 共同项 | a 边际 | b 边际 | 独立 | 共同项 ≥ 两边际之和 |
|---|---|---|---|---|---|
| `model_calls` | 0 | 0 | **24** | 1 | False |
| `human_adjudication_records` | **222** | 0 | 0（但须在**新**候选集上重做） | 1 | True |
| `freeze_revisions` | 2 | 1 | 1 | 0 | True |
| `gate_runs` | 1 | 0 | 1 | 1 | True |
| `zero_call_code_changes` | 2 | 2 | 2 | 0 | False |

**收益三态**：S0 现状 = **0**（实测）；S1 共同项完成后 = **[7, 39]**（下界＝归一化后字段逐字对齐、上界＝逐字证据可达，**均为实测**）；S2 加补跑、S3 加 route b 重抽 = **[7, 48]**，均标 **unverified**。人工裁定区间 = **32** 条（39 − 7）。

**② 伪二分假设（EC-AB3）**：在 `human_adjudication_records`／`freeze_revisions`／`gate_runs` 三个维度上**成立**（共同项 ≥ 两边际之和）；在 `model_calls`（0 vs 24）与 `zero_call_code_changes`（2 vs 4）上**不成立**。
⇒ 路线分叉的真实差异只有**"24 次模型调用 + 2 处代码改动"**这一小块；其余成本两边都要付，且 route b 无法复用 route a 的人工裁定结果。

**③ 冻结影响（EC-AB4）**：共 9 条绑定物件。直接失配的是 `material_semantics_module`（`1305dba1…`）与 4 个 plan 文件；金标冻结链里已漂移的契约绑定（v2→v3）须与 v4 **同轮**修；`treatment store` 对象须保持可读（B3）；`frozen-gold.json` 与 `structured_scoring.py` **声明不受影响**（后者不在 gate-32 绑定清单内，仍建议 v4 轮显式复核一次）。

**④ route b 受控实验草案（EC-AB5，未执行）**：同代码双臂（control＝现冻结协议文本／treatment＝**只改提示词**）；指标 M1 `quoted_other`、M2 `condition`、M3 `behavior`、M4 `speech_role` 分布、M5 协议违规须为 0、M6 逐字证据可达率、M7 fail-closed 不得放大；判据 EC-X1（任一指标达金标计数 ≥50% 且 M5=0 ⇒ 口径歧义成立）、EC-X2（全无改善 ⇒ 属模型能力，route b 不得以收益为由）、EC-X5（M7 上升即终止回滚）；预算试跑 4 次／全量 48 次（＝24×2 臂，依据 gate-32 `expected_attempts`）；授权项待填。

**⑤ 仍缺（本批不代替）**：缺口 1 = **32 条区间的人工可裁定比例**（需 xyl 抽样裁定）；缺口 2 = **route b 的收益**（需执行上述实验）。

### 5.13 契约 v4 草案（r7 补记）

产物：`evidence/45-contract-v4-draft-20261012/r0-zero-call/`（零调用只读；幂等、支持 `--no-write`）。

| 产物 | sha256 |
|---|---|
| 预注册 `preregistered-contract-v4.json` | `06d57cfa…a95d1d` |
| **草案** `proposed-scoring-contract-v4.json` | `506f2e39…d02d2c` |
| 差异 `contract-v4-diff.json`（机器计算） | `a7ad7bc3…ce75b1` |
| 待裁定 `contract-v4-open-decisions.json` | `15378de9…27a457` |

- **草案不是交付物**：`status = draft_pending_human_signature`，`signoff.signed_by` 为空（自检通过）；**v3 契约字节未变**（`d9bc51f2…` 实测复核）。
- 差异由脚本递归 diff 计算，与 `declared_changes` 逐根一致（自检通过）。
- 新增条款：`caliber_rules`（逐字段口径归一化 + 依据 + 是否可自动归一）、`read_path`（角色通用机制、本期仅 items；声明与记录 ID 无关、`review_assertions` 不得作匹配规则）、`adjudication_clause`（Stage 2 责任人/凭据/**全量 222**/逐字引文要求/抽检须隐藏建议）、`threshold_source`（双源 + OPEN-1 + 轴警告）、`relation_matching`（OPEN-2）、`bookkeeping_requirements`；`matching.projection` 增补"归一化不得覆盖原始字段"。
- **两项待你裁定**：**OPEN-1** 阈值单源（A: 以门 28 为权威 0.85/0.80/20 ／ B: 维持评分器 0.95/0.90 并改门）；**OPEN-2** relations 修正（A 裁定映射／B 删金标字段／C 本轮不纳入）。另 **FORCED-1**：口径方向由 §8（金标字节不变）推定只剩"以金标口径为准、读时归一化"一条，**方向已定但条款仍须签认**。

#### 5.13.1 签认与落地（r8 补记）

- **签认**：`45-contract-v4-draft-20261012/r0-zero-call/contract-v4-review.md`＝**已签认**（`753532e8…`，2026-10-12）：结论 ☑ 认可并签认 v4、**OPEN-1 = A**（门 28 权威 0.85/0.80/20，评分器改为读契约）、**OPEN-2 = C**（material_relations 本轮不纳入评分）。
- **落地**（新目录，write-once；草稿与 v3 字节均未变）：`evidence/43-scoring-contract-v4-signed-20261012/r0-zero-call/`

| 产物 | sha256 |
|---|---|
| `scoring-contract-v4.json`（`status = frozen_signed`） | `6806f139…b712d` |
| `signoff-record.json` | `5e8737f4…92d9ff` |
| `README.md` | `37fad0a6…5ab3af` |

> r9 注：上表哈希为 **P07 改号后**重跑的取值（原 `479ae04e…`/`32c14a15…`/`beb469c5…`）；改名只动路径、不改字节，**签署工具 `contract-v4-review.md` 哈希恒为 `753532e8…`**。改号记录见 `45-…/r0-zero-call/rename-record.json`。

- **撤销留痕**：本报告 §10 此前被预填（半签），已于 2026-10-12 按 U 指示撤销；`contract-v4-review.md` 曾被误判为预填并被重生成脚本回退一次（**我的越权操作**，仅 `chain-report.md` 获得撤销授权），已于同日为生成脚本加**签认护栏**：检测到已签认标记即**拒绝写入**（除非显式 `--force`）。
- ⚠️ **对账发现（重要）**：并行会话另有 v4 草案 `41-items-chain-accounting-20261012/r3-signoff-apply/scoring-contract-v4.proposed.json`（`b3f88649…`，`status = proposed_pending_signoff`，**签认栏为空、从未签认**）。按节名映射（`items_field_carrier_read_path`→`read_path`、`threshold_single_source`→`threshold_source`）对账后，**该草案有 18 条独有叶子路径**，其中 3 条为**核心条款且已签版缺失**：
  1. `carrier_mapping.rule`：**只允许确定性载体映射（候选 `text` → 契约 `proposition`），只改字段名，不生成、不改写、不摘要任何语义文本**；
  2. `absent_required_fields.rule`：**缺字段时记 `absent`，不得因缺字段直接判不匹配，也不得补造**；
  3. `equivalence_judgement.scorer_contract`：**评分器不得以身份相等为匹配前提，只消费裁定完成的映射**。
  ⇒ **已签版 v4 在核心读路径语义上是不完整的**。**不得**改已签版（那正是"签认后改写"）；须走**新修订（v4.1 或 v5）+ 单独签认**把上述条款并入。
- **签认后仍未完成（不得读成已过门）**：评分器读契约/阈值对齐（§7-6，代码未改）；金标冻结链契约绑定再绑定（v2→v3→v4）；口径归一化实现与回归测试（§7-7 A1/A2）；route a/b 边际裁定与缺口 1/2（§5.12）。

#### 5.13.2 全链路重规划入口（r9 补记）

- **本节取代 §7 的修复依赖序**：计划以 `evidence/44-replan-20261012/r0-zero-call/replan.md` 为准（`replan.json` = `2cdd3506…c71ccb`，P07 改号后重跑），含 Wave 0–5、关键路径、缺陷→计划项映射与**机器化遗漏自检**（`complete = true`：§7 全 14 行、§9 全 16 项、D1–D12、扫描命中全部有归属；另显式声明未覆盖范围）。§7 保留作为溯源，不再作为执行顺序。
- **P07 已完成（2026-10-12）**：本会话证据目录 `41-contract-v4-draft-20261012` **改号为 `45-contract-v4-draft-20261012`**（41 另属并行 Issue 41），改号记录见 `45-…/r0-zero-call/rename-record.json`；已同步修好本报告、`43` 与 `44` 的脚本引用并重跑。**遗留一项**：并行文件 `41-items-chain-accounting-20261012/r2-proposals/contract-v4-draft.md` 中对旧路径的引用已失效，须由该会话或 U 处置（不由本会话写入）。
- ⚠️ **新增两处链路末端缺环（此前未记录）**：**①裁定→评分输入装配器不存在**（无代码读 `adjudications`/`canonical_observed_fields`）；**②评分器只认字段逐字相等、不消费裁定**（`structured_scoring.py:456`）。⇒ **即使 v4.1 补全且 222 条裁定完成，门 33 仍为 0 分**，且会被误归因为抽取质量。两者均为**零裁定纯工程**，已列为 Wave 0（P01/P02）。

#### 5.13.3 契约 v4.1 草案（r10 补记，P10 已完成）

产物：`evidence/46-contract-v41-draft-20261012/r0-zero-call/`（零调用；幂等、支持 `--no-write`；含签认护栏）。

| 产物 | sha256 |
|---|---|
| 预注册 `preregistered-v41-merge.json` | `3f704f6f…c5f300` |
| **草案** `proposed-scoring-contract-v4.1.json`（`status = draft_pending_human_signature`） | `ee085552…026875` |
| 差异 `contract-v4.1-diff.json`（机器计算） | `ffc5639a…5c61d7` |
| 对账 `merge-reconciliation.json` | `674221cb…bb21b7` |
| 审阅件 `contract-v4.1-review.md`（签认栏留空） | `adcd7d61…f891dc` |

- **合并规则**（预注册声明、机器执行）：以**已签 v4 为基**，donor 叶子**仅当基缺少该路径时写入**；路径已存在且值不同则**保留基值并记冲突**，绝不静默覆盖。
- **自检结果**：**新增 22 条叶子、按已签结论落地 2 条、冲突 0、删除 0**（`add_only = true`）；基、签署工具与 donor 三个已签/外来产物**哈希均未变**（`6806f139…`／`753532e8…`／`b3f88649…`）。
- **并入的 3 条核心条款**（此前已签版缺失，正是路线 a 的可行性开关）：`read_path.carrier_mapping.rule`（只改字段名、不生成/改写/摘要语义）、`read_path.absent_required_fields.rule`（缺字段记 absent、**不得因缺字段直接判不匹配**）、`read_path.equivalence_judgement.scorer_contract`（**评分器不得以身份相等为匹配前提**）。
- **两处需 U 确认的可质疑项**（脚本撰写或改名，非机械搬运）：① `threshold_source.decision_history` 由 donor 的 `pending_signoff_detail` 改名而来，其历史说明已更新为"该分叉已由 OPEN-1=A 裁定"；② `read_path.absent_required_fields.alignment_with_caliber_rules`（调和 donor「记 absent」与基「移出匹配基」两种表述）。
- **待办**：U 签认 v4.1（只勾"认可并签认 v4.1"，无需再选选项）→ 并行草案可标 `superseded_by` → 绑定再绑定与门 28 基准推进（P12/P13）以 v4.1 哈希为准。

#### 5.13.4 契约 v4.1 已签认并落地；P12/P13 提案（r11 补记）

**A. 签认与落地**（`evidence/47-scoring-contract-v41-signed-20261012/r0-zero-call/`）

| 产物 | sha256 |
|---|---|
| `scoring-contract-v4.1.json`（`status = frozen_signed`） | `c76ac13e…38781b` |
| `signoff-record.json` | `32dc784e…70677` |
| `README.md` | `81e293ab…2ffe89` |

- 签署工具：`46-…/r0-zero-call/contract-v4.1-review.md` = `1d012182…b94bdc`（`复核人 xyl／2026-10-12`、结论已勾"认可并签认 v4.1"）。
- **备注为空 ⇒ 两处 `open_for_reviewer` 项（`threshold_source.decision_history`、`read_path.absent_required_fields.alignment_with_caliber_rules`）按「原样接受」处理**。这是对空备注的解释，已显式记录于 `signoff-record.json`，**不视为逐条确认**。
- 取代关系：已签 v4 `6806f139…` 与并行草案 `b3f88649…` **均标 superseded_by v4.1**（后者从未签认，其独有叶子已并入）。上游四个已签/外来产物**哈希均未变**。
- 幂等 + `--no-write` 通过；已签产物写盘前有签认护栏。

**B. P12/P13 记账提案**（`evidence/48-rebinding-and-basis-proposals-20261012/r0-zero-call/`，`in_place_edits = 0`）

| 产物 | sha256 |
|---|---|
| `gold-freeze-rebinding-proposal.json`（P12） | `3a99d6ad…d4c773` |
| `gate28-metric-basis-proposal.json`（P13） | `2f0de079…e93d25` |

- **P12**：金标冻结链 8 条输入实测 **漂移 1 条**（`scoring-contract.json` 记 v2 `2eb24be7…`，实际 v4.1 `c76ac13e…`；经 v3、v4），其余 7 条匹配。须以**新文件**记录再绑定，`freeze-manifest.json` 字节不变（实测 `da85e293…` 未变）。并行会话的同类记录针对 v2→v3，**不能沿用**。
- **P13**：门 28 有**两处**绑定过期（此前只记了一处）：`quality_requirements.metric_basis = …-v3` 与 **`gold.scoring_contract_sha256 = d9bc51f2…`（v3）**；与契约 v4.1 形成**循环引用**（契约阈值取自门 28，门 28 的基准/绑定又落后于契约）。须同轮推进为 `…-v4.1` 并再绑定；**阈值数值逐字不变**。门 28 自身已有 v2→v3 的同类先例（`revision_history[1]`），故本次是沿用既有手续。门 28 文件字节不变（实测 `987772e9…` 未变）。
- 两项均 `proposal_pending_signoff`，改的只是记账，不改语义。
- **签认件已就绪（r15）**：`48-…/r0-zero-call/rebinding-signoff-review.md`（`3fa1385f…`，待 U 签）。起草该件时对 P12 做完整实测，**又查出 2 处原提案未覆盖的绑定点**（`48-…/rebinding-scope-extension.json`，`438cbca1…`）：① `freeze-state.json.scoring_contract` 记的是**路径而非哈希**（弱绑定，现解析为 v3）；② `freeze-state.json.contract_snapshot` 是**内嵌的 v2 草案全文**（`status: draft_pending_human_review`）。处置建议：①新记录钉住解析哈希、"路径改哈希"留后续；②**保留字节**（改它即伪造历史），由新记录声明"是历史、非当前绑定"。故 P12 完整范围为 **3 处**、P13 为 **2 处**；签认件已声明"本件为准"，原两份机器提案字节未改。

#### 5.13.5 P12/P13 已签认落地；P14/P16 完成；1 项待裁定（r16 补记）

**签认与落地**（`evidence/55-rebinding-signoff-applied-20261012/`）

- U 签认件：`48-…/rebinding-signoff-review.md` = `06ca5279…`（空白版 `3fa1385f…`；`复核人 xyl／2026-10-12 10:00`，结论已勾"P12 三处 + P13 两处"，**备注为空** ⇒ §二/§三 推荐处置按原样接受，已显式记录该解释）。
- **新增两个记录，既有字节零改动**（`in_place_edits = 0`；经 `tools/evidence_guard.write_once` 写入）：

| 记录 | sha256 | 内容 |
|---|---|---|
| P12 `10-quality-gold-freeze-20261008-r2/rebinding-v4.1-20261012.json` | `565a680b…` | 3 处绑定点（manifest 输入再绑定 v2→v4.1；路径绑定钉解析哈希；内嵌快照声明为历史） |
| P13 `28-…/r0-zero-call/preregistered-gate-v2.json` | `8cc11bcc…` | 门内 `revision 5`；`metric_basis → …-v4.1`；`gold.scoring_contract_sha256 → c76ac13e…`；**阈值六项逐字不变**（实测 `threshold_values_unchanged = true`） |

- 冻结原件字节未变（实测）：`freeze-manifest.json` `da85e293…`、`freeze-state.json` `08703b8d…`、`frozen-gold.json` `603de5e6…`、门 28 v1 `987772e9…`。
- 复跑幂等（两件均被护栏识别为 `already_signed_skipped`）。

**P14 已落地**（`10-quality-gold-expansion-20261008-r2/validation-report-alignment-20261012.json`，`e7fe7aec…`）

- **关键发现：不能就地改。** `validation-report.json` 是冻结链的记录输入且当前 `match`（`139cfc22…`）；改它会使 `freeze-manifest.json` **和** `draft-manifest.json` **两处**记录输入同时漂移。故与 P12 同法走**新增记录**。
- 原件字节不变（`status: valid_review_draft`／`human_accepted_counts: {}` 是冻结当时的草案态，属历史真值）；对齐后的计数（claims 20 / material_items 48 / material_relations 24，源自 `freeze-state.json.counts`）由新记录承载。

**P16 冻结链校验器已建成并首跑**（`tools/check_freeze_chain.py` + `evidence/56-freeze-chain-validator-20261012/`）

- 落实契约 `bookkeeping_requirements.freeze_chain_validator_required`（"现无"→ 有）。只读、零调用、有问题即非零退出。
- 首跑：`ok 13 / covered_by_record 3 / drift 0 / needs_ruling 1 / exit 1`。3 处 `covered_by_record` 分别由 P12/P13 覆盖。
- **1 项待 U 具名裁定**：契约 v4.1 的 `authority_source.sha256` 仍钉门 28 **v1**（`987772e9…`），而 P13 已产生继任记录 **v2**（`8cc11bcc…`）——阈值数值实测逐字相同，不影响口径，但"哪份门是权威"需裁定：(a) 契约出新版本改钉 v2；**(b) 明确 v1=冻结执行门、v2=基准持有记录**（本会话倾向 b）。裁定前校验器保持非零退出。

**记账四条至此的状态**：绑定同步（P12）✅、validation-report 一致性（P14）✅、冻结链校验器（P16）✅、门 28 基准同步（P13）✅。**剩余**：P03 评分器读契约（已解锁，代码未改）；上述 1 项裁定；`freeze-state.json.scoring_contract` 的"路径改哈希"（需改字节，单独裁定）。

#### 5.13.6 U 裁定 (a) ⇒ 契约 v4.2 草案（r17 补记）

U 对 §5.13.5 的待裁定项选 **(a)：契约出新版本、把权威门改钉 v2**。落地：`evidence/57-contract-v42-draft-20261012/`（零调用）。

- **改动（机器 diff 证明）**：`changed = 9` 个叶子、**`unexpected_changed = 0`**、**`threshold_values_unchanged = true`**。实质只有 3 处：`threshold_source.authority_source.{sha256, where}` 与 `threshold_source.effective.source` 改指门 28 **v2**（`preregistered-gate-v2.json`，`8cc11bcc…`）；其余为 `schema_version`/`status`/`supersedes`/`revision_history`/`signoff` 的版本推进。
- `status = draft_pending_human_signature`；**签认前不生效**，v4.1 字节不变（`c76ac13e…`）。
- 全契约 grep 复核：钉门 28 哈希/文件名的位置**仅 3 处**，其余"门 28"均为概念性散文引用（保留）。

| 产物 | sha256 |
|---|---|
| `proposed-scoring-contract-v4.2.json`（草案） | 见 `57-…/MANIFEST.json` |
| `contract-v4.2-diff.json`（机器 diff） | 同上 |
| **`contract-v4.2-review.md`（签认件，待签）** | 同上 |

**连带：P06 护栏修两处机制误报**（`51-…/guard-fix-record.json`）

生成 v4.2 草稿时护栏**拒绝写入**，原因是两处误报——把"签认槽位的字样"当成"签认本身"：

1. **md**：空白模板含"复核人：""☐ 认可并签认"即判已签 → 改为：复核人行须有实际姓名（剥日期标签）、或有 ☑、或结论行有 x 标记。
2. **json**：存在 `signoff` 键即判已签 → 改为：`signoff` 须实际携带 `signed_by` 或 `instrument`。

修复后自检：已签契约/已签审阅件仍判 `signed`，空白模板与带空占位的草案判 `plain`；`tests/test_evidence_guard.py` 增至 **17 项**全过；P06 扫描器仍 `violations = 0`。护栏哈希 `0396923e…` → `bbe4bacd…`（`51/MANIFEST.json` 字节未改，由 `guard-fix-record.json` 作取代声明）。

**待办**：U 签 `57-…/contract-v4.2-review.md` ⇒ v4.2 生效 ⇒ **P03（评分器读契约）以 v4.2 为准开工**。

#### 5.13.7 契约 v4.2 已签认落地；冻结链校验器全绿（r18 补记）

**签认与落地**（`evidence/58-contract-v42-signed-20261012/`）

- U 签认件：`57-…/contract-v4.2-review.md` = `215a3490…`（空白版 `759e89c2…`；`复核人 xyl／2026-10-12`，`☑ 认可并签认 v4.2`，备注空 ⇒ 草案按原样接受，已显式记录该解释）。
- **新增**：`58-…/scoring-contract-v4.2.json`（`status = frozen_signed`；`authority_source` 改钉门 28 **v2** `8cc11bcc…`）+ `signoff-record.json` + README + MANIFEST。
- 上游字节未变（实测）：v4.1 `c76ac13e…`、门 28 v2 `8cc11bcc…`、签认件 `215a3490…`。复跑被护栏拒（已签件不可覆盖）。

**P12 同轮再绑定 v4.2**（`10-quality-gold-freeze-20261008-r2/rebinding-v4.2-20261012.json`，`8fa7f8bb…`）

- 依据：已签契约 v4.2 的 `bookkeeping_requirements.contract_binding_sync`（"契约修订必须同轮更新 frozen-gold 侧记录的契约绑定哈希"）。校验器在 v4.2 落地后立即拦下这一点（P12 v4.1 记录绑定的是 v4.1 ⇒ drift），证明该机制有效。
- 三处站点处置与 v4.1 再绑定记录完全一致；冻结链三文件与上一条记录字节未动（`in_place_edits = 0`）。

**冻结链校验器全绿**（`tools/check_freeze_chain.py`，`56-…/freeze-chain-check.json`）

```
ok 11 · covered_by_record 5 · drift 0 · needs_ruling 0 · exit 0
```

- 校验器三处更新：`CONTRACT_CURRENT` 改指 v4.2；authority-pin 检查改为"命中任一已知门记录即 ok"；再绑定记录取 glob 最新一条。
- 5 处 `covered_by_record` 均为"落后但已被新版本记录覆盖"，不得读成 ok。

**一条须记录在案的机制性事实（backlog，不阻塞）**

契约钉门哈希、门的 `metric_basis` 又钉契约版本 ⇒ **两者会相互追逐**：本轮 v4.2 落地后，门 v2 的 `metric_basis`（`…-v4.1`）已落后于契约，若按 `gate28_basis_sync` 再推进门，门哈希变化又会使契约的 pin 过期。**打破追逐的不变量是"阈值数值恒等"**（校验器已逐字核查 v1/v2 与契约三方一致）。建议后续以该不变量为权威、门版本推进只作簿记；是否把此规则写成条款属 U 裁定。

**剩余**：P03 评分器读契约（以 **v4.2** 为准，已解锁）；P04/P05 口径实现与回归；route a/b 与缺口 1/2；Stage 2 真实裁定 222 条；补跑授权。

#### 5.13.8 P03 阈值单源落地（r19 补记）

设计与评估：`evidence/59-p03-design-20261012/`（`p03-design.md` + `p03-design-evaluation.md`）；验证：`evidence/60-p03-verification-20261012/`。**未动代码前先出设计**，U 裁定采用评估结论 **1-A＋2-C＋3-A′**。

**关键设计事实（评估中实测发现）**：门 28 权威轴**没有按角色阈值**——"0.85/0.80"是总体/分源轴；且 **16 条 high-risk 断言 ≠ risk 集合**（16∩risk=10，21 条 risk 中 11 条不在 16 内，16 中 6 条是 opinion/立场项）。若按直觉把按角色阈值换成 0.80/0.85，即混轴（`axes_warning` 禁止）。

**落地内容**（`plugins/corpus/structured_scoring.py`，只增字段不删）：

1. 新增 `ContractGateRequirements`（已签快照 v4.2：六值＋16 断言＋`role_scope=material_items`＋`material_items_target_total=48`）。
2. **`rate_gate_passed` 切换为契约轴判定**（唯一布尔），在 items 角色域内计算：总体召回 ≥0.85、每源召回 ≥0.80、精度 ≥0.80、接受总数 ≥40、每源接受 ≥20、16 条断言全命中；critical 处理保持不变。
3. **按角色 pilot 阈值降级为 `pilot_policy_blockers` 诊断清单**（无数值布尔）——不删字段、不再 gating。
4. **risk_condition 照报不 gating**（契约 `metrics.risk_condition`："总体仍可按既有 scorer 计算"），新增按角色计数 `risk_condition_by_role`。
5. **report_support 移入 readiness**（契约 `metrics.quality_gate` 的放行前提），数值 0.95 暂留并标注"契约六值无对应项"。
6. **单一来源可执行形式**：内嵌快照 + 回归测试直接读 `58-…/scoring-contract-v4.2.json` 逐字比对；校验器新增两条检查。

**验证（10 条退出判据全过）**：

- 内嵌值==契约逐字相等（测试 + 校验器 `OK scorer embedded…`）；校验器 `ok 13 / covered 5 / drift 0 / needs_ruling 0 / exit 0`。
- **legacy 四臂账本逐字段不变**（`60-…/ledger-invariance.json`：tp/fp/fn/duplicate/precision/recall/matched 全等；D/D2 标量全等）；gate 区块变更 = 本轮已签交付物；`36/l9-redo.json` 字节未动（`acd268f2…`）。
- 测试 **98 项全过**（23 legacy + 20 裁定驱动 + 14 契约门 + 24 装配器 + 17 护栏）；corpus 全量 1474 过，2 项失败为既有环境问题（与 P03 前基线一致）。
- 修改的既有断言（3 处，逐条记录于测试内注释）：`test_zero_denominators…`（per-role 零分母移至 pilot 清单、report_support 移 readiness、新增契约 blocker 断言）；`test_candidate_thresholds…` 与 `test_signed_off…`（传入按 fixture 缩放的 `gate_requirements`——它们测的是门机制，不是 48 门数值）。

**已申报的防护落差**：risk 门控从"21 条全 gated（≥0.95，无契约出处）"变为"16 条深度断言（其中 risk 10）＋总体/分源/接受数"；11 条未被 16 覆盖的 risk 记录由总体召回 0.85 与接受数覆盖，比率照报。此为 OPEN-1=A 的真实代价。

**剩余**：P04/P05 口径归一化与回归；route a/b 与缺口 1/2；**Stage 2 真实裁定 222 条**；补跑授权。

**C. 仍未完成（不得读成已过门）**：P01 装配器、P02 匹配改造、P03 评分器读契约/阈值、P04/P05 口径实现与回归、P12/P13 签认、route a/b 与缺口 1/2。

### 5.14 Wave 0 进展：P01 完成、P02 设计待审（r12 补记）

**P01 裁定→评分输入装配器：已实现并通过证据运行。** 产物 `evidence/49-p01-assembler-20261012/r0-zero-call/`（零调用、幂等、含预注册）。

- 新代码：`plugins/corpus/adjudication_assembly.py`（`b7e426f3…`）；新测试 `tests/test_corpus_adjudication_assembly.py`。
- 实现契约 5 条：`adjudication_clause`（11 必填字段 / judgement 枚举 / evidence 必填）、`read_path.carrier_mapping`（只改字段名）、`read_path.absent_required_fields`（显式 `absent`）、`caliber_rules`（归一化只作用于匹配视图、原始字段不覆盖）、`equivalence_judgement.scorer_contract`（输出裁定映射）。
- **结构性禁止读金标**：函数签名无金标参数（有测试断言）；确定性载体由装配器从候选自身字段**重算**，申报值不符即拒绝——这是"禁止金标注入"的可执行形式。
- **证据运行（真实数据）**：以门 33 工作台 v2（222 条候选）为目录，提交门 33 草案的 **19 条 `accepted`** ⇒ **装配成功 0、拒绝 19**。独立逐规则探测（不被 fail-fast 掩盖）的违约类：

| 违约类 | 命中 |
|---|---|
| `reviewer_missing` / `evidence_missing` / `judgement_outside_contract_enum` | 各 19 |
| `proposition_rewritten_or_copied`（金标注入） | 19 |
| `field_filled_from_outside_candidate::{attribution, speaker_ref, source_stance}` | 各 19 |
| `deterministic_field_declared_differently::perspective` | 3 |

- ⇒ **契约合法裁定数 = 0，装配器输出为空**：门 33 的 0 分是**装配缺口**造成的，不是抽取质量问题。这是 §5.13.2「链路末端两处缺环」的可执行证实。
- 回归：评分器 23 项 + 新模块 24 项全通过；`tests/` 中 corpus 相关 1440 通过，2 项失败均为**环境既有问题**（`current_database='postgres' ≠ 'i2_sandbox_corpus'`；测试硬编码 `reader-pdf-10+` 而实际 `reader-pdf-11`），与本轮新增无关（`structured_scoring.py` 未改动）。

**P02 评分器匹配改造：设计说明已出，待 U 审阅**（`evidence/50-p02-matcher-design-20261012/r0-zero-call/matcher-design.md`，`bb2f59a1…`）。要点：新增 `MatchingMode.ADJUDICATED`（默认，无映射即报错、不回落）与显式 `LEGACY_IDENTITY`（诊断/对照臂）；评分器只校验裁定合法性、不做二次相似匹配；`correct_extra` 进入 precision 分子但不入 recall 分母（默认 0 时与原公式恒等，既有断言不受影响）。**两点待 U 确认**：默认模式取值；14 处既有测试调用点显式加 `LEGACY_IDENTITY`。

**P06 签认护栏推广：已完成（机制层）**（`evidence/51-p06-guard-20261012/`，`in_place_edits=0`、`historical_scripts_modified=0`）。

- 交付：`tools/evidence_guard.py`（单一实现：三态判定 + `assert_writable` + 原子 `write_once`，**`allow_overwrite=True` 下仍拒绝已签认件**）；`tools/check_evidence_guard.py`（AST 静态一致性检查，`violation` 时非零退出，可作门）；`tools/evidence_guard_exceptions.json`；`tests/test_evidence_guard.py`（13 项）。
- 实测：116 个脚本 → `guarded 3` / `violations **0**` / `legacy_exempt **4**`。
- **关键判断：不逐个改写历史脚本。** 那些脚本已执行，其哈希被 4 件产物引用（1 MANIFEST + 3 README/报告）；改字节＝改写历史，会使其产物（冻结金标、门 28、门 32 冻结门）的出处记录失效，与 §8 冲突。故落"机制 + 执行器 + 显式例外登记"：**新增**未护栏写入者必被拦截，历史写入者登记且禁原地重跑。4 条例外已具名（含 `43/apply_v4_signoff.py` —— 它**已被 47 取代**且 47 自带护栏）。
- 自检纠错三处（已记入产物）：文本标记误报（JSON 仅**引用** `signed_by` 被判已签）、`frozen.atomic_write(...)` 限定调用假阴性、`X.write_text(Y)` 目标解析错。

**Wave 0 余项**：**P08**（补齐或声明不补 MANIFEST：32/33/34/35 与 41-items-chain-accounting 的 r0）尚未做；**P07** 由 U 一句话决定。

**P02 评分器匹配改造：已完成**（U 2026-10-12 裁定默认 `ADJUDICATED`、同意改既有调用点）。产物 `evidence/53-p02-legacy-invariance-20261012/`。

- `plugins/corpus/structured_scoring.py`（`172ce465…` → `50d1553e…`）：新增 `MatchingMode`（`ADJUDICATED` 默认，无映射即报错、**不回落**；`LEGACY_IDENTITY` 须显式）；匹配拆为 `_match_by_identity`（仅诊断/对照）与 `_match_by_adjudication`（只校验裁定合法性，不二次判定）；`RoleMetrics`/`OriginMetrics` 增 `correct_extra`，`precision = (tp+correct_extra)/(tp+correct_extra+fp)`（默认 0 时与原式恒等），`recall` 分母不含它。
- 裁定词汇表单源：`AdjudicationJudgement` 定义在评分器，`adjudication_assembly.Judgement` 改为其别名。
- 既有测试 **14 处**调用点显式加 `LEGACY_IDENTITY`（**断言一字未动**）；新增 `tests/test_corpus_structured_scoring_adjudicated.py`（20 项）。
- **legacy 不变性已实测**：复跑 `evidence/36` 四臂（A `0/222/48`、B `tp 19`、C `tp 0`、D/D2 `0`），比对 **12 个字段区**全部一致、`differing_sections = []`，`36/l9-redo.json` 字节未变。方法：复制到同深度临时目录 + 包装注入 `LEGACY_IDENTITY`，**未改历史脚本**（`in_place_edits = 0`、`historical_scripts_edited = false`），副本已删除。
- **已知破面（已声明）**：另有 3 个已执行的历史脚本（`10/run_quality_score.py:246`、`34/audit_chain.py:327`、`36/l9_redo.py:208`）未传 `matching_mode`，改造后再跑会报错——刻意如此（身份相等不得为缺省），三者不改。
- **P02 不产生门分数**：真实裁定数仍为 0；不改阈值（属 P03）；不实现口径归一化（属 P04/P05）。
- 回归：80 项全通过（23 legacy + 20 裁定驱动 + 24 装配器 + 13 护栏）；`ruff check`/`format --check` 全绿。

**P07 编号歧义：已收敛**（`evidence/52-p07-numbering-closure-20261012/`）。

- 裁定：**41 归 `41-items-chain-accounting`**（存在 `issues/41-…-freeze.md` ⇒ 编号与 Issue 号对齐是唯一可判定的权威依据）；**契约草案保持 45**（原为 41，已改号）。规则：编号全局唯一，有对应 Issue 者优先占用该号。
- 全树 grep 出 5 处旧路径：2 处**历史记载**（保留）、3 处活引用断裂。其中跨并行目录的 `41-…/r2-proposals/contract-v4-draft.md:80` 经 U 同意已修正（`f8a8edf1…` → `620bc6cc…`，单行路径，非签认件）。
- 另 2 处（`45/MANIFEST.json` 的 1 条过期输入键、`45/draft_contract_v4.py:10` 用法注释）**刻意不就地修**：45 的脚本自带签认护栏，重跑会被拒；`--force` 会抹掉 U 的签认。按 write-once 登记，待该目录出新版本时一并修。
- **连带发现（D9 的起因）**：`45/draft_contract_v4.py:281-283` 记载——重跑该脚本**曾静默抹掉 U 在 `contract-v4-review.md`（`753532e8…`）上的签认**。⇒ D9 不是抽象风险，本项目已真实发生过一次；P06 的方向（机制 + 执行器 + 例外登记）与该教训一致。P06 扫描器**未漏报**此项（`guarded = 3` 中即含该脚本）。

**P08 r0 目录 MANIFEST：已完成 ⇒ Wave 0 收口**（`evidence/54-p08-manifest-backfill-20261012/`）。

- 判定规则：本工作流目录 ⇒ **回填 MANIFEST**（哈希可核）；**并行会话目录 ⇒ 声明不补**（避免形成第二个相互竞争的真相源，延续既有跨目录边界）。
- 回填（**只新增文件，`in_place_edits = 0`**；经 `tools/evidence_guard.write_once` 写入，故禁止覆盖）：

| 目录 | 域产物 | 声明输入 | 见证文件 | MANIFEST sha256 |
|---|---|---|---|---|
| `32-…/r0-zero-call` | `freeze-manifest.json` | 7（域产物自声明） | 9 | `21e6ec68…` |
| `33-…/r0-zero-call` | `workbench.json` | 3（域产物自声明） | 7 | `285984d6…` |
| `34-…/r0-zero-call` | `chain-audit.json` | 5（域产物自声明） | 3 | `229ecffd…` |
| `35-…/r0-zero-call` | `gold-audit.json` | **0（显式"不推断"）** | 5 | `f834a610…` |

- `35` 的 `gold-audit.json` 未声明 `inputs`：**不推断**输入清单（产物内的 sha256 多为记录级引用，当作输入即为编造），只保证输出侧可核。
- **声明不补**：`41-…/r0-zero-call`（并行会话目录；其 `accounting-checks.json` 已含 14 条 inputs 与 checks，即为该会话真相源）。
- 回填件效力边界（已写入每件）：`kind = retro_manifest`，证明的是**回填当日**字节，**不**证明该目录自创建以来字节未变；不是该目录诞生时的清单。
- 复跑幂等（全 `already_present_skipped`）；P06 护栏扫描仍 `violations = 0`；回归 80 项全通过。

> **Wave 0 至此全部完成**（`evidence/44-replan-20261012` 的退出判据：P01/P02/P06/P08 全部产出且回归通过；P07 已由 U 决定）：P01 装配器 ✅、P02 匹配改造 ✅、P06 护栏推广 ✅、P07 编号收敛 ✅、P08 MANIFEST ✅。**但 Wave 0 完成不等于门 33 有分数**——真实裁定数仍为 0，卡点已从"工程缺失"转为"① Stage 2 真实裁定（222 条）、② 补跑授权（7 条 critical）"两件需 U/人手的事。

### 5.14 Stage-1 助手 v2（r7 补记，§7-5 已完成）

产物：`evidence/42-stage1-suggester-upgrade-20261012/r0-zero-call/`（零调用只读；幂等、支持 `--no-write`；工作台 v2 字节未变）。

| 产物 | sha256 |
|---|---|
| 预注册 `preregistered-suggester-v2.json` | `96fb234f…5b16d2` |
| `suggestions-v2.json` | `7fa2fdc9…03a4bb` |
| `suggester-v2-report.json` | `2fc2896d…61a970` |

- **目标不是"更准"（无真值、不可测），而是"每条建议带可核验证据链"**：信号 = 槽位关联 + 逐字引文 + 数值交集 + 字符 2-gram + 归一化枚举一致（权重预注册固定，未调参）。
- **置信分布显著改善**：high 3→**46**、medium 17→**129**、low 146→**8**、none 56→**39**（222 候选同批对比）。
- **有逐字引文证据链的金标**：quote+context 口径 **41/48**；限定 quote-only **39/48**，与 issue-35 的 `records_with_exact_candidate_quote = 39` **一致**（EC-S1 交叉校验通过）——**EC-S1 的口径差已定位为"是否含 `context_evidence` 引文"**，两者必须分别披露，不得互相替代。
- **硬约束遵守**：未把金标 `semantic_fields` 写入候选（禁止重犯旧预填 19 条的错误）；候选字段逐字节未变（EC-S5 通过）；**未报任何准确率**（EC-S2）。
- top1 变化 161/222 ⇒ 属新基线：Stage 2 须以 `suggestions-v2.json` 为准（合并方式见其 md）。

## 6. 量化天花板（诊断口径，非生产报分口径）

> **2026-10-12 更正（见 §11）**：下表中凡取自门 33 草案的数字均**受污染**，不得用于门槛判断。
> 草案助手把金标字段回填进候选（违反契约 `matching.normalization`），"命中"因此测的是回填操作。
> 仍可靠的只有"物理丢失"类数字（48 − 7、md 22 − 7、7 条 critical）。结论方向不变。

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
| 5 ✔ | **已完成（2026-10-12）**：Stage-1 助手 v2（证据链版），见 §5.14 | `19/48` 量的是助手（high 3 / medium 17 / low 146 / none 56），不是抽取质量；且该数两臂均为构造量（§5.4） | 工具，零调用 | 否 |
| 6 | 记账与口径一致性：契约哈希 v2→v3 绑定、`validation-report` 空缺、门 32 判据与被测对象同轴、评分器阈值与门 28 对齐 | 否则任何"契约已绑""协议已验""阈值即口径"的陈述都不可信 | 记账，零调用 | 阈值变更需具名签认（**已并入契约 v4 草案 OPEN-1**，§5.13） |
| 7 | 读路径规则写成**与记录 ID 无关**的字段语义规则，并逐字段给出"候选字段 → 契约字段"映射 + 不可派生反例清单（§5.5） | 否则修复只对本批 19 条成立、不可推广（§5.7） | 契约 v4 条款 | 需裁定 |
| 8 ✔ | **已完成（2026-10-11，授权后）**：用留出记录重做 L9、禁止金标注入；结论见 §5.8 | 现行 `19/48` 是循环量，不能作为路线 a 的可行性证据（§5.4） | 零调用 | 否 |
| 9 ✔ | **已完成（2026-10-12）**：claims / material_relations 同型 L3 零调用审计，结论见 §5.11 | 另两角色的同型接缝未验证，不得以 items 单角色推断（§5.6） | 零调用 | 否 |
| 12 | 修 `material_relations` 契约：`from/to_gold_record_id` 要求候选携带**金标主键**，严格 identity 下恒为 0；须改为裁定映射或删去 | 该角色在现契约下**结构性不可评分**（§5.11 EC-B4） | 契约条款 | 需具名签认 |
| 13 | 执行 route b 收益的受控双臂实验（预注册草案已就绪） | 缺它则 route b 的收益永远只是假设（§5.12 缺口 2） | 真实调用 | **需授权**（模型／`attempts_max`／节流／预算／样本包号） |
| 14 | 对 32 条人工裁定区间做分层抽样裁定（xyl） | 缺它则 route a 的收益只有下界 7 与上界 39（§5.12 缺口 1） | 人工 | 需 xyl |
| 10 ✔ | **已完成（2026-10-12）**：重建门 33 工作台 v2（严格超集，补回 `speaker_ref` 与 layer B 字段），结论见 §5.10 | 现行工作台缺该字段（影响 222/222 条），Stage 2 人工裁定**不可执行**（§5.9） | 零调用，工具 | 否 |
| 11 | 定枚举**口径归一化条款**（`perspective`／`speech_role` 等） | 金标与生产端同轴默认值相反；不立此条款，任何匹配恒为 0（§5.9） | 契约条款 | **已起草（v4 草案 `caliber_rules`，§5.13），待具名签认** |

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
| ~~契约 v4 草案审阅~~ | **已签认（2026-10-12）**：OPEN-1 = **A**、OPEN-2 = **C**；落地见 §5.13.1 | xyl | 2026-10-12 |
| ~~v4.1 并入并行草案核心条款~~ | **已签认（2026-10-12）**：`46-…/contract-v4.1-review.md` `1d012182…`；落地 `47-…/scoring-contract-v4.1.json` `c76ac13e…`（`frozen_signed`）；备注为空 ⇒ 两处可质疑项按原样接受（见 §5.13.4） | xyl | 2026-10-12 |
| **P12 金标冻结链再绑定**（v2→v4.1） | ☐ 签认（新版本记录，不就地改）　☐ 退回 | | |
| **P13 门 28 基准推进**（`metric_basis` + `gold.scoring_contract_sha256` 同轮 → v4.1） | ☐ 签认（新版本门记录）　☐ 退回 | | |
| 阈值统一 | （已由 OPEN-1 = A 裁定：门 28 为单一口径；评分器须改为读契约，**代码未改**） | xyl | 2026-10-12 |
| 读路径普遍性（§5.7 三条硬要求） | ☐ 接受三条并写入契约 v4　☐ 只修本批数据 | | |
| 跨角色范围 | ☐ items-only　☐ 每角色各建读路径（先做 §7-9 审计） | | |
| B-1 两条 md 记录（NT-I06／NT-I41） | ☐ 纳入补跑范围　☐ 判为模型 `no_supported_item`　☐ 关联方法差异（非损失） | | |
| `material_relations` 契约缺陷（§7-12） | ☐ 改为裁定映射　☐ 删去 `from/to_gold_record_id`　☐ 该角色本轮不纳入评分 | | |
| route b 受控实验授权（§7-13） | 模型／`attempts_max`／节流／预算上限／样本包号（预注册草案见 §5.12④） | | |
| 32 条区间抽样裁定（§7-14） | 抽样量／分层方式（决定 route a 收益） | | |
| 路线 a/b 最终裁定（r3 依据） | ☐ route a（零调用：修投影 + 复用 layer B 派生 + 口径归一化条款；自动对齐 7/48，余靠人工）　☐ route b（重抽统一口径，作废门 32 冻结）　☐ a + 定向补跑 | | |
| 枚举口径归一化条款（§7-11） | ☐ 以金标口径为准（`source_explicit→unknown` 等）　☐ 维持生产端口径并改金标　　须具名签认 | | |

## 10. 签认栏

- 复核人：　　　　日期：
- 结论：☐ 认可本口径　☐ 退回修改
- 备注：

> **撤销记录（2026-10-12）**：本栏此前曾被预先填入签名与日期（结论勾选为空，属**半签**且未经审阅）。
> 按 U 指示于 2026-10-12 **撤销签认**，恢复为未签认状态；该次填记**不是有效签认**，
> 不作为任何后续步骤（含 §7/§9 各项）的依据。原文不改写、以本记录留痕。

## 11. 修订记录（2026-10-12，记账核对票带出；原编 36 号，后改号为 41）

原文不改写，只在此登记更正。依据 `evidence/41-items-chain-accounting-20261012/r0-zero-call/accounting-checks.json`。

1. **§6 的草案来源数字受污染（AC-5 / AC-6）**：Stage-2 v1 助手把**金标**的 `semantic_fields` 写进候选
   `canonical_observed_fields` 并预置 `judgement=accepted`，违反契约 `matching.normalization`
   「不从金标反填候选缺字段」与 `matching.projection`。因此：
   - `19/48`（§3 L9 与 §6）**不是预期待匹配数**，它是"把金标拷进候选"这一步的产物；
   - `critical_matched = 1`、`risk/condition matched = 5` 同样受污染；
   - **仍可靠**：48 − 7 = 41/48；md 22 − 7 = 15；7 条 critical 物理缺失（均来自
     residual-attribution 与 Issue 35，与草案无关）。§6 的结论（补跑是必要前提）不变。
2. **新增：评分器匹配模式与契约冲突（AC-4，§3 L7 的加强）**：评分器按
   `(role, source_id, origin, semantic_fields)` **严格相等**匹配（`structured_scoring.py:118-142,457`），
   而契约 v2 起即写明 `matching.mode = human_adjudicated_semantic_equivalence…` 且"proposition 不用
   逐字字符串相等判定"。故 L7 不止"未实现 v3 读路径"，其**匹配机制本身即违反契约**。
3. **新增：契约合法操作下自动匹配为 0**（`contract-gap-report.json`）：即使只比较双方都携带的 5 个
   共有字段（`semantic_type/statement_role/speech_role/perspective/polarity`），匹配数仍为 **0**。
   推论：读路径**不能**实现为"共有字段相等"，只能定义载体映射（候选 `text` → 契约 `proposition`），
   等价性必须由**人工**判定，评分器必须**消费裁定**而非自行重算。
4. **新增：契约是三方孤例（§5.2 的机读复核）**：候选缺 4 项（`proposition`/`attribution`/
   `source_stance`/`speaker_ref`）；金标比契约多若干项。契约描述的形态，生产端不产出、金标也不完全使用。

## 12. 与并行会话实测的对账（2026-10-12，Issue 41 带出）

同一链路上另有会话产出 `evidence/36-l9-redo-…`（L9 重做）、`37-…`（路线决定）、`38-…`
（工作台 v2）、`40-…`（路线 a/b 成本-收益）。其实测推翻／修正本文若干数字，**以实测为准**：

| 本文原写 | 并行实测 | 处置 |
|---|---|---|
| §6：覆盖槽位内无候选 = 7 条 | **9 条**（除丢包区 7 条外，另有 NT-I06 `char:1393-1655`、NT-I41 `char:5055-5071`，且这两条不在 residual-attribution 的归因里） | **撤回** |
| §6：`48 − 7 = 41/48`、`md 22 − 7 = 15` | `48 − 9 = 39`；且 route a 的记录级上界分两种口径：**strict 0/48** 与 **carrier-only 35/48**，两者**不得合并表述** | **更正** |
| §6：md 分源召回 0.682 → 判"不可达" | 该差异 **100% 由 corpus_absent 解释**；剔除无候选记录后 md/docx 同为 1.0 ⇒ 规则本身跨源成立 | **更正**（结论降级：随语料缺口，非规则失效） |
| §5.2：候选 `semantic_fields` 11 项含 `speaker_ref` | 222 条候选 `speaker_ref` 载体 **0**、`proposition` key 存在数 **0** | **更正** |
| §5.1：condition 读路径"正是为条件组设计" | 方向对，但 10 条 condition 金标中仅 **1** 条覆盖槽位内有 condition 候选 ⇒ 该读路径**几乎无可读数据** | **补正** |
| §3 L9 记 `19/48`（金标字段形态） | 与 §11-1 一致：`B_gold_injected=19`、`A_native=0` ⇒ 19/48 全部来自金标注入 | 已由 §11 更正 |

**仍然成立的结论**：

1. 根因接缝唯一（L3 ≡ L7）；L9 是测量不是节点；契约是三方孤例（§4.1、§5.2）。
2. 阻塞出分的三项（接缝路线、Stage-2 结构阻塞、丢失包）——其中**接缝路线已由 `37` 裁定为 route a**；
   故本文 §7 的修复依赖序应由 `40` 的工作项表（C1–C6 / A1–A2 / B1–B4 / I1–I2）取代。
3. **补跑丢失包（`40` 的 I1）仍是必要前提**：9 条覆盖槽位内无候选的记录中，7 条属丢包区且
   全部为 critical；`unresolved_candidates_max = 0` 与人工裁定 222 条是与路线无关的共同项。
