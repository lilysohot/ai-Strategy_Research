# P14 · final bounded question-group relation execution

Status: **final gate failed; current model plus extractor route closed**

The separately authorized P14 execution consumed exactly four relation calls and no
Claims or items calls. All four HTTP/model attempts completed successfully and no
automatic retry was made. Total recorded usage was 53,370 prompt, 14,189 completion,
11,657 reasoning, and 67,559 total tokens. The provider did not return a price, so cost
is unavailable rather than zero.

Two packets completed and two failed strict protocol validation. In attempts 2 and 3,
15 non-answer `relation_result` rows returned the relation type in `status`: eight
`challenges`, five `supports`, and two `conditions`. The frozen contract permits only
`present` or `absent`. The controller therefore rejected those packets; it did not
coerce the values, relax the schema, or replay the responses under a modified rule.
Transport and controller-owned question/pair indexing were not the failure source.

The frozen gate required 4/4 completed packets and zero failed packets. Actual result
was 2/4 completed and 2 failed, so the terminal gate failed before the signed 44-case,
known-error, regression, and target-relation quality scores could be validly computed.
The 92 relations retained from the two completed packets are an incomplete candidate
payload and must not be published or treated as a quality result.

Per the pre-execution terminal policy, no P15 prompt revision or extra call is allowed
inside this repair task. The current model plus extractor route is rejected and closed.
Any prompt/schema relaxation, model replacement, deterministic relation algorithm, or
other replacement is a new task with a new authorization and budget. Publication,
query, delivery, and context use remain unauthorized and zero.

The original `README.md`, `plan.json`, `final-gate.json`, and frozen plan manifest were
left byte-for-byte unchanged. `audit_live.py` is a zero-call, read-only audit of the
immutable live store; it emits `protocol-audit.json`, `execution-summary.json`, and
`final-decision.json`.
