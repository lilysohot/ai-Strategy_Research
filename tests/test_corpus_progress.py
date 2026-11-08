"""Returned evidence, not search wording, drives the incomplete stop-loss."""

import json
from types import SimpleNamespace

import pytest

from benchmarks.team_workflow.corpus_fixtures import fixed_corpus_tools
from frontier_agent.components.agent_bus.fan_in import INCOMPLETE_STOP_REASONS
from frontier_agent.core.loop_types import ToolResult
from plugins.corpus.progress import STOP_REASON, CorpusProgressObserver
from tests.test_team_corpus_fixtures import call, case


def context():
    return SimpleNamespace(messages=[], tool_calls=[], metadata={}, turn=0)


async def turn(observer, ctx, name, payload, *, args=None, delivered=None, extra_calls=()):
    ctx.turn += 1
    call_id = f"call-{ctx.turn}"
    ctx.tool_calls = [{"name": name, "args": args or {}}, *extra_calls]
    raw = json.dumps(payload)
    await observer.on_tool_result(ctx, ToolResult(name, args or {}, raw, 0, call_id, False))
    ctx.messages.append({
        "role": "tool", "tool_call_id": call_id,
        "content": raw if delivered is None else delivered,
    })
    return await observer.on_turn_end(ctx)


def fetch(doc="cv2:" + "1" * 64, loc="chunk:unit", text="exact source", start=0):
    return {"ok": True, "doc_id": doc, "locator": loc, "text": text,
            "fragment": {"start": start, "end": start + len(text)}}


async def test_changed_queries_same_real_evidence_stop_as_incomplete(tmp_path):
    observer, ctx = CorpusProgressObserver(stop_after=6), context()
    with fixed_corpus_tools(case("F18"), tmp_path, "A") as tools:
        for i in range(7):
            payload = await call(tools, "corpus_search", query=f"different query {i}")
            decision = await turn(observer, ctx, "corpus_search", payload)
            if i < 6:
                assert decision is None
            if i == 3:
                state = await observer.on_before_llm(ctx)
                assert '"task_sufficiency": "not_assessed"' in state.inject_messages[0]
        assert decision.stop_reason == STOP_REASON
        assert STOP_REASON in INCOMPLETE_STOP_REASONS
        assert ctx.metadata["corpus_progress"]["repeated_calls"] == 6


async def test_preview_discovery_allows_required_read_and_whole_document(tmp_path):
    observer, ctx = CorpusProgressObserver(stop_after=4), context()
    with fixed_corpus_tools(case("F22"), tmp_path, "A") as tools:
        search = await call(tools, "corpus_search", query="candidate")
        assert not search["hits"][0]["excerpts"]
        for _ in range(3):
            assert await turn(observer, ctx, "corpus_search", search) is None
        args = {"doc_id": search["hits"][0]["doc_id"], "scope": "document"}
        for _ in range(30):
            page = await call(tools, "corpus_fetch", **args)
            assert page["ok"]
            assert await turn(observer, ctx, "corpus_fetch", page) is None
            assert observer.streak == 0
            if page["fetch_complete"]:
                break
            args = {"doc_id": page["doc_id"], "cursor": page["next_cursor"]}
        else:
            pytest.fail("document traversal did not finish")


@pytest.mark.parametrize("changed", [
    fetch(doc="cv2:" + "2" * 64), fetch(loc="chunk:other"),
    fetch(start=100), fetch(text="new source text"),
])
async def test_new_version_location_range_or_text_resets_budget(changed):
    observer, ctx = CorpusProgressObserver(stop_after=4), context()
    for _ in range(4):
        assert await turn(observer, ctx, "corpus_fetch", fetch()) is None
    assert observer.streak == 3
    assert await turn(observer, ctx, "corpus_fetch", changed) is None
    assert observer.streak == 0


@pytest.mark.parametrize("body", ["{truncated", json.dumps({"ok": False, "code": "budget_exceeded"})])
async def test_undelivered_body_does_not_consume_budget(body):
    observer, ctx = CorpusProgressObserver(stop_after=4), context()
    for _ in range(8):
        assert await turn(observer, ctx, "corpus_fetch", fetch(), delivered=body) is None
    assert not observer.seen


@pytest.mark.parametrize("name,payload", [
    ("corpus_search", {"ok": True, "hits": None}),
    ("corpus_fetch", {"ok": True, "items": 4}),
    ("corpus_inventory", {"ok": True, "items": None}),
])
async def test_malformed_result_shape_is_unknown_not_a_loop_failure(name, payload):
    observer, ctx = CorpusProgressObserver(stop_after=4), context()
    for _ in range(6):
        assert await turn(observer, ctx, name, payload) is None
    assert not observer.seen and observer.streak == 0


async def test_checkpoint_in_mixed_batch_cannot_be_overridden_by_stop_loss():
    observer, ctx = CorpusProgressObserver(stop_after=4), context()
    for _ in range(4):
        assert await turn(observer, ctx, "corpus_fetch", fetch()) is None
    assert await turn(observer, ctx, "corpus_fetch", fetch(), extra_calls=[{
        "name": "submit_report", "args": {"finish": False},
    }]) is None
    assert observer.streak == 0


async def test_coordinator_never_stops_from_repetition_alone():
    observer, ctx = CorpusProgressObserver(), context()
    for _ in range(12):
        assert await turn(observer, ctx, "corpus_fetch", fetch()) is None


async def test_withdrawal_blocks_alternate_read_paths_but_not_other_documents(tmp_path):
    observer, ctx = CorpusProgressObserver(stop_after=6), context()
    with fixed_corpus_tools(case("F24"), tmp_path, "A") as tools:
        doc = case("F24")["sources"][0]["doc_id"]
        first = await call(tools, "corpus_fetch", doc_id=doc, scope="document")
        await turn(observer, ctx, "corpus_fetch", first)
        failed = await call(tools, "corpus_fetch", doc_id=doc, cursor=first["next_cursor"])
        assert failed["code"] == "withdrawn" and failed["retryable"] is False
        assert not failed["fetch_complete"]
        await turn(observer, ctx, "corpus_fetch", failed)
        for name, args in [
            ("corpus_fetch", {"scope": "document", "force_refresh": True}),
            ("corpus_fetch", {"locator": first["items"][0]["locator"]}),
            ("corpus_inventory", {"locators": [first["items"][0]["locator"]]}),
        ]:
            denied = await observer.on_tool_call(ctx, {"name": name, "args": {"doc_id": doc, **args}})
            assert denied.skip_is_error
            assert json.loads(denied.skip_with_result)["execution_suppressed"]
        assert await observer.on_tool_call(ctx, {
            "name": "corpus_fetch", "args": {"doc_id": "cv2:" + "b" * 64},
        }) is None
        # A later job may observe an external re-admission; no process-global denial.
        assert await CorpusProgressObserver().on_tool_call(ctx, {
            "name": "corpus_fetch", "args": {"doc_id": doc, "scope": "document"},
        }) is None


async def test_transient_error_is_not_a_document_denial():
    observer, ctx = CorpusProgressObserver(stop_after=4), context()
    error = {"ok": False, "doc_id": "doc", "code": "fetch_failed", "retryable": True}
    for _ in range(8):
        assert await turn(observer, ctx, "corpus_fetch", error) is None
    assert not observer.withdrawn


async def test_real_loop_stops_after_delivered_repeats_without_claiming_completion():
    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.loop_types import LoopConfig
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from frontier_agent.core.tool import tool

    @tool
    async def corpus_search(query: str) -> str:
        """Return one fixed candidate."""
        return json.dumps({"ok": True, "hits": [{"doc_id": "cv2:" + "a" * 64, "title": "A"}]})

    class Client:
        model = "scripted"
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            return LLMResponse(content="", finish_reason="tool_calls", tool_calls=[{
                "id": f"q{self.calls}", "type": "function", "function": {
                    "name": "corpus_search", "arguments": json.dumps({"query": str(self.calls)}),
                },
            }])

    client = Client()
    result = await run_agent_loop(
        llm=client, system_prompt="Research", user_message="Find the required information",
        config=LoopConfig(task_id="progress-loop", max_turns=20), tools=[corpus_search],
        observers=[CorpusProgressObserver(stop_after=6)],
    )
    assert result.stopped_by == STOP_REASON
    assert result.tool_calls_count == client.calls == 7
    assert result.metadata["corpus_progress"]["task_sufficiency"] == "not_assessed"
