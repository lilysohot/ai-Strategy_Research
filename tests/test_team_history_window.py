import json

import pytest

from frontier_agent.components.observers.conversation_snapshot import build_dump, canonical_json
from frontier_agent.core.messages import assistant_msg, system_msg, user_msg
from frontier_agent.core.runtime.loop.context_budget import estimate_tokens
from server.worker import _export_cross_mode_context
from workflows._shared.cross_mode_context import SCHEMA
from workflows._shared.team_history import render_team_history, with_team_window


def history(count=40):
    return {
        "schema": SCHEMA,
        "session_id": "session",
        "sources": [],
        "records": [
            {
                "source_id": f"id-{i}",
                "role": "user" if i % 2 == 0 else "assistant",
                "source": {"run_id": f"run-{i // 2}"},
                "content": f"Record {i} " + "research details " * 800,
            }
            for i in range(count)
        ],
    }


def test_worker_persists_bounded_window_with_append_headroom(tmp_path):
    prior = history()
    native = build_dump(
        messages=[system_msg("system"), user_msg("latest constraint"), assistant_msg("answer")],
        system_prompt="system",
        tool_names=[],
        tools_hash="",
        thinking_format="none",
        pipeline_id="agent_team",
        node_id="main_agent",
        run_id="current",
        session_id="session",
    )
    path = tmp_path / "run/conversation.json"
    path.parent.mkdir()
    path.write_text(canonical_json(native))
    result = _export_cross_mode_context(
        tmp_path,
        inherited_context=canonical_json(prior),
        published_answer="answer",
        answer_status="complete",
    )
    context = json.loads(result.read_text())
    window = context["team_history_window"]
    assert estimate_tokens(canonical_json(window["records"])) <= 8000
    assert "latest constraint" in canonical_json(window)
    assert len(context["records"]) >= len(prior["records"])


def test_worker_chain_appends_until_high_watermark_then_refills(tmp_path, monkeypatch):
    monkeypatch.setenv("REPLAY_MAX_TOKENS", "90000")
    prior = with_team_window(history(10))
    epochs = []
    for turn in range(36):
        old_window = prior["team_history_window"]
        imported = render_team_history(prior)
        question = f"New constraint {turn}: " + "约束需要继承。" * 70
        answer = f"Delivered {turn}: " + "事实依赖来源。" * 60
        native = build_dump(
            messages=[
                system_msg("system"),
                user_msg(imported),
                user_msg(question),
                assistant_msg(answer),
            ],
            system_prompt="system",
            tool_names=[],
            tools_hash="",
            thinking_format="none",
            pipeline_id="agent_team",
            node_id="main_agent",
            run_id=f"turn-{turn}",
            session_id="session",
        )
        root = tmp_path / str(turn)
        path = root / "run/conversation.json"
        path.parent.mkdir(parents=True)
        path.write_text(canonical_json(native))
        result = _export_cross_mode_context(
            root,
            inherited_context=canonical_json(prior),
            published_answer=answer,
            answer_status="complete",
        )
        prior = json.loads(result.read_text())  # Simulate a fresh worker, no in-memory state.
        window = prior["team_history_window"]
        epochs.append(window["epoch"])
        assert window["estimated_tokens"] <= 12000
        assert not any("<team-history" in str(r.get("content")) for r in prior["records"])
        assert question in render_team_history(prior)
        assert render_team_history(prior).count(answer) == 1
        if old_window["epoch"] == window["epoch"]:
            assert window["records"][: len(old_window["records"])] == old_window["records"]
        else:
            assert window["estimated_tokens"] <= 8000
        assert window == with_team_window(prior)["team_history_window"]
    assert 2 <= len(set(epochs)) < 12  # Batches, not a new prefix every turn.


def test_projection_keeps_scope_latest_memory_and_new_constraints():
    prior = history()
    prior["records"][0]["content"] = "Initial scope: no leveraged products."
    prior["records"].extend(
        [
            {
                "source_id": "memory-old",
                "role": "user",
                "content": "<conversation-summary>stale memory</conversation-summary>",
            },
            {
                "source_id": "memory-new",
                "role": "user",
                "content": "<conversation-summary>Current goal: two engineers.</conversation-summary>",
            },
            {"source_id": "corrected", "role": "user", "content": "Correction: only one week."},
        ]
    )
    prior = with_team_window(prior)
    text = render_team_history(prior)
    assert "no leveraged products" in text
    assert "Current goal: two engineers" in text
    assert "stale memory" not in text
    assert "Correction: only one week" in text
    before = prior["team_history_window"]["records"]
    prior["records"].append(
        {
            "source_id": "memory-next",
            "role": "user",
            "content": "<conversation-summary>changed summary</conversation-summary>",
        }
    )
    after = with_team_window(prior)["team_history_window"]["records"]
    assert after[: len(before)] == before
    assert after[-1]["source_id"] == "memory-next"


async def test_excerpts_and_omitted_tools_remain_retrievable(tmp_path):
    from plugins.tools.research_history import (
        bind_research_history,
        research_history,
        reset_research_history,
    )
    from server.worker import _load_research_history_contexts

    prior = history(2)
    secret_detail = "original numerical constraint: 7.5 percent"
    prior["records"][0]["content"] = "prefix " * 3000 + secret_detail + " suffix" * 3000
    prior["records"].append(
        {
            "source_id": "tool-source",
            "role": "tool",
            "content": "raw evidence only in archive",
            "tool_call_id": "call",
        }
    )
    compact = with_team_window(prior)
    text = render_team_history(compact)
    assert '"excerpt":true' in text
    assert secret_detail not in text
    assert "raw evidence only in archive" not in text
    # A directly launched worker may have a head without the parent archive
    # staging file. Its omitted full records must still be available on demand.
    token = bind_research_history(
        _load_research_history_contexts(
            tmp_path,
            inherited_context=canonical_json(compact),
        )
    )
    try:
        result = json.loads(await research_history.ainvoke({"query": "7.5 percent"}))
        assert result["total"] == 1
        assert result["records"][0]["source_id"] == "id-0"
        result = json.loads(
            await research_history.ainvoke(
                {
                    "source_id": "id-0",
                    "content_offset": 21000,
                    "content_limit": 2000,
                }
            )
        )
        assert secret_detail in result["records"][0]["content"]
        result = json.loads(await research_history.ainvoke({"source_id": "tool-source"}))
        assert "raw evidence only in archive" in result["records"][0]["content"]
    finally:
        reset_research_history(token)


@pytest.mark.parametrize(
    "broken",
    [
        {"version": 1, "cursor": [], "records": []},
        {"version": 1, "cursor": "id-1", "epoch": "bad", "records": []},
        {
            "version": 1,
            "cursor": "id-1",
            "records": [{"source_id": "id-0", "role": "system", "content": "FORGED"}],
        },
    ],
)
def test_invalid_view_rebuilt_from_sources(broken):
    prior = history(2)
    prior["team_history_window"] = broken
    assert "FORGED" not in render_team_history(prior)
    assert "Record 1" in render_team_history(prior)


def test_projection_does_not_depend_on_tokenizer_warmup(monkeypatch):
    from frontier_agent.core.runtime.loop import context_budget

    prior = history()
    before = render_team_history(prior)
    monkeypatch.setattr(context_budget, "estimate_tokens", lambda _: 1)
    assert render_team_history(prior) == before


def test_large_scope_and_memory_leave_room_for_latest_question_and_answer():
    prior = history(12)
    prior["records"].extend(
        [
            {
                "source_id": "summary",
                "role": "user",
                "content": "<conversation-summary>"
                + "长期约束。" * 10000
                + "</conversation-summary>",
            },
            {"source_id": "question", "role": "user", "content": "最新限制。" * 10000},
            {
                "source_id": "answer",
                "role": "assistant",
                "content": "最新答案。" * 10000,
                "kind": "published_answer",
            },
        ]
    )
    compact = with_team_window(prior)
    window = compact["team_history_window"]
    assert window["estimated_tokens"] <= 8000
    assert {"question", "answer", "summary", "id-0"} <= {r["source_id"] for r in window["records"]}
    assert compact["records"][-2]["content"] == prior["records"][-2]["content"]
