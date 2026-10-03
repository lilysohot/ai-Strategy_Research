"""Explicit experimental react profile and process-isolated product replays."""

from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
RUNNER = REPO / "tests" / "corpus_structured_replay_runner.py"


def run_process(tmp_path, mode, *, scenario="positive", enforce=False):
    cwd = tmp_path / mode
    cwd.mkdir(exist_ok=True)
    env = {
        "PATH": os.environ["PATH"],
        "HOME": str(cwd / "home"),
        "PYTHONPATH": str(REPO),
        "PYTHON_DOTENV_DISABLED": "1",
        "OPENAI_MODEL": "synthetic-main",
        "OPENAI_API_KEY": "synthetic-key",
        "OPENAI_BASE_URL": "https://synthetic.invalid/v1",
        "REACT_WORKFLOW_PROFILE": "tui" if scenario == "legacy" else "tui-semantic",
        "MAIN_MAX_TURNS": "8",
        "SANDBOX_BACKEND": "native",
        "APODEX_IN_NATIVE": "1",
        "A4_ENFORCE": "1" if enforce else "0",
    }
    command = [sys.executable, str(RUNNER), mode, str(tmp_path), scenario]
    if mode == "research" and scenario != "writable_root":
        nested_mount = []
        if scenario == "nested_writable":
            subtree = str(tmp_path / "write" / "store" / "objects")
            nested_mount = ["--bind", subtree, subtree]
        command = [
            "bwrap",
            "--die-with-parent",
            "--new-session",
            "--unshare-pid",
            "--unshare-net",
            "--ro-bind",
            "/",
            "/",
            "--bind",
            str(cwd),
            str(cwd),
            "--proc",
            "/proc",
            "--dev",
            "/dev",
            "--chdir",
            str(cwd),
            *nested_mount,
            "--",
            *command,
        ]

    def invoke():
        return subprocess.run(command, cwd=cwd, env=env, text=True, capture_output=True, timeout=60)

    if mode == "research" and scenario == "withdrawn":
        # The researcher cannot become a writer. The parent remains outside
        # its mount namespace and permits only this fixed synthetic withdrawal.
        with ThreadPoolExecutor(max_workers=1) as pool:
            pending = pool.submit(invoke)
            request = cwd / "withdraw.request"
            deadline = time.monotonic() + 50
            while not request.exists() and not pending.done() and time.monotonic() < deadline:
                time.sleep(0.02)
            if request.exists():
                writer = subprocess.run(
                    [sys.executable, str(RUNNER), "retire", str(tmp_path), scenario],
                    cwd=tmp_path / "write",
                    env=env,
                    text=True,
                    capture_output=True,
                    timeout=15,
                )
                assert writer.returncode == 0, writer.stderr
                (cwd / "withdraw.ack").touch()
            result = pending.result()
    else:
        result = invoke()
    assert result.returncode == 0, result.stdout[-5000:] + result.stderr[-7000:]
    return json.loads((cwd / "replay-result.json").read_text())


@pytest.fixture
def profiles(monkeypatch, tmp_path):
    import dotenv

    import apodex.profiles as profiles

    # Profile loading is tested with fake configuration, never a real .env.
    monkeypatch.setattr(dotenv, "load_dotenv", lambda *a, **k: False)
    monkeypatch.setattr(profiles, "_USER_DIR", tmp_path / "profiles")
    monkeypatch.setenv("OPENAI_MODEL", "synthetic-main")
    monkeypatch.setenv("OPENAI_API_KEY", "synthetic-key")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://synthetic.invalid/v1")
    profiles._CACHE.clear()
    profiles._workflow_tool_names.cache_clear()
    yield profiles
    profiles._CACHE.clear()
    profiles._workflow_tool_names.cache_clear()


def test_react_semantic_profile_is_explicit_and_uses_workflow_tools(profiles, monkeypatch):
    monkeypatch.setenv("REACT_WORKFLOW_PROFILE", "tui-semantic")
    experiment = profiles.get_profile("react")
    assert experiment.workflow_profile == "tui-semantic"
    assert experiment.declared_tools == ()
    assert {"corpus_semantic_query", "corpus_fetch"} <= set(experiment.tool_names)
    profiles._CACHE.clear()
    monkeypatch.delenv("REACT_WORKFLOW_PROFILE")
    default = profiles.get_profile("react")
    assert default.workflow_profile == "tui"
    assert "corpus_semantic_query" not in default.tool_names
    assert set(experiment.tool_names) - set(default.tool_names) == {"corpus_semantic_query"}


def test_semantic_recovery_instructions_are_visible_in_model_tool_schema():
    from plugins.tools.corpus_semantic_query import corpus_semantic_query

    description = corpus_semantic_query.description
    assert "CS_CURSOR_STALE" in description
    assert "corpus_fetch" in description
    assert "budget_limited" in description


@pytest.mark.parametrize("allowed", [[], ["read_file"]])
def test_semantic_profile_respects_explicit_tool_override(profiles, allowed):
    from workflows.stateful_react_agent.profile import load_react_profile

    resolved = load_react_profile("tui-semantic", overrides={"agent": {"agent_tools": allowed}})
    assert resolved["agent"]["agent_tools"] == allowed


@pytest.mark.parametrize("enforce", [False, True])
def test_product_react_cross_process_semantic_report_is_verified(tmp_path, enforce):
    writer = run_process(tmp_path, "write")
    research = run_process(tmp_path, "research", enforce=enforce)
    assert writer["roles"] == ["claims", "material_items"]
    assert writer["pid"] != research["pid"]
    assert writer["cwd"] != research["cwd"]
    assert research["verification"]["status"] == "verified"
    assert research["verification"]["report_chars"] > 0
    assert research["tool_calls"] == ["corpus_semantic_query", "corpus_submit_manifest"]
    assert {"corpus_fetch", "corpus_semantic_query", "corpus_submit_manifest"} <= set(
        research["tools"]
    )
    assert research["model_calls"] == 3
    assert set(research["requests"][1]["delivery_before_response"][0].values()) == {"pending"}
    assert set(research["requests"][2]["delivery_before_response"][0].values()) == {"delivered"}
    assert research["unexpected_access"] == []
    assert research["guard_probes"] == ["network", "dotenv", "production_db", "model"]
    assert research["ledger"]["fetched"] == []
    assert all(
        status == "delivered"
        for receipt in research["ledger"]["semantic"]["receipts"]
        for status in receipt["delivery"].values()
    )


def test_product_budget_gap_requires_fresh_query_before_verification(tmp_path):
    run_process(tmp_path, "write")
    result = run_process(tmp_path, "research", scenario="budget")
    assert result["tool_calls"] == [
        "corpus_semantic_query",
        "corpus_semantic_query",
        "corpus_submit_manifest",
    ]
    pages = [
        json.loads(m["content"])
        for request in result["requests"]
        for m in request["messages"]
        if m.get("role") == "tool" and '"page_status"' in m.get("content", "")
    ]
    assert any(p["page_status"] == "budget_limited" and not p["records"] for p in pages)
    assert result["verification"]["status"] == "verified"
    assert result["unexpected_access"] == []


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("bad_handle", "unsupported"),
        ("withdrawn", "partial"),
        ("resolver_error", "verification_error"),
    ],
)
@pytest.mark.parametrize("enforce", [False, True])
def test_product_rejects_invalid_or_invalidated_evidence(tmp_path, scenario, expected, enforce):
    run_process(tmp_path, "write")
    result = run_process(tmp_path, "research", scenario=scenario, enforce=enforce)
    assert result["verification"]["status"] == expected
    assert result["verification"]["report_chars"] > 0
    assert result["unexpected_access"] == []
    rendered = json.dumps(result["display_history"], ensure_ascii=False)
    assert ("证据完整性校验（A4）" in rendered) is enforce


@pytest.mark.parametrize("scenario", ["legacy", "missing_root", "invisible_root"])
def test_product_source_fallback_and_disabled_experiment_remain_usable(tmp_path, scenario):
    run_process(tmp_path, "write")
    result = run_process(tmp_path, "research", scenario=scenario)
    assert result["verification"]["status"] == "verified"
    assert result["tool_calls"][-2:] == ["corpus_fetch", "corpus_submit_manifest"]
    assert result["ledger"]["fetched"]
    if scenario == "legacy":
        assert "corpus_semantic_query" not in result["tools"]
        assert not result["ledger"]["semantic"]["calls"]
    else:
        assert result["tool_calls"][0] == "corpus_semantic_query"
        expected = "CS_NOT_FOUND" if scenario == "invisible_root" else "CS_STORE_ROOT_REQUIRED"
        assert expected in json.dumps(result["requests"])
    assert result["unexpected_access"] == []


def test_product_missing_footnote_cannot_become_verified(tmp_path):
    writer = run_process(tmp_path, "write", scenario="missing_footnote")
    result = run_process(tmp_path, "research", scenario="missing_footnote", enforce=True)
    assert writer["publication_id"] is None
    assert "missing" in json.dumps(writer["snapshot"])
    assert "footnote" in json.dumps(writer["snapshot"])
    assert result["verification"]["status"] == "draft"
    assert "not_published" in json.dumps(result["requests"])
    assert result["unexpected_access"] == []


def test_product_downstream_trim_preserves_restart_protocol(tmp_path):
    run_process(tmp_path, "write", scenario="downstream_trim")
    result = run_process(tmp_path, "research", scenario="downstream_trim")
    second_request = result["requests"][1]["messages"]
    page = json.loads(next(m["content"] for m in reversed(second_request) if m["role"] == "tool"))
    assert page["records"] == []
    assert page["page_status"] == "budget_limited"
    assert "CS_CURSOR_STALE" in page["error_codes"]
    assert result["tool_calls"] == [
        "corpus_semantic_query",
        "corpus_semantic_query",
        "corpus_submit_manifest",
    ]
    assert result["verification"]["status"] == "verified"
    assert result["unexpected_access"] == []


def test_product_market_control_is_fixed_without_network(tmp_path):
    run_process(tmp_path, "write")
    result = run_process(tmp_path, "research", scenario="market")
    assert result["tool_calls"][0] == "market_quote"
    body = json.loads(
        next(
            m["content"] for m in reversed(result["requests"][1]["messages"]) if m["role"] == "tool"
        )
    )
    assert body["ok"]
    assert body["items"][0]["last_price"] == 15
    assert body["items"][0]["as_of_ms"] == 1767225600000
    assert result["verification"]["status"] == "verified"
    assert result["unexpected_access"] == []


def test_product_research_tools_cannot_write_publication_store(tmp_path):
    run_process(tmp_path, "write")
    result = run_process(tmp_path, "research", scenario="readonly")
    assert result["tool_calls"][:1] == ["bash"]
    body = next(
        m["content"] for m in reversed(result["requests"][1]["messages"]) if m["role"] == "tool"
    )
    assert "READONLY_CONFIRMED" in body
    assert "WRITABLE_STORE" not in body
    assert result["verification"]["status"] == "verified"
    assert result["unexpected_access"] == []


@pytest.mark.parametrize("scenario", ["writable_root", "nested_writable"])
def test_product_refuses_writable_store_before_model_request(tmp_path, scenario):
    run_process(tmp_path, "write")
    result = run_process(tmp_path, "research", scenario=scenario)
    assert "requires a read-only publication-store mount" in result.get("startup_error", "")
    assert result["model_calls"] == 0
