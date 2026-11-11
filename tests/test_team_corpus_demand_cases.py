"""Review-stage integrity only; no model or benchmark case execution."""

import hashlib
import json
from pathlib import Path

import pytest

from benchmarks.team_workflow.run import catalog, digest, require_runnable, select_cases
from benchmarks.team_workflow.worker import execute

ROOT = Path(__file__).resolve().parents[1] / "benchmarks/team_workflow"
NEW_IDS = {f"F{i}" for i in range(18, 26)} | {"P55"}


def test_original_71_case_objects_are_unchanged():
    lock = json.loads((ROOT / "baseline-71.lock.json").read_text())
    current = {c["id"]: c for c in catalog()}
    assert len(lock["cases"]) == 71
    assert set(current) - set(lock["cases"]) == NEW_IDS | {
        "P56",
        "P57",
        "P58",
        "F26",
        "F27",
        "F28",
    }
    for key, value in lock["cases"].items():
        assert digest(current[key]) == value


def test_approved_cases_are_runnable_and_pending_cases_still_fail_closed(monkeypatch):
    assert len(select_cases("frozen", None)) == 28
    assert len(select_cases("protocol", None)) == 58
    for case in catalog():
        if case["id"] in NEW_IDS:
            assert case["review_status"] == "approved"
            require_runnable(case)
    draft = {**next(c for c in catalog() if c["id"] == "F18"), "review_status": "pending_review"}
    monkeypatch.setattr("benchmarks.team_workflow.run.catalog", lambda: [draft])
    assert select_cases("frozen", None) == []
    with pytest.raises(ValueError, match="pending user review"):
        select_cases("frozen", ["F18"])


async def test_direct_worker_rejects_draft_before_provider_or_output_setup(tmp_path):
    case = next(c for c in catalog() if c["id"] == "F18")
    with pytest.raises(ValueError, match="pending user review"):
        await execute({**case, "review_status": "pending_review"}, tmp_path, "default")
    assert not list(tmp_path.iterdir())
    with pytest.raises(ValueError, match="unknown fixture adapter"):
        require_runnable({**case, "tool_fixture": "unknown"})


def test_fixtures_are_bound_and_opposing_controls_share_content():
    cases = {c["id"]: c for c in catalog()}
    raw = (ROOT / "corpus-demand-fixtures.json").read_bytes()
    fixtures = json.loads(raw)["documents"]
    for key in NEW_IDS - {"P55"}:
        case = cases[key]
        assert case["tool_fixture"] == "corpus_document_v1"
        source = case["sources"][0]
        assert source["fixture_sha256"] == hashlib.sha256(raw).hexdigest()
        doc = fixtures[source["document_key"]]
        assert doc["doc_id"] == source["doc_id"]
        unit_ids = {u["unit_id"] for u in doc["units"]}
        config = case["fixture_contract"]
        for field in ("search_excerpt_units", "search_preview_units", "candidate_inventory_units"):
            assert set(config[field]) <= unit_ids
    for left, right in (("F18", "F22"), ("F20", "F21"), ("F20", "F24")):
        assert cases[left]["sources"] == cases[right]["sources"]
    assert cases["F18"]["question"] == cases["F22"]["question"]
    assert cases["F22"]["fixture_contract"]["search_excerpt_units"] == []
    assert cases["F22"]["fixture_contract"]["search_preview_units"] == ["u01"]
    assert sum(len(u["text"]) for u in fixtures["orbit"]["units"]) > 6000
    assert "u06" not in cases["F23"]["fixture_contract"]["candidate_inventory_units"]
