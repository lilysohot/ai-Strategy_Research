"""Web evidence must survive the same team handoff as corpus evidence."""

import json

import pytest

from frontier_agent.core.loop_types import AgentLoopResult, ToolResult
from plugins.tools._verification import bind_checks
from tests.test_agent_team_verification import make_bound, planned_items
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_atomic_delivery import prepare, turn_context
from workflows.agent_team.delivery import TeamDeliveryObserver
from workflows.agent_team.observers.content_acquisition import ContentAcquisitionObserver
from workflows.agent_team.observers.member_progress import MemberProgressObserver

delivery_run = _delivery_run
URL = "https://example.test/source"
BODY = "Publication date unknown. 20–25 TB only with 30-day retention."


async def observe(body, *, urls=URL, error=False, focus=""):
    observer = ContentAcquisitionObserver()
    ctx = turn_context()
    await observer.on_tool_result(
        ctx,
        ToolResult(
            name="web_fetch",
            args={"url": urls, "info_to_extract": focus},
            result=body,
            duration_ms=1,
            tool_call_id="fetch",
            is_error=error,
        ),
    )
    result = AgentLoopResult(messages=[], final_content="A researcher's interpretation")
    await observer.on_loop_end(result)
    return result, ctx


@pytest.mark.parametrize("structured", [False, True])
async def test_web_original_binds_into_verifier_and_changes_binding(tmp_path, structured):
    payload = (
        json.dumps(
            {
                "ok": True,
                "items": [{"ok": True, "status": "success", "source": URL, "content": BODY}],
            }
        )
        if structured
        else BODY
    )
    result, ctx = await observe(payload)
    assert ctx.metadata["web_evidence"] == result.metadata["web_evidence"]
    bus, spec, _ = make_bound(tmp_path)
    bus._jobs["source"].result.metadata.update(result.metadata)
    first, prompt = bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )
    assert BODY in prompt and URL in prompt
    result, _ = await observe(BODY.replace("30-day", "60-day"))
    bus._jobs["source"].result.metadata.update(result.metadata)
    second, _ = bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )
    assert first[0]["binding_id"] != second[0]["binding_id"]


async def test_mixed_batch_preserves_success_and_partial_but_not_failure():
    result, _ = await observe(
        json.dumps(
            {
                "ok": False,
                "items": [
                    {"ok": True, "status": "success", "source": URL, "content": BODY},
                    {
                        "ok": False,
                        "status": "partial",
                        "source": URL + "/partial",
                        "content": "Only abstract",
                    },
                    {
                        "ok": False,
                        "status": "failed",
                        "source": URL + "/failed",
                        "content": "Failure diagnostic",
                    },
                ],
            }
        ),
        urls=[URL, URL + "/partial", URL + "/failed"],
        error=True,
    )
    records = result.metadata["web_evidence"]
    assert [r["status"] for r in records] == ["success", "partial"]
    assert "Failure diagnostic" not in str(records)
    assert not result.metadata["content_acquisition"][1]["obtained"]


async def test_successful_plain_batch_keeps_url_body_pairing():
    result, _ = await observe(
        f"[1] URL: {URL}\n    Info: {BODY}\n\n[2] URL: {URL}/b\n    Info: Independent second page",
        urls=[URL, URL + "/b"],
    )
    assert [(r["source"], r["text"]) for r in result.metadata["web_evidence"]] == [
        (URL, BODY),
        (URL + "/b", "Independent second page"),
    ]


async def test_json_string_batch_uses_the_same_per_page_attribution_as_a_list():
    urls = [URL, URL + "/b"]
    focuses = ["retention", "market size"]
    result, _ = await observe(
        f"[1] URL: {urls[0]}\n    Info: {BODY}\n\n"
        f"[2] URL: {urls[1]}\n    Info: Independent second page",
        urls=json.dumps(urls),
        focus=json.dumps(focuses),
    )
    assert [(r["source"], r["text"]) for r in result.metadata["web_evidence"]] == [
        (urls[0], BODY),
        (urls[1], "Independent second page"),
    ]
    assert all(r["content_kind"] == "focused_extraction" for r in result.metadata["web_evidence"])


async def test_focused_extraction_is_not_presented_as_original(tmp_path):
    result, _ = await observe("Summary claims 20 TB", focus="capacity")
    bus, spec, _ = make_bound(tmp_path)
    bus._jobs["source"].result.metadata.update(result.metadata)
    _, prompt = bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )
    assert result.metadata["web_evidence"][0]["content_kind"] == "focused_extraction"
    assert "not original source text" in prompt


async def test_web_source_triggers_early_member_handoff(monkeypatch):
    monkeypatch.setattr("workflows.agent_team.observers.member_progress.time.monotonic", lambda: 0)
    observer = MemberProgressObserver({})
    _, ctx = await observe(BODY)
    monkeypatch.setattr("workflows.agent_team.observers.member_progress.time.monotonic", lambda: 20)
    decision = await observer.on_before_llm(ctx)
    assert decision is not None
    assert "[early research handoff]" in decision.inject_messages[0]


async def test_web_only_delivery_does_not_request_corpus_manifest(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus)
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 786)
    decision = await TeamDeliveryObserver(budget).on_before_llm(turn_context())
    prompt = " ".join(decision.inject_messages)
    assert "include corpus_conclusions" not in prompt
    assert "Omit corpus_conclusions" in prompt
    assert "job ID" in prompt


def test_configured_verification_window_is_not_consumed_by_delivery_reserve():
    from workflows.agent_team.nodes.main_agent import _build_team_phase_budget

    budget = _build_team_phase_budget(
        started_monotonic_s=0,
        research_wall_s=359,
        publication_phase_timeout_s=90,
        verification_phase_timeout_s=90,
        hard_deadline_monotonic_s=600,
        finalization_timeout_s=45,
        wind_down_timeout_s=15,
        worst_case_tool_s=45,
        publication_state={},
    )
    actual_deadline = budget.deadline_for_job(can_publish=False, is_verification=True)
    assert actual_deadline - budget.research_deadline_s >= 90
    assert budget.publication_deadline_s - budget.delivery_start_s >= 90


async def test_real_web_fetch_mixed_result_retains_originals(monkeypatch):
    import importlib

    from plugins.tools._content_outcome import content_limitation

    module = importlib.import_module("plugins.tools.web_fetch")

    async def fetch(url, focus):
        return BODY if url == URL else content_limitation(url, "No access")

    monkeypatch.setattr(module, "_fetch_with_budget", fetch)
    response = await module.web_fetch.func(url=[URL, URL + "/blocked"])
    result, _ = await observe(
        response.result, urls=[URL, URL + "/blocked"], error=response.is_error
    )
    assert len(result.metadata["web_evidence"]) == 1
    assert result.metadata["web_evidence"][0]["text"] == BODY
    assert [r["obtained"] for r in result.metadata["content_acquisition"]] == [True, False]


async def test_large_web_sources_are_bounded_and_omission_is_explicit():
    from plugins.tools._web_handoff import render_web_handoff

    result, _ = await observe("QUALIFIED_ORIGINAL " * 3000)
    text = render_web_handoff({"first": result.metadata["web_evidence"]})
    assert len(text) < 34000
    assert '"text_omitted": true' in text
    assert URL in text
    assert "not read evidence" in text


async def test_web_text_is_deduplicated_across_source_jobs():
    from plugins.tools._web_handoff import render_web_handoff

    result, _ = await observe(BODY)
    text = render_web_handoff(
        {"first": result.metadata["web_evidence"], "second": result.metadata["web_evidence"]}
    )
    assert text.count(BODY) == 1
    assert '"source_job": "second"' in text
    assert '"same_text_as_source": "first"' in text


def test_web_handoff_prioritizes_late_direct_evidence_for_the_bound_claim():
    from plugins.tools._web_handoff import render_web_handoff

    filler = "Unrelated model leaderboard material. " * 900
    direct = "据行业机构测算，2026年海外AI短剧全年规模约6.5亿美元；这是估算值，不是平台已实现收入。"
    sources = {
        "model_job": [
            {
                "source": "https://example.test/models",
                "text": filler,
                "status": "success",
                "content_kind": "focused_extraction",
                "sha256": "a" * 64,
            }
        ],
        "industry_job": [
            {
                "source": "https://example.test/industry",
                "text": direct,
                "status": "success",
                "content_kind": "focused_extraction",
                "sha256": "b" * 64,
            }
        ],
    }
    text = render_web_handoff(
        sources,
        focus_text="海外AI短剧规模约6.5亿美元，必须保留估算属性",
        body_budget=4000,
    )
    assert direct in text
    assert len(text) < 8000


@pytest.mark.parametrize("urls", [[URL], [URL, URL + "/b"]])
async def test_aligned_web_fetch_keeps_single_and_multi_page_attribution(monkeypatch, urls):
    import importlib

    module = importlib.import_module("plugins.tools.web_fetch_aligned")

    async def fetch(url, focus, headers):
        return BODY if url == URL else "Second source"

    monkeypatch.setattr(module, "_fetch_single", fetch)
    response = await module.web_fetch_aligned.func(url=urls)
    result, _ = await observe(response, urls=urls)
    records = result.metadata["web_evidence"]
    assert [r["source"] for r in records] == urls
    assert records[0]["text"] == BODY


async def test_aligned_error_is_not_web_evidence():
    result, _ = await observe("[ERROR]: Unexpected error: unavailable")
    assert not result.metadata["web_evidence"]
    assert not result.metadata["content_acquisition"][0]["obtained"]
