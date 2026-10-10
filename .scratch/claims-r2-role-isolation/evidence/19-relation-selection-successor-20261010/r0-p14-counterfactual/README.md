# Issue 19 R0 · P14 read-only counterfactual

Status: **semantic no-go; same-model successor stopped before implementation**

This audit answers whether the P14 failure was only a response-contract defect. It
opens the immutable P14 SQLite ledger read-only, verifies frozen file and object
hashes, rebuilds candidate-v5 question-group mappings, and narrowly interprets a
non-answer relation type as `present` only when it exactly matches that candidate's
controller-owned type and retains `evidence_selector="pair_window"`.

The reconstruction is complete: all 333 candidate decisions are recovered with no
unrecoverable records. Fifteen terminals receive the pre-registered diagnostic
interpretation. This does not mutate P14, revive its failed decision, or constitute a
valid protocol replay.

The resulting semantics fail the frozen quality gate:

- signed cases: 32/44, required at least 40/44;
- known errors: 5/9, required at least 7/9;
- regressions among the 35 previously correct cases: 8, maximum 2;
- target relations: 4/4;
- supports/conditions regressions: 2, pre-registered maximum 0.

Therefore P14 was not merely a format failure. Per the pre-registered decision tree,
the proposed same-model selected-indices implementation and any further live call are
stopped. A different model or deterministic/hybrid algorithm would be a separately
authorized future task, not a continuation of P14 or Issue 19.

`audit_counterfactual.py` writes nothing and prints one canonical JSON object. Two
independent runs produced the same stdout SHA-256:
`c65f99889bbcd64a4dba6812b60ee5a6072bdc1272770e89d3838a2efc7fbe71`.
Ruff and Pyright pass. No model, publication, query, delivery, or context-use action
occurred.
