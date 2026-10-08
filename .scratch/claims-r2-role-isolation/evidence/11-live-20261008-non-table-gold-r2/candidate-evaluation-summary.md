# Signed r2 non-table candidate evaluation

Date: 2026-10-08  
Gold: `10-quality-gold-freeze-20261008-r2/frozen-gold.json`  
Reviewer/adjudicator: `xyl`  
Status: executed; quality gate not passed

The signed finite target is 20 Claims / 48 material items / 24 material relations. The model never received the gold, production database access was zero, holdout access was false, concurrency was one, and automatic retries were zero.

| source | max calls | actual calls | Claims | material_items | material_relations | extracted facts/items | protocol result |
|---|---:|---:|---:|---:|---:|---:|---|
| industrial-fulian-md | 32 | 21 | valid, review_required (91 facts) | invalid, review_required (53 items; 46 extracted, 9 partial, 1 no-supported) | 0; dependency blocked | 91 / 53 | atomic slot obligations incomplete |
| optical-module-docx | 47 | 27 | valid, review_required (41 facts) | invalid, review_required (82 items; 71 extracted, 20 partial, 1 no-supported) | 0; dependency blocked | 41 / 82 | atomic slot obligations incomplete |

The 48 calls are within the 79-call ceiling. `plan_consistent=true` for both sources. No relation call was made because the upstream `material_items` artifact was not protocol-valid; this is the intended fail-closed dependency behavior, not a missing retry.

The material-item failures are semantic coverage failures, not transport failures. The model returned successful HTTP responses, but the atomic coverage ledger reported missing required signal types (notably negation/evidence) and failed validation for some slots. Therefore the output remains review-required and is not eligible for publication or downstream consumption. The exact per-source ledgers and immutable objects are under each source's `check.json`, `summary.json`, and `store/` directory.

This run is a diagnostic candidate extraction, not a completed quality score: the signed target is finite and recall can be adjudicated, but precision is `N/A` until every extra candidate is independently adjudicated. `quality_gate_passed=false` remains the correct conclusion.
