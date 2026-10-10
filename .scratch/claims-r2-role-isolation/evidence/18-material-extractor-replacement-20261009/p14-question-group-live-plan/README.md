# P14 · final bounded question-group relation plan

Status: **final plan frozen; execution is not authorized**

This is the final decision plan for the current material relation extractor line. It
reuses the immutable copper snapshot, signed accepted-items import, candidate-v5,
items validation v11, and strict `complete_parent` dependency policy. Claims and
items have zero attempt budget. Only the relation protocol changes to
`material-relations-question-group-jsonl-v1`, with at most four relation attempts and
no retry expansion.

The plan freeze may read the explicitly supplied structured-extraction configuration
to bind its model profile. It makes no model request and stores only the credential
reference, never the credential value.

Execution requires a separate explicit authorization for at most four relation calls.
Passing or failing that execution ends the current prompt/extractor repair line; no
P15 prompt revision is permitted under this task.

Frozen batch:
`batch:391150525103650ff49af17a251091c0908e00bd299553d7108643c174f27a58`.
The plan freeze made zero model requests. Verification confirms that P12→P14 changes
only the relation protocol and derived identities; snapshot, imported items, budgets,
candidate-v5, validation-v11, strict dependency policy, provider, model, and credential
reference are unchanged.

The final gate requires 4/4 completed packets, no partial or failed packet, at least
40/44 signed cases correct, at least 7/9 known errors corrected, at most two regressions
among the 35 previously correct cases, and 4/4 target relations. Publication and
positive consumption remain outside this authorization.
