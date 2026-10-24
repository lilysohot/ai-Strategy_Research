"""grep_search tool — search file contents using regex patterns."""

from __future__ import annotations

import base64
import json
import logging
import re
from pathlib import Path

from frontier_agent.core.tool import tool
from plugins.tools._sandbox import shell_quote as _shell_quote

logger = logging.getLogger(__name__)

_MAX_RESULT_CHARS = 8_000
_MAX_MATCHES = 50

_CONTEXT_RENDERER = r"""
import base64
import json
import sys

payload = json.loads(base64.b64decode(sys.argv[1]).decode("utf-8"))
context = int(payload["context"])
grouped = {}
for item in payload["matches"]:
    grouped.setdefault(item["path"], []).append(int(item["line"]))

for file_index, (path, selected_lines) in enumerate(grouped.items()):
    selected = set(selected_lines)
    ranges = []
    for line_number in sorted(selected):
        start = max(1, line_number - context)
        end = line_number + context
        if ranges and start <= ranges[-1][1] + 1:
            ranges[-1][1] = max(ranges[-1][1], end)
        else:
            ranges.append([start, end])
    wanted = {number for start, end in ranges for number in range(start, end + 1)}
    found = {}
    try:
        with open(path, "r", encoding="utf-8", errors="ignore") as handle:
            for number, line in enumerate(handle, start=1):
                if number in wanted:
                    found[number] = line.rstrip("\n\r")
                if ranges and number >= ranges[-1][1]:
                    break
    except OSError as exc:
        print(f"cannot read {path}: {exc}", file=sys.stderr)
        raise SystemExit(2)

    if file_index:
        print()
    print(f"## {path}")
    for range_index, (start, end) in enumerate(ranges):
        if range_index:
            print("--")
        for number in range(start, end + 1):
            if number not in found:
                continue
            prefix = ">" if number in selected else " "
            print(f"{prefix}{number}: {found[number]}")
""".strip()


def _bounded_grep_command(command: str, limit: int) -> str:
    """Limit stdout while preserving grep's own exit status.

    ``head`` may close the pipe after the requested prefix, in which case grep
    exits with SIGPIPE (141). That is a successful truncated probe; genuine grep
    errors such as an invalid expression or missing path must still propagate.
    """
    return (
        "set -o pipefail; "
        f"{command} | head -n {limit}; "
        "grep_status=${PIPESTATUS[0]}; "
        'if [ "$grep_status" -eq 141 ]; then exit 0; fi; '
        'exit "$grep_status"'
    )


def _parse_sandbox_matches(output: str, default_path: str) -> list[tuple[str, int, str]]:
    """Parse ``grep -H -Z -n`` output, tolerating the legacy test shape."""
    matches: list[tuple[str, int, str]] = []
    for row in output.splitlines():
        if "\0" in row:
            file_path, location = row.split("\0", 1)
        else:
            file_path, location = default_path, row
            with_file = re.match(r"^(.*):(\d+):(.*)$", row)
            if with_file:
                file_path = with_file.group(1)
                location = f"{with_file.group(2)}:{with_file.group(3)}"
        parsed = re.match(r"^(\d+):(.*)$", location)
        if parsed:
            matches.append((file_path, int(parsed.group(1)), parsed.group(2)))
    return matches


def _format_sandbox_matches(matches: list[tuple[str, int, str]], requested_path: str) -> str:
    rows: list[str] = []
    for file_path, line_number, content in matches:
        prefix = "" if file_path == requested_path else f"{file_path}:"
        rows.append(f"{prefix}{line_number}:{content}")
    return "\n".join(rows)


def _context_render_command(matches: list[tuple[str, int, str]], context_lines: int) -> str:
    payload = {
        "context": context_lines,
        "matches": [
            {"path": path, "line": line_number}
            for path, line_number, _content in matches
        ],
    }
    encoded = base64.b64encode(
        json.dumps(payload, ensure_ascii=False).encode("utf-8"),
    ).decode("ascii")
    return f"python3 -c {_shell_quote(_CONTEXT_RENDERER)} {_shell_quote(encoded)}"


def _local_grep(
    pattern: str,
    path: str,
    glob_filter: str | None,
    context_lines: int,
    max_results: int,
) -> str:
    """Fallback: search local allowed directories using Python re."""
    from plugins.tools._path_auth import _is_path_allowed, task_input_matcher
    from plugins.tools._sandbox import is_spill_path, spill_path_matcher
    from plugins.tools.ignore_rules import discover_repo_root, should_ignore_path

    search_path = Path(path)
    if not search_path.exists():
        return f"Error: path '{path}' does not exist"

    try:
        regex = re.compile(pattern)
    except re.error as e:
        return f"Error: invalid regex pattern: {e}"

    # Security: only search allowed directories
    allowed, reason = _is_path_allowed(str(search_path))
    if not allowed:
        return f"Access denied: {reason}"

    # Collect matching files. An explicit file path is a common coordinator
    # call shape for attached markdown/text files; Path.rglob() on a file
    # yields nothing and previously produced a misleading "No matches".
    if search_path.is_file():
        files = [search_path]
    elif glob_filter:
        files = sorted(search_path.rglob(glob_filter))
    else:
        files = sorted(f for f in search_path.rglob("*") if f.is_file())
    # Spill is hidden from ordinary workspace discovery on purpose, but an
    # explicit recovery-manifest path is an instruction to search that store.
    # Path authorization and per-file symlink checks below still apply.
    explicit_spill_search = (
        ".spill" in search_path.parts or is_spill_path(str(search_path))
    )
    repo_root = discover_repo_root(search_path if search_path.is_dir() else search_path.parent)
    # Both resolved once: each lookup re-reads env and resolves a path, ~12x the
    # cost of the string compare the loop needs. That is 1.01x on a real grep —
    # reading and scanning the file dwarfs it — so this is for legibility, not
    # speed: one place establishes the roots, and the loop below stays a filter.
    is_task_input = task_input_matcher()
    in_spill = spill_path_matcher()

    results: list[str] = []
    match_count = 0

    for fpath in files:
        if not explicit_spill_search and (".spill" in fpath.parts or in_spill(fpath)):
            continue
        # Authorizing only the search root is not enough: rglob walks into
        # symlinked descendants, so a link the model dropped in its workspace
        # would have this loop read the target. Every candidate is re-authorized
        # — unconditionally, because the link can be an ANCESTOR of the match
        # (``workspace/notes -> /etc`` makes ``notes/passwd`` an ordinary file),
        # which a per-file ``is_symlink`` test would miss.
        if not _is_path_allowed(str(fpath))[0]:
            continue
        if not fpath.is_file() or fpath.stat().st_size > 1_000_000:
            continue
        # Cheap ignore test first: only a file the repo rules would drop is
        # worth the input-mount check, which resolves the candidate's real path.
        if (
            not explicit_spill_search
            and should_ignore_path(fpath, repo_root)
            and not is_task_input(fpath)
        ):
            continue
        try:
            lines = fpath.read_text(encoding="utf-8", errors="ignore").splitlines()
        except Exception:
            continue

        file_matches: list[str] = []
        for i, line in enumerate(lines):
            if regex.search(line):
                start = max(0, i - context_lines)
                end = min(len(lines), i + context_lines + 1)
                for j in range(start, end):
                    prefix = ">" if j == i else " "
                    file_matches.append(f"{prefix}{j + 1}: {lines[j]}")
                if context_lines > 0:
                    file_matches.append("--")
                match_count += 1
                if match_count >= max_results:
                    break

        if file_matches:
            rel = fpath.relative_to(search_path) if fpath.is_relative_to(search_path) else fpath
            results.append(f"## {rel}\n" + "\n".join(file_matches))

        if match_count >= max_results:
            break

    if not results:
        return f"No matches found for pattern '{pattern}' in {path}"

    output = "\n\n".join(results)
    if match_count >= max_results:
        output += f"\n\n... (showing first {max_results} matches)"
    return output


@tool
async def grep_search(
    pattern: str,
    path: str = ".",
    glob: str | None = None,
    context_lines: int = 0,
    max_results: int = 50,
) -> str:
    """Search file contents using a regex pattern.

    Efficiently finds code patterns, function definitions, variable usage,
    and text across files. Supports regex, file filtering, and context lines.

    Args:
        pattern: Regular expression pattern to search for (e.g. "def foo", "import.*os").
        path: Directory to search in (default "."). Use absolute paths for sandbox.
        glob: File pattern filter (e.g. "*.py", "*.ts", "*.md"). Only searches matching files.
        context_lines: Number of lines to show before and after each match (default 0).
        max_results: Maximum number of matches to return (default 50).

    Returns:
        Matching lines with file paths and line numbers, grouped by file.
    """
    if not pattern or not pattern.strip():
        return "Error: search pattern is required."

    pattern = pattern.strip()
    max_results = max(1, min(max_results, _MAX_MATCHES))
    context_lines = max(0, min(context_lines, 5))

    from plugins.tools._sandbox import resolve_runtime_path
    path = resolve_runtime_path(path)

    from plugins.tools._path_auth import _is_path_allowed
    local_allowed, _ = _is_path_allowed(path)

    # Try E2B sandbox first when path is not an allowed local repo path
    try:
        from plugins.tools._sandbox import get_sandbox, sandbox_available
        if sandbox_available() and not local_allowed:
            sandbox = get_sandbox()

            # Probe one match beyond the requested limit. The old sandbox path
            # piped directly through ``head`` and returned a plausible-looking
            # prefix with no indication that more rows existed; a coordinator
            # could then cite that preview as the complete input.
            cmd = (
                "grep -rnH -Z --include='*' -E "
                f"{_shell_quote(pattern)} -- {_shell_quote(path)}"
            )
            if glob:
                cmd = (
                    f"grep -rnH -Z --include={_shell_quote(glob)} -E "
                    f"{_shell_quote(pattern)} -- {_shell_quote(path)}"
                )
            # Same rule as ``_local_grep``: the spill store stays out of ordinary
            # recursive discovery — surfacing it lets the agent re-read bodies
            # compaction just dropped — but an explicit recovery path is an
            # instruction to search it. ``_local_grep`` grew this in 8063ac8;
            # this branch is the one real workspace paths take, so it needs the
            # same rule or the store is only hidden when the sandbox is absent.
            if ".spill" not in Path(path).parts:
                cmd = cmd.replace("grep -rnH", "grep -rnH --exclude-dir=.spill", 1)
            probe_cmd = _bounded_grep_command(cmd, max_results + 1)

            result = sandbox.commands.run(probe_cmd, timeout=30)
            probe_output = result.stdout or ""
            if result.exit_code == 1 and not probe_output:
                return f"No matches found for pattern '{pattern}' in {path}"
            if result.exit_code not in (0, 1):
                # grep returns 1 for no matches, other codes are errors
                error = result.stderr or "unknown error"
                return f"Error: grep failed: {error}"

            if not probe_output.strip():
                return f"No matches found for pattern '{pattern}' in {path}"

            probe_matches = _parse_sandbox_matches(probe_output, path)
            if not probe_matches:
                return "Error: grep returned output in an unsupported format"
            truncated = len(probe_matches) > max_results
            displayed_matches = probe_matches[:max_results]
            if context_lines > 0:
                context_result = sandbox.commands.run(
                    _context_render_command(displayed_matches, context_lines),
                    timeout=30,
                )
                if context_result.exit_code != 0:
                    error = context_result.stderr or "unknown error"
                    return f"Error: context rendering failed: {error}"
                output = context_result.stdout or ""
            else:
                output = _format_sandbox_matches(displayed_matches, path)

            if truncated:
                output += (
                    "\n\n[Results truncated: this is an incomplete preview for "
                    f"max_results={max_results}. Additional matches exist; narrow "
                    "pattern/path or increase max_results.]"
                )

            # Apply overflow handling (truncate + save full to disk if needed)
            from plugins.tools._overflow import maybe_overflow
            return maybe_overflow("grep_search", output)
    except Exception as e:
        logger.debug("Sandbox grep failed: %s, trying local", e)

    # Local search
    return _local_grep(pattern, path, glob, context_lines, max_results)
