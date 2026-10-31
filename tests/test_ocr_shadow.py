"""Admission, containment and failure regressions for the opt-in OCR sidecar."""

import json
import subprocess
from unittest.mock import Mock

import pytest

from tools import _ocr_shadow_worker as worker
from tools import ocr_shadow as shadow


def test_disabled_never_reads_sources_or_runs_docker(monkeypatch, capsys):
    validate = Mock(side_effect=AssertionError("must not read manifest"))
    docker = Mock(side_effect=AssertionError("must not call Docker"))
    monkeypatch.setattr(shadow, "validate_documents", validate)
    monkeypatch.setattr(shadow.subprocess, "run", docker)
    assert shadow.main(["--manifest", "/does-not-exist"]) == 0
    assert json.loads(capsys.readouterr().out)["status"] == "disabled"
    validate.assert_not_called()
    docker.assert_not_called()


@pytest.mark.parametrize("pages", [[True], [0], [1, 1], list(range(1, 8)), []])
def test_page_boundaries(tmp_path, pages):
    source = tmp_path / "test.pdf"
    source.write_bytes(b"%PDF fixture")
    with pytest.raises(ValueError):
        shadow.validate_documents(
            [{"path": str(source), "sha256": shadow.digest(source), "pages": pages}]
        )


def test_changed_input_rejected(tmp_path):
    source = tmp_path / "test.pdf"
    source.write_bytes(b"%PDF changed")
    with pytest.raises(ValueError, match="hash"):
        shadow.validate_documents([{"path": str(source), "sha256": "0" * 64, "pages": [1]}])


def test_unknown_cannot_promote_candidate_or_native_fallback():
    decision = {"status": "unknown", "candidates": [{"raw": {"lines": ["123.45"]}}]}
    assert worker.oriented_payload(decision) == {"status": "error", "text": ""}
    result = worker.review_envelope({"status": "error", "text": "native footer"}, decision)
    assert result["status"] == "orientation_unknown"
    assert result["body"]["text"] == "native footer"
    assert result["eligible_for_ingestion"] is False
    assert result["needs_review"] is True


def test_selected_coordinates_are_in_corrected_page_space():
    raw = {
        "lines": ["42.5%"],
        "scores": [0.99],
        "render_pixels": [100, 200],
        "boxes_normalized": [[[0.1, 0.2], [0.5, 0.2], [0.5, 0.3], [0.1, 0.3]]],
    }
    converted = worker.oriented_payload({"status": "oriented", "raw": raw})
    assert converted["boxes"][0] == [[10, 40], [50, 40], [50, 60], [10, 60]]
    result = worker.review_envelope({"status": "ok"}, {"status": "oriented"})
    assert result["status"] == "needs_review"
    assert result["eligible_for_ingestion"] is False


@pytest.mark.parametrize("status", ["error", "timeout", "empty", "fallback", "unavailable"])
def test_failure_not_masked_by_pending_review(status):
    assert worker.review_envelope({"status": status}, None)["status"] == status


def test_native_gaps_preserved():
    body = {"status": "needs_review", "coverage": {"missing_regions": [1]}, "text": "native"}
    result = worker.review_envelope(body, None)
    assert result["body"] == body
    assert result["orientation"] is None
    assert result["needs_review"] is True


def test_container_mounts_only_copies_and_result_dir(tmp_path):
    command = shadow.container_command(
        "generated-name",
        tmp_path / "frozen",
        tmp_path / "inputs",
        tmp_path / "out",
        "sha256:fixed",
        "doc0.pdf",
        1,
    )
    mounts = [command[i + 1] for i, arg in enumerate(command) if arg == "--mount"]
    assert len(mounts) == 3
    assert sum(m.endswith(",readonly") for m in mounts) == 2
    assert command[command.index("--network") + 1] == "none"
    assert "--read-only" in command
    assert command[command.index("--pull") + 1] == "never"
    assert all("docker.sock" not in m for m in mounts)


def test_timeout_removes_only_own_container_and_records_failure(monkeypatch, tmp_path):
    run = Mock(
        side_effect=[subprocess.TimeoutExpired("docker", 120), subprocess.CompletedProcess([], 0)]
    )
    monkeypatch.setattr(shadow.subprocess, "run", run)
    result = shadow.execute_page(["docker", "run"], tmp_path, "frontier-ocr-shadow-owned")
    assert result["status"] == "timeout"
    assert run.call_args_list[1].args[0] == ["docker", "rm", "-f", "frontier-ocr-shadow-owned"]
    assert (
        json.loads((tmp_path / "host-failure.json").read_text())["eligible_for_ingestion"] is False
    )


def test_worker_cannot_silently_approve(monkeypatch, tmp_path):
    (tmp_path / "result.json").write_text(
        json.dumps({"status": "ok", "eligible_for_ingestion": True})
    )
    monkeypatch.setattr(
        shadow.subprocess, "run", Mock(return_value=subprocess.CompletedProcess([], 0))
    )
    assert shadow.execute_page(["docker"], tmp_path, "owned")["status"] == "error"


def test_release_drift_rejected_before_docker(monkeypatch, tmp_path):
    source = tmp_path / "frozen.py"
    source.write_text("modified")
    release = tmp_path / "release.json"
    release.write_text(json.dumps({"files": {"frozen.py": "0" * 64}}))
    monkeypatch.setattr(shadow, "ROOT", tmp_path)
    monkeypatch.setattr(shadow, "RELEASE", release)
    docker = Mock(side_effect=AssertionError("should reject first"))
    monkeypatch.setattr(shadow.subprocess, "run", docker)
    with pytest.raises(ValueError, match="Frozen source"):
        shadow.verify_release()
    docker.assert_not_called()
