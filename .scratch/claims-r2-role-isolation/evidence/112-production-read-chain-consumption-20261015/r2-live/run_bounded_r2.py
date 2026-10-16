"""Bounded M_main consumption run against the production read chain (r2).

Fixes the r1-live seam failure: the workflow profile is forced in-process to
``tui-semantic`` BEFORE any config load, and a fail-closed preflight asserts the
semantic-query tool is really bound before a single model request is issued.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

# Must happen before any frontier_agent / apodex import resolves react.yaml.
os.environ["REACT_WORKFLOW_PROFILE"] = "tui-semantic"

REQUIRED_TOOL = "corpus_semantic_query"
MANIFEST_TOOL = "corpus_submit_manifest"


def preflight() -> dict:
    from workflows.stateful_react_agent import profile as wf_profile

    wf_profile._ALIAS_OVERRIDES["tui-semantic"] = {
        "agent": {
            "agent_tools": [REQUIRED_TOOL],
            "task_board": False,
        }
    }
    resolved = wf_profile.load_react_profile("tui-semantic")
    names = list((resolved.get("agent") or {}).get("agent_tools") or [])

    from plugins.tools import _BUILTIN_TOOLS
    from plugins.tools.corpus_manifest import CORPUS_RETRIEVAL_TOOLS, MANIFEST_TOOL_NAME

    builtin_names = {getattr(t, "name", "") for t in _BUILTIN_TOOLS}
    verdict = {
        "workflow_profile_env": os.environ["REACT_WORKFLOW_PROFILE"],
        "resolved_agent_tools": names,
        "required_tool_present": REQUIRED_TOOL in names,
        "required_tool_allowlisted": REQUIRED_TOOL in builtin_names,
        "manifest_companion_will_bind": bool(set(names) & CORPUS_RETRIEVAL_TOOLS)
        and MANIFEST_TOOL_NAME not in names,
        "model_requests": 0,
    }
    verdict["verdict"] = (
        "PASS"
        if all(
            verdict[k]
            for k in (
                "required_tool_present",
                "required_tool_allowlisted",
                "manifest_companion_will_bind",
            )
        )
        else "FAIL"
    )
    return verdict


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--prompt", required=True)
    parser.add_argument("--preflight-out", default=None)
    args = parser.parse_args()

    verdict = preflight()
    if args.preflight_out:
        Path(args.preflight_out).write_text(
            json.dumps(verdict, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    print("[preflight] " + json.dumps(verdict, ensure_ascii=False), flush=True)
    if verdict["verdict"] != "PASS":
        print("REFUSE: 语义查询工具未接通，禁止发出模型请求", file=sys.stderr)
        return 3

    prompt = Path(args.prompt).read_text(encoding="utf-8").strip()

    from apodex.cli import main as cli_main

    sys.argv = [
        "frontier-agent",
        "--mode",
        "react",
        "--native",
        "--cwd",
        args.cwd,
        "--no-tui",
        "--no-color",
        "--yes",
        "--print",
        "--max-turns",
        "8",
        prompt,
    ]
    return int(cli_main() or 0)


if __name__ == "__main__":
    raise SystemExit(main())
