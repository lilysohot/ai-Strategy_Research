# P10 accepted-items import live relation gate

P9 demonstrated the formal import seam but its first execution preflight froze an
unconfigured public profile, so the ledger imported items and blocked relations before any
attempt. No P9 model budget was consumed. The CLI now accepts an explicit
`--config-env-file`, and live execution validates only roles that can actually issue a model
request. P10 was therefore frozen as a new immutable plan rather than rewriting P9.

P10 imported the signed P7 items artifact into the formal ledger with zero items attempts.
The derived v5 relation task made exactly four authorized requests: all four succeeded, with
no retry or unknown outcome. Usage was 91,087 prompt, 30,924 completion, 22,616 reasoning,
and 122,011 total tokens. Provider cost metadata was unavailable and is not reported as zero.

The v5 candidate set contains 333 pairs and the selector accepted 217. The four frozen target
relations are all recalled, including both atomic answers to the Mitsui question. This passes
the selected-target recall gate, not a whole-document precision gate. Packet acceptance remains
highly non-uniform at 14/31, 79/84, 3/91 and 121/127, so publication and downstream consumption
remain blocked pending incremental signoff and a reusable precision sample.

