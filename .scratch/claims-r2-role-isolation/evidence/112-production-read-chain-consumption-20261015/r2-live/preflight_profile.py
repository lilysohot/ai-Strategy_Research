"""Zero-call preflight: assert the semantic-query tool is actually bound.

Root cause of the r1-live invalid run: the workflow profile stayed on the
default ``tui`` (apodex react.yaml resolves ``workflow_profile`` from
``REACT_WORKFLOW_PROFILE``), so ``corpus_semantic_query`` never entered the
function list and the run burned budget on the plain-text path.

This script replicates the real seams without any model call:
1. force ``REACT_WORKFLOW_PROFILE=tui-semantic`` in-process (before config load);
2. apply the same alias override the runner uses;
3. resolve the profile and assert the tool name list;
4. assert the tool is in the plugins allowlist;
5. assert the manifest companion will be bound (A4 boundary).
"""

from __future__ import annotations

import json
import os
import sys

os.environ["REACT_WORKFLOW_PROFILE"] = "tui-semantic"

REQUIRED_TOOL = "corpus_semantic_query"
MANIFEST_TOOL = "corpus_submit_manifest"


def main() -> int:
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
    allowlisted = REQUIRED_TOOL in builtin_names
    manifest_will_bind = bool(set(names) & CORPUS_RETRIEVAL_TOOLS) and MANIFEST_TOOL_NAME not in names

    from apodex.cli import build_parser  # noqa: F401  (import-only: proves wiring loads)

    verdict = {
        "workflow_profile_env": os.environ["REACT_WORKFLOW_PROFILE"],
        "resolved_agent_tools": names,
        "required_tool_present": REQUIRED_TOOL in names,
        "required_tool_allowlisted": allowlisted,
        "manifest_companion_will_bind": manifest_will_bind,
        "model_requests": 0,
    }
    ok = verdict["required_tool_present"] and allowlisted and manifest_will_bind
    verdict["verdict"] = "PASS" if ok else "FAIL"
    print(json.dumps(verdict, ensure_ascii=False, indent=2))

    if not ok:
        print("REFUSE: 语义查询工具未接通，禁止发出模型请求", file=sys.stderr)
        return 3
    return 0


if __name__ == "__main__":
    sys.exit(main())
