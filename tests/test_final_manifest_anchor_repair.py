"""Final-body anchor binding must preserve words and expose actionable repairs."""

import pytest

from plugins.tools.corpus_manifest import prepare_final_manifest


def conclusion(anchor):
    return {
        "id": "c1", "report_quote": anchor,
        "evidence": [{"doc_id": "doc1", "locator": "chunk:c1", "quote": "原文"}],
    }


def test_final_anchor_binds_formatting_to_exact_body_without_mutating_input():
    body = "- **乐观**：220 次，约 **1 GW**。"
    rows = [conclusion("乐观：220 次，约 1 GW。")]
    manifest = prepare_final_manifest(rows, body)
    assert manifest["conclusions"][0]["report_quote"] in body
    assert manifest["conclusions"][0]["report_quote"] == "**乐观**：220 次，约 **1 GW**。"
    assert rows[0]["report_quote"] == "乐观：220 次，约 1 GW。"


def test_changed_words_rejected_with_exact_body_repair_candidate():
    body = "- **压力**：50–70 次，一半用于算力，0.1–0.25 GW。"
    with pytest.raises(ValueError) as error:
        prepare_final_manifest([conclusion("压力情形：50–70 次，一半用于算力，0.1–0.25 GW。")], body)
    assert body in str(error.value)


@pytest.mark.parametrize("anchor", ["乐观：221 次，约 1 GW。", "乐观：220 次，约 2 GW。"])
def test_formatting_repair_never_changes_numbers(anchor):
    with pytest.raises(ValueError):
        prepare_final_manifest([conclusion(anchor)], "**乐观**：220 次，约 **1 GW**。")


@pytest.mark.parametrize("anchor", ["可达 1 GW", "不超过 1 MW", "超过 1 GW"])
def test_formatting_repair_preserves_negation_units_and_conditions(anchor):
    with pytest.raises(ValueError):
        prepare_final_manifest([conclusion(anchor)], "**不超过** 1 GW")


def test_ambiguous_formatting_matches_are_not_bound():
    with pytest.raises(ValueError):
        prepare_final_manifest([conclusion("乐观：1 GW")], "**乐观**：1 GW\n乐观：**1 GW**")


def test_code_markers_are_not_removed():
    with pytest.raises(ValueError):
        prepare_final_manifest([conclusion("x a y")], "`x **a** y`")
