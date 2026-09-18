"""Bounded no-network regression runner and write-once pre-fix archive."""

import hashlib
import json
import shutil
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = BASE.parents[2]


def main():
    if sys.argv[1:] == ["archive"]:
        snapshot = json.loads((BASE / "freezes/i0c-r24.json").read_text())
        for group in ("i3_2_tooling", "i3_2_assets", "docs", "freeze_validator"):
            for relative, expected in snapshot["binding"][group].items():
                src = ROOT / relative
                dst = HERE / "before-r24" / relative
                assert hashlib.sha256(src.read_bytes()).hexdigest() == expected, relative
                if dst.exists():
                    assert dst.read_bytes() == src.read_bytes()
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        return 0
    label = sys.argv[1] if len(sys.argv) > 1 else "green"
    env = {
        "PATH": "/usr/bin:/bin",
        "LANG": "C.UTF-8",
        "PYTHONPATH": str(ROOT),
        "PYTHONDONTWRITEBYTECODE": "1",
        "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
        "CORPUS_GUARD_PHASE": "i3",
        "CORPUS_GUARD_CONFIG": str(BASE / "guards/i3.json"),
    }
    command = [
        str(ROOT / ".venv/bin/python"),
        "-B",
        "-m",
        "pytest",
        "--noconftest",
        "-c",
        "/dev/null",
        "-p",
        "no:cacheprovider",
        "-p",
        "plugins.corpus.preparation.guard_pytest",
        str(HERE / "test_approval_contract.py"),
        "tests/test_corpus_scoring.py",
        str(BASE / "audits/20260918-i30-review/test_review_probes.py"),
        "-q",
        "--tb=short",
    ]
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    text = (
        "$ "
        + " ".join(command)
        + "\n"
        + result.stdout
        + result.stderr
        + f"\nexit={result.returncode}\n"
    )
    with (HERE / (label + ".txt")).open("x", encoding="utf-8") as handle:
        handle.write(text)
    print(text)
    return result.returncode


if __name__ == "__main__":
    sys.exit(main())
