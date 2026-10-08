# r3 quality remediation freeze · 2026-10-08

This is a zero-model-call freeze for the extraction-quality remediation following the signed r2
candidate adjudication. It does not overwrite the r2 run, publish semantic artifacts, or claim that
quality thresholds have passed.

Frozen current versions:

- Claims extractor: `af59c933380b`; lint: `claims-v2-lint-5`
- Evidence pipeline: `evidence-pipeline-8`
- Material extractor: `material-semantics-20`
- Material items protocol: `material-atomic-jsonl-v5`
- Material items validation: `material-items-validation-v3`
- Material relations protocol: `material-relations-jsonl-v1`

`freeze-manifest.json` binds the exact implementation, schema, configuration, tests, signed r2
adjudication, and frozen gold bytes. `structural-replay.json` records the no-model upper-bound audit.
The next permitted operation is a new bounded r3 run over the same 24 frozen non-table units,
followed by fresh human adjudication. The current status is not published.
