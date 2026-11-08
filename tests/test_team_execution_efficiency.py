"""Scope, conditional acquisition, delivery readiness and presentation regressions."""

import importlib
import json
from types import SimpleNamespace

import pytest

from frontier_agent.core.loop_types import ToolResult, notify_tool_result
from plugins.tools._content_outcome import content_limitation
from plugins.tools.task_board import snapshot_tasks
from tests.test_agent_team_verification import add_job, binding
from tests.test_team_atomic_delivery import delivery_run as _delivery_run
from tests.test_team_atomic_delivery import prepare, turn_context
from workflows.agent_team.delivery import TeamDeliveryObserver
from workflows.agent_team.final_report import finalize_team_report
from workflows.agent_team.lifecycle import snapshot_job_outcomes
from workflows.agent_team.observers.content_acquisition import ContentAcquisitionObserver

delivery_run = _delivery_run
fetch_module = importlib.import_module("plugins.tools.web_fetch")


@pytest.mark.parametrize("primary", ["readable", "failed", "partial", "blocked"])
async def test_fallback_runs_only_after_eligible_primary_outcome(monkeypatch, primary):
    calls = []

    async def fetch(url, focus):
        calls.append(url)
        if url == "https://source.test/a":
            if primary == "readable":
                return "Tuesday, Room 204."
            return content_limitation(
                url, "Primary unavailable", status={"failed": "failed", "partial": "partial", "blocked": "policy_blocked"}[primary],
                content="Tuesday" if primary == "partial" else "",
            )
        return "Tuesday, Room 204."

    monkeypatch.setattr(fetch_module, "_fetch_with_budget", fetch)
    result = await fetch_module.web_fetch.func(
        url="https://source.test/a", fallback_urls=["https://source.test/b", "https://source.test/c"]
    )
    assert calls == (["https://source.test/a"] if primary in {"readable", "blocked"} else ["https://source.test/a", "https://source.test/b"])
    if primary == "blocked":
        assert result.is_error
    elif primary != "readable":
        payload = json.loads(result)
        assert payload["source"] == "https://source.test/b"
        assert payload["items"][0]["source"] == "https://source.test/a"
        assert payload["ok"] is True


async def test_independent_fetch_batch_is_preserved(monkeypatch):
    calls = []

    async def fetch(url, focus):
        calls.append(url)
        return "Independent evidence"

    monkeypatch.setattr(fetch_module, "_fetch_with_budget", fetch)
    await fetch_module.web_fetch.func(url=["https://a.test", "https://b.test"])
    assert set(calls) == {"https://a.test", "https://b.test"}


async def test_exhausted_fallback_retains_all_failed_attempts(monkeypatch):
    async def fetch(url, focus):
        return content_limitation(url, "Unavailable")

    monkeypatch.setattr(fetch_module, "_fetch_with_budget", fetch)
    result = await fetch_module.web_fetch.func(url="https://a.test", fallback_urls=["https://b.test"])
    assert result.is_error
    assert [i["source"] for i in json.loads(result.result)["items"]] == ["https://a.test", "https://b.test"]


async def test_fallback_receipt_attributes_content_to_successful_source(monkeypatch):
    async def fetch(url, focus):
        return content_limitation(url, "Unavailable") if url.endswith("a.test") else "Read from backup."

    monkeypatch.setattr(fetch_module, "_fetch_with_budget", fetch)
    args = {"url": "https://a.test", "fallback_urls": ["https://b.test"]}
    result = await fetch_module.web_fetch.func(**args)
    ctx = SimpleNamespace(metadata={})
    await notify_tool_result([ContentAcquisitionObserver()], ctx, ToolResult(
        name="web_fetch", args=args, result=result, duration_ms=1, tool_call_id="fallback", is_error=False,
    ))
    observed = {o["source"]: o for o in ctx.metadata["content_acquisition"]}
    assert not observed["https://a.test"]["obtained"]
    assert observed["https://b.test"]["obtained"]


async def test_fallback_does_not_change_independent_batch_semantics(monkeypatch):
    async def unexpected(*_):
        pytest.fail("invalid mixed dependency request must not fetch anything")

    monkeypatch.setattr(fetch_module, "_fetch_with_budget", unexpected)
    with pytest.raises(ValueError, match="one primary"):
        await fetch_module.web_fetch.func(url=["https://a.test", "https://b.test"], fallback_urls=["https://c.test"])


async def test_publication_keeps_audit_in_contract_without_appending_pass_hashes(delivery_run):
    bus, _ = delivery_run
    await prepare(bus)
    draft = "The checked amount is 50."
    out = finalize_team_report(
        draft, source="agent", answer_status="complete", stopped_by="final_answer",
        tasks=[{**t, "resolution": "resolved"} for t in snapshot_tasks("run")],
        wind_down={"job_outcomes": snapshot_job_outcomes(bus, "run")},
    )
    assert out["final_answer"] == draft
    assert out["report_contract"]["verification_checks"][0]["verdict"] == "pass"
    assert "sha256" in json.dumps(out["report_contract"])


def test_missing_evidence_is_disclosed_once_and_execution_counts_stay_in_audit():
    gap = "Shipping is unknown."
    out = finalize_team_report(
        "The subtotal is 44. " + gap, source="agent", answer_status="partial",
        stopped_by="final_answer", tasks=[{"id": "t1", "description": "Total", "resolution": "blocked", "gap": gap}],
        wind_down={"status": "complete", "collected_count": 2, "unresolved_count": 0},
    )
    assert out["final_answer"].count(gap) == 1
    assert "Reports collected during wind-down" not in out["final_answer"]
    assert out["report_contract"]["wind_down"]["collected_count"] == 2
    assert out["answer_status"] == "partial"


async def test_delivery_admission_supplies_exact_passed_publication_text(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus)
    checked = binding()
    checked["publication_excerpt"] = True
    checked["subject"]["text"] = "4 × 5 + 2 × 12 = 44."
    add_job(bus, "j1", [checked], verdicts=["pass"])
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 500)
    iv = await TeamDeliveryObserver(budget).on_before_llm(turn_context())
    assert checked["subject"]["text"] in " ".join(iv.inject_messages)


async def test_running_member_hides_delivery_before_model_generation(delivery_run, monkeypatch):
    bus, budget = delivery_run
    await prepare(bus)
    bus._jobs["j1"].status = "running"
    monkeypatch.setattr("workflows.agent_team.delivery.time.monotonic", lambda: 500)
    observer = TeamDeliveryObserver(budget, coordination_tools=("assign_task", "collect_reports", "deliver_answer"))
    iv = await observer.on_before_llm(turn_context())
    assert "deliver_answer" not in iv.allowed_tool_names
    assert "collect_reports" in iv.allowed_tool_names
    assert not observer.active


@pytest.mark.parametrize("verdict", ["fail", "unchecked"])
async def test_hiding_audit_never_hides_required_verification_failure(delivery_run, verdict):
    bus, _ = delivery_run
    await prepare(bus, verdict)
    out = finalize_team_report(
        "The proposed amount is 50.", source="agent", answer_status="complete",
        stopped_by="final_answer", tasks=snapshot_tasks("run"),
        wind_down={"job_outcomes": snapshot_job_outcomes(bus, "run")},
    )
    assert out["answer_status"] == "partial"
    assert "amount" in out["final_answer"].lower()
    assert out["report_contract"]["verification_checks"][0]["verdict"] == verdict
