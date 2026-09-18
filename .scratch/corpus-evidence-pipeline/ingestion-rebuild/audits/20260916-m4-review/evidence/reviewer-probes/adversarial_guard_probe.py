"""Adversarial guard probe (M4 review, reviewer-authored): 9 refusal/allow checks.

Provenance: first executed inside the M4 independent-review session (2026-09-16,
results recorded in review.md §2.3). This file is the frozen script; the sibling
``adversarial_guard_probe-output.txt`` is a re-run capture under the same guard
implementation/config (both hash-bound by freezes/i1-r3.json). Synthetic only:
no real PG / public network / model calls; the socket case replays an audit
event signal; the holdout path is never successfully opened.

Run (repo root, controlled minimal env):

    env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" \
      PYTHONDONTWRITEBYTECODE=1 \
      CORPUS_GUARD_PHASE=i1 \
      CORPUS_GUARD_CONFIG=".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json" \
      .venv/bin/python -B .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-m4-review/evidence/reviewer-probes/adversarial_guard_probe.py

Exit code: 0 = all 9 expectations met; 1 = mismatch (investigate).
"""
from __future__ import annotations

import hashlib
import json
import os
import socket
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

REPO = Path(__file__).resolve().parents[7]
CONFIG = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json"

sys.path.insert(0, str(REPO))
from plugins.corpus.preparation import guard  # noqa: E402


def main() -> int:
    config_sha = hashlib.sha256(CONFIG.read_bytes()).hexdigest()
    loaded = guard.install(str(CONFIG))
    if loaded.phase != "i1":
        raise RuntimeError(f"unexpected guard phase {loaded.phase!r}")
    cfg = json.loads(CONFIG.read_text(encoding="utf-8"))
    holdout = cfg["sources"]["forbidden_roots"][0]
    allowed = cfg["sources"]["allowed_source_paths"][0]

    results: dict[str, dict[str, object]] = {}

    def record(name: str, expected: str, actual: str) -> None:
        results[name] = {"expected": expected, "actual": actual, "ok": expected == actual}

    # 1) holdout content must be refused (never read)
    try:
        open(holdout, "rb").close()  # noqa: SIM115
        actual = "NOT_REFUSED"
    except OSError:
        actual = "REFUSED"
    record("read_holdout", "REFUSED", actual)

    # 2) unlisted path under read_roots must be refused (policy precedes existence)
    try:
        open("data/corpus/does-not-exist-probe.pdf", "rb").close()  # noqa: SIM115
        actual = "NOT_REFUSED"
    except OSError:
        actual = "REFUSED"
    record("read_unlisted", "REFUSED", actual)

    # 3) allow-listed file: read allowed (hash only, no content persisted)
    digest = hashlib.sha256(open(allowed, "rb").read()).hexdigest()  # noqa: SIM115
    record("read_allowed_hash", "ALLOWED", "ALLOWED" if len(digest) == 64 else "BAD")

    # 4) write into protected data/ must be refused
    try:
        open("data/probe-write.txt", "w").close()  # noqa: SIM115
        actual = "NOT_REFUSED"
    except OSError:
        actual = "REFUSED"
    record("write_data", "REFUSED", actual)

    # 5) model client import must be refused
    try:
        import openai  # noqa: F401

        actual = "NOT_REFUSED"
    except ImportError:
        actual = "REFUSED"
    record("import_openai", "REFUSED", actual)

    # 6) socket.connect audit replay (no real connection/DNS) must be refused
    class _Sock:
        family = socket.AF_INET

    try:
        sys.audit("socket.connect", _Sock(), ("203.0.113.1", 443))
        actual = "NOT_REFUSED"
    except OSError:
        actual = "REFUSED"
    record("socket_connect", "REFUSED", actual)

    # 7) non-Python child spawn must be refused
    try:
        subprocess.run(["/bin/true"], check=False)  # noqa: S603
        actual = "NOT_REFUSED"
    except Exception:
        actual = "REFUSED"
    record("spawn_nonpython", "REFUSED", actual)

    # 8) Python child inherits the guard via command-line rewrite
    child_code = (
        "import sys\n"
        "try:\n"
        f"    open({holdout!r}, 'rb').close(); print('CHILD_NOT_REFUSED')\n"
        "except OSError:\n"
        "    print('CHILD_REFUSED')\n"
    )
    child = subprocess.run(
        [sys.executable, "-I", "-B", "-c", child_code], capture_output=True, text=True
    )
    actual = f"{child.stdout.strip()}/rc={child.returncode}"
    results["child_python"] = {
        "expected": "CHILD_REFUSED/rc=0",
        "actual": actual,
        "ok": actual == "CHILD_REFUSED/rc=0",
    }

    # 9) env/DSN poisoning contract
    poisoned = (os.environ.get("OPENAI_API_KEY", ""), os.environ.get("CORPUS_DSN", ""))
    results["poisoned"] = {
        "expected": "CORPUS_GUARD_DISABLED / postgresql://corpus-guard:",
        "actual": f"{poisoned[0]} / {poisoned[1][:30]}",
        "ok": poisoned[0] == "CORPUS_GUARD_DISABLED"
        and poisoned[1].startswith("postgresql://corpus-guard:"),
    }

    all_ok = all(item["ok"] for item in results.values())
    report = {
        "probe": "adversarial-guard-probe",
        "timestamp": datetime.now(UTC).isoformat(timespec="seconds"),
        "guard_phase": loaded.phase,
        "config_sha256": config_sha,
        "results": results,
        "all_expected": all_ok,
    }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if all_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
