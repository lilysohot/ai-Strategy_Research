# P13 · question-group answer selector zero-call implementation

Status: **zero-call implementation and oracle replay complete; no live plan and no model calls**

P12 showed that judging 299 `answers` pairs independently is unstable. This stage
introduces `material-relations-question-group-jsonl-v1` without changing the frozen
candidate-v5 population. The controller groups existing answer pairs by question;
the model-facing interface returns only local answer indexes once per question. The
controller expands those indexes back to the existing immutable candidate pairs and
creates exact evidence windows and relation IDs. Non-answer relations retain their
pair-level terminals.

The zero-call replay uses P10 decisions plus the 44 signed P11 truths as an oracle.
It proves grouping identity, fail-closed terminal accounting, exact pair expansion,
and target preservation. It does **not** estimate live model accuracy or authorize a
new trial.

## Result

- candidate-v5 remains 333 pairs: 299 `answers` and 34 non-answer relations;
- 299 answer pairs become 66 question groups;
- required terminals fall from 333 to 100, a 69.97% reduction;
- prompt characters fall from P12's 195,046 to 127,133, a 34.82% reduction;
- the signed oracle expands to the exact 216 expected immutable pairs;
- all 44 signed cases and all 4 selected target relations are preserved;
- two deterministic runs produced the same summary hash.

The 44/44 result is an oracle/interface result, not a prediction of live model
accuracy. A separate bounded plan may be frozen only after review and explicit
authorization.

Publication, query, delivery, context use, and model calls remain zero.
