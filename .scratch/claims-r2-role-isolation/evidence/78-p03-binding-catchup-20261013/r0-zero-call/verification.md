# P03 绑定追平（评分器快照 → 已签门 v3 / 契约 v4.3）核验记录

- 2026-10-13　零模型调用、只读　通过 8 / 失败 0
- 依据契约：`.scratch/claims-r2-role-isolation/evidence/75-r2-signed-20261013/r0-zero-call/scoring-contract-v4.3.json` `sha256:d7b4f8a81ef42e3cd5d619eae92bc34df7b7aa683d34aeba4f1a22719ae69a2f`
  （threshold_source.effective.implementation_required + required_alignment(OPEN-1=A)）
- 依据门：`.scratch/claims-r2-role-isolation/evidence/75-r2-signed-20261013/r0-zero-call/gate-v3.json` `sha256:340b312d9c0cec278e828d8303a03e9daf953feef4c0eef688f3d257971a9732`
  （high_risk_item_assertions_required(11) + high_risk_item_assertions_excluded(5)）

## 一、逐项核验

| 检查 | 谓词 | 结果 | 实测 |
|---|---|---|---|
| `snapshot_equals_signed_contract` | 评分器快照 == 契约 v4.3 threshold_source.effective（六项） | PASS | `{"mismatched": {}, "schema_version": "non-table-selected-target-scoring-contract-v4.3"}` |
| `snapshot_schema_version_is_v4.3` | 快照 schema_version == 契约 schema_version | PASS | `{"snapshot": "non-table-selected-target-scoring-contract-v4.3", "contract": "non-table-selected-target-scoring-contract-v4.3"}` |
| `sentinel_follows_signed_gate` | 哨兵清单 == 门 v3 清单（11 项）且与被移出 5 项互斥 | PASS | `{"required": ["NT-I13", "NT-I15", "NT-I17", "NT-I29", "NT-I35", "NT-I37", "NT-I38", "NT-I39", "NT-I42", "NT-I43", "NT-I48"], "excluded": ["NT-I09", "N` |
| `dataclass_field_sets_unchanged` | ContractGateRequirements / QualityPolicy 字段集逐字未变 | PASS | `{"contract": ["schema_version", "role_scope", "target_recall_overall_min", "target_recall_per_source_min", "candidate_precision_min", "accepted_record` |
| `policy_cannot_move_the_verdict` | 改 pilot 策略阈值 ⇒ rate_gate_passed 与 rate_blockers 不变（唯一权威布尔） | PASS | `{"lenient_passed": false, "strict_passed": false, "pilot_blockers_differ": true}` |
| `two_twenty_axes_are_distinct` | 角色轴 min_gold_per_role(20) 与源轴 accepted_records_per_source_min(20) 未被混用 | PASS | `{"min_gold_per_role": 20, "accepted_records_per_source_min": 20}` |
| `published_score_record_unchanged` | 77 出分记录在本改动后逐字节不变 | PASS | `{"recorded": "sha256:7a8a8c2b5849aa802abd5616248d7a3e090d63ae9ba44fd1ca6ce0877a147d09", "now": "sha256:7a8a8c2b5849aa802abd5616248d7a3e090d63ae9ba44fd` |
| `freeze_chain_validator_clean` | check_freeze_chain.py 退出 0，drift=0，needs_ruling=0 | PASS | `{"exit": 0, "ok": 17, "covered": 8, "drift": 0, "needs_ruling": 0}` |

## 二、改动文件（哈希）

- `plugins/corpus/structured_scoring.py` `sha256:aa40d42dbd58663715df217bca06c48ef5843d913a9a6d2170f0ee681b0ab4e0`
- `tools/check_freeze_chain.py` `sha256:089ef31ed044635b6eb3910372430ce7683aa33112517522ad64adef86128a29`
- `tests/test_corpus_contract_gate.py` `sha256:6f1851a54dbfac5447d504740a762d768741a220a353fb3573ef52cf03e3189a`
- `tests/test_corpus_structured_scoring_adjudicated.py` `sha256:2d96e2d5ffc68cd9eabf18452eb3ac9e763f6a4301dc046299a7b6630f4875e2`

## 三、明确未改动的部分

- **PILOT_CANDIDATE_POLICY**：数值未动：P03 已把 rate_gate_passed 单源到契约快照，pilot 策略只剩诊断语义；改它无功能收益且会动到历史 pilot 基线
- **claims_and_relations_axes**：契约 role_scope=material_items，未覆盖；保持原值并记为未推进
- **min_gold_per_role**：角色轴，与源轴 accepted_records_per_source_min 分属两轴，未混用

## 四、复现

```bash
uv run python .scratch/claims-r2-role-isolation/evidence/78-p03-binding-catchup-20261013/r0-zero-call/verify_p03_binding.py
```
