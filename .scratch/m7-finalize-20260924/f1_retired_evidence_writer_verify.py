"""F1 运行验收：旧 evidence 写入口必须在零连接前 fail-closed。"""
from __future__ import annotations

import hashlib
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

from plugins.corpus.service import CorpusService, RetiredEvidenceWriteError

ROOT = Path("/home/administrator/FrontierAgent")
OUT = ROOT / ".scratch/m7-finalize-20260924/f1-retired-evidence-writer-verification.json"
SOURCE = ROOT / "plugins/corpus/service.py"
TEST = ROOT / "tests/test_corpus_ingest_retired.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"write-once report already exists: {OUT}")
    service = CorpusService("postgresql://forbidden:forbidden@127.0.0.1:1/nowhere")
    with patch("psycopg.connect", side_effect=AssertionError("database connection attempted")) as connect:
        try:
            service.save_evidence_run(object())  # type: ignore[arg-type]
        except RetiredEvidenceWriteError as exc:
            rejection = str(exc)
        else:
            raise AssertionError("retired evidence writer unexpectedly returned")
    default_persist = inspect.signature(CorpusService.extract_claims).parameters["persist"].default
    passed = connect.call_count == 0 and default_persist is False
    report = {
        "artifact": OUT.name,
        "task": "M7 re-review F1 remediation: retired corpus_evidence_runs writer",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "service": str(SOURCE.relative_to(ROOT)),
            "service_sha256": digest(SOURCE),
            "regression_test": str(TEST.relative_to(ROOT)),
            "regression_test_sha256": digest(TEST),
            "runner_sha256": digest(Path(__file__)),
        },
        "checks": {
            "save_evidence_run_rejected": True,
            "exception": "RetiredEvidenceWriteError",
            "message": rejection,
            "psycopg_connect_calls": connect.call_count,
            "extract_claims_persist_default": default_persist,
        },
        "gate": {
            "passed": passed,
            "checks": [
                "old writer rejected before any database connection" if connect.call_count == 0 else "connection attempted",
                "extract_claims defaults to persist=False" if default_persist is False else "wrong persistence default",
            ],
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["gate"], ensure_ascii=False))
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
