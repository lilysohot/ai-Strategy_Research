# P12 · relation selector v2 zero-call remediation

Status: **live execution complete; selector v2 rejected by signed quality gates**

P11 was signed by xyl on 2026-10-10. Its nine concrete relation errors split into
five P10 false-positive `present` decisions and four false-negative `absent`
decisions. All nine pairs already exist in the frozen v5 candidate set, so this
remediation deliberately does not add a lexical candidate-pruning layer or bump the
candidate rule. The failure is at the selector's semantic decision seam.

## Implementation

`material-relations-selector-jsonl-v2` keeps the v1 response shape and controller
ownership unchanged. It adds explicit atomic decision rules:

- an `answers` source atom must resolve the target question predicate;
- numeric, list, yes/no, and false-premise correction replies count as direct answers;
- same-turn adjacency, topical similarity, and explanation of a neighboring claim do
  not establish an answer;
- explicit self-correction can be `challenges`, while compatible facts on different
  dimensions cannot;
- `supports` and `conditions` still require explicit source linkage.

The v1 protocol remains readable and executable with its original prompt. The
role-artifact contract and CLI accept both v1 and v2; P12 explicitly selected v2.
After the live quality failure, new direct callers default back to v1 while v2 remains
read-compatible for immutable P12 audit and replay. Response fields, candidate
identity, evidence windows, item validation, and formal-ledger behavior are unchanged.

## Zero-call result

The script reconstructs the exact P10 population from hash-bound objects and confirms
the candidate set is still
`sha256:0e93746e5edf13547b7d149c90ebfa586ed48910707db5aceefac2379f100613`.
Applying only the signed P11 oracle corrections changes 217 present / 116 absent to
216 present / 117 absent:

- 5 signed false positives become absent;
- 4 signed false negatives become present;
- none of the four matched target-relation IDs is removed.

This is a counterfactual specification for calibration, not a claim that selector v2
has already reproduced the decisions. No model was called.

## Frozen plan

Batch `batch:3728b5fb95633c916e70706827709ef3f80572a71aa41f733d7e46cbc01d5b23`
is frozen with:

- the same snapshot and signed accepted-items import as P10;
- items attempts = 0;
- relation candidate rule v5 and validation v11 unchanged;
- strict `complete_parent` dependency;
- relation selector protocol v2;
- maximum four relation attempts, no retry expansion.

Freezing the plan made zero model requests. xyl subsequently authorized at most four
live relation calls. Execution used exactly four calls, all transport/protocol
successful, with no retries or ledger findings. Items remained at zero calls.

The live result failed the semantic gates:

- present decisions fell from 217 to 141 (87 present→absent, 11 absent→present);
- only 4/9 signed known errors were corrected;
- signed 44-case accuracy fell from P10's 35/44 to P12's 34/44;
- both Mitsui answer atoms were removed, reducing target relation recall from 4/4
  to 3/4.

Selector v2 is therefore rejected for release. The run remains an immutable candidate
artifact; publication, query, delivery, and context use remain zero.

## Files

- `build_counterfactual.py`: reconstructs P10, verifies signed P11 identity, freezes
  calibration cases and v2 prompt hashes.
- `signed-calibration-cases.json`: the nine signed decision deltas with atomic endpoint
  text.
- `counterfactual-summary.json`: zero-call population and target-preservation result.
- `accepted-items-artifact.json` / `accepted-items-payload.json`: hash-bound CLI inputs.
- `plan.json`: immutable selector-v2 relation-only plan.
- `verify_plan.py` / `plan-diff-summary.json`: proves P10→P12 changes only the selector
  protocol and derived identities.
- `evaluate_live.py`: exports the formal ledger result and evaluates it against the
  target scorer and signed P11 cases.
- `execution-summary.json` / `evaluation-summary.json`: formal execution and selected
  target results.
- `signed-sample-regression.json`: P10→P12 transitions and signed 44-case confusion.
- `failure-analysis.json`: failed-gate diagnosis and the next zero-call architecture.
