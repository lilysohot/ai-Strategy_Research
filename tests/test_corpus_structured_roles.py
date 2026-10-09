"""Role isolation and deterministic routing; synthetic fake/replay only."""

from __future__ import annotations

import json
import socket
from dataclasses import dataclass, replace
from pathlib import Path

import httpx
import pytest

from plugins.corpus.claims import LlmCallError, LlmResponse
from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    MATERIAL_RELATION_JSONL_VERSION,
    MATERIAL_SLOT_JSONL_VERSION,
)
from plugins.corpus.service import CorpusService
from plugins.corpus.structured.config import canonical_hash
from plugins.corpus.structured.roles import (
    execute_claims_role,
    execute_material_items_role,
    execute_material_relations_role,
    route_snapshot,
)
from plugins.corpus.structured.snapshot import (
    EvidenceSnapshot,
    SnapshotBuildSource,
    SnapshotCellSource,
    SnapshotDependencySource,
    SnapshotDocumentSource,
    SnapshotGapSource,
    SnapshotHead,
    SnapshotReader,
    SnapshotTextSource,
    SnapshotUnitSource,
    build_snapshot,
)

SOURCE_ID = "1" * 64
BUILD_ID = "2" * 64


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*args: object, **kwargs: object) -> None:
        raise AssertionError("role tests must not access network, models, or databases")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(CorpusService, "_connect", denied)
    monkeypatch.setattr("plugins.corpus.service.build_default_llm", denied)
    original_open = Path.open
    real_env = Path(__file__).resolve().parents[1] / ".env"

    def guarded_open(path, *args, **kwargs):
        assert path.resolve() != real_env, "real .env must not be read"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)


@dataclass
class MemoryReader(SnapshotReader):
    payload: SnapshotBuildSource

    def read_head(self, source_id: str) -> SnapshotHead:
        assert source_id == SOURCE_ID
        return self.payload.head

    def read_build(self, head: SnapshotHead) -> SnapshotBuildSource:
        assert head == self.payload.head
        return self.payload


def _snapshot(*, generation: int = 1) -> EvidenceSnapshot:
    table = "指标|2025A\n营业收入|12|亿元"
    units = (
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
            source_unit_id="quant-u",
            chunk_id="quant-c",
            kind="prose",
            text="预计虚构星河公司2026年收入15亿元。",
            locator="page:2/paragraph:1",
            ordinal=2,
            dependencies=(
                SnapshotDependencySource(
                    kind="condition",
                    target_unit_id="condition-u",
                    target_chunk_id="condition-c",
                    required_for=("cite", "compare", "calculate"),
                ),
            ),
        ),
        SnapshotUnitSource(
            source_unit_id="condition-u",
            chunk_id="condition-c",
            kind="prose",
            text="仅在合成许可获批时成立。",
            locator="page:2/paragraph:2",
            ordinal=3,
        ),
        SnapshotUnitSource(
            source_unit_id="opinion-u",
            chunk_id="opinion-c",
            kind="prose",
            text="合成分析师认为竞争力可能改善。",
            locator="page:3/paragraph:1",
            ordinal=4,
        ),
        SnapshotUnitSource(
            source_unit_id="dialogue-u",
            chunk_id="dialogue-c",
            kind="prose",
            text="主持人：需求是否改善？\n专家：因为订单增加，需求已经改善。",
            locator="page:4/dialogue:1",
            ordinal=5,
        ),
        SnapshotUnitSource(
            source_unit_id="plain-u",
            chunk_id="plain-c",
            kind="prose",
            text="合成供应链韧性改善。",
            locator="page:4/paragraph:2",
            ordinal=6,
        ),
        SnapshotUnitSource(
            source_unit_id="gap-u",
            chunk_id="gap-c",
            kind="gap",
            text="【解析缺口】",
            locator="page:5/image:1",
            ordinal=7,
        ),
    )
    head = SnapshotHead(
        source_id=SOURCE_ID,
        build_id=BUILD_ID,
        publication_generation=generation,
    )
    payload = SnapshotBuildSource(
        head=head,
        parser_versions={"parse": "p1", "clean": "c1", "chunk": "k1"},
        document=SnapshotDocumentSource(
            title="完全合成角色隔离材料",
            subject="虚构星河公司",
            published="2026-01-01",
        ),
        units=units,
        gaps=(
            SnapshotGapSource(
                code="synthetic_parse_gap",
                locator="page:5/image:1",
                context_status="missing",
            ),
        ),
    )
    return build_snapshot(MemoryReader(payload), SOURCE_ID)


def _json_between(prompt: str, start: str, end: str) -> object:
    return json.loads(prompt.split(start, 1)[1].split(end, 1)[0].strip())


class FakeItems:
    def __init__(self) -> None:
        self.prompts: list[str] = []

    def __call__(self, prompt: str) -> str:
        self.prompts.append(prompt)
        slots = _json_between(prompt, "候选槽位：\n", "\n来源语境（不可作引文）：")
        speakers = _json_between(
            prompt,
            "系统表达者注册表（可直接引用 speaker_id）：\n",
            "\n候选槽位：",
        )
        assert isinstance(slots, list) and isinstance(speakers, list) and speakers
        speaker_id = speakers[0]["speaker_id"]
        records: list[dict[str, object]] = []
        for index, slot in enumerate(slots):
            quote = slot["text"]
            question = "？" in quote or quote.startswith("问：")
            answer = quote.startswith("答：") or "答：" in quote or "需求已经改善" in quote
            condition = "仅在" in quote
            forecast = "预计" in quote
            records.append(
                {
                    "record_type": "item",
                    "candidate_slot_id": slot["candidate_slot_id"],
                    "item_id": f"item-{len(self.prompts)}-{index}",
                    "text": quote,
                    "semantic_type": "forecast"
                    if forecast
                    else "opinion"
                    if "认为" in quote
                    else "fact",
                    "statement_role": "question"
                    if question
                    else "condition"
                    if condition
                    else "evidence"
                    if answer
                    else "claim",
                    "speech_role": "question" if question else "answer" if answer else "statement",
                    "perspective": "source_explicit",
                    "speaker_ref": speaker_id,
                    "polarity": "affirmed",
                    "value": "15亿元" if "15亿元" in quote else None,
                    "behavior_status": None,
                    "temporal_frame": "contemporaneous",
                    "evidence_quote": quote,
                    "unknown_fields": [],
                }
            )
        return "\n".join(json.dumps(record, ensure_ascii=False) for record in records)


def test_routing_is_explicit_for_table_quantitative_qualitative_and_gap() -> None:
    snapshot = _snapshot()
    plan = route_snapshot(snapshot)
    by_source_id = {
        unit.metadata["source_unit_id"]: next(
            decision for decision in plan.decisions if decision.unit_id == unit.unit_id
        )
        for unit in snapshot.units
    }

    assert by_source_id["table-u"].claims_protocol == "claims-deterministic-v1"
    assert by_source_id["quant-u"].claims_protocol == "claims-json-v2"
    assert by_source_id["quant-u"].material_items is True
    assert by_source_id["opinion-u"].claims_protocol is None
    assert by_source_id["opinion-u"].material_items is True
    assert by_source_id["condition-u"].material_items is True
    assert by_source_id["plain-u"].reason_codes == ("unclassified_prose_conservatively_retained",)
    assert by_source_id["gap-u"].unit_id in plan.unrouted_unit_ids
    assert "source_gap_or_empty" in by_source_id["gap-u"].reason_codes
    assert len(plan.unrouted_gap_ids) == 1
    assert len(plan.decisions) == len(snapshot.units)


def test_routing_recognizes_chinese_scaled_count_units() -> None:
    payload = SnapshotBuildSource(
        head=SnapshotHead(source_id=SOURCE_ID, build_id=BUILD_ID, publication_generation=9),
        parser_versions={"parse": "p1", "clean": "c1", "chunk": "k1"},
        document=SnapshotDocumentSource(
            title="合成行业材料", subject="光模块行业", published="2026-01-01"
        ),
        units=(
            SnapshotUnitSource(
                source_unit_id="scaled-count-u",
                chunk_id="scaled-count-c",
                kind="prose",
                text="预计27年CPO达到5万到10万个，行业需求约1.5亿只。",
                locator="body[1]",
                ordinal=1,
            ),
        ),
    )
    decision = route_snapshot(build_snapshot(MemoryReader(payload), SOURCE_ID)).decisions[0]
    assert decision.claims_protocol == "claims-json-v2"
    assert "source_anchored_quantitative_statement" in decision.reason_codes


def test_claims_table_is_zero_model_and_prose_only_calls_claims() -> None:
    snapshot = _snapshot()
    calls: list[str] = []

    def fake(prompt: str) -> str:
        calls.append(prompt)
        return "[]"

    table = execute_claims_role(
        snapshot,
        task_id="claims-table",
        protocol="claims-deterministic-v1",
        llm=fake,
        max_calls=0,
    )
    assert calls == []
    assert table.artifact.execution_status == "succeeded"
    assert len(table.payload.facts) == 1

    prose = execute_claims_role(
        snapshot,
        task_id="claims-prose",
        protocol="claims-json-v2",
        llm=fake,
        max_calls=10,
    )
    assert len(calls) == 1
    assert all("Claims" in prompt or "claim" in prompt.lower() for prompt in calls)
    assert all(packet.method != "deterministic-table" for packet in prose.payload.packet_runs)


def test_items_only_never_issues_relation_request_and_is_independently_wrapped() -> None:
    snapshot = _snapshot()
    fake = FakeItems()
    result = execute_material_items_role(
        snapshot,
        task_id="items-only",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=fake,
        max_calls=20,
    )

    assert fake.prompts
    assert all("本阶段只抽 speakers 和 items" in prompt for prompt in fake.prompts)
    assert all("候选关系对" not in prompt for prompt in fake.prompts)
    assert result.payload.understanding.relations == ()
    assert all(
        packet.diagnostics is None
        or packet.diagnostics.get("stages", {}).get("relations", {}).get("status")
        == "not_requested_for_items_role"
        for packet in result.payload.packet_runs
    )
    assert result.artifact.role == "material_items"
    assert result.artifact.payload_sha256 == canonical_hash(result.payload.model_dump(mode="json"))
    assert "relations_not_requested" in result.artifact.coverage.reason_codes


@pytest.mark.parametrize(
    ("entry", "protocol"),
    [
        ("claims", "claims-json-v1"),
        ("items", "material-jsonl-v1"),
    ],
)
def test_unsupported_protocols_are_rejected_before_any_call(entry: str, protocol: str) -> None:
    snapshot = _snapshot()
    calls: list[str] = []

    def fake(prompt: str) -> str:
        calls.append(prompt)
        return "[]"

    with pytest.raises(ValueError, match="CS_PROTOCOL_UNSUPPORTED"):
        if entry == "claims":
            execute_claims_role(
                snapshot,
                task_id="unsupported",
                protocol=protocol,
                llm=fake,
                max_calls=10,
            )
        else:
            execute_material_items_role(
                snapshot,
                task_id="unsupported",
                protocol=protocol,
                llm=fake,
                max_calls=10,
            )
    assert calls == []


def test_relations_consume_fixed_validated_items_without_reextracting_them() -> None:
    snapshot = _snapshot()
    item_fake = FakeItems()
    items = execute_material_items_role(
        snapshot,
        task_id="items",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=item_fake,
        max_calls=20,
    )
    question = next(
        item for item in items.payload.understanding.items if item.speech_role == "question"
    )
    answer = next(
        item for item in items.payload.understanding.items if item.speech_role == "answer"
    )
    relation_prompts: list[str] = []

    def relation_fake(prompt: str) -> str:
        relation_prompts.append(prompt)
        pairs = _json_between(
            prompt,
            "允许判断的候选关系对（不得输出列表外端点或其他 type）：\n",
            "\n\n当前证据包：",
        )
        catalog = _json_between(prompt, "可用 items：\n", "\n允许判断的候选关系对")
        quotes = {row["item_id"]: row["evidence_quote"] for row in catalog}
        return "\n".join(
            json.dumps(
                {
                    "record_type": "relation_decision",
                    "candidate_pair_id": pair["candidate_pair_id"],
                    "status": "present",
                    "evidence_quote": quotes[pair["from_item"]],
                },
                ensure_ascii=False,
            )
            for pair in pairs
        )

    relations = execute_material_relations_role(
        snapshot,
        task_id="relations",
        protocol=MATERIAL_RELATION_JSONL_VERSION,
        items_execution=items,
        endpoint_item_ids=(question.item_id, answer.item_id),
        llm=relation_fake,
        max_calls=5,
    )

    assert relation_prompts and all(
        "本阶段只抽 speakers 和 items" not in p for p in relation_prompts
    )
    assert relations.relation_candidates is not None
    assert relations.relation_candidates.items_run_id == items.payload.run_id
    assert relations.relation_candidates.endpoint_item_ids == (question.item_id, answer.item_id)
    assert relations.artifact.upstream_artifact_ids == (items.artifact.artifact_id,)
    assert relations.payload.understanding.items == ()
    assert relations.payload.understanding.relations
    assert items.payload.understanding.items


def test_relations_reject_unqualified_or_wrong_version_endpoints_before_call() -> None:
    snapshot = _snapshot()
    items = execute_material_items_role(
        snapshot,
        task_id="items",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=FakeItems(),
        max_calls=20,
    )
    endpoint = items.payload.understanding.items[0].item_id
    calls: list[str] = []

    with pytest.raises(ValueError, match="validation version"):
        execute_material_relations_role(
            snapshot,
            task_id="relations",
            protocol=MATERIAL_RELATION_JSONL_VERSION,
            items_execution=items,
            endpoint_item_ids=(endpoint,),
            items_validation_version="latest",
            llm=lambda prompt: calls.append(prompt) or "",
            max_calls=1,
        )
    with pytest.raises(ValueError, match="not in the frozen items run"):
        execute_material_relations_role(
            snapshot,
            task_id="relations",
            protocol=MATERIAL_RELATION_JSONL_VERSION,
            items_execution=items,
            endpoint_item_ids=("claim-fact-id-is-not-an-r2-item",),
            items_validation_version=MATERIAL_ITEMS_VALIDATION_VERSION,
            llm=lambda prompt: calls.append(prompt) or "",
            max_calls=1,
        )
    with pytest.raises(ValueError, match="CS_PROTOCOL_UNSUPPORTED"):
        execute_material_relations_role(
            snapshot,
            task_id="relations",
            protocol="material-jsonl-v1",
            items_execution=items,
            endpoint_item_ids=(endpoint,),
            llm=lambda prompt: calls.append(prompt) or "",
            max_calls=1,
        )
    assert calls == []


def test_deferred_items_are_not_reported_as_no_content() -> None:
    result = execute_material_items_role(
        _snapshot(),
        task_id="items-deferred",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=None,
        max_calls=0,
    )
    assert result.artifact.execution_status == "deferred"
    assert result.artifact.coverage.omitted_unit_ids
    assert "relations_not_requested" in result.artifact.coverage.reason_codes
    assert any(packet.status == "deferred" for packet in result.payload.packet_runs)


def test_claims_failure_does_not_block_independent_items_success() -> None:
    snapshot = _snapshot()

    def failed_claims(_prompt: str) -> str:
        raise RuntimeError("synthetic Claims failure")

    claims = execute_claims_role(
        snapshot,
        task_id="claims-failed",
        protocol="claims-json-v2",
        llm=failed_claims,
        max_calls=1,
    )
    items = execute_material_items_role(
        snapshot,
        task_id="items-after-claims-failure",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=FakeItems(),
        max_calls=20,
    )
    assert claims.artifact.execution_status == "failed"
    assert items.payload.understanding.items
    assert items.artifact.execution_status == "succeeded"


def test_role_failures_do_not_erase_other_role_or_upstream_items() -> None:
    snapshot = _snapshot()
    items = execute_material_items_role(
        snapshot,
        task_id="items",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=FakeItems(),
        max_calls=20,
    )
    original_ids = tuple(item.item_id for item in items.payload.understanding.items)
    question = next(
        item for item in items.payload.understanding.items if item.speech_role == "question"
    )
    answer = next(
        item for item in items.payload.understanding.items if item.speech_role == "answer"
    )

    def failed(_prompt: str) -> str:
        raise RuntimeError("synthetic relation failure")

    relations = execute_material_relations_role(
        snapshot,
        task_id="relations-failed",
        protocol=MATERIAL_RELATION_JSONL_VERSION,
        items_execution=items,
        endpoint_item_ids=(question.item_id, answer.item_id),
        llm=failed,
        max_calls=1,
    )
    assert relations.artifact.execution_status == "failed"
    assert relations.artifact.quality_status == "review_required"
    assert relations.payload.understanding.relations == ()
    assert tuple(item.item_id for item in items.payload.understanding.items) == original_ids
    valued_item = next(item for item in items.payload.understanding.items if item.value == "15亿元")
    assert "usable_for" not in valued_item.model_dump()


def test_service_exposes_the_same_strict_role_seams() -> None:
    snapshot = _snapshot()
    service = CorpusService("postgresql://unused")
    result = service.execute_claims_role(
        snapshot,
        task_id="service-table",
        protocol="claims-deterministic-v1",
    )
    assert result.artifact.execution_status == "succeeded"
    assert result.artifact.protocol_status == "valid"


def test_empty_claims_scope_is_zero_calls_and_zero_packets():
    result = execute_claims_role(
        _snapshot(),
        task_id="empty",
        protocol="claims-json-v2",
        scoped_unit_ids=(),
        max_calls=9,
        llm=lambda _: pytest.fail("empty scope must not broaden to all units"),
    )
    assert result.payload.packet_runs == ()
    assert result.calls == ()
    assert result.artifact.coverage.scoped_unit_ids == ()
    assert "no_routed_candidates" in result.artifact.coverage.reason_codes


@pytest.mark.parametrize("task_id,scope_kind", [("", "prose"), ("task", "table")])
def test_invalid_claims_task_rejected_before_model(task_id, scope_kind):
    snapshot = _snapshot()
    scope = tuple(unit.unit_id for unit in snapshot.units if unit.kind == scope_kind)
    with pytest.raises(ValueError, match="CS_INPUT_INVALID"):
        execute_claims_role(
            snapshot,
            task_id=task_id,
            protocol="claims-json-v2",
            scoped_unit_ids=scope,
            max_calls=9,
            llm=lambda _: pytest.fail("invalid input must precede dispatch"),
        )


def test_dispatch_receipts_bind_task_role_snapshot_and_failures_without_retry():
    snapshot = _snapshot()
    requests = []

    def dispatch(request):
        requests.append(request)
        raise LlmCallError(
            {
                "execution_status": "outcome_unknown",
                "error_type": "TransportOutcomeUnknown",
                "usage": None,
                "cost": None,
            }
        )

    result = CorpusService("postgresql://unused").execute_claims_role(
        snapshot,
        task_id="ledger-task",
        protocol="claims-json-v2",
        max_calls=8,
        dispatch=dispatch,
    )
    assert len(requests) == len(result.calls) == 1
    request = requests[0]
    assert (request.task_id, request.role, request.protocol, request.snapshot_id) == (
        "ledger-task",
        "claims",
        "claims-json-v2",
        snapshot.snapshot_id,
    )
    assert request.request_sha256 == canonical_hash(request.prompt)
    assert result.calls[0].response_sha256 is None
    assert result.calls[0].diagnostics["usage"] is None
    assert result.artifact.execution_status == "outcome_unknown"
    assert result.artifact.quality_status != "accepted"


def test_wrong_role_adapter_is_rejected_before_reservation():
    from plugins.corpus.structured.adapter import ExtractionAdapter
    from plugins.corpus.structured.config import bind_roles, load_extraction_config

    adapter = ExtractionAdapter(bind_roles(load_extraction_config(environ={}))[1])
    with pytest.raises(ValueError, match="adapter role/protocol mismatch"):
        execute_claims_role(
            _snapshot(),
            task_id="claims",
            protocol="claims-json-v2",
            llm=adapter,
            max_calls=1,
        )


@pytest.mark.parametrize("state", ["blocked", "cancelled", "deferred"])
@pytest.mark.parametrize("role", ["claims", "material_items"])
def test_dispatch_rejection_preserves_state_and_receipt_without_error_type(state, role):
    from plugins.corpus.claims import LlmCallError

    def reject(_request):
        raise LlmCallError({"execution_status": state, "error_code": "CS_BUDGET_EXHAUSTED"})

    execute = execute_claims_role if role == "claims" else execute_material_items_role
    protocol = "claims-json-v2" if role == "claims" else MATERIAL_SLOT_JSONL_VERSION
    result = execute(
        _snapshot(), task_id="dispatch-rejected", protocol=protocol, dispatch=reject, max_calls=1
    )
    assert len(result.calls) == 1
    assert result.calls[0].execution_status == state
    assert result.calls[0].response_sha256 is None
    assert result.artifact.execution_status == state
    assert result.artifact.error_codes == ("CS_BUDGET_EXHAUSTED",)
    assert result.artifact.quality_status != "accepted"
    assert result.artifact.coverage.omitted_unit_ids


def test_partial_atomic_output_has_visible_omission_and_no_quality_acceptance():
    fake = FakeItems()

    def missing(prompt):
        lines = fake(prompt).splitlines()
        return "\n".join(lines[:1])

    result = execute_material_items_role(
        _snapshot(),
        task_id="missing-output",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=missing,
        max_calls=20,
    )
    assert result.artifact.protocol_status == "invalid"
    assert result.artifact.quality_status == "review_required"
    assert result.artifact.coverage.omitted_unit_ids


def test_selected_item_slot_does_not_claim_other_packets_covered():
    snapshot = _snapshot()
    full = execute_material_items_role(
        snapshot,
        task_id="full",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=FakeItems(),
        max_calls=20,
    )
    selected_slot = next(slot for slot in full.payload.candidate_slots if "竞争力" in slot.text)
    result = execute_material_items_role(
        snapshot,
        task_id="one-slot",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=FakeItems(),
        max_calls=20,
        candidate_slot_ids=(selected_slot.candidate_slot_id,),
    )
    assert len(result.calls) == 1
    assert len(result.artifact.coverage.scoped_unit_ids) == 1
    assert result.payload.candidate_slots == (selected_slot,)


def test_single_slot_in_multi_slot_packet_retains_unit_coverage_gap():
    snapshot = _snapshot()
    full = execute_material_items_role(
        snapshot,
        task_id="all",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=FakeItems(),
        max_calls=20,
    )
    slot = next(slot for slot in full.payload.candidate_slots if "需求是否" in slot.text)
    result = execute_material_items_role(
        snapshot,
        task_id="question-only",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=FakeItems(),
        max_calls=1,
        candidate_slot_ids=(slot.candidate_slot_id,),
    )
    assert len(result.calls) == 1
    assert result.artifact.coverage.omitted_unit_ids
    assert result.artifact.quality_status == "review_required"


def test_role_artifact_serialization_matches_frozen_schema():
    from test_corpus_structured_contracts import V1, _load, _validation_errors

    result = execute_claims_role(_snapshot(), task_id="schema", protocol="claims-deterministic-v1")
    schema = _load(V1 / "role-artifact.schema.json")
    assert _validation_errors(result.artifact.model_dump(mode="json"), schema, schema) == []
    result.artifact.verify_identity()


def test_relations_reject_tampered_or_rejected_artifact_before_call():
    snapshot = _snapshot()
    items = execute_material_items_role(
        snapshot,
        task_id="items",
        protocol=MATERIAL_SLOT_JSONL_VERSION,
        llm=FakeItems(),
        max_calls=20,
    )
    altered = items.artifact.model_copy(update={"quality_status": "rejected"})
    with pytest.raises(ValueError, match="CS_ARTIFACT_CORRUPT"):
        execute_material_relations_role(
            snapshot,
            task_id="rel",
            protocol=MATERIAL_RELATION_JSONL_VERSION,
            items_execution=replace(items, artifact=altered),
            endpoint_item_ids=(),
            llm=lambda _: pytest.fail("tampered upstream"),
            max_calls=1,
        )
    altered = altered.model_copy(
        update={
            "artifact_id": canonical_hash(
                altered.model_dump(mode="json", exclude={"artifact_id"}),
            )
        }
    )
    with pytest.raises(ValueError, match="CS_DEPENDENCY_NOT_READY"):
        execute_material_relations_role(
            snapshot,
            task_id="rel",
            protocol=MATERIAL_RELATION_JSONL_VERSION,
            items_execution=replace(items, artifact=altered),
            endpoint_item_ids=(),
            llm=lambda _: pytest.fail("rejected upstream"),
            max_calls=1,
        )


def test_claims_retains_source_condition_even_if_model_omits_it():
    snapshot = _snapshot()
    response = json.dumps(
        [
            {
                "claim_text": "虚构星河公司2026年收入15亿元",
                "evidence_quote": "虚构星河公司2026年收入15亿元",
                "evidence_kind": "prose",
                "scope": "company",
                "subject": "虚构星河公司",
                "metric": "收入",
                "value_text": "15",
                "unit_raw": "亿元",
                "period_raw": "2026年",
                "kind": "fact",
            }
        ],
        ensure_ascii=False,
    )
    result = execute_claims_role(
        snapshot,
        task_id="qualifiers",
        protocol="claims-json-v2",
        llm=lambda _: response,
        max_calls=1,
    )
    assert result.payload.facts
    fact = result.payload.facts[0]
    assert "仅在合成许可获批时成立" in fact.claim.qualifiers["source_context"]
    assert "预计" in fact.claim.qualifiers["source_context"]
    assert "calculate" not in fact.usable_for
    assert fact.evidence_alignment["dependency_spans"]
    assert fact.evidence_alignment["role_context_spans"]
    assert result.artifact.quality_status == "review_required"


def test_mock_wire_reservation_and_receipt_are_one_per_role_request():
    from plugins.corpus.structured.adapter import ExtractionAdapter
    from plugins.corpus.structured.config import bind_roles, load_extraction_config

    config = load_extraction_config(
        environ={
            "STRUCTURED_EXTRACTION_PROVIDER": "openai_compat",
            "STRUCTURED_EXTRACTION_MODEL": "synthetic-extract",
            "STRUCTURED_EXTRACTION_BASE_URL": "https://extract.invalid/v1",
            "STRUCTURED_EXTRACTION_API_KEY": "sk-fake-secret",
        }
    )
    authorizations, requests = [], []

    def reserve(intent):
        authorizations.append(intent)
        return "attempt-1"

    def wire(request):
        requests.append(request)
        return httpx.Response(
            200,
            json={
                "choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
            },
        )

    adapter = ExtractionAdapter(bind_roles(config)[0], reserve, lambda: httpx.MockTransport(wire))
    result = execute_claims_role(
        _snapshot(),
        task_id="wire",
        protocol="claims-atomic-json-v2",
        llm=adapter,
        max_calls=1,
    )
    assert len(authorizations) == len(requests) == len(result.calls) == 1
    assert authorizations[0].role == result.calls[0].request.role == "claims"
    assert result.calls[0].diagnostics["attempt_id"] == "attempt-1"
    assert result.calls[0].diagnostics["usage"] is None
    assert json.loads(requests[0].content)["model"] == "synthetic-extract"


def test_truncated_claims_is_not_accepted_or_retried():
    result = execute_claims_role(
        _snapshot(),
        task_id="truncated",
        protocol="claims-json-v2",
        max_calls=9,
        llm=lambda _: LlmResponse("[]", {"finish_reason": "length"}),
    )
    assert len(result.calls) == 1
    assert result.artifact.quality_status != "accepted"
    assert result.artifact.coverage.omitted_unit_ids


@pytest.mark.parametrize("raw", ['{"claims": []}', "[] trailing text", '[{"relations": []}]'])
def test_claims_role_does_not_salvage_joint_or_nonprotocol_output(raw):
    result = execute_claims_role(
        _snapshot(),
        task_id="strict-claims",
        protocol="claims-json-v2",
        max_calls=1,
        llm=lambda _: raw,
    )
    assert result.payload.facts == ()
    assert result.artifact.execution_status == "failed"
    assert result.artifact.quality_status != "accepted"
