"""7d0: short lookups, terminal schema repair, and source-backed quote checks."""

import importlib
import json
from copy import deepcopy
from types import SimpleNamespace

import pytest

from frontier_agent.core.llm import LLMResponse
from frontier_agent.core.loop_types import LoopConfig, ToolResult
from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
from frontier_agent.core.tool import tool
from plugins.tools._verification import (
    VerificationCheck,
    bind_checks,
    reset_verification_scope,
    set_verification_scope,
    validate_results,
)
from plugins.tools.submit_report import submit_report
from tests.test_agent_team_verification import binding, make_bound, planned_items, verdict_for
from tests.test_team_verification_admission import admission_run as _admission_run
from workflows._shared.research.observers.finalize_answer_observer import FinalizeAnswerObserver
from workflows.agent_team.observers.member_progress import MemberProgressObserver

admission_run = _admission_run


@pytest.mark.parametrize("defect", ["summary", "missing_content", "empty"])
async def test_final_turn_submission_repairs_without_research_or_verdict_changes(defect):
    check = binding(version="a" * 64)
    metadata = {"verification_checks": [check], "verification_events": []}
    verdict = verdict_for(check)
    research_calls = []

    @tool
    async def read_source() -> str:
        """Read a deterministic source."""
        research_calls.append(1)
        return "amount 50"

    class Client:
        calls = 0

        async def chat(self, messages, **kwargs):
            self.calls += 1
            if self.calls <= 3:
                name, args = "read_source", {}
            elif self.calls == 4:
                name = "submit_report"
                args = {"verification_results": [deepcopy(verdict)]}
                if defect == "summary":
                    args["summary"] = "Scope: amount. Finding: 50."
                elif defect == "empty":
                    args = {}
            else:
                assert self.calls == 5, "terminal repair must be bounded"
                assert "submission repair" in str(messages)
                name = "submit_report"
                args = {
                    "content": "Scope: amount. Finding: 50.",
                    "verification_results": [deepcopy(verdict)],
                }
            return LLMResponse(
                content="", tool_calls=[{"id": f"c{self.calls}", "name": name, "args": args}]
            )

    client = Client()
    token = set_verification_scope("review", metadata)
    try:
        result = await run_agent_loop(
            system_prompt="Check",
            user_message="Review",
            llm=client,
            tools=[read_source, submit_report],
            config=LoopConfig(max_turns=4),
            observers=[
                MemberProgressObserver(metadata),
                FinalizeAnswerObserver(tool_names=["submit_report"]),
            ],
        )
        assert result.stopped_by == "final_answer"
        assert client.calls <= 5 and len(research_calls) == 3
        assert len(metadata["verification_events"]) == 1
        assert metadata["verification_events"][0]["binding_id"] == check["binding_id"]
        # Every remaining assistant call has a result; rollback must not orphan calls.
        requested = {c["id"] for m in result.messages for c in m.get("tool_calls", [])}
        answered = {m["tool_call_id"] for m in result.messages if m.get("role") == "tool"}
        assert requested == answered
    finally:
        reset_verification_scope(token)


async def test_submission_repair_is_once_and_cannot_execute_research_or_change_verdict():
    check = binding(version="a" * 64)
    observer = MemberProgressObserver({"verification_checks": [check]})
    args = {"verification_results": [verdict_for(check)]}
    ctx = SimpleNamespace(tool_calls=[{"name": "submit_report", "args": args}], metadata={})
    first = await observer.on_llm_response(ctx)
    assert first.continue_to_next_turn and first.pop_last_message
    before = await observer.on_before_llm(ctx)
    assert before.allowed_tool_names == ("submit_report",)
    denied = await observer.on_tool_call(ctx, {"name": "corpus_search", "args": {"query": "again"}})
    assert denied.skip_is_error
    changed = deepcopy(args)
    changed["content"] = "Changed answer"
    changed["verification_results"][0]["verdict"] = "unchecked"
    denied = await observer.on_tool_call(ctx, {"name": "submit_report", "args": changed})
    assert denied.skip_is_error
    assert await observer.on_llm_response(ctx) is None


@pytest.mark.parametrize(
    "mode,quote,accepted",
    [
        ("exact", "AI\u00a0安全", True),
        ("exact", "AI 安全", False),
        ("nbsp_space", "AI 安全", True),
        ("nbsp_space", "AI 完全安全", False),
    ],
)
def test_quote_check_uses_captured_source_not_model_transcription(tmp_path, mode, quote, accepted):
    bus, spec, _ = make_bound(tmp_path)
    bus._jobs["source"].result.metadata["corpus_evidence"] = [
        {"doc_id": "cv2:" + "a" * 64, "locator": "chunk:original", "text": "AI\u00a0安全"}
    ]
    spec = VerificationCheck.model_validate(
        {
            **spec.model_dump(),
            "subject": {"text": f"引文：{quote}"},
            "quote_checks": [
                {"source_key": "source", "locator": "chunk:original", "quote": quote, "mode": mode}
            ],
        }
    )
    checks, _ = bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )
    comparison = checks[0]["quote_comparisons"][0]
    assert comparison["raw_match"] is (quote == "AI\u00a0安全")
    assert comparison["matched"] is accepted
    token = set_verification_scope("review", {"verification_checks": checks})
    try:
        verdict = verdict_for(
            checks[0], method="My copied strings are equal", detail="equal_raw=True"
        )
        if accepted:
            assert validate_results([verdict])
        else:
            with pytest.raises(ValueError, match="quote"):
                validate_results([verdict])
    finally:
        reset_verification_scope(token)


async def test_date_lookup_stops_broad_search_after_supported_match():
    # Historical P41 selector retained for catalog compatibility. The retired date
    # hint no longer affects convergence; see the explicit benchmark migration note.
    observer = MemberProgressObserver({"find_one_published_on": "2026-11-06"})
    ctx = SimpleNamespace(metadata={})
    payload = {
        "ok": True,
        "hits": [
            {
                "doc_id": "cv2:" + "a" * 64,
                "published": "2026-11-06",
                "evidence_contract": "native-search-evidence-v2",
                "excerpts": [{"text": "2026-11-06 研究", "ref": "eref:" + "b" * 64 + ":0"}],
            }
        ],
        "coverage": {"processing": "partial"},
    }
    await observer.on_tool_result(
        ctx, ToolResult("corpus_search", {}, json.dumps(payload), 1, "c1", False)
    )
    decision = await observer.on_before_llm(ctx)
    assert decision is None
    allowed = await observer.on_tool_call(
        ctx,
        {
            "name": "corpus_fetch",
            "args": {
                "doc_id": "cv2:" + "a" * 64,
                "locator": payload["hits"][0]["excerpts"][0]["ref"],
            },
        },
    )
    assert allowed is None
    # An unsuitable candidate may be replaced within the original task.
    allowed = await observer.on_tool_call(
        ctx, {"name": "corpus_search", "args": {"query": "necessary replacement on same date"}}
    )
    assert allowed is None


async def test_checkpoint_nudge_escalates_after_unsubmitted_turns():
    """Round-2 verifier shape: read-only turns while checks stay unsubmitted.

    The first nudge asks for one verdict per turn. When two full turns pass
    with pending checks and no checkpoint, the injection escalates to demand
    submit-first; a checkpointed verdict re-arms the tracker to the normal
    per-check nudge.
    """
    check = binding(version="a" * 64)
    observer = MemberProgressObserver({"verification_checks": [check]})
    ctx = SimpleNamespace(metadata={}, turn=1)
    first = await observer.on_before_llm(ctx)
    assert "[next verification check]" in first.inject_messages[0]
    assert "overdue" not in first.inject_messages[0]

    ctx.turn = 3
    escalated = await observer.on_before_llm(ctx)
    assert "[verification checkpoint overdue]" in escalated.inject_messages[0]
    assert "unchecked" in escalated.inject_messages[0]

    ctx.turn = 4
    await observer.on_tool_result(
        ctx, ToolResult("submit_report", {}, "checkpointed", 4, "c1", False)
    )
    ctx.turn = 5
    normal = await observer.on_before_llm(ctx)
    assert "[next verification check]" in normal.inject_messages[0]
    assert "overdue" not in normal.inject_messages[0]


@pytest.mark.parametrize("mutation", ["date", "preview", "failed"])
async def test_date_lookup_does_not_stop_on_unsupported_candidate(mutation):
    observer = MemberProgressObserver({"find_one_published_on": "2026-11-06"})
    hit = {
        "doc_id": "cv2:" + "a" * 64,
        "published": "2026-11-06",
        "evidence_contract": "native-search-evidence-v2",
        "excerpts": [{"text": "Report", "ref": "eref:" + "b" * 64 + ":0"}],
    }
    if mutation == "date":
        hit["published"] = "2026-11-05"
    if mutation == "preview":
        hit.pop("excerpts")
    ctx = SimpleNamespace(metadata={})
    await observer.on_tool_result(
        ctx,
        ToolResult(
            "corpus_search",
            {},
            json.dumps({"ok": mutation != "failed", "hits": [hit]}),
            1,
            "c",
            mutation == "failed",
        ),
    )
    assert await observer.on_before_llm(ctx) is None


async def test_search_coverage_counts_do_not_repeat_unusable_source_hashes(monkeypatch):
    module = importlib.import_module("plugins.tools.corpus_search")
    coverage = {
        "processing": "partial",
        "availability": "unknown",
        "native": {
            "sources": 148,
            "cutoff": "2026-11-06",
            "unknown_date_sources": [f"{i:064x}" for i in range(80)],
        },
    }

    class Backend:
        def search_with_coverage(self, query, *, limit):
            return [], coverage

    monkeypatch.setattr(module, "get_service", lambda: Backend())
    response = json.loads(await module.corpus_search.func("today"))
    native = response["coverage"]["native"]
    assert native["unknown_date_source_count"] == 80
    assert "unknown_date_sources" not in native
    assert native["cutoff"] == "2026-11-06"
    assert len(coverage["native"]["unknown_date_sources"]) == 80, "Do not mutate service coverage"
    from plugins.tools._corpus_scope import compact_corpus_limits, corpus_limits

    observation = {
        "tool": "corpus_search",
        "obtained": True,
        "coverage": {
            "processing": "complete",
            "availability": "available",
            "native": native,
        },
    }
    assert corpus_limits([observation])
    assert compact_corpus_limits([observation])[0]["coverage"]["native"]["unknown_date_sources"]


async def test_date_lookup_assignment_reaches_runtime_metadata(admission_run):
    from plugins.tools.assign_task import AgentTeamAssignmentSpec, agent_team_assign_task

    bus, _ = admission_run
    result = await agent_team_assign_task.func(
        tasks=[
            {
                "agent": "reviewer",
                "prompt": "Find any one report on the date",
                "find_one_published_on": "2026-11-06",
            }
        ]
    )
    assert "Submitted" in result
    entry = bus.list_task_jobs("run")[0]
    assert "find_one_published_on" not in entry.item.metadata
    with pytest.raises(ValueError):
        AgentTeamAssignmentSpec(agent="reviewer", prompt="Find", find_one_published_on="2026-02-30")


def test_quote_binding_rejects_unbound_sources_and_persisted_false_pass(tmp_path):
    from plugins.tools._verification import project_checks
    from tests.test_agent_team_verification import add_job

    bus, spec, _ = make_bound(tmp_path)
    bus._jobs["source"].result.metadata["corpus_evidence"] = [
        {"doc_id": "cv2:" + "a" * 64, "locator": "chunk:original", "text": "AI\u00a0安全"}
    ]
    data = {
        **spec.model_dump(),
        "subject": {"text": "AI 安全"},
        "quote_checks": [
            {
                "source_key": "source",
                "locator": "chunk:original",
                "quote": "AI 安全",
                "mode": "exact",
            }
        ],
    }
    for field, value in [
        ("source_key", "unbound"),
        ("locator", "guessed"),
        ("quote", "not in subject"),
    ]:
        invalid = deepcopy(data)
        invalid["quote_checks"][0][field] = value
        with pytest.raises(ValueError):
            bind_checks(
                [VerificationCheck.model_validate(invalid)],
                bus=bus,
                task_id="run",
                work_items=planned_items(),
                required=True,
                outputs_root=tmp_path,
            )
    checks, _ = bind_checks(
        [VerificationCheck.model_validate(data)],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )
    event = verdict_for(checks[0])
    projected = project_checks(
        [
            {
                "job_id": "review",
                "verification_checks": checks,
                "verification_events": [event],
                "status": "complete",
            }
        ]
    )
    assert projected["checks"][0]["verdict"] != "pass"
    add_job(bus, "failed", checks, verdicts=["fail"])
    # Retaining the same quote cannot silently remove the exact-match obligation.
    dropped = {
        **data,
        "quote_checks": [],
        "replaces_job_id": "failed",
        "revision_kind": "subject",
        "revision_reason": "omit quote check",
    }
    with pytest.raises(ValueError, match="quote"):
        bind_checks(
            [VerificationCheck.model_validate(dropped)],
            bus=bus,
            task_id="run",
            work_items=planned_items(),
            required=True,
            outputs_root=tmp_path,
        )
