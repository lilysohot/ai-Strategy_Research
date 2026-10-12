# 契约 v3 → v4 草案 差异（机器计算）

- 差异条目：18
- v3：`non-table-selected-target-scoring-contract-v3` / `frozen_signed`
- v4 草案：`non-table-selected-target-scoring-contract-v4` / `draft_pending_human_signature`

| JSON 路径 | 操作 | 旧值 | 新值 |
|---|---|---|---|
| `adjudication_clause` | add | — | {"mode": "human_adjudicated_semantic_equivalence_then_one_to_one_mapping", "responsible_party": "xyl（待签认确认）", "full_coverage_required": {"unresolved_max": 0, "c… |
| `bookkeeping_requirements` | add | — | {"contract_binding_sync": "契约修订必须同轮更新 frozen-gold 侧记录的契约绑定哈希；现记录 v2 `2eb24be7…` 与实际 v3 `d9bc51f2…` 不符（match=False）", "validation_report_consistency": "validatio… |
| `caliber_rules` | add | — | {"principle": "以金标口径为准，在读取/匹配视图上归一化；**不得覆盖候选或金标的原始字段**。", "direction_note": "『维持生产端口径并改金标』与 issue-34 §8（冻结金标字节不变）冲突 ⇒ 事实上只剩本方向；本方向仍标注为待具名签认，草案不自行生效。", "rules": … |
| `matching.projection` | change | 现有 strict scorer 只接受裁定完成的语义映射；映射须保存原始候选字段、裁定人、理由和依据。不得将目标字符串直接赋给候选并宣称自动语义评分。 | 现有 strict scorer 只接受裁定完成的语义映射；映射须保存原始候选字段、裁定人、理由和依据。不得将目标字符串直接赋给候选并宣称自动语义评分。 读路径/口径归一化只作用于匹配视图，不得覆盖候选或金标的原始字段；原始候选字段必须完整留存。 |
| `read_path` | add | — | {"mechanism": "按角色注册读路径：每个契约必需字段声明 carrier 与 normalization；机制与记录 ID 无关。", "id_independence": "任何读路径规则不得按 record_id 硬编码（禁止 NT-Ixx 逐条规则）。", "review_assertions_sta… |
| `relation_matching` | add | — | {"defect": "契约 role_required_fields.material_relations 含 from_gold_record_id / to_gold_record_id，即要求候选携带金标主键 ⇒ 严格 identity 匹配下该角色恒为 0（evidence/39 EC-B4）", "open… |
| `revision_history` | change | [{"revision": "v2", "status": "draft_pending_human_review", "sha256": "sha256:2eb24be7e74f9e6003ca623487478790cdb60265c5f05377eda377f498f3bdbe"}, {"revision": "… | [{"revision": "v2", "status": "draft_pending_human_review", "sha256": "sha256:2eb24be7e74f9e6003ca623487478790cdb60265c5f05377eda377f498f3bdbe"}, {"revision": "… |
| `schema_version` | change | non-table-selected-target-scoring-contract-v3 | non-table-selected-target-scoring-contract-v4 |
| `signoff.scope_note` | change | 本次签认只定评分契约读路径与度量口径；不代表 items-only 真实复验通过、不代表发布或语境完整。 | 签认只定读路径、口径与度量口径；不代表 items-only 真实复验通过、不代表发布或语境完整。 |
| `signoff.signed_by` | change | xyl |  |
| `signoff.signed_on` | change | 2026-10-11 |  |
| `signoff.statement` | change | 核准本契约 v3 作为 items-only 质量门的已签认度量基准。 | 【待签认】本 v4 草案覆盖 issue-34 §7-1/§7-3/§7-6/§7-7/§7-11/§7-12；签认前不生效。 |
| `status` | change | frozen_signed | draft_pending_human_signature |
| `supersedes.note` | change | v2 未签认即被钉为 Issue 28 门度量基准；本 v3 为其签认后继版本，v2 内容与哈希留存可追溯，不就地覆盖历史。 | v4 为 draft；未签认前不生效，v3 字节不变、哈希留存可追溯。 |
| `supersedes.schema_version` | change | non-table-selected-target-scoring-contract-v2 | non-table-selected-target-scoring-contract-v3 |
| `supersedes.sha256` | change | sha256:2eb24be7e74f9e6003ca623487478790cdb60265c5f05377eda377f498f3bdbe | sha256:d9bc51f286a977ec92315b6e97c7ac303a971691334f4752ccd7e61d5b75a7ce |
| `supersedes.status_at_supersede` | change | draft_pending_human_review | frozen_signed |
| `threshold_source` | add | — | {"authority_source": {"where": "门 28 preregistered-gate.json quality_requirements（signed）", "sha256": "sha256:987772e957ce14526798a7258d1e5e8cb9afb4d58fb3f005e3… |

> 本差异由脚本递归 diff 计算，非手写；审阅对象与 `proposed-scoring-contract-v4.json` 一致。
