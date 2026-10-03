"""Read-only semantic query tests over published synthetic artifacts."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass
from pathlib import Path

import dotenv
import dotenv.main
import httpx
import pytest
from test_corpus_structured_contracts import V1, _load, _validation_errors
from test_corpus_structured_execution import write_response
from test_corpus_structured_publication import forecast_artifacts, relation_artifacts

from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.material_semantics import build_candidate_slots, build_material_structure
from plugins.corpus.service import CorpusService
from plugins.corpus.structured.ledger import ReplayResponse, plan_batch, replay_batch
from plugins.corpus.structured.query import query_semantic
from plugins.corpus.structured.snapshot import (
    SnapshotBuildSource,
    SnapshotDependencySource,
    SnapshotDocumentSource,
    SnapshotHead,
    SnapshotReader,
    SnapshotUnitSource,
    build_snapshot,
)
from plugins.corpus.structured.store import (
    ArtifactReference,
    CrossRoleMapping,
    publish_semantic,
    read_semantic,
    retire_semantic,
)


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("semantic query tests must not access external systems")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(socket.socket, "connect_ex", denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied)
    monkeypatch.setattr(dotenv, "load_dotenv", denied)
    monkeypatch.setattr(dotenv.main, "load_dotenv", denied)
    monkeypatch.setattr(CorpusService, "_connect", denied)


def test_query_returns_exact_published_claim_evidence(tmp_path: Path) -> None:
    value, _plan, root, references, _checked = forecast_artifacts(tmp_path)
    publication = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references["claims"],),
        expected_parent_publication_id=None,
        store_root=root,
    )

    page = query_semantic(
        value.source_id,
        value.build_id,
        purpose="calculate",
        query_text="营业收入",
        store_root=root,
    )

    assert page.publication_id == publication.publication_id
    assert page.page_status == "complete"
    assert len(page.records) == 1
    record = page.records[0]
    assert record.mapping_status == "unlinked"
    assert record.role == "claims"
    assert "calculate" in record.usable_for
    assert record.evidence[0].handle == f"cv2:{value.build_id}#chunk:forecast-c"
    assert record.evidence[0].quote == "999999.SZ 2026年营业收入15亿元。"
    assert (record.evidence[0].start, record.evidence[0].end) == (0, 24)
    assert record.evidence[0].coordinate_system == "unicode_code_points"


@dataclass
class QueryReader(SnapshotReader):
    payload: SnapshotBuildSource

    def read_head(self, source_id: str) -> SnapshotHead:
        assert source_id == self.payload.head.source_id
        return self.payload.head

    def read_build(self, head: SnapshotHead) -> SnapshotBuildSource:
        assert head == self.payload.head
        return self.payload


def published_material_with_condition(
    tmp_path: Path, *, supported: bool = True, extra_units: int = 0
):
    source_id, build_id = "3" * 64, "4" * 64
    snapshot = build_snapshot(
        QueryReader(
            SnapshotBuildSource(
                head=SnapshotHead(source_id=source_id, build_id=build_id, publication_generation=1),
                parser_versions={"parse": "p1", "clean": "c1", "chunk": "k1"},
                document=SnapshotDocumentSource(
                    title="合成条件材料", subject="虚构公司", published="2026-01-01"
                ),
                units=(
                    SnapshotUnitSource(
                        source_unit_id="main-u",
                        chunk_id="query-c",
                        kind="prose",
                        text="虚构公司2026年收入15亿元。",
                        locator="page:1/paragraph:1",
                        ordinal=1,
                        dependencies=(
                            SnapshotDependencySource(
                                kind="condition",
                                target_unit_id="condition-u",
                                target_chunk_id="query-c",
                                required_for=("cite", "compare", "calculate"),
                            ),
                        ),
                    ),
                    SnapshotUnitSource(
                        source_unit_id="condition-u",
                        chunk_id="query-c",
                        kind="prose",
                        text="仅在合成许可获批时成立。",
                        locator="page:1/paragraph:2",
                        ordinal=2,
                    ),
                    *(
                        SnapshotUnitSource(
                            source_unit_id=f"extra-{index}",
                            chunk_id="query-c",
                            kind="prose",
                            text=f"虚构公司项目{index}的2026年收入15亿元。",
                            locator=f"page:1/paragraph:{index + 3}",
                            ordinal=index + 3,
                            dependencies=(
                                SnapshotDependencySource(
                                    kind="condition",
                                    target_unit_id="condition-u",
                                    target_chunk_id="query-c",
                                    required_for=("cite", "compare", "calculate"),
                                ),
                            ),
                        )
                        for index in range(extra_units)
                    ),
                ),
            )
        ),
        source_id,
    )
    plan = plan_batch(
        snapshot,
        max_attempts=extra_units + 2,
        role_max_attempts={"claims": 0, "material_items": extra_units + 2, "material_relations": 0},
        relations_enabled=False,
    )
    task = next(task for task in plan.tasks if task.role == "material_items")
    document = evidence_document_from_snapshot(snapshot, role="material_items")
    slots = build_candidate_slots(document, build_material_structure(document))
    speaker = "spk_" + fingerprint([None, "document_voice", "unknown"])[:12]
    contents = [
        json.dumps(
            {
                "record_type": "item",
                "candidate_slot_id": slot.candidate_slot_id,
                "item_id": f"item-{slot.candidate_slot_id}",
                "text": slot.text,
                "semantic_type": "forecast" if "收入" in slot.text else "fact",
                "statement_role": "claim" if "收入" in slot.text else "condition",
                "speech_role": "statement",
                "perspective": "source_explicit",
                "speaker_ref": speaker,
                "polarity": "affirmed",
                "value": "15亿元" if "收入" in slot.text else None,
                "behavior_status": None,
                "temporal_frame": "forward_looking",
                "evidence_quote": slot.text,
                "unknown_fields": [],
            },
            ensure_ascii=False,
        )
        if supported
        else json.dumps(
            {
                "record_type": "coverage",
                "candidate_slot_id": slot.candidate_slot_id,
                "status": "no_supported_item",
                "reason_codes": ["synthetic_no_support"],
            },
            ensure_ascii=False,
        )
        for slot in slots
    ]
    responses = tmp_path / "responses"
    for sequence, content in enumerate(contents, start=1):
        write_response(
            responses,
            ReplayResponse(
                task_id=task.task_id,
                sequence=sequence,
                role=task.role,
                protocol=task.protocol,
                content=content,
            ),
            f"items-{sequence}",
        )
    root = tmp_path / "store"
    checked = replay_batch(plan, responses=responses, store_root=root)
    task = next(task for task in checked.ledger.tasks if task.role == "material_items")
    assert task.quality_status == "accepted", json.dumps(
        task.model_dump(mode="json"), ensure_ascii=False, indent=2
    )
    reference = ArtifactReference(
        batch_id=plan.batch_id, task_id=task.task_id, artifact_sha256=task.artifact_sha256
    )
    publication = publish_semantic(
        source_id=source_id,
        build_id=build_id,
        snapshot_id=snapshot.snapshot_id,
        artifacts=(reference,),
        expected_parent_publication_id=None,
        store_root=root,
    )
    return snapshot, root, publication


def test_query_delivers_required_condition_even_without_query_term(tmp_path: Path) -> None:
    snapshot, root, _publication = published_material_with_condition(tmp_path)

    page = query_semantic(
        snapshot.source_id, snapshot.build_id, purpose="cite", query_text="收入", store_root=root
    )

    assert len(page.records) == 1
    record = page.records[0]
    assert [proof.quote for proof in record.evidence] == [
        "虚构公司2026年收入15亿元。",
        "仅在合成许可获批时成立。",
    ]
    assert [(dependency.kind, dependency.status) for dependency in record.dependencies] == [
        ("condition", "present")
    ]
    dependency = record.dependencies[0]
    assert record.evidence[dependency.evidence_index].unit_id == "condition-u"
    assert "收入" not in record.evidence[dependency.evidence_index].quote


def test_query_page_matches_frozen_contract(tmp_path: Path) -> None:
    snapshot, root, _publication = published_material_with_condition(tmp_path)

    page = query_semantic(
        snapshot.source_id, snapshot.build_id, purpose="cite", query_text="收入", store_root=root
    )

    schema = _load(V1 / "semantic-query-page.schema.json")
    assert _validation_errors(page.model_dump(mode="json"), schema, schema) == []


def test_cursor_is_deterministic_and_withdrawal_makes_it_stale(tmp_path: Path) -> None:
    snapshot, root, publication = published_material_with_condition(tmp_path)
    first = query_semantic(
        snapshot.source_id, snapshot.build_id, purpose="cite", limit=1, store_root=root
    )

    assert first.page_status == "more_available"
    assert len(first.records) == 1
    assert first.next_cursor is not None
    second = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        limit=1,
        cursor=first.next_cursor,
        store_root=root,
    )
    replayed = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        limit=1,
        cursor=first.next_cursor,
        store_root=root,
    )
    assert second == replayed
    assert second.page_status == "complete"
    assert second.records[0].record_id != first.records[0].record_id

    retire_semantic(
        source_id=snapshot.source_id,
        build_id=snapshot.build_id,
        expected_parent_publication_id=publication.publication_id,
        store_root=root,
    )
    stale = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        limit=1,
        cursor=first.next_cursor,
        store_root=root,
    )
    assert stale.page_status == "cursor_stale"
    assert stale.error_codes == ("CS_CURSOR_STALE",)
    assert stale.records == ()


def test_cursor_rejects_changed_query_or_response_budget(tmp_path: Path) -> None:
    snapshot, root, _publication = published_material_with_condition(tmp_path)
    first = query_semantic(
        snapshot.source_id, snapshot.build_id, purpose="cite", limit=1, store_root=root
    )
    assert first.next_cursor

    changed_query = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        query_text="许可",
        cursor=first.next_cursor,
        store_root=root,
    )
    changed_budget = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        max_chars=5_499,
        cursor=first.next_cursor,
        store_root=root,
    )

    assert changed_query.page_status == changed_budget.page_status == "cursor_stale"
    assert changed_query.error_codes == changed_budget.error_codes == ("CS_CURSOR_STALE",)


def test_query_rejects_invalid_identifiers_filters_and_tampered_cursor(tmp_path: Path) -> None:
    snapshot, root, _publication = published_material_with_condition(tmp_path)
    first = query_semantic(
        snapshot.source_id, snapshot.build_id, purpose="cite", limit=1, store_root=root
    )
    assert first.next_cursor
    replacement = "A" if first.next_cursor[-1] != "A" else "B"
    tampered = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        cursor=first.next_cursor[:-1] + replacement,
        store_root=root,
    )

    assert tampered.page_status == "cursor_stale"
    assert tampered.error_codes == ("CS_CURSOR_STALE",)
    with pytest.raises(ValueError, match="source_id/build_id"):
        query_semantic("not-a-hash", snapshot.build_id, purpose="cite", store_root=root)
    with pytest.raises(ValueError, match="invalid semantic field filter"):
        query_semantic(
            snapshot.source_id,
            snapshot.build_id,
            purpose="cite",
            field_filters={"role": "unsupported"},
            store_root=root,
        )


def test_budget_returns_gap_without_partial_evidence_or_json(tmp_path: Path) -> None:
    snapshot, root, _publication = published_material_with_condition(tmp_path)

    one_record_page = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        limit=1,
        store_root=root,
    )
    one_record_budget = len(one_record_page.model_dump_json()) + 50
    partial_page = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        max_chars=one_record_budget,
        store_root=root,
    )
    assert partial_page.page_status == "budget_limited"
    assert len(partial_page.records) == 1
    assert partial_page.next_cursor is not None
    assert len(partial_page.model_dump_json()) <= one_record_budget

    page = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        query_text="收入",
        max_chars=1_000,
        store_root=root,
    )
    encoded = page.model_dump_json()

    assert page.page_status == "budget_limited"
    assert page.error_codes == ("CS_BUDGET_EXHAUSTED",)
    assert page.records == ()
    assert page.next_cursor is not None
    assert len(encoded) <= 1_000
    assert json.loads(encoded)["page_status"] == "budget_limited"
    assert "15亿元" not in encoded

    tighter = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        query_text="收入",
        max_chars=700,
        store_root=root,
    )
    assert tighter.page_status == "budget_limited"
    assert tighter.records == ()
    assert len(tighter.model_dump_json()) <= 700


def test_query_distinguishes_publication_extraction_and_match_states(tmp_path: Path) -> None:
    snapshot, root, _publication = published_material_with_condition(tmp_path)

    unpublished = query_semantic("9" * 64, "8" * 64, purpose="cite", store_root=root)
    not_extracted = query_semantic(
        snapshot.source_id, snapshot.build_id, purpose="calculate", store_root=root
    )
    lexical_miss = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        query_text="绝不可能出现的词",
        store_root=root,
    )
    no_support_snapshot, no_support_root, _publication = published_material_with_condition(
        tmp_path / "no-support", supported=False
    )
    checked_without_support = query_semantic(
        no_support_snapshot.source_id,
        no_support_snapshot.build_id,
        purpose="cite",
        store_root=no_support_root,
    )

    assert (unpublished.page_status, unpublished.error_codes) == (
        "not_published",
        ("CS_NOT_PUBLISHED",),
    )
    assert (not_extracted.page_status, not_extracted.error_codes) == (
        "not_extracted",
        ("CS_DEPENDENCY_NOT_READY",),
    )
    assert (lexical_miss.page_status, lexical_miss.error_codes) == ("no_match", ())
    assert (checked_without_support.page_status, checked_without_support.error_codes) == (
        "no_match",
        ("CS_NOT_FOUND",),
    )


def test_condition_is_independently_searchable_not_support_ranked_away(tmp_path: Path) -> None:
    snapshot, root, _publication = published_material_with_condition(tmp_path)

    page = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        query_text="许可获批",
        store_root=root,
    )

    assert page.page_status == "complete"
    assert len(page.records) == 1
    assert page.records[0].evidence[0].quote == "仅在合成许可获批时成立。"


def test_checked_empty_role_is_not_hidden_by_other_published_roles(tmp_path: Path) -> None:
    snapshot, _, root, references, _ = forecast_artifacts(
        tmp_path,
        item_overrides={
            "record_type": "coverage",
            "status": "no_supported_item",
            "reason_code": "synthetic_no_support",
        },
    )
    publish_semantic(
        source_id=snapshot.source_id,
        build_id=snapshot.build_id,
        snapshot_id=snapshot.snapshot_id,
        artifacts=tuple(references.values()),
        expected_parent_publication_id=None,
        store_root=root,
    )
    for query_text in ("", "营业收入", "不匹配"):
        page = query_semantic(
            snapshot.source_id,
            snapshot.build_id,
            purpose="cite",
            query_text=query_text,
            field_filters={"role": "material_items"},
            store_root=root,
        )
        assert (page.page_status, page.error_codes, page.records) == (
            "no_match",
            ("CS_NOT_FOUND",),
            (),
        )
    lexical_miss = query_semantic(
        snapshot.source_id,
        snapshot.build_id,
        purpose="cite",
        query_text="不匹配",
        field_filters={"role": "claims"},
        store_root=root,
    )
    assert (lexical_miss.page_status, lexical_miss.error_codes) == ("no_match", ())


def test_relation_search_matches_source_and_endpoint_text(tmp_path: Path) -> None:
    snapshot, root, items, relations = relation_artifacts(tmp_path)
    publish_semantic(
        source_id=snapshot.source_id,
        build_id=snapshot.build_id,
        snapshot_id=snapshot.snapshot_id,
        artifacts=(items, relations),
        expected_parent_publication_id=None,
        store_root=root,
    )
    args = dict(purpose="cite", field_filters={"role": "material_relations"}, store_root=root)
    all_relations = query_semantic(snapshot.source_id, snapshot.build_id, **args)
    assert all_relations.records
    record = all_relations.records[0]
    view = read_semantic(snapshot.source_id, snapshot.build_id, store_root=root)
    endpoint_texts = {
        item.text
        for artifact in view.artifacts
        if artifact.artifact.role == "material_items"
        for item in artifact.payload.understanding.items
    }
    assert endpoint_texts == {"主持人：需求是否改善？", "专家：因为订单增加，需求已经改善。"}
    for text in (record.evidence[0].quote, *endpoint_texts):
        found = query_semantic(snapshot.source_id, snapshot.build_id, query_text=text, **args)
        matched = next(item for item in found.records if item.record_id == record.record_id)
        assert all(
            any(text in evidence.quote for evidence in matched.evidence) for text in endpoint_texts
        )


@pytest.mark.parametrize("reverse", [False, True])
def test_mapping_conflict_survives_other_links_and_order(tmp_path: Path, reverse: bool) -> None:
    snapshot, _, root, references, _ = forecast_artifacts(tmp_path)
    args = dict(
        source_id=snapshot.source_id,
        build_id=snapshot.build_id,
        snapshot_id=snapshot.snapshot_id,
        artifacts=tuple(references.values()),
        store_root=root,
    )
    first = publish_semantic(**args, expected_parent_publication_id=None)
    conflict = first.mappings[0]
    assert conflict.mapping_status == "conflict"
    unlinked = CrossRoleMapping(
        claim_fact_id=conflict.claim_fact_id,
        material_item_id=None,
        mapping_status="unlinked",
        evidence_unit_ids=conflict.evidence_unit_ids,
    )
    mappings = (conflict, unlinked) if reverse else (unlinked, conflict)
    publish_semantic(**args, expected_parent_publication_id=first.publication_id, mappings=mappings)
    for role in ("claims", "material_items"):
        page = query_semantic(
            snapshot.source_id,
            snapshot.build_id,
            purpose="cite",
            field_filters={"role": role, "mapping_status": "conflict"},
            store_root=root,
        )
        assert len(page.records) == 1
        assert page.records[0].mapping_status == "conflict"
        assert page.records[0].usable_for == ("cite",)
