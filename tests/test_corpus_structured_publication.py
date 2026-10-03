"""Semantic publication versioning, conflict propagation, and race tests."""

from __future__ import annotations

import json
import socket
import sqlite3
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import dotenv
import dotenv.main
import httpx
import pytest
from _corpus_structured_subprocess import finish_process, isolated_process, run_isolated
from test_corpus_structured_execution import (
    BUILD_ID,
    SOURCE_ID,
    Reader,
    dialogue_item_content,
    dialogue_snapshot,
    extraction_config,
    snapshot,
    write_response,
)
from test_corpus_structured_store import prepared

from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.material_semantics import (
    build_candidate_slots,
    build_material_structure,
    build_relation_candidate_set,
)
from plugins.corpus.service import CorpusService
from plugins.corpus.structured.ledger import (
    ReplayResponse,
    StructuredExecutionError,
    plan_batch,
    replay_batch,
)
from plugins.corpus.structured.roles import execute_material_items_role
from plugins.corpus.structured.snapshot import (
    SnapshotBuildSource,
    SnapshotDocumentSource,
    SnapshotHead,
    SnapshotUnitSource,
    build_snapshot,
)
from plugins.corpus.structured.store import (
    ArtifactReference,
    CrossRoleMapping,
    _auto_mappings,
    _RecordEvidence,
    publish_semantic,
    read_semantic,
    retire_semantic,
)


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("publication tests must not access network, models, or production DB")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(dotenv, "load_dotenv", denied)
    monkeypatch.setattr(dotenv.main, "load_dotenv", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(CorpusService, "_connect", denied)


def forecast_snapshot(*, build_id: str = BUILD_ID):
    head = SnapshotHead(source_id=SOURCE_ID, build_id=build_id, publication_generation=1)
    return build_snapshot(
        Reader(
            SnapshotBuildSource(
                head=head,
                parser_versions={"parse": "p1", "clean": "c1", "chunk": "k1"},
                document=SnapshotDocumentSource(
                    title="合成预测", subject="999999.SZ", published="2026-01-01"
                ),
                units=(
                    SnapshotUnitSource(
                        source_unit_id="forecast-u",
                        chunk_id="forecast-c",
                        kind="prose",
                        text="999999.SZ 2026年营业收入15亿元。",
                        locator="page:1/paragraph:1",
                        ordinal=1,
                    ),
                ),
            )
        ),
        SOURCE_ID,
    )


def forecast_artifacts(
    tmp_path: Path, *, build_id: str = BUILD_ID, item_overrides: dict | None = None
):
    value = forecast_snapshot(build_id=build_id)
    plan = plan_batch(
        value,
        max_attempts=2,
        role_max_attempts={"claims": 1, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    responses = tmp_path / f"responses-{build_id[:8]}"
    document = evidence_document_from_snapshot(value, role="material_items")
    slots = build_candidate_slots(document, build_material_structure(document))
    assert len(slots) == 1
    slot = slots[0]
    speaker = "spk_" + fingerprint([None, "document_voice", "unknown"])[:12]
    for task in plan.tasks:
        if task.role == "claims":
            content = json.dumps(
                [
                    {
                        "claim_text": slot.text,
                        "evidence_quote": slot.text,
                        "evidence_kind": "prose",
                        "scope": "company",
                        "subject": "999999.SZ",
                        "metric": "营业收入",
                        "value_text": "15",
                        "unit_raw": "亿元",
                        "period_raw": "2026年",
                        "kind": "fact",
                    }
                ],
                ensure_ascii=False,
            )
        else:
            content = json.dumps(
                {
                    "record_type": "item",
                    "candidate_slot_id": slot.candidate_slot_id,
                    "item_id": "local-forecast",
                    "text": slot.text,
                    "semantic_type": "fact",
                    "statement_role": "claim",
                    "speech_role": "statement",
                    "perspective": "source_explicit",
                    "speaker_ref": speaker,
                    "polarity": "affirmed",
                    "value": "16亿元",
                    "behavior_status": None,
                    "temporal_frame": "contemporaneous",
                    "evidence_quote": slot.text,
                    "unknown_fields": [],
                    **(item_overrides or {}),
                },
                ensure_ascii=False,
            )
        write_response(
            responses,
            ReplayResponse(
                task_id=task.task_id,
                sequence=1,
                role=task.role,
                protocol=task.protocol,
                content=content,
            ),
            task.role,
        )
    root = tmp_path / "store"
    checked = replay_batch(plan, responses=responses, store_root=root)
    references = {
        task.role: ArtifactReference(
            batch_id=plan.batch_id,
            task_id=task.task_id,
            artifact_sha256=task.artifact_sha256,
        )
        for task in checked.ledger.tasks
        if task.artifact_sha256 is not None
    }
    return value, plan, root, references, checked


@pytest.mark.parametrize(
    ("overrides", "status", "fields"),
    [
        ({"value": None, "polarity": "negated"}, "conflict", ("polarity",)),
        ({"value": "15亿元"}, "confirmed", ()),
        ({"value": "150000万元"}, "confirmed", ()),
        ({"value": "15%"}, "conflict", ("unit",)),
        ({"value": "大约15亿元"}, "suspected", ()),
        ({"value": "15亿元", "semantic_type": "forecast"}, "conflict", ("factuality",)),
        ({"value": "15亿元", "statement_role": "condition"}, "conflict", ("condition",)),
        ({"value": None}, "suspected", ()),
        ({"value": "15"}, "suspected", ()),
        ({"value": "15亿元", "unknown_fields": ["value"]}, "suspected", ()),
        ({"text": "999999.SZ 2026年营业收入16亿元。"}, "conflict", ("value",)),
        ({"text": "888888.SZ 2026年营业收入15亿元。", "value": "15亿元"}, "suspected", ()),
        (
            {"text": "999999.SZ 2026年营业收入15亿元。另一家公司利润下降。", "value": "15亿元"},
            "suspected",
            (),
        ),
    ],
)
def test_cross_role_comparison_preserves_semantics(tmp_path, overrides, status, fields):
    value, _plan, root, references, _checked = forecast_artifacts(
        tmp_path, item_overrides=overrides
    )
    manifest = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references["claims"], references["material_items"]),
        expected_parent_publication_id=None,
        store_root=root,
    )
    assert [(m.mapping_status, m.conflict_fields) for m in manifest.mappings] == [(status, fields)]
    view = read_semantic(value.source_id, value.build_id, store_root=root)
    purposes = next(iter(view.effective_claim_purposes.values()))
    assert ("calculate" in purposes) == (status != "conflict")
    if status == "suspected":
        assert "CROSS_ROLE_COMPARISON_UNPROVEN" in manifest.reason_codes
        forced = CrossRoleMapping.model_validate(
            {**manifest.mappings[0].model_dump(), "mapping_status": "confirmed"}
        )
        with pytest.raises(
            StructuredExecutionError, match=r"mapping_.*unproven|mapping_comparison_incomplete"
        ):
            publish_semantic(
                source_id=value.source_id,
                build_id=value.build_id,
                snapshot_id=value.snapshot_id,
                artifacts=(references["claims"], references["material_items"]),
                expected_parent_publication_id=manifest.publication_id,
                mappings=(forced,),
                store_root=root,
            )


def test_claims_p1_then_late_r2_conflict_p2_tightens_purposes(tmp_path: Path) -> None:
    value, _plan, root, references, checked = forecast_artifacts(tmp_path)
    assert {(task.role, task.quality_status) for task in checked.ledger.tasks} == {
        ("claims", "accepted"),
        ("material_items", "accepted"),
    }
    p1 = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references["claims"],),
        expected_parent_publication_id=None,
        store_root=root,
    )
    p1_view = read_semantic(value.source_id, value.build_id, store_root=root)
    fact_id = next(iter(p1_view.effective_claim_purposes))
    assert "calculate" in p1_view.effective_claim_purposes[fact_id]

    p2 = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references["claims"], references["material_items"]),
        expected_parent_publication_id=p1.publication_id,
        store_root=root,
    )
    assert p2.generation == 2
    assert p2.parent_publication_id == p1.publication_id
    assert [mapping.mapping_status for mapping in p2.mappings] == ["conflict"]
    assert p2.mappings[0].conflict_fields == ("value",)
    p2_view = read_semantic(value.source_id, value.build_id, store_root=root)
    assert p2_view.effective_claim_purposes[fact_id] == ("cite",)
    historical = read_semantic(
        value.source_id,
        value.build_id,
        publication_id=p1.publication_id,
        allow_historical=True,
        store_root=root,
    )
    assert "calculate" in historical.effective_claim_purposes[fact_id]


def test_cross_role_mapping_does_not_merge_same_locator_distinct_propositions() -> None:
    first = _RecordEvidence(
        frozenset({"same-unit"}),
        frozenset({("chunk:same", 0, 8)}),
        "甲公司收入增长",
    )
    second = _RecordEvidence(
        frozenset({"same-unit"}),
        frozenset({("chunk:same", 10, 18)}),
        "乙公司利润下降",
    )
    item = _RecordEvidence(
        frozenset({"same-unit"}),
        frozenset({("chunk:same", 10, 18)}),
        "乙公司利润下降",
    )
    mappings = _auto_mappings({"fact-a": first, "fact-b": second}, {"item-b": item})
    by_fact = {mapping.claim_fact_id: mapping for mapping in mappings if mapping.claim_fact_id}
    assert by_fact["fact-a"].mapping_status == "unlinked"
    # These records have no subject/metric/period binding: equal text is not enough.
    assert by_fact["fact-b"].mapping_status == "suspected"


def test_actual_rule_upgrade_preserves_legacy_history(tmp_path, monkeypatch):
    import plugins.corpus.structured.store as store

    value, _plan, root, references, _checked = forecast_artifacts(
        tmp_path, item_overrides={"value": "15亿元"}
    )
    with monkeypatch.context() as legacy:
        legacy.setattr(store, "CROSS_ROLE_RULE_VERSION", "cross-role-map-v1")
        p1 = publish_semantic(
            source_id=value.source_id,
            build_id=value.build_id,
            snapshot_id=value.snapshot_id,
            artifacts=tuple(references.values()),
            expected_parent_publication_id=None,
            store_root=root,
        )
        old_view = read_semantic(value.source_id, value.build_id, store_root=root)
    assert p1.mappings[0].conflict_fields == ("value",)
    assert p1.mappings[0].rule_version == "cross-role-map-v1"
    with pytest.raises(StructuredExecutionError, match="publication_rule_upgrade_required"):
        read_semantic(value.source_id, value.build_id, store_root=root)
    p2 = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=tuple(references.values()),
        expected_parent_publication_id=p1.publication_id,
        lifecycle="rule_upgrade",
        store_root=root,
    )
    assert p2.mappings[0].rule_version == "cross-role-map-v2"
    assert p2.mappings[0].mapping_status == "confirmed"
    history = read_semantic(
        value.source_id,
        value.build_id,
        publication_id=p1.publication_id,
        allow_historical=True,
        store_root=root,
    )
    assert history == old_view
    assert "calculate" in next(
        iter(
            read_semantic(
                value.source_id, value.build_id, store_root=root
            ).effective_claim_purposes.values()
        )
    )


def test_head_cache_refreshes_on_publish_and_retirement(tmp_path):
    value, _plan, root, references = prepared(tmp_path)
    parent = None
    for generation in (1, 2):
        manifest = publish_semantic(
            source_id=value.source_id,
            build_id=value.build_id,
            snapshot_id=value.snapshot_id,
            artifacts=(references["material_items"],),
            expected_parent_publication_id=parent,
            store_root=root,
        )
        cache = json.loads(next((root / "cache" / "heads").glob("*.json")).read_text())
        assert cache["generation"] == generation
        assert cache["publication_id"] == manifest.publication_id
        parent = manifest.publication_id
    retired = retire_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        expected_parent_publication_id=parent,
        store_root=root,
    )
    cache = json.loads(next((root / "cache" / "heads").glob("*.json")).read_text())
    assert cache["generation"] == 3
    assert cache["publication_id"] == retired.publication_id


def test_delayed_cache_refresh_uses_latest_committed_head(tmp_path):
    value, _plan, root, references = prepared(tmp_path)

    def publish_next(checkpoint):
        if checkpoint != "after_db_commit":
            return
        p1 = read_semantic(value.source_id, value.build_id, store_root=root).manifest
        publish_semantic(
            source_id=value.source_id,
            build_id=value.build_id,
            snapshot_id=value.snapshot_id,
            artifacts=(references["material_items"],),
            expected_parent_publication_id=p1.publication_id,
            store_root=root,
        )

    publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references["material_items"],),
        expected_parent_publication_id=None,
        store_root=root,
        checkpoint=publish_next,
    )
    current = read_semantic(value.source_id, value.build_id, store_root=root).manifest
    cache = json.loads(next((root / "cache" / "heads").glob("*.json")).read_text())
    assert current.generation == cache["generation"] == 2
    assert current.publication_id == cache["publication_id"]


def test_two_writers_with_same_frozen_parent_have_one_winner(tmp_path: Path) -> None:
    value, _plan, root, references = prepared(tmp_path)

    def submit(_index: int):
        try:
            return publish_semantic(
                source_id=value.source_id,
                build_id=value.build_id,
                snapshot_id=value.snapshot_id,
                artifacts=(references["material_items"],),
                expected_parent_publication_id=None,
                store_root=root,
            )
        except StructuredExecutionError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as pool:
        outcomes = list(pool.map(submit, range(2)))
    assert sum(not isinstance(value, Exception) for value in outcomes) == 1
    error = next(value for value in outcomes if isinstance(value, StructuredExecutionError))
    assert error.code == "CS_PUBLICATION_CONFLICT"
    connection = sqlite3.connect(root / "index" / "structured.sqlite3")
    assert connection.execute("SELECT COUNT(*) FROM semantic_publications").fetchone() == (1,)
    connection.close()


def publication_script(value, reference, checkpoint=""):
    return (
        "import os\nfrom plugins.corpus.structured.store import ArtifactReference, publish_semantic\n"
        "from plugins.corpus.structured.ledger import StructuredExecutionError\n"
        "def checkpoint(name):\n"
        f"    if name == {checkpoint!r}: os._exit(73)\n"
        "try:\n"
        f"    m = publish_semantic(source_id={value.source_id!r}, build_id={value.build_id!r}, "
        f"snapshot_id={value.snapshot_id!r}, artifacts=(ArtifactReference.model_validate_json("
        f"{reference.model_dump_json()!r}),), expected_parent_publication_id=None, "
        "checkpoint=checkpoint)\n"
        "    print(m.publication_id)\n"
        "except StructuredExecutionError as exc:\n"
        "    print(exc.code)\n"
    )


def test_real_process_writers_compare_frozen_parent(tmp_path):
    value, _plan, root, references = prepared(tmp_path)
    script = publication_script(value, references["material_items"])
    processes = [isolated_process(script, cwd=tmp_path, root=root) for _ in range(2)]
    outputs = [finish_process(process).strip() for process in processes]
    assert outputs.count("CS_PUBLICATION_CONFLICT") == 1
    assert sum(output.startswith("sha256:") for output in outputs) == 1
    assert read_semantic(value.source_id, value.build_id, store_root=root).manifest.generation == 1


@pytest.mark.parametrize("checkpoint", ["after_manifest_write", "after_db_commit"])
def test_process_hard_exit_never_exposes_half_publication(tmp_path, checkpoint):
    value, _plan, root, references = prepared(tmp_path)
    run_isolated(
        publication_script(value, references["material_items"], checkpoint),
        cwd=tmp_path,
        root=root,
        expected_code=73,
    )
    if checkpoint == "after_manifest_write":
        with pytest.raises(StructuredExecutionError, match="CS_NOT_PUBLISHED"):
            read_semantic(value.source_id, value.build_id, store_root=root)
        # Orphan manifests are reusable; no head or generation was committed.
        result = run_isolated(
            publication_script(value, references["material_items"]), cwd=tmp_path, root=root
        )
        assert result.startswith("sha256:")
    view = read_semantic(value.source_id, value.build_id, store_root=root)
    assert view.manifest.generation == 1
    assert len(view.artifacts) == 1


def test_crash_before_commit_leaves_orphan_not_head_and_after_commit_head_is_readable(
    tmp_path: Path,
) -> None:
    class Crash(BaseException):
        pass

    value, _plan, root, references = prepared(tmp_path)

    def before(name: str) -> None:
        if name == "after_manifest_write":
            raise Crash

    with pytest.raises(Crash):
        publish_semantic(
            source_id=value.source_id,
            build_id=value.build_id,
            snapshot_id=value.snapshot_id,
            artifacts=(references["material_items"],),
            expected_parent_publication_id=None,
            store_root=root,
            checkpoint=before,
        )
    assert list((root / "manifests").glob("*.json"))
    with pytest.raises(StructuredExecutionError, match="CS_NOT_PUBLISHED"):
        read_semantic(value.source_id, value.build_id, store_root=root)

    def after(name: str) -> None:
        if name == "after_db_commit":
            raise Crash

    with pytest.raises(Crash):
        publish_semantic(
            source_id=value.source_id,
            build_id=value.build_id,
            snapshot_id=value.snapshot_id,
            artifacts=(references["material_items"],),
            expected_parent_publication_id=None,
            store_root=root,
            checkpoint=after,
        )
    view = read_semantic(value.source_id, value.build_id, store_root=root)
    assert view.manifest.generation == 1
    assert not (root / "cache" / "heads").exists()


def test_withdrawal_and_expiration_are_distinct_and_history_remains_reproducible(
    tmp_path: Path,
) -> None:
    value, _plan, root, references = prepared(tmp_path)
    p1 = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references["material_items"],),
        expected_parent_publication_id=None,
        store_root=root,
    )
    retire_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        expected_parent_publication_id=p1.publication_id,
        store_root=root,
    )
    with pytest.raises(StructuredExecutionError, match="publication_withdrawn"):
        read_semantic(value.source_id, value.build_id, store_root=root)
    history = read_semantic(
        value.source_id,
        value.build_id,
        publication_id=p1.publication_id,
        allow_historical=True,
        store_root=root,
    )
    assert history.manifest == p1

    exp_value, _exp_plan, exp_root, exp_references = prepared(tmp_path / "expiry-case")
    exp_p1 = publish_semantic(
        source_id=exp_value.source_id,
        build_id=exp_value.build_id,
        snapshot_id=exp_value.snapshot_id,
        artifacts=(exp_references["material_items"],),
        expected_parent_publication_id=None,
        store_root=exp_root,
    )
    expired = retire_semantic(
        source_id=exp_value.source_id,
        build_id=exp_value.build_id,
        expected_parent_publication_id=exp_p1.publication_id,
        expired=True,
        store_root=exp_root,
    )
    assert expired.generation == 2
    with pytest.raises(StructuredExecutionError, match="publication_expired"):
        read_semantic(exp_value.source_id, exp_value.build_id, store_root=exp_root)


def test_rule_upgrade_source_update_and_failed_new_publish_do_not_replace_history(
    tmp_path: Path,
) -> None:
    value, _plan, root, references = prepared(tmp_path)
    p1 = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references["material_items"],),
        expected_parent_publication_id=None,
        store_root=root,
    )
    upgraded = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references["material_items"],),
        expected_parent_publication_id=p1.publication_id,
        reason_codes=("RULE_REVALIDATED",),
        lifecycle="rule_upgrade",
        store_root=root,
    )
    assert (
        read_semantic(value.source_id, value.build_id, store_root=root).lifecycle == "rule_upgrade"
    )

    new_build = "9" * 64
    new_value, _new_plan, _same_root, new_references, _checked = forecast_artifacts(
        tmp_path, build_id=new_build
    )
    updated = publish_semantic(
        source_id=new_value.source_id,
        build_id=new_value.build_id,
        snapshot_id=new_value.snapshot_id,
        artifacts=(new_references["material_items"],),
        expected_parent_publication_id=None,
        lifecycle="source_update",
        store_root=root,
    )
    assert read_semantic(value.source_id, value.build_id, store_root=root).manifest == upgraded
    assert read_semantic(value.source_id, new_build, store_root=root).manifest == updated

    with pytest.raises(StructuredExecutionError, match="publication_source_binding"):
        publish_semantic(
            source_id=value.source_id,
            build_id="9" * 64,
            snapshot_id=value.snapshot_id,
            artifacts=(references["material_items"],),
            expected_parent_publication_id=None,
            lifecycle="source_update",
            store_root=root,
        )
    assert (
        read_semantic(value.source_id, value.build_id, store_root=root).manifest.publication_id
        == upgraded.publication_id
    )


def test_same_input_different_model_profiles_keep_distinct_artifact_identity(
    tmp_path: Path,
) -> None:
    value = snapshot()
    root = tmp_path / "store"
    references = []
    for index, model in enumerate(("synthetic-a", "synthetic-b")):
        plan = plan_batch(
            value,
            config=extraction_config(model),
            max_attempts=1,
            role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
            relations_enabled=False,
        )
        responses = tmp_path / f"responses-{index}"
        from test_corpus_structured_execution import replay_fixture

        replay_fixture(value, plan, responses)
        checked = replay_batch(plan, responses=responses, store_root=root)
        task = next(task for task in checked.ledger.tasks if task.role == "material_items")
        references.append(
            ArtifactReference(
                batch_id=plan.batch_id,
                task_id=task.task_id,
                artifact_sha256=task.artifact_sha256,
            )
        )
    assert references[0].task_id != references[1].task_id
    assert references[0].artifact_sha256 != references[1].artifact_sha256
    p1 = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references[0],),
        expected_parent_publication_id=None,
        store_root=root,
    )
    p2 = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references[1],),
        expected_parent_publication_id=p1.publication_id,
        store_root=root,
    )
    assert p1.artifacts != p2.artifacts


def relation_artifacts(tmp_path: Path):
    value = dialogue_snapshot()
    plan = plan_batch(
        value,
        max_attempts=2,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 1},
        max_relation_attempts=1,
    )
    items_task = next(task for task in plan.tasks if task.role == "material_items")
    responses = tmp_path / "relation-responses"
    write_response(
        responses,
        ReplayResponse(
            task_id=items_task.task_id,
            sequence=1,
            role="material_items",
            protocol=items_task.protocol,
            content=dialogue_item_content(value),
        ),
        "items",
    )
    items_execution = execute_material_items_role(
        value,
        task_id=items_task.task_id,
        protocol=items_task.protocol,
        llm=lambda _prompt: dialogue_item_content(value),
        max_calls=1,
    )
    endpoints = tuple(item.item_id for item in items_execution.payload.understanding.items)
    candidates = build_relation_candidate_set(
        value,
        items_execution.payload,
        endpoint_item_ids=endpoints,
        items_validation_version=plan.relations.items_validation_version,
        rule_version=plan.relations.rule_version,
    )
    relation_content = "\n".join(
        json.dumps(
            {
                "record_type": "relation_decision",
                "candidate_pair_id": candidate.candidate_pair_id,
                "status": "present",
                "evidence_quote": next(
                    item.evidence[0].quote
                    for item in items_execution.payload.understanding.items
                    if item.item_id == candidate.from_item
                ),
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
    first = replay_batch(plan, responses=responses, store_root=root)
    relation_task = next(task for task in first.ledger.tasks if task.role == "material_relations")
    assert relation_task.quality_status == "accepted"
    reference = ArtifactReference(
        batch_id=plan.batch_id,
        task_id=relation_task.task_id,
        artifact_sha256=relation_task.artifact_sha256,
    )
    items_task = next(task for task in first.ledger.tasks if task.role == "material_items")
    items_reference = ArtifactReference(
        batch_id=plan.batch_id,
        task_id=items_task.task_id,
        artifact_sha256=items_task.artifact_sha256,
    )
    return value, root, items_reference, reference


def test_relation_artifact_cannot_publish_without_its_items_artifact(tmp_path: Path) -> None:
    value, root, _items_reference, reference = relation_artifacts(tmp_path)
    with pytest.raises(StructuredExecutionError, match="relation_upstream_invalid"):
        publish_semantic(
            source_id=value.source_id,
            build_id=value.build_id,
            snapshot_id=value.snapshot_id,
            artifacts=(reference,),
            expected_parent_publication_id=None,
            store_root=root,
        )


def test_replaced_items_do_not_reactivate_old_relations(tmp_path):
    value, root, items_reference, reference = relation_artifacts(tmp_path)
    p1 = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(items_reference, reference),
        expected_parent_publication_id=None,
        store_root=root,
    )
    old = read_semantic(value.source_id, value.build_id, store_root=root)
    assert old.active_relation_ids
    plan = plan_batch(
        value,
        config=extraction_config("replacement-model"),
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    task = next(task for task in plan.tasks if task.role == "material_items")
    responses = tmp_path / "replacement-responses"
    write_response(
        responses,
        ReplayResponse(
            task_id=task.task_id,
            sequence=1,
            role=task.role,
            protocol=task.protocol,
            content=dialogue_item_content(value),
        ),
        "items",
    )
    replayed = replay_batch(plan, responses=responses, store_root=root)
    task = next(task for task in replayed.ledger.tasks if task.role == "material_items")
    replacement = ArtifactReference(
        batch_id=plan.batch_id, task_id=task.task_id, artifact_sha256=task.artifact_sha256
    )
    with pytest.raises(StructuredExecutionError, match="relation_upstream_invalid"):
        publish_semantic(
            source_id=value.source_id,
            build_id=value.build_id,
            snapshot_id=value.snapshot_id,
            artifacts=(replacement, reference),
            expected_parent_publication_id=p1.publication_id,
            store_root=root,
        )
    assert read_semantic(value.source_id, value.build_id, store_root=root) == old
    p2 = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(replacement,),
        expected_parent_publication_id=p1.publication_id,
        store_root=root,
    )
    assert read_semantic(value.source_id, value.build_id, store_root=root).active_relation_ids == ()
    assert (
        read_semantic(
            value.source_id,
            value.build_id,
            publication_id=p1.publication_id,
            allow_historical=True,
            store_root=root,
        )
        == old
    )
    retire_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        expected_parent_publication_id=p2.publication_id,
        store_root=root,
    )
    with pytest.raises(StructuredExecutionError, match="publication_withdrawn"):
        read_semantic(value.source_id, value.build_id, store_root=root)
