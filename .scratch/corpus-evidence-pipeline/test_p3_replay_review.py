"""Synthetic guards for the P3 development-only inventory."""

from __future__ import annotations

import json
import socket
from pathlib import Path

import psycopg
import pytest
from p3_replay_review import DEV_IDS, NEW_WIRE_REQUIRED, build, load_inputs, normalized, verify_pins

from plugins.corpus import _r2_runtime as runtime


def test_frozen_inputs_and_development_boundary() -> None:
    verify_pins()
    samples, scopes = load_inputs()
    assert tuple(samples) == DEV_IDS
    assert all(row["sample_id"] in DEV_IDS for row in scopes)


def test_legacy_item_shape_cannot_enter_new_wire() -> None:
    old = {
        "record_type": "item",
        "candidate_slot_id": "slot-old",
        "text": "source says X",
    }
    assert not set(old) >= NEW_WIRE_REQUIRED
    with pytest.raises(ValueError):
        runtime.ItemWire.model_validate(old)


@pytest.mark.parametrize("extra", [" ", "。", "，"])
def test_normalization_is_only_literal_layout(extra: str) -> None:
    assert normalized("甲" + extra + "乙") in {"甲乙", "甲,乙"}


def test_actual_inventory_is_zero_call_and_not_replayable() -> None:
    inventory, queue = build()
    assert inventory["model_calls"] == inventory["judge_calls"] == inventory["postgres_access"] == 0
    assert inventory["holdout_source_paths_opened"] == 0
    assert all(row["new_wire_records_accepted"] == 0 for row in inventory["legacy"].values())
    assert all(
        row["new_runtime_replay"] == "not_replayable" for row in inventory["legacy"].values()
    )
    assert queue["approved_records"] == 0 and queue["reviewer"] is None


def test_actual_build_has_no_socket_or_postgres_path(monkeypatch: pytest.MonkeyPatch) -> None:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("external access forbidden")

    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(psycopg, "connect", forbidden)
    inventory, _ = build()
    assert inventory["postgres_access"] == 0


def test_all_legacy_terminal_ids_are_accounted_for() -> None:
    inventory, _ = build()
    for version in inventory["legacy"].values():
        assert version["raw_response_count"] == 9
        assert version["invalid_json_lines"] == 0
        assert sum(row["expected"] for row in version["terminal_coverage"].values()) == 37
        assert all(
            row["missing"] == row["unknown"] == 0 for row in version["terminal_coverage"].values()
        )


def test_all_micro_targets_remain_in_denominator() -> None:
    inventory, queue = build()
    assert len(queue["records"]) == 35
    assert sum(inventory["review_queue_counts"].values()) == 35
    assert all(row["review_status"] == "proposed_not_approved" for row in queue["records"])
    assert not inventory["p4_budget_authorized"]


def test_actual_planner_exposes_no_executable_candidate() -> None:
    inventory, _ = build()
    assert inventory["review_queue_counts"] == {"structurally_unresolved": 35}
    assert all(row["candidate_obligations"] == 0 for row in inventory["micro_planner"])
    assert all(row.get("candidate_obligations") == 0 for row in inventory["full_capacity"])


def test_output_writer_refuses_overwrite(tmp_path: Path) -> None:
    from p3_replay_review import write_once

    target = tmp_path / "result.json"
    write_once(target, {"ok": True})
    assert json.loads(target.read_text()) == {"ok": True}
    with pytest.raises(FileExistsError):
        write_once(target, {"ok": False})
