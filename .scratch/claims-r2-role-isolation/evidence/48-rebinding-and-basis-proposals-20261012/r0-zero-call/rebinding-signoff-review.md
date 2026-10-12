# P12 / P13 记账修订 · 签认件（待签）

- 本件：`evidence/48-rebinding-and-basis-proposals-20261012/r0-zero-call/rebinding-signoff-review.md`
- 状态：**待 U 签认**（签认前不生效）
- 零模型调用；签认只授权**新增两个记录**，不授权任何字节改动
- 与 `README.md` 同目录的两份机器提案（`gold-freeze-rebinding-proposal.json` `3a99d6ad…`、`gate28-metric-basis-proposal.json` `2f0de079…`）的关系：**本件为准**。起草本件时又查出 P12 的**两处漏项**（§二 第 2、3 条，标 NEW），是那两份提案未覆盖的。

---

## 一、这份签下去等于什么（一句话）

允许创建**两个新的记账记录**，把"契约绑定"从不该出现的旧版本（v2 / v3）改为**当前已签的 v4.1**（`sha256:c76ac13ec0a109074775a2b5e1c8cc170da955847638d6ea7f5778988238781b`）。

**不改任何既有字节、不改任何阈值数值、不改金标。**

---

## 二、P12：金标冻结链契约绑定（实测 3 处，其中 2 处为新发现）

| # | 位置 | 现记 | 应为 |
|---|---|---|---|
| 1 | `freeze-manifest.json.inputs[…/10-quality-gold-expansion-20261008-r2/scoring-contract.json]` | v2 `2eb24be7…` | v4.1 `c76ac13e…` |
| 2 | **NEW** `freeze-state.json.scoring_contract` | **一个路径**（非哈希）；该路径现内容 = v3 `d9bc51f2…` | 新记录**钉住其解析后的哈希**，并建议后续改用哈希 |
| 3 | **NEW** `freeze-state.json.contract_snapshot` | **内嵌的 v2 契约草案全文**（`status: draft_pending_human_review`） | **保留字节**（历史真值）；由新记录声明"它是历史，不是当前绑定" |

- 其余 7 条输入实测 `match`（含两个源文件）。
- 建议落位（新文件）：`evidence/10-quality-gold-freeze-20261008-r2/rebinding-v4.1-20261012.json`
- 签认后**不动**：`freeze-manifest.json`（`da85e293…`）、`freeze-state.json`（`08703b8d…`）、`frozen-gold.json`、`freeze-state.json` 内嵌快照——字节全部保留。
- 并行会话已有一份 v2→v3 的同类记录，**不能沿用**（版本不同）。

**为什么第 3 条建议不改**：`contract_snapshot` 是"冻结当时实际生效的契约"的记录。改它才是伪造历史。新记录只负责声明"它不是当前绑定"。

**为什么第 2 条只能部分修**：`scoring_contract` 记的是**路径**而非哈希 ⇒ 属**弱绑定**（会静默跟随路径内容）。新记录钉住其解析哈希；把"路径改成哈希"本身留作后续（那会改字节，需单独裁定）。

---

## 三、P13：门 28 基准与绑定（实测 2 处）

| # | 位置 | 现记 | 应为 |
|---|---|---|---|
| 1 | `quality_requirements.metric_basis` | `non-table-selected-target-scoring-contract-v3` | `…-v4.1` |
| 2 | `gold.scoring_contract_sha256` | `sha256:d9bc51f286a977ec92315b6e97c7ac303a971691334f4752ccd7e61d5b75a7ce`（v3） | `sha256:c76ac13e…`（v4.1） |

- **为什么必须签**：已签契约 v4.1 的 `threshold_source.effective` 取自门 28 `quality_requirements`；而门 28 的基准与绑定又指向 v3 ⇒ **循环引用**，所谓"单一口径"并未真正闭合。
- 阈值**数值逐字不变**：`target_recall_overall_min 0.85` / `target_recall_per_source_min 0.80` / `candidate_precision_min 0.80` / `accepted_records_total_min 40` / `accepted_records_per_source_min 20` / `unresolved_candidates_max 0`。
- 门 28 内记的 `gold.freeze_state_sha256` / `freeze_manifest_sha256` 与两个实际文件**一致**（实测），此项无漂移。
- 建议落位（新文件）：`evidence/28-items-only-quality-gate-20261010/r0-zero-call/preregistered-gate-v2.json`
- 先例：门 28 `revision_history[1].changes` 已有过**完全相同手续**的 v2→v3 推进（改 `scoring_contract_sha256` + 改 `metric_basis`）。本次不是新发明。
- 签认后**不动**：`preregistered-gate.json`（`987772e9…`）字节。

---

## 四、签认之后会发生什么

1. 我创建上述两个新记录（零调用、只新增文件、既有字节不动）。
2. **P03（评分器读契约 / 阈值单源落地）** 随之解锁——它需要"契约 v4.1 + 门 28 推进记录"两者齐备。
3. 不需你签、我一并做的两项记账：**P14** `validation-report.json` 的 `human_accepted_counts` 由 `{}` 对齐到 48/48（该件现 `status: valid_review_draft`，非签认件）；**P16** 冻结链校验器（任何契约/金标/manifest 修订须校验绑定一致）。
4. 明确**不做**：不改金标字节、不改任何阈值数值、不就地修改任何文件。

---

## 五、签认栏

- 复核人：　　xyl　　　　日期：2026-10-12 10:00
- 结论：x 认可并签认（P12 三处 + P13 两处，均按 §二/§三 处置）　　☐ 退回修改
- 备注：

> 签认后：P12 落 `10-quality-gold-freeze-20261008-r2/rebinding-v4.1-20261012.json`；P13 落 `28-…/preregistered-gate-v2.json`；随后开工 P03。
