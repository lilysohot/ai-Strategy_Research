"""Focused regressions for identity delivery, no-tool repair, and failed fetch envelopes."""

import importlib
import json
from types import SimpleNamespace

import pytest

from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig, LoopPolicy, ToolResult
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from plugins.corpus import projection, tool_refs
from plugins.corpus.final_delivery import identity_manifest, prepare_delivery_manifest
from plugins.corpus.ledger import get_run_ledger, publish_boundary, verify_manifest
from plugins.tools._bus_scope import SWARM_SCOPE_KEY
from plugins.tools.task_board import add_task, bind_assignment, snapshot_tasks, update_task
from tests.test_agent_team_verification import add_job
from tests.test_corpus_navigation import _FILENAME
from tests.test_corpus_navigation import service as service_fixture
from tests.test_team_atomic_delivery import delivery_run as delivery_run_fixture
from workflows.agent_team.delivery import TeamDeliveryObserver, deliver_answer
from workflows.agent_team.subagent_runtime import SwarmToolResultPostProcessor
from workflows.stateful_react_agent._runtime import ReactToolResultPostProcessor
from workflows.stateful_react_agent.delivery import CorpusDeliveryObserver

service = service_fixture
delivery_run = delivery_run_fixture

fetch_module = importlib.import_module("plugins.tools.corpus_fetch")
search_module = importlib.import_module("plugins.tools.corpus_search")


@pytest.fixture(autouse=True)
def isolated_run(tmp_path, monkeypatch):
    monkeypatch.setenv("APODEX_RUN_DIR", str(tmp_path / "run"))
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", "on")
    projection.reset_snapshot_index()
    yield
    projection.reset_snapshot_index()


async def observed_identity():
    body = await search_module.corpus_search.func(query="SpaceX")
    get_run_ledger().record_search(body, turn=1)
    return body


class TextClient:
    model = "scripted"

    def __init__(self, answers):
        self.answers = iter(answers)
        self.calls = 0

    async def chat(self, messages, **kwargs):
        self.calls += 1
        return LLMResponse(content=next(self.answers), finish_reason="stop")


@pytest.mark.parametrize("repair", [False, True])
async def test_react_identity_no_fetch_no_banner_and_preexit_repair(service, repair):
    await observed_identity()
    answers = ([f"{_FILENAME}\n正文证明增长会加速。"] if repair else []) + [_FILENAME]
    client = TextClient(answers)
    result = await run_agent_loop(
        llm=client,
        system_prompt="Return the filename only",
        user_message="Find a SpaceX file",
        config=LoopConfig(
            task_id="run", max_turns=5, loop_policy=LoopPolicy(no_tool_behavior="stop")
        ),
        tools=[],
        observers=[CorpusDeliveryObserver()],
    )
    assert client.calls == 1 + int(repair)
    assert result.final_content == _FILENAME
    assert not service.calls, "identity delivery must not force a fetch"
    outcome = publish_boundary(
        get_run_ledger(),
        final_text=result.final_content,
        answer_status="complete",
        announce_status=True,
    )
    assert outcome["answer_status"] == "complete"
    assert outcome["publish_status"] == "verified"
    assert outcome["final_text"] == _FILENAME
    assert outcome["verification"]["conclusions"][0]["verification_kind"] == "document_identity"


async def test_react_bad_prose_gets_only_one_repair_then_remains_partial(service):
    await observed_identity()
    client = TextClient(["No source binding for this assertion."] * 2)
    result = await run_agent_loop(
        llm=client,
        system_prompt="Answer",
        user_message="Question",
        config=LoopConfig(
            task_id="run", max_turns=5, loop_policy=LoopPolicy(no_tool_behavior="stop")
        ),
        tools=[],
        observers=[CorpusDeliveryObserver()],
    )
    assert client.calls == 2
    outcome = publish_boundary(
        get_run_ledger(),
        final_text=result.final_content,
        answer_status="complete",
        announce_status=True,
    )
    assert outcome["answer_status"] == "partial"
    assert outcome["publish_status"] == "draft"


async def test_identity_cannot_authorize_prose_unknown_or_changed_values(service):
    await observed_identity()
    ledger = get_run_ledger()
    manifest = prepare_delivery_manifest(_FILENAME, None, ledger)
    for text in (_FILENAME + "\nThis proves future growth.", "invented.pdf", "2026-10-24"):
        assert identity_manifest(text, ledger) is None
        with pytest.raises(ValueError, match="requires corpus_conclusions"):
            prepare_delivery_manifest(text, None, ledger)
        assert verify_manifest(manifest, ledger, final_text=text)["status"] != "verified"
    manifest["conclusions"][0]["document_identity"]["build_id"] = "other-build"
    assert verify_manifest(manifest, ledger, final_text=_FILENAME)["status"] != "verified"


def test_fetch_only_identity_does_not_change_search_coverage():
    ledger = get_run_ledger()
    ledger.record_fetch_result(
        json.dumps(
            {
                "ok": True,
                "doc_id": "cv2:build",
                "build_id": "build",
                "filename": "source.pdf",
                "document_title": "Source title",
                "published": "2026-11-06",
                "publication_date_basis": "explicit",
                "items": [],
            }
        )
    )
    assert not ledger.offered and ledger.all_offered_fetched() is None
    manifest = prepare_delivery_manifest("source.pdf\nSource title\n2026-11-06", None, ledger)
    assert (
        verify_manifest(manifest, ledger, final_text="source.pdf\nSource title\n2026-11-06")[
            "status"
        ]
        == "verified"
    )
    assert ledger.to_dict()["document_identities"]


async def test_last_turn_keeps_existing_downgrade_instead_of_retrying(service):
    await observed_identity()
    client = TextClient(["Unbound source claim."])
    result = await run_agent_loop(
        llm=client,
        system_prompt="Answer",
        user_message="Question",
        config=LoopConfig(
            task_id="run", max_turns=1, loop_policy=LoopPolicy(no_tool_behavior="stop")
        ),
        tools=[],
        observers=[CorpusDeliveryObserver()],
    )
    assert client.calls == 1
    assert (
        publish_boundary(
            get_run_ledger(),
            final_text=result.final_content,
            answer_status="complete",
            announce_status=True,
        )["answer_status"]
        == "partial"
    )


async def test_team_unchecked_work_delivers_identity_and_dispositions_in_one_call(
    service,
    delivery_run,
    monkeypatch,
):
    await observed_identity()
    bus, budget = delivery_run
    await add_task.func(
        [{"description": "Find filename"}, {"description": "Return filename", "kind": "delivery"}]
    )
    add_job(bus, "source", [])
    bind_assignment("run", ["t1"], "reviewer", "source")
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 100)
    observer = TeamDeliveryObserver(budget, coordination_tools=("deliver_answer", "update_task"))

    class Client:
        model = "scripted"
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            assert self.calls == 1
            names = {t["function"]["name"] for t in kwargs["tools"]}
            assert names == {"deliver_answer", "update_task"}
            assert not observer.active, "completed execution must not force wind-down"
            return LLMResponse(
                content="",
                finish_reason="tool_calls",
                tool_calls=[
                    {
                        "id": "finish",
                        "type": "function",
                        "function": {
                            "name": "deliver_answer",
                            "arguments": json.dumps(
                                {
                                    "content": _FILENAME,
                                    "updates": [
                                        {
                                            "id": "t1",
                                            "resolution": "resolved",
                                            "notes": "Requested filename located in search result",
                                        }
                                    ],
                                }
                            ),
                        },
                    }
                ],
            )

    result = await run_agent_loop(
        llm=Client(),
        system_prompt="Return filename",
        user_message="Find file",
        config=LoopConfig(task_id="run", max_turns=10),
        scope_metadata={SWARM_SCOPE_KEY: SimpleNamespace(original_question="Find file")},
        tools=[deliver_answer, update_task],
        observers=[observer],
    )
    assert result.final_content == _FILENAME
    assert result.stopped_by == "final_answer"
    assert observer.active
    assert all(t["resolution"] == "resolved" for t in snapshot_tasks("run"))
    outcome = publish_boundary(
        get_run_ledger(),
        final_text=result.final_content,
        answer_status="complete",
        announce_status=True,
    )
    assert outcome["final_text"] == _FILENAME and outcome["answer_status"] == "complete"


def failure_payload(code="budget_exceeded"):
    return {
        "ok": False,
        "error": "fetch_failed: see item_errors",
        "items": [],
        "doc_id": "cv2:private",
        "build_id": "private",
        "next_cursor": "private" * 500,
        "item_errors": [
            {"locator": f"chunk:private/unit:{i}", "code": code, "error": "Original failure " * 20}
            for i in range(17)
        ],
        "unresolved": [f"chunk:private/unit:{i}" for i in range(17)],
    }


@pytest.mark.parametrize("processor", [ReactToolResultPostProcessor, SwarmToolResultPostProcessor])
@pytest.mark.parametrize("code", ["budget_exceeded", "read_failure"])
def test_failed_fetch_processor_keeps_kind_and_full_audit(processor, code):
    full = failure_payload(code)
    visible = processor().process(
        ToolResult(
            name="corpus_fetch",
            args={},
            result=json.dumps(full),
            duration_ms=0,
            is_error=True,
            tool_call_id="failed",
        )
    )
    assert len(visible) <= 1500
    assert "private" not in visible
    assert json.loads(visible)["code"] == code
    assert json.loads(visible)["item_errors_count"] == 17
    projection.reset_snapshot_index()
    assert projection.materialize("corpus_fetch", visible) == full


@pytest.mark.parametrize("budget", [400, 1500])
async def test_public_fetch_failure_respects_request_budget(monkeypatch, budget):
    full = failure_payload()

    async def fail(*args):
        return json.dumps(full)

    monkeypatch.setattr(fetch_module, "_fetch", fail)
    visible = await fetch_module.corpus_fetch.func(ref="sref:test", max_chars=budget)
    assert len(visible) <= budget
    recovered = projection.materialize("corpus_fetch", visible)
    assert json.loads(visible)["next_cursor"] == recovered["next_cursor"]
    recovered["next_cursor"] = tool_refs.resolve_cursor_reference(recovered["next_cursor"])
    assert recovered == full
    assert json.loads(visible)["fetch_complete"] is False


def test_failed_fetch_snapshot_failure_does_not_leak(monkeypatch):
    def fail(*args, **kwargs):
        raise OSError("private store failure")

    monkeypatch.setattr(tool_refs, "store_metadata_snapshot", fail)
    visible = projection.project_tool_result("corpus_fetch", json.dumps(failure_payload()))
    assert "private" not in visible
    assert json.loads(visible)["code"] == "metadata_unavailable"
    assert projection.try_materialize("corpus_fetch", visible) is None


def test_legacy_failed_fetch_fitter_preserves_real_error(monkeypatch):
    monkeypatch.setenv("CORPUS_NAVIGATION_MODE", "off")
    visible = fetch_module.fit_structured_payload(json.dumps(failure_payload("read_failure")), 400)
    assert len(visible) <= 400
    assert json.loads(visible)["code"] == "read_failure"
