"""M0 contract tests for context carried between completed workflow runs."""

from __future__ import annotations

import json

import pytest

from frontier_agent.components.observers.conversation_snapshot import build_dump
from frontier_agent.core.messages import assistant_msg, system_msg, tool_msg, user_msg
from workflows._shared.cross_mode_context import (
    SCHEMA,
    TAIL_START,
    CrossModeContextError,
    append_context_to_question,
    export_conversation_context,
    render_context_tail,
    with_published_answer,
)
from workflows.agent_team.spec import SWARM_SPEC
from workflows.stateful_react_agent.spec import REACT_SPEC


def _tool_call(call_id: str) -> dict:
    return {
        "content": "",
        "role": "assistant",
        "tool_calls": [
            {
                "type": "function",
                "id": call_id,
                "function": {
                    "name": "lookup",
                    "arguments": '{"ticker":"ACME"}',
                },
            }
        ],
    }


def _dump(
    *,
    pipeline_id: str,
    run_id: str,
    messages: list[dict],
    trim: bool = False,
) -> dict:
    doc = build_dump(
        messages=messages,
        system_prompt=str(messages[0]["content"]),
        tool_names=["lookup"],
        tools_hash="tool-hash",
        thinking_format="none",
        pipeline_id=pipeline_id,
        node_id="react_agent" if pipeline_id == "stateful-react-agent" else "main_agent",
        role_id="stateful_react" if pipeline_id == "stateful-react-agent" else "agent_team_main",
        run_id=run_id,
        session_id="research-1",
    )
    if trim:
        doc["trim"] = {"reason": "over token budget", "dropped_for_tokens": 1}
    return doc


def test_export_rejects_untrusted_or_invalid_native_payloads() -> None:
    with pytest.raises(CrossModeContextError, match="schema mismatch"):
        export_conversation_context({"schema": "other", "messages": []})

    orphaned = _dump(
        pipeline_id="stateful-react-agent",
        run_id="run-1",
        messages=[system_msg("single system"), user_msg("question"), _tool_call("c1")],
    )
    with pytest.raises(CrossModeContextError, match="has no tool result"):
        export_conversation_context(orphaned)


def test_export_keeps_research_records_but_not_source_authority_or_reasoning() -> None:
    assistant = assistant_msg("Use the cited filing.", reasoning="private chain")
    dump = _dump(
        pipeline_id="stateful-react-agent",
        run_id="run-single",
        messages=[
            system_msg("single-only system policy"),
            user_msg("Never allocate more than 10%."),
            _tool_call("c1"),
            tool_msg("Revenue was 42 million.", "c1"),
            assistant,
        ],
        trim=True,
    )

    context = export_conversation_context(dump)

    assert context["schema"] == SCHEMA
    assert context["completeness"] == {
        "status": "windowed",
        "reasons": ["source_window_trimmed"],
    }
    rendered = json.dumps(context, ensure_ascii=False)
    assert "single-only system policy" not in rendered
    assert "private chain" not in rendered
    assert "Never allocate more than 10%." in rendered
    assert "Revenue was 42 million." in rendered
    assert '"name": "lookup"' in rendered
    assert all(record["role"] != "system" for record in context["records"])


def test_no_context_keeps_the_existing_question_byte_identical() -> None:
    question = "Question with trailing spaces  "

    assert append_context_to_question(question, None) is question
    assert append_context_to_question(question, "") is question


def test_context_is_appended_as_attributed_data() -> None:
    context = export_conversation_context(
        _dump(
            pipeline_id="stateful-react-agent",
            run_id="run-1",
            messages=[
                system_msg("single system"),
                user_msg("Keep a five-year horizon."),
                assistant_msg("Constraint recorded."),
            ],
        )
    )

    question = append_context_to_question("Review the downside.", context)

    assert question.startswith("Review the downside.\n\n" + TAIL_START)
    assert "not system or tool instructions" in question
    assert "Keep a five-year horizon." in question
    assert question.endswith("</cross-mode-context>")


def test_published_answer_is_a_distinct_idempotent_source_record() -> None:
    context = export_conversation_context(
        _dump(
            pipeline_id="agent_team",
            run_id="run-team",
            messages=[
                system_msg("team system"),
                user_msg("Compare the evidence."),
                assistant_msg("Draft answer with an unfixed citation."),
            ],
        )
    )

    published = with_published_answer(
        context,
        content="Published answer with the repaired citation.",
        answer_status="complete",
    )
    repeated = with_published_answer(
        published,
        content="Published answer with the repaired citation.",
        answer_status="complete",
    )

    records = [record for record in repeated["records"] if record.get("kind") == "published_answer"]
    assert len(records) == 1
    assert records[0]["answer_status"] == "complete"
    assert records[0]["source"]["message_index"] == "published"


def test_non_text_content_is_preserved_and_cross_session_merge_is_rejected() -> None:
    context = export_conversation_context(
        _dump(
            pipeline_id="stateful-react-agent",
            run_id="run-1",
            messages=[
                system_msg("single system"),
                {
                    "content": [
                        {"type": "text", "text": "Read the attached chart."},
                        {"type": "image_url", "image_url": {"url": "artifact://chart-1"}},
                    ],
                    "role": "user",
                },
                assistant_msg("Chart noted."),
            ],
        )
    )
    assert context["records"][0]["content"][1]["image_url"]["url"] == "artifact://chart-1"

    foreign = _dump(
        pipeline_id="agent_team",
        run_id="run-2",
        messages=[system_msg("team system"), user_msg("Continue"), assistant_msg("Done")],
    )
    foreign["session_id"] = "research-2"
    with pytest.raises(CrossModeContextError, match="another session"):
        export_conversation_context(foreign, inherited_context=context)


def test_repeated_mode_changes_keep_stable_records_without_recursive_wrapping() -> None:
    single_context = export_conversation_context(
        _dump(
            pipeline_id="stateful-react-agent",
            run_id="run-single-1",
            messages=[
                system_msg("single system"),
                user_msg("Keep a five-year horizon."),
                assistant_msg("I will keep that constraint."),
            ],
        )
    )
    team_question = append_context_to_question("Check two independent sources.", single_context)
    team_context = export_conversation_context(
        _dump(
            pipeline_id="agent_team",
            run_id="run-team-1",
            messages=[
                system_msg("team system"),
                user_msg(team_question),
                assistant_msg("The two sources disagree on demand."),
            ],
        ),
        inherited_context=single_context,
    )
    next_single_question = append_context_to_question("Explain the disagreement.", team_context)
    final_context = export_conversation_context(
        _dump(
            pipeline_id="stateful-react-agent",
            run_id="run-single-2",
            messages=[
                system_msg("single system"),
                user_msg(next_single_question),
                assistant_msg("One source used an older reporting period."),
            ],
        ),
        inherited_context=team_context,
    )

    ids = [record["source_id"] for record in final_context["records"]]
    contents = [str(record.get("content") or "") for record in final_context["records"]]
    assert len(ids) == len(set(ids)) == 6
    assert sum("Keep a five-year horizon." in text for text in contents) == 1
    assert sum("Check two independent sources." in text for text in contents) == 1
    assert sum("Explain the disagreement." in text for text in contents) == 1
    assert all(TAIL_START not in text for text in contents)
    assert [source["run_id"] for source in final_context["sources"]] == [
        "run-single-1",
        "run-team-1",
        "run-single-2",
    ]


def test_ten_alternating_runs_grow_only_by_new_source_records() -> None:
    context = None
    for index in range(10):
        pipeline_id = "stateful-react-agent" if index % 2 == 0 else "agent_team"
        question = f"User turn {index}"
        imported_question = append_context_to_question(question, context)
        context = export_conversation_context(
            _dump(
                pipeline_id=pipeline_id,
                run_id=f"run-{index}",
                messages=[
                    system_msg(f"{pipeline_id} system"),
                    user_msg(imported_question),
                    assistant_msg(f"Answer {index}"),
                ],
            ),
            inherited_context=context,
        )

    records = context["records"]
    assert len(records) == 20
    assert len({record["source_id"] for record in records}) == 20
    assert len(context["sources"]) == 10
    assert all(TAIL_START not in str(record.get("content") or "") for record in records)
    for index in range(10):
        assert sum(record.get("content") == f"User turn {index}" for record in records) == 1


async def test_portable_prompt_window_is_bounded_while_archive_record_stays_addressable() -> None:
    full = export_conversation_context(
        _dump(
            pipeline_id="stateful-react-agent",
            run_id="large-run",
            messages=[
                system_msg("single system"),
                user_msg("early-detail-991 " + "x" * 4000),
                assistant_msg("latest answer"),
            ],
        )
    )
    bounded = export_conversation_context(
        _dump(
            pipeline_id="agent_team",
            run_id="next-run",
            messages=[
                system_msg("team system"),
                user_msg(append_context_to_question("continue", full)),
                assistant_msg("new answer"),
            ],
        ),
        inherited_context=full,
        max_tokens=500,
    )
    bounded = with_published_answer(
        bounded,
        content="published latest answer",
        answer_status="complete",
        max_tokens=500,
    )

    assert "portable_window_trimmed" in bounded["completeness"]["reasons"]
    assert any(record.get("kind") == "published_answer" for record in bounded["records"])
    assert "early-detail-991" in json.dumps(full, ensure_ascii=False)
    assert "early-detail-991" not in render_context_tail(bounded)
    from plugins.tools.research_history import (
        bind_research_history,
        research_history,
        reset_research_history,
    )

    token = bind_research_history([json.dumps(bounded)])
    try:
        found = json.loads(await research_history.func(query="early-detail-991"))
        assert found["total"] == 1
        assert "early-detail-991" in found["records"][0]["content"]
    finally:
        reset_research_history(token)


def test_both_workflow_entry_nodes_admit_the_portable_context_field() -> None:
    react_fields = REACT_SPEC.nodes[0].context_policy.include_fields or []
    team_fields = SWARM_SPEC.nodes[0].context_policy.include_fields or []

    assert "cross_mode_context" in react_fields
    assert "cross_mode_context" in team_fields
    assert "continuity_write_enabled" in team_fields


def test_worker_selects_native_only_for_same_mode_single(tmp_path) -> None:
    from frontier_agent.components.observers.conversation_snapshot import canonical_json
    from server.worker import _load_continuity_inputs

    native = _dump(
        pipeline_id="stateful-react-agent",
        run_id="run-single",
        messages=[
            system_msg("single system"),
            user_msg("Original constraint"),
            assistant_msg("Recorded"),
        ],
    )
    native_payload = canonical_json(native)
    portable_payload = canonical_json(export_conversation_context(native))
    (tmp_path / "prior_conversation.json").write_text(native_payload, encoding="utf-8")
    (tmp_path / "prior_cross_mode_context.json").write_text(portable_payload, encoding="utf-8")

    replay, cross = _load_continuity_inputs(
        tmp_path,
        target_pipeline_id="stateful-react-agent",
        prior_pipeline_id="stateful-react-agent",
    )
    assert replay == native_payload
    assert cross == ""

    replay, cross = _load_continuity_inputs(
        tmp_path,
        target_pipeline_id="agent_team",
        prior_pipeline_id="stateful-react-agent",
    )
    assert replay == native_payload
    assert cross == portable_payload

    replay, cross = _load_continuity_inputs(
        tmp_path,
        target_pipeline_id="stateful-react-agent",
        prior_pipeline_id="agent_team",
    )
    assert replay == native_payload
    assert cross == portable_payload


def test_worker_converts_a_legacy_native_head_for_first_team_switch(tmp_path) -> None:
    from server.worker import _load_continuity_inputs

    native = _dump(
        pipeline_id="stateful-react-agent",
        run_id="legacy-single",
        messages=[
            system_msg("single system"),
            user_msg("Legacy constraint"),
            assistant_msg("Legacy answer"),
        ],
    )
    (tmp_path / "prior_conversation.json").write_text(json.dumps(native), encoding="utf-8")

    _, cross = _load_continuity_inputs(
        tmp_path,
        target_pipeline_id="agent_team",
        prior_pipeline_id="",
    )

    assert "Legacy constraint" in cross
    assert "single system" not in cross


def test_export_removes_imported_tail_before_team_generated_task_board() -> None:
    inherited = export_conversation_context(
        _dump(
            pipeline_id="stateful-react-agent",
            run_id="single-before-team",
            messages=[
                system_msg("single system"),
                user_msg("Keep the risk limit."),
                assistant_msg("Risk limit retained."),
            ],
        )
    )
    team_input = (
        append_context_to_question("Compare sources.", inherited)
        + "\n\n--- YOUR TASK BOARD (from planning) ---\n- verify demand"
    )

    exported = export_conversation_context(
        _dump(
            pipeline_id="agent_team",
            run_id="team-after-single",
            messages=[
                system_msg("team system"),
                user_msg(team_input),
                assistant_msg("Demand evidence conflicts."),
            ],
        ),
        inherited_context=inherited,
    )

    new_contents = [
        str(record.get("content") or "")
        for record in exported["records"]
        if record["source"]["run_id"] == "team-after-single"
    ]
    assert all(TAIL_START not in content for content in new_contents)
    assert any("Compare sources." in content for content in new_contents)
    assert any("YOUR TASK BOARD" in content for content in new_contents)


def test_export_drops_separate_imported_history_message():
    inherited = export_conversation_context(_dump(
        pipeline_id="agent_team", run_id="previous",
        messages=[system_msg("system"), user_msg("Original constraint"),
                  assistant_msg("Prior answer")],
    ))
    exported = export_conversation_context(_dump(
        pipeline_id="agent_team", run_id="next",
        messages=[system_msg("system"), user_msg(render_context_tail(inherited)),
                  user_msg("New question"), assistant_msg("New answer")],
    ), inherited_context=inherited)
    assert len(exported["records"]) == 4
    assert all(TAIL_START not in str(r.get("content")) for r in exported["records"])
    assert exported["records"][-2]["content"] == "New question"


@pytest.mark.asyncio
async def test_cross_mode_context_replaces_stale_native_replay(tmp_path, monkeypatch) -> None:
    from types import SimpleNamespace

    import apodex.session
    from workflows.stateful_react_agent.nodes import main_agent as node

    context = export_conversation_context(
        _dump(
            pipeline_id="agent_team",
            run_id="run-team",
            messages=[
                system_msg("team system"),
                user_msg("Check independent sources."),
                assistant_msg("The sources disagree."),
            ],
        )
    )
    stale_single = _dump(
        pipeline_id="stateful-react-agent",
        run_id="run-old-single",
        messages=[
            system_msg("single system"),
            user_msg("Old question"),
            assistant_msg("Old answer"),
        ],
    )

    monkeypatch.setattr(
        node,
        "_resolve_llm_and_profile",
        lambda *args, **kwargs: (
            SimpleNamespace(model_name="mock"),
            {"agent": {"direct": True, "replay_max_tokens": 0}},
            None,
        ),
    )
    monkeypatch.setattr(
        node, "registry", SimpleNamespace(get=lambda _: None, get_optional=lambda _: None)
    )
    monkeypatch.setattr(node, "_tools_for_stateful_react", lambda *args: [])
    monkeypatch.setattr(node, "get_direct_system_prompt", lambda: "single system")
    monkeypatch.setattr(node, "resolve_sandbox_mode", lambda _: "bwrap")
    monkeypatch.setattr(node, "_resolve_worktree_root", lambda *args: tmp_path)
    monkeypatch.setattr(node, "_resolve_sandbox_binds", lambda *args: ((), tmp_path / "outputs"))
    monkeypatch.setattr(node, "_resolve_trajectory_dir", lambda *args: tmp_path / "trace")
    monkeypatch.setattr(
        node, "_resolve_conversation_path", lambda *args: tmp_path / "conversation.json"
    )

    class LoopReached(Exception):
        pass

    async def loop(**kwargs):
        assert kwargs["initial_messages"] is None
        assert kwargs["user_message"].startswith("Continue the analysis.\n\n" + TAIL_START)
        assert "The sources disagree." in kwargs["user_message"]
        raise LoopReached

    monkeypatch.setattr(node, "run_agent_loop", loop)
    monkeypatch.setattr(apodex.session, "run_agent_loop", loop)
    with pytest.raises(LoopReached):
        await node.react_agent_node(
            {
                "original_question": "Continue the analysis.",
                "replay_payload": json.dumps(stale_single),
                "cross_mode_context": context,
                "metadata": {"session_id": "research-1"},
            },
            SimpleNamespace(task_id="cross-mode-test"),
        )


@pytest.mark.asyncio
async def test_research_history_searches_and_pages_archived_records() -> None:
    from plugins.tools.research_history import (
        bind_research_history,
        research_history,
        reset_research_history,
    )

    context = export_conversation_context(
        _dump(
            pipeline_id="stateful-react-agent",
            run_id="history-run",
            messages=[
                system_msg("single system"),
                user_msg("The original limit is 7.5 percent."),
                assistant_msg("Recorded with supporting detail " + "x" * 80),
            ],
        )
    )
    payload = json.dumps(context, ensure_ascii=False)
    token = bind_research_history([payload, payload])
    try:
        result = json.loads(
            await research_history.ainvoke({"query": "7.5 percent", "content_limit": 12})
        )
        assert result["ok"] is True
        assert result["total"] == 1
        record = result["records"][0]
        assert record["source"]["run_id"] == "history-run"
        assert record["content_next_offset"] == 12

        continuation = json.loads(
            await research_history.ainvoke(
                {
                    "source_id": record["source_id"],
                    "content_offset": record["content_next_offset"],
                    "content_limit": 20000,
                }
            )
        )
        assert "7.5 percent" in record["content"] + continuation["records"][0]["content"]
    finally:
        reset_research_history(token)


def test_worker_history_stage_is_consumed_before_model_tools_start(tmp_path) -> None:
    from server.history import RESEARCH_HISTORY_STAGE
    from server.worker import _load_research_history_contexts

    path = tmp_path / RESEARCH_HISTORY_STAGE
    path.write_text(
        json.dumps({"schema": "research-history-stage/1", "contexts": ["context-a"]}),
        encoding="utf-8",
    )

    assert _load_research_history_contexts(tmp_path) == ["context-a"]
    assert not path.exists()


@pytest.mark.parametrize("legacy", [False, True])
def test_portable_context_drops_runtime_controls_and_inline_reasoning(legacy):
    messages = [
        system_msg("system"),
        user_msg("Compare hardware, keep sources."),
        assistant_msg("<think>PRIVATE_REASONING</think>Visible finding with source."),
        user_msg("Current task board (keep it current via add_task / update_task): old tasks"),
        user_msg("The research admission window is closed. Collect the available findings."),
        assistant_msg("<think>UNFINISHED_PRIVATE_REASONING"),
    ]
    doc = _dump(pipeline_id="agent_team", run_id="clean", messages=messages)
    if legacy:
        context = {
            "schema": SCHEMA,
            "session_id": "research-1",
            "records": [
                {"source_id": f"old-{i}", "source": {"run_id": "old"}, **m}
                for i, m in enumerate(messages[1:])
            ],
            "sources": [],
            "completeness": {},
        }
        text = append_context_to_question("Follow up", context)
    else:
        text = json.dumps(export_conversation_context(doc))
    assert "PRIVATE_REASONING" not in text
    assert "Current task board" not in text
    assert "research admission window" not in text
    assert "Visible finding with source." in text
    assert "Compare hardware, keep sources." in text


def test_sanitized_legacy_tail_is_not_nested_on_export():
    from workflows._shared.cross_mode_context import TAIL_END

    old = {
        "schema": SCHEMA,
        "session_id": "research-1",
        "records": [
            {
                "source_id": "legacy-1",
                "source": {"run_id": "old"},
                "role": "assistant",
                "content": "<think>PRIVATE_REASONING</think>Old finding",
            }
        ],
        "sources": [],
        "completeness": {},
    }
    old_tail = f"\n\n{TAIL_START}\nOld wrapper\n{json.dumps(old)}\n{TAIL_END}"
    doc = _dump(
        pipeline_id="agent_team",
        run_id="new",
        messages=[
            system_msg("system"),
            user_msg("Follow up" + old_tail),
            assistant_msg("New answer"),
        ],
    )
    exported = export_conversation_context(doc, inherited_context=old)
    assert len(exported["records"]) == 3
    assert exported["records"][0]["source_id"] == "legacy-1"
    assert exported["records"][1]["content"] == "Follow up"
    assert TAIL_START not in json.dumps(exported)
    assert "PRIVATE_REASONING" not in json.dumps(exported)


def test_portable_cleaning_keeps_tool_evidence_and_quoted_user_text():
    context = {
        "schema": SCHEMA,
        "session_id": "research-1",
        "records": [
            {
                "source_id": "tool",
                "source": {},
                "role": "tool",
                "content": "<think>quoted source</think>",
            },
            {
                "source_id": "user",
                "source": {},
                "role": "user",
                "content": 'Explain the message "The research admission window is closed."',
            },
            {
                "source_id": "assistant",
                "source": {},
                "role": "assistant",
                "content": [
                    {"type": "thinking", "thinking": "PRIVATE_REASONING"},
                    {"type": "text", "text": "<think>PRIVATE_REASONING</think>Visible text"},
                ],
            },
        ],
        "sources": [],
        "completeness": {},
    }
    rendered = append_context_to_question("Current question", context)
    assert "PRIVATE_REASONING" not in rendered
    assert "Visible text" in rendered
    assert "quoted source" in rendered
    assert "Explain the message" in rendered


@pytest.mark.parametrize("tamper", ["checksum", "messages", "missing_receipt"])
def test_native_archive_requires_valid_messages_and_checksum(tamper: str) -> None:
    import hashlib

    from frontier_agent.components.observers.conversation_snapshot import canonical_json

    doc = _dump(
        pipeline_id="agent_team",
        run_id="archived-run",
        messages=[
            system_msg("system"),
            user_msg("latest"),
            assistant_msg("answer"),
        ],
    )
    archive = [system_msg("system"), user_msg("original evidence")]
    doc["archive_messages"] = archive
    doc["trim"] = {
        "recovery": {"sha256": hashlib.sha256(canonical_json(archive).encode("utf-8")).hexdigest()}
    }
    if tamper == "checksum":
        archive[1]["content"] = "altered"
    elif tamper == "messages":
        archive[1]["role"] = "invalid-role"
    else:
        doc.pop("trim")
    with pytest.raises(CrossModeContextError, match="archive"):
        export_conversation_context(doc)


async def test_archive_sanitization_does_not_replay_runtime_guidance_or_reasoning() -> None:
    from plugins.tools.research_history import (
        bind_research_history,
        research_history,
        reset_research_history,
    )

    payload = {
        "schema": SCHEMA,
        "records": [],
        "archived_records": [
            {"source_id": "notice", "role": "user", "content": "[Evidence boundary] old guidance"},
            {
                "source_id": "fact",
                "role": "assistant",
                "content": "<think>private</think>Public fact",
                "reasoning_content": "private reasoning",
            },
        ],
    }
    assert "Public fact" not in render_context_tail(payload)
    token = bind_research_history([json.dumps(payload)])
    try:
        found = json.loads(await research_history.func())
        assert found["total"] == 1
        assert found["records"][0]["source_id"] == "fact"
        assert "Public fact" in found["records"][0]["content"]
        assert "private" not in json.dumps(found)
    finally:
        reset_research_history(token)
