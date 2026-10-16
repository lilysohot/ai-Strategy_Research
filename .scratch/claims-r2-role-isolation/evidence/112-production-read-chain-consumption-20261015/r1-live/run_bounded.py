"""Launch one bounded M_main consumption run against the production read chain.

Same entry as 43 号 (evidence/81/run_bounded.py): alias override with a
single-tool allowlist, then apodex CLI in react mode. The query path resolves
through CORPUS_STRUCTURED_ROOT (108 号 placed production store) — no file
artifact mount, no production PG write.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--cwd", required=True)
    parser.add_argument("--prompt", required=True)
    args = parser.parse_args()
    prompt = Path(args.prompt).read_text(encoding="utf-8").strip()

    from workflows.stateful_react_agent import profile

    profile._ALIAS_OVERRIDES["tui-semantic"] = {
        "agent": {
            "agent_tools": ["corpus_semantic_query"],
            "task_board": False,
        }
    }

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
