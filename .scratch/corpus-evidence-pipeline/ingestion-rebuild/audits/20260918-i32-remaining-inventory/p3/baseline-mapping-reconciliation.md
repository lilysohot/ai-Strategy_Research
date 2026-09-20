# P3 旧基线映射对账（未落正式）

- `baseline-bindings.json` `a397aea92e77…`（I0A-4 2026-09-15，git_head `8d4772ca`）｜绑定：i0c-r1、i0c-r28
- 候选包 v3 `016c87e506aa…`（用例级 5 类）｜绑定：i0c-r28

| 类别 | v3 用例级明细 | 可绑定度 | 已核哈希 | 漂移 |
|---|---|---|---|---|
| legacy_retrieval_golden | 有 | 可非重跑绑定 | golden.py | 0 |
| old_doc_kind_review_export | **缺** | **纯描述（不可绑定）** | — | 0 |
| financial_controlled_recalc_57 | 有 | 可非重跑绑定 | pilot_manifest.json／verify_claims_entry.py | 0 |
| formula_7 | 有（嵌套于 financial_controlled_recalc_57） | **纯描述（不可绑定）** | — | 0 |
| customer_table_12 | 有 | **纯描述（不可绑定）** | — | 0 |
| prose_numbers_3 | 有 | **纯描述（不可绑定）** | — | 0 |
| macro_legacy_fields_0_of_3 | 有 | **纯描述（不可绑定）** | — | 0 |

## 结论与建议

- 指针 vs 内联：`baseline-bindings.json` 的 5 个类别只写『见 i0a4-candidates-v3… baseline_bindings_v3.<x>』，用例级明细（预期资产+hash、可跑入口+hash、params/副作用/DB、机器记录）都在候选包 v3 里；两者哈希口径不同（index 里 `sha256: null` + `sha256_report`）
- 缺项：候选包 v3 只有 5 类，`old_doc_kind_review_export` 无用例级明细（该类别注记『权威版本待 U 确认（.audit 共 88 个 2026-09-12 工件）』）
- 重跑能力：v3 的 `runnable_entry` 明确带『向原库写 corpus_evidence_runs 新行（零模型但非零写）』与 `db: 原库 5432`，`prose_numbers_3` 标注『复跑须另立预算授权』——**在 I3 守卫（零写、无 PG、无网络）下不能重跑**，因此 I3-2 的『旧通过能力不退化』只能做非重跑绑定（期望资产 + 入口字节 + 机器记录），真实重验按既有分工排 I3-5 并需单独授权
- 绑定状态：`baseline-bindings.json` 仅 ['i0c-r1', 'i0c-r28'] 绑定；**候选包 v3 未被任何修订绑定**（['i0c-r28']）⇒ `baseline-bindings.json` 的 `binding_detail` 指向一个未入链的文件，I3-2 冻结时必须一起处理
- 可绑定度：7 类中只有 2 类可做『非重跑绑定』（`legacy_retrieval_golden` 的 `plugins/corpus/golden.py`、`financial_controlled_recalc_57` 的 `pilot_manifest.json` + `verify_claims_entry.py`，声明哈希与现况一致、0 漂移）；3 类（`customer_table_12`、`prose_numbers_3`、`macro_legacy_fields_0_of_3`）的用例级明细是**纯描述**（run_id／source_anchor／expected／status，无 path、无 sha256），因此目前无法作为非重跑绑定；`financial_controlled_recalc_57` 的 `machine_record` 有路径但**未声明哈希**

**I3-2 动作**：
- 把 v3 的用例级明细**内联或强引用（双哈希：index sha + v3 sha）**后随 r27 重绑，避免『指针指向未被绑定的文件』（现 v3 零绑定）
- 给 3 个纯描述类目补 `path` + `sha256`（`customer_table_12` 用冻结 run `0a1dbf39…`、`prose_numbers_3` 用冻结目标/报告、`macro_legacy_fields_0_of_3` 用字段清单），并给 `financial_controlled_recalc_57.machine_record` 补声明哈希——否则『不退化』只能靠散文声明
- `old_doc_kind_review_export` 在 v3 无条目：需 U 圈定权威版本（.audit 88 个工件）或明确降级
- 在冻结清单里写明：旧基线在 I3 守卫下**不重跑**，只作非重跑绑定；重验排 I3-5 + 单独授权

**新旧口径对照方法**：
- 对每个旧基线用例：只比对『预期资产 + 机器记录』（历史通过数字）与新口径下的**同一用例**重评结果；旧口径（逐题通过含 require_all）与新召回标准**分别报告，不互相替代**
- 新链路跑不通时按 fail-closed 计入 `blockers`，不得以旧数字顶替
