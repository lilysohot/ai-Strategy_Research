# I3-2 其余冻结项清点（2026-09-18，i0c-r26 之后）

> 权威范围来自 `docs/plan/corpus-ingestion-rebuild-tasks.md` 第 321 行（I3-2）：
> **"在本轮候选业务结果可见之前确认 source/query gold、旧基线映射、各类阈值/关键题/负例，
> 冻结评分器与试验初始版本"** → 拆成 8 个子项逐项对账。
> 本文件是**清点与计划**（未入冻结绑定）；机读版见 [inventory.json](inventory.json)。

## 0. 一句话结论

**已闭环 2 项**（source gold、负例清单本体）、**部分闭环 2 项**（query gold 缺机器可读 targets；
旧基线映射存在但未随 I3-2 重绑）、**完全未做 3 项**（阈值取值确认、试验初始版本、关键题清单确认）、
**无缺口 1 项**（评分器已冻结）。
**最关键的阻塞**：`query-gold-frozen.jsonl` **30/30 题没有 `evidence_targets`**——评分器按设计
对每题落 `missing_required_input:<qid>:evidence_targets_absent`，即**现在无法对任何一题产出有效指标**。

## 1. 逐项对账

| # | 冻结项 | 现状（证据） | 缺口 | 谁做 | 能否零模型 |
|---|---|---|---|---|---|
| 1 | **source gold** | ✅ **已冻结**：`source-gold-frozen.jsonl` `37662c77…`（36 槽位 = 冻结 23 条逐字节保留 + 采纳 13 槽）；负例近似命中 7 条隔离成 `i3-2/source-gold-nearmiss-library.jsonl` `0fc9dac3…`；r26 `i3_2_source_gold` 组绑定 | 无 | — | — |
| 2 | **query gold** | ⚠️ 已冻结（`6f6c5a25…`，30 题，含 `critical`/`satisfy_rule`/`answer_existence`/`relevant_sources`，人工签认字段齐）但 **`evidence_targets` 0/30**；批准投影已就绪：`evidence-targets-approved.json` `5b89d981…` = 24 道有答案题 **79 必需 + 20 补充**（负例 6 题 0 条） | **把投影材料化成评分器可读字段**（新 query-gold 版本）：每题 `evidence_targets` = `[{target_id, quote, locator, source_id}]`（多出的 `role/constraints/basis` 键被 `gold_from_records` 忽略，可保留作审计）；`locator` 已是 `page:N` / `cell:…` token；**补充证据必须放非必需字段**（如 `supplementary_evidence_targets`），否则会被 `EvidencePass` 当必需；负例题 `answer_existence=no_answer` ⇒ `_evidence_required` 自动 False，无需 targets | A（改金标需 U 签认 + 新修订） | ✅ 是 |
| 3 | **各类阈值** | ✅ 已确认（2026-09-19，U：按默认；记录见 `p2/policy-and-lists-confirmation.json`；仍待随 r27 冻结）——原表述『未冻结/仅代码默认』已更正。取值：`ScoringPolicy` 5 项默认值（`plugins/corpus/scoring.py:261-265`）：`top_k=5`、`min_rate=Fraction(19,20)`（95%）、`require_critical_all_pass=True`、`max_false_positives=0`、`max_fabricated_citations=0`；代码注释明写"**I3-2 冻结其取值**，默认值为架构 §12.3 的开发基线" | U **确认取值** → 写成冻结清单（取值 + 哈希 + 依据）。若取值 ≠ 默认 ⇒ 改实现 ⇒ 新评分器修订（r27） | U 判 / A 出清单 | ✅ 清单可零模型 |
| 4 | **关键题** | ⚠️ 清单本体已冻结（金标 `critical` 字段）但 **28/30 为关键题**（仅 `industry-006`、`macro-004` 非关键），且 `require_critical_all_pass=True` ⇒ 近乎"全过"要求；6 道无答案负例也全被标 critical | U **确认维持 28/30 还是收窄**（收窄需新金标版本）；确认后把清单与"全项否决"口径写进冻结清单 | U 判 | ✅ 可出确认单 |
| 5 | **负例** | ✅ 清单与确认齐：6 道 `no_answer`（`company-009/010`、`industry-009/010`、`macro-009/010`）；候选 `negative_opt_out` 6；裁决件 6 条 `negative_reviews`（`full_text_coverage_confirmed=true`，署名 `xyl`）；近似命中库 7 条已隔离 | 口径落纸：负例不进三指标分母、`max_false_positives=0`、是否维持"负例也全 critical"（与 #4 同判） | U 判 / A 记录 | ✅ 可零模型 |
| 6 | **旧基线映射** | ⚠️ 存在 `baseline-bindings.json`（I0A-4，2026-09-15，7 类：`legacy_retrieval_golden`／`old_doc_kind_review_export`／`financial_controlled_recalc_57`／`formula_7`／`customer_table_12`／`prose_numbers_3`／`macro_legacy_fields_0_of_3`，多数为"报告级绑定 + status/target/binding_detail"）但**仅 `i0c-r1` 绑定**，r26 未重绑；`superseded_note` 指向"候选包 v3 的**用例级**明细（`baseline_bindings_v3`）" | ①核对 v3 用例级明细是否已并入现文件（差异表）；②决定 I3-2 是否重绑；③明确"旧通过能力不退化"在**新 source/evidence 口径**下如何对照（旧锚点 ↔ 新 locator/证据映射，宏观 0/3 与全部旧失败题必须留在基线范围） | A 出对账表 / U 判口径 | ✅ 是（零模型） |
| 7 | **评分器冻结** | ✅ `plugins/corpus/scoring.py` 已在 r19（纯新增）/r21（F1—F5 整改）绑定，本轮未改（校验通过） | 无（只需把哈希写进 #8 清单） | — | — |
| 8 | **试验初始版本** | ⚠️ 清单草稿已建（`p4/experiment-initial-version.json`，`draft_pending_signoff`）；唯一评分输入已派生（`i3-2/query-gold-scoring-v1.jsonl`）——原表述『无产物』已更正 | 建清单并随 I3-2 冻结：评分器 sha + `query-gold`（材料化后）sha + 投影 sha + **policy 取值**（#3）+ 关键题/负例清单哈希（#4/#5）+ `baseline-bindings` sha（#6）+ 运行命令 + 零模型/零 PG 声明 + 冻结修订号 | A 出清单 / U 签认 | ✅ 是 |

## 2. 建议交付顺序（P1 起可零模型推进）

1. **P1 材料化评分器输入**：`query-gold-with-targets`（新版本，含 `evidence_targets` + `supplementary_evidence_targets`），
   自洽校验：每题 target 的 `source_id/locator/quote` 与 `source-gold-frozen.jsonl` **逐字一致**、
   `target_id` 全局唯一、负例题不带 targets；核对 `gold_from_records` 只吃 4 个键的既有行为。
2. **P2 阈值/策略 + 关键题 + 负例 口径确认单**（U 判：#3 取值、#4 28/30、#5 误报上限）。
3. **P3 旧基线映射对账**：`baseline_bindings_v3` 用例级明细 vs 现文件差异表 + 新旧锚点映射。
4. **P4 试验初始版本清单**（引用 P1—P3 产物哈希）。
5. **P5 冻结 r27**：绑定 P1—P4 产物 + 台账，`validate_i0c_freeze.py` exit 0。
   之后才具备 **I3-1（E2E）** 的解冻条件（仍需 PG/模型与预算授权）。

## 3. 边界与遗留（不得据此宣告 I3-2 完成）

- 评分器**从未在真实 E2E 观测上跑过**：本轮清点只解决"输入齐不齐"，不产生任何业务指标。
- 裁决件 20 条**人工同义映射待审计**（机器只核 span 出处，不证语义等价）。
- `macro-004` 机器 `blocked` 未消（q2 靠人工裁定承载；建议 mapping-7 覆盖"短句由相邻段落承载"）。
- 相关但**非** I3-2 冻结项：M5 报告 F3（`validate_i1_freeze.py` 对工作区 13 项失配，P3）仍登记未修，
  建议随 I3 前置一并理顺。
- 强制零模型、未写生产库、未读候选业务结果；I3-5 真实答案语义验收未做。
