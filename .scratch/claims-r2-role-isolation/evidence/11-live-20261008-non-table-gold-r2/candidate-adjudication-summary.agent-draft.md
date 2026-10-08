# r2 candidate adjudication and query/delivery/context_use observation — agent draft

This is a complete agent-assisted pre-adjudication of the 267 persisted candidates. It is not a human signature and does not satisfy the named-human gate.

## Candidate results

| role | candidates | matched | correct extra | incorrect | duplicate | precision | target recall |
|---|---:|---:|---:|---:|---:|---:|---:|
| claims | 132 | 15 | 22 | 94 | 1 | 28.03% | 75.00% |
| material_items | 135 | 4 | 65 | 65 | 1 | 51.11% | 8.33% |
| material_relations | 0 | 0 | 0 | 0 | 0 | N/A | 0.00% |

## Stage observation

- Both source/build queries were executed read-only and returned `CS_NOT_PUBLISHED`, `page_status=not_published`, and zero records.
- `delivery=not_delivered`: no semantic evidence unit was returned for delivery.
- `context_use=not_used`: no semantic evidence entered a successful M_main request; M_main calls remain zero.
- The publication and quality gates remain closed. No store row, artifact, publication head, or user model configuration was changed.

## Required human action

A named reviewer must inspect every row in `candidate-adjudications.agent-draft.json`, amend disputed decisions, and append a signed freeze. Until then precision/recall above are agent suggestions, not the formal quality result.
