"""Reproducible no-model regression lane; logs only in the current audit directory."""
import os
from pathlib import Path
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
BASE = HERE.parents[1]
ENV = {"PATH": os.environ.get("PATH", "/usr/bin:/bin"), "LANG": "C.UTF-8",
       "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1", "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1",
       "CORPUS_GUARD_PHASE": "i3", "CORPUS_GUARD_CONFIG": str(BASE / "guards/i3.json")}


def run(label, args, env=ENV):
    result = subprocess.run(args, cwd=ROOT, env=env, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, text=True)
    text = result.stdout + f"\nexit={result.returncode}\n"
    (HERE / f"{label}.txt").write_text(text)
    print(label, text[-4500:], flush=True)
    return result.returncode


if __name__ == "__main__":
    tests = sorted(str(p.relative_to(ROOT)) for p in (ROOT / "tests").glob("test_corpus_preparation*.py"))
    tests.remove("tests/test_corpus_preparation_guard.py")
    tests += ["tests/test_corpus_gap_review.py", "tests/test_corpus_gap_dispositions.py",
              "tests/test_corpus_scoring.py", "tests/test_corpus_cli.py", "tests/test_corpus_cli_isolation.py"]
    prefix = [sys.executable, "-B", "-m", "pytest", "--noconftest", "-c", "/dev/null",
              "-p", "no:cacheprovider", "-p", "plugins.corpus.preparation.guard_pytest"]
    # Admission tests read the two explicitly approved MD/DOCX sources during
    # collection. Use the existing E2E guard, never widen the no-read I3 guard.
    env = {**ENV, "CORPUS_GUARD_PHASE": "i3-e2e",
           "CORPUS_GUARD_CONFIG": str(BASE / "guards/i3-e2e.json")}
    codes = [run("regression-e2e-guard", [*prefix, *tests, "-q", "--tb=short",
                       "--basetemp", str(HERE / "regression-e2e-tmp")], env)]
    # Guard self-tests deliberately install different configurations in isolated
    # subprocesses; a preinstalled parent guard correctly prevents that swap.
    clean = {key: value for key, value in ENV.items() if not key.startswith("CORPUS_GUARD_")}
    codes.append(run("guard-self-tests", [*prefix, "tests/test_corpus_preparation_guard.py",
                     "-q", "--tb=short", "--basetemp", str(HERE / "guard-tests-tmp")], clean))
    raise SystemExit(int(any(codes)))
