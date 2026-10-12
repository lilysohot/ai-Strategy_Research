# P03 设计说明 · 阈值单源落地（评分器读契约）

- 状态：**待 U 审阅**（未改任何代码）
- 依据：已签契约 **v4.2**（`58-…/scoring-contract-v4.2.json`）`threshold_source.effective` + `implementation_required`
  ——「评分器现以 PILOT_CANDIDATE_POLICY 硬编码 0.95/0.90，与本节冲突；须改为读取本契约」
- 前置已齐：契约 v4.2 已签、门 28 推进记录（P13）、冻结链校验器全绿（exit 0）
- 零模型调用

## 一、关键发现：轴不匹配，"换数字"是错的

| 评分器现策略（`PILOT_CANDIDATE_POLICY`） | 门 28 权威轴（契约 `effective` 六值） | 能否直接映射 |
|---|---|---|
| 按角色 `precision_min`：claims 49/50、items 19/20、relations 19/20 | `candidate_precision_min = 0.80`（**不分角色**） | ✅ 可映射 |
| 按角色 `recall_min`：claims 19/20、items 9/10、relations 17/20 | `target_recall_overall_min = 0.85`（**总体**）＋ `target_recall_per_source_min = 0.80`（**分源**） | ❌ **没有"按角色召回"这一轴** |
| `risk_condition_recall_min = 0.95` | **无对应值**（契约 `metrics.risk_condition`：按角色分别报告，"不称独立风险场景"；门 28 用的是 `high_risk_item_assertions_required`＝16 条记录 ID 清单，不是比率） | ❌ 无对应 |
| `report_support_min = 0.95` | **无对应值**（契约 `metrics.quality_gate`：query/delivery/context_use 是放行前提，属 readiness） | ❌ 无对应 |
| `min_gold_per_role = 20` | `minimum_accepted_records_per_role = 20`（角色轴）✓ 另有 `accepted_records_per_source_min = 20`（**源轴**） | ✅ 可映射，但**两轴不得混用**（契约 `axes_warning` 明文） |

**结论**：OPEN-1=A 的"0.85/0.80/20"是**门轴**，不是按角色轴。若把按角色阈值简单换成 0.80/0.85，就是把"总体/分源"混成"按角色"——正是契约 `axes_warning` 禁止的事。

## 二、推荐设计（方案 A）：门轴直读为权威，按角色降级为诊断

1. **新增 `ContractGateRequirements`**（评分器内，值取自已签 v4.2）：六值 ＋ `high_risk_item_assertions_required`（16 条 ID）＋ `role_required_fields` ＋ `material_items_target_total`。
2. **新增契约轴判定**并作为 `rate_gate_passed` 的**权威依据**：总体召回 ≥0.85、每源召回 ≥0.80、精度 ≥0.80、接受总数 ≥40、每源接受 ≥20、未裁定 =0、16 条 high-risk 断言记录全部命中。
3. **按角色 `QualityPolicy` 降级为诊断切片**：保留输出（origin/role 归因仍然需要），但不再是放行依据；其数值暂维持现状并标注 `pilot/diagnostic, not authority`。
4. **`risk_condition_recall_min` / `report_support_min`：保持不变**，但归入 **readiness**（放行前提），并标注"契约六值无对应项"。理由：契约 `metrics.quality_gate` 明说 query/delivery/context_use 是放行前提；risk_condition 契约只要求"按角色报告"。
5. **单一来源机制**：评分器内嵌的是**已签快照**；另加一条**回归测试**直接读取 `58-…/scoring-contract-v4.2.json`，断言与内嵌值逐字相等 ⇒ 契约一改，测试即红（这是"读契约"的可执行形式，也避免产品代码 import `.scratch`）。同时给 `tools/check_freeze_chain.py` 增加同一校验（门→评分器）。

## 三、兼容影响（必须先说清）

| 影响 | 说明 |
|---|---|
| **legacy 四臂的 `gate.rate_blockers` 会变** | P02 的"四臂逐字段不变"承诺**只覆盖匹配账本（tp/fp/fn）**；P03 改的是门判定，属已签决策的落实。tp/fp/fn/duplicate 仍须逐字段不变，我会单独验证。 |
| 既有 23 项 legacy 测试 | 断言里涉及 `rate_gate_passed`/`rate_blockers` 的**会改**（这是 OPEN-1=A 的必然结果，不是"改测试适配实现"——判据来自已签契约）。 |
| `CandidateScore`/`QualityGateScore` 结构 | 新增字段（契约轴判定），不删既有字段 ⇒ 不破坏既有数据结构。 |

## 四、退出判据（预注册）

1. 契约轴判定实现且 `rate_gate_passed` 由其驱动；六值与 16 条断言来自 `ContractGateRequirements`。
2. 回归测试：内嵌值 == `58-…/scoring-contract-v4.2.json` 逐字相等。
3. `tools/check_freeze_chain.py` 增"评分器内嵌阈值 == 契约值"检查并保持 exit 0。
4. legacy 四臂 tp/fp/fn/duplicate 逐字段不变（gate blockers 除外，已声明）。
5. 既有测试全绿（允许修改门相关断言，逐条记录）。
6. 零模型调用；不改金标、不改门 28 字节、不改契约字节。

## 五、需要你裁定的三点

1. **按角色召回怎么办**：☐ 按角色切片**不设召回门槛**（只报数，门轴用总体/分源——我推荐，最忠实于契约）　☐ 按角色沿用 0.80（混轴，需在契约里补一条说明）
2. **`risk_condition_recall_min`（0.95）与 `report_support_min`（0.95）**：☐ 移入 readiness、保留数值（我推荐）　☐ 一并废除（risk 改为"16 条断言全命中"）
3. **`rate_gate_passed` 语义切换**：☐ 直接切换为契约轴（我推荐；旧门轴降级为诊断字段保留）　☐ 先并存两个判定、下一轮再切换

## 六、明确不在 P03 范围

- P04/P05（口径归一化与其回归）——本设计不实现 `caliber_rules` 的归一化逻辑，只落阈值。
- 门 33 出分——真实裁定仍为 0。
- 修改契约/门 28/金标字节。
