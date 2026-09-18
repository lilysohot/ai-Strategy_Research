"""Read-only product review; writes generated logs only in this new audit directory."""
import json
from pathlib import Path
import runpy
import subprocess
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
PYTHON = ROOT / ".venv/bin/python"
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"


def run(name, args, env):
    result = subprocess.run(args, cwd=ROOT, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    (HERE / (name + ".txt")).write_text(
        "$ " + " ".join(map(str, args)) + "\n" + result.stdout +
        f"\nexit={result.returncode}\n", encoding="utf-8")
    print(name, "exit=", result.returncode)
    print(result.stdout)
    return result.returncode


def main():
    clean = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
             "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    codes = [run("freeze-validation", [str(PYTHON), "-B", str(BASE / "freezes/validate_i0c_freeze.py")], clean)]
    # Do not invoke verifier.main(): it rewrites historical matrix-summary.json.
    verifier = runpy.run_path(str(BASE / "audits/20260918-m5-review/verify_matrix.py"))
    verified = verifier["verify"](BASE / "audits/20260918-m5-review/evidence")
    (HERE / "m5-evidence-recheck.json").write_text(
        json.dumps(verified, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("M5 read-only evidence recheck:", len(verified["blocks"]), "blocks;",
          "misses=", verified["misses"], "errors=", verified["errors"])
    guarded = {**clean, "CORPUS_GUARD_PHASE": "i3", "CORPUS_GUARD_CONFIG":
               ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3.json"}
    prefix = [str(PYTHON), "-B", "-m", "pytest", "--noconftest", "-c", "/dev/null",
              "-p", "no:cacheprovider", "-p", "plugins.corpus.preparation.guard_pytest"]
    codes.append(run("baseline", [*prefix, "tests/test_corpus_scoring.py", "-q", "--tb=short"], guarded))
    codes.append(run("independent-probes", [*prefix, str(HERE / "test_review_probes.py"),
                               "-q", "--tb=short"], guarded))
    return int(any(codes) or bool(verified["errors"]) or bool(verified["misses"]))


if __name__ == "__main__":
    sys.exit(main())
