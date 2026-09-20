"""Static checks and framework import checks, with no model requests."""
import os
from pathlib import Path
import runpy
import sys

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
runner = runpy.run_path(str(HERE / "run_checks.py"))
run = runner["run"]
env = {**runner["ENV"], "HOME": os.environ.get("HOME", "/home/administrator")}
files = ["plugins/corpus/preparation/gap_review.py", "plugins/corpus/preparation/gaps.py",
         "plugins/corpus/preparation/engine.py", "plugins/corpus/preparation/repository.py",
         "plugins/corpus/preparation/repository_pg.py", "plugins/corpus/cli.py"]
run("ruff", [str(ROOT / ".venv/bin/ruff"), "check", *files, "tests/test_corpus_gap_review.py"], env)
run("pyright", [str(ROOT / ".venv/bin/pyright"), *files], env)
run("symbols", [sys.executable, "-B", "tools/check_symbols.py"], env)
# Imports under the unchanged I3 guard: a generic framework smoke may be
# incompatible with the SDK import prohibition. Record that outcome honestly.
for stage in (1, 2):
    code = ("import runpy,sys; from plugins.corpus.preparation import guard; "
            "guard.install('.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3.json'); "
            f"sys.argv=['tools/import_smoke.py','--stage','{stage}']; "
            "runpy.run_path('tools/import_smoke.py',run_name='__main__')")
    run(f"import-smoke-stage-{stage}", [sys.executable, "-B", "-c", code], env)
prefix = [sys.executable, "-B", "-m", "pytest", "--noconftest", "-c", "/dev/null",
          "-p", "no:cacheprovider", "-p", "plugins.corpus.preparation.guard_pytest"]
run("human-gap-i3", [*prefix, "tests/test_corpus_gap_review.py", "-q", "--tb=short",
                     "--basetemp", str(HERE / "i3-only-tmp")], env)
