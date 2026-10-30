from __future__ import annotations

import hashlib
import json
import shutil
import uuid
from pathlib import Path
from types import SimpleNamespace

import pytest

from frontier_agent.components.agent_bus import AgentBus
from frontier_agent.components.agent_bus.fan_in import format_report_block
from frontier_agent.components.agent_bus.models import JobEntry, SubAgentResult, SubTask
from frontier_agent.core.loop_types import AgentLoopResult, ToolResult, TurnContext
from frontier_agent.core.tool import ToolOutcome
from plugins.tools._handoff import (
    publish_file,
    reset_handoff_scope,
    set_handoff_scope,
    validate_handoff_refs,
)
from plugins.tools._sandbox import (
    clear_task_sandbox,
    make_current_sandbox,
    set_task_sandbox,
)
from plugins.tools.publish_handoff import publish_handoff
from plugins.tools.submit_report import REPORT_TEXT_MAX_CHARS, submit_report
from workflows._shared.research.observers.finalize_answer_observer import (
    FinalizeAnswerObserver,
)
from workflows.agent_team.subagent_runtime import (
    SwarmSubagentRuntime,
    _adapt_swarm_result,
)


@pytest.fixture
def handoff_runtime(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    workspace = tmp_path / "workspace"
    outputs = tmp_path / "outputs"
    inputs = tmp_path / "inputs"
    for path in (workspace, outputs, inputs):
        path.mkdir()

    monkeypatch.setenv("SANDBOX_BACKEND", "native")
    monkeypatch.setenv("APODEX_IN_NATIVE", "1")
    monkeypatch.setenv("FRONTIER_AGENT_WORKSPACE_DIR", str(workspace))
    monkeypatch.setenv("FRONTIER_AGENT_OUTPUTS_DIR", str(outputs))
    monkeypatch.setenv("FRONTIER_AGENT_INPUTS_DIR", str(inputs))

    sandbox_token = set_task_sandbox(make_current_sandbox(workspace))
    scope_token = set_handoff_scope(
        producer="analyst",
        job_id="job-7",
        workspace_root=workspace,
        outputs_root=outputs,
    )
    try:
        yield workspace, outputs
    finally:
        reset_handoff_scope(scope_token)
        clear_task_sandbox(sandbox_token)


@pytest.mark.asyncio
async def test_publish_handoff_creates_immutable_version_with_provenance(
    handoff_runtime: tuple[Path, Path],
) -> None:
    workspace, outputs = handoff_runtime
    (workspace / "candidate.csv").write_text("ticker,value\nAAA,42\n", encoding="utf-8")

    raw = await publish_handoff.func(
        source_path="/workspace/candidate.csv",
        label="screening-results",
    )

    assert not isinstance(raw, ToolOutcome)
    payload = json.loads(raw)
    assert payload["ok"] is True
    assert payload["ref"].startswith(
        "/outputs/scratch/handoffs/analyst/screening-results/"
    )
    assert len(payload["sha256"]) == 64
    published = outputs / payload["ref"].removeprefix("/outputs/")
    assert published.read_text(encoding="utf-8") == "ticker,value\nAAA,42\n"
    assert published.stat().st_mode & 0o222 == 0

    manifest = json.loads(Path(f"{published}.handoff.json").read_text(encoding="utf-8"))
    assert manifest == payload
    assert manifest["producer"] == "analyst"
    assert manifest["job_id"] == "job-7"
    assert manifest["source_name"] == "candidate.csv"


@pytest.mark.asyncio
async def test_submit_report_rejects_oversize_text_and_unpublished_attachment(
    handoff_runtime: tuple[Path, Path],
) -> None:
    too_large = await submit_report.func("x" * (REPORT_TEXT_MAX_CHARS + 1))
    assert isinstance(too_large, ToolOutcome)
    assert too_large.is_error is True
    assert "publish_handoff" in str(too_large.result)

    invalid = await submit_report.func(
        "Scope: checked\nFindings: ready",
        attachments=["/workspace/candidate.csv"],
    )
    assert isinstance(invalid, ToolOutcome)
    assert invalid.is_error is True
    assert "controlled handoff reference" in str(invalid.result)


@pytest.mark.asyncio
async def test_valid_handoff_reference_survives_report_fan_in(
    handoff_runtime: tuple[Path, Path],
) -> None:
    workspace, _outputs = handoff_runtime
    (workspace / "candidate.csv").write_text("a,b\n1,2\n", encoding="utf-8")
    published = json.loads(
        await publish_handoff.func(
            source_path="/workspace/candidate.csv",
            label="candidate-table",
        )
    )

    accepted = await submit_report.func(
        "Scope: generated candidate table\nFindings: see attachment",
        attachments=[published["ref"]],
    )
    assert isinstance(accepted, str)

    block = format_report_block(
        "analyst",
        SubAgentResult(
            question="make table",
            role_id="swarm_sub",
            final_content="Scope: generated candidate table",
            success=True,
            metadata={
                "stopped_by": "final_answer",
                "report_attachments": [published["ref"]],
            },
        ),
    )
    assert '<attachments count="1">' in block
    assert f'<attachment ref="{published["ref"]}" />' in block


@pytest.mark.asyncio
async def test_terminal_observer_latches_attachment_refs() -> None:
    observer = FinalizeAnswerObserver(tool_names=["submit_report"])
    ctx = TurnContext(
        turn=1,
        max_turns=3,
        task_id="task",
        role_id="swarm_sub",
        ai_text="",
        thinking="",
        tool_calls=[],
        messages=[],
        usage=None,
        metadata={},
    )
    ref = "/outputs/scratch/handoffs/analyst/table/abc-table.csv"
    await observer.on_tool_result(ctx, ToolResult(
        name="submit_report",
        args={"content": "done", "attachments": [ref]},
        result="Report submitted",
        duration_ms=1,
        tool_call_id="call-1",
        is_error=False,
    ))

    assert ctx.metadata["final_answer_attachments"] == [ref]


@pytest.mark.asyncio
async def test_result_adapter_carries_attachments_into_bus_metadata() -> None:
    from frontier_agent.components.agent_bus.models import SubTask

    ref = "/outputs/scratch/handoffs/analyst/table/abc-table.csv"
    result = await _adapt_swarm_result(
        AgentLoopResult(
            messages=[],
            final_content="done",
            stopped_by="final_answer",
            metadata={
                "final_answer": "done",
                "final_answer_attachments": [ref],
            },
        ),
        job_id="job-1",
        item=SubTask(question="build table", role_id="swarm_sub"),
        session_name="analyst",
        runtime=SwarmSubagentRuntime(),
    )

    assert result.metadata["report_attachments"] == [ref]


def test_nonpublisher_bwrap_binds_keep_only_handoff_scratch_writable(tmp_path: Path) -> None:
    from workflows.agent_team.subagent_runtime import _resolve_subagent_binds

    outputs = tmp_path / "outputs"
    configured = ((str(outputs), "/outputs", False),)

    binds = _resolve_subagent_binds(configured, can_publish=False)

    assert (str(outputs), "/outputs", True) in binds
    assert (str(outputs / "scratch"), "/outputs/scratch", False) in binds


def test_handoff_store_is_read_only_through_file_and_shell_policy() -> None:
    from plugins.tools._deliverable_policy import (
        bash_output_write_error,
        output_write_error,
    )

    ref = "/outputs/scratch/handoffs/analyst/table/v1.csv"
    assert "controlled read-only store" in (output_write_error(ref) or "")
    assert "controlled read-only store" in (
        bash_output_write_error(f"rm {ref}") or ""
    )
    assert bash_output_write_error(f"cat {ref}") is None
    assert bash_output_write_error(f"cp {ref} /workspace/copy.csv") is None


def test_publish_handoff_rejects_symlinked_store(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    outputs = tmp_path / "outputs"
    outside = tmp_path / "outside"
    workspace.mkdir()
    (outputs / "scratch").mkdir(parents=True)
    outside.mkdir()
    (workspace / "candidate.csv").write_text("private", encoding="utf-8")
    try:
        (outputs / "scratch" / "handoffs").symlink_to(outside, target_is_directory=True)
    except (OSError, NotImplementedError):
        pytest.skip("symlinks unsupported")

    token = set_handoff_scope(
        producer="analyst",
        job_id="job-symlink",
        workspace_root=workspace,
        outputs_root=outputs,
    )
    try:
        with pytest.raises(ValueError, match="cannot be backed by a symlink"):
            publish_file("/workspace/candidate.csv", "blocked")
    finally:
        reset_handoff_scope(token)

    assert list(outside.iterdir()) == []


def test_attach_expansion_preserves_structured_handoff_refs() -> None:
    from plugins.tools.assign_task import _expand_attach_tags

    ref = "/outputs/scratch/handoffs/analyst/table/v1.csv"
    session = SimpleNamespace(
        last_report="Scope: built table",
        last_report_metadata={"final_answer_attachments": [ref]},
    )
    bus = SimpleNamespace(get_session=lambda _session_id: session)

    expanded = _expand_attach_tags(
        'Review <attach agent="analyst"/>', "task", bus,
    )

    assert "Scope: built table" in expanded
    assert f'<attachment ref="{ref}" />' in expanded


@pytest.mark.asyncio
async def test_exact_job_attach_survives_agent_reuse_and_has_durable_snapshot(
    tmp_path: Path,
) -> None:
    """A verifier can name wave 1 after the same member has produced wave 2."""
    from plugins.tools.assign_task import _expand_attach_tags

    bus = AgentBus()
    task_id = "root"
    session_id = await bus.create_session(
        task_id=task_id,
        name="analyst",
        role_id="researcher",
        system_prompt="test",
        tools_override=[],
        llm_override=object(),
    )
    session = bus.get_session(session_id)
    assert session is not None
    store = bus.configure_task_result_store(task_id, tmp_path / "team-results")
    ref = "/outputs/scratch/handoffs/analyst/table/v1.csv"
    first = SubAgentResult(
        question="wave one",
        role_id="researcher",
        final_content="FIRST_WAVE_RESULT",
        success=True,
        job_id="root.job.1",
        metadata={"stopped_by": "submit_report", "report_attachments": [ref]},
    )
    bus._jobs[first.job_id] = JobEntry(
        job_id=first.job_id,
        parent_task_id=task_id,
        item=SubTask(question="wave one"),
        task=None,
        session_id=session_id,
        status="completed",
        result=first,
    )
    await bus._checkpoint_session_result(session=session, result=first)
    session.last_report = "SECOND_WAVE_RESULT"
    session.last_report_metadata = {}

    latest = _expand_attach_tags('Review <attach agent="analyst"/>', task_id, bus)
    exact = _expand_attach_tags(
        'Review <attach agent="analyst" job="root.job.1"/>', task_id, bus,
    )

    assert "SECOND_WAVE_RESULT" in latest and "FIRST_WAVE_RESULT" not in latest
    assert "FIRST_WAVE_RESULT" in exact and "SECOND_WAVE_RESULT" not in exact
    assert f'<attachment ref="{ref}" />' in exact
    assert "job root.job.1" in exact
    snapshot = store / "root.job.1.json"
    assert snapshot.is_file()
    assert json.loads(snapshot.read_text(encoding="utf-8"))["final_content"] == "FIRST_WAVE_RESULT"

    # A fresh bus can read the immutable audit snapshot without resuming work.
    restored = AgentBus()
    restored.configure_task_result_store(task_id, store)
    loaded = restored.get_job_result(task_id, first.job_id)
    assert loaded is not None
    assert loaded[0] == session_id
    assert loaded[1].final_content == "FIRST_WAVE_RESULT"

    conflicting = SubAgentResult(
        question="wave one", role_id="researcher", final_content="CHANGED_RESULT",
        success=True, job_id=first.job_id,
    )
    await bus._checkpoint_session_result(session=session, result=conflicting)
    assert conflicting.metadata["result_snapshot_error"] == "RuntimeError"
    assert "FIRST_WAVE_RESULT" in snapshot.read_text(encoding="utf-8")
    assert "CHANGED_RESULT" not in snapshot.read_text(encoding="utf-8")


@pytest.mark.asyncio
async def test_exact_job_attach_rejects_cross_agent_reference() -> None:
    from plugins.tools.assign_task import _expand_attach_tags

    bus = AgentBus()
    task_id = "root"
    analyst = await bus.create_session(
        task_id=task_id, name="analyst", role_id="researcher",
        system_prompt="test", tools_override=[], llm_override=object(),
    )
    await bus.create_session(
        task_id=task_id, name="verifier", role_id="researcher",
        system_prompt="test", tools_override=[], llm_override=object(),
    )
    result = SubAgentResult(
        question="wave one", role_id="researcher", final_content="PRIVATE_RESULT",
        success=True, job_id="root.job.1",
    )
    bus._jobs[result.job_id] = JobEntry(
        job_id=result.job_id, parent_task_id=task_id,
        item=SubTask(question="wave one"), task=None, session_id=analyst,
        status="completed", result=result,
    )

    expanded = _expand_attach_tags(
        'Review <attach agent="verifier" job="root.job.1"/>', task_id, bus,
    )
    assert "belongs to a different agent" in expanded
    assert "PRIVATE_RESULT" not in expanded


def test_fan_in_report_exposes_exact_job_reference() -> None:
    block = format_report_block(
        "analyst",
        SubAgentResult(
            question="q", role_id="researcher", final_content="answer",
            success=True, job_id="root.job.7",
            metadata={"stopped_by": "submit_report"},
        ),
    )
    assert '<report agent="analyst" job="root.job.7" status="complete">' in block


def test_snapshot_failure_is_visible_as_incomplete_report() -> None:
    block = format_report_block(
        "analyst",
        SubAgentResult(
            question="q", role_id="researcher", final_content="answer",
            success=True, job_id="root.job.8",
            metadata={
                "stopped_by": "submit_report",
                "result_snapshot_error": "PermissionError",
            },
        ),
    )
    assert 'status="incomplete" reason="checkpoint_error"' in block
    assert "durable result snapshot could not be saved" in block


def test_handoff_to_publisher_to_web_artifact_hash(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from server.artifacts import (
        is_reserved_output_path,
        resolve_artifact_path,
        scan_outputs,
    )
    from server.config import build_run_paths, get_config

    run_id = uuid.uuid4().hex
    monkeypatch.setattr(get_config(), "runs_root", tmp_path / "runs")
    paths = build_run_paths(run_id)
    producer_workspace = paths["workspace"] / "team" / "analyst"
    producer_workspace.mkdir(parents=True)
    source = producer_workspace / "candidate.csv"
    source.write_bytes(b"ticker,value\nAAA,42\n")

    token = set_handoff_scope(
        producer="analyst",
        job_id="job-web",
        workspace_root=producer_workspace,
        outputs_root=paths["outputs"],
    )
    try:
        handoff = publish_file("/workspace/candidate.csv", "screening-results")
        validate_handoff_refs([handoff["ref"]])
    finally:
        reset_handoff_scope(token)

    # The publisher consumes the exact immutable ref and emits the declared
    # final artifact. The Web scanner must hide handoff internals while keeping
    # the user-facing file downloadable with the same digest.
    handoff_path = paths["outputs"] / handoff["ref"].removeprefix("/outputs/")
    final_path = paths["outputs"] / "screening-results.csv"
    shutil.copyfile(handoff_path, final_path)

    found = scan_outputs(run_id)
    assert [entry["rel_path"] for entry in found] == ["screening-results.csv"]
    expected = hashlib.sha256(final_path.read_bytes()).hexdigest()
    assert found[0]["sha256"] == expected == handoff["sha256"]
    assert resolve_artifact_path(run_id, "screening-results.csv") == final_path.resolve()
    assert resolve_artifact_path(run_id, handoff["ref"].removeprefix("/outputs/")) is None
    assert resolve_artifact_path(
        run_id, f"anything/../{handoff['ref'].removeprefix('/outputs/')}"
    ) is None
    assert is_reserved_output_path("anything/../scratch/handoffs/private.csv")


def test_bwrap_handoff_mount_is_read_only_but_scratch_stays_writable(
    tmp_path: Path,
) -> None:
    from plugins.tools._sandbox import BwrapSandbox, bwrap_available
    from workflows.agent_team.subagent_runtime import _resolve_subagent_binds

    if not bwrap_available():
        pytest.skip("bubblewrap is unavailable")
    workspace = tmp_path / "workspace"
    outputs = tmp_path / "outputs"
    workspace.mkdir()
    binds = _resolve_subagent_binds(
        ((str(outputs), "/outputs", False),), can_publish=False,
    )
    handoff = outputs / "scratch" / "handoffs" / "fixed.txt"
    handoff.write_text("verified", encoding="utf-8")
    sandbox = BwrapSandbox(workspace=workspace, binds=binds)
    try:
        scratch_write = sandbox.commands.run(
            "printf ok > /outputs/scratch/member-note.txt", timeout=10,
        )
        tamper = sandbox.commands.run(
            "printf bad >> /outputs/scratch/handoffs/fixed.txt", timeout=10,
        )
        final_write = sandbox.commands.run(
            "printf bad > /outputs/leak.txt", timeout=10,
        )
    finally:
        sandbox.kill()

    assert scratch_write.exit_code == 0
    assert tamper.exit_code != 0
    assert final_write.exit_code != 0
    assert handoff.read_text(encoding="utf-8") == "verified"


@pytest.mark.asyncio
@pytest.mark.parametrize("file_exists", [False, True])
async def test_research_handoff_publication_attempt_then_direct_report(handoff_runtime, file_exists):
    import time

    from frontier_agent.core.llm import LLMResponse
    from frontier_agent.core.runtime.loop.agent_loop import run_agent_loop
    from workflows.agent_team.subagent_runtime import (
        InheritedWallClockDeadlineObserver,
        build_swarm_session_runtime_spec,
    )

    workspace, _ = handoff_runtime
    if file_exists:
        (workspace / "notes.md").write_text("Existing evidence", encoding="utf-8")
    draft = "Scope: research\nFinding: partial\nEvidence: https://example.org\nUnresolved: checks"

    class HandoffLLM:
        model = "scripted"
        calls = 0
        def __init__(self):
            self.refs = []

        async def chat(self, messages, **kwargs):
            self.calls += 1
            offered = {schema["function"]["name"] for schema in kwargs["tools"]}
            if self.calls == 1:
                assert offered == {"submit_report", "publish_handoff"}
                assert any("No report file is required" in str(m) for m in messages)
                name, args = "publish_handoff", {"source_path": "/workspace/notes.md"}
            else:
                assert offered == {"submit_report"}
                results = [m["content"] for m in messages if m["role"] == "tool"]
                assert len(results) == 1
                if file_exists:
                    self.refs = [json.loads(results[0])["ref"]]
                else:
                    assert "Error" in results[0]
                name, args = "submit_report", {
                    "content": draft if file_exists else draft + "; missing attachment",
                    "attachments": self.refs,
                }
            return LLMResponse(content="", tool_calls=[{
                "id": f"call-{self.calls}", "type": "function",
                "function": {"name": name, "arguments": json.dumps(args)},
            }], finish_reason="tool_calls")

    llm = HandoffLLM()
    spec = build_swarm_session_runtime_spec(
        SwarmSubagentRuntime(), session_name="researcher", task_id="root",
    )
    result = await run_agent_loop(
        system_prompt="research", user_message="submit existing findings", llm=llm,
        tools=[publish_handoff, submit_report],
        config=spec.config_builder("root.job.1", SubTask("research"), 4),
        observers=[
            InheritedWallClockDeadlineObserver(time.monotonic() + 60, handoff_at=time.monotonic() - 1),
            FinalizeAnswerObserver(tool_names=["submit_report"]),
        ],
    )
    assert llm.calls == 2
    assert result.stopped_by == "final_answer"
    assert result.final_content == (draft if file_exists else draft + "; missing attachment")
    if file_exists:
        assert len(validate_handoff_refs(llm.refs)) == 1
    else:
        assert llm.refs == []
        assert not (workspace / "notes.md").exists()
