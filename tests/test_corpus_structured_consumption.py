"""Zero-network semantic query -> actual request -> existing A4 integration."""

from __future__ import annotations

import copy
import json
import socket
from types import SimpleNamespace

import dotenv
import dotenv.main
import httpx
import pytest
from test_corpus_structured_contracts import V1, _load, _validation_errors
from test_corpus_structured_execution import write_response
from test_corpus_structured_publication import forecast_artifacts
from test_corpus_structured_query import QueryReader, published_material_with_condition

from frontier_agent.components.middleware.llm.base import LLMMiddleware, LLMMiddlewareChain
from frontier_agent.core.llm import LLMResponse, StreamDelta
from frontier_agent.core.loop_types import LoopConfig, LoopPolicy, ToolResult
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.infra.llm.fallback import LLMFallbackChain
from frontier_agent.infra.llm_adapter import FallbackLLM
from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.ledger import (
    ConsumptionLedgerObserver,
    get_run_ledger,
    publish_boundary,
    reset_run_ledgers,
    verify_manifest,
)
from plugins.corpus.material_semantics import build_candidate_slots, build_material_structure
from plugins.corpus.semantic_delivery import with_semantic_delivery
from plugins.corpus.service import CorpusService
from plugins.corpus.structured.consumption import (
    quote_hash,
    reference_for_record,
)
from plugins.corpus.structured.ledger import ReplayResponse, plan_batch, replay_batch
from plugins.corpus.structured.query import SemanticQueryPage
from plugins.corpus.structured.snapshot import (
    SnapshotBuildSource,
    SnapshotDocumentSource,
    SnapshotHead,
    SnapshotUnitSource,
    build_snapshot,
)
from plugins.corpus.structured.store import ArtifactReference, publish_semantic, retire_semantic
from plugins.tools.corpus_manifest import corpus_submit_manifest, with_manifest_tool
from plugins.tools.corpus_semantic_query import corpus_semantic_query, fit_structured_payload
from workflows.stateful_react_agent._runtime import ReactToolResultPostProcessor


@pytest.fixture(autouse=True)
def isolation(tmp_path, monkeypatch):
    def denied(*_args, **_kwargs):
        raise AssertionError("08 must not access network, dotenv or production DB")

    for method in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, method, denied)
    monkeypatch.setattr(socket, "create_connection", denied)
    monkeypatch.setattr(socket, "getaddrinfo", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", denied)
    monkeypatch.setattr(dotenv, "load_dotenv", denied)
    monkeypatch.setattr(dotenv.main, "load_dotenv", denied)
    monkeypatch.setattr(CorpusService, "_connect", denied)
    monkeypatch.setenv("APODEX_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.delenv("A4_ENFORCE", raising=False)
    reset_run_ledgers()
    yield
    reset_run_ledgers()


class SuccessfulLlm:
    model = "synthetic"

    async def chat(self, messages, **_kwargs):
        return LLMResponse(content="received")

    async def stream(self, messages, **_kwargs):
        yield StreamDelta(content="received")


@pytest.fixture
async def sample(tmp_path, monkeypatch):
    snapshot, root, publication = published_material_with_condition(tmp_path)
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(root))
    args = dict(
        source_id=snapshot.source_id, build_id=snapshot.build_id, purpose="cite", query_text="收入"
    )
    body = await corpus_semantic_query.ainvoke(args)
    page = SemanticQueryPage.model_validate_json(body)
    ledger = get_run_ledger()
    observer = ConsumptionLedgerObserver(ledger=ledger)
    ctx = SimpleNamespace(turn=1, messages=[])
    await observer.on_tool_call(ctx, {"name": "corpus_semantic_query", "args": args, "id": "q1"})
    await observer.on_tool_result(
        ctx,
        ToolResult(
            name="corpus_semantic_query",
            args=args,
            result=body,
            duration_ms=0,
            tool_call_id="q1",
            is_error=False,
        ),
    )
    quote = "收入预测依赖许可获批。"
    ref = reference_for_record(publication.publication_id, page.records[0], "cite", "结论一", quote)
    conclusion = {
        "id": "C1",
        "report_quote": quote,
        "semantic_references": [ref.model_dump(mode="json")],
    }
    return SimpleNamespace(
        snapshot=snapshot,
        root=root,
        publication=publication,
        page=page,
        body=body,
        args=args,
        ledger=ledger,
        observer=observer,
        ctx=ctx,
        quote=quote,
        ref=ref,
        conclusion=conclusion,
    )


def message(body, *, role="tool", call_id="q1"):
    return {"role": role, "tool_call_id": call_id, "content": body}


async def deliver(sample, messages=None):
    await with_semantic_delivery(SuccessfulLlm(), sample.ledger).chat(
        [message(sample.body)] if messages is None else messages,
    )


def verify(sample, conclusion=None, *, pending=False, final=None):
    return verify_manifest(
        {"conclusions": [conclusion or sample.conclusion]},
        sample.ledger,
        final_text=sample.quote if final is None else final,
        pending_aware=pending,
    )


async def test_pending_requires_successful_actual_request_not_turn_end_or_resolver(sample):
    assert verify(sample, pending=True)["conclusions"][0]["delivery"] == ["pending"]
    assert not sample.ledger.fetched and not sample.ledger.requested

    sample.ctx.messages = [message(sample.body)]
    await sample.observer.on_turn_end(sample.ctx)
    # Legacy finalize and backend source verification must not acknowledge semantic delivery.
    sample.ledger.finalize(sample.ctx.messages)
    assert verify(sample, pending=True)["status"] == "partial"
    assert sample.ledger.semantic.receipts[0].statuses[sample.ref.record_id] == "pending"
    await deliver(sample)
    out = verify(sample)
    assert out["status"] == "verified"
    checked = out["conclusions"][0]["semantic_references"][0]
    schema = _load(V1 / "report-semantic-reference.schema.json")
    assert _validation_errors(checked, schema, schema) == []
    assert checked["delivery_status"] == "delivered"
    assert checked["quality_status"] == "accepted"
    assert checked["verification_status"] == "verified"
    assert not sample.ledger.fetched and not sample.ledger.requested


async def test_manifest_claimed_verified_flags_cannot_acknowledge_delivery(sample):
    conclusion = copy.deepcopy(sample.conclusion)
    ref = conclusion["semantic_references"][0]
    ref.update(
        delivery_status="delivered", verification_status="verified", quality_status="accepted"
    )
    out = verify(sample, conclusion, pending=True)
    assert out["status"] == "partial"
    checked = out["conclusions"][0]["semantic_references"][0]
    assert checked["delivery_status"] == "pending"
    assert checked["verification_status"] == "pending"


@pytest.mark.parametrize(
    "change", ["empty", "assistant", "wrong_call", "trim", "dependency", "quote"]
)
async def test_rewritten_or_wrong_identity_messages_never_acknowledge(sample, change):
    messages = [message(sample.body)]
    if change == "empty":
        messages = []
    elif change == "assistant":
        messages[0]["role"] = "assistant"
    elif change == "wrong_call":
        messages[0]["tool_call_id"] = "different-query"
    elif change == "trim":
        messages[0]["content"] = fit_structured_payload(sample.body, 700)
    else:
        payload = json.loads(sample.body)
        record = payload["records"][0]
        if change == "dependency":
            record["dependencies"] = []
            record["evidence"] = record["evidence"][:1]
        else:
            record["evidence"][0]["quote"] = "15亿元"
        messages[0]["content"] = json.dumps(payload, ensure_ascii=False)
    await deliver(sample, messages)
    out = verify(sample)
    assert out["status"] != "verified"
    assert "not_delivered" in {p["code"] for p in out["conclusions"][0]["problems"]}


async def test_failed_request_does_not_confirm_delivery(sample):
    class FailedLlm:
        async def chat(self, messages, **kwargs):
            raise ConnectionError("synthetic failure")

    with pytest.raises(ConnectionError):
        await with_semantic_delivery(FailedLlm(), sample.ledger).chat([message(sample.body)])
    assert verify(sample, pending=True)["conclusions"][0]["delivery"] == ["pending"]


async def test_stream_acknowledges_only_when_provider_yields(sample):
    stream = with_semantic_delivery(SuccessfulLlm(), sample.ledger).stream([message(sample.body)])
    assert verify(sample, pending=True)["status"] != "verified"
    assert (await anext(stream)).content == "received"
    assert verify(sample)["status"] == "verified"
    await stream.aclose()


@pytest.mark.parametrize("fallback", ["none", "chain", "legacy"])
async def test_middleware_compaction_precedes_delivery_snapshot(sample, fallback):
    class DropEvidence(LLMMiddleware):
        name = "synthetic-drop"

        async def before_llm(self, ctx, messages):
            return [m for m in messages if m.get("role") != "tool"]

    chain = LLMMiddlewareChain()
    chain.add(DropEvidence())
    original = chain.wrap_llm(SuccessfulLlm(), role_id="test")

    class FailedLlm:
        model = "synthetic-failure"

        async def chat(self, messages, **kwargs):
            raise RuntimeError("synthetic 500 error")

    if fallback == "chain":
        original = LLMFallbackChain.from_models([FailedLlm(), original])
    elif fallback == "legacy":
        original = FallbackLLM(FailedLlm(), original, max_retries=0)
    wrapped = with_semantic_delivery(original, sample.ledger)
    await wrapped.chat([message(sample.body)])
    assert wrapped is not original
    if fallback == "none":
        assert wrapped.inner is not original.inner
    assert verify(sample)["status"] != "verified"


@pytest.mark.parametrize(
    "mutation",
    ["handle", "offset", "hash", "dependency", "purpose", "report", "publication", "record"],
)
async def test_manifest_cannot_launder_invalid_semantic_evidence(sample, mutation):
    await deliver(sample)
    conclusion = copy.deepcopy(sample.conclusion)
    ref = conclusion["semantic_references"][0]
    ref.update(
        delivery_status="delivered", verification_status="verified", quality_status="accepted"
    )
    if mutation == "handle":
        ref["evidence_ranges"][0]["handle"] = "cv2:" + "9" * 64 + "#chunk:query-c"
    elif mutation == "offset":
        ref["evidence_ranges"][0]["start"] += 1
    elif mutation == "hash":
        ref["evidence_ranges"][0]["quote_sha256"] = "sha256:" + "0" * 64
    elif mutation == "dependency":
        ref["dependency_assertions"] = []
    elif mutation == "purpose":
        ref["purpose"] = "calculate"
    elif mutation == "report":
        ref["report_quote"] = "没有出现在报告里的句子"
    elif mutation == "publication":
        ref["publication_id"] = "sha256:" + "0" * 64
    else:
        ref["record_id"] = "nonexistent"
    assert verify(sample, conclusion)["status"] != "verified"


async def test_retired_publication_is_rejected_without_forged_fetch(sample):
    await deliver(sample)
    assert verify(sample)["status"] == "verified"
    retire_semantic(
        source_id=sample.snapshot.source_id,
        build_id=sample.snapshot.build_id,
        expected_parent_publication_id=sample.publication.publication_id,
        store_root=sample.root,
    )
    out = verify(sample)
    assert out["status"] != "verified"
    ref = out["conclusions"][0]["semantic_references"][0]
    assert ref["publication_status"] == "withdrawn"
    assert ref["delivery_status"] == "delivered"
    assert not sample.ledger.fetched


@pytest.mark.parametrize("enforce", [False, True])
async def test_infra_failure_never_becomes_verified_or_skip(sample, monkeypatch, enforce):
    await deliver(sample)
    await corpus_submit_manifest.ainvoke({"conclusions": [sample.conclusion]})

    def unavailable(*args, **kwargs):
        raise OSError("synthetic unavailable store")

    monkeypatch.setattr("plugins.corpus.structured.consumption.read_semantic", unavailable)
    monkeypatch.setenv("A4_ENFORCE", "1" if enforce else "0")
    result = publish_boundary(sample.ledger, final_text=sample.quote, answer_status="complete")
    assert result["publish_status"] == "verification_error"
    assert result["boundary_action"] == ("downgrade" if enforce else "observe")


@pytest.mark.parametrize("enforce", [False, True])
async def test_query_only_activity_requires_manifest(sample, monkeypatch, enforce):
    monkeypatch.setenv("A4_ENFORCE", "1" if enforce else "0")
    result = publish_boundary(sample.ledger, final_text=sample.quote, answer_status="complete")
    assert result["publish_status"] == "draft"
    assert result["boundary_action"] == ("downgrade" if enforce else "observe")
    assert [t.name for t in with_manifest_tool([corpus_semantic_query], role_id="test")] == [
        "corpus_semantic_query",
        "corpus_submit_manifest",
    ]


async def test_submit_short_selection_generates_contract_without_trusting_delivery(sample):
    selection = {
        "id": "C1",
        "report_quote": sample.quote,
        "required_dependencies": ["condition"],
        "semantic_references": [
            {
                "publication_id": sample.publication.publication_id,
                "record_id": sample.ref.record_id,
                "purpose": "cite",
            }
        ],
    }
    pending = json.loads(await corpus_submit_manifest.ainvoke({"conclusions": [selection]}))
    assert pending["publish_status"] == "partial"
    assert pending["conclusions"][0]["delivery"] == ["pending"]
    await deliver(sample)
    out = json.loads(await corpus_submit_manifest.ainvoke({"conclusions": [selection]}))
    assert out["publish_status"] == "verified"
    assert len(out["conclusions"][0]["semantic_references"][0]["evidence_ranges"]) == 2
    boundary = publish_boundary(sample.ledger, final_text=sample.quote, answer_status="complete")
    assert boundary["boundary_action"] == "publish"
    assert boundary["publish_status"] == "verified"


async def test_semantic_publication_is_not_a_report_manifest(sample):
    out = json.loads(
        await corpus_submit_manifest.ainvoke(
            {
                "conclusions": [sample.publication.model_dump(mode="json")],
            }
        )
    )
    assert out["ok"] is False
    assert (
        verify_manifest(sample.publication.model_dump(mode="json"), sample.ledger)["status"]
        == "draft"
    )


@pytest.mark.parametrize("enforce", [False, True])
async def test_real_loop_query_only_submit_and_a4_verified(tmp_path, monkeypatch, enforce):
    snapshot, root, _ = published_material_with_condition(tmp_path)
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(root))
    monkeypatch.setenv("A4_ENFORCE", "1" if enforce else "0")
    ledger = get_run_ledger()
    report = "仅在许可获批时，收入预测成立。"

    class ScriptedLlm:
        model = "synthetic-no-network"

        def __init__(self):
            self.calls = 0
            self.requests = []

        async def chat(self, messages, **kwargs):
            self.calls += 1
            self.requests.append(copy.deepcopy(messages))
            assert "corpus_submit_manifest" in [s["function"]["name"] for s in kwargs["tools"]]
            if self.calls == 1:
                name = "corpus_semantic_query"
                args = dict(
                    source_id=snapshot.source_id,
                    build_id=snapshot.build_id,
                    purpose="cite",
                    query_text="收入",
                )
            elif self.calls == 2:
                content = next(m["content"] for m in reversed(messages) if m["role"] == "tool")
                page = SemanticQueryPage.model_validate_json(content)
                assert len(page.records[0].evidence) == 2
                name = "corpus_submit_manifest"
                args = {
                    "conclusions": [
                        {
                            "id": "C1",
                            "report_quote": report,
                            "semantic_references": [
                                {
                                    "publication_id": page.publication_id,
                                    "record_id": page.records[0].record_id,
                                    "purpose": "cite",
                                }
                            ],
                        }
                    ]
                }
            else:
                result = json.loads(
                    next(m["content"] for m in reversed(messages) if m["role"] == "tool")
                )
                assert result["publish_status"] == "verified"
                return LLMResponse(content=report, finish_reason="stop")
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": f"call-{self.calls}",
                        "type": "function",
                        "function": {"name": name, "arguments": json.dumps(args)},
                    }
                ],
                finish_reason="tool_calls",
            )

    llm = ScriptedLlm()
    result = await run_agent_loop(
        system_prompt="synthetic",
        user_message="report",
        llm=with_semantic_delivery(llm, ledger),
        tools=with_manifest_tool([corpus_semantic_query], role_id="test"),
        config=LoopConfig(
            max_turns=3,
            max_llm_retries=1,
            loop_policy=LoopPolicy(no_tool_behavior="stop"),
            tool_result_post_processor=ReactToolResultPostProcessor(),
        ),
        observers=[ConsumptionLedgerObserver(ledger=ledger)],
    )
    assert result.final_content == report
    boundary = publish_boundary(ledger, final_text=result.final_content, answer_status="complete")
    assert boundary["publish_status"] == "verified" and boundary["boundary_action"] == "publish"
    assert not ledger.fetched and not ledger.requested
    assert ledger.semantic.calls[0]["tool"] == "corpus_semantic_query"
    assert ledger.semantic.calls[0]["call_id"] == "call-1"
    assert quote_hash("仅在合成许可获批时成立。") in json.dumps(boundary, ensure_ascii=False)


async def test_identical_quotes_are_bound_to_the_exact_source_interval(tmp_path, monkeypatch):
    text = "虚构公司收入15亿元。"
    snapshot = build_snapshot(
        QueryReader(
            SnapshotBuildSource(
                head=SnapshotHead(source_id="a" * 64, build_id="b" * 64, publication_generation=1),
                parser_versions={"parse": "p1", "clean": "c1", "chunk": "k1"},
                document=SnapshotDocumentSource(title="合成重复引文", subject="虚构公司"),
                units=tuple(
                    SnapshotUnitSource(
                        source_unit_id=f"repeated-{index}",
                        chunk_id=f"dup-{index}",
                        kind="prose",
                        text=text,
                        locator=f"page:{index}",
                        ordinal=index,
                    )
                    for index in (1, 2)
                ),
            )
        ),
        "a" * 64,
    )
    plan = plan_batch(
        snapshot,
        max_attempts=2,
        role_max_attempts={"claims": 0, "material_items": 2, "material_relations": 0},
        relations_enabled=False,
    )
    task = next(t for t in plan.tasks if t.role == "material_items")
    document = evidence_document_from_snapshot(snapshot, role="material_items")
    slots = build_candidate_slots(document, build_material_structure(document))
    assert len(slots) == 2
    responses = tmp_path / "responses"
    for i, slot in enumerate(slots, start=1):
        content = dict(
            record_type="item",
            candidate_slot_id=slot.candidate_slot_id,
            item_id=f"item-{i}",
            text=slot.text,
            semantic_type="fact",
            statement_role="claim",
            speech_role="statement",
            perspective="source_explicit",
            speaker_ref="spk_" + fingerprint([None, "document_voice", "unknown"])[:12],
            polarity="affirmed",
            value="15亿元",
            behavior_status=None,
            temporal_frame="contemporaneous",
            evidence_quote=slot.text,
            unknown_fields=[],
        )
        write_response(
            responses,
            ReplayResponse(
                task_id=task.task_id,
                sequence=i,
                role=task.role,
                protocol=task.protocol,
                content=json.dumps(content, ensure_ascii=False),
            ),
            f"item-{i}",
        )
    root = tmp_path / "store"
    checked = replay_batch(plan, responses=responses, store_root=root)
    task = next(t for t in checked.ledger.tasks if t.role == "material_items")
    assert task.quality_status == "accepted", json.dumps(
        task.model_dump(mode="json"), ensure_ascii=False
    )
    publication = publish_semantic(
        source_id=snapshot.source_id,
        build_id=snapshot.build_id,
        snapshot_id=snapshot.snapshot_id,
        artifacts=(
            ArtifactReference(
                batch_id=plan.batch_id, task_id=task.task_id, artifact_sha256=task.artifact_sha256
            ),
        ),
        expected_parent_publication_id=None,
        store_root=root,
    )
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(root))
    args = dict(source_id=snapshot.source_id, build_id=snapshot.build_id, purpose="cite")
    body = await corpus_semantic_query.ainvoke(args)
    page = SemanticQueryPage.model_validate_json(body)
    first, second = sorted(page.records, key=lambda r: r.evidence[0].handle)
    assert first.evidence[0].quote == second.evidence[0].quote
    assert first.evidence[0].start == second.evidence[0].start == 0
    assert first.evidence[0].unit_id != second.evidence[0].unit_id
    ledger = get_run_ledger()
    observer = ConsumptionLedgerObserver(ledger=ledger)
    await observer.on_tool_result(
        SimpleNamespace(turn=1),
        ToolResult(
            name="corpus_semantic_query",
            args=args,
            result=body,
            duration_ms=0,
            tool_call_id="dup",
            is_error=False,
        ),
    )
    # Only the second occurrence actually enters the request, even though the text is identical.
    payload = json.loads(body)
    payload["records"] = [second.model_dump(mode="json")]
    await with_semantic_delivery(SuccessfulLlm(), ledger).chat(
        [
            message(json.dumps(payload, ensure_ascii=False), call_id="dup"),
        ]
    )
    references = [
        reference_for_record(publication.publication_id, r, "cite", "C1", "报告")
        for r in (first, second)
    ]
    results = [
        verify_manifest(
            {
                "conclusions": [
                    {
                        "id": "C1",
                        "report_quote": "报告",
                        "semantic_references": [ref.model_dump(mode="json")],
                    }
                ]
            },
            ledger,
            final_text="报告",
        )
        for ref in references
    ]
    assert results[0]["status"] == "partial"
    assert results[1]["status"] == "verified"


async def test_late_conflict_invalidates_old_calculate_reference(tmp_path, monkeypatch):
    snapshot, _, root, refs, _ = forecast_artifacts(tmp_path)
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(root))
    first = publish_semantic(
        source_id=snapshot.source_id,
        build_id=snapshot.build_id,
        snapshot_id=snapshot.snapshot_id,
        artifacts=(refs["claims"],),
        expected_parent_publication_id=None,
        store_root=root,
    )
    args = dict(source_id=snapshot.source_id, build_id=snapshot.build_id, purpose="calculate")
    body = await corpus_semantic_query.ainvoke(args)
    page = SemanticQueryPage.model_validate_json(body)
    ledger = get_run_ledger()
    await ConsumptionLedgerObserver(ledger=ledger).on_tool_result(
        SimpleNamespace(turn=1),
        ToolResult(
            name="corpus_semantic_query",
            args=args,
            result=body,
            duration_ms=0,
            tool_call_id="forecast",
            is_error=False,
        ),
    )
    await with_semantic_delivery(SuccessfulLlm(), ledger).chat([message(body, call_id="forecast")])
    reference = reference_for_record(
        first.publication_id, page.records[0], "calculate", "C1", "预测"
    )
    manifest = {
        "conclusions": [
            {"report_quote": "预测", "semantic_references": [reference.model_dump(mode="json")]}
        ]
    }
    assert verify_manifest(manifest, ledger, final_text="预测")["status"] == "verified"
    publish_semantic(
        source_id=snapshot.source_id,
        build_id=snapshot.build_id,
        snapshot_id=snapshot.snapshot_id,
        artifacts=tuple(refs.values()),
        expected_parent_publication_id=first.publication_id,
        store_root=root,
    )
    result = verify_manifest(manifest, ledger, final_text="预测")
    assert result["status"] == "partial"
    assert result["conclusions"][0]["semantic_references"][0]["publication_status"] == "superseded"


async def test_failed_semantic_call_still_activates_a4():
    ledger = get_run_ledger()
    observer = ConsumptionLedgerObserver(ledger=ledger)
    ctx = SimpleNamespace(turn=1)
    await observer.on_tool_call(ctx, {"name": "corpus_semantic_query", "args": {}, "id": "bad"})
    await observer.on_tool_result(
        ctx,
        ToolResult(
            name="corpus_semantic_query",
            args={},
            result="failed",
            duration_ms=0,
            tool_call_id="bad",
            is_error=True,
        ),
    )
    out = publish_boundary(ledger, final_text="无法提供证据", answer_status="complete")
    assert out["boundary_action"] == "observe" and out["publish_status"] == "draft"


async def test_last_turn_tool_result_without_next_request_stays_pending(tmp_path, monkeypatch):
    snapshot, root, _ = published_material_with_condition(tmp_path)
    monkeypatch.setenv("CORPUS_STRUCTURED_ROOT", str(root))
    ledger = get_run_ledger()

    class OneCallLlm:
        model = "synthetic"

        async def chat(self, messages, **kwargs):
            return LLMResponse(
                content="",
                tool_calls=[
                    {
                        "id": "last-query",
                        "type": "function",
                        "function": {
                            "name": "corpus_semantic_query",
                            "arguments": json.dumps(
                                {
                                    "source_id": snapshot.source_id,
                                    "build_id": snapshot.build_id,
                                    "purpose": "cite",
                                    "query_text": "收入",
                                }
                            ),
                        },
                    }
                ],
                finish_reason="tool_calls",
            )

    await run_agent_loop(
        system_prompt="synthetic",
        user_message="query",
        llm=with_semantic_delivery(OneCallLlm(), ledger),
        tools=[corpus_semantic_query],
        config=LoopConfig(max_turns=1, max_llm_retries=1),
        observers=[ConsumptionLedgerObserver(ledger=ledger)],
    )
    assert ledger.semantic.receipts
    assert set(ledger.semantic.receipts[0].statuses.values()) == {"pending"}
    assert not ledger.fetched
