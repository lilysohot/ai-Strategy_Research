from __future__ import annotations

import json
import os
from argparse import Namespace


async def test_worker_keeps_interruption_and_partial_delivery_diagnostics(tmp_path, monkeypatch):
    from server import config, worker
    from workflows.stateful_react_agent.spec import REACT_SPEC

    expected = {
        "final_answer": "研究未完成，以下是已核验原文片段。",
        "stopped_by": "llm_error",
        "answer_status": "partial",
        "final_answer_source": "verified_corpus_excerpts",
        "llm_error_reason": "reasoning_runaway_early",
        "llm_retry_blocked_by": "logical_call_deadline",
    }

    class Session:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def run(self, *args, **kwargs):
            # Exercise the node-to-worker projection, where diagnostics were lost.
            return {k: v for k, v in expected.items() if k in REACT_SPEC.nodes[0].output_fields}

    frames = []
    monkeypatch.setattr(config, "run_dir_for", lambda _: tmp_path)
    monkeypatch.setattr(worker, "_setup_logging", lambda _: None)
    monkeypatch.setattr(worker, "_frame", lambda event, **data: frames.append((event, data)))
    monkeypatch.setattr("benchmarks.public.core.kernel_adapter.BenchmarkSession", Session)
    args = Namespace(
        run_id="recovery-summary", session_id="test", turn_index=1, prompt="总结资料",
        prompt_addendum="", pipeline_id="stateful-react-agent", backend="native",
        wall_time=900, max_turns=60, model="", base_url="", api_key="", agent_tools="",
    )
    env = dict(os.environ)
    try:
        assert await worker.run_once(args) == 0
    finally:
        os.environ.clear()
        os.environ.update(env)
    summary = json.loads((tmp_path / "summary.json").read_text())
    terminal = next(data for event, data in frames if event == "run_finished")
    for key, value in expected.items():
        assert summary.get(key) == value, (key, summary)
        assert terminal.get(key) == value, (key, terminal)
