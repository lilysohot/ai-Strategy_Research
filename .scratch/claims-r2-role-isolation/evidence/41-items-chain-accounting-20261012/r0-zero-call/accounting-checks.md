# items 链路记账与口径一致性核对（Issue 36）

- 日期：2026-10-12
- 零模型调用、零生产库访问、未修改任何既有产物
- 汇总：PASS 4 / FAIL 7 / INFO 0；其中需具名签认 2 项

## 输入哈希

| 产物 | sha256 |
| --- | --- |
| `frozen_gold` | `sha256:603de5e6c532463db8ae2788b830c2c1a74400b4ba736292bd5503468dfa7de2` |
| `scoring_contract` | `sha256:d9bc51f286a977ec92315b6e97c7ac303a971691334f4752ccd7e61d5b75a7ce` |
| `freeze_manifest` | `sha256:da85e29397f1b4b45186567079a9f2341bf36e42b7bf2ba8cb7102b23632b23e` |
| `freeze_state` | `sha256:08703b8dad9fc6c130872899741534c940787c29a15423db19d398999b237d85` |
| `validation_report` | `sha256:139cfc222eb4688dccdce5c0116b00c84b87401e01e22427658c3dcfa6d5bc52` |
| `gate28` | `sha256:987772e957ce14526798a7258d1e5e8cb9afb4d58fb3f005e31891a5f46b2684` |
| `gate32` | `sha256:6fb47e7945ce133dbdea7b73c6bb3b5e7266856cf6d956dbb9d191303783fba8` |
| `gate32_freeze_manifest` | `sha256:1a0e008ad2af5835910cfe7d62918936f557dc377dd353e6a6dfea0f9df142f5` |
| `gate32_decision` | `sha256:669464116e58217962ba092ad98f07a81dfc082db56be1a716d62070c8c33a65` |
| `skeleton` | `sha256:cc2946ef6a487fba059ca995f2c34f469d4c96720b6b6186225c97bd1e41b537` |
| `draft` | `sha256:972acca8d0375d3e5686f08f20cae1b55967abdd3203d4d0fac6c1708f54e89e` |
| `preview` | `sha256:2337a1abde54a4b7acf788371c35c372302e700b151d9d8d6484c6227e8f6b2e` |
| `draft_script` | `sha256:7d839413dd0770ef0f277b762432b3618c0cb92dffd1e8f0117523e7d94998a6` |
| `scorer` | `sha256:172ce465492cf26cb7249599d9f53ac40d266c1883a49cea51b0b178894874f1` |

## 检查明细

### AC-1 · 金标冻结链的契约绑定是否等于实际签认契约 — FAIL

```json
{
  "manifest_records": "2eb24be7e74f9e6003ca623487478790cdb60265c5f05377eda377f498f3bdbe",
  "actual_contract": "d9bc51f286a977ec92315b6e97c7ac303a971691334f4752ccd7e61d5b75a7ce",
  "manifest_embedded_status": "draft_pending_human_review",
  "manifest_embedded_schema": "non-table-selected-target-scoring-contract-v2",
  "signed_contract_schema": "non-table-selected-target-scoring-contract-v3",
  "signed_contract_status": "frozen_signed"
}
```

### AC-2 · 门 28 的契约绑定是否等于实际签认契约 — PASS

```json
{
  "gate_records": "d9bc51f286a977ec92315b6e97c7ac303a971691334f4752ccd7e61d5b75a7ce",
  "actual_contract": "d9bc51f286a977ec92315b6e97c7ac303a971691334f4752ccd7e61d5b75a7ce",
  "quality_requirements_status": "signed",
  "metric_basis": "non-table-selected-target-scoring-contract-v3"
}
```

### AC-3 · 评分器阈值是否与门 28 权威阈值同源 — FAIL（需签认）

```json
{
  "scorer_hard_coded": {
    "material_items_recall": "19/20",
    "material_items_recall_decimal": 0.95,
    "material_items_precision": "9/10",
    "material_items_precision_decimal": 0.9,
    "risk_condition_recall": "19/20",
    "risk_condition_recall_decimal": 0.95
  },
  "gate28_authoritative": {
    "target_recall_overall_min": 0.85,
    "target_recall_per_source_min": 0.8,
    "candidate_precision_min": 0.8
  },
  "scorer_reads_contract_or_gate": false
}
```

### AC-4 · 评分器匹配模式是否符合契约 matching.mode — FAIL

```json
{
  "scorer": {
    "identity_expression": "return (self.role, self.source_id, self.origin, self.semantic_fields)",
    "match_predicate": "item.identity == candidate.identity"
  },
  "contract_matching_mode": "human_adjudicated_semantic_equivalence_then_one_to_one_mapping",
  "contract_items_rule": "同义改写可接受；须保持一个原子命题、语义类型、话语角色、归属、否定、条件、行为意向。proposition 不用逐字字符串相等判定。",
  "contract_projection_rule": "现有 strict scorer 只接受裁定完成的语义映射；映射须保存原始候选字段、裁定人、理由和依据。不得将目标字符串直接赋给候选并宣称自动语义评分。"
}
```

### AC-5 · Stage-2 草案是否执行了契约禁止的『从金标反填候选缺字段』 — FAIL

```json
{
  "draft_script_fills_canonical_observed_fields_from_gold": true,
  "draft_script_excerpt": "\"canonical_observed_fields\": {\n                    key: value for key, value in canonical_fields(gold_row[\"semantic_fields\"])\n                }",
  "contract_normalization_rule": "数值仅做十进制单位缩放和闭区间规范化；日期和期间保留基准语境；约数不能升级成精确承诺。记录所用规则，不从金标反填候选缺字段。",
  "contract_forbids": "不从金标反填候选缺字段",
  "skeleton_entries_empty": 222,
  "skeleton_entries_total": 222,
  "draft_auto_accepted": 19
}
```

### AC-6 · 草案预览的召回类数字是否可用于门槛判断 — FAIL

```json
{
  "draft_recall_upper_bound": {
    "matched_gold": 19,
    "gold_total": 48,
    "fraction": "19/48",
    "decimal": 0.3958,
    "note": "upper bound only: it assumes every high/medium draft is confirmed and no pending candidate matches an unmatched gold record"
  },
  "critical_coverage": {
    "critical_gold_total": 12,
    "critical_matched": 1,
    "critical_missing": [
      "NT-I13",
      "NT-I14",
      "NT-I15",
      "NT-I16",
      "NT-I17",
      "NT-I19",
      "NT-I34",
      "NT-I40",
      "NT-I42",
      "NT-I43",
      "NT-I44"
    ]
  },
  "risk_condition_coverage": {
    "total": 21,
    "matched": 5,
    "missing": [
      "NT-I04",
      "NT-I09",
      "NT-I10",
      "NT-I13",
      "NT-I15",
      "NT-I17",
      "NT-I19",
      "NT-I23",
      "NT-I29",
      "NT-I31",
      "NT-I34",
      "NT-I35",
      "NT-I39",
      "NT-I40",
      "NT-I42",
      "NT-I43"
    ]
  },
  "contaminated_by": "AC-5",
  "reason": "these counts are computed from draft entries whose canonical_observed_fields were copied from the gold record, so they measure the copy, not the extraction",
  "still_usable": {
    "unresolved_candidates": "203 candidate(s) still unresolved; contract v3 requires N/A instead of reporting a precision that excludes them",
    "physically_lost_slots": {
      "infrastructure": 7,
      "model_behavior": 0,
      "our_contract_signal_overlabelling": 2,
      "unclassified": 0
    }
  }
}
```

### AC-7 · 冻结后的验收记录是否齐备 — FAIL

```json
{
  "validation_status": "valid_review_draft",
  "validation_human_accepted_counts": {},
  "validation_formal_gold_frozen": false,
  "freeze_state_formal_gold_frozen": true,
  "freeze_state_status": "frozen_ready_for_candidate_evaluation",
  "freeze_state_reviewer": "xyl",
  "unresolved_semantic_ambiguities": [
    {
      "record_id": "NT-I17",
      "fields": [
        "condition_inner_boolean"
      ]
    }
  ]
}
```

### AC-8 · 门 32 判据能否独立确认『协议修复』这一被测对象 — FAIL（需签认）

```json
{
  "verdict": "structural_fail",
  "root_cause_status": "eliminated: zero 'unsupported JSONL record' batches under the v6 prompt, against 11 batches under the v5 control arm",
  "protocol_status_valid": {
    "met": false,
    "observed": {
      "industrial-fulian-md": "not_checked",
      "optical-module-docx": "not_checked"
    },
    "reason": "the items task did not succeed, so protocol adjudication was not reached"
  },
  "criteria_unmet": [
    "protocol_status_valid",
    "failed_partial_invalid_duplicate_batches_max_0",
    "completed_min",
    "execution_status_succeeded"
  ],
  "protocol_violation_batches": {
    "control": {
      "industrial-fulian-md": 3,
      "optical-module-docx": 8
    },
    "treatment": {
      "industrial-fulian-md": 0,
      "optical-module-docx": 0
    }
  }
}
```

### AC-9 · 冻结金标字节未变 — PASS

```json
{
  "manifest_records": "603de5e6c532463db8ae2788b830c2c1a74400b4ba736292bd5503468dfa7de2",
  "actual": "603de5e6c532463db8ae2788b830c2c1a74400b4ba736292bd5503468dfa7de2",
  "records": 92,
  "material_items": 48
}
```

### AC-10 · 门 28 高风险断言清单是否等于契约 items 角色断言子集 — PASS

```json
{
  "gate28_count": 16,
  "contract_items_subset_count": 16,
  "gate28_only": [],
  "contract_only": [],
  "contract_total_assertions": 24,
  "contract_non_items": [
    "NT-C11",
    "NT-C12",
    "NT-C13",
    "NT-R09",
    "NT-R10",
    "NT-R12",
    "NT-R19",
    "NT-R20"
  ]
}
```

### AC-11 · 门 32 判定记录引用的冻结清单哈希是否可复核 — PASS

```json
{
  "decision_freeze_manifest_sha256": "sha256:1a0e008ad2af5835910cfe7d62918936f557dc377dd353e6a6dfea0f9df142f5",
  "actual_freeze_manifest": "sha256:1a0e008ad2af5835910cfe7d62918936f557dc377dd353e6a6dfea0f9df142f5",
  "decision_gate_sha256_declared_only": "sha256:6fb47e7945ce133dbdea7b73c6bb3b5e7266856cf6d956dbb9d191303783fba8",
  "preregistered_gate_has_own_hash_field": false
}
```

