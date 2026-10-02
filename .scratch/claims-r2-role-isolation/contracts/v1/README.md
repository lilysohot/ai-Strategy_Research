# Structured corpus contract v1

This directory freezes the public envelopes for the first Claims/R2 role-isolation
increment.  It does not replace `EvidenceRun`/`EvidenceFact` or
`MaterialRun`/`MaterialUnderstanding`; role artifacts point at immutable payloads
serialized with those existing business contracts.

All hashes are lowercase SHA-256.  Identity hashes use UTF-8 JSON encoded with
sorted keys and separators `(',', ':')`.  Arrays retain order.  Timestamps,
filesystem paths, secrets, and mutable status fields are excluded unless a schema
explicitly lists them in `identity_input`.

Text offsets use zero-based, half-open Unicode code-point intervals over the exact
`text` field named by `text_sha256`.  They are never byte, UTF-16, PDF glyph, page,
or concatenated-document offsets.  A locator plus an interval is therefore not
portable to another text surface without an explicit mapping.

`state-codes.json` is the authoritative state/error catalogue.  Every envelope
keeps execution, protocol, publication, context, cross-role mapping, and quality
state in separate fields; no state implies another.

