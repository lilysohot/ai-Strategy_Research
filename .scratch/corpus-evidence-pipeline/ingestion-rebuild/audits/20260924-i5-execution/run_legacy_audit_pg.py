"""Exercise legacy backup/audit compatibility in a disposable isolated database."""

from __future__ import annotations

import importlib.util
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[5]
OUT = Path(__file__).resolve().parent
OLD = (
    ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify"
)
sys.path.insert(0, str(ROOT))

spec = importlib.util.spec_from_file_location("i37_runner", OLD / "run_tests.py")
if spec is None or spec.loader is None:
    raise SystemExit("cannot load isolated-PG lane helper")
runner = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runner)
runner.HERE = OUT
runner.D2D6_DB = "i5_execution_legacy"

created = False
result: dict[str, object] | None = None
drop_result = False
try:
    legacy_dsn = runner.ensure_d2d6_db()
    created = True
    environment = runner.lane_env(guard=None, dsn=None)
    environment.update(
        CORPUS_DSN=legacy_dsn,
        CORPUS_I2_DSN="",
        CORPUS_TARGET_DB="",
        PYTHON_DOTENV_DISABLED="1",
    )
    result = runner.run_lane(
        "i5-legacy-audit",
        ["tests/test_corpus_audit.py", "tests/test_corpus_evidence_pipeline.py"],
        environment,
    )
finally:
    if created:
        drop_result = runner.drop_d2d6_db()

report = {
    "lane": result,
    "temporary_legacy_database_removed": drop_result,
    "scope": "backup column coverage and retired evidence-writer behavior",
}
(OUT / "legacy-audit-results.json").write_text(
    json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
)
if result is None or result["exit_code"] != 0 or not drop_result:
    raise SystemExit(1)
