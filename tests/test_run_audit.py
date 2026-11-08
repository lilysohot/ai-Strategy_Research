"""The audit remains available behind the same run ownership boundary."""

import json
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi import HTTPException

from server import run_outcome
from server.routes import runs


def test_terminal_audit_projection_preserves_checks_and_excludes_other_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(run_outcome, "run_dir_for", lambda _: tmp_path)
    assert run_outcome.read_terminal_audit("run") is None
    (tmp_path / "summary.json").write_text(json.dumps({"report_contract": {
        "verification_checks": [{"binding_id": "v1", "verdict": "fail"}],
        "acquisition_limits": [{"source": "https://source.test", "status": "partial"}],
        "private_worker_metadata": "not exposed",
    }}))
    result = run_outcome.read_terminal_audit("run")
    assert result["verification_checks"][0]["verdict"] == "fail"
    assert result["acquisition_limits"][0]["status"] == "partial"
    assert "private_worker_metadata" not in result


async def test_audit_is_not_read_before_ownership_check(monkeypatch):
    async def hidden(*_):
        return None

    monkeypatch.setattr(runs, "_visible_run", hidden)
    monkeypatch.setattr(runs, "read_terminal_audit", lambda _: pytest.fail("unauthorized disk read"))
    with pytest.raises(HTTPException) as error:
        await runs.run_audit(str(uuid4()), SimpleNamespace(id=uuid4()))
    assert error.value.status_code == 404


async def test_authorized_audit_uses_redacted_projection(monkeypatch):
    async def visible(*_):
        return object()

    monkeypatch.setattr(runs, "_visible_run", visible)
    monkeypatch.setattr(runs, "read_terminal_audit", lambda _: {"verification": "unchecked"})
    seen = []
    monkeypatch.setattr(runs, "redact_deep", lambda value: seen.append(value) or value)
    result = await runs.run_audit(str(uuid4()), SimpleNamespace(id=uuid4()))
    assert result == {"available": True, "audit": {"verification": "unchecked"}}
    assert seen == [{"verification": "unchecked"}]
