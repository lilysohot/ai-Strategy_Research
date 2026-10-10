# P11 · relation precision sample and recall sentinels

Status: **human signed by xyl on 2026-10-10; not a release gate**

This is a zero-model-call audit over the immutable P10 relation candidate set and
selector decisions. It does not alter P10 artifacts, gold, thresholds, publication,
query, delivery, or context use.

## Frozen population and sample

- Candidate universe: 333
- P10 `present`: 217
- P10 `absent`: 116
- Precision denominator: 32 sampled `present` decisions
  - all 19 non-`answers` predictions are a census;
  - 13 `answers` predictions are selected by stable SHA-256 rank within packet
    using frozen quotas 3/5/5.
- Recall sentinels: 12 sampled `absent` decisions across packet/type strata.
  They are diagnostic examples and are never included in the precision denominator.

Every row freezes its controller-owned candidate pair, both atomic endpoints, and
the exact source `pair_window`. `sample-plan.json` records the population count,
sample count, and inclusion probability for every stratum. The sample is reusable
while the snapshot, accepted items artifact, candidate rule, and selector decisions
remain unchanged.

## Agent-draft result

- Raw sample correctness: 27/32 (84.38%). This number is **not** a document
  precision estimate because rare relation types were deliberately oversampled.
- Stratified expansion estimate: 118/217 = **54.38%**.
- Diagnostic normal 95% interval: **24.78%–83.98%**. It is too wide for a release
  decision and all judgments remain unsigned.
- Recall sentinels: 4/12 P10 `absent` decisions were overturned. This proves
  concrete missed edges but is not a recall estimate because the sentinel design is
  not probability-weighted for recall.

Observed general failure modes:

1. `answers` edges are over-produced when a later atom belongs to the same response
   turn but does not resolve the pending question predicate.
2. A fact that merely explains payment uncertainty or supplies adjacent context is
   sometimes promoted to a complete answer.
3. Direct list answers, correction of a question's false premise, atomic numeric
   answers, and a speaker's explicit self-correction can be selected `absent`.

The next implementation step is zero-call: add candidate/selector regression
fixtures for these three families and tighten the prompt/rule seam before any new
live execution. A later signed quality gate should expand only the high-variance
`answers` strata if the remediation result still needs a precise estimate.

## Files

- `build_sample.py`: reconstructs the P10 candidate universe and freezes the sample.
- `sample-plan.json`: immutable sample identities, endpoint fields, windows, strata,
  and inclusion probabilities.
- `adjudicate_sample.py`: applies the explicit agent decisions and calculates the
  stratified draft estimate.
- `candidate-adjudications.agent-draft.json`: per-pair judgments and xyl's signed
  authorization; the historical filename is retained for stable references.
- `evaluation-summary.agent-draft.json`: metric calculation and failure taxonomy.

Reproduce from the repository root:

```bash
PYTHONPATH=. .venv/bin/python \
  .scratch/claims-r2-role-isolation/evidence/18-material-extractor-replacement-20261009/\
p11-relation-precision-sample/build_sample.py
PYTHONPATH=. .venv/bin/python \
  .scratch/claims-r2-role-isolation/evidence/18-material-extractor-replacement-20261009/\
p11-relation-precision-sample/adjudicate_sample.py
```
