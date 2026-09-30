"""F02: build-context isolation for Web runtime data.

``deploy/Dockerfile.web`` does ``COPY server ./server`` with the repository root
as its build context, and ``server/config.py`` defaults ``runs_root`` /
``uploads_root`` **inside the source tree**. Without an ignore rule, trajectories,
inputs, outputs and diffs get baked into an image layer.

``.gitignore`` does not affect Docker, and a volume mounted later only masks the
path — it does not remove files already committed to a layer. So the ignore file
is the control, and it needs a test: a rule deleted during an unrelated refactor
would otherwise silently reintroduce data-bearing images.

These checks are static by design. Building the real image needs network access
to pull ``python:3.12-slim``; the dynamic sentinel evidence lives in the audit
record for this issue, not here.
"""

from __future__ import annotations

import fnmatch
from pathlib import Path, PurePosixPath

import pytest

REPO_ROOT = Path(__file__).resolve().parents[1]
DOCKERIGNORE = REPO_ROOT / ".dockerignore"


def _rules() -> list[str]:
    """Non-comment, non-empty patterns from the root ignore file."""
    lines = DOCKERIGNORE.read_text(encoding="utf-8").splitlines()
    return [ln.strip() for ln in lines if ln.strip() and not ln.strip().startswith("#")]


def _ignored(rules: list[str], rel_path: str) -> bool:
    """True when ``rel_path`` (or any ancestor directory) matches a rule.

    Mirrors the subset of ``.dockerignore`` semantics these rules rely on: a
    trailing ``/`` marks a directory pattern, otherwise the pattern is matched
    against each path prefix with fnmatch (``*``/``?``, no ``**`` recursion).
    A leading ``!`` is a negation and, as in Docker, the last matching rule wins.
    """
    parts = PurePosixPath(rel_path).parts
    ignored = False
    for depth in range(1, len(parts) + 1):
        prefix = "/".join(parts[:depth])
        for raw in rules:
            negated = raw.startswith("!")
            rule = raw[1:] if negated else raw
            pattern = rule.rstrip("/") if rule.endswith("/") else rule
            if fnmatch.fnmatch(prefix, pattern):
                ignored = not negated
    return ignored


# Runtime data that must never reach a build context or an image layer.
MUST_EXCLUDE = [
    "server/runs/3f2b1c4d5e6f7a8b9c0d1e2f3a4b5c6d/run/agent/trajectories/react_agent.jsonl",
    "server/runs/3f2b1c4d5e6f7a8b9c0d1e2f3a4b5c6d/inputs/report.pdf",
    "server/runs/3f2b1c4d5e6f7a8b9c0d1e2f3a4b5c6d/ws/outputs/result.xlsx",
    "server/runs/3f2b1c4d5e6f7a8b9c0d1e2f3a4b5c6d/diff/base/0000.bin",
    "server/dev.db",
    "server/dev.db-wal",
    "uploads/quarterly.pdf",
    "data/exports.csv",
]

# Build inputs the images actually COPY. Excluding any of these breaks the build.
MUST_KEEP = [
    "pyproject.toml",
    "uv.lock",
    "README.md",
    "config/providers.yaml",
    "frontier_agent/core/runtime/loop/agent_loop.py",
    "plugins/tools/_sandbox.py",
    "workflows/agent_team/spec.py",
    "apodex/cli.py",
    "server/app.py",
    "server/config.py",
    "server/alembic/versions/0003_turn_seq_unique.py",
    "benchmarks/public/runner/run_subprocess.py",
    "tools/check_symbols.py",
    "docker/entrypoint.sh",
    "deploy/Dockerfile.web",
    "web/package.json",
    "web/package-lock.json",
    "web/src/main.ts",
]

# Local-only trees that are large, carry no build value, and must stay local.
MUST_EXCLUDE_LOCAL = [
    "web/node_modules/vite/index.js",
    "web/dist/assets/index.js",
    "web/dist-ssr/server.js",
    "web/coverage/lcov.info",
    ".scratch/web-runtime-trace-hardening/spec.md",
    ".kilo/worktrees/elastic-sting/server/app.py",
    ".e5runs/result.json",
    ".e5runs_e5_160401-failed-infra/trace.jsonl",
    ".pytest_cache/v/cache/lastfailed",
    ".ruff_cache/foo",
    # Bare `__pycache__` / `*.pyc` only match at the root, hence the `**` rules.
    "server/__pycache__/store.cpython-312.pyc",
    "frontier_agent/components/observers/__pycache__/trajectory.cpython-312.pyc",
    "plugins/tools/__pycache__/_sandbox.cpython-312.pyc",
]


@pytest.fixture(scope="module")
def rules() -> list[str]:
    assert DOCKERIGNORE.is_file(), "root .dockerignore is missing"
    return _rules()


@pytest.mark.parametrize("rel_path", MUST_EXCLUDE)
def test_runtime_data_is_excluded(rules, rel_path):
    assert _ignored(rules, rel_path), f"runtime data would enter the image: {rel_path}"


@pytest.mark.parametrize("rel_path", MUST_EXCLUDE_LOCAL)
def test_local_only_trees_are_excluded(rules, rel_path):
    assert _ignored(rules, rel_path), f"local-only tree would bloat the context: {rel_path}"


@pytest.mark.parametrize("rel_path", MUST_KEEP)
def test_build_inputs_survive(rules, rel_path):
    assert not _ignored(rules, rel_path), f"ignore rule would break the build: {rel_path}"
    assert (REPO_ROOT / rel_path).exists(), f"listed build input does not exist: {rel_path}"


def test_frontend_ignore_is_inert_and_mirrored(rules):
    """``deploy/Dockerfile.frontend`` builds with the repo root as its context.

    Docker only reads ``<context-root>/.dockerignore``, so ``web/.dockerignore``
    never applies. Its rules have to be mirrored at the root; this guards against
    someone trusting the nested file instead.
    """
    nested = REPO_ROOT / "web" / ".dockerignore"
    assert nested.is_file()
    for line in nested.read_text(encoding="utf-8").splitlines():
        rule = line.strip()
        if not rule or rule.startswith("#") or rule.startswith("!"):
            continue
        if rule == ".git":
            # No .git exists under web/; the root-level rule already covers the
            # repository's own. Nothing to mirror.
            continue
        assert _ignored(rules, f"web/{rule.rstrip('/')}/probe"), (
            f"web/.dockerignore rule {rule!r} is inert and not mirrored at the root"
        )
