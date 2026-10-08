"""Durable structured execution ledger tests; synthetic replay only."""

from __future__ import annotations

import json
import socket
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path

import httpx
import pytest

from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.material_semantics import (
    build_candidate_slots,
    build_material_structure,
    build_relation_candidate_set,
)
from plugins.corpus.service import CorpusService
from plugins.corpus.structured.config import canonical_hash, load_extraction_config
from plugins.corpus.structured.ledger import (
    BatchPlan,
    ExecutionJournal,
    ReplayDirectory,
    ReplayResponse,
    StructuredExecutionError,
    _read_object,
    _write_object,
    cancel_batch,
    check_batch,
    execute_batch,
    plan_batch,
    replay_batch,
)
from plugins.corpus.structured.roles import RoleArtifact, RoleRequest, execute_material_items_role
from plugins.corpus.structured.snapshot import (
    EvidenceSnapshot,
    SnapshotBuildSource,
    SnapshotCellSource,
    SnapshotDocumentSource,
    SnapshotHead,
    SnapshotReader,
    SnapshotTextSource,
    SnapshotUnitSource,
    build_snapshot,
)

SOURCE_ID = "7" * 64
BUILD_ID = "8" * 64


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError(
            "execution tests must not access network, real models, or production DB"
        )

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(CorpusService, "_connect", denied)
    real_env = Path(__file__).resolve().parents[1] / ".env"
    original_open = Path.open

    def guarded_open(path: Path, *args: object, **kwargs: object):
        assert path.resolve() != real_env
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)


@dataclass
class Reader(SnapshotReader):
    payload: SnapshotBuildSource

    def read_head(self, source_id: str) -> SnapshotHead:
        assert source_id == SOURCE_ID
        return self.payload.head

    def read_build(self, head: SnapshotHead) -> SnapshotBuildSource:
        assert head == self.payload.head
        return self.payload


def snapshot(*, dual_model_roles: bool = False) -> EvidenceSnapshot:
    table = "指标|2025A\n营业收入|12|亿元"
    units = [
        SnapshotUnitSource(
            source_unit_id="table-u",
            chunk_id="table-c",
            kind="table",
            text=table,
            locator="page:1/table:1",
            ordinal=1,
            cells=(
                SnapshotCellSource(
                    row="营业收入",
                    column="2025A",
                    value="12",
                    unit="亿元",
                    start=14,
                    end=16,
                    row_ref=SnapshotTextSource("table-u", "table-c", 9, 13),
                    column_ref=SnapshotTextSource("table-u", "table-c", 3, 8),
                    unit_ref=SnapshotTextSource("table-u", "table-c", 17, 19),
                ),
            ),
        ),
        SnapshotUnitSource(
            source_unit_id="opinion-u",
            chunk_id="opinion-c",
            kind="prose",
            text="合成分析师认为竞争力可能改善。",
            locator="page:2/paragraph:1",
            ordinal=2,
        ),
    ]
    if dual_model_roles:
        units.append(
            SnapshotUnitSource(
                source_unit_id="forecast-u",
                chunk_id="forecast-c",
                kind="prose",
                text="预计虚构公司2026年收入15亿元。",
                locator="page:3/paragraph:1",
                ordinal=3,
            )
        )
    head = SnapshotHead(source_id=SOURCE_ID, build_id=BUILD_ID, publication_generation=1)
    return build_snapshot(
        Reader(
            SnapshotBuildSource(
                head=head,
                parser_versions={"parse": "p1", "clean": "c1", "chunk": "k1"},
                document=SnapshotDocumentSource(
                    title="合成执行账材料", subject="虚构公司", published="2026-01-01"
                ),
                units=tuple(units),
            )
        ),
        SOURCE_ID,
    )


def dialogue_snapshot() -> EvidenceSnapshot:
    head = SnapshotHead(source_id=SOURCE_ID, build_id=BUILD_ID, publication_generation=1)
    return build_snapshot(
        Reader(
            SnapshotBuildSource(
                head=head,
                parser_versions={"parse": "p1", "clean": "c1", "chunk": "k1"},
                document=SnapshotDocumentSource(
                    title="合成问答材料", subject="虚构公司", published="2026-01-01"
                ),
                units=(
                    SnapshotUnitSource(
                        source_unit_id="dialogue-u",
                        chunk_id="dialogue-c",
                        kind="prose",
                        text="主持人：需求是否改善？\n专家：因为订单增加，需求已经改善。",
                        locator="page:1/dialogue:1",
                        ordinal=1,
                    ),
                ),
            )
        ),
        SOURCE_ID,
    )


def write_response(directory: Path, response: ReplayResponse, name: str) -> None:
    directory.mkdir(parents=True, exist_ok=True)
    (directory / f"{name}.json").write_text(response.model_dump_json(), encoding="utf-8")


def extraction_config(model: str = "synthetic-model"):
    return load_extraction_config(
        environ={
            "STRUCTURED_EXTRACTION_PROVIDER": "openai_compat",
            "STRUCTURED_EXTRACTION_MODEL": model,
            "STRUCTURED_EXTRACTION_BASE_URL": "https://synthetic.invalid/v1",
            "STRUCTURED_EXTRACTION_API_KEY": "synthetic-not-a-secret",
        }
    )


def item_content(value: EvidenceSnapshot, *, extracted: bool = True) -> str:
    document = evidence_document_from_snapshot(value, role="material_items")
    structure = build_material_structure(document)
    slots = build_candidate_slots(document, structure)
    assert len(slots) == 1
    slot = slots[0]
    if not extracted:
        return json.dumps(
            {
                "record_type": "coverage",
                "candidate_slot_id": slot.candidate_slot_id,
                "status": "no_supported_item",
                "reason_codes": ["synthetic_no_item"],
            },
            ensure_ascii=False,
        )
    speaker_id = "spk_" + fingerprint([None, "document_voice", "unknown"])[:12]
    return json.dumps(
        {
            "record_type": "item",
            "candidate_slot_id": slot.candidate_slot_id,
            "item_id": "item-synthetic-opinion",
            "text": slot.text,
            "semantic_type": "opinion",
            "statement_role": "claim",
            "speech_role": "statement",
            "perspective": "source_explicit",
            "speaker_ref": speaker_id,
            "polarity": "affirmed",
            "value": None,
            "behavior_status": None,
            "temporal_frame": "contemporaneous",
            "evidence_quote": slot.text,
            "unknown_fields": [],
        },
        ensure_ascii=False,
    )


def dialogue_item_content(value: EvidenceSnapshot) -> str:
    document = evidence_document_from_snapshot(value, role="material_items")
    slots = build_candidate_slots(document, build_material_structure(document))
    assert len(slots) == 2
    records = []
    for slot in slots:
        question = "？" in slot.text
        label = "主持人" if question else "专家"
        role = "moderator" if question else "industry_expert"
        records.append(
            {
                "record_type": "item",
                "candidate_slot_id": slot.candidate_slot_id,
                "item_id": "item-question" if question else "item-answer",
                "text": slot.text,
                "semantic_type": "fact",
                "statement_role": "question" if question else "evidence",
                "speech_role": "question" if question else "answer",
                "perspective": "source_explicit",
                "speaker_ref": "spk_" + fingerprint([label, role, "unknown"])[:12],
                "polarity": "affirmed",
                "value": None,
                "behavior_status": None,
                "temporal_frame": "contemporaneous",
                "evidence_quote": slot.text,
                "unknown_fields": [],
            }
        )
    return "\n".join(json.dumps(record, ensure_ascii=False) for record in records)


def replay_fixture(
    value: EvidenceSnapshot, plan, directory: Path, *, extracted: bool = True
) -> None:
    for task in plan.tasks:
        if task.role == "material_items":
            write_response(
                directory,
                ReplayResponse(
                    task_id=task.task_id,
                    sequence=1,
                    role="material_items",
                    protocol=task.protocol,
                    content=item_content(value, extracted=extracted),
                    diagnostics={"usage": None, "cost": None},
                ),
                "items-1",
            )


def test_plan_is_stable_zero_call_and_freezes_limits() -> None:
    value = snapshot()
    first = plan_batch(
        value,
        max_attempts=2,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 1},
        max_relation_tasks=1,
        max_relation_attempts=1,
    )
    second = plan_batch(
        value,
        max_attempts=2,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 1},
        max_relation_tasks=1,
        max_relation_attempts=1,
    )
    assert first == second
    first.verify_identity()
    assert {task.method for task in first.tasks} == {"deterministic", "model"}
    assert all(task.role != "material_relations" for task in first.tasks)
    assert first.relations.rule_version == "material-relation-candidates-v3"
    assert first.routing.decisions
    assert all(decision.reason_codes for decision in first.routing.decisions)

    tampered_payload = first.model_dump(mode="json")
    tampered_payload["tasks"][0]["protocol"] = "claims-json-v2"
    identity = {
        key: value
        for key, value in tampered_payload.items()
        if key not in {"batch_id", "plan_sha256"}
    }
    tampered_payload["plan_sha256"] = canonical_hash(identity)
    tampered_payload["batch_id"] = f"batch:{tampered_payload['plan_sha256'][7:]}"
    tampered = BatchPlan.model_validate(tampered_payload)
    with pytest.raises(StructuredExecutionError, match="initial_tasks_do_not_match_routing"):
        tampered.verify_identity()


def test_replay_persists_contract_ledger_and_no_candidate_derivation(tmp_path: Path) -> None:
    value = snapshot()
    plan = plan_batch(
        value,
        max_attempts=2,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 1},
        max_relation_attempts=1,
    )
    responses = tmp_path / "responses"
    replay_fixture(value, plan, responses)
    result = replay_batch(plan, responses=responses, store_root=tmp_path / "store")

    assert result.plan_consistent
    assert result.ledger.budget.reserved_attempts == 1
    assert result.ledger.budget.actual_attempts == 1
    assert len(result.ledger.attempts) == 1
    assert result.ledger.attempts[0].provider == "replay"
    assert result.ledger.attempts[0].usage is None
    assert result.cost_summary[0].unknown_calls == 1
    assert set(task.role for task in result.ledger.tasks) == {
        "claims",
        "material_items",
        "material_relations",
    }
    assert set(result.derivations.values()) == {"no_candidates"}
    assert all(task.execution_status == "succeeded" for task in result.ledger.tasks)

    from test_corpus_structured_contracts import V1, _load, _validation_errors

    schema = _load(V1 / "execution-ledger.schema.json")
    assert _validation_errors(result.ledger.model_dump(mode="json"), schema, schema) == []


def test_read_only_check_works_after_cwd_change_without_mutating_index(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = snapshot()
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    responses = tmp_path / "responses"
    replay_fixture(value, plan, responses, extracted=False)
    root = tmp_path / "store"
    replay_batch(plan, responses=responses, store_root=root)
    database = root / "index" / "structured.sqlite3"
    before = (database.stat().st_mtime_ns, database.stat().st_size)
    elsewhere = tmp_path / "another-run"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    checked = check_batch(plan.batch_id, store_root=root)
    after = (database.stat().st_mtime_ns, database.stat().st_size)
    assert checked.plan_consistent
    assert before == after
    assert set(checked.derivations.values()) == {"disabled"}


def test_batch_and_role_budget_reservation_is_atomic_across_connections(tmp_path: Path) -> None:
    value = snapshot(dual_model_roles=True)
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 1, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    model_tasks = [task for task in plan.tasks if task.method == "model"]
    assert {task.role for task in model_tasks} == {"claims", "material_items"}
    root = tmp_path / "store"
    initializer = ExecutionJournal.open(plan, root)
    initializer.close()

    def reserve(task) -> tuple[str, str]:
        journal = ExecutionJournal.open(plan, root)
        profile = next(item for item in plan.profiles if item.role == task.role)
        request = RoleRequest(
            task_id=task.task_id,
            role=task.role,
            protocol=task.protocol,
            snapshot_id=value.snapshot_id,
            input_sha256=task.input_sha256,
            request_sha256=canonical_hash({"task": task.task_id}),
            prompt="synthetic",
            sequence=1,
        )
        try:
            try:
                return (
                    "reserved",
                    journal.reserve_attempt(
                        request,
                        request_sha256=request.request_sha256,
                        provider="replay",
                        request_model=profile.model or "replay-fixture",
                        profile_sha256=profile.profile_sha256,
                        role_profile_sha256=profile.role_profile_sha256,
                    ),
                )
            except StructuredExecutionError as exc:
                return ("rejected", exc.code)
        finally:
            journal.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(reserve, model_tasks))
    assert sorted(status for status, _ in outcomes) == ["rejected", "reserved"]
    assert next(value for status, value in outcomes if status == "rejected") == (
        "CS_BUDGET_EXHAUSTED"
    )


def test_atomic_budget_loser_is_explicit(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> None:
    value = snapshot(dual_model_roles=True)
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 1, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    root = tmp_path / "store"
    journal = ExecutionJournal.open(plan, root)
    tasks = [task for task in plan.tasks if task.method == "model"]
    first, second = tasks

    def request(task) -> RoleRequest:
        return RoleRequest(
            task_id=task.task_id,
            role=task.role,
            protocol=task.protocol,
            snapshot_id=value.snapshot_id,
            input_sha256=task.input_sha256,
            request_sha256=canonical_hash(task.task_id),
            prompt="synthetic",
            sequence=1,
        )

    first_profile = next(item for item in plan.profiles if item.role == first.role)
    journal.reserve_attempt(
        request(first),
        request_sha256=request(first).request_sha256,
        provider="replay",
        request_model=first_profile.model or "replay-fixture",
        profile_sha256=first_profile.profile_sha256,
        role_profile_sha256=first_profile.role_profile_sha256,
    )
    second_profile = next(item for item in plan.profiles if item.role == second.role)
    with pytest.raises(StructuredExecutionError, match="CS_BUDGET_EXHAUSTED"):
        journal.reserve_attempt(
            request(second),
            request_sha256=request(second).request_sha256,
            provider="replay",
            request_model=second_profile.model or "replay-fixture",
            profile_sha256=second_profile.profile_sha256,
            role_profile_sha256=second_profile.role_profile_sha256,
        )
    journal.close()
    checked = check_batch(plan.batch_id, store_root=root)
    assert checked.ledger.budget.reserved_attempts == 1
    assert checked.ledger.budget.actual_attempts == 1


def test_batches_with_same_logical_tasks_are_isolated_in_one_store(tmp_path: Path) -> None:
    value = snapshot()
    first_plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    second_plan = plan_batch(
        value,
        max_attempts=2,
        role_max_attempts={"claims": 0, "material_items": 2, "material_relations": 0},
        relations_enabled=False,
    )
    assert first_plan.batch_id != second_plan.batch_id
    first_task = next(task for task in first_plan.tasks if task.role == "material_items")
    second_task = next(task for task in second_plan.tasks if task.role == "material_items")
    assert first_task.task_id == second_task.task_id
    root = tmp_path / "store"

    journal = ExecutionJournal.open(first_plan, root)
    profile = next(item for item in first_plan.profiles if item.role == "material_items")
    request = RoleRequest(
        task_id=first_task.task_id,
        role="material_items",
        protocol=first_task.protocol,
        snapshot_id=value.snapshot_id,
        input_sha256=first_task.input_sha256,
        request_sha256=canonical_hash("first-batch-reserved-request"),
        prompt="synthetic",
        sequence=1,
    )
    attempt_id = journal.reserve_attempt(
        request,
        request_sha256=request.request_sha256,
        provider="replay",
        request_model="replay-fixture",
        profile_sha256=profile.profile_sha256,
        role_profile_sha256=profile.role_profile_sha256,
    )
    journal.connection.execute(
        "UPDATE attempts SET response_object_sha256=? WHERE batch_id=? AND attempt_id=?",
        ("sha256:" + "0" * 64, first_plan.batch_id, attempt_id),
    )
    journal.close()

    responses = tmp_path / "responses"
    replay_fixture(value, second_plan, responses)
    second = replay_batch(second_plan, responses=responses, store_root=root)
    assert second.plan_consistent
    assert len(second.ledger.attempts) == 1
    connection = sqlite3.connect(root / "index" / "structured.sqlite3")
    first_status = connection.execute(
        "SELECT execution_status FROM attempts WHERE batch_id=? AND attempt_id=?",
        (first_plan.batch_id, attempt_id),
    ).fetchone()
    connection.close()
    assert first_status == ("running",)


def test_batch_execution_mode_cannot_switch_between_replay_and_live(tmp_path: Path) -> None:
    plan = plan_batch(snapshot(), max_attempts=0, relations_enabled=False)
    root = tmp_path / "store"
    journal = ExecutionJournal.open(plan, root, "replay")
    journal.close()

    with pytest.raises(StructuredExecutionError, match="batch_execution_mode_mismatch"):
        ExecutionJournal.open(plan, root, "live")


def test_interrupted_reserved_attempt_becomes_unknown_and_is_never_replayed(tmp_path: Path) -> None:
    class Crash(BaseException):
        pass

    value = snapshot()
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    responses = tmp_path / "responses"
    replay_fixture(value, plan, responses)
    root = tmp_path / "store"

    def crash(name: str) -> None:
        if name == "after_reserve":
            raise Crash

    with pytest.raises(Crash):
        replay_batch(plan, responses=responses, store_root=root, checkpoint=crash)
    resumed = replay_batch(plan, responses=responses, store_root=root)
    assert len(resumed.ledger.attempts) == 1
    assert resumed.ledger.attempts[0].execution_status == "outcome_unknown"
    assert resumed.ledger.tasks[1].execution_status == "outcome_unknown"
    assert "attempt_outcome_unknown" in " ".join(resumed.findings)
    serialized = resumed.ledger.model_dump(mode="json")
    assert "response_sha256" not in serialized["attempts"][0]
    unknown_task = next(
        task for task in serialized["tasks"] if task["execution_status"] == "outcome_unknown"
    )
    assert "artifact_sha256" not in unknown_task

    from test_corpus_structured_contracts import V1, _load, _validation_errors

    schema = _load(V1 / "execution-ledger.schema.json")
    assert _validation_errors(serialized, schema, schema) == []


def test_saved_response_is_reparsed_after_artifact_crash_without_new_attempt(
    tmp_path: Path,
) -> None:
    class Crash(BaseException):
        pass

    value = snapshot()
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    responses = tmp_path / "responses"
    replay_fixture(value, plan, responses)
    root = tmp_path / "store"

    def crash(name: str) -> None:
        if name == "after_response_commit":
            raise Crash

    with pytest.raises(Crash):
        replay_batch(plan, responses=responses, store_root=root, checkpoint=crash)
    resumed = replay_batch(plan, responses=responses, store_root=root)
    assert len(resumed.ledger.attempts) == 1
    assert resumed.ledger.attempts[0].execution_status == "succeeded"
    assert next(
        task for task in resumed.ledger.tasks if task.role == "material_items"
    ).artifact_sha256


def test_missing_response_is_failure_not_no_content_or_attempt(tmp_path: Path) -> None:
    value = snapshot()
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    empty = tmp_path / "responses"
    empty.mkdir()
    checked = replay_batch(plan, responses=empty, store_root=tmp_path / "store")
    items = next(task for task in checked.ledger.tasks if task.role == "material_items")
    assert items.execution_status == "failed"
    assert checked.ledger.attempts == ()
    assert items.quality_status != "accepted"


def test_root_is_required_and_relative_paths_are_rejected() -> None:
    plan = plan_batch(snapshot())
    with pytest.raises(StructuredExecutionError, match="CS_STORE_ROOT_REQUIRED"):
        check_batch(plan.batch_id, store_root=None)
    with pytest.raises(StructuredExecutionError, match="CS_PATH_OUTSIDE_ROOT"):
        check_batch(plan.batch_id, store_root=Path("relative"))


def test_store_index_and_object_symlink_escapes_are_rejected(tmp_path: Path) -> None:
    value = snapshot()
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    outside = tmp_path / "outside"
    outside.mkdir()
    index_root = tmp_path / "index-root"
    index_root.mkdir()
    (index_root / "index").symlink_to(outside, target_is_directory=True)
    with pytest.raises(StructuredExecutionError, match="CS_PATH_OUTSIDE_ROOT"):
        ExecutionJournal.open(plan, index_root)

    object_root = tmp_path / "object-root"
    journal = ExecutionJournal.open(plan, object_root)
    journal.close()
    (object_root / "objects").symlink_to(outside, target_is_directory=True)
    responses = tmp_path / "responses"
    replay_fixture(value, plan, responses)
    with pytest.raises(StructuredExecutionError, match="CS_PATH_OUTSIDE_ROOT"):
        replay_batch(plan, responses=responses, store_root=object_root)


def test_sqlite_uses_wal_foreign_keys_and_full_sync(tmp_path: Path) -> None:
    plan = plan_batch(snapshot())
    journal = ExecutionJournal.open(plan, tmp_path / "store")
    assert journal.connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    assert journal.connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
    assert journal.connection.execute("PRAGMA synchronous").fetchone()[0] == 2
    journal.close()
    mode = (tmp_path / "store" / "index" / "structured.sqlite3").stat().st_mode & 0o777
    assert mode == 0o600


def test_unknown_or_corrupt_ledger_schema_fails_with_distinct_contract_errors(
    tmp_path: Path,
) -> None:
    plan = plan_batch(snapshot())
    unknown_root = tmp_path / "unknown"
    journal = ExecutionJournal.open(plan, unknown_root)
    journal.connection.execute("UPDATE ledger_metadata SET value='999' WHERE key='schema_version'")
    journal.close()
    with pytest.raises(StructuredExecutionError, match="CS_SCHEMA_UNSUPPORTED"):
        check_batch(plan.batch_id, store_root=unknown_root)

    corrupt_root = tmp_path / "corrupt"
    database = corrupt_root / "index" / "structured.sqlite3"
    database.parent.mkdir(parents=True)
    database.write_bytes(b"not a sqlite database")
    with pytest.raises(StructuredExecutionError, match="CS_ARTIFACT_CORRUPT"):
        check_batch(plan.batch_id, store_root=corrupt_root)


def test_corrupt_response_object_is_detected_before_resume(tmp_path: Path) -> None:
    class Crash(BaseException):
        pass

    value = snapshot()
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    responses = tmp_path / "responses"
    replay_fixture(value, plan, responses)
    root = tmp_path / "store"

    def crash(name: str) -> None:
        if name == "after_response_commit":
            raise Crash

    with pytest.raises(Crash):
        replay_batch(plan, responses=responses, store_root=root, checkpoint=crash)
    connection = sqlite3.connect(root / "index" / "structured.sqlite3")
    object_sha = connection.execute("SELECT response_object_sha256 FROM attempts").fetchone()[0]
    connection.close()
    digest = object_sha[7:]
    (root / "objects" / "sha256" / digest[:2] / f"{digest}.json").write_text("{}", encoding="utf-8")
    with pytest.raises(StructuredExecutionError, match="CS_ARTIFACT_CORRUPT"):
        replay_batch(plan, responses=responses, store_root=root)


def test_live_adapter_sends_once_and_every_request_has_one_attempt(tmp_path: Path) -> None:
    value = snapshot()
    config = extraction_config()
    plan = plan_batch(
        value,
        config=config,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    calls: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request)
        return httpx.Response(
            200,
            json={
                "model": "synthetic-provider-model",
                "choices": [{"message": {"content": item_content(value)}, "finish_reason": "stop"}],
                "usage": {
                    "prompt_tokens": 11,
                    "completion_tokens": 7,
                    "total_tokens": 18,
                },
            },
        )

    root = tmp_path / "store"
    checked = execute_batch(
        plan,
        store_root=root,
        allow_model=True,
        config=config,
        transport_factories={"material_items": lambda: httpx.MockTransport(handler)},
    )
    assert len(calls) == 1
    assert len(checked.ledger.attempts) == 1
    attempt = checked.ledger.attempts[0]
    assert attempt.execution_status == "succeeded"
    assert attempt.provider == "openai_compat"
    assert attempt.request_model == "synthetic-model"
    assert attempt.response_model == "synthetic-provider-model"
    assert calls[0].headers["idempotency-key"] == attempt.attempt_id
    assert attempt.usage == {
        "completion_tokens": 7,
        "prompt_tokens": 11,
        "reasoning_tokens": None,
        "total_tokens": 18,
    }
    assert checked.plan_consistent

    connection = sqlite3.connect(root / "index" / "structured.sqlite3")
    diagnostics = json.loads(
        connection.execute(
            "SELECT diagnostics FROM attempts WHERE batch_id=? AND attempt_id=?",
            (plan.batch_id, attempt.attempt_id),
        ).fetchone()[0]
    )
    diagnostics["provider"] = "replay"
    connection.execute(
        "UPDATE attempts SET provider=?, diagnostics=? WHERE batch_id=? AND attempt_id=?",
        ("replay", json.dumps(diagnostics), plan.batch_id, attempt.attempt_id),
    )
    connection.commit()
    connection.close()

    tampered = check_batch(plan.batch_id, store_root=root)
    assert not tampered.plan_consistent
    assert f"attempt_provider_model_mismatch:{attempt.attempt_id}" in tampered.findings
    assert f"response_binding_mismatch:{attempt.attempt_id}" in tampered.findings


def test_transport_unknown_outcome_is_not_automatically_resent(tmp_path: Path) -> None:
    value = snapshot()
    config = extraction_config()
    plan = plan_batch(
        value,
        config=config,
        max_attempts=2,
        role_max_attempts={"claims": 0, "material_items": 2, "material_relations": 0},
        relations_enabled=False,
    )
    sends = 0

    def handler(_request: httpx.Request) -> httpx.Response:
        nonlocal sends
        sends += 1
        raise httpx.ReadError("synthetic uncertain send")

    kwargs = {
        "store_root": tmp_path / "store",
        "allow_model": True,
        "config": config,
        "transport_factories": {"material_items": lambda: httpx.MockTransport(handler)},
    }
    first = execute_batch(plan, **kwargs)
    second = execute_batch(plan, **kwargs)
    assert sends == 1
    assert len(first.ledger.attempts) == len(second.ledger.attempts) == 1
    assert second.ledger.attempts[0].execution_status == "outcome_unknown"
    items = next(task for task in second.ledger.tasks if task.role == "material_items")
    assert items.execution_status == "outcome_unknown"
    assert items.error_codes == ("CS_OUTCOME_UNKNOWN",)


def test_missing_config_blocks_model_before_request_but_not_deterministic_task(
    tmp_path: Path,
) -> None:
    plan = plan_batch(snapshot(), max_attempts=1)
    checked = execute_batch(
        plan,
        store_root=tmp_path / "store",
        allow_model=True,
        config=load_extraction_config(environ={}),
    )
    assert checked.ledger.attempts == ()
    claims = next(task for task in checked.ledger.tasks if task.role == "claims")
    items = next(task for task in checked.ledger.tasks if task.role == "material_items")
    assert claims.execution_status == "succeeded"
    assert items.execution_status == "blocked"
    assert items.error_codes == ("CS_CONFIG_MISSING",)


def test_budget_dependency_relation_closure_and_deadline_states_are_distinct(
    tmp_path: Path,
) -> None:
    value = snapshot()

    budget_plan = plan_batch(
        value,
        max_attempts=0,
        role_max_attempts={"claims": 0, "material_items": 0, "material_relations": 0},
    )
    responses = tmp_path / "budget-responses"
    replay_fixture(value, budget_plan, responses)
    budget = replay_batch(budget_plan, responses=responses, store_root=tmp_path / "budget-store")
    budget_items = next(task for task in budget.ledger.tasks if task.role == "material_items")
    assert budget_items.execution_status == "blocked"
    assert budget_items.error_codes == ("CS_BUDGET_EXHAUSTED",)
    assert set(budget.derivations.values()) == {"dependency_not_ready:CS_DEPENDENCY_NOT_READY"}

    relation_plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        max_relation_tasks=0,
    )
    relation_responses = tmp_path / "relation-responses"
    replay_fixture(value, relation_plan, relation_responses)
    relation = replay_batch(
        relation_plan,
        responses=relation_responses,
        store_root=tmp_path / "relation-store",
    )
    assert set(relation.derivations.values()) == {"budget_exhausted:CS_BUDGET_EXHAUSTED"}

    deadline_plan = plan_batch(value, max_attempts=1, deadline_epoch=0)
    deadline_responses = tmp_path / "deadline-responses"
    replay_fixture(value, deadline_plan, deadline_responses)
    deadline = replay_batch(
        deadline_plan,
        responses=deadline_responses,
        store_root=tmp_path / "deadline-store",
    )
    assert {task.execution_status for task in deadline.ledger.tasks} == {"cancelled"}
    assert deadline.ledger.attempts == ()


def test_explicit_operator_cancellation_does_not_release_or_send_budget(tmp_path: Path) -> None:
    value = snapshot()
    plan = plan_batch(value, max_attempts=1, relations_enabled=False)
    root = tmp_path / "store"
    journal = ExecutionJournal.open(plan, root)
    journal.close()
    cancel_batch(plan.batch_id, store_root=root)
    responses = tmp_path / "responses"
    replay_fixture(value, plan, responses)
    checked = replay_batch(plan, responses=responses, store_root=root)
    assert {task.execution_status for task in checked.ledger.tasks} == {"cancelled"}
    assert checked.ledger.budget.reserved_attempts == 0
    assert checked.ledger.attempts == ()


def test_role_profiles_and_costs_are_separate_and_unknown_is_not_zero(tmp_path: Path) -> None:
    value = snapshot(dual_model_roles=True)
    claims_config = extraction_config("claims-model")
    items_config = extraction_config("items-model")
    plan = plan_batch(
        value,
        config=items_config,
        role_configs={"claims": claims_config},
        max_attempts=3,
        role_max_attempts={"claims": 1, "material_items": 2, "material_relations": 0},
        relations_enabled=False,
    )
    profiles = {profile.role: profile for profile in plan.profiles}
    assert profiles["claims"].model == "claims-model"
    assert profiles["material_items"].model == "items-model"
    assert profiles["claims"].profile_sha256 != profiles["material_items"].profile_sha256

    document = evidence_document_from_snapshot(value, role="material_items")
    structure = build_material_structure(document)
    slots = build_candidate_slots(document, structure)
    by_packet: dict[str, list] = {}
    for slot in slots:
        by_packet.setdefault(slot.packet_id, []).append(slot)
    speaker_id = "spk_" + fingerprint([None, "document_voice", "unknown"])[:12]

    def rows(packet_slots) -> str:
        result = []
        for index, slot in enumerate(packet_slots):
            forecast = "预计" in slot.text
            result.append(
                {
                    "record_type": "item",
                    "candidate_slot_id": slot.candidate_slot_id,
                    "item_id": f"item-{slot.candidate_slot_id}-{index}",
                    "text": slot.text,
                    "semantic_type": "forecast" if forecast else "opinion",
                    "statement_role": "claim",
                    "speech_role": "statement",
                    "perspective": "source_explicit",
                    "speaker_ref": speaker_id,
                    "polarity": "affirmed",
                    "value": "15亿元" if forecast else None,
                    "behavior_status": None,
                    "temporal_frame": "future" if forecast else "contemporaneous",
                    "evidence_quote": slot.text,
                    "unknown_fields": [],
                }
            )
        return "\n".join(json.dumps(row, ensure_ascii=False) for row in result)

    responses = tmp_path / "responses"
    claims_task = next(
        task for task in plan.tasks if task.role == "claims" and task.method == "model"
    )
    write_response(
        responses,
        ReplayResponse(
            task_id=claims_task.task_id,
            sequence=1,
            role="claims",
            protocol=claims_task.protocol,
            content="[]",
            diagnostics={
                "cost": {
                    "amount": 0.25,
                    "currency": "USD",
                    "kind": "estimated",
                    "price_version": "synthetic-v1",
                }
            },
        ),
        "claims",
    )
    items_task = next(task for task in plan.tasks if task.role == "material_items")
    for sequence, packet_slots in enumerate(by_packet.values(), 1):
        write_response(
            responses,
            ReplayResponse(
                task_id=items_task.task_id,
                sequence=sequence,
                role="material_items",
                protocol=items_task.protocol,
                content=rows(packet_slots),
                diagnostics=(
                    {
                        "cost": {
                            "amount": 2.0,
                            "currency": "CNY",
                            "kind": "provider_reported",
                            "price_version": "synthetic-v2",
                        }
                    }
                    if sequence == 1
                    else {"cost": None}
                ),
            ),
            f"items-{sequence}",
        )
    checked = replay_batch(plan, responses=responses, store_root=tmp_path / "store")
    assert checked.ledger.budget.actual_attempts == 3
    assert {attempt.request_model for attempt in checked.ledger.attempts} == {
        "claims-model",
        "items-model",
    }
    assert any(
        attempt.cost and attempt.cost.get("price_version") == "synthetic-v2"
        for attempt in checked.ledger.attempts
    )
    claims_costs = [summary for summary in checked.cost_summary if summary.model == "claims-model"]
    items_costs = [summary for summary in checked.cost_summary if summary.model == "items-model"]
    assert any(
        summary.currency == "USD" and summary.known_amount == 0.25 for summary in claims_costs
    )
    assert any(summary.currency == "CNY" and summary.known_amount == 2.0 for summary in items_costs)
    assert any(
        summary.kind == "provider_reported" and summary.price_version == "synthetic-v2"
        for summary in items_costs
    )
    assert any(summary.currency is None and summary.unknown_calls == 1 for summary in items_costs)


def test_check_reconciles_frozen_task_attempt_artifact_and_role_budget_bindings(
    tmp_path: Path,
) -> None:
    value = snapshot()
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    responses = tmp_path / "responses"
    replay_fixture(value, plan, responses)
    root = tmp_path / "store"
    clean = replay_batch(plan, responses=responses, store_root=root)
    assert clean.plan_consistent

    database = root / "index" / "structured.sqlite3"
    connection = sqlite3.connect(database)
    material_task = next(task for task in clean.ledger.tasks if task.role == "material_items")
    attempt = clean.ledger.attempts[0]
    connection.execute(
        "UPDATE tasks SET protocol='tampered-protocol', artifact_id='tampered' WHERE task_id=?",
        (material_task.task_id,),
    )
    connection.execute(
        "UPDATE attempts SET attempt_id='attempt:tampered', request_model='tampered-model' "
        "WHERE attempt_id=?",
        (attempt.attempt_id,),
    )
    connection.execute(
        "UPDATE role_budgets SET max_attempts=99 WHERE batch_id=? AND role='material_items'",
        (plan.batch_id,),
    )
    connection.commit()
    connection.close()

    checked = check_batch(plan.batch_id, store_root=root)
    assert not checked.plan_consistent
    assert f"planned_task_binding_mismatch:{material_task.task_id}" in checked.findings
    assert "attempt_identity_mismatch:attempt:tampered" in checked.findings
    assert "attempt_provider_model_mismatch:attempt:tampered" in checked.findings
    assert f"artifact_binding_mismatch:{material_task.task_id}" in checked.findings
    assert "role_budget_plan_mismatch:material_items" in checked.findings


def test_check_rejects_hash_consistent_wrong_business_payload(tmp_path: Path) -> None:
    value = snapshot()
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    responses = tmp_path / "responses"
    replay_fixture(value, plan, responses)
    root = tmp_path / "store"
    clean = replay_batch(plan, responses=responses, store_root=root)
    task = next(task for task in clean.ledger.tasks if task.role == "material_items")

    connection = sqlite3.connect(root / "index" / "structured.sqlite3")
    row = connection.execute(
        "SELECT artifact_sha256 FROM tasks WHERE batch_id=? AND task_id=?",
        (plan.batch_id, task.task_id),
    ).fetchone()
    assert row is not None
    artifact = RoleArtifact.model_validate(_read_object(root, row[0]))
    invalid_payload = {"run_id": "hash-consistent-but-not-a-material-run"}
    payload_sha = canonical_hash(invalid_payload)
    forged = artifact.model_copy(update={"artifact_id": "pending", "payload_sha256": payload_sha})
    forged = forged.model_copy(
        update={
            "artifact_id": canonical_hash(forged.model_dump(mode="json", exclude={"artifact_id"}))
        }
    )
    forged.verify_identity()
    payload_object = _write_object(root, invalid_payload)
    artifact_object = _write_object(root, forged.model_dump(mode="json"))
    connection.execute(
        "UPDATE tasks SET artifact_sha256=?, artifact_id=?, payload_sha256=?, "
        "payload_object_sha256=? WHERE batch_id=? AND task_id=?",
        (
            artifact_object,
            forged.artifact_id,
            payload_sha,
            payload_object,
            plan.batch_id,
            task.task_id,
        ),
    )
    connection.commit()
    connection.close()

    checked = check_batch(plan.batch_id, store_root=root)
    assert not checked.plan_consistent
    assert f"artifact_binding_mismatch:{task.task_id}" in checked.findings


def test_relation_task_is_registered_before_request_and_resume_deduplicates(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value = dialogue_snapshot()
    plan = plan_batch(
        value,
        max_attempts=2,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 1},
        max_relation_tasks=1,
        max_relation_attempts=1,
    )
    items_task = next(task for task in plan.tasks if task.role == "material_items")
    content = dialogue_item_content(value)
    items_execution = execute_material_items_role(
        value,
        task_id=items_task.task_id,
        protocol=items_task.protocol,
        llm=lambda _prompt: content,
        max_calls=1,
    )
    assert items_execution.artifact.quality_status == "accepted"
    endpoints = tuple(item.item_id for item in items_execution.payload.understanding.items)
    candidates = build_relation_candidate_set(
        value,
        items_execution.payload,
        endpoint_item_ids=endpoints,
        items_validation_version=plan.relations.items_validation_version,
        rule_version=plan.relations.rule_version,
    )
    assert candidates.candidates
    responses = tmp_path / "responses"
    write_response(
        responses,
        ReplayResponse(
            task_id=items_task.task_id,
            sequence=1,
            role="material_items",
            protocol=items_task.protocol,
            content=content,
        ),
        "items",
    )
    relation_content = "\n".join(
        json.dumps(
            {
                "record_type": "relation_decision",
                "candidate_pair_id": candidate.candidate_pair_id,
                "status": "absent",
                "evidence_quote": None,
            },
            ensure_ascii=False,
        )
        for candidate in candidates.candidates
    )
    write_response(
        responses,
        ReplayResponse(
            parent_task_id=items_task.task_id,
            sequence=1,
            role="material_relations",
            protocol="material-relations-jsonl-v1",
            content=relation_content,
        ),
        "relations",
    )
    root = tmp_path / "store"
    original_get = ReplayDirectory.get

    def assert_registered(
        source: ReplayDirectory, request: RoleRequest, *, parent_task_id: str | None = None
    ):
        if request.role == "material_relations":
            connection = sqlite3.connect(root / "index" / "structured.sqlite3")
            row = connection.execute(
                "SELECT derived, execution_status FROM tasks WHERE task_id=?",
                (request.task_id,),
            ).fetchone()
            derivation = connection.execute(
                "SELECT derived_task_id, status FROM derivations WHERE parent_task_id=?",
                (items_task.task_id,),
            ).fetchone()
            connection.close()
            assert row == (1, "ready")
            assert derivation == (request.task_id, "registered")
        return original_get(source, request, parent_task_id=parent_task_id)

    monkeypatch.setattr(ReplayDirectory, "get", assert_registered)
    first = replay_batch(plan, responses=responses, store_root=root)
    second = replay_batch(plan, responses=responses, store_root=root)
    assert len(first.ledger.tasks) == len(second.ledger.tasks) == 2
    assert len(first.ledger.attempts) == len(second.ledger.attempts) == 2
    relation_task = next(task for task in second.ledger.tasks if task.role == "material_relations")
    assert relation_task.task_id.startswith("task:")
    assert relation_task.execution_status == "succeeded"
    assert set(second.derivations.values()) == {"succeeded"}


def test_relation_task_uses_extracted_endpoints_from_partial_items_run(tmp_path: Path) -> None:
    value = dialogue_snapshot()
    plan = plan_batch(
        value,
        max_attempts=2,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 1},
        max_relation_tasks=1,
        max_relation_attempts=1,
    )
    items_task = next(task for task in plan.tasks if task.role == "material_items")
    content = dialogue_item_content(value) + "\n" + json.dumps(
        {
            "record_type": "item",
            "candidate_slot_id": "slot_nonexistent",
            "item_id": "discarded-malformed-item",
            "text": "无法验证的额外输出",
        },
        ensure_ascii=False,
    )
    items_execution = execute_material_items_role(
        value,
        task_id=items_task.task_id,
        protocol=items_task.protocol,
        llm=lambda _prompt: content,
        max_calls=1,
    )
    assert items_execution.artifact.execution_status == "succeeded"
    assert items_execution.artifact.protocol_status == "invalid"
    assert items_execution.artifact.quality_status == "review_required"
    qualified_endpoints = tuple(
        item_ref
        for entry in items_execution.payload.understanding.coverage.slot_ledger
        if entry.status == "extracted"
        for item_ref in entry.item_refs
    )
    assert len(qualified_endpoints) == 2
    candidates = build_relation_candidate_set(
        value,
        items_execution.payload,
        endpoint_item_ids=qualified_endpoints,
        items_validation_version=plan.relations.items_validation_version,
        rule_version=plan.relations.rule_version,
    )
    assert candidates.candidates

    responses = tmp_path / "responses"
    write_response(
        responses,
        ReplayResponse(
            task_id=items_task.task_id,
            sequence=1,
            role="material_items",
            protocol=items_task.protocol,
            content=content,
        ),
        "items",
    )
    relation_content = "\n".join(
        json.dumps(
            {
                "record_type": "relation_decision",
                "candidate_pair_id": candidate.candidate_pair_id,
                "status": "absent",
                "evidence_quote": None,
            },
            ensure_ascii=False,
        )
        for candidate in candidates.candidates
    )
    write_response(
        responses,
        ReplayResponse(
            parent_task_id=items_task.task_id,
            sequence=1,
            role="material_relations",
            protocol="material-relations-jsonl-v1",
            content=relation_content,
        ),
        "relations",
    )

    result = replay_batch(plan, responses=responses, store_root=tmp_path / "store")
    relation_task = next(task for task in result.ledger.tasks if task.role == "material_relations")
    assert relation_task.endpoint_item_ids == qualified_endpoints
    assert relation_task.execution_status == "succeeded"
    assert set(result.derivations.values()) == {"succeeded"}


def test_concurrent_relation_derivation_registers_one_logical_task(tmp_path: Path) -> None:
    value = dialogue_snapshot()
    plan = plan_batch(
        value,
        max_attempts=2,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 1},
        max_relation_tasks=1,
        max_relation_attempts=1,
    )
    parent = next(task for task in plan.tasks if task.role == "material_items")
    items = execute_material_items_role(
        value,
        task_id=parent.task_id,
        protocol=parent.protocol,
        llm=lambda _prompt: dialogue_item_content(value),
        max_calls=1,
    )
    root = tmp_path / "store"
    setup = ExecutionJournal.open(plan, root)
    setup.save_execution(parent, items)
    setup.close()

    def derive(_index: int) -> str:
        journal = ExecutionJournal.open(plan, root)
        try:
            task = journal.derive_relation_task(parent)
            assert task is not None
            return task.task_id
        finally:
            journal.close()

    with ThreadPoolExecutor(max_workers=2) as pool:
        task_ids = list(pool.map(derive, range(2)))
    assert len(set(task_ids)) == 1
    checked = check_batch(plan.batch_id, store_root=root)
    assert len([task for task in checked.ledger.tasks if task.role == "material_relations"]) == 1
    assert set(checked.derivations.values()) == {"registered"}


def test_single_runner_lease_rejects_parallel_batch_execution(tmp_path: Path) -> None:
    value = snapshot()
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    responses = tmp_path / "responses"
    replay_fixture(value, plan, responses)
    root = tmp_path / "store"
    reserved = threading.Event()
    release = threading.Event()
    errors: list[BaseException] = []

    def checkpoint(name: str) -> None:
        if name == "after_reserve":
            reserved.set()
            assert release.wait(timeout=5)

    def run_first() -> None:
        try:
            replay_batch(plan, responses=responses, store_root=root, checkpoint=checkpoint)
        except BaseException as exc:
            errors.append(exc)

    worker = threading.Thread(target=run_first)
    worker.start()
    assert reserved.wait(timeout=5)
    with pytest.raises(StructuredExecutionError, match="CS_DEPENDENCY_NOT_READY"):
        replay_batch(plan, responses=responses, store_root=root)
    release.set()
    worker.join(timeout=5)
    assert not worker.is_alive()
    assert errors == []
    checked = check_batch(plan.batch_id, store_root=root)
    assert len(checked.ledger.attempts) == 1
