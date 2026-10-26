"""Exercise CLI role prompts/tools through a real Web worker and bwrap."""

from __future__ import annotations

import asyncio
import json
import os
import re
import sys
import uuid
from pathlib import Path

import pytest

from deploy.huggingface.mock_llm import MockLLMServer, text_turn, tool_call_turn
from plugins.tools._sandbox import bwrap_available
from server.config import build_run_paths, run_dir_for
from server.profile import PROFILE_NAME
from workflows.agent_team.profile import load_swarm_profile
from workflows.agent_team.prompts import FINAL_VERIFIER, SUBAGENT_RESEARCH


@pytest.mark.skipif(sys.platform != "linux", reason="Web bwrap worker requires Linux")
@pytest.mark.parametrize("internal_final,versioned", [(False, False), (True, False), (False, True)])
async def test_web_worker_delegates_reads_and_verifies_with_cli_roles(monkeypatch, internal_final, versioned):
    if not bwrap_available():
        pytest.skip("bubblewrap unavailable")

    run_id = uuid.uuid4().hex
    paths = build_run_paths(run_id)
    (paths["inputs"] / "brief.txt").write_text("PARITY_SOURCE_VALUE=42\n", encoding="utf-8")
    answer = ('<report agent="reader">RAW_INTERNAL_RESULT: 42</report>' if internal_final else
              "The independently verified value is 42.")
    main_script = [
        tool_call_turn("add_task", {"tasks": [{"description": "Read and verify value"}]}),
        tool_call_turn("create_subagent", {"agents": [
            {"name": "reader", "system_prompt": "Read the supplied file."},
            {"name": "final_verifier", "system_prompt": "Verify the returned value."},
        ]}),
        tool_call_turn("assign_task", {"tasks": [{
            "agent": "reader", "prompt": "Read /inputs/brief.txt and report its value.",
        }]}),
        tool_call_turn("collect_reports", {"timeout": 30}),
        None,  # exact reader job is filled from the preceding collect result
        tool_call_turn("collect_reports", {"timeout": 30}),
        tool_call_turn("update_task", {"updates": [{
            "id": "t1", "resolution": "resolved", "notes": "Reader and verifier agree: 42",
        }]}),
        text_turn(answer),
    ]
    scripts = {
        "main": main_script,
        "reader": [
            tool_call_turn("read_file", {"path": "/inputs/brief.txt"}),
            tool_call_turn("submit_report", {"content": "READER_REPORT: value is 42."}),
        ],
        "verifier": [
            tool_call_turn("read_file", {"path": "/inputs/brief.txt"}),
            tool_call_turn("submit_report", {"content": "VERIFIER_REPORT: independently read 42."}),
        ],
    }
    requests = {role: [] for role in scripts}
    if versioned:
        scripts["verifier"].append(scripts["verifier"][-1])
    server = MockLLMServer().start()

    def next_turn(payload):
        tools = {item["function"]["name"] for item in payload.get("tools", [])}
        system = str(payload["messages"][0]["content"])
        if "create_subagent" in tools:
            role = "main"
        elif system.startswith(FINAL_VERIFIER):
            role = "verifier"
        elif system.startswith(SUBAGENT_RESEARCH):
            role = "reader"
        else:
            return text_turn(answer)
        index = len(requests[role])
        requests[role].append(payload)
        if role == "main" and index == 4:
            history = "\n".join(
                str(message.get("content") or "")
                for message in (payload.get("messages") or [])
            )
            match = re.search(r'<report agent="reader" job="([^"]+)"', history)
            assert match, history[-4000:]
            assignment = {
                "agent": "final_verifier",
                "prompt": (
                    "Verify 42 against /inputs/brief.txt. "
                    f'<attach agent="reader" job="{match.group(1)}"/>'
                ),
            }
            if versioned:
                assignment["verification_checks"] = [{
                    "check_id": "value", "work_item_id": "t1", "criterion": "Check value is 42",
                    "subject": {"job_id": match.group(1)},
                    "evidence": [{"job_id": match.group(1)}],
                }]
            return tool_call_turn("assign_task", {"tasks": [assignment]})
        if versioned and role == "verifier" and index == 1:
            task = next(str(m["content"]) for m in payload["messages"]
                        if "# Bound verification checks" in str(m.get("content", "")))
            checks, _ = json.JSONDecoder().raw_decode(task.split("# Bound verification checks\n", 1)[1])
            check = checks[0]
            return tool_call_turn("submit_report", {
                "content": "VERIFIER_REPORT: independently read 42.", "finish": False,
                "verification_results": [{
                    "check_id": "value", "binding_id": check["binding_id"], "verdict": "pass",
                    "method": "read original input and compare", "detail": "Both contain 42",
                    "evidence_keys": [check["evidence"][0]["key"]],
                }],
            })
        return scripts[role][min(index, len(scripts[role]) - 1)]

    monkeypatch.setattr(server._script, "next_turn", next_turn)
    env = {
        **os.environ,
        "OPENAI_MODEL": server.model,
        "OPENAI_BASE_URL": server.base_url,
        "OPENAI_API_KEY": "sk-test",
        "LLM_PROVIDER": "openai",
    }
    proc = None
    try:
        proc = await asyncio.create_subprocess_exec(
            sys.executable, "-m", "server.worker", "--run-id", run_id,
            "--session-id", uuid.uuid4().hex, "--pipeline-id", "agent_team",
            "--backend", "bwrap", "--wall-time", "400", "--max-turns", "20",
            "--business-prefix", "1", "--mixed-mode-history", "--continuity", "off",
            "--prompt", "Read /inputs/brief.txt, independently verify its value, and answer in text.",
            cwd=Path(__file__).resolve().parents[1], env=env,
            stdin=asyncio.subprocess.DEVNULL,
            stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE,
        )
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=60)
        assert proc.returncode == 0, (stdout + stderr).decode(errors="replace")[-8000:]
    finally:
        if proc is not None and proc.returncode is None:
            proc.kill()
            await proc.wait()
        server.stop()

    cli = load_swarm_profile(PROFILE_NAME)["agent"]
    for role, seen in requests.items():
        assert seen, f"missing {role} model requests"
        names = {item["function"]["name"] for item in seen[0]["tools"]}
        expected = set(cli["main_agent_tools"] if role == "main" else cli["sub_agent_tools"])
        if role == "main":
            expected.add("research_history")
        assert names == expected
        prompt = seen[0]["messages"][0]["content"]
        assert "BUSINESS CONTEXT POLICY:" not in prompt
        assert "INPUT REQUEST POLICY:" not in prompt
        assert "Scientific Problem-Solving Guide" not in prompt

    for role in ("reader", "verifier"):
        observations = [m for req in requests[role] for m in req["messages"] if m["role"] == "tool"]
        assert any("PARITY_SOURCE_VALUE=42" in str(m["content"]) for m in observations)
    main_history = json.dumps(requests["main"][-1]["messages"])
    assert "READER_REPORT" in main_history and "VERIFIER_REPORT" in main_history
    verifier_history = json.dumps(requests["verifier"][0]["messages"])
    assert "READER_REPORT" in verifier_history
    assert "job " in verifier_history
    summary = json.loads((run_dir_for(run_id) / "summary.json").read_text())
    assert summary["stopped_by"] == "final_answer"
    if internal_final:
        assert "RAW_INTERNAL_RESULT" not in summary["final_answer"]
        assert "system-generated execution status" in summary["final_answer"]
        assert summary["report_contract"]["kind"] == "system_status"
        assert summary["answer_status"] == "not_found"
    else:
        assert summary["final_answer"].startswith(answer)
        assert summary["report_contract"]["kind"] == "complete"
        assert summary["report_contract"]["task_board"][0]["resolution"] == "resolved"
    frames = [json.loads(line) for line in stdout.decode().splitlines() if line.startswith("{")]
    terminal = next(frame for frame in frames if frame.get("type") == "run_finished")
    assert terminal["report_contract"] == summary["report_contract"]
    assert terminal["final_answer"] == summary["final_answer"]
    snapshots = sorted((paths["run"] / "agent" / "team-results").rglob("*.json"))
    assert len(snapshots) == 2
    saved = [json.loads(path.read_text(encoding="utf-8")) for path in snapshots]
    assert {item["agent_name"] for item in saved} == {"reader", "final_verifier"}
    assert all(item["final_content"] for item in saved)
    if versioned:
        contract = summary["report_contract"]
        assert contract["verification"] == "passed_for_declared_checks"
        verifier = next(item for item in saved if item["agent_name"] == "final_verifier")
        assert verifier["assignment_metadata"]["verification_events"][0]["verdict"] == "pass"
        assert contract["verification_checks"][0]["binding_id"] == (
            verifier["assignment_metadata"]["verification_checks"][0]["binding_id"]
        )
        assert "[version-bound checks]" in main_history
        assert len(requests["verifier"]) >= 3  # partial submit did not terminate the loop
