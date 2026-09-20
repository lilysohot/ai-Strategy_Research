import json
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
env = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8", "PYTHONPATH": str(ROOT),
       "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
python = [sys.executable, "-B"]
guard = [*python, "-m", "plugins.corpus.preparation.guard", "--config", str(BASE / "guards/i3.json"), "--"]
files = ["plugins/corpus/preparation/gap_review.py", "plugins/corpus/preparation/pdf_gap_regions.py",
         "plugins/corpus/preparation/gaps.py"]
checks = [
    ("collector-tests", [*python, "-m", "pytest", "--noconftest", "-c", "/dev/null", "-p", "no:cacheprovider",
                          "-p", "plugins.corpus.preparation.guard_pytest", str(HERE / "test_collector.py"), "-q"]),
    ("ruff", [*python, "-m", "ruff", "check", *files, "tests/test_corpus_gap_review.py"]),
    ("pyright", [*python, "-m", "pyright", *files]),
    ("symbols", [*guard, *python, "tools/check_symbols.py"]),
    ("import-stage1", [*guard, *python, "tools/import_smoke.py", "--stage", "1"]),
    ("import-stage2", [*guard, *python, "tools/import_smoke.py", "--stage", "2"]),
]
results = []
for name, command in checks:
    runenv = dict(env)
    if name == "collector-tests":
        runenv.update(CORPUS_GUARD_PHASE="i3", CORPUS_GUARD_CONFIG=str(BASE / "guards/i3.json"))
    result = subprocess.run(command, cwd=ROOT, env=runenv, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    (HERE / f"{name}.txt").write_text(result.stdout + f"\nexit={result.returncode}\n")
    results.append({"check": name, "exit": result.returncode, "command": command,
                    "note": "Global imports may be blocked by mandatory zero-model guard; not counted as passed" if name.startswith("import-") else ""})
    print(name, result.returncode, result.stdout[-700:], flush=True)
results.append({"check": "LLM preflight", "status": "not_run", "reason": "User's zero-model discipline: preflight issues a real model call."})
(HERE / "validation-results.json").write_text(json.dumps(results, ensure_ascii=False, indent=2) + "\n")
if any(r.get("exit", 0) for r in results if not r["check"].startswith("import-")):
    raise SystemExit(1)
