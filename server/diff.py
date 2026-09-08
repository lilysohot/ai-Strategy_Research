"""Run diff generation (P2.5, cli-web-parity.md §5.4).

Terminal baseline semantics, replicated for the web: the content a file had at
the moment the run FIRST touched it through a file tool is the baseline
(missing file → /dev/null); at run end every touched file is diffed against
that baseline into unified hunks with +/- statistics.

Three pieces, all worker-side and best-effort (a snapshot failure must never
break a run):

* :class:`DiffRecorder` — an ``sdk_extra_observers`` hook. Its ``on_tool_call``
  fires *before* the tool executes, which is exactly "首次写入前快照".
* ``snapshot_outputs_baseline`` — a run-start hash scan of the working
  directory (``ws``; the outputs subtree is covered by its own root).
* ``write_diff`` — run-end comparison, persisted as ``<run_root>/diff.json``.

Two change sources end up in the payload:

* ``source="file_tool"`` — snapshotted before/after pairs → real unified
  hunks. These are the entries :func:`revert_paths` acts on.
* ``source="bash_scan"`` — working-directory files whose hash changed vs the
  run-start baseline but that no file tool touched. Display-only (no hunks):
  bash writes are opaque here, matching the terminal's second diff class —
  the scan can see that the tree changed, never *who* changed it.

Per §2.2 binary and oversized files are skipped from the payload entirely (no
comparable baseline survives them); a first-touch snapshot on disk is still
kept so :func:`revert_paths` can restore the bytes.

**Revert (P3.3, §6.3)** restores exactly the ``file_tool`` class, from the same
manifest the diff was computed from. The ``bash_scan`` class is refused with an
explicit reason: a scan cannot tell the agent's write from the user's editor or
a dev server in the same window, so reverting it would destroy unrelated work —
the terminal's rule, kept verbatim.

Path handling reuses :func:`plugins.tools._sandbox.resolve_runtime_path` — the
same alias mapping the tools themselves get; no second resolution point. A
snapshot read is additionally contained: anything that resolves outside the
workspace/outputs roots is refused (fail-closed), so a hostile ``path``
argument cannot make the worker read arbitrary host files into the diff.
"""

from __future__ import annotations

import difflib
import hashlib
import json
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Tools whose primary target is a filesystem write (file_editor_view is
# read-only). All of them take the target as the ``path`` argument.
_SNAPSHOT_TOOLS = frozenset({
    "create_file",
    "write_file",
    "file_editor_create",
    "file_editor_str_replace",
})

# A baseline larger than this is not kept (a multi-GB input dropped into
# outputs should not be read into memory twice); the file then simply does not
# appear in the file-tool diff.
_MAX_SNAPSHOT_BYTES = 8 * 1024 * 1024

# Walk bounds for the run-start outputs scan, mirroring server.artifacts.
_MAX_SCAN_FILES = 500


def _is_binary(data: bytes) -> bool:
    """NUL-byte sniff — the same cheap oracle the preview classifier uses."""
    return b"\x00" in data[:8_192]


def _hash_tree(root: Path, *, skip: Path | None = None) -> dict[str, str]:
    """sha256 every regular file under ``root``, keyed by relative posix path.

    Shared by the run-start baseline scan and the run-end re-scan (§2.2 第二类).
    Symlinks (dirs and files) are skipped so a link cannot pull content from
    outside the root into the diff; ``skip`` prunes a nested subtree (the
    outputs dir inside the working directory) to avoid double counting.
    """
    hashes: dict[str, str] = {}
    if not root.is_dir():
        return hashes
    for dirpath, dirnames, filenames in os.walk(root, followlinks=False):
        dirnames[:] = [
            d
            for d in dirnames
            if not (Path(dirpath) / d).is_symlink()
            and (skip is None or (Path(dirpath) / d).resolve() != skip)
        ]
        for name in filenames:
            if len(hashes) >= _MAX_SCAN_FILES:
                break
            path = Path(dirpath) / name
            if path.is_symlink() or not path.is_file():
                continue
            digest = hashlib.sha256()
            try:
                digest.update(path.read_bytes())
            except OSError:
                continue
            hashes[path.relative_to(root).as_posix()] = digest.hexdigest()
    return hashes


def _unified_hunks(base: str, current: str, display: str) -> tuple[str, int, int]:
    """Unified diff text plus added/deleted line counts (markers excluded)."""
    diff = difflib.unified_diff(
        base.splitlines(keepends=True),
        current.splitlines(keepends=True),
        fromfile=f"a/{display}",
        tofile=f"b/{display}",
    )
    lines = list(diff)
    additions = sum(
        1 for ln in lines if ln.startswith("+") and not ln.startswith("+++")
    )
    deletions = sum(
        1 for ln in lines if ln.startswith("-") and not ln.startswith("---")
    )
    return "".join(lines), additions, deletions


class DiffRecorder:
    """Snapshots file-tool targets before their first write; emits diff.json."""

    def __init__(
        self,
        *,
        run_root: Path,
        outputs_root: Path,
        workspace_root: Path | None = None,
    ) -> None:
        self._run_root = Path(run_root)
        self._outputs_root = Path(outputs_root)
        self._diff_dir = self._run_root / "diff"
        self._base_dir = self._diff_dir / "base"
        self._manifest_path = self._diff_dir / "manifest.json"
        self._baseline_path = self._diff_dir / "outputs_baseline.json"
        # Scan roots for the second diff class (§2.2): the working directory
        # bash runs in, plus the deliverables dir. Keys in the baseline are
        # prefixed ("<root>/<rel>") so one dict can hold both trees; the
        # outputs subtree is pruned from the workspace walk (it has its own
        # root). ``workspace_root=None`` keeps the outputs-only behaviour.
        self._scan_roots: list[tuple[str, Path]] = [("outputs", self._outputs_root)]
        if workspace_root is not None:
            self._scan_roots.append(("workspace", Path(workspace_root)))
        # canonical display path → entry; first touch wins, later calls no-op.
        self._entries: dict[str, dict[str, Any]] = {}

    # — observer hook (sdk_extra_observers) ————————————————————————

    async def on_tool_call(self, ctx: Any, tool_call: dict[str, Any]) -> None:
        """Snapshot the target of a file-tool call before it executes.

        Deliberately returns ``None``: this observer only observes, it never
        rewrites or skips a call. All failures are swallowed — snapshotting is
        a UI nicety and must not disturb the run.
        """
        try:
            self._snapshot_tool_target(tool_call)
        except Exception:
            logger.warning("diff snapshot failed", exc_info=True)
        # The loop's notify_tool_call treats None as "continue".

    def _snapshot_tool_target(self, tool_call: dict[str, Any]) -> None:
        name = str(tool_call.get("name") or "")
        if name not in _SNAPSHOT_TOOLS:
            return
        args = tool_call.get("args")
        if not isinstance(args, dict):
            return
        raw = args.get("path")
        if not isinstance(raw, str) or not raw.strip():
            return
        display = os.path.normpath(raw)
        if display in self._entries:
            return  # first touch wins — the baseline must predate every write

        from plugins.tools._sandbox import resolve_mount_dirs, resolve_runtime_path

        host = Path(resolve_runtime_path(display))
        workspace, outputs, _inputs = resolve_mount_dirs()
        try:
            real = host.resolve()
            contained = any(
                real.is_relative_to(Path(root).resolve())
                for root in (workspace, outputs)
                if root
            )
        except (OSError, ValueError):
            return
        if not contained:
            return  # fail-closed: never read outside the writable roots

        if not host.is_file():
            self._entries[display] = {"snapshot": None}
            self._save_manifest()
            return
        try:
            if host.stat().st_size > _MAX_SNAPSHOT_BYTES:
                logger.info("diff baseline skipped (too large): %s", display)
                return
            data = host.read_bytes()
        except OSError:
            return
        self._base_dir.mkdir(parents=True, exist_ok=True)
        rel = f"{len(self._entries):04d}.bin"
        (self._base_dir / rel).write_bytes(data)
        self._entries[display] = {"snapshot": rel}
        self._save_manifest()

    def _save_manifest(self) -> None:
        self._diff_dir.mkdir(parents=True, exist_ok=True)
        self._manifest_path.write_text(
            json.dumps(self._entries, ensure_ascii=False), encoding="utf-8"
        )

    # — run-start baseline scan (second diff class) ——————————————————

    def snapshot_outputs_baseline(self) -> None:
        """Hash the working directory before the agent runs (§2.2 第二类).

        Files that change later without a file-tool snapshot are the bash-scan
        class: real status (added/modified/deleted), display-only.
        """
        baseline: dict[str, str] = {}
        try:
            self._diff_dir.mkdir(parents=True, exist_ok=True)
            for prefix, root in self._scan_roots:
                skip = self._outputs_root if root != self._outputs_root else None
                for rel, digest in _hash_tree(root, skip=skip).items():
                    baseline[f"{prefix}/{rel}"] = digest
            self._baseline_path.write_text(
                json.dumps(baseline, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            logger.warning("outputs baseline scan failed", exc_info=True)

    # — run-end diff ————————————————————————————————————————————————

    def write_diff(self) -> dict[str, Any]:
        """Compare baselines against the current tree; persist ``diff.json``."""
        files: list[dict[str, Any]] = []
        for display, entry in self._entries.items():
            self._diff_file_tool_entry(display, entry, files)
        files.extend(self._bash_scan_entries())
        body = {"files": files}
        try:
            self._run_root.mkdir(parents=True, exist_ok=True)
            (self._run_root / "diff.json").write_text(
                json.dumps(body, ensure_ascii=False), encoding="utf-8"
            )
        except OSError:
            logger.warning("diff.json write failed", exc_info=True)
        return body

    def _read_snapshot(self, entry: dict[str, Any]) -> bytes | None:
        rel = entry.get("snapshot")
        if not rel:
            return None
        try:
            return (self._base_dir / rel).read_bytes()
        except OSError:
            return None

    def _diff_file_tool_entry(
        self, display: str, entry: dict[str, Any], files: list[dict[str, Any]]
    ) -> None:
        from plugins.tools._sandbox import resolve_runtime_path

        host = Path(resolve_runtime_path(display))
        base = self._read_snapshot(entry)
        try:
            current: bytes | None = host.read_bytes() if host.is_file() else None
        except OSError:
            current = None
        if base is None and current is None:
            return  # snapshotted-but-missing then deleted, or unreadable: no change

        if base is None:
            status = "added"
        elif current is None:
            status = "deleted"
        else:
            status = "modified"

        # §2.2: binary files leave no comparable baseline — skipped from the
        # payload entirely; the first-touch snapshot stays on disk for P3.3.
        if _is_binary(base or b"") or _is_binary(current or b""):
            return
        if status == "deleted":
            hunks, additions, deletions = "", 0, 0
            if base is not None:
                _hunks, _a, deletions = _unified_hunks(
                    base.decode("utf-8", errors="replace"), "", display
                )
                hunks = _hunks
        else:
            hunks, additions, deletions = _unified_hunks(
                (base or b"").decode("utf-8", errors="replace"),
                (current or b"").decode("utf-8", errors="replace"),
                display,
            )
            if status == "modified" and not hunks:
                return  # rewritten to identical content
        files.append({
            "path": display,
            "status": status,
            "source": "file_tool",
            "hunks": hunks,
            "additions": additions,
            "deletions": deletions,
        })

    def _bash_scan_entries(self) -> list[dict[str, Any]]:
        """Working-directory files changed since the run-start baseline, minus
        the ones a file tool already covers. Display-only: status is real,
        hunks are not attempted."""
        try:
            baseline: dict[str, str] = json.loads(
                self._baseline_path.read_text(encoding="utf-8")
            )
        except (OSError, json.JSONDecodeError):
            return []

        covered = {
            os.path.normpath(path) for path in self._entries
        }
        current: dict[str, str] = {}
        for prefix, root in self._scan_roots:
            skip = self._outputs_root if root != self._outputs_root else None
            for rel, digest in _hash_tree(root, skip=skip).items():
                current[f"{prefix}/{rel}"] = digest

        # Baseline keys are "<root>/<rel>"; the root name maps to the sandbox
        # mount the tools display ("/outputs", "/workspace").
        def display_for(key: str) -> str:
            prefix, _, rel = key.partition("/")
            return f"/{prefix}/{rel}"

        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        for key, digest in current.items():
            display = display_for(key)
            if display in covered or digest == baseline.get(key):
                continue
            seen.add(key)
            entries.append({
                "path": display,
                "status": "added" if key not in baseline else "modified",
                "source": "bash_scan",
                "hunks": "",
                "additions": 0,
                "deletions": 0,
            })
        for key in baseline:
            if key in seen or display_for(key) in covered:
                continue
            if key not in current:
                entries.append({
                    "path": display_for(key),
                    "status": "deleted",
                    "source": "bash_scan",
                    "hunks": "",
                    "additions": 0,
                    "deletions": 0,
                })
        return entries


# ── revert (P3.3, cli-web-parity.md §6.3) ──────────────────────────


def run_writable_roots(run_root: Path) -> tuple[Path, Path]:
    """``(workspace, outputs)`` for a run — the two roots writes are contained in.

    Mirrors :func:`server.config.build_run_paths` without materialising the tree:
    a revert against a run whose directories were cleaned up must fail closed,
    not resurrect them.
    """
    workspace = Path(run_root) / "ws"
    return workspace, workspace / "outputs"


def load_manifest(run_root: Path) -> dict[str, Any]:
    """Read a persisted first-touch manifest; ``{}`` when the run never wrote."""
    path = Path(run_root) / "diff" / "manifest.json"
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def resolve_run_display_path(run_root: Path, display: str) -> Path | None:
    """Map a sandbox display path onto THIS run's own tree (server-side).

    The worker maps ``/workspace`` and ``/outputs`` through
    ``plugins.tools._sandbox.resolve_runtime_path`` using env vars that exist
    only in the worker process, so the same call in the server would hand back
    the literal alias. The server derives the identical mapping from the run
    layout instead, and accepts only those two aliases — the manifest can only
    ever hold paths inside them, so a wider mapping could only widen the blast
    radius (``/inputs``, ``/etc/passwd`` and relative paths are refused).

    Returns ``None`` for anything that escapes its root after resolution,
    symlinks included: a link the agent planted must not turn a revert into a
    write outside the run.
    """
    if not display or not display.startswith("/"):
        return None
    normalized = os.path.normpath(display)
    workspace, outputs = run_writable_roots(run_root)
    for alias, root in (("/workspace", workspace), ("/outputs", outputs)):
        if normalized == alias:
            # The root itself is a directory, never a snapshot target.
            return None
        prefix = alias + "/"
        if not normalized.startswith(prefix):
            continue
        candidate = root / normalized[len(prefix):]
        try:
            resolved = candidate.resolve()
            contained = resolved.is_relative_to(root.resolve())
        except (OSError, ValueError):
            return None
        return candidate if contained else None
    return None


#: Refusal reasons, with the operator-facing wording the terminal also gives.
#: ``not_snapshotted`` is the §2.2 第二类 case: reverting it would roll back
#: whatever else wrote into the same window, so it is handed to a human.
_REVERT_REASONS = {
    "not_snapshotted": "扫描发现，无法区分是否为 Agent 改动，请人工处理",
    "outside_roots": "路径不在本次运行的可写目录内",
    "missing_baseline": "运行前的基线快照已丢失",
    "io_error": "回滚写入失败",
}


def _revert_result(
    path: str,
    status: str,
    reason: str | None,
    *,
    detail: str | None = None,
) -> dict[str, Any]:
    out: dict[str, Any] = {"path": path, "status": status}
    if reason:
        out["reason"] = reason
        out["message"] = _REVERT_REASONS.get(reason, reason)
    if detail:
        out["detail"] = detail
    return out


def revert_paths(run_root: Path, paths: list[str]) -> dict[str, Any]:
    """Restore file-tool targets to the content they had before the run (§6.3).

    The manifest is the same allow-list the terminal's第一类 uses, so this can
    only ever undo what a file tool is known to have written. Everything else —
    notably the ``bash_scan`` class — comes back as ``status="rejected"`` with
    an explicit reason rather than being silently skipped: the UI must be able
    to explain why a row is not revertable, or the user assumes a bug.

    Two outcomes restore a file:

    * ``restored`` — a baseline existed and was written back.
    * ``removed``  — the baseline was ``/dev/null`` (the file did not exist
      before the run), so deleting it IS the revert; leaving it behind would
      preserve exactly the change the user asked to undo.

    ``diff.json`` is refreshed after any successful revert so the Diff tab drops
    what is no longer a change.
    """
    manifest = load_manifest(run_root)
    base_dir = Path(run_root) / "diff" / "base"
    results: list[dict[str, Any]] = []

    for raw in paths:
        display = os.path.normpath(str(raw))
        entry = manifest.get(display)
        if not isinstance(entry, dict):
            results.append(_revert_result(display, "rejected", "not_snapshotted"))
            continue
        target = resolve_run_display_path(run_root, display)
        if target is None:
            results.append(_revert_result(display, "rejected", "outside_roots"))
            continue

        snapshot = entry.get("snapshot")
        if snapshot:
            # Basename only: the manifest is worker-written, but its contents are
            # still data — never let a name in it climb out of the snapshot dir.
            snap = base_dir / Path(str(snapshot)).name
            if not snap.is_file():
                results.append(_revert_result(display, "rejected", "missing_baseline"))
                continue
            try:
                data = snap.read_bytes()
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            except OSError as exc:
                logger.warning("revert failed: %s", display, exc_info=True)
                results.append(_revert_result(display, "failed", "io_error", detail=str(exc)))
                continue
            results.append(_revert_result(display, "restored", None))
        else:
            try:
                if target.is_symlink() or target.is_file():
                    target.unlink()
            except OSError as exc:
                logger.warning("revert failed: %s", display, exc_info=True)
                results.append(_revert_result(display, "failed", "io_error", detail=str(exc)))
                continue
            results.append(_revert_result(display, "removed", None))

    reverted = [r["path"] for r in results if r["status"] in ("restored", "removed")]
    if reverted:
        _drop_diff_entries(run_root, set(reverted))
    return {"results": results, "reverted": reverted}


def _drop_diff_entries(run_root: Path, paths: set[str]) -> None:
    """Remove reverted paths from ``diff.json`` (P3.3 post-revert refresh).

    Re-deriving the whole payload here is *not* an option: ``write_diff`` maps
    display paths through ``resolve_runtime_path``, which reads the
    ``FRONTIER_AGENT_*_DIR`` env vars the worker process owns — in the server
    that call hands back the literal alias and every entry would come out as
    "deleted". Instead we drop exactly what the revert undid, which is the same
    result :meth:`DiffRecorder.write_diff` would produce: a restored file has
    base == current, the case it already leaves out of the payload (no hunks).
    """
    path = Path(run_root) / "diff.json"
    try:
        body = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return
    files = body.get("files")
    if not isinstance(files, list):
        return
    kept = [f for f in files if not (isinstance(f, dict) and f.get("path") in paths)]
    if len(kept) == len(files):
        return
    body["files"] = kept
    try:
        path.write_text(json.dumps(body, ensure_ascii=False), encoding="utf-8")
    except OSError:
        logger.warning("diff.json refresh after revert failed", exc_info=True)


__all__ = ["DiffRecorder", "revert_paths"]
