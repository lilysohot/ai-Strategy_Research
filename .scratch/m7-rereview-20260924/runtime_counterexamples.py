"""Synthetic M7 re-review: no network, database connections, models, or source writes.

This script records S1/S2/retired-ingest closure and demonstrates that the
separately retired EvidenceRun writer still emits SQL for the old public table.
EvidenceRun shared types and financial validation are intentionally preserved;
the finding concerns only the approved writer retirement in I4-5.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
import socket
import sys
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))
os.environ["PYTHON_DOTENV_DISABLED"] = "1"
os.environ.pop("CORPUS_TARGET_DB", None)


def main() -> dict[str, object]:
    def forbidden(*args: object, **kwargs: object) -> None:
        raise AssertionError("Network or real database connection attempted")

    # Network remains blocked for imports and all verification operations.
    with patch.object(socket.socket, "connect", forbidden), patch.object(
        socket, "create_connection", forbidden
    ):
        import psycopg

        with patch.object(psycopg, "connect", forbidden):
            from plugins.corpus import service
            from plugins.corpus.evidence_pipeline import build_evidence_run_from_units
            from plugins.corpus.preparation import read_pg, search_pg

            os.environ["CORPUS_TARGET_DB"] = "postgres"
            svc = service.CorpusService("not-a-real-dsn")
            assert svc._target_db == "postgres"
            target_connection = MagicMock()
            target_cursor = target_connection.cursor.return_value.__enter__.return_value
            target_cursor.fetchone.return_value = ("postgres",)
            target_cursor.fetchall.return_value = [("postgres",), ("apodex",)]
            read_pg._check_target(target_connection, None)
            search_pg._check_target(target_connection, None)

            with patch.object(svc, "read_chain", return_value="new"), patch.object(
                svc, "search_with_coverage", return_value=(["sentinel"], {})
            ) as delegated:
                assert svc.search("  synthetic probe  ", limit=3) == ["sentinel"]
                delegated.assert_called_once_with("synthetic probe", limit=3)

            with patch.object(svc, "_connect") as connection:
                try:
                    svc.run_ingest("/nonexistent-synthetic-source")
                except service.RetiredIngestError:
                    pass
                else:
                    raise AssertionError("Retired ingest did not reject")
                connection.assert_not_called()

            # Pure in-memory units projection, with zero prose/model budget.
            run = build_evidence_run_from_units(
                "a" * 64,
                [{"locator": "unit:synthetic", "text": "Synthetic audit evidence."}],
                max_prose_calls=0,
            )
            with patch.object(svc, "_connect") as connection:
                returned = svc.save_evidence_run(run)
                cursor = connection.return_value.__enter__.return_value.cursor.return_value
                cursor = cursor.__enter__.return_value
                statements = [call.args[0] for call in cursor.execute.call_args_list]
                assert returned == run.run_id
                assert any("INSERT INTO corpus_evidence_runs" in sql for sql in statements)

            blocked = [name for name in ("openai", "anthropic") if name in sys.modules]
            assert not blocked, blocked
            return {
                "real_network_connections": 0,
                "real_database_connections": 0,
                "model_sdk_modules_loaded": blocked,
                "s1_late_env_service_target": svc._target_db,
                "s1_late_env_read_search_checks_passed": True,
                "s2_search_delegates_same_query_limit": True,
                "g2_ingest_rejected_before_connection": True,
                "g2_evidence_writer_still_returns_run_id": returned == run.run_id,
                "g2_evidence_writer_emitted_sql": statements,
                "requirements": [
                    "i4-cutover-manifest.json forbidden[1]: public old tables receive no writes",
                    "i45_tool_roundtrip.py lines 228-232: save_evidence_run recorded deactivated",
                    "I4-5: deactivate the approved old write entry points",
                ],
            }


if __name__ == "__main__":
    print(json.dumps(main(), ensure_ascii=False, indent=2))
