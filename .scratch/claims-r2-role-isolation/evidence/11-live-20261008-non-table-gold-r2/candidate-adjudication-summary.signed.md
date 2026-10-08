# Signed r2 candidate adjudication and prepublication observation

Date: 2026-10-08  
Reviewer/adjudicator: `xyl`  
Status: signed and frozen; quality gate failed

The user explicitly signed `candidate-adjudications.agent-draft.json`. The frozen successor preserves all 267 terminal decisions unchanged and records the agent rationale beside the human acceptance. No model or production-database call was made during freeze.

| role | candidates | matched | correct extra | incorrect | duplicate | precision | target recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| claims | 132 | 15 | 22 | 94 | 1 | 28.03% | 75.00% |
| material_items | 135 | 4 | 65 | 65 | 1 | 51.11% | 8.33% |
| material_relations | 0 | 0 | 0 | 0 | 0 | N/A | 0.00% |

Both exact source/build queries returned `CS_NOT_PUBLISHED` and zero records. Therefore delivery remained `not_delivered`, context use remained `not_used`, and M_main calls remained zero. The signed adjudication resolves the human-review gate only; it does not authorize publication and cannot turn these failed rates into a passing quality result.
