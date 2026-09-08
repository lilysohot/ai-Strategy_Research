#!/usr/bin/env python3
"""M0.5 spike — prove the web platform's runtime chain before building it.

This is deliberately NOT the platform. It is ~200 lines that answer one
question: can a new top-level ``server/`` drive ``BenchmarkSession`` with
per-run user config, per-run filesystem roots, a structured event stream,
cooperative stop, and artefact collection — without touching
``frontier_agent/``, ``workflows/``, ``plugins/tools/`` or ``benchmarks/``?

What it exercises, and the seam each one uses:

    pipeline registration  CWD = repo root (``_discover_pipeline_specs``)
    user LLM injection     profile YAML ``${OPENAI_*}`` placeholders
    event stream           metadata["sdk_extra_observers"]
    cooperative stop       metadata["pause_check"]
    per-run FS roots       FRONTIER_AGENT_{WORKSPACE,OUTPUTS,INPUTS}_DIR
    workspace authorising  CODING_WORKSPACE_ROOT
    trajectory location    metadata["_trial_dir"]
    prompt addendum        metadata["_sys_prompt_addendum"]

Two modes:

    uv run python server/spike.py
        In-process mock endpoint (``deploy/huggingface/mock_llm``), scripted to
        make exactly one ``create_file`` tool call. Zero API cost, deterministic.

    uv run python server/spike.py --real \
        --base-url https://open.bigmodel.cn/api/paas/v4 --model glm-5.3-flash \
        --api-key "$KEY"
        Real endpoint. This is the mode that decides go/no-go, because it is the
        only one that proves the endpoint can drive native function calling.

Writes ``<root>/summary.json`` for ``verify_spike.py`` to assert against.
Exit code is 0 only when the run itself completed; the acceptance gates live
in ``verify_spike.py`` so a failed spike still produces a diagnosable tree.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[1]

# ``_discover_pipeline_specs`` scans ``Path("workflows")`` relative to the CWD,
# so the spike must run from the repository root. Chdir rather than assert: the
# layout is a property of the runtime, not something a caller should remember.
os.chdir(REPO_ROOT)
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

SPIKE_PROMPT = (
    "Read the brief mounted at /inputs/brief.md, then write a short markdown "
    "summary to /outputs/report.md using create_file. Keep it under five lines."
)


def _preview(value: Any, limit: int = 400) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def build_tree(root: Path) -> dict[str, Path]:
    """Create the per-run directory tree the web platform would create per run.

    ``outputs`` is nested inside ``workspace`` on purpose: the react node
    authorises exactly one write root (``CODING_WORKSPACE_ROOT``), so a sibling
    ``outputs/`` would sit outside it. This is the layout
    ``deploy/huggingface/adapter.py`` ships.
    """
    workspace = root / "ws"
    paths = {
        "root": root,
        "workspace": workspace,
        "outputs": workspace / "outputs",
        "inputs": root / "inputs",
        "run": root / "run",
        "spill": root / "spill",
    }
    for path in paths.values():
        path.mkdir(parents=True, exist_ok=True)
    (paths["inputs"] / "brief.md").write_text(
        "# Brief\n\nSpike input file. Summarise this in one sentence.\n",
        encoding="utf-8",
    )
    return paths


def apply_env(paths: dict[str, Path], *, backend: str, wall_time_s: int,
              model: str, base_url: str, api_key: str) -> dict[str, str]:
    """Install per-run environment BEFORE anything imports ``infra.config``.

    ``get_config()`` caches on first read and ``_load_env_file`` uses
    ``override=False``, so anything set here wins over the repo ``.env`` for the
    lifetime of this process. That is exactly the property run-per-subprocess
    relies on; a pooled worker would leak user A's config into user B's run.
    """
    env = {
        # Filesystem isolation mode. Must be native or container: only those two
        # branches of the react node honour FRONTIER_AGENT_*_DIR. bwrap/auto
        # ignores them and derives <_trial_dir>/sandbox/{worktree,outputs}.
        "SANDBOX_BACKEND": backend,
        "FRONTIER_AGENT_WORKSPACE_DIR": str(paths["workspace"]),
        "FRONTIER_AGENT_OUTPUTS_DIR": str(paths["outputs"]),
        "FRONTIER_AGENT_INPUTS_DIR": str(paths["inputs"]),
        "CODING_WORKSPACE_ROOT": str(paths["workspace"]),
        # Tool-result overflow would otherwise land in the OS temp dir, outside
        # every per-run root.
        "APODEX_SPILL_DIR": str(paths["spill"]),
        "FRONTIER_AGENT_TASK_WALL_TIME_S": str(wall_time_s),
        "OPENAI_MODEL": model,
        "OPENAI_BASE_URL": base_url,
        "OPENAI_API_KEY": api_key,
        # Defence in depth, mirroring the HF deployment: no model-authored
        # command runs, so the absent unprivileged tool account is not a gap.
        "BASH_ALLOWLIST_MODE": "enforce",
        "FRONTIER_AGENT_TOOL_USER": "off",
    }
    os.environ.update(env)
    return env


class BridgeObserver:
    """The event bridge the web platform will need, in ~40 lines.

    Mirrors ``deploy.huggingface.adapter.StructuredEventObserver`` but writes
    JSONL directly instead of going through a channel, to prove the
    "events land on disk with a replayable line-number cursor" claim (FR-4.2)
    without also building the relay.
    """

    def __init__(self, sink: Any) -> None:
        self._sink = sink
        self.tool_calls: list[str] = []
        self.tool_errors: list[str] = []
        self.deltas = 0
        self.turns = 0
        self.stopped_by = ""

    async def on_llm_delta(self, ctx: Any) -> None:
        if getattr(ctx, "delta", None):
            self.deltas += 1
            self._sink("assistant_delta", text=ctx.delta)

    async def on_tool_call(self, ctx: Any, tool_call: dict[str, Any]) -> None:
        # The dict is OpenAI-shaped on the assistant-message path and flattened
        # on the streaming path; accept both rather than silently recording "".
        function = tool_call.get("function") or tool_call
        name = str(function.get("name") or "")
        self.tool_calls.append(name)
        # ``keys`` is diagnostic: the platform's L3 timeline wants an argument
        # preview at tool_started, so the spike records which keys the hook
        # actually receives rather than assuming the OpenAI wire shape.
        self._sink("tool_started", name=name,
                   args=_preview(function.get("arguments") or ""),
                   keys=sorted(tool_call))

    async def on_tool_result(self, ctx: Any, result: Any) -> None:
        text = str(getattr(result, "result", "") or "")
        failed = bool(getattr(result, "is_error", False)) or text.lstrip().startswith("Error")
        name = str(getattr(result, "name", "") or "")
        if failed:
            self.tool_errors.append(name)
        self._sink("tool_finished", name=name, ok=not failed, detail=_preview(text))

    async def on_turn_end(self, ctx: Any) -> None:
        self.turns = max(self.turns, int(getattr(ctx, "turn", 0) or 0))

    async def on_loop_start(self, config: Any) -> None:
        self._sink("run_started")

    async def on_loop_end(self, result: Any) -> None:
        # ``stopped_by`` lives on AgentLoopResult, not on the pipeline state the
        # runner returns — the platform must capture it here.
        self.stopped_by = str(getattr(result, "stopped_by", "") or "")
        self._sink("run_finished", stopped_by=self.stopped_by)


async def _false() -> bool:
    return False


def run_spike(*, paths: dict[str, Path], profile: str, timeout_s: int,
              pipeline_id: str,
              profile_overrides: dict[str, Any] | None = None) -> dict[str, Any]:
    """Bootstrap the runtime and execute one run. Returns the summary dict."""
    from benchmarks.public.core.kernel_adapter import BenchmarkSession

    events_path = paths["run"] / "events.jsonl"
    seq = {"n": 0}

    def sink(type_: str, **data: Any) -> None:
        seq["n"] += 1
        line = json.dumps({"seq": seq["n"], "type": type_, "ts": time.time(), **data},
                          ensure_ascii=False)
        with events_path.open("a", encoding="utf-8") as handle:
            handle.write(line + "\n")

    observer = BridgeObserver(sink)
    started = time.time()

    async def _go() -> dict[str, Any]:
        metadata: dict[str, Any] = {
            # Condition: without one of these the node silently falls back to
            # ResourceManager.get_llm() with profile=None.
            "profile": profile,
            # Wins over the named profile's YAML (deep-merged, applied last).
            # The sanctioned seam for giving the agent file tools without
            # editing workflows/: shipped profiles ship research-only tool
            # lists (simple/benchmark have no read_file or create_file).
            "profile_overrides": profile_overrides or None,
            # Teaches the model the /workspace, /outputs, /inputs convention.
            "fs_mode": True,
            "_trial_dir": str(paths["run"]),
            "coding_workspace_root": str(paths["workspace"]),
            "session_id": f"spike-{int(started)}",
            "turn_index": 1,
            "sdk_extra_observers": [observer],
            "pause_check": _false,
            # Ignored in native mode (bind mounts are a bwrap-branch concern),
            # included so the real-endpoint run proves it is harmless.
            "_sandbox_mounts": [
                {"src": str(paths["inputs"]), "dst": "/inputs", "mode": "ro"},
            ],
            "_sys_prompt_addendum": (
                "Input files are mounted read-only at /inputs. "
                "Write the final deliverable to /outputs."
            ),
        }
        async with BenchmarkSession() as session:
            return await asyncio.wait_for(
                session.run(SPIKE_PROMPT, meta=metadata, pipeline_id=pipeline_id),
                timeout=timeout_s,
            )

    error = ""
    state: dict[str, Any] = {}
    try:
        state = asyncio.run(_go())
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"

    answer = ""
    for key in ("final_answer", "final_content", "report", "answer", "output"):
        value = state.get(key)
        if isinstance(value, dict):
            value = value.get("content")
        if isinstance(value, str) and value.strip():
            answer = value.strip()
            break

    return {
        "error": error,
        "duration_s": round(time.time() - started, 2),
        "tool_calls": observer.tool_calls,
        "tool_errors": observer.tool_errors,
        "deltas": observer.deltas,
        "turns": observer.turns,
        "stopped_by": observer.stopped_by,
        "events_written": seq["n"],
        "answer": answer[:2000],
        "state_keys": sorted(state),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default="/tmp/frontier-spike",
                        help="spike tree root (default: %(default)s)")
    parser.add_argument("--backend", default="native",
                        choices=("native", "container"),
                        help="SANDBOX_BACKEND; must be native or container")
    parser.add_argument("--pipeline", default="stateful-react-agent")
    parser.add_argument("--profile", default="tui",
                        help="workflow profile; only 'tui' ships read_file/create_file")
    parser.add_argument("--agent-tools", default="",
                        help="comma-separated override for agent.agent_tools")
    parser.add_argument("--timeout", type=int, default=240)
    parser.add_argument("--wall-time", type=int, default=180)
    parser.add_argument("--model", default="mock-frontier-model")
    parser.add_argument("--base-url", default="")
    parser.add_argument("--api-key", default="")
    parser.add_argument("--real", action="store_true",
                        help="use a real endpoint instead of the in-process mock")
    args = parser.parse_args()

    if args.real and not (args.base_url and args.api_key):
        parser.error("--real requires --base-url and --api-key")

    root = Path(args.root).resolve()
    # Captured BEFORE the run so the acceptance gate can tell "the spike wrote
    # outside server/" apart from "the working tree was already dirty".
    baseline = subprocess.run(
        ["git", "status", "--porcelain"], cwd=REPO_ROOT,
        capture_output=True, text=True, check=False,
    ).stdout.strip().splitlines()
    paths = build_tree(root)

    server: Any = None
    base_url = args.base_url
    api_key = args.api_key
    if not args.real:
        from deploy.huggingface.mock_llm import (
            MockLLMServer,
            text_turn,
            tool_call_turn,
        )

        server = MockLLMServer(script=[
            tool_call_turn("create_file", {
                "path": "/outputs/report.md",
                "content": "# Spike report\n\nDeliverable written by create_file.\n",
            }),
            text_turn("Report written to /outputs/report.md."),
        ]).start()
        base_url = server.base_url
        api_key = "sk-spike-mock"

    apply_env(paths, backend=args.backend, wall_time_s=args.wall_time,
              model=args.model, base_url=base_url, api_key=api_key)

    overrides: dict[str, Any] = {}
    if args.agent_tools:
        overrides["agent"] = {
            "agent_tools": [n.strip() for n in args.agent_tools.split(",") if n.strip()],
        }

    try:
        summary = run_spike(paths=paths, profile=args.profile,
                            timeout_s=args.timeout, pipeline_id=args.pipeline,
                            profile_overrides=overrides or None)
    finally:
        if server is not None:
            server.stop()

    summary["paths"] = {k: str(v) for k, v in paths.items()}
    summary["config"] = {
        "backend": args.backend, "pipeline": args.pipeline, "profile": args.profile,
        "model": args.model, "real": args.real, "overrides": overrides,
    }
    summary["git_baseline"] = baseline
    (paths["run"] / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nspike tree: {root}")
    print(f"verify with: uv run python server/verify_spike.py --root {root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
