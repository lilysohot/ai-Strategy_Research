"""The 109-号 items re-extraction entry trio: freeze, gates, stage 2, worksheet.

What these tests pin, all zero-call:

* prepare/execute refuse unless the 109-号 pre-registration is signed and its budget binding is
  intact — "P1 签认前禁止起跑" and "预算未授权不得起跑" are enforced by code, not convention;
* the recomputed batch count may not exceed the signed historical reference (md 10 / docx 14);
* stage-2 gate rules are read from the signed pre-registration and evaluated literally, so amending
  the signed rule changes behaviour without a code edit; an unknown rule refuses (fail-closed);
* the worksheet rows are blank for the named human, carry the 92-号 C1 pending-coverage checklist
  (29 entries, hash-bound), and a failed gate emits ``stage2-failed.json`` instead of a worksheet.
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sqlite3
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
HERE = (
    ROOT
    / ".scratch/claims-r2-role-isolation/evidence/109-items-extraction-and-publication-20261015"
    / "r0-zero-call"
)
PREREG = HERE / "items-reextraction-preregistration-v2.json"  # canonical; frozen (round-3)
DRAFT_PREREG = HERE / "items-reextraction-preregistration.draft.json"
AUTHORISATION = HERE / "budget-authorisation-r2.json"
C1_REGISTRATION = (
    ROOT
    / ".scratch/claims-r2-role-isolation/evidence/92-claims-scope-registration-20261014"
    / "r0-zero-call/claims-scope-registration.json"
)


def _module(name: str):
    spec = importlib.util.spec_from_file_location(name, HERE / f"{name}.py")
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _prereg_copy(tmp_path: Path, **changes: object) -> Path:
    payload = json.loads(PREREG.read_text(encoding="utf-8"))
    payload.update(changes)
    target = tmp_path / "prereg.json"
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


def _authorisation_copy(tmp_path: Path, **changes: object) -> Path:
    payload = json.loads(AUTHORISATION.read_text(encoding="utf-8"))
    payload.update(changes)
    target = tmp_path / "authorisation.json"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return target


def _bound_prereg(tmp_path: Path) -> tuple[Path, Path]:
    """A signed prereg whose budget binding points at a fresh authorisation copy."""
    authorisation = _authorisation_copy(tmp_path)
    payload = json.loads(PREREG.read_text(encoding="utf-8"))
    payload["budget_request"]["stage_1_live_run"]["authorisation_record"]["sha256"] = _sha256(
        authorisation
    )
    prereg = tmp_path / "prereg.json"
    prereg.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return prereg, authorisation


# ---------------------------------------------------------------- prepare


def test_prepare_refuses_a_draft_prereg(tmp_path: Path) -> None:
    prepare = _module("prepare_items_reextract_plan")
    prepare.PREREG = _prereg_copy(tmp_path, status="draft_pending_human_signature")
    with pytest.raises(SystemExit, match="draft_pending_human_signature"):
        prepare.signed_prereg()


def test_prepare_refuses_a_stale_authorisation_binding(tmp_path: Path) -> None:
    prepare = _module("prepare_items_reextract_plan")
    prepare.PREREG = _prereg_copy(tmp_path, status="frozen_before_execution")
    prepare.AUTHORISATION = _authorisation_copy(tmp_path)  # hash differs from the draft binding
    with pytest.raises(SystemExit, match="different authorisation"):
        prepare.signed_prereg()


def test_prepare_refuses_batches_beyond_the_signed_reference() -> None:
    prepare = _module("prepare_items_reextract_plan")
    historical = {"items-industrial-fulian-md": 10, "items-optical-module-docx": 14}
    with pytest.raises(SystemExit, match="须 U 另裁"):
        prepare.check_attempts("industrial-fulian-md", 11, historical)
    prepare.check_attempts("industrial-fulian-md", 10, historical)  # equal passes
    prepare.check_attempts("optical-module-docx", 14, historical)


# ---------------------------------------------------------------- execute


def test_executor_refuses_a_draft_prereg(tmp_path: Path) -> None:
    executor = _module("execute_items_reextract")
    executor.PREREG = _prereg_copy(tmp_path, status="draft_pending_human_signature")
    with pytest.raises(SystemExit, match="draft_pending_human_signature"):
        executor.authorised_budget()


def test_executor_refuses_a_missing_authorisation(tmp_path: Path) -> None:
    executor = _module("execute_items_reextract")
    prereg, _ = _bound_prereg(tmp_path)
    executor.PREREG = prereg
    executor.AUTHORISATION = tmp_path / "absent.json"
    with pytest.raises(SystemExit, match="不得起跑"):
        executor.authorised_budget()


def test_executor_refuses_a_binding_mismatch(tmp_path: Path) -> None:
    executor = _module("execute_items_reextract")
    prereg, _ = _bound_prereg(tmp_path)
    executor.PREREG = prereg
    executor.AUTHORISATION = _authorisation_copy(
        tmp_path / "other", budget={"ceiling_total_tokens": 1}
    )
    with pytest.raises(SystemExit, match="不一致"):
        executor.authorised_budget()


def test_executor_refuses_an_ineffective_authorisation(tmp_path: Path) -> None:
    executor = _module("execute_items_reextract")
    authorisation = _authorisation_copy(tmp_path, status="draft_pending_human_signature")
    payload = json.loads(PREREG.read_text(encoding="utf-8"))
    payload["status"] = "frozen_before_execution"
    payload["budget_request"]["stage_1_live_run"]["authorisation_record"]["sha256"] = _sha256(
        authorisation
    )
    executor.PREREG = tmp_path / "prereg.json"
    executor.PREREG.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    executor.AUTHORISATION = authorisation
    with pytest.raises(SystemExit, match="不生效"):
        executor.authorised_budget()


def test_executor_accepts_the_bound_authorisation(tmp_path: Path) -> None:
    executor = _module("execute_items_reextract")
    prereg, authorisation = _bound_prereg(tmp_path)
    executor.PREREG = prereg
    executor.AUTHORISATION = authorisation
    budget = executor.authorised_budget()
    assert budget["value"] == 1_000_000
    assert budget["unit"] == "total_tokens"
    assert budget["attempts_ceiling"] == 30


def test_disk_state_is_freeze_ready() -> None:
    """The real files on disk: canonical prereg frozen, binding the real r2 authorisation."""
    executor = _module("execute_items_reextract")
    budget = executor.authorised_budget()
    assert budget["value"] == 1_000_000
    assert budget["attempts_ceiling"] == 30
    assert budget["authorisation_status"] == "countersigned_effective"


# ---------------------------------------------------------------- worksheet


def _fake_store(tmp_path: Path, slug: str, items: list[dict], succeeded: bool = True) -> None:
    store = tmp_path / slug / "live-store"
    payload = {
        "understanding": {
            "speakers": [
                {"speaker_id": "spk_x", "role": "document_voice", "identity_status": "unknown"}
            ],
            "items": items,
        }
    }
    digest = hashlib.sha256(json.dumps(payload).encode()).hexdigest()
    object_dir = store / "objects/sha256" / digest[:2]
    object_dir.mkdir(parents=True)
    (object_dir / f"{digest}.json").write_text(json.dumps(payload), encoding="utf-8")
    index = store / "index"
    index.mkdir(parents=True)
    connection = sqlite3.connect(index / "structured.sqlite3")
    connection.execute(
        "CREATE TABLE tasks (task_id TEXT, role TEXT, execution_status TEXT,"
        " protocol_status TEXT, payload_object_sha256 TEXT)"
    )
    connection.execute(
        "INSERT INTO tasks VALUES (?, 'material_items', ?, 'not_checked', ?)",
        (
            "task:1",
            "succeeded" if succeeded else "failed",
            "sha256:" + digest,
        ),
    )
    connection.execute("CREATE TABLE attempts (attempt_id TEXT, execution_status TEXT)")
    connection.execute("INSERT INTO attempts VALUES ('attempt:1', 'succeeded')")
    connection.commit()
    connection.close()


def _item(item_id: str, text: str) -> dict:
    return {
        "item_id": item_id,
        "text": text,
        "semantic_type": "fact",
        "statement_role": "claim",
        "speech_role": "statement",
        "perspective": "source_explicit",
        "polarity": "affirmed",
        "speaker_ref": "spk_x",
        "evidence": [{"locator": "chunk:c", "quote": text[:10]}],
    }


def _fake_freeze(tmp_path: Path, succeeded: bool = True) -> Path:
    freeze = tmp_path / "freeze"
    _fake_store(freeze, "industrial-fulian-md", [_item("itm_a", "第一批事实陈述。")], succeeded)
    _fake_store(freeze, "optical-module-docx", [_item("itm_b", "第二条事实陈述。")], succeeded)
    manifest = {
        "entries": [
            {"slug": "industrial-fulian-md", "source_id": "sha256:f8fa"},
            {"slug": "optical-module-docx", "source_id": "sha256:48c0"},
        ]
    }
    (freeze / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (freeze / "execution-summary.json").write_text(
        json.dumps({"new_model_calls": 2, "budget_exceeded": False}), encoding="utf-8"
    )
    return freeze


def test_worksheet_rows_are_blank_and_c1_checklist_is_hash_bound(tmp_path: Path) -> None:
    builder = _module("build_items_adjudication_worksheet")
    builder.PREREG = _prereg_copy(tmp_path, status="frozen_before_execution")
    freeze = _fake_freeze(tmp_path)
    result = builder.build(freeze, tmp_path / "out")
    worksheet = result["worksheet"]
    assert worksheet["candidate_count"] == 2
    for row in worksheet["adjudications"]:
        assert row["judgement"] is None and row["matched_gold_id"] is None
        assert row["reviewer"] is None and row["adjudicator"] is None
        assert row["review_status"] == "pending_named_human_signoff"
    checklist = worksheet["c1_pending_coverage"]
    assert len(checklist) == 29
    assert all(entry["disposition"] is None for entry in checklist)
    assert worksheet["stage2_measured"]["sources_with_candidates"] == 2


def test_worksheet_refuses_a_c1_count_drift(tmp_path: Path) -> None:
    builder = _module("build_items_adjudication_worksheet")
    payload = json.loads(PREREG.read_text(encoding="utf-8"))
    payload["status"] = "frozen_before_execution"
    payload["adjudication_clause"]["c1_pending_coverage"]["count"] = 28
    builder.PREREG = tmp_path / "prereg.json"
    builder.PREREG.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    with pytest.raises(SystemExit, match="signed binding says 28"):
        builder.c1_checklist(payload)


def test_stage2_rules_follow_the_signed_file(tmp_path: Path) -> None:
    builder = _module("build_items_adjudication_worksheet")
    signed = _prereg_copy(tmp_path)
    builder.PREREG = signed
    measured = {"sources_with_candidates": 2, "attempts_outcome_unknown": 0}
    assert builder.apply_signed_gates(measured)["passed"] is True

    amended = json.loads(signed.read_text(encoding="utf-8"))
    amended["stage2_gates"]["gates"]["sources_with_candidates"]["rule"] = ">= 3"
    amended_path = tmp_path / "amended.json"
    amended_path.write_text(json.dumps(amended, ensure_ascii=False), encoding="utf-8")
    builder.PREREG = amended_path
    assert builder.apply_signed_gates(measured)["passed"] is False


def test_stage2_outcome_unknown_attempt_is_an_execution_incident(tmp_path: Path) -> None:
    builder = _module("build_items_adjudication_worksheet")
    builder.PREREG = _prereg_copy(tmp_path)
    measured = {"sources_with_candidates": 2, "attempts_outcome_unknown": 1}
    assert builder.apply_signed_gates(measured)["passed"] is False


def test_task_failure_alone_does_not_stop_the_round(tmp_path: Path) -> None:
    """v2 semantics: semantic-controller discards demote the task terminal state to report-only."""
    builder = _module("build_items_adjudication_worksheet")
    builder.PREREG = _prereg_copy(tmp_path)
    freeze = tmp_path / "freeze"
    _fake_store(freeze, "industrial-fulian-md", [_item("itm_a", "第一批事实陈述。")], succeeded=False)
    _fake_store(freeze, "optical-module-docx", [_item("itm_b", "第二条事实陈述。")])
    manifest = {
        "entries": [
            {"slug": "industrial-fulian-md", "source_id": "sha256:f8fa"},
            {"slug": "optical-module-docx", "source_id": "sha256:48c0"},
        ]
    }
    (freeze / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (freeze / "execution-summary.json").write_text(
        json.dumps({"new_model_calls": 2, "budget_exceeded": False}), encoding="utf-8"
    )
    result = builder.build(freeze, tmp_path / "out")
    assert result["gates"]["passed"] is True
    assert result["worksheet"]["stage2_measured"]["material_items_tasks_failed"] == 1
    assert result["worksheet"]["candidate_count"] == 2


def test_stage2_unknown_rule_fails_closed(tmp_path: Path) -> None:
    builder = _module("build_items_adjudication_worksheet")
    with pytest.raises(SystemExit, match="unsupported signed stage2 rule"):
        builder.evaluate_rule("≈ 2", 2)


def test_failed_gate_emits_stage2_failed_not_a_worksheet(tmp_path: Path) -> None:
    builder = _module("build_items_adjudication_worksheet")
    builder.PREREG = _prereg_copy(tmp_path, status="frozen_before_execution")
    freeze = tmp_path / "freeze"
    _fake_store(freeze, "industrial-fulian-md", [], succeeded=False)  # failed task, empty pool
    _fake_store(freeze, "optical-module-docx", [_item("itm_b", "第二条事实陈述。")])
    manifest = {
        "entries": [
            {"slug": "industrial-fulian-md", "source_id": "sha256:f8fa"},
            {"slug": "optical-module-docx", "source_id": "sha256:48c0"},
        ]
    }
    (freeze / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")
    (freeze / "execution-summary.json").write_text(
        json.dumps({"new_model_calls": 2, "budget_exceeded": False}), encoding="utf-8"
    )
    result = builder.build(freeze, tmp_path / "out")
    assert result["gates"]["passed"] is False
    assert result["worksheet"]["candidate_count"] == 1


def test_worksheet_refuses_a_budget_exceeded_run(tmp_path: Path) -> None:
    builder = _module("build_items_adjudication_worksheet")
    builder.PREREG = _prereg_copy(tmp_path, status="frozen_before_execution")
    freeze = _fake_freeze(tmp_path)
    summary = json.loads((freeze / "execution-summary.json").read_text(encoding="utf-8"))
    summary["budget_exceeded"] = True
    (freeze / "execution-summary.json").write_text(json.dumps(summary), encoding="utf-8")
    with pytest.raises(SystemExit, match="exceeded its token ceiling"):
        builder.build(freeze, tmp_path / "out")
