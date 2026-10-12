"""Conformance check: does every evidence script guard its signed-artifact writes?

Wave 0 · P06. Static scan, zero model calls, read-only.

For each script under ``--root`` it reports:

* the write targets it can resolve statically,
* whether the script applies the shared guard (``tools.evidence_guard`` / ``write_once``)
  or an inline equivalent,
* and, cross-referenced with the real file system, whether any **already signed or frozen**
  artifact is writable by an unguarded script — the D9 partial-closure risk.

Exit code is non-zero when an unguarded script writes a signed artifact, so this can run as
a preflight gate.

Usage:
    uv run python tools/check_evidence_guard.py --root .scratch/claims-r2-role-isolation/evidence
    ... --json out.json
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import SIGNATURE_MARKERS, artifact_state  # noqa: E402

WRITE_CALLS = {"write_text", "atomic_write", "write_once", "dump", "write_bytes"}


@dataclass
class ScriptReport:
    """One evidence script's write surface and guard conformance."""

    path: str
    guarded: str
    write_targets: list[str] = field(default_factory=list)
    signed_targets_written: list[str] = field(default_factory=list)
    verdict: str = "ok"


def _guard_status(source: str) -> str:
    if "evidence_guard" in source and "write_once" in source:
        return "shared_guard"
    if "write_once" in source:
        return "shared_guard"
    if "拒绝写入" in source or "SIGNATURE_MARKERS" in source:
        return "inline_guard"
    if "已含签认标记" in source:
        return "inline_guard"
    return "unguarded"


def _literal_target(node: ast.AST) -> str | None:
    """Resolve ``HERE / "x.json"`` and ``Path("x.json")`` to a bare filename."""
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Div):
        return _literal_target(node.right)
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        return node.value
    return None


def _collect_targets(source: str) -> list[str]:
    """Resolve statically known write destinations.

    ``X.write_text(Y)`` writes to ``X``; ``atomic_write(X, Y)`` writes to ``X``.
    """
    tree = ast.parse(source)
    targets: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Call):
            continue
        function = node.func
        target_node: ast.AST | None = None
        if isinstance(function, ast.Attribute) and function.attr in ("write_text", "write_bytes"):
            target_node = function.value
        elif (
            isinstance(function, ast.Attribute) and function.attr in ("atomic_write", "write_once")
        ) or (isinstance(function, ast.Name) and function.id in ("atomic_write", "write_once")):
            target_node = node.args[0] if node.args else None
        if target_node is None:
            continue
        resolved = _literal_target(target_node)
        if resolved:
            targets.append(resolved)
    return sorted(set(targets))


def scan(root: Path, exemptions: set[str] | None = None) -> list[ScriptReport]:
    """Scan every ``*.py`` under ``root`` (excluding caches and before/ snapshot trees)."""
    exempt = exemptions or set()
    reports: list[ScriptReport] = []
    for script in sorted(root.rglob("*.py")):
        text_path = str(script)
        if "__pycache__" in text_path or "/before" in text_path or "/before-" in text_path:
            continue
        source = script.read_text(encoding="utf-8", errors="replace")
        try:
            targets = _collect_targets(source)
        except SyntaxError:
            reports.append(ScriptReport(str(script), "unparsable", [], [], "skipped"))
            continue
        guarded = _guard_status(source)
        signed_written = [
            name for name in targets if artifact_state(script.parent / name) == "signed"
        ]
        if guarded != "unguarded" or not signed_written:
            verdict = "ok"
        elif _relative(script) in exempt:
            verdict = "legacy_exempt"
        else:
            verdict = "violation"
        reports.append(ScriptReport(_relative(script), guarded, targets, signed_written, verdict))
    return reports


def load_exemptions(path: Path) -> set[str]:
    """Load the registry of executed legacy scripts that must not be patched in place."""
    if not path.exists():
        return set()
    payload = json.loads(path.read_text(encoding="utf-8"))
    return {str(item["script"]) for item in payload.get("exemptions", [])}


def _relative(script: Path) -> str:
    try:
        return str(script.relative_to(REPO_ROOT))
    except ValueError:
        return str(script)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", default=".scratch/claims-r2-role-isolation/evidence")
    parser.add_argument("--json", default=None)
    parser.add_argument("--exceptions", default="tools/evidence_guard_exceptions.json")
    parser.add_argument("--quiet", action="store_true")
    args = parser.parse_args()

    root = (REPO_ROOT / args.root).resolve()
    exemptions = load_exemptions(REPO_ROOT / args.exceptions)
    reports = scan(root, exemptions)
    violations = [item for item in reports if item.verdict == "violation"]
    legacy = [item for item in reports if item.verdict == "legacy_exempt"]
    unguarded = [item for item in reports if item.guarded == "unguarded"]
    signed_guarded = [
        item for item in reports if item.guarded != "unguarded" and item.signed_targets_written
    ]

    summary = {
        "root": str(root.relative_to(REPO_ROOT)) if root.is_relative_to(REPO_ROOT) else str(root),
        "scripts_scanned": len(reports),
        "guarded": sum(1 for item in reports if item.guarded != "unguarded"),
        "unguarded": len(unguarded),
        "violations": len(violations),
        "legacy_exempt": len(legacy),
        "signed_targets_protected": sum(
            len(item.signed_targets_written) for item in signed_guarded
        ),
        "signature_markers": list(SIGNATURE_MARKERS),
        "scripts": [asdict(item) for item in reports],
    }
    if args.json:
        Path(args.json).write_text(
            json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
    if not args.quiet:
        print(
            json.dumps(
                {k: v for k, v in summary.items() if k != "scripts"}, ensure_ascii=False, indent=1
            )
        )
        if violations:
            print("\n违约（新增的未加护栏写入者，必须修复）:")
            for item in violations:
                print(f"  {item.path} -> {item.signed_targets_written}")
        if legacy:
            print(f"\n历史例外（已执行、不得原地重跑；见 exceptions 登记）共 {len(legacy)} 个:")
            for item in legacy:
                print(f"  {item.path} -> {item.signed_targets_written}")
        if unguarded:
            print(f"\n未加护栏的脚本共 {len(unguarded)} 个（其中多数只写非签认产物）:")
            for item in unguarded[:10]:
                print(f"  {item.path} targets={item.write_targets or '<dynamic>'}")
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
