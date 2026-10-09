# P1 copper failure analysis

Date: 2026-10-09  
Status: P1 failed; stop current extractor patching; publication remains blocked

The signed Claims gate passed, then the frozen copper plan used all 16 authorized calls (12 items and 4 relations), with zero retries. Every call has an immutable response object and terminal attempt record. No production database or publication write occurred.

The items task produced 398 individually accepted candidates, but only 385 of 487 slots were complete; 102 slots remained partial, so the aggregate task is `succeeded / invalid / review_required`. Sixty slots had no terminal record. Fifty-seven of those omissions were concentrated in two 48-slot batches, while the same packet's final 25-slot batch was complete. Every response ended normally with `finish_reason=stop`, making provider truncation an unlikely explanation.

Thirty-five item attempts failed validation. Twenty-nine were exact-quote failures: 26 were caused by the model prepending an inferred speaker label such as `专家：` or `主持人：` to text that did not contain that prefix, while only three involved source HTML span/style markup. Upstream cleaning is therefore a real local defect, but it is not the primary cause of this run's failure.

Relations received all 180 fixed candidate-pair decisions, but five `present` decisions failed exact quote alignment for the same invented speaker-prefix reason. Two of four relation packets were partial. The generic ledger intentionally supports relation derivation from the extracted endpoint subset of partial items; that behavior conflicted with this P1 plan's stricter stop policy and allowed four relation calls that a strict trial should have blocked.

Claims adjudication is complete and xyl-signed. Items and relations are not sent to candidate-wide adjudication because their protocol roster is incomplete; the 398 items and 108 relations remain diagnostic evidence only. Frozen gold and thresholds are unchanged, and no new gold is required to repair this failure.

The required branch is now: preserve snapshots, roles, ledger, immutable response storage, frozen gold, and publication/consumption gates; replace the item/relation extractor implementation and freeze a strict complete-parent dependency policy. Do not create another prompt/lexicon patch version.
