"""F05: the ``/trace`` projection must keep readable reasoning and stay redacted.

The history view can only show reasoning the API actually returns — if the
projection ever strips ``thinking``, the UI silently loses it again. At the same
time this endpoint must not become a second unredacted egress, so the F03
boundary is pinned here too.

Both sides are checked against a synthetic trajectory file: no worker, no model,
no database, no network.
"""

from __future__ import annotations

import json

import pytest

from server.relay import trajectory_records_for_egress

_SECRET = "sk-abcdef1234567890"


@pytest.fixture
def run_dir(tmp_path, monkeypatch):
    """A run directory whose trajectory path matches what the reader expects."""
    d = tmp_path / "run-f05"
    (d / "run" / "agent" / "trajectories").mkdir(parents=True)
    monkeypatch.setattr("server.relay.run_dir_for", lambda run_id: d)
    return d


def _write(d, records: list[dict]) -> None:
    traj = d / "run" / "agent" / "trajectories" / "react_agent.jsonl"
    traj.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in records),
        encoding="utf-8",
    )


def test_trace_returns_readable_thinking(run_dir):
    _write(run_dir, [{"t": "llm", "turn": 1, "thinking": "先核对口径", "content": "hi"}])
    records = trajectory_records_for_egress("run-f05")
    assert records[0]["thinking"] == "先核对口径", "readable reasoning must survive the projection"


def test_trace_keeps_thinking_blocks_distinct_from_thinking(run_dir):
    """Encrypted/signed blocks stay on the record but are never prose.

    The view classifies a turn with only these as restricted; what matters here
    is that the block is still available for replay and was not flattened into
    ``thinking``.
    """
    _write(
        run_dir,
        [
            {
                "t": "llm",
                "turn": 1,
                "thinking_blocks": [{"type": "thinking", "signature": "ErUBCkYI"}],
            }
        ],
    )
    record = trajectory_records_for_egress("run-f05")[0]
    assert record["thinking_blocks"][0]["signature"] == "ErUBCkYI"
    assert "thinking" not in record, "blocks must not be flattened into readable reasoning"


def test_trace_still_redacts_tool_results(run_dir):
    """F03 boundary: a secret echoed by a tool is masked on this egress too."""
    _write(
        run_dir,
        [{"t": "result", "name": "bash", "result": f"export OPENAI_API_KEY={_SECRET}"}],
    )
    records = trajectory_records_for_egress("run-f05")
    assert _SECRET not in json.dumps(records, ensure_ascii=False)


def test_missing_trajectory_file_yields_no_records(run_dir):
    assert trajectory_records_for_egress("run-f05") == []
