"""投研 profile overrides pushed from the server to the runtime.

The web platform never edits ``workflows/``. Instead it ships overrides through
the ``metadata["profile_overrides"]`` seam (deep-merged, applied last by the
react node) so the agent gets exactly the tool set a research product needs —
file tools for deliverables, and the market tools appended by the server (T4.2).

This is the sanctioned profile contract from tech-stack.md §5.4. It does NOT
touch any upstream file: visibility is controlled entirely from here.
"""

from __future__ import annotations

from typing import Any

# Baseline agent tool set for the投研 product. File tools (read_file /
# create_file) are the load-bearing wall for deliverables; market_* tools are
# appended by the server once the market plugin registers them (T4.2) — see
# ``market_tool_names`` below, which is empty until then and harmless.
BASE_AGENT_TOOLS = [
    "web_search",
    "web_fetch",
    "bash",
    "grep_search",
    "glob_search",
    "read_file",
    "create_file",
    "recover_result",
]

# Appended from the server side via profile_overrides. Empty at M1 (market tools
# land in T4.2); kept as a single hook so T4.3 only edits this list.
MARKET_TOOL_NAMES: list[str] = []


def build_profile_overrides() -> dict[str, Any]:
    """Construct the ``profile_overrides`` payload for ``metadata``.

    ``fs_mode=True`` teaches the model the /workspace /outputs /inputs convention
    and deliverable-writing rules; ``thinking_format="tag"`` declares the format
    explicitly so user-supplied unknown model names never fall into an inferred
    format they cannot emit (tech-stack.md §5.4).
    """
    agent_tools = [*BASE_AGENT_TOOLS, *MARKET_TOOL_NAMES]
    return {
        "agent": {
            "agent_tools": agent_tools,
            "fs_mode": True,
            "thinking_format": "tag",
        },
    }


# The profile name the worker passes as ``metadata["profile"]``. ``tui`` is the
# shipped profile that already carries read_file/create_file; we still layer the
# overrides above so the tool set is fully server-controlled and the market tools
# can be appended without editing the YAML.
PROFILE_NAME = "tui"
