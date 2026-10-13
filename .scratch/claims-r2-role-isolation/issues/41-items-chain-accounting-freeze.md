# 41 · items 链路口径冻结与记账一致性（零调用）

Status: in_progress（Stage 1 记账核对 + Stage 2 助手修正已落地；契约 v4→v4.3 与门 v3 已于 2026-10-13 由 xyl 具名签认——原记「契约/阈值/判据变更待签认」已闭合；P04/P05 口径归一化与回归、route a/b 仍未完成）
Type: gate task
Parent: [34 · 链路根因审计](../evidence/34-chain-root-cause-audit-20261011/chain-report.md)、
[33 · items-only 质量评分门](33-items-quality-scoring-gate.md)
Model attempts: 0
Production database access: 0

## 1. 问题

同一批证据在相邻轮次得出「1 个接缝 / 2 个节点 / 4 个节点」三种数字，用户判定"判断出现不同判断"。
根因不是推理错，而是**口径未声明且中途更换**，加上**链路里存在多份互相冲突的"真相"**。

本票做两件事：① 把口径冻结成可核验的规则；② 把"多份真相"变成机读检查并修掉其中一条
（Stage-2 助手执行了契约明文禁止的操作）。

## 2. 口径冻结（`items-chain-accounting-v1`）

所有计数一律按三元谓词给出：**层级（L1–L9）× 性质（缺陷／事件／未做／已闭合）× 是否阻塞出分**。

三条硬规则：

1. **"测量"不算节点**——L9 是对 L3∩L7 的可执行验证，不构成第三个坏节点。
2. **"非根因"不等于"无问题"**——未证明是根因只能记 `not_root_cause`，不得写成"通过"。
3. **"已修"不等于"已过门"**——v6 消除根因（双臂实测）与门 32 `structural_fail` 是并列事实。

| 问法 | 确定答案 |
|---|---|
| 根因接缝 | **1**（L3 ≡ L7，同一接缝两侧） |
| 阻塞出分的位点 | **3** |
| 执行链未闭合 | **1 缺陷（我方信号 2 槽）+ 1 事件（1 包 = 7 条 critical）** |
| 评分链未闭合 | **2 代码位点 + 1 项结构性不可执行** |
| 已闭合 | **2**（v6 协议、契约 v3 签认） |
| 记账／判据／口径缺陷 | **7**（见 §4） |
| 明确非问题 | **5** |

## 3. 交付物（零调用，实跑）

| 产物 | sha256 |
|---|---|
| `../evidence/41-items-chain-accounting-20261012/r0-zero-call/audit_accounting.py` | `39451a79…5ce344` |
| `…/r0-zero-call/accounting-checks.json` | `0ea8ee9b…7c60a8` |
| `…/r0-zero-call/accounting-checks.md` | `02ae5986…436f772` |
| `…/r1-stage2-v2/build_adjudication_draft_v2.py` | `3c681519…7dee831` |
| `…/r1-stage2-v2/adjudications.v2.json` | `67cbd78d…1c452578` |
| `…/r1-stage2-v2/contract-gap-report.json` | `c3cdbfe7…4a45f3d` |

两个脚本均零模型调用、只读输入、`--no-write` 可用、重复运行逐字节一致（已实测两次哈希相同）。
**未修改任何既有产物**（含冻结目录）；v1 产物字节不动。

勘误（2026-10-12，签认前复核登记）：`accounting-checks.md` 标题残留改号前旧称 "Issue 36"；
该文件为 write-once 证据，不改字节，以本行为准。

## 4. 记账核对结果：PASS 4 / FAIL 7（2 项需具名签认）

### 通过

| 检查 | 结论 |
|---|---|
| AC-2 | 门 28 的契约绑定 == 实际签认契约 v3（`d9bc51f2…`），`quality_requirements_status=signed` |
| AC-9 | 冻结金标字节未变（`603de5e6…`，48 条，`material_items` 48） |
| AC-10 | 门 28 的 16 条高风险断言 == 契约 items 角色断言子集（Issue 30 的扩充完整） |
| AC-11 | 门 32 判定记录引用的冻结清单哈希可复核（`1a0e008a…` 实测一致） |

### 未通过（全部为真实缺陷）

| 检查 | 事实 | 处置 |
|---|---|---|
| **AC-1** | 金标冻结链 `freeze-manifest.inputs` 记录契约哈希 `2eb24be7…`（v2），实际签认 `d9bc51f2…`（v3）；`freeze-state.contract_snapshot.status = draft_pending_human_review` | 需出**再绑定记录**（新版本，保留旧哈希），不得就地覆盖 |
| **AC-3** | 评分器硬编码 `RoleThreshold(MATERIAL_ITEMS, 19/20, 9/10)` + `risk_condition_recall_min=19/20`；门 28 权威值为 `0.85 / 0.80`。评分器既不读契约也不读门 | 阈值统一（**须具名签认**） |
| **AC-4** | 评分器匹配 = `(role, source_id, origin, semantic_fields)` **严格相等**（`structured_scoring.py:118-142, 457`）；契约 `matching.mode = human_adjudicated_semantic_equivalence_then_one_to_one_mapping`，且明写"proposition 不用逐字字符串相等判定" | 评分器改为**消费人工裁定映射**；需代码改造 + 复核 |
| **AC-5** | Stage-2 v1 把**金标**的 `semantic_fields` 写入候选 `canonical_observed_fields` 并预置 `judgement=accepted`，违反契约 `matching.normalization`「不从金标反填候选缺字段」与 `matching.projection` | **已修**（v2 助手，见 §5） |
| **AC-6** | `draft-preview.json` 的 `19/48`、`critical 1/12`、`risk 5/21` 均由 AC-5 的操作产生 | 三个数字**受污染，不得用于任何门槛判断** |
| **AC-7** | `validation-report: status=valid_review_draft`、`human_accepted_counts={}`、`formal_gold_frozen=false`；而 `freeze-state` 声明 `formal_gold_frozen=true` | 需补冻结后的验收记录（新版本记录，不改冻结件） |
| **AC-8** | 门 32 `verdict=structural_fail` 与 `root_cause_status=eliminated` 并列；`protocol_status_valid=not_checked` 因 items task 未成功。用结构完备性判据测协议修复，一次无关传输抖动即可否决结论 | 判据同轴化（**须具名签认**） |

## 5. Stage-2 助手修正（§7-5 的实际形态）

`r1-stage2-v2/build_adjudication_draft_v2.py` 相对 v1 的三处改动：

1. `canonical_observed_fields` 一律取**候选自身**字段（不再从金标取）；
2. 所有候选保持 `judgement = pending`、`matched_gold_id = null`，不再预置 `accepted`；
3. 新增 `contract-gap-report.json`，把字段缺口与阻塞变成机读数字。

实跑结果：

```
candidates = 222          preset_accepted = 0
contract_legal_matches   = 0      （按候选原生字段做 identity，必然 0）
fields_missing_in_candidate = [attribution, proposition, source_stance, speaker_ref]
shared_fields_used = [semantic_type, statement_role, speech_role, perspective, polarity]
sizing_counterfactual_matches = 0  （反事实，非契约合法、非分数、不设门槛）
```

**关键新发现**：即便只比较双方都携带的 5 个字段，匹配数也是 **0**。这说明：

- 契约合法操作下**无法自动成立任何匹配**（AC-5 的 19/48 确实是拷贝的产物）；
- 读路径规则**不可能**实现为"共有字段相等"；它只能定义**载体映射**（候选 `text` → 契约
  `proposition`），随后由**人工裁定等价**，评分器必须消费该裁定，而不是自己按 identity 重算
  （与 AC-4 同一件事）。

## 6. 待签认项

| 项 | 内容 | 归属 |
|---|---|---|
| 口径冻结 | 采纳 `items-chain-accounting-v1`（§2） | 本票 |
| 阈值统一 | 以门 28（0.85/0.80）为权威，还是改门适配评分器（0.95/0.90） | 具名签认 |
| 门 32 判据同轴 | 拆分"协议修复确认"与"结构完备性"两组判据，保留原判据记录 | 具名签认 |
| 契约 v4 | 读路径以金标形态为权威 + Stage-2 规范化责任 + 阈值单源（草案另附） | 具名签认 |
| 评分器改造 | 由 identity 匹配改为消费人工裁定映射（实现已签认契约 v3，非改口径） | 复核 |

## 7. 范围外／不做

- 不改冻结金标、冻结清单、冻结状态、门 28/32/33 既有产物；不就地覆盖任何历史哈希；
- 不改阈值、不改判据（仅出提案，变更须具名签认）；
- 不放宽 fail-closed 校验与解析；不启用 `response_format`；
- 不代做人工裁定（契约要求 `human_adjudicated`）；不发布、不访问生产库；
- 本票不发起任何模型调用。

## 8. 关联

- 根因与口径重算：[34 链路根因报告](../evidence/34-chain-root-cause-audit-20261011/chain-report.md)
- 记账核对证据：`../evidence/41-items-chain-accounting-20261012/r0-zero-call/accounting-checks.md`
- 契约缺口与阻塞：`../evidence/41-items-chain-accounting-20261012/r1-stage2-v2/contract-gap-report.json`
- 金标审计：Issue 29；契约补签：Issue 30；评分门：Issue 33

## 9. 与并行会话产物的对账（2026-10-12）

同一链路上已有另一会话产出 `evidence/36-l9-redo-and-baseline-20261011`、
`37-store-baseline-and-route-decision-20261012`、`38-gate33-workbench-rebuild-20261012`、
`39-roles-l3-audit-20261012`、`40-route-ab-decision-inputs-20261012`。本票因此**改号为 41**
（原 36 与其证据目录撞号）。对账结果：

| 本票工作 | 并行会话已有 | 处理 |
|---|---|---|
| AC-5 金标反填（19/48 是拷贝产物） | `36/l9-redo`：`B_gold_injected=19`、`A_native=0` ⇒ 19/48 全部来自金标注入 | **互相印证**，不重复 |
| §7-1 接缝路线待裁定 | `37/route-decision.json`：**已裁定 route a**（absent=`['source_stance']`，归一化后 5 元组对齐 7/48，留出 3） | 本票 §6 该项**撤销**（已决） |
| §7-5 Stage-1/2 助手修正 | `38`：工作台 v2 已重建（补 `speaker_ref`/layer B，给出 contract_view） | 本票 `r1-stage2-v2` 仅保留**记账证据**价值，不再单独推进 |
| §7-6 阈值单源 / 评分器读契约 | `40`：已列为共同项 C3 | 归并到 `40` 的工作项表 |
| §7-1/§7-3 契约条文 | `40`：C1+C2（同一份 v4） | 本票 `r2-proposals/contract-v4-draft.md` 降为**输入**，不单独签认 |
| §7-2 补跑丢失包 | `40`：独立项 I1（须先定重试/幂等策略） | 维持：需授权参数，本票不发起 |

**本票的净贡献**（与上述不重复的部分）：

1. `items-chain-accounting-v1` 口径与三条硬规则（§2）；
2. 机读记账核对 AC-1…AC-11（PASS 4 / FAIL 7）；其中 **AC-1 金标冻结链契约绑定 v2→v3 漂移**、
   **AC-7 冻结后验收记录空缺**、**AC-8 门 32 判据不同轴** 三项是并行产物未覆盖的；
3. 下面这张**撤回表**——更正本票与 34 号报告里被并行实测推翻的数字。

**对照后须撤回／更正的既有数字**：

| 我写的 | 并行实测 | 依据 |
|---|---|---|
| 覆盖槽位内无候选 = 7 条 | **9 条**（另含 NT-I06 / NT-I41） | `36/l9-redo.md` backlog B-1 |
| 48 − 7 = 41/48 为召回上界 | 48 − 9 = **39**；且两份口径（strict 0/48 与 carrier-only 35/48）**不得合并表述** | 同上 EC-4 |
| 候选 `semantic_fields` 含 `speaker_ref` | 222 条中 `speaker_ref` 载体 **0**、`proposition` key 存在数 **0** | 同上"候选侧实测" |
| condition 读路径"正是为条件组设计" | 10 条 condition 金标中仅 **1** 条覆盖槽位内有 condition 候选 ⇒ **几乎无可读数据** | 同上 backlog B-3 |
| md 分源召回 0.682 判"不可达" | 该差异 **100% 由 corpus_absent 解释**；剔除后 md/docx 同为 1.0 ⇒ 规则跨源成立 | 同上 EC-3 |

## 10. 签认栏

- 复核人：　　xyl　　日期：2026-10-12
- 结论： x 认可口径并准予继续　☐ 退回修改
- 待签认项（§6）逐项：☐ 口径 ☐ 阈值 ☐ 门 32 判据 ☐ 契约 v4（并入 `40` C1/C2） ☐ 评分器改造（`40` C3）
- **agent 记录的落地状态（2026-10-12）**：文件级"准予继续"已生效；§6 逐项框未勾选，故按下列口径执行：
  - 已落地（**方向无关**项）：口径冻结采纳、AC-1 再绑定记录、AC-7 验收记录投影、契约 v4 提案、门 32 判据拆分提案（见 §11）；
  - **仍未决、不代选**：阈值方向 —— A：以门 28 为权威（0.85 / 0.80）改评分器；B：维持评分器现值（0.95 / 0.90）并改门。
- 授权依据：`user_chat_2026-10-12` 指令「已签认签 issues/41-items-chain-accounting-freeze.md」。

## 11. 签认落地（零调用，实跑，幂等）

| 产物 | sha256 | 落地内容 |
|---|---|---|
| `../evidence/41-items-chain-accounting-20261012/r3-signoff-apply/apply_signoff_41.py` | `66d5db72…60286ecf` | 本次落地脚本（只读输入、`--no-write` 语义由只写本目录保证、重复运行逐字节一致） |
| `…/r3-signoff-apply/freeze-rebinding-record.json` | `b197ece9…3ce98d1` | **AC-1**：金标冻结链记录的契约哈希 `2eb24be7…`（v2）→ 有效绑定 `d9bc51f2…`（v3）的再绑定记录；三个冻结构件字节未动 |
| `…/r3-signoff-apply/gold-acceptance-record.json` | `154178d4…11ac1acf` | **AC-7**：从 `frozen-gold.json` 自身 `review_status`/`adjudication` 确定性投影出验收计数 `claims 20 / material_items 48 / material_relations 24 = 92`，逐条有裁定；不新增任何断言 |
| `…/r3-signoff-apply/scoring-contract-v4.proposed.json` | `b3f88649…ae7818f` | **C1/C2**：契约 v4 提案。差分实测：**新增 2 键**（`items_field_carrier_read_path`、`threshold_single_source`）、**删除 0 键**、变更仅限 6 个元数据键；`status=proposed_pending_signoff`；`threshold_single_source.required_alignment = PENDING_SIGNOFF` |
| `…/r3-signoff-apply/gate-32-v2-criteria.proposed.json` | `c4675ecf…322a2df8` | **AC-8**：门 32 判据拆为 G1（`protocol_status`/`reasoning_tokens_*`/`control_arm_must_reproduce_failure`）与 G2（其余 7 项）；原判据与判定文件逐字保留；附门内键名↔判定文件键名对照表 |

**未改动**：`frozen-gold.json`、`freeze-manifest.json`、`freeze-state.json`、`scoring-contract.json`(v3)、
`preregistered-gate.json`(28/32)、门 33 既有产物 —— 落地后哈希逐一复核为原值。

**v4 仍需你签**：① 是否采纳 v4（替代 route b）；② 阈值方向 A/B；③ 是否裁决 39 号 §7-11 的
"每角色通用读路径机制、先只落 items"。

## Comments（2026-10-13 追加，不改写以上字节）

- **待签项已闭合**：上列 ①②③ 与契约 v4 的后续版本链已由用户具名裁定并签认——契约 v4（`evidence/43-…`，
  OPEN-1=A / OPEN-2=C）→ v4.1（`evidence/47-…`）→ v4.2（`evidence/58-…`，改钉门 28 **v2** `8cc11bcc…`）
  → **v4.3**（`evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json`）。本票头部
  `Status` 中「契约/阈值/判据变更待签认」据此更新。
- **同轮新增的门与出分**：门 28 模板由 **v3** 取代（`evidence/75-…/gate-v3.json`，`sha256:340b312d…`）；
  门 33 在 v3 + v4.3 基准下重算 **PASS**（`evidence/77-…/r1-score/`，41/48 = 0.854）。**六项阈值逐字未改。**
- **P03 绑定已追平**：评分器契约快照 → v4.3 六项 + 哨兵 11 项（`evidence/78-…/verification.md`，8/0 通过）。
- **仍未完成（本票不结）**：P04/P05 口径归一化与回归、route a/b 裁定、缺口 1（32 条区间的人工可裁定比例）
  与缺口 2（route b 收益）；**评分器改读契约阈值（OPEN-1=A 的兑现）代码仍未实施**。
