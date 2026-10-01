"""Recheck the E6 isolated database and frozen 51-target delivery matrix.

This verifier is deliberately zero-model and read-only.  It resolves the
configured corpus connection to ``e6_holdout_corpus``, confirms that every
holdout source has an active publication, then reruns the normal
``corpus_search -> corpus_fetch`` delivery scorer.  The result is evidence for
an administrative close-with-exceptions decision; it does not redefine the
frozen protocol or turn failed targets into passes.
"""
from __future__ import annotations

import asyncio
import importlib.util
import json
import os
import sys
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import dotenv
from psycopg.conninfo import conninfo_to_dict, make_conninfo

SCRIPT = Path(__file__).resolve()
HERE = SCRIPT.parent
ROOT = SCRIPT.parents[2]
TARGET_DB = "e6_holdout_corpus"
BUILD_ARTIFACT = HERE / "e6-holdout-build.json"
RESULT = HERE / "e6-closure-verification.json"

sys.path.insert(0, str(ROOT))
dotenv.load_dotenv(ROOT / ".env")


def _configure_isolated_database() -> str:
    from plugins.corpus.service import dsn

    base = conninfo_to_dict(dsn())
    target_dsn = make_conninfo(**{**base, "dbname": TARGET_DB})
    os.environ["CORPUS_DSN"] = target_dsn
    os.environ["CORPUS_TARGET_DB"] = TARGET_DB
    os.environ.pop("PGOPTIONS", None)
    return target_dsn


def _load_delivery_module() -> Any:
    path = HERE / "e5_data_delivery.py"
    spec = importlib.util.spec_from_file_location("e6_frozen_delivery", path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load delivery verifier: {path}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _delivery_summary(targets: list[dict[str, Any]]) -> dict[str, Any]:
    failures = [target for target in targets if not target["all_pass"]]
    by_role: dict[str, dict[str, Any]] = {}
    for role in sorted({str(target.get("role") or "unknown") for target in targets}):
        role_targets = [target for target in targets if target.get("role") == role]
        role_failures = [target for target in role_targets if not target["all_pass"]]
        by_role[role] = {
            "passed": len(role_targets) - len(role_failures),
            "failed": len(role_failures),
            "failure_classes": dict(Counter(target["first_fail"] for target in role_failures)),
        }
    return {
        "targets": len(targets),
        "passed": len(targets) - len(failures),
        "failed": len(failures),
        "failure_classes": dict(Counter(target["first_fail"] for target in failures)),
        "by_role": by_role,
    }


def main() -> int:
    target_dsn = _configure_isolated_database()

    from plugins.corpus.preparation.repository_pg import PgStore

    build_data = json.loads(BUILD_ARTIFACT.read_text(encoding="utf-8"))
    store = PgStore(target_dsn, sandbox_db=TARGET_DB)
    publications = []
    for source in build_data["sources"]:
        publication = store.get_publication(source["source_id"])
        active_build_id = publication.active_build_id if publication else None
        publications.append(
            {
                "sample_id": source["sample_id"],
                "source_id": source["source_id"],
                "expected_build_id": source.get("build_id"),
                "active_build_id": active_build_id,
                "generation": publication.generation if publication else None,
                "active": bool(active_build_id),
                "expected_build_active": active_build_id == source.get("build_id"),
            }
        )

    delivery = _load_delivery_module()
    rows = delivery._load_samples("holdout", set())
    targets = asyncio.run(delivery._run(rows))
    summary = _delivery_summary(targets)
    failures = [
        {
            "target_id": target["target_id"],
            "role": target["role"],
            "first_fail": target["first_fail"],
            "sample_id": target["sample_id"],
        }
        for target in targets
        if not target["all_pass"]
    ]
    target_results = [
        {
            "sample_id": target["sample_id"],
            "target_id": target["target_id"],
            "role": target["role"],
            "all_pass": target["all_pass"],
            "first_fail": target["first_fail"],
            "search_hits": target["search_hits"],
            "source_offered": target["source_offered"],
            "plans": target["plans"],
            "pages": target["pages"],
            "fetch_complete": target["fetch_complete"],
            "quote_delivered": target["quote_delivered"],
            "dependencies": target["dependencies"],
        }
        for target in targets
    ]
    publication_summary = {
        "sources": len(publications),
        "active": sum(item["active"] for item in publications),
        "expected_build_active": sum(item["expected_build_active"] for item in publications),
    }
    result = {
        "artifact": "e6-closure-verification",
        "generated_at": datetime.now(UTC).isoformat(),
        "mode": "zero-model; read-only; isolated database",
        "target_db": TARGET_DB,
        "publication_summary": publication_summary,
        "publications": publications,
        "delivery_summary": summary,
        "target_results": target_results,
        "failures": failures,
        "decision": {
            "status": "closed_with_accepted_exceptions",
            "strict_protocol_pass": False,
            "accepted_exception_count": len(failures),
            "basis": "owner accepted the documented retrieval/fetch residual risk",
        },
    }
    RESULT.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"publication": publication_summary, "delivery": summary}, ensure_ascii=False, indent=2))
    print(f"artifact={RESULT}")
    return 0 if publication_summary["active"] == len(publications) and len(targets) == 51 else 1


if __name__ == "__main__":
    raise SystemExit(main())
