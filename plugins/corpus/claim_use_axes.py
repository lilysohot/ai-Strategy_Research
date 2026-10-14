"""Per-axis withdrawal of claim uses (signed C4, scoring contract v4.4).

The historical rule granted ``compare`` and ``calculate`` together and only when a record had
**no** reason code at all (``evidence_pipeline`` §kinds: ``not reasons``). The signed C4 replaces
that all-or-nothing coupling with an explicit axis table:

* every reason code is classified into exactly one **axis** (this is code-side knowledge — the
  contract cannot name the codes);
* every axis declares which **uses** its gap withdraws;
* unknown codes fail closed (they withdraw the two strongest uses);
* no axis here withdraws ``cite``: whether a record may be cited at all stays with the existing
  evidence logic (``quality_status``, quote alignment, source spans) upstream of this table.

Vocabulary note: downstream consumers constrain ``usable_for`` to ``{cite, compare, calculate}``
(``plugins/corpus/structured/store.py``). The signed axes that only affect the *cite side*
(attribution / perspective / source_stance) therefore withdraw nothing here; they are recorded as
``cite_side_axes`` so a future purpose vocabulary can pick them up without changing this table.

Policy status: the default is the **conservative** reading — the condition/qualifier codes stay
on the axes that withdraw ``compare``/``calculate`` (matching §5.1.2's "gaps must not keep the
affected uses" and preserving today's outcomes). Moving those two codes to the attribution axis
is a caliber change and is measured in the 92-号 landing record (+16 calculable records on the
frozen claims pool); it needs a signed contract revision.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping

USES: tuple[str, ...] = ("cite", "compare", "calculate")
"""The purpose vocabulary the downstream layers accept."""

STRONGEST: frozenset[str] = frozenset({"compare", "calculate"})
"""The two uses withdrawn together by any axis gap that affects comparability."""

CITE_ONLY: frozenset[str] = frozenset()
"""The cite side only: nothing is withdrawn from the {cite, compare, calculate} vocabulary."""

REASON_AXIS: Mapping[str, str] = {
    # value
    "value_missing": "value",
    "value_not_in_evidence": "value",
    "value_unit_pair_not_in_quote": "value",
    "normalized_value_mismatch": "value",
    # unit
    "unit_missing": "unit",
    "unit_unknown": "unit",
    "metric_unit_mismatch": "unit",
    "normalized_unit_mismatch": "unit",
    # period / time anchor
    "period_missing": "period",
    "period_ambiguous": "period",
    "period_unanchored": "period",
    "period_not_in_packet": "period",
    "time_invalid": "period",
    "known_at_missing": "known_at",
    "known_at_unverified_override": "known_at",
    # metric
    "metric_missing": "metric",
    "metric_not_in_quote": "metric",
    "metric_not_registered": "metric",
    "ratio_definition_unverified": "metric",
    # subject
    "subject_missing": "subject",
    "subject_not_anchored": "subject",
    "subject_ambiguous": "subject",
    "subject_scope_mismatch": "subject",
    # kind
    "opinion_value_projection": "kind",
    # conflict
    "conflicting_values": "conflict",
    # evidence retrieval / atomicity
    "source_evidence_mapping_missing": "evidence",
    "evidence_not_found": "evidence",
    "atomic_evidence_unverified": "evidence",
    "atomic_evidence_mismatch": "evidence",
    "atomic_evidence_ambiguous": "evidence",
    # condition / qualifier / context (CONSERVATIVE DEFAULT — see module docstring)
    "source_qualified_context_requires_review": "condition",
    "source_condition_dependency": "condition",
    "source_negation_dependency": "condition",
    "qualifier_definition_unverified": "condition",
    "qualifier_invalid": "condition",
    "context_partial": "condition",
    # attribution side (cite-side only)
    "source_attribution_dependency": "attribution",
    # protocol / parse level
    "prompt_injection_detected": "protocol",
    "response_truncated": "protocol",
}

AXIS_USES: Mapping[str, frozenset[str]] = {
    "value": STRONGEST,
    "unit": STRONGEST,
    "period": STRONGEST,
    "known_at": STRONGEST,
    "metric": STRONGEST,
    "subject": STRONGEST,
    "kind": STRONGEST,
    "conflict": STRONGEST,
    "evidence": STRONGEST,
    "condition": STRONGEST,
    "protocol": STRONGEST,
    # Cite-side axes: nothing is withdrawn from today's {cite, compare, calculate} vocabulary.
    "attribution": CITE_ONLY,
    "perspective": CITE_ONLY,
    "source_stance": CITE_ONLY,
}

CITE_SIDE_AXES: tuple[str, ...] = ("attribution", "perspective", "source_stance")
"""Axes the signed C4 assigns to the cite side (no withdrawal in today's vocabulary)."""


def axis_of(reason_code: str) -> str | None:
    """The axis a reason code belongs to, or None when the code is unregistered."""
    return REASON_AXIS.get(reason_code)


def withdrawn_uses(reason_codes: Iterable[str]) -> frozenset[str]:
    """Uses withdrawn by these reason codes; unregistered codes fail closed (strongest)."""
    withdrawn: set[str] = set()
    for code in reason_codes:
        axis = axis_of(code)
        if axis is None:
            withdrawn |= STRONGEST
            continue
        withdrawn |= AXIS_USES.get(axis, STRONGEST)
    return frozenset(withdrawn)


def uses_for(reason_codes: Iterable[str], *, kind: str, has_value: bool) -> tuple[str, ...]:
    """Granted uses under the signed C4 axis table.

    ``kind``/``has_value`` keep the two structural preconditions: an opinion's number is not a
    fact to compare, and a record without a value can never be compared or calculated.
    """
    withdrawn = set(withdrawn_uses(reason_codes))
    if kind == "opinion" or not has_value:
        withdrawn |= STRONGEST
    return tuple(use for use in USES if use not in withdrawn)
