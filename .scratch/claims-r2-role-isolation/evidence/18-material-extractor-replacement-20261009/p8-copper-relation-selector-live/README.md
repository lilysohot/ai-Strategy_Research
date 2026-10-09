# P8 copper relation selector bounded live gate

The signed P7 items artifact was reused unchanged. No item model request was made. Four
relation packets were authorized, durably recorded before I/O, and sent once each with no
retry. All four returned `stop` and completed protocol validation.

The run froze 269 deterministic candidate pairs and accepted 190 relations. The frozen
selected-target scorer reports 1/4 relation recall. Atomic endpoint adjudication recovers
three of the four gold relations: capex Q/A, yield Q/A, and quoted yield support. The Mitsui
Q/A relation had no deterministic candidate and therefore could not reach the selector.

This evidence does not estimate relation precision: the copper gold is selected target gold,
not exhaustive negative gold. The 70.63% accepted-candidate rate and extreme packet variance
(10/31, 58/58, 3/60, 119/120) are calibration warnings. Publication, semantic query,
delivery, and context use remain blocked.

The normal batch ledger cannot import an accepted replay-mode items artifact as the parent of
a live-mode relations task. `run_relation_gate.py` therefore uses the production relation role
executor and adapter with a separate atomic attempt ledger. This is an explicitly recorded
architecture gap; the evidence runner must not be treated as a general publication path.

Post-run zero-call correction: `material-development-scorer-4` now expands only relation
endpoints across bounded atomic groups and deduplicates matches by gold relation. Re-evaluating
this same immutable payload reports 3/4, matching the signed adjudication; the earlier 1/4 is
retained above as the historical scorer result. Candidate rule v5 also removes seven edges
aimed only at a facilitator invitation while preserving 333 candidates and both Mitsui answer
atoms. No v5 selector call was made here. The formal import gap is closed by the separately
frozen P9 plan.
