"""Adversarial role protocol and frozen relation dependency regression tests."""

from __future__ import annotations

import json
import socket

import pytest
from test_corpus_structured_roles import (
    BUILD_ID,
    SOURCE_ID,
    FakeItems,
    MemoryReader,
    _json_between,
    _snapshot,
)

from plugins.corpus.claims import LlmResponse
from plugins.corpus.evidence import fingerprint
from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    MATERIAL_RELATION_JSONL_VERSION,
    MATERIAL_SLOT_JSONL_VERSION,
    MaterialRun,
    build_relation_candidate_set,
    extract_material_items_role_from_snapshot,
    extract_material_relations_role_from_snapshot,
)
from plugins.corpus.service import CorpusService
from plugins.corpus.structured.snapshot import (
    SnapshotBuildSource,
    SnapshotDocumentSource,
    SnapshotHead,
    SnapshotUnitSource,
    build_snapshot,
)


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("guard tests must not access models, network, or databases")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(CorpusService, "_connect", denied)
    monkeypatch.setattr("plugins.corpus.service.build_default_llm", denied)


def _items(snapshot=None):
    return extract_material_items_role_from_snapshot(
        snapshot or _snapshot(),
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=FakeItems(),
        max_calls=20,
    )


def _rehash(run):
    payload = run.model_dump(mode="json")
    payload.pop("run_id")
    return run.model_copy(update={"run_id": fingerprint(payload)})


def _candidates(run, endpoints, snapshot=None):
    return build_relation_candidate_set(
        snapshot or _snapshot(),
        run,
        endpoint_item_ids=endpoints,
        items_validation_version=MATERIAL_ITEMS_VALIDATION_VERSION,
    )


@pytest.mark.parametrize(
    "corruption",
    [
        "evidence_run",
        "contract",
        "duplicate_item",
        "duplicate_ledger",
        "slot",
        "quote",
        "interval",
        "locator",
        "dependency_removed",
    ],
)
def test_forged_upstream_is_rejected_before_relation_calls(corruption):
    run = _items()
    item = next(item for item in run.understanding.items if item.value == "15亿元")
    understanding = run.understanding
    if corruption == "evidence_run":
        run = run.model_copy(update={"evidence_run_id": "f" * 64})
    elif corruption == "contract":
        understanding = understanding.model_copy(update={"contract_version": "old"})
    elif corruption == "duplicate_item":
        understanding = understanding.model_copy(update={"items": (*understanding.items, item)})
    elif corruption == "duplicate_ledger":
        entry = next(
            entry for entry in understanding.coverage.slot_ledger if item.item_id in entry.item_refs
        )
        understanding = understanding.model_copy(
            update={
                "coverage": understanding.coverage.model_copy(
                    update={"slot_ledger": (*understanding.coverage.slot_ledger, entry)}
                )
            }
        )
    elif corruption == "slot":
        run = run.model_copy(
            update={
                "candidate_slots": tuple(
                    slot.model_copy(update={"text": "forged"}) for slot in run.candidate_slots
                )
            }
        )
    else:
        evidence = item.evidence[0]
        if corruption == "dependency_removed":
            changed = item.model_copy(update={"evidence": (evidence,)})
        else:
            updates = {
                "quote": {"quote": "fabricated"},
                "interval": {"start": -1},
                "locator": {"locator": "wrong-locator"},
            }[corruption]
            changed = item.model_copy(
                update={"evidence": (evidence.model_copy(update=updates), *item.evidence[1:])}
            )
        understanding = understanding.model_copy(
            update={
                "items": tuple(
                    changed if other.item_id == item.item_id else other
                    for other in understanding.items
                )
            }
        )
    run = _rehash(run.model_copy(update={"understanding": understanding}))
    calls = []
    with pytest.raises(ValueError, match="CS_INPUT_INVALID"):
        extract_material_relations_role_from_snapshot(
            _snapshot(),
            run,
            protocol=MATERIAL_RELATION_JSONL_VERSION,
            endpoint_item_ids=(item.item_id,),
            items_validation_version=MATERIAL_ITEMS_VALIDATION_VERSION,
            llm=lambda prompt: calls.append(prompt) or "",
            max_calls=1,
        )
    assert calls == []


def test_endpoint_input_order_does_not_change_candidates_or_candidate_identity():
    run = _items()
    endpoints = tuple(
        item.item_id
        for item in run.understanding.items
        if item.speech_role in {"question", "answer"}
    )
    first = _candidates(run, endpoints)
    second = _candidates(run, tuple(reversed(endpoints)))
    assert first.candidates
    assert first == second


def test_items_retain_cross_unit_condition_evidence():
    fake = FakeItems()
    run = extract_material_items_role_from_snapshot(
        _snapshot(),
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=fake,
        max_calls=20,
    )
    item = next(item for item in run.understanding.items if item.value == "15亿元")
    assert any("仅在合成许可获批时成立" in evidence.quote for evidence in item.evidence)
    assert len({evidence.packet_id for evidence in item.evidence}) == 2
    assert _candidates(run, (item.item_id,)).endpoint_item_ids == (item.item_id,)
    quantified_prompt = next(
        prompt for prompt in fake.prompts if '"text":"预计虚构星河公司2026年收入15亿元。"' in prompt
    )
    assert "完整证据依赖" in quantified_prompt
    assert "仅在合成许可获批时成立" in quantified_prompt.split("完整证据依赖", 1)[1]


@pytest.mark.parametrize("corruption", ["extra_role", "joint_fields", "finish_reason", "truncated"])
def test_items_role_rejects_silent_protocol_fallback(corruption):
    fake = FakeItems()

    def response(prompt):
        valid = fake(prompt)
        if corruption == "extra_role":
            return valid + '\n{"record_type":"relation"}'
        if corruption == "joint_fields":
            rows = valid.splitlines()
            record = json.loads(rows[0])
            record["relations"] = []
            return "\n".join([json.dumps(record), *rows[1:]])
        if corruption == "finish_reason":
            return LlmResponse(valid, diagnostics={"finish_reason": "content_filter"})
        return valid + '\n{"record_type":'

    run = extract_material_items_role_from_snapshot(
        _snapshot(),
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=response,
        max_calls=20,
    )
    assert run.understanding.items == ()
    assert any(entry.status == "failed" for entry in run.understanding.coverage.slot_ledger)


@pytest.mark.parametrize(
    "corruption", ["extra_role", "extra_field", "absent_quote", "finish_reason"]
)
def test_relation_role_rejects_malformed_success(corruption):
    run = _items()
    endpoints = tuple(
        item.item_id
        for item in run.understanding.items
        if item.speech_role in {"question", "answer"}
    )

    def response(prompt):
        pairs = _json_between(
            prompt, "允许判断的候选关系对（不得输出列表外端点或其他 type）：\n", "\n\n当前证据包："
        )
        rows = [
            {
                "record_type": "relation_decision",
                "candidate_pair_id": pair["candidate_pair_id"],
                "status": "absent",
                "evidence_quote": None,
            }
            for pair in pairs
        ]
        if corruption == "extra_field":
            rows[0]["items"] = []
        elif corruption == "absent_quote":
            rows[0]["evidence_quote"] = "fabricated"
        elif corruption == "extra_role":
            rows.append({"record_type": "item"})
        text = "\n".join(json.dumps(row) for row in rows)
        return (
            LlmResponse(text, diagnostics={"finish_reason": "tool_calls"})
            if corruption == "finish_reason"
            else text
        )

    relations, candidates = extract_material_relations_role_from_snapshot(
        _snapshot(),
        run,
        protocol=MATERIAL_RELATION_JSONL_VERSION,
        endpoint_item_ids=endpoints,
        items_validation_version=MATERIAL_ITEMS_VALIDATION_VERSION,
        llm=response,
        max_calls=5,
    )
    assert candidates.candidates
    assert relations.understanding.relations == ()
    assert all(packet.status == "failed" for packet in relations.packet_runs)


def test_empty_relation_payload_still_binds_frozen_endpoint_set():
    run = _items()
    outputs = []
    for item in run.understanding.items[:2]:
        result, candidate_set = extract_material_relations_role_from_snapshot(
            _snapshot(),
            run,
            protocol=MATERIAL_RELATION_JSONL_VERSION,
            endpoint_item_ids=(item.item_id,),
            items_validation_version=MATERIAL_ITEMS_VALIDATION_VERSION,
            llm=None,
            max_calls=0,
        )
        assert not candidate_set.candidates
        assert result.relation_candidate_set_id == candidate_set.candidate_set_id
        result.verify_identity()
        outputs.append(result.run_id)
    assert outputs[0] != outputs[1]


def test_historical_material_run_hash_remains_readable():
    run = _items()
    data = run.model_dump(mode="json")
    data["extractor_version"] = "material-semantics-13"
    data.pop("relation_candidate_set_id")
    data.pop("run_id")
    old = MaterialRun.model_validate({**data, "run_id": fingerprint(data)})
    old.verify_identity()
    with pytest.raises(ValueError, match="extractor version"):
        _candidates(old, ())


@pytest.mark.parametrize(
    "text",
    [
        "专家：需求改善，因为订单增加，且价格提高。",
        "专家：需求改善，预计公告称订单增加，且价格提高。",
    ],
)
def test_explicit_connector_or_attribution_does_not_generate_cooccurrence_chain(text):
    snapshot = build_snapshot(
        MemoryReader(
            SnapshotBuildSource(
                head=SnapshotHead(source_id=SOURCE_ID, build_id=BUILD_ID, publication_generation=1),
                parser_versions={"parse": "p1", "clean": "c1", "chunk": "k1"},
                document=SnapshotDocumentSource(title="合成材料", subject="合成主体"),
                units=(
                    SnapshotUnitSource(
                        source_unit_id="unit",
                        chunk_id="chunk",
                        kind="prose",
                        ordinal=0,
                        locator="paragraph:1",
                        text=text,
                    ),
                ),
            )
        ),
        SOURCE_ID,
    )
    fake = FakeItems()

    def response(prompt):
        rows = [json.loads(line) for line in fake(prompt).splitlines()]
        for row in rows:
            if "因为" in row["evidence_quote"] or "公告" in row["evidence_quote"]:
                row["statement_role"] = "evidence"
            if "公告" in row["evidence_quote"]:
                row["perspective"] = "quoted_other"
        return "\n".join(json.dumps(row) for row in rows)

    run = extract_material_items_role_from_snapshot(
        snapshot,
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=response,
        max_calls=5,
    )
    assert len(run.understanding.items) == 3
    candidates = _candidates(run, tuple(item.item_id for item in run.understanding.items), snapshot)
    assert len(candidates.candidates) == 1
    assert candidates.candidates[0].from_item == run.understanding.items[1].item_id


def test_empty_scope_from_deferred_items_is_not_no_candidates():
    snapshot = _snapshot()
    run = extract_material_items_role_from_snapshot(
        snapshot,
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=None,
        max_calls=0,
    )
    with pytest.raises(ValueError, match="not a qualified no-candidate"):
        _candidates(run, ())


@pytest.mark.parametrize("record_type", ["item", "coverage"])
@pytest.mark.parametrize("slot_value", [None, "", 42])
def test_atomic_role_requires_explicit_nonempty_slot_id(record_type, slot_value):
    fake = FakeItems()

    def response(prompt):
        rows = [json.loads(line) for line in fake(prompt).splitlines()]
        for index, row in enumerate(rows):
            if record_type == "coverage":
                rows[index] = {
                    "record_type": "coverage",
                    "status": "no_supported_item",
                    "reason_code": "synthetic_no_item",
                }
            else:
                row.pop("candidate_slot_id")
            if slot_value is not None:
                rows[index]["candidate_slot_id"] = slot_value
        return "\n".join(json.dumps(row) for row in rows)

    run = extract_material_items_role_from_snapshot(
        _snapshot(),
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=response,
        max_calls=20,
    )
    assert run.understanding.items == ()
    assert run.understanding.coverage.slot_ledger
    assert all(entry.status == "failed" for entry in run.understanding.coverage.slot_ledger)
