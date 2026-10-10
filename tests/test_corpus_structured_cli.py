"""Process-level structured CLI tests across independent working directories."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_corpus_structured_execution import item_content, snapshot
from test_corpus_structured_publication import forecast_artifacts

from plugins.corpus.structured.ledger import BatchPlan
from plugins.corpus.structured.store import publish_semantic

ROOT = Path(__file__).resolve().parents[1]


def environment() -> dict[str, str]:
    env = dict(os.environ)
    for key in tuple(env):
        if key == "CORPUS_STRUCTURED_ROOT" or key.startswith("STRUCTURED_EXTRACTION_"):
            env.pop(key)
    env["PYTHONPATH"] = str(ROOT)
    return env


def run_cli(
    *args: str, cwd: Path, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "plugins.corpus.structured.cli", *args],
        cwd=cwd,
        env=env or environment(),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )


def prepare(tmp_path: Path) -> tuple[Path, Path, Path, BatchPlan]:
    value = snapshot()
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(value.model_dump_json(), encoding="utf-8")
    plan_path = tmp_path / "plan.json"
    planning_cwd = tmp_path / "planning-cwd"
    planning_cwd.mkdir()
    planned = run_cli(
        "plan",
        "--snapshot",
        str(snapshot_path),
        "--out",
        str(plan_path),
        "--max-attempts",
        "1",
        "--role-budget",
        "claims=0",
        "--role-budget",
        "material_items=1",
        "--role-budget",
        "material_relations=0",
        "--disable-relations",
        cwd=planning_cwd,
    )
    assert planned.returncode == 0, planned.stderr
    plan = BatchPlan.model_validate_json(plan_path.read_text(encoding="utf-8"))
    item_task = next(task for task in plan.tasks if task.role == "material_items")
    responses = tmp_path / "responses"
    responses.mkdir()
    (responses / "items.json").write_text(
        json.dumps(
            {
                "schema_version": "corpus-replay-response-v1",
                "task_id": item_task.task_id,
                "sequence": 1,
                "role": "material_items",
                "protocol": item_task.protocol,
                "request_sha256": None,
                "content": item_content(value),
                "diagnostics": {"usage": None, "cost": None},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    return snapshot_path, plan_path, responses, plan


def test_plan_replay_and_read_only_check_cross_process_and_cwd(tmp_path: Path) -> None:
    _, plan_path, responses, plan = prepare(tmp_path)
    store = tmp_path / "store"
    replay_cwd = tmp_path / "replay-cwd"
    check_cwd = tmp_path / "research-run-cwd"
    replay_cwd.mkdir()
    check_cwd.mkdir()

    replayed = run_cli(
        "replay",
        "--plan",
        str(plan_path),
        "--responses",
        str(responses),
        "--store-root",
        str(store),
        cwd=replay_cwd,
    )
    assert replayed.returncode == 0, replayed.stderr
    replay_payload = json.loads(replayed.stdout)
    assert replay_payload["ledger"]["batch_id"] == plan.batch_id
    assert replay_payload["ledger"]["budget"]["actual_attempts"] == 1

    database = store / "index" / "structured.sqlite3"
    before = (database.stat().st_mtime_ns, database.stat().st_size)
    checked = run_cli(
        "check",
        "--batch-id",
        plan.batch_id,
        "--store-root",
        str(store),
        cwd=check_cwd,
    )
    after = (database.stat().st_mtime_ns, database.stat().st_size)
    assert checked.returncode == 0, checked.stderr
    assert json.loads(checked.stdout) == replay_payload
    assert before == after


def test_query_reads_published_records_cross_process_and_cwd_without_writes(
    tmp_path: Path,
) -> None:
    value, _plan, store, references, _checked = forecast_artifacts(tmp_path)
    publication = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references["claims"],),
        expected_parent_publication_id=None,
        store_root=store,
    )
    cwd = tmp_path / "query-cwd"
    cwd.mkdir()
    database = store / "index" / "structured.sqlite3"
    before = (database.stat().st_mtime_ns, database.stat().st_size)

    queried = run_cli(
        "query",
        "--source-id",
        value.source_id,
        "--build-id",
        value.build_id,
        "--purpose",
        "calculate",
        "--query-text",
        "营业收入",
        "--limit",
        "20",
        "--field-filter",
        "role=claims",
        "--store-root",
        str(store),
        cwd=cwd,
    )

    assert queried.returncode == 0, queried.stderr
    payload = json.loads(queried.stdout)
    assert payload["schema_version"] == "corpus-semantic-query-page-v1"
    assert payload["publication_id"] == publication.publication_id
    assert payload["page_status"] == "complete"
    assert [record["role"] for record in payload["records"]] == ["claims"]

    unpublished = run_cli(
        "query",
        "--source-id",
        value.source_id,
        "--build-id",
        "9" * 64,
        "--purpose",
        "cite",
        "--store-root",
        str(store),
        cwd=cwd,
    )
    assert unpublished.returncode == 5
    assert json.loads(unpublished.stdout)["page_status"] == "not_published"

    invalid = run_cli(
        "query",
        "--source-id",
        value.source_id,
        "--build-id",
        value.build_id,
        "--purpose",
        "cite",
        "--field-filter",
        "role=unsupported",
        "--store-root",
        str(store),
        cwd=cwd,
    )
    assert invalid.returncode == 2
    assert invalid.stderr.strip() == "CS_INPUT_INVALID: query_invalid"
    assert before == (database.stat().st_mtime_ns, database.stat().st_size)


def test_execute_without_allow_model_is_config_error_but_runs_deterministic_work(
    tmp_path: Path,
) -> None:
    _, plan_path, _, plan = prepare(tmp_path)
    store = tmp_path / "store"
    cwd = tmp_path / "execute-cwd"
    cwd.mkdir()
    result = run_cli(
        "execute",
        "--plan",
        str(plan_path),
        "--store-root",
        str(store),
        cwd=cwd,
    )
    assert result.returncode == 3
    payload = json.loads(result.stdout)
    assert payload["ledger"]["attempts"] == []
    claims = next(task for task in payload["ledger"]["tasks"] if task["role"] == "claims")
    items = next(task for task in payload["ledger"]["tasks"] if task["role"] == "material_items")
    assert claims["execution_status"] == "succeeded"
    assert claims["artifact_sha256"].startswith("sha256:")
    assert items["execution_status"] == "blocked"
    assert items["error_codes"] == ["CS_CONFIG_MISSING"]

    checked = run_cli(
        "check",
        "--batch-id",
        plan.batch_id,
        "--store-root",
        str(store),
        cwd=cwd,
    )
    assert checked.returncode == 3


def test_missing_root_invalid_plan_and_unknown_batch_exit_codes(tmp_path: Path) -> None:
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    missing_root = run_cli("check", "--batch-id", "batch:none", cwd=cwd)
    assert missing_root.returncode == 3
    assert missing_root.stderr.strip() == "CS_STORE_ROOT_REQUIRED: structured_root_missing"

    bad_plan = tmp_path / "bad-plan.json"
    bad_plan.write_text("{}", encoding="utf-8")
    invalid = run_cli(
        "replay",
        "--plan",
        str(bad_plan),
        "--responses",
        str(cwd),
        "--store-root",
        str(tmp_path / "store"),
        cwd=cwd,
    )
    assert invalid.returncode == 2
    assert invalid.stderr.strip() == "CS_INPUT_INVALID: plan_invalid"

    unknown_root = tmp_path / "unknown-root"
    unknown_root.mkdir()
    unknown = run_cli(
        "check",
        "--batch-id",
        "batch:none",
        "--store-root",
        str(unknown_root),
        cwd=cwd,
    )
    assert unknown.returncode == 5
    assert unknown.stderr.strip() == "CS_NOT_FOUND: structured_index_not_found"


@pytest.mark.skipif(os.name == "nt", reason="process crash assertion uses POSIX os._exit")
def test_process_crash_after_reservation_resumes_as_unknown_without_resend(tmp_path: Path) -> None:
    _, plan_path, responses, plan = prepare(tmp_path)
    store = tmp_path / "store"
    cwd = tmp_path / "crash-cwd"
    cwd.mkdir()
    script = (
        "import os; from pathlib import Path; "
        "from plugins.corpus.structured.ledger import BatchPlan,replay_batch; "
        f"p=BatchPlan.model_validate_json(Path({str(plan_path)!r}).read_text()); "
        "replay_batch(p,"
        f"responses=Path({str(responses)!r}),store_root=Path({str(store)!r}),"
        "checkpoint=lambda name: os._exit(77) if name=='after_reserve' else None)"
    )
    crashed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=cwd,
        env=environment(),
        text=True,
        capture_output=True,
        timeout=30,
        check=False,
    )
    assert crashed.returncode == 77

    resumed = run_cli(
        "replay",
        "--plan",
        str(plan_path),
        "--responses",
        str(responses),
        "--store-root",
        str(store),
        cwd=cwd,
    )
    assert resumed.returncode == 6, resumed.stderr
    payload = json.loads(resumed.stdout)
    assert len(payload["ledger"]["attempts"]) == 1
    assert payload["ledger"]["attempts"][0]["execution_status"] == "outcome_unknown"
    assert "response_sha256" not in payload["ledger"]["attempts"][0]
    unknown_task = next(
        task for task in payload["ledger"]["tasks"] if task["execution_status"] == "outcome_unknown"
    )
    assert "artifact_sha256" not in unknown_task
    assert payload["ledger"]["budget"] == {
        "actual_attempts": 1,
        "currency": None,
        "max_attempts": 1,
        "reserved_attempts": 1,
    }
    assert payload["ledger"]["batch_id"] == plan.batch_id


def test_plan_default_budget_is_zero_and_does_not_infer_live_authority(tmp_path: Path) -> None:
    value = snapshot()
    source = tmp_path / "snapshot.json"
    target = tmp_path / "plan.json"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    source.write_text(value.model_dump_json(), encoding="utf-8")
    result = run_cli("plan", "--snapshot", str(source), "--out", str(target), cwd=cwd)
    assert result.returncode == 0
    plan = BatchPlan.model_validate_json(target.read_text(encoding="utf-8"))
    assert plan.max_attempts == 0
    assert set(plan.role_max_attempts.values()) == {0}
    assert json.loads(result.stdout)["model_requests"] == 0


def test_plan_cli_reads_only_an_explicit_config_env_file(tmp_path: Path) -> None:
    value = snapshot()
    source = tmp_path / "snapshot.json"
    target = tmp_path / "plan.json"
    config_env = tmp_path / "structured.env"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    source.write_text(value.model_dump_json(), encoding="utf-8")
    config_env.write_text(
        "STRUCTURED_EXTRACTION_PROVIDER=openai_compat\n"
        "STRUCTURED_EXTRACTION_MODEL=synthetic-model\n"
        "STRUCTURED_EXTRACTION_BASE_URL=https://synthetic.invalid/v1\n"
        "STRUCTURED_EXTRACTION_API_KEY=synthetic-not-a-secret\n",
        encoding="utf-8",
    )

    result = run_cli(
        "plan",
        "--snapshot",
        str(source),
        "--out",
        str(target),
        "--config-env-file",
        str(config_env),
        cwd=cwd,
    )

    assert result.returncode == 0, result.stderr
    plan = BatchPlan.model_validate_json(target.read_text(encoding="utf-8"))
    assert all(profile.configured for profile in plan.profiles)
    assert {profile.model for profile in plan.profiles} == {"synthetic-model"}


def test_plan_cli_can_freeze_claims_only(tmp_path: Path) -> None:
    value = snapshot(dual_model_roles=True)
    source = tmp_path / "snapshot.json"
    target = tmp_path / "plan.json"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    source.write_text(value.model_dump_json(), encoding="utf-8")

    result = run_cli(
        "plan",
        "--snapshot",
        str(source),
        "--out",
        str(target),
        "--max-attempts",
        "2",
        "--role-budget",
        "claims=2",
        "--role-budget",
        "material_items=0",
        "--role-budget",
        "material_relations=0",
        "--disable-relations",
        "--role",
        "claims",
        cwd=cwd,
    )

    assert result.returncode == 0, result.stderr
    plan = BatchPlan.model_validate_json(target.read_text(encoding="utf-8"))
    plan.verify_identity()
    assert plan.enabled_roles == ("claims",)
    assert {task.role for task in plan.tasks} == {"claims"}


def test_plan_cli_freezes_material_batching_options(tmp_path: Path) -> None:
    value = snapshot()
    source = tmp_path / "snapshot.json"
    target = tmp_path / "plan.json"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    source.write_text(value.model_dump_json(), encoding="utf-8")

    result = run_cli(
        "plan",
        "--snapshot",
        str(source),
        "--out",
        str(target),
        "--max-attempts",
        "1",
        "--role-budget",
        "claims=0",
        "--role-budget",
        "material_items=1",
        "--role-budget",
        "material_relations=0",
        "--disable-relations",
        "--role",
        "material_items",
        "--max-items-per-packet",
        "64",
        "--max-slots-per-batch",
        "48",
        "--material-type",
        "conference_minutes",
        cwd=cwd,
    )

    assert result.returncode == 0, result.stderr
    plan = BatchPlan.model_validate_json(target.read_text(encoding="utf-8"))
    plan.verify_identity()
    assert plan.material_items_options is not None
    assert plan.material_items_options.model_dump() == {
        "max_items_per_packet": 64,
        "max_slots_per_batch": 48,
        "material_type": "conference_minutes",
    }


def test_plan_cli_can_opt_into_controller_selector_protocol(tmp_path: Path) -> None:
    value = snapshot()
    source = tmp_path / "snapshot.json"
    target = tmp_path / "selector-plan.json"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    source.write_text(value.model_dump_json(), encoding="utf-8")

    result = run_cli(
        "plan",
        "--snapshot",
        str(source),
        "--out",
        str(target),
        "--role",
        "material_items",
        "--disable-relations",
        "--material-items-protocol",
        "material-atomic-selector-jsonl-v5",
        "--max-estimated-tokens-per-batch",
        "8192",
        "--candidate-slot-id",
        "slot:scope-a",
        cwd=cwd,
    )

    assert result.returncode == 0, result.stderr
    plan = BatchPlan.model_validate_json(target.read_text(encoding="utf-8"))
    plan.verify_identity()
    task = next(task for task in plan.tasks if task.role == "material_items")
    assert task.protocol == "material-atomic-selector-jsonl-v5"
    assert plan.material_items_options is not None
    assert plan.material_items_options.max_slots_per_batch == 24
    assert plan.material_items_options.max_estimated_tokens_per_batch == 8192
    assert plan.material_items_options.candidate_slot_ids == ("slot:scope-a",)


@pytest.mark.parametrize(
    "protocol",
    [
        "material-relations-selector-jsonl-v1",
        "material-relations-selector-jsonl-v2",
        "material-relations-question-group-jsonl-v1",
        "material-relations-question-group-jsonl-v2",
    ],
)
def test_plan_cli_can_freeze_relation_selector_protocol(tmp_path: Path, protocol: str) -> None:
    value = snapshot()
    source = tmp_path / "snapshot.json"
    target = tmp_path / "relation-selector-plan.json"
    cwd = tmp_path / "cwd"
    cwd.mkdir()
    source.write_text(value.model_dump_json(), encoding="utf-8")

    result = run_cli(
        "plan",
        "--snapshot",
        str(source),
        "--out",
        str(target),
        "--material-items-protocol",
        "material-atomic-selector-jsonl-v5",
        "--material-relations-protocol",
        protocol,
        "--relation-dependency-policy",
        "complete_parent",
        cwd=cwd,
    )

    assert result.returncode == 0, result.stderr
    plan = BatchPlan.model_validate_json(target.read_text(encoding="utf-8"))
    plan.verify_identity()
    profile = next(profile for profile in plan.profiles if profile.role == "material_relations")
    assert profile.protocol == protocol
    assert plan.relations.dependency_policy == "complete_parent"
