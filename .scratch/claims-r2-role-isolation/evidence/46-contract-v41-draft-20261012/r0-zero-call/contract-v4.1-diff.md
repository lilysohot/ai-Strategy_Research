# 契约 v4 → v4.1 差异（机器计算）

- 差异条目：24

| JSON 路径 | 操作 | 旧值 | 新值 |
|---|---|---|---|
| `read_path.absent_required_fields` | add | — | {"list[0]": "attribution", "list[1]": "source_stance", "list[2]": "speaker_ref", "rule": "候选未携带上述字段时，canonical_observed_fields 记 absent，等价性判… |
| `read_path.applies_to` | add | — | role == 'material_items' |
| `read_path.audit_reference` | add | — | Issue 34 chain-report §5.2/§11；Issue 36/37/38/39/40/41 实测。 |
| `read_path.authoritative_side` | add | — | 冻结金标（48/48 逐字可回取、xyl 签认、Issue 29 判定 gold_meaning_sound=true） |
| `read_path.carrier_mapping` | add | — | {"rule": "裁定前允许且仅允许做确定性载体映射：候选 `text` 视为契约 `proposition` 的载体。映射只改字段名，不生成、不改写、不摘要任何语义文本。", "forbidden": "不得从金标反填候选缺失字段；不得把目标字符串直接赋给候选；不得为凑匹配而… |
| `read_path.condition_role` | add | — | 沿用 v3 的 condition_role_read_path（含 compound_condition 子规则）。 |
| `read_path.equivalence_judgement` | add | — | {"owner": "human adjudicator", "rule": "等价性一律由人工判定（沿用 matching.mode）；评分器不得自行按字段相等推导匹配。", "scorer_contract": "评分器只消费裁定完成的映射，并校验其 role/source_… |
| `revision_history` | change | [{"revision": "v2", "status": "draft_pending_human_review", "sha256": "sha256:2eb24be7e74f9e6003ca623487478790cdb60265c5f05377eda377f498f3bd… | [{"revision": "v2", "status": "draft_pending_human_review", "sha256": "sha256:2eb24be7e74f9e6003ca623487478790cdb60265c5f05377eda377f498f3bd… |
| `schema_version` | change | non-table-selected-target-scoring-contract-v4 | non-table-selected-target-scoring-contract-v4.1 |
| `signoff.instrument.note` | add | — | 签认后回填本文件实际哈希。v4 的签署工具（已签 review 件 `753532e8…`）见 supersedes 指向的已签 v4 的 signoff.instrument。 |
| `signoff.instrument.path` | change | .scratch/claims-r2-role-isolation/evidence/45-contract-v4-draft-20261012/r0-zero-call/contract-v4-review.md | .scratch/claims-r2-role-isolation/evidence/46-contract-v41-draft-20261012/r0-zero-call/contract-v4.1-review.md |
| `signoff.instrument.sha256` | change | sha256:753532e8074aa0bf8a9f9cddf2b0e97b9b19519ed95b154407fdfac2e6c0ccd7 | pending_signature |
| `signoff.signed_by` | change | xyl |  |
| `signoff.signed_on` | change | 2026-10-12 |  |
| `signoff.statement` | change | 核准本契约 v4 作为 items-only 质量门的已签认度量基准；签署工具为 contract-v4-review.md 的签认栏（认可并签认 v4）。 | 【待签认】v4.1 = 已签 v4 + 并行草案独有叶子；签认前不生效。 |
| `status` | change | frozen_signed | draft_pending_human_signature |
| `supersedes.note` | change | v4 为 draft；未签认前不生效，v3 字节不变、哈希留存可追溯。 | v4.1 以已签 v4 为基，只增不删地把并行草案的独有叶子并入；v4.1 未签认前不生效，v4 字节不变、哈希留存可追溯。 |
| `supersedes.schema_version` | change | non-table-selected-target-scoring-contract-v3 | non-table-selected-target-scoring-contract-v4 |
| `supersedes.sha256` | change | sha256:d9bc51f286a977ec92315b6e97c7ac303a971691334f4752ccd7e61d5b75a7ce | sha256:6806f1399e3bbf5ace41264598f6228998f706dd082f20d580d5303a48ab712d |
| `threshold_source.already_verified` | add | — | {"gate28_contract_binding": "PASS（issue 41 AC-2）", "gate28_high_risk_assertions": "PASS：16 条 == 契约 items 断言子集（issue 41 AC-10）"} |
| `threshold_source.conflict_resolution` | add | — | 实现值与契约不一致时以已签认来源为准，实现方须改为读取或与契约同步，变更须具名签认。 |
| `threshold_source.decision_history` | add | — | {"fork": "门 28（signed）为 target_recall_overall_min=0.85 / candidate_precision_min=0.80；评分器实现为 0.95 / 0.90（structured_scoring.py:334-339）", "o… |
| `threshold_source.required_alignment` | add | — | OPEN-1 = A（2026-10-12 已签认）：以门 28 为单一口径，评分器改为读契约 |
| `threshold_source.rule` | add | — | 召回/精确率/未裁定上限/断言清单以本契约与签认门为唯一来源；任何实现方不得另存一份。 |

> 由脚本递归 diff 计算，非手写。
