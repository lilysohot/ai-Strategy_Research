# Issue 21 P0 · GLM-5.3-Flash 16K bounded live trial

Status: **final gate failed; 16K compatibility route closed**

This compatibility trial keeps the Issue 20 model and all extraction inputs,
prompt/schema versions, candidates, gold, and gates fixed. It changes only the
public request option `max_output_tokens` from 4,096 to 16,384. Claims and items
remain at zero calls; relations may use at most four calls with no retry.

The generic CLI preflight first rejected a default-4K credential restoration
against the frozen 16K profile before any request. The same immutable plan was
then executed through an exact-profile entry point. Three requests completed and
all three exhausted 16,384 completion tokens with empty visible content; the
fourth crossed the 300-second boundary as `outcome_unknown`. It was not retried.

Known usage for the first three requests is 32,812 prompt, 49,152 completion,
49,121 reasoning, and 81,964 total tokens. The unknown request may also have
consumed tokens or cost. All four packets failed with zero visible protocol
records, so the 44/9/35/4 semantic gate was not scored. Increasing the output
limit alone is rejected; publication and downstream consumption remain zero.
