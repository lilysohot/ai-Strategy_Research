"""P7 acceptance: drive the new ``/api/corpus/items/{source_id}`` route over ASGI (zero model calls).

The point of this script is that it exercises the **real** route against the **real** production
structured store — real ``query_semantic``, real head cache, real fail-closed translation — while
replacing only the auth dependency, so no business-database connection is needed and nothing is
written. It also re-checks the 108 号 claims route on the same store to prove the items publication
did not disturb it.

Usage:
    python p7_items_endpoint_acceptance.py [--store-root PATH] [--record OUT.json]
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]  # .scratch/claims-r2-role-isolation
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

DEFAULT_STORE = REPO_ROOT / "data/corpus/structured-store"
SOURCES = {
    "industrial-fulian-md": "f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb",
    "optical-module-docx": "48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f",
}
EXPECTED_ITEMS = {"industrial-fulian-md": 80, "optical-module-docx": 119}


async def drive(store_root: Path) -> dict[str, Any]:
    from httpx import ASGITransport, AsyncClient

    from server.app import app
    from server.deps import get_current_user

    app.dependency_overrides[get_current_user] = lambda: object()
    transport = ASGITransport(app=app)
    results: dict[str, Any] = {}
    async with AsyncClient(transport=transport, base_url="http://p7") as client:
        for slug, source_id in SOURCES.items():
            roles: set[str] = set()
            total = 0
            pages = 0
            cursor: str | None = None
            last_status = 0
            page_status: Any = None
            while True:
                params: dict[str, Any] = {"limit": 50, "purpose": "cite"}
                if cursor:
                    params["cursor"] = cursor
                response = await client.get(f"/api/corpus/items/{source_id}", params=params)
                last_status = response.status_code
                if response.status_code != 200:
                    break
                body = response.json()
                page_status = body.get("page_status")
                records = body.get("records") or []
                total += len(records)
                roles |= {record["role"] for record in records}
                pages += 1
                cursor = body.get("next_cursor")
                if not cursor or pages >= 40:
                    break
            claims = await client.get(
                f"/api/corpus/claims/{source_id}", params={"limit": 5, "purpose": "compare"}
            )
            results[slug] = {
                "items_status": last_status,
                "items_total": total,
                "items_roles": sorted(roles),
                "items_pages": pages,
                "items_exhausted": not cursor,
                "items_page_status": page_status,
                "claims_compare_status": claims.status_code,
                "claims_compare_records": len(claims.json().get("records", []))
                if claims.status_code == 200
                else None,
            }
        unknown = await client.get("/api/corpus/items/does-not-exist", params={"limit": 1})
        results["unknown_source_status"] = unknown.status_code
        results["unauthorised_guard"] = "covered by tests/test_web_corpus_read_chain.py"
    app.dependency_overrides.clear()
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--store-root", default=str(DEFAULT_STORE))
    parser.add_argument("--record", default=None)
    args = parser.parse_args()

    store_root = Path(args.store_root).resolve()
    previous = os.environ.get("CORPUS_STRUCTURED_ROOT")
    os.environ["CORPUS_STRUCTURED_ROOT"] = str(store_root)
    try:
        results = asyncio.run(drive(store_root))
    finally:
        if previous is None:
            os.environ.pop("CORPUS_STRUCTURED_ROOT", None)
        else:
            os.environ["CORPUS_STRUCTURED_ROOT"] = previous

    failures: list[str] = []
    for slug, expected in EXPECTED_ITEMS.items():
        got = results[slug]
        if got["items_status"] != 200:
            failures.append(f"{slug}: items status {got['items_status']}")
        if got["items_roles"] != ["material_items"]:
            failures.append(f"{slug}: items page roles are {got['items_roles']}")
        if got["items_total"] != expected:
            failures.append(
                f"{slug}: items reachable over HTTP = {got['items_total']}, expected {expected}"
            )
        if not got["items_exhausted"]:
            failures.append(f"{slug}: items pagination did not exhaust")
    for slug in EXPECTED_ITEMS:
        if results[slug]["claims_compare_status"] != 200:
            failures.append(f"{slug}: claims compare route regressed after the items publication")
    if results["unknown_source_status"] != 404:
        failures.append(f"unknown source gave {results['unknown_source_status']}, expected 404")
    if failures:
        raise SystemExit(f"P7 acceptance failed: {failures}")

    record = {
        "schema_version": "items-web-endpoint-acceptance-1",
        "id": "109-items-extraction-and-publication-20261015",
        "created_on": "2026-10-15",
        "model_calls": 0,
        "production_pg_writes": 0,
        "method": (
            "ASGITransport 直驱真实路由 + 真实生产 store（query_semantic 与 head cache 全真），"
            "仅替换 get_current_user 依赖 ⇒ 不连业务库、不写任何东西"
        ),
        "store_root": str(store_root),
        "expected_items": EXPECTED_ITEMS,
        "observed": results,
    }
    print(json.dumps(record, ensure_ascii=False, indent=2))
    if args.record:
        from tools.evidence_guard import assert_writable, write_once

        target = Path(args.record).resolve()
        payload = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
        assert_writable(target, reason="109 号 P7 端点验收记录")
        write_once(target, payload)
        print(f"wrote {target} sha256={hashlib.sha256(payload.encode()).hexdigest()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
