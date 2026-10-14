"""Signed C4: per-axis withdrawal of claim uses, with a machine check on the vocabulary.

The axis table in ``plugins/corpus/claim_use_axes`` is only safe if it classifies **every**
reason code the producers can emit — an unregistered code silently withdraws the strongest uses
(fail-closed), which would look like a quality regression rather than a missing table row. The
vocabulary check below is therefore a conformance test, not a smoke test: it walks the producer
modules' ASTs and collects the code literals they can emit.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from plugins.corpus.claim_use_axes import (
    AXIS_USES,
    CITE_SIDE_AXES,
    REASON_AXIS,
    STRONGEST,
    USES,
    axis_of,
    uses_for,
    withdrawn_uses,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
PRODUCER_MODULES = (
    REPO_ROOT / "plugins/corpus/evidence_pipeline.py",
    REPO_ROOT / "plugins/corpus/claims_detail.py",
    REPO_ROOT / "plugins/corpus/_semantic_validation.py",
)
# Codes built by string interpolation (f-strings) cannot be read off the AST; they are enumerated
# here so the table must still classify each concrete expansion.
DYNAMIC_CODES = (
    "source_condition_dependency",
    "source_negation_dependency",
    "source_attribution_dependency",
)


def _emitted_codes(path: Path) -> set[str]:
    """Collect string literals the module emits as reason codes."""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    codes: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            name = ""
            if isinstance(node.func, ast.Attribute):
                name = node.func.attr
            if name in {"append", "extend"} and node.args:
                argument = node.args[0]
                if (
                    name == "append"
                    and isinstance(argument, ast.Constant)
                    and isinstance(argument.value, str)
                ):
                    codes.add(argument.value)
                if name == "extend" and isinstance(argument, (ast.List, ast.Tuple)):
                    codes |= _literals(argument)
        if isinstance(node, ast.keyword) and node.arg == "reason_codes":
            codes |= _literals(node.value)
        if isinstance(node, ast.Return) and isinstance(node.value, (ast.List, ast.Tuple)):
            codes |= _literals(node.value)
    return {code for code in codes if code and code.islower() and "_" in code}


def _literals(node: ast.AST) -> set[str]:
    found: set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Constant) and isinstance(child.value, str):
            value = child.value
            if value and value.islower() and "_" in value:
                found.add(value)
    return found


# ---------------------------------------------------------------- vocabulary conformance


def test_every_emitted_reason_code_is_classified() -> None:
    emitted: set[str] = set()
    for path in PRODUCER_MODULES:
        emitted |= _emitted_codes(path)
    unregistered = sorted(
        code for code in (emitted | set(DYNAMIC_CODES)) if code not in REASON_AXIS
    )
    assert unregistered == []
    assert emitted, "the AST scan found no reason codes — the scan itself is broken"


def test_every_axis_declares_its_uses() -> None:
    assert set(AXIS_USES) >= set(REASON_AXIS.values())
    assert all(uses <= set(USES) for uses in AXIS_USES.values())
    assert set(CITE_SIDE_AXES) <= set(AXIS_USES)
    for axis in CITE_SIDE_AXES:
        assert AXIS_USES[axis] == frozenset()


# ---------------------------------------------------------------- per-axis behaviour


@pytest.mark.parametrize(
    ("reason_codes", "expected"),
    [
        ((), ("cite", "compare", "calculate")),
        (("value_missing",), ("cite",)),
        (("unit_missing",), ("cite",)),
        (("period_ambiguous",), ("cite",)),
        (("metric_missing",), ("cite",)),
        (("subject_not_anchored",), ("cite",)),
        (("opinion_value_projection",), ("cite",)),
        # Conservative default: condition/qualifier context withdraws the strong uses.
        (("source_qualified_context_requires_review",), ("cite",)),
        (("qualifier_definition_unverified",), ("cite",)),
        # The signed attribution axis is cite-side only, so it withdraws nothing here.
        (("source_attribution_dependency",), ("cite", "compare", "calculate")),
        # Unregistered codes fail closed.
        (("brand_new_code",), ("cite",)),
    ],
)
def test_uses_follow_the_axis_table(reason_codes, expected) -> None:
    assert uses_for(reason_codes, kind="fact", has_value=True) == expected


def test_cite_is_never_withdrawn_by_a_numeric_or_context_axis() -> None:
    for code in REASON_AXIS:
        assert "cite" not in withdrawn_uses([code])


def test_unregistered_code_withdraws_the_strongest_uses_only() -> None:
    assert withdrawn_uses(["who_knows"]) == STRONGEST
    assert "cite" not in withdrawn_uses(["who_knows"])


def test_opinion_and_valueless_records_cannot_be_compared_or_calculated() -> None:
    assert uses_for((), kind="opinion", has_value=True) == ("cite",)
    assert uses_for((), kind="fact", has_value=False) == ("cite",)


def test_axis_lookup_is_explicit_about_unknown_codes() -> None:
    assert axis_of("value_missing") == "value"
    assert axis_of("not_a_code") is None
