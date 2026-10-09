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

The plan was frozen with zero model requests. It authorizes at most four future relation
attempts and zero claims/items attempts, but it has not been executed. Publication, query,
delivery and context use remain zero.

