# P9 accepted-items import plan

This zero-call gate replaces the P8 side ledger with a first-class import inside the
formal structured execution ledger. The signed P7 `material_items` artifact and its
hash-bound `MaterialRun` payload are embedded in the immutable plan. Execution will
create a new ledger-owned import artifact whose sole upstream dependency is the P7
artifact; it cannot issue an items request.

The current relation candidate rule is v5. Against the same immutable P7 payload it
keeps 333 candidates: all 269 v3 candidates plus 64 source-ordered additions. It removes
only seven v4 edges aimed at the facilitator invitation “有请…提问，请发言”, and keeps
both Mitsui answer atoms linked to the actual Mitsui question.

The scorer is now `material-development-scorer-4`. Item field scoring remains one-to-one,
while relation endpoints may use a bounded same-speaker/same-role/same-packet atomic group.
Correct predicted edges are deduplicated by gold relation. Re-evaluating the immutable P8
payload therefore reports 3/4 relation recall, matching the signed adjudication.

The plan was frozen with zero model requests. It authorized at most four relation attempts
and zero claims/items attempts. Publication, query, delivery and context use remain zero.

2026-10-10 preflight update: execution imported items successfully but blocked the relation
task before reservation with `CS_CONFIG_MISSING`. The plan had frozen an unconfigured public
profile because the CLI did not yet expose the config loader's explicit dotenv path. No attempt
or budget was consumed. P9 is retained as failure evidence and must not be retried; P10 freezes
the configured profile after adding `--config-env-file`.
