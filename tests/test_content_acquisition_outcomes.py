"""Business acquisition failures must survive the actual tool execution boundary."""

import importlib
import json
from types import SimpleNamespace

import pytest

from frontier_agent.core.runtime.loop.tool_exec import execute_tools


async def execute(tool, args):
    return (await execute_tools(
        [{"name": tool.name, "args": args, "id": "acquisition-1"}],
        {tool.name: tool}, timeout=5, turn=1, count_offset=0,
    ))[0]


@pytest.fixture(params=["web_fetch", "web_fetch_aligned"])
def fetch_module(monkeypatch, request):
    module = importlib.import_module(f"plugins.tools.{request.param}")

    async def public(url):
        return None

    async def scrape(url, callback, **kwargs):
        if "missing" in url:
            raise module.ScrapeUnavailable("empty")
        return "Source text: revenue is 42."

    monkeypatch.setattr(module, "non_public_url_error", public)
    monkeypatch.setattr(module, "scrape_result_cache", SimpleNamespace(get_or_scrape=scrape))
    if request.param == "web_fetch":
        monkeypatch.setattr(module, "get_config", lambda: SimpleNamespace())
        monkeypatch.setattr(module, "unrendered_kind", lambda content: None)
        monkeypatch.setattr(module, "_scrape_cache", SimpleNamespace(
            check=lambda url: None, record_success=lambda url: None,
        ))
    else:
        async def extract(content, info):
            return {"success": True, "extracted_info": content}

        monkeypatch.setattr(module, "_extract_info_with_llm", extract)
        monkeypatch.setattr(module, "_unrendered_kind", lambda content: None)
        monkeypatch.setattr(module, "web_fetch", module.web_fetch_aligned, raising=False)
    return module


async def test_empty_fetch_is_not_a_successful_content_acquisition(fetch_module):
    result = await execute(fetch_module.web_fetch, {"url": "https://example.org/missing"})
    assert result.is_error is True
    payload = json.loads(result.result)
    assert payload["status"] == "unavailable"
    assert payload["content"] == ""


async def test_mixed_batch_retains_content_and_individual_failure(fetch_module):
    result = await execute(fetch_module.web_fetch, {
        "url": ["https://example.org/present", "https://example.org/missing"],
    })
    assert result.is_error is True
    payload = json.loads(result.result)
    assert payload["status"] == "partial"
    assert [item["status"] for item in payload["items"]] == ["success", "unavailable"]
    assert "revenue is 42" in payload["items"][0]["content"]


async def test_low_coverage_page_retains_text_without_claiming_full_acquisition(
    fetch_module, monkeypatch,
):
    name = "_unrendered_kind" if hasattr(fetch_module, "_unrendered_kind") else "unrendered_kind"
    monkeypatch.setattr(fetch_module, name, lambda content: "empty")
    result = await execute(fetch_module.web_fetch, {"url": "https://example.org/present"})
    payload = json.loads(result.result)
    assert result.is_error is True
    assert payload["status"] == "partial"
    assert "revenue is 42" in payload["content"]


async def test_vision_unavailable_is_not_an_image_analysis(monkeypatch):
    module = importlib.import_module("plugins.tools.view_image")

    async def unavailable(*args):
        return "Error: 503 Service Unavailable"

    monkeypatch.setattr(module, "_call_vision_api", unavailable)
    result = await execute(module.view_image, {"image_path_or_url": "https://example.org/chart.png"})
    assert result.is_error is True
    payload = json.loads(result.result)
    assert payload["status"] == "unavailable"
    assert payload["content"] == ""
    assert "image was loaded successfully" not in payload["detail"]


def test_read_file_image_and_pdf_limits_are_structured():
    from frontier_agent.core.tool import ToolOutcome
    from plugins.tools.read_file import _structured_read_outcome

    image = _structured_read_outcome(
        "/inputs/chart.png",
        "auto",
        None,
        "file: chart.png\ntype: image/png\nnote: image — vision unavailable; not read.",
    )
    assert isinstance(image, ToolOutcome)
    image_payload = json.loads(image.result)
    assert image_payload["status"] == "unavailable"
    assert image_payload["content"] == ""
    assert image_payload["coverage"]["media_type"] == "image"

    pdf = _structured_read_outcome(
        "/inputs/report.pdf",
        "auto",
        None,
        "(PDF: 3 pages) — overview\n<!-- page 1 -->\ntext\nfigure not read: chart",
    )
    assert isinstance(pdf, ToolOutcome)
    pdf_payload = json.loads(pdf.result)
    assert pdf_payload["status"] == "partial"
    assert "page 1" in pdf_payload["content"]
    assert pdf_payload["coverage"]["document_complete"] is False

    hidden_layer = _structured_read_outcome(
        "/inputs/layered.pdf",
        "image",
        None,
        "optional layers (OCG, may be hidden): annotations",
    )
    assert isinstance(hidden_layer, ToolOutcome)
    assert json.loads(hidden_layer.result)["status"] == "partial"


async def test_read_file_limit_reaches_member_acquisition_metadata():
    from frontier_agent.core.loop_types import ToolResult, notify_tool_result
    from plugins.tools.read_file import _structured_read_outcome
    from workflows.agent_team.observers.content_acquisition import ContentAcquisitionObserver

    outcome = _structured_read_outcome(
        "/inputs/report.pdf",
        "text",
        "1-2",
        "(PDF: 10 pages (pages 1-2))\ntext only",
    )
    observer = ContentAcquisitionObserver()
    ctx = SimpleNamespace(metadata={})
    result = ToolResult(
        name="read_file",
        args={"path": "/inputs/report.pdf", "pdf_mode": "text", "pages": "1-2"},
        result=outcome.result,
        duration_ms=1,
        tool_call_id="read-1",
        is_error=True,
    )
    await notify_tool_result([observer], ctx, result)

    observation = ctx.metadata["content_acquisition"][0]
    assert observation["tool"] == "read_file"
    assert observation["status"] == "partial"
    assert observation["coverage"]["requested_pages"] == "1-2"
    assert observation["detail"]


async def test_acquisition_limits_survive_member_report_and_later_failed_retry(fetch_module):
    from frontier_agent.core.loop_types import AgentLoopResult, notify_tool_result
    from workflows.agent_team.final_report import finalize_team_report
    from workflows.agent_team.observers.content_acquisition import ContentAcquisitionObserver

    observer = ContentAcquisitionObserver()
    ctx = SimpleNamespace(metadata={})
    missing = await execute(fetch_module.web_fetch, {"url": "https://example.org/missing"})
    await notify_tool_result([observer], ctx, missing)
    success = await execute(fetch_module.web_fetch, {"url": "https://example.org/present"})
    await notify_tool_result([observer], ctx, success)
    assert not success.is_error
    # A failed later request to an already-read source does not erase the read.
    from plugins.tools._content_outcome import content_limitation

    success.result = content_limitation("https://example.org/present", "later failure").result
    success.is_error = True
    await notify_tool_result([observer], ctx, success)
    result = AgentLoopResult(messages=[], final_content="All good", stopped_by="submit_report")
    await observer.on_loop_end(result)
    observations = result.metadata["content_acquisition"]
    assert observations == ctx.metadata["content_acquisition"]
    assert observations[1]["obtained"] is True
    assert observations[1]["last_attempt_status"] == "unavailable"
    out = finalize_team_report(
        "The supplied document states revenue is 42.", source="agent", answer_status="complete",
        stopped_by="final_answer", wind_down={"job_outcomes": [{
            "job_id": "j1", "required": True, "status": "complete",
            "content_acquisition": observations,
        }]},
    )
    assert out["answer_status"] == "complete"  # an access failure alone says nothing about necessity
    assert len(out["report_contract"]["acquisition_limits"]) == 1
    assert "https://example.org/missing" in out["final_answer"]
    assert "https://example.org/present" not in out["final_answer"]
