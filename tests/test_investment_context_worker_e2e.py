from __future__ import annotations

import json
import os
import subprocess
import sys
import uuid
from pathlib import Path

from deploy.huggingface.mock_llm import MockLLMServer, text_turn
from server.config import run_dir_for

REPO_ROOT = Path(__file__).resolve().parents[1]


def test_real_worker_request_contains_one_frozen_context_and_guarded_tools() -> None:
    run_id = uuid.uuid4().hex
    run_root = run_dir_for(run_id)
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "investment-context.json").write_text(
        json.dumps(
            {
                "schema_version": "business-snapshot/1",
                "run_id": run_id,
                "research_id": str(uuid.uuid4()),
                "snapshot_id": str(uuid.uuid4()),
                "use_case": "plan_analysis",
                "source": "manual",
                "values": {
                    "account.total_capital": {
                        "value": "123456.78",
                        "status": "user_provided",
                        "source": {"kind": "account_revision", "revision": 1},
                    }
                },
                "missing": {},
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    with MockLLMServer(script=[text_turn("context received")]) as endpoint:
        env = {
            **os.environ,
            "OPENAI_MODEL": "mock-frontier-model",
            "OPENAI_BASE_URL": endpoint.base_url,
            "OPENAI_API_KEY": "sk-data08-test",
            "SERVER_DATABASE_URL": "sqlite+aiosqlite:///:memory:",
        }
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "server.worker",
                "--run-id",
                run_id,
                "--session-id",
                str(uuid.uuid4()),
                "--prompt",
                "analyse the frozen plan",
                "--backend",
                "native",
                "--wall-time",
                "900",
                "--max-turns",
                "3",
            ],
            cwd=REPO_ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    assert endpoint.requests
    payload = endpoint.requests[0]
    messages = payload["messages"]
    combined = "\n".join(str(message.get("content") or "") for message in messages)
    assert combined.count("</investment_context_data>") == 1
    assert combined.count("123456.78") == 1
    assert "BUSINESS CONTEXT POLICY" in combined
    offered = {item["function"]["name"] for item in payload["tools"]}
    assert "investment_context" in offered
    assert "investment_position_sizing" in offered
    assert "investment_strategy_lint" in offered
    assert "position_sizing" not in offered
    assert "strategy_lint" not in offered
