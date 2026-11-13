"""Navigation manifest feedback stays compact without changing verification."""

import json

import pytest

from frontier_agent.core.loop_types import ToolResult
from plugins.corpus import projection, tool_refs
from workflows.agent_team.subagent_runtime import SwarmToolResultPostProcessor
from workflows.stateful_react_agent._runtime import ReactToolResultPostProcessor


@pytest.fixture(autouse=True)
def navigation(monkeypatch):
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", "on")
    projection.reset_snapshot_index()
    yield
    projection.reset_snapshot_index()


def _full_result():
    return {
        "ok": True, "manifest_file": "/srv/run/corpus/manifest.json", "owner": "worker:1",
        "submission_mode": "upsert", "active_conclusion_ids": ["C1", "C2"],
        "publish_status": "partial", "evidence_status": "partial", "report_bound": True,
        "counts": {"supported": 1, "partial": 1},
        "conclusions": [{
            "id": "C2", "status": "partial", "delivery": ["pending"],
            "missing_dependencies": ["footnote"],
            "matched_evidence": [{"doc_id": "cv2:hidden", "locator": "chunk:hidden",
                                  "start": 0, "end": 10, "quote": "原文" * 10_000}],
            "semantic_references": [{
                "publication_id": "hidden-publication", "record_id": "hidden-record",
                "evidence_ranges": [{"unit_id": "hidden-unit", "source_start": 5}],
                "purpose": "cite", "delivery_status": "pending",
                "publication_status": "published", "verification_status": "pending",
                "quality_status": "review_required",
            }],
            "problems": [{"code": "pending_delivery", "message": "evidence[1] cv2:hidden"}],
        }],
    }


@pytest.mark.parametrize("processor", [ReactToolResultPostProcessor, SwarmToolResultPostProcessor])
def test_manifest_is_projected_before_generic_truncation(processor):
    full = _full_result()
    body = json.dumps(full)
    assert len(body) > 6_000
    output = processor().process(ToolResult(
        name="corpus_submit_manifest", args={}, result=body, duration_ms=0, tool_call_id="m1",
        is_error=False,
    ))
    visible = json.loads(output)
    assert len(output) < 2_000
    assert visible["active_conclusion_ids"] == ["C1", "C2"]
    assert visible["submission_mode"] == "upsert" and visible["report_bound"] is True
    assert visible["counts"] == full["counts"]
    row = visible["conclusions"][0]
    assert row["missing_dependencies"] == ["footnote"]
    assert row["problems"][0]["evidence_index"] == 1
    assert row["semantic_references"][0]["verification_status"] == "pending"
    assert row["semantic_references"][0]["quality_status"] == "review_required"
    assert "hidden" not in output and "/srv/" not in output
    assert projection.materialize("corpus_submit_manifest", output, tool_call_id="m1") == full
    assert projection.project_tool_result("corpus_submit_manifest", output) == output


@pytest.mark.parametrize("full,code", [
    ({"ok": False, "errors": [
        "conclusions[2].evidence[1].evidence_ref: cannot read /srv/private cv2:hidden"
    ]}, "invalid_evidence"),
    ({"ok": False, "errors": ["conclusions[0] 语义引用无效: unit:hidden /srv/private"]},
     "invalid_semantic_reference"),
    ({"ok": True, "verification_error": "RuntimeError /srv/private cv2:hidden"},
     "verification_error"),
    ({"ok": False, "error_kind": "report_binding", "errors": ["/srv/private missing"]},
     "report_binding_error"),
])
def test_manifest_error_paths_never_replay_internal_details(full, code):
    output = projection.project_tool_result("corpus_submit_manifest", json.dumps(full))
    visible = json.loads(output)
    assert visible["errors"][0]["code"] == code
    if code == "invalid_evidence":
        assert visible["errors"][0]["targets"] == ["conclusions[2].evidence[1].evidence_ref"]
    assert "hidden" not in output and "/srv/" not in output
    assert projection.materialize("corpus_submit_manifest", output) == full


def test_manifest_snapshot_failure_never_falls_back_to_internal_body(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("/srv/private inaccessible")

    monkeypatch.setattr(tool_refs, "store_metadata_snapshot", fail)
    output = projection.project_tool_result("corpus_submit_manifest", json.dumps(_full_result()))
    visible = json.loads(output)
    assert visible["ok"] is False
    assert visible["publish_status"] == "verification_error"
    assert visible["errors"][0]["code"] == "metadata_snapshot_unavailable"
    assert "hidden" not in output and "/srv/" not in output
    assert projection.try_materialize("corpus_submit_manifest", output) is None


def test_manifest_legacy_feedback_is_unchanged(monkeypatch):
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", "off")
    body = json.dumps(_full_result())
    assert projection.project_tool_result("corpus_submit_manifest", body) == body


def test_manifest_invalid_json_does_not_leak_raw_exception():
    output = projection.project_tool_result("corpus_submit_manifest", "error /srv/private cv2:hidden")
    assert json.loads(output)["ok"] is False
    assert "hidden" not in output and "/srv/" not in output
