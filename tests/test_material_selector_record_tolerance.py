"""The 109-号 root-cause fix: selector-protocol tolerance for an omitted constant record_type.

Round-1 of the items re-extraction lost 10/24 packets because the model emitted obligation
records *without* the constant ``record_type`` leaf while every other field was present and
exact — the strict validator discarded the whole packet. The fix re-injects the constant in
``_strict_role_llm`` and only there; every other deviation still rejects unchanged.
"""

from __future__ import annotations

import json

import pytest

from plugins.corpus.material_semantics import _strict_role_llm

SELECTOR = frozenset({"obligation_result"})
SLOT = frozenset({"speaker", "item", "coverage"})


def _obligation(index: int = 0, **overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "obligation_index": index,
        "status": "no_supported_item",
        "reason_code": "title_only",
        "items": [],
    }
    row.update(overrides)
    return row


def test_missing_record_type_is_reinjected() -> None:
    llm = _strict_role_llm(lambda _prompt: json.dumps(_obligation()), SELECTOR)
    assert llm is not None
    result = json.loads(llm("prompt"))
    assert result["record_type"] == "obligation_result"
    assert result["obligation_index"] == 0


def test_valid_response_returns_byte_identical() -> None:
    raw = json.dumps({"record_type": "obligation_result", **_obligation()})
    llm = _strict_role_llm(lambda _prompt: raw, SELECTOR)
    assert llm is not None
    assert llm("prompt") == raw


def test_partial_tolerance_keeps_conformant_lines_untouched() -> None:
    good = json.dumps({"record_type": "obligation_result", **_obligation(0)})
    tolerant = json.dumps(_obligation(1))
    raw = f"{good}\n{tolerant}"
    llm = _strict_role_llm(lambda _prompt: raw, SELECTOR)
    assert llm is not None
    lines = llm("prompt").splitlines()
    assert lines[0] == good
    assert json.loads(lines[1])["record_type"] == "obligation_result"


def test_missing_record_type_with_wrong_shape_still_rejects() -> None:
    llm = _strict_role_llm(lambda _prompt: json.dumps({"obligation_index": 0}), SELECTOR)
    assert llm is not None
    with pytest.raises(ValueError, match="unsupported JSONL record"):
        llm("prompt")


def test_wrong_record_type_still_rejects() -> None:
    llm = _strict_role_llm(
        lambda _prompt: json.dumps({"record_type": "item", "candidate_slot_id": "s", **_obligation()}),
        SELECTOR,
    )
    assert llm is not None
    with pytest.raises(ValueError, match="unsupported JSONL record"):
        llm("prompt")


def test_non_dict_line_still_rejects() -> None:
    llm = _strict_role_llm(lambda _prompt: '"just a string"', SELECTOR)
    assert llm is not None
    with pytest.raises(ValueError, match="unsupported JSONL record"):
        llm("prompt")


def test_tolerance_is_selector_only() -> None:
    llm = _strict_role_llm(lambda _prompt: json.dumps(_obligation()), SLOT)
    assert llm is not None
    with pytest.raises(ValueError, match="unsupported JSONL record"):
        llm("prompt")


def test_blank_lines_survive_normalization() -> None:
    raw = f"\n{json.dumps(_obligation())}\n"
    llm = _strict_role_llm(lambda _prompt: raw, SELECTOR)
    assert llm is not None
    assert json.loads(llm("prompt").splitlines()[1])["record_type"] == "obligation_result"
