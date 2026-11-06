"""Known-defect probes, explicitly selected by the evaluator, never xfailed."""

import json
from pathlib import Path

from frontier_agent.core.loop_types import AgentLoopResult, ToolResult, TurnContext
from plugins.tools._verification import bind_checks
from tests.test_agent_team_verification import make_bound, planned_items
from workflows.agent_team.observers.content_acquisition import ContentAcquisitionObserver


async def test_web_original_survives_member_handoff(tmp_path: Path) -> None:
    """Exercise production observer -> result -> bound verifier prompt, not a mock scorer."""
    url = "https://fixtures.invalid/date-source"
    original = "SOURCE_SENTINEL_9A7: Publication date is unknown. Trial cohort contains 17 sites."
    observer = ContentAcquisitionObserver()
    context = TurnContext(
        turn=1,
        max_turns=2,
        task_id="run",
        role_id="researcher",
        ai_text="",
        thinking="",
        tool_calls=[],
        messages=[],
        usage={},
        metadata={},
    )
    await observer.on_tool_result(
        context,
        ToolResult(
            name="web_fetch",
            args={"url": url},
            result=json.dumps(
                {
                    "ok": True,
                    "status": "success",
                    "items": [
                        {"ok": True, "status": "success", "source": url, "content": original},
                    ],
                }
            ),
            duration_ms=1,
            tool_call_id="fetch",
            is_error=False,
        ),
    )
    result = AgentLoopResult(messages=[], final_content="Researcher says the date is known.")
    await observer.on_loop_end(result)
    bus, spec, _ = make_bound(tmp_path)
    source = bus._jobs["source"].result
    assert source is not None
    source.metadata.update(result.metadata)
    _, prompt = bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=planned_items(),
        required=True,
        outputs_root=tmp_path,
    )
    assert original in prompt, "Web original lost between acquisition and independent verification"
    assert url in prompt
