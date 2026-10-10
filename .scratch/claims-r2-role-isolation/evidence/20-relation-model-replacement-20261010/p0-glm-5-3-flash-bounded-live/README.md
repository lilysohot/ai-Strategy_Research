# Issue 20 P0 · GLM-5.3-Flash bounded relation-only live trial

Status: **final gate failed; GLM-5.3-Flash plus frozen extractor closed**

This task is a model-only successor to the closed P14 route. It keeps the P14
snapshot, signed accepted-items import, relation candidate v5 population,
validation v11, strict `complete_parent` dependency, question-group prompt and
response protocol, and the signed 44/9/35/4 quality gate unchanged. The only
intentional experimental variable is the configured model identity,
`glm-5.3-flash`, plus identities derived from that profile.

The authorization ceiling is four relation requests. Claims and items have zero
attempt budget. There are no automatic retries, no new gold labels, and no
publication, query, delivery, or context use in this task.

The frozen batch used all four authorized relation requests. Transport succeeded
4/4 with no retry, but each response stopped at the 4,096 completion-token limit.
Reasoning consumed 16,377 of 16,384 completion tokens in aggregate and all four
visible contents were empty. Consequently all four packets failed before protocol
records existed, and the signed 44/9/35/4 semantic gate could not be scored.

This result rejects `glm-5.3-flash` with the frozen 4,096-token request profile; it
does not measure the model's relation semantics. Per the preregistered stop policy,
changing output budget, reasoning controls, prompt, or model requires a new task.
Publication, query, delivery, and context use remain zero.
