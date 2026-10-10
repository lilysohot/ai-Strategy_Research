# Issue 24 · Relation boolean protocol zero-call replay

Status: passed
Model calls: 0

- `material-relations-question-group-jsonl-v2` keeps answer-group local indices.
- Non-answer terminals are exactly `record_type`, `relation_index`, `is_present`.
- Controller restores relation type, pair identity, evidence window and relation ID.
- Frozen Issue 22 decisions replay as 4/4 complete packets, 333/333 candidate decisions,
  100 terminals, 212 present relations, and zero missing/duplicate/invalid decisions.
- Signed gold-v2 sensitivity remains 37/38; the only error is the compatible thickness
  ordering incorrectly selected as a challenge.

This replay proves Interface and parser closure only. It transforms already stored decisions
and therefore does not prove that Doubao Lite will obey the new output shape. A separately
frozen, bounded live trial is required for that claim.
