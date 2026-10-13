# 33 · items-only 质量评分门（门 32 产物的诊断口径评分）

Status: complete
Execution: 已验收（2026-10-13：质量门在 R2 修订基准「门 v3 + 契约 v4.3 + 7 条具名改判」下重算 PASS；原基准 FAIL 终态由新记录取代、旧证据字节未改；发布/query/delivery/context_use 与 M_main 消费仍未启动）
Type: gate task
Parent: [32 · items selector v6 与执行配置重冻结](32-items-v6-and-reasoning-refreeze-gate.md)
Model attempts: 0（本门全程零调用；R2 修订、重算与 P03 绑定追平同为 0 调用）
Production database access: 0

## 1. 目的

对门 32 **treatment 臂**（v6 提示词 + 关闭思考）产出的 items 做质量评分，回答"这批数据能不能用"。
分母是 Issue 10 冻结的 48-item 非表格金标；判据全部取自已签认的
`non-table-selected-target-scoring-contract-v3`（`scoring-contract.json`，xyl 2026-10-11 签认）。

本门**不**评价协议、不重跑模型、不修改任何既有冻结物。

## 2. 输入（全部只读）

| 输入 | 路径 | 说明 |
| --- | --- | --- |
| 候选 | `../evidence/32-items-v6-reasoning-refreeze-20261011/live/candidates.json` | treatment 两源产出，md 88 + docx 134 = 222 条 |
| 金标 | `../evidence/10-quality-gold-freeze-20261008-r2/frozen-gold.json` | `role=material_items` 共 48 条 |
| 契约 | `../evidence/10-quality-gold-expansion-20261008-r2/scoring-contract.json` | schema `non-table-selected-target-scoring-contract-v3` |
| 覆盖披露 | `../evidence/32-…/live/residual-attribution.json` | 9 个未产出槽位：7 基础设施 + 2 我方信号标注过强（含 2 条连带丢失） |
| 评分器 | `plugins/corpus/structured_scoring.py` | `score_structured_quality`（严格 identity 一对一匹配） |

## 3. 流程（三步，严格顺序）

**Stage 1 · 裁定工作台（零调用，已完成）**
导出 222 条候选与 48 条金标的完整对照、自动对齐**建议**、以及契约 `candidate_adjudication_fields`
要求的 11 字段裁定骨架。建议值只是降低人工工作量的辅助，**不是评分输入**。

**Stage 2 · 人工逐条裁定（xyl；不可省略）**
契约 `matching.mode = human_adjudicated_semantic_equivalence_then_one_to_one_mapping`，且
`matching.projection` 明确禁止"把目标字符串直接赋给候选并宣称自动语义评分"。因此每条候选必须由人给出
`judgement`（`accepted` / `edited` / `rejected` / `pending`）与 `matched_gold_id`，并保留原始候选字段、
裁定人、理由与依据。

**Stage 3 · 严格评分（零调用）**
把裁定结果规范化后送入 `score_structured_quality`（raw 与 validated 两份分别裁定与计分），输出
target recall / candidate precision / duplicates / origin 切片 / 覆盖率 / 报告支撑 / 门槛。

## 4. 报分口径（契约 v3）

- scope：`selected_target_recall_not_exhaustive_document_gold`——分母只有人工接受的 48 条目标，
  **不宣称**覆盖两份材料的全部命题。
- `target_recall` = 已匹配接受金标 / 接受金标总数（48）。
- `candidate_precision` = (matched + correct_extra) / (matched + correct_extra + incorrect + duplicate)；
  **存在 `unresolved` 候选时记 N/A 并如实披露，不得排除后报告通过**。
- 同义重复只计第一条，其余记 duplicate FP。
- 额外正确输出单列 `correct_extra`，不回填召回分母。
- `minimum_accepted_records_per_role = 20`。
- 16 条高风险断言（NT-I09/13/15/17/19/29/35/37/38/39/42/43/45/46/47/48）逐条人工判定；
  断言是回归防退化项，不自动证明语义正确。

## 5. 范围外／不做

- 不做 publication、positive_query / delivery / context_use / report_reference；
- 不改金标、不改阈值、不改评分契约、不新增金标（`new_gold_allowed=false`）；
- 不重跑模型、不改提示词、不放宽任何 fail-closed 规则；
- 不把本门结果表述为"生产默认口径"或"完整文档覆盖"。

## 6. 待披露项（必须随报分一并给出）

1. 9 个未产出槽位：7 个基础设施（md 一次传输未知）+ 2 个我方信号标注过强（docx；其中 1 个连带丢失
   2 条模型已产出内容）——**这 2 条不计入模型漏抽**；
2. docx 1 次请求内 2 个槽位被判失败的口径分歧（已在 `residual-attribution.json` 记录并保留
   "自动判定 / 人工裁定"两栏）；
3. precision 若因 unresolved 记 N/A，须同时给出 unresolved 明细。

## 7. 授权待填项

| 项 | 授权人 | 日期 | 参数 |
| --- | --- | --- | --- |
| `gold_consumption_and_scoring` |  |  | 只读金标 + 报诊断口径；不改金标 |
| `publication` |  |  | —（默认 false） |
| `production_database_access` |  |  | —（默认 false） |

## 8. 交付物

- `../evidence/33-items-quality-scoring-20261011/r0-zero-call/workbench.json`（候选 × 金标对照 + 建议 + 裁定骨架）
- `../evidence/33-items-quality-scoring-20261011/r0-zero-call/workbench.md`（人工裁定的可读清单）
- `../evidence/33-items-quality-scoring-20261011/r0-zero-call/adjudications.json`（Stage 2 产出，人工填写）
- `../evidence/33-items-quality-scoring-20261011/r1-score/score-report.json`（Stage 3 产出）

## 9. 签认栏

- 复核人：xyl　日期：2026-10-11
- 结论： 准予执行（按 §7 填授权）　☐ 退回修改

## 10. Comments（执行结论追加）

### 2026-10-13　Stage 2/3 完成：门 33 首次诚实出分 = FAIL（全判据）

- **裁定闭环**：222 池（`../../claims-r2-role-isolation/adjudication/worksheet.json`，reviewer=xyl×222，含 2026-10-12 U 校准撤销 3 行）+ 补跑签认 31 条（I06/I41 15 + base 16）= 253 条裁定；装配护栏 0 拒绝；5 条 out_of_scope 按契约排除。
- **门 33 结果**（全判据，`../evidence/69-union-adjudication-20261013/r1-score/gate33-full-verdict.md`）：召回 **34/48 = 0.708 < 0.85 FAIL**（源1 0.909 ✅ / 源2 0.538 ❌）；精确率 240/248 = 0.968 ✅；unresolved = 0 ✅；接受数 242 / 117+130 ✅；**16 条高危断言 8/16**（未过：NT-I09/I19/I38/I39/I45–I48，全部源2）。
- **FAIL 定性**：14 条 FN 为真实抽取覆盖缺口（三次独立抽取均未覆盖），非流程/匹配/裁定问题。
- **本轮新增 matched 金标 8 条**（NT-I06 + base 批 7 条）；"31"为裁定行数，不是匹配数。
- **裁定权威**：A 工作表唯一有效；`evidence/67` 机械预填经 29 行分歧比对后正式除名（69 号并集裁定）。
- **给 U 的观察**：本票据 §7 `gold_consumption_and_scoring` 授权行签署时未填（签认栏为准予执行）——建议补记或追认，避免后续审计再挂账。
- 证据链：`../evidence/65-…`（双臂补跑授权/执行）→ `66-…`（base 协议变更与修复）→ `67/68`（预填除名/回溯审计）→ `69-…`（并集裁定与出分）→ `70-…`（结案记录）。

### 2026-10-13　门 33 终态：不可达，如实记档（U 裁定）

- **裁定**：U 2026-10-13 明确——在「不改金标、不扩大样本」约束下门 33 无法达标，本轮判为**不可达**、如实
  记档；发布标准（结构完备性）另走「显式缺口」路线，**不再依赖补抽**。
- **终态**：门 33 = **FAIL（未过判据 1、2、7）**。判据 1 总召回 34/48 = 0.708；判据 2 源1 20/22 = 0.909、
  源2 14/26 = 0.538；判据 7 断言 8/16；判据 3/4/5/6 PASS。谓词声明与逐条记录：
  `../evidence/72-gate33-terminal-and-corrections-20261013/r0-zero-call/terminal-decision.json`、同目录 `corrections.md`。
- **不可达的结构原因**（零调用归因
  `../evidence/71-fn-attribution-20261013/r0-zero-call/fn-attribution.json`）：14 条 FN **全部**是同源候选
  「已抽到但被具名裁定为不等价」，**0 条**为抽取覆盖缺口、**0 条**落在 9 个未产出槽。判据 7 的 8 条缺口
  中 5 条（NT-I09/I19/I38/I39/I48）可经复核裁定回收；**剩余 3 条 NT-I45/I46/I47 即 U 2026-10-12 亲自校准
  撤销者**（候选与金标逐字相同，差别在 perspective/source_stance 口径），改判亦不可由执行方回收。
- **因此排除的出路**：定向补抽（同片段会被同一口径再判 correct_extra）、仅降数值门槛（判据 7 仍为 13/16）。
- **更正 4 处既有表述**（新记录 + 旧哈希留存，未编辑旧字节）：①「缺口为真实 FN（金标无候选匹配），非流程
  问题」；②「14 条 FN 为真实抽取覆盖缺口」；③「8 条未过断言全部属于源2」（实测 NT-I09/I19 属于源1，与该
  文件自身判据 2「源1 20/22」自相矛盾）；④「需对源2 对应片段定向补抽」。明细见
  `../evidence/72-gate33-terminal-and-corrections-20261013/r0-zero-call/corrections.md`。
- **登记但不判定**：判据 5 的接受数在 verdict（242）与评分器可导出值（tp+ce = 240）之间存在分歧，两者均
  ≥ 40，结论不变。
- **不阻塞**：发布标准与门 33 阈值/金标解耦——`plugins/corpus/structured/store.py` 对 gold/recall/assertion
  零引用（机器核验）。
- **仍待补**：§7 `gold_consumption_and_scoring` 授权行签署时未填，**未具名前保持挂账，不代签**；本票头部
  `Status`/`Execution` 行仍为旧值，待正式结票时同步。

## 8. R2 结票（2026-10-13 追加；不修改以上任何既有字节）

- **状态变更**：本票由 `preregistered_zero_call` 结为 `complete` / `Execution: 已验收`（用户 2026-10-13
  具名裁定「已验收」）。验收对象是**质量门**；发布与正向消费不在本票验收范围，仍未启动。
- **取代关系（关键）**：本票先前的 FAIL 终态记录（`../evidence/72-gate33-terminal-and-corrections-20261013/r0-zero-call/terminal-decision.json`，
  原基准下「不可达」）**未被改写**，取代关系由契约 v4.3 `registrations.supersedes_terminal_record` 登记。
  两段结论不矛盾：前者是**原基准**下的诚实终态，后者是**修订基准**下的过门。
- **R2 修订（三件，均具名签认；签署人 `xyl`，2026-10-13）**：
  - 门 v3：`../evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json`（`sha256:340b312d…`，
    `frozen_before_execution` + countersignature）；**六项阈值逐字未改**（0.85 / 0.80 / 0.80 / 40 / 20 / 0），
    哨兵清单由 16 项缩为 **11 项**（移出 NT-I09/I19/I45/I46/I47，逐条登记于
    `high_risk_item_assertions_excluded`）。
  - 契约 v4.3：`../evidence/75-…/scoring-contract-v4.3.json`（`sha256:d7b4f8a8…`，`frozen_signed`）；
    新增 `matching.items`「上下文唯一可恢复」条款，并登记冻结金标侧绑定落后（仍 v2）为例外。
  - 7 条具名改判：`../evidence/75-…/re-adjudication.json`（`named_signed`）——NT-I23/I26/I34/I38/I39/I45/I48
    由 `correct_extra` 改判 `matched`（三项人裁：二选一 = NT-I23、未选 I24；第 7 条 = NT-I45）。
- **重算出分（PASS）**：`../evidence/77-gate33-rescore-under-v3-20261013/r1-score/gate33-score-under-v3.json`
  ——召回 **41/48 = 0.854**（源1 20/22 = 0.909、源2 21/26 = 0.808）、精确率 30/31 = 0.968（与旧 240/248
  同比值）、unresolved 0、接受 240、哨兵 **11/11**；7 条判据全 PASS。**余量极薄（总 +0.004 / 源2 +0.008），
  不得读成生产可用或整篇覆盖。**
- **链条回溯审计**：`../evidence/76-r2-retro-audit-20261013/r0-zero-call/`——首轮 23 项检查 7 项未过并全部处置；
  复查 26 项、签认后相位 27 项均 0 未过。
- **实现绑定追平**：`../evidence/78-p03-binding-catchup-20261013/r0-zero-call/verification.md`——评分器契约快照
  推进到 v4.3 六项 + 哨兵 11 项（改 `plugins/corpus/structured_scoring.py`、`tools/check_freeze_chain.py`
  与 2 个测试文件）；8 项核验通过 8/失败 0、冻结链校验器 `exit 0`。
- **前置表述更正（引用，不改写旧行）**：本票前文「8 条未过断言全部源2」一句不成立（NT-I09/I19 属源1），
  更正见 `../evidence/72-…/r0-zero-call/corrections.md` 第 3 项；「14 条 FN 为真实抽取覆盖缺口」亦由
  `../evidence/71-fn-attribution-20261013/` 更正为「候选已抽到、被判不等价」。
- **仍开放（不阻塞结票）**：§7 `gold_consumption_and_scoring` 授权行仍为空（未具名，挂账不代签）；
  **评分器改读契约阈值（OPEN-1=A 的兑现）代码改动仍未实施**——77 是独立脚本重算，不等于评分器已改造。
- **共享护栏缺陷已修（2026-10-13，同轮）**：`tools/evidence_guard.artifact_state` 把未签门草案读成 `signed`
  （76 号 §四第 4 行的上报项）已修复——`countersignature` 占位块不再等同签署，证据守卫扫描由 `exit 1 /
  violations 1` 恢复为 `exit 0 / violations 0`，且未登记任何脚本为例外；记录见
  `../evidence/79-guard-countersignature-fix-20261013/r0-zero-call/`。
