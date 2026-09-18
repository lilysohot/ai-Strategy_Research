"""Re-run bounded existing gates without overwriting historical audit logs."""
import json
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
env = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8", "PYTHONPATH": str(ROOT),
       "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
       "CORPUS_GUARD_PHASE": "i3", "CORPUS_GUARD_CONFIG": str(BASE / "guards/i3.json")}
python = str(ROOT / ".venv/bin/python")
commands = {
    "regression": [python, "-B", "-m", "pytest", "--noconftest", "-c", "/dev/null",
        "-p", "no:cacheprovider", "-p", "plugins.corpus.preparation.guard_pytest",
        str(BASE / "audits/20260918-i32-remediation/test_approval_contract.py"),
        "tests/test_corpus_scoring.py", str(BASE / "audits/20260918-i30-review/test_review_probes.py"),
        "-q", "--tb=short"],
    "freeze-validation": [python, "-B", "-c",
        "import runpy; from plugins.corpus.preparation.guard import install; "
        f"install({str(BASE / 'guards/i3.json')!r}); "
        f"runpy.run_path({str(BASE / 'freezes/validate_i0c_freeze.py')!r}, run_name='__main__')"],
}
results = []
for name, command in commands.items():
    result = subprocess.run(command, cwd=ROOT, env=env, capture_output=True, text=True, check=False)
    with (HERE / (name + ".txt")).open("x", encoding="utf-8") as output:
        output.write("$ " + " ".join(command) + "\n" + result.stdout + result.stderr + f"\nexit={result.returncode}\n")
    print(name, result.returncode, result.stdout[-2200:], flush=True)
    results.append({"name": name, "exit_code": result.returncode})
with (HERE / "gate-reruns.json").open("x") as output:
    json.dump(results, output, indent=2)
sys.exit(0 if all(r["exit_code"] == 0 for r in results) else 1)
