"""The authorized Run view reads only the terminal board projection."""

import json

from server import run_outcome


def test_terminal_board_survives_reconnect_without_exposing_other_metadata(tmp_path, monkeypatch):
    monkeypatch.setattr(run_outcome, "run_dir_for", lambda _: tmp_path)
    assert run_outcome.read_terminal_task_board("run") is None
    (tmp_path / "summary.json").write_text(json.dumps({
        "report_contract": {"task_board": [{
            "id": "t1", "description": "Write answer", "resolution": "resolved",
            "unexpected_metadata": "must not leave the server",
        }, {
            "id": "t2", "description": "Verify", "resolution": "blocked",
            "gap": "Independent source unavailable", "verification_status": "unchecked",
            "verification_execution_status": "complete",
        }]},
    }))
    board = run_outcome.read_terminal_task_board("run")
    assert board[0] == {"id": "t1", "description": "Write answer", "resolution": "resolved"}
    assert board[1]["resolution"] == "blocked"
    assert board[1]["verification_execution_status"] == "complete"
    (tmp_path / "summary.json").write_text("invalid json")
    assert run_outcome.read_terminal_task_board("run") is None
