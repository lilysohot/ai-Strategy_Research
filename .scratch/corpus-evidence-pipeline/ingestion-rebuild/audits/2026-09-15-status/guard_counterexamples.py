"""Offline acceptance review only; temporary synthetic sources, no PG/model/network calls.

This diagnostic does not fix the guard. Exit 1 means its acceptance contract is unmet.
All mutations target a TemporaryDirectory owned by this script, never real corpus data.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

REPO = Path(__file__).resolve().parents[5]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--case", action="append")
    parser.add_argument("--out", type=Path)
    args = parser.parse_args()
    results = []
    with tempfile.TemporaryDirectory(prefix="i0-guard-review-") as directory:
        root = Path(directory)
        source = root / "sources"
        holdout = root / "holdout"
        protected = root / "protected"
        for folder in (source, holdout, protected):
            folder.mkdir()
        for file in (source / "sample.md", holdout / "secret.md", protected / "keep.md"):
            file.write_text("synthetic-only", encoding="utf-8")
        config = {
            "config_version": 1,
            "phase": "synthetic-review",
            "network": {"mode": "deny_all", "allowed_targets": []},
            "model": {
                "blocked_modules": ["fractions"],
                "blocked_module_prefixes": [],
                "poisoned_env": [],
                "poisoned_dsn": [],
            },
            "sources": {
                "read_roots": [str(source)],
                "allowed_source_paths": [],
                "forbidden_roots": [str(holdout)],
                "protected_roots": [str(protected)],
            },
        }
        config_path = root / "guard.json"
        config_path.write_text(json.dumps(config), encoding="utf-8")
        # Copy only the policy, replacing its protected root with a synthetic one.
        # No real source path is opened by any test body.
        i1 = json.loads((REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json").read_text())
        i1["sources"]["protected_roots"] = [str(source)]
        i1_path = root / "i1-synthetic.json"
        i1_path.write_text(json.dumps(i1), encoding="utf-8")

        prelude = (
            "import sys, os, subprocess, socket\n"
            f"sys.path.insert(0, {str(REPO)!r})\n"
            "from plugins.corpus.preparation import guard\n"
        )
        environment = {
            "PATH": os.defpath,
            "HOME": str(root),
            "LANG": "C.UTF-8",
            "PYTHONDONTWRITEBYTECODE": "1",
            "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        }

        def run_case(case_id: str, label: str, operation: str, *, cfg: Path = config_path,
                     wrapper: bool = False, plugin: bool = False) -> None:
            if args.case and case_id not in args.case:
                return
            # Only a guard-labelled refusal is accepted, not arbitrary IO/import failures.
            checked = (
                "try:\n"
                + "\n".join("    " + line for line in operation.splitlines())
                + "\nexcept (OSError, ImportError, guard.GuardError) as exc:\n"
                "    if 'corpus preparation guard' not in str(exc):\n"
                "        raise\n"
                "    print('GUARD_REFUSED')\n"
                "    raise SystemExit(0)\n"
                "print('POLICY_BYPASS')\n"
                "raise SystemExit(1)\n"
            )
            code = prelude
            if not wrapper and not plugin:
                code += f"guard.install({str(cfg)!r})\n"
            code += checked
            command = [sys.executable, "-I", "-B", "-c", code]
            if wrapper:
                command = [
                    sys.executable, "-I", "-B", "-c",
                    prelude + "raise SystemExit(guard.main(sys.argv[1:]))\n",
                    "--config", str(cfg), "--", *command,
                ]
            completed = subprocess.run(command, cwd=root, env=environment,
                                       text=True, capture_output=True, timeout=15, check=False)
            passed = completed.returncode == 0 and "GUARD_REFUSED" in completed.stdout
            result = {
                "id": case_id, "case": label, "expected": "guard_refusal",
                "passed": passed, "exit_code": completed.returncode,
                "observed": completed.stdout.strip(),
                "stderr": completed.stderr.strip().replace(str(root), "<TEMP>"),
            }
            results.append(result)
            print(f"{case_id} {'PASS' if passed else 'FAIL'} {label}: {result['observed']}")

        run_case("C01", "absolute forbidden read (positive control)",
                 f"open({str(holdout / 'secret.md')!r}).read()")
        run_case("C02", "relative forbidden read", "open('holdout/secret.md').read()")
        run_case("C03", "relative protected write", "open('protected/keep.md', 'w').write('changed')")
        run_case("C04", "absolute protected unlink", f"os.unlink({str(protected / 'keep.md')!r})")
        run_case("C05", "empty allowed_source_paths denies source read",
                 f"open({str(source / 'sample.md')!r}).read()")
        run_case("C06", "I1 empty read_roots denies source read (synthetic root)",
                 f"open({str(source / 'sample.md')!r}).read()", cfg=i1_path)
        run_case("C07", "CLI wrapper preserves guard in exec target",
                 f"open({str(holdout / 'secret.md')!r}).read()", wrapper=True)
        child_code = f"open({str(holdout / 'secret.md')!r}).read(); print('CHILD_READ')"
        run_case("C08", "ordinary child inherits file guard",
                 "child = subprocess.run([sys.executable, '-I', '-B', '-c', "
                 f"{child_code!r}], capture_output=True, text=True, check=False)\n"
                 "if child.returncode != 0 and 'corpus preparation guard' in child.stderr:\n"
                 "    raise guard.GuardError('corpus preparation guard: child refused')\n"
                 "assert child.returncode == 0 and 'CHILD_READ' in child.stdout\n"
                 "print('CHILD_READ_CONFIRMED')")
        run_case("C09", "pytest phase without config fails closed",
                 "os.environ['CORPUS_GUARD_PHASE'] = 'i1'\n"
                 "os.environ.pop('CORPUS_GUARD_CONFIG', None)\n"
                 "from plugins.corpus.preparation import guard_pytest\n"
                 "guard_pytest.pytest_load_initial_conftests([], None, None)", plugin=True)
        run_case("C10", "blocked stdlib module import (positive control)", "import fractions")
        # Audit-event replay only: never perform an actual socket connection or DNS lookup.
        run_case("C11", "deny_all rejects Unix socket connect audit event",
                 "class FakeSocket:\n    family = socket.AF_UNIX\n"
                 "sys.audit('socket.connect', FakeSocket(), '/synthetic-pg.sock')")
        run_case("C12", "deny_all rejects IPv4 connect audit event (positive control)",
                 "class FakeSocket:\n    family = socket.AF_INET\n"
                 "sys.audit('socket.connect', FakeSocket(), ('127.0.0.1', 5432))")

    files = [
        "plugins/corpus/preparation/guard.py",
        "plugins/corpus/preparation/guard_pytest.py",
        "plugins/corpus/preparation/__init__.py",
        "tests/test_corpus_preparation_guard.py",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i0-inventory.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json",
        str(Path(__file__).resolve().relative_to(REPO)),
    ]
    report = {
        "artifact": "i0-status-guard-counterexamples", "date": "2026-09-15",
        "scope": "synthetic temporary files and audit-event replay only; no real corpus, PG, models or network requests",
        "python": sys.version.split()[0], "cases": results,
        "passed": sum(item["passed"] for item in results),
        "failed": sum(not item["passed"] for item in results),
        "fingerprints": {path: hashlib.sha256((REPO / path).read_bytes()).hexdigest() for path in files},
    }
    if args.out:
        with args.out.open("x", encoding="utf-8") as output:
            json.dump(report, output, ensure_ascii=False, indent=2)
            output.write("\n")
    print(f"SUMMARY {report['passed']} passed, {report['failed']} failed")
    return 1 if report["failed"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
