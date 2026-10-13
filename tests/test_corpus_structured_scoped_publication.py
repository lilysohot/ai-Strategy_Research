"""Scoped publication preserves source failures and verifies selected evidence."""

import json
import sqlite3

import pytest
from test_corpus_structured_publication import deny_external_io, forecast_artifacts  # noqa: F401

from plugins.corpus.structured.config import canonical_hash
from plugins.corpus.structured.consumption import (
    SemanticConsumption,
    reference_for_record,
    verify_reference,
)
from plugins.corpus.structured.ledger import StructuredExecutionError, _read_object, _write_object
from plugins.corpus.structured.query import query_semantic
from plugins.corpus.structured.store import (
    EXPLICIT_GAPS,
    SCOPED_SELECTION_PREFIX,
    ArtifactReference,
    publish_semantic,
    read_semantic,
    retire_semantic,
)


def scoped_fixture(tmp_path, *, quality="review_required", failed_slot=False):
    snapshot, plan, root, refs, _ = forecast_artifacts(tmp_path)
    ref = refs["material_items"]
    artifact = _read_object(root, ref.artifact_sha256)
    connection = sqlite3.connect(root / "index/structured.sqlite3")
    payload_sha = connection.execute(
        "SELECT payload_object_sha256 FROM tasks WHERE task_id=?", (ref.task_id,)
    ).fetchone()[0]
    payload = _read_object(root, payload_sha)
    item_id = payload["understanding"]["items"][0]["item_id"]
    if failed_slot:
        payload["understanding"]["coverage"]["slot_ledger"][0]["status"] = "failed"
        payload["run_id"] = canonical_hash(
            {k: v for k, v in payload.items() if k != "run_id"}
        ).removeprefix("sha256:")
        payload_sha = _write_object(root, payload)
        artifact["payload_sha256"] = canonical_hash(payload)
    artifact.update(
        quality_status=quality, execution_status="outcome_unknown", protocol_status="not_checked"
    )
    artifact["coverage"]["omitted_unit_ids"] = [snapshot.units[0].unit_id]
    artifact["artifact_id"] = canonical_hash(
        {k: v for k, v in artifact.items() if k != "artifact_id"}
    )
    new_sha = _write_object(root, artifact)
    connection.execute(
        "UPDATE tasks SET artifact_sha256=?, artifact_id=?, quality_status=?, execution_status='outcome_unknown', protocol_status='not_checked', publication_status='unpublished', payload_object_sha256=?, payload_sha256=? WHERE task_id=?",
        (
            new_sha,
            artifact["artifact_id"],
            quality,
            payload_sha,
            artifact["payload_sha256"],
            ref.task_id,
        ),
    )
    connection.commit()
    connection.close()
    ref = ArtifactReference(batch_id=plan.batch_id, task_id=ref.task_id, artifact_sha256=new_sha)
    args = dict(
        source_id=snapshot.source_id,
        build_id=snapshot.build_id,
        snapshot_id=snapshot.snapshot_id,
        artifacts=[ref],
        expected_parent_publication_id=None,
        store_root=root,
    )
    return snapshot, root, ref, item_id, args


def test_scoped_publish_preserves_failures_and_exact_selection(tmp_path):
    snap, root, ref, item_id, args = scoped_fixture(tmp_path)
    original = _read_object(root, ref.artifact_sha256)
    with pytest.raises(StructuredExecutionError, match="artifact_not_publishable"):
        publish_semantic(**args)
    pub = publish_semantic(**args, record_selection={ref.artifact_sha256: [item_id]})
    assert pub.quality_status == "review_required"
    assert pub.coverage.material_items == "partial"
    view = read_semantic(snap.source_id, snap.build_id, store_root=root)
    assert view.artifacts[0].artifact.execution_status == "outcome_unknown"
    assert _read_object(root, ref.artifact_sha256) == original
    page = query_semantic(snap.source_id, snap.build_id, purpose="cite", store_root=root)
    assert [r.record_id for r in page.records] == [item_id]
    assert page.records[0].quality_status == "review_required"
    assert EXPLICIT_GAPS in page.error_codes
    empty = query_semantic(
        snap.source_id, snap.build_id, purpose="cite", query_text="no-such-text", store_root=root
    )
    assert empty.page_status == "no_match" and EXPLICIT_GAPS in empty.error_codes
    retire_semantic(
        source_id=snap.source_id,
        build_id=snap.build_id,
        expected_parent_publication_id=pub.publication_id,
        store_root=root,
    )
    assert (
        query_semantic(snap.source_id, snap.build_id, purpose="cite", store_root=root).page_status
        == "not_published"
    )


@pytest.mark.parametrize("mode", ["empty", "unknown", "wrong_artifact", "rejected", "failed_slot"])
def test_invalid_scoped_selection_fails_closed(tmp_path, mode):
    snap, root, ref, item_id, args = scoped_fixture(
        tmp_path,
        quality="rejected" if mode == "rejected" else "review_required",
        failed_slot=mode == "failed_slot",
    )
    selection = {ref.artifact_sha256: [item_id]}
    if mode == "empty":
        selection[ref.artifact_sha256] = []
    if mode == "unknown":
        selection[ref.artifact_sha256] = ["invented"]
    if mode == "wrong_artifact":
        selection = {"sha256:" + "f" * 64: [item_id]}
    with pytest.raises(StructuredExecutionError):
        publish_semantic(**args, record_selection=selection)
    assert (
        query_semantic(snap.source_id, snap.build_id, purpose="cite", store_root=root).page_status
        == "not_published"
    )


def test_selection_object_tampering_is_rejected(tmp_path):
    snap, root, ref, item_id, args = scoped_fixture(tmp_path)
    pub = publish_semantic(**args, record_selection={ref.artifact_sha256: [item_id]})
    digest = next(
        x.removeprefix(SCOPED_SELECTION_PREFIX)
        for x in pub.reason_codes
        if x.startswith(SCOPED_SELECTION_PREFIX)
    ).removeprefix("sha256:")
    path = root / "objects/sha256" / digest[:2] / (digest + ".json")
    value = json.loads(path.read_text())
    value["records"][ref.artifact_sha256].append("invented")
    path.write_text(json.dumps(value))
    with pytest.raises(StructuredExecutionError):
        read_semantic(snap.source_id, snap.build_id, store_root=root)


def test_a4_scoped_citation_still_requires_actual_delivery(tmp_path, monkeypatch):
    snap, root, ref, item_id, args = scoped_fixture(tmp_path)
    pub = publish_semantic(**args, record_selection={ref.artifact_sha256: [item_id]})
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(root))
    page = query_semantic(snap.source_id, snap.build_id, purpose="cite", store_root=root)
    consumption = SemanticConsumption()
    consumption.record_result(
        {"source_id": snap.source_id, "build_id": snap.build_id}, page.model_dump_json(), "q1", 1
    )
    reference = reference_for_record(
        pub.publication_id, page.records[0], "cite", "claim", "forecast"
    )
    result, problems = verify_reference(
        reference, consumption=consumption, final_text="forecast", pending_aware=False
    )
    assert result.verification_status != "verified" and problems
    consumption.confirm_request(
        [{"role": "tool", "tool_call_id": "q1", "content": page.model_dump_json()}]
    )
    result, problems = verify_reference(
        reference, consumption=consumption, final_text="forecast", pending_aware=False
    )
    assert not problems and result.verification_status == "verified"
    assert result.quality_status == "review_required" and EXPLICIT_GAPS in result.error_codes
