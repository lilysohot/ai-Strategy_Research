"""G3b：用归档 crosswalk 的历史正文，补足 I4-6 隔离恢复验收门。

原 G3 报告已校验 backup manifest、11 张表计数、扩展、权限、引用键及七张
台账表。本补验不修改其 write-once 记录：在新的 one-off database 恢复同一
``postgres.dump``，再将 crosswalk 中每一个可解析的 ``(doc_id, block_locator,
block_text)`` 与恢复后的 ``public.blocks.text`` 逐字比较。正文比较是通过门的一
部分，不是信息性统计。生产容器和生产数据库均不写入。
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
WINDOW = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i4-window"
BACKUP = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/backups/i4-final-20260923T1544Z"
CROSSWALK = WINDOW / "i4c-exports/i4c-old-evidence-locator-crosswalk.jsonl"
G3_REPORT = ROOT / ".scratch/m7-fix-20260924/g3-isolated-restore-verification.json"
OUT = ROOT / ".scratch/m7-finalize-20260924/g3b-isolated-restore-body-verification.json"
VERIFY_DB = "i4_g3b_restore_20260924"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def run(args: list[str], *, stdin: Path | None = None) -> subprocess.CompletedProcess[str]:
    if stdin is None:
        return subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )
    with stdin.open("rb") as source:
        return subprocess.run(
            args,
            stdin=source,
            capture_output=True,
            text=True,
            timeout=900,
            check=False,
        )


def sql(statement: str, *, database: str = VERIFY_DB) -> str:
    proc = run(
        ["docker", "exec", "corpus-db", "psql", "-U", "postgres", "-d", database,
         "-At", "-F", "\x1f", "-v", "ON_ERROR_STOP=1", "-c", statement]
    )
    if proc.returncode:
        raise RuntimeError(f"psql {database} failed: {proc.stderr[:400]}")
    return proc.stdout


def expected_bodies() -> tuple[dict[tuple[str, str], str], int]:
    rows = [json.loads(line) for line in CROSSWALK.read_text(encoding="utf-8").splitlines() if line]
    unresolved = [row for row in rows if "block_text" not in row]
    expected: dict[tuple[str, str], str] = {}
    for row in rows:
        if "block_text" not in row:
            continue
        key = (str(row["doc_id"]), str(row["block_locator"]))
        body = str(row["block_text"])
        prior = expected.setdefault(key, body)
        if prior != body:
            raise RuntimeError(f"crosswalk has conflicting source bodies for {key!r}")
    if not expected or len(expected) + len(unresolved) != len(rows):
        raise RuntimeError("crosswalk rows are incomplete")
    return expected, len(unresolved)


def restored_bodies() -> dict[tuple[str, str], list[bytes]]:
    # Hex never wraps lines, so psql cannot alter embedded newlines or delimiters.
    output = sql(
        "SELECT doc_id, locator, encode(convert_to(text, 'UTF8'), 'hex') "
        "FROM public.blocks ORDER BY doc_id, locator"
    )
    result: dict[tuple[str, str], list[bytes]] = {}
    for line in output.splitlines():
        doc_id, locator, encoded = line.split("\x1f", 2)
        key = (doc_id, locator)
        result.setdefault(key, []).append(bytes.fromhex(encoded))
    return result


def main() -> int:
    if OUT.exists():
        raise SystemExit(f"write-once report already exists: {OUT}")
    expected, unresolved_count = expected_bodies()
    prior = json.loads(G3_REPORT.read_text(encoding="utf-8"))
    if prior.get("gate", {}).get("passed") is not True:
        raise SystemExit("prior G3 report is not a passing base for the body supplement")

    manifest = subprocess.run(
        ["sha256sum", "--check", "--quiet", "artifact-manifest.sha256"],
        cwd=BACKUP,
        capture_output=True,
        text=True,
        timeout=900,
        check=False,
    )
    manifest_count = sum(1 for line in (BACKUP / "artifact-manifest.sha256").read_text().splitlines() if line)
    manifest_ok = manifest.returncode == 0 and not manifest.stdout.strip()
    if VERIFY_DB in sql("SELECT datname FROM pg_database ORDER BY 1", database="postgres").split():
        raise SystemExit(f"one-off database already exists: {VERIFY_DB}")

    created = False
    destroyed = False
    restore_seconds: float | None = None
    mismatch_keys: list[tuple[str, str]] = []
    missing_keys: list[tuple[str, str]] = []
    ambiguous_keys: list[tuple[str, str]] = []
    actual: dict[tuple[str, str], list[bytes]] = {}
    try:
        sql(f"CREATE DATABASE {VERIFY_DB}", database="postgres")
        created = True
        started = time.perf_counter()
        restored = run(
            ["docker", "exec", "-i", "corpus-db", "pg_restore", "-U", "postgres", "-d", VERIFY_DB,
             "--no-owner", "--exit-on-error"],
            stdin=BACKUP / "postgres.dump",
        )
        restore_seconds = round(time.perf_counter() - started, 3)
        if restored.returncode:
            raise RuntimeError(f"pg_restore failed: {restored.stderr[:400]}")
        actual = restored_bodies()
        for key, expected_body in expected.items():
            bodies = actual.get(key)
            if not bodies:
                missing_keys.append(key)
            elif len(bodies) != 1:
                ambiguous_keys.append(key)
            elif bodies[0] != expected_body.encode("utf-8"):
                mismatch_keys.append(key)
    finally:
        if created:
            sql(f"DROP DATABASE IF EXISTS {VERIFY_DB} WITH (FORCE)", database="postgres")
            destroyed = VERIFY_DB not in sql(
                "SELECT datname FROM pg_database ORDER BY 1", database="postgres"
            ).split()

    bodies_ok = not missing_keys and not mismatch_keys and not ambiguous_keys and len(expected) == 290
    gate = manifest_ok and bodies_ok and destroyed
    report = {
        "artifact": OUT.name,
        "task": "M7 re-review F2 remediation: I4-6 historical source-body restore gate",
        "observed_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "source": {
            "backup": str(BACKUP.relative_to(ROOT)),
            "backup_manifest_entries": manifest_count,
            "backup_manifest_sha256": digest(BACKUP / "artifact-manifest.sha256"),
            "crosswalk": str(CROSSWALK.relative_to(ROOT)),
            "crosswalk_sha256": digest(CROSSWALK),
            "prior_g3_report": str(G3_REPORT.relative_to(ROOT)),
            "prior_g3_report_sha256": digest(G3_REPORT),
        },
        "restore": {
            "target": f"corpus-db isolated instance / one-off {VERIFY_DB}",
            "command": "pg_restore --no-owner --exit-on-error < postgres.dump",
            "exit_code": 0,
            "measured_seconds": restore_seconds,
            "production_write_paths_touched": False,
        },
        "body_comparison": {
            "method": "crosswalk resolved (doc_id, block_locator, block_text) vs restored "
                      "public.blocks(doc_id, locator, text), exact UTF-8 byte-preserving comparison",
            "crosswalk_rows": len(expected) + unresolved_count,
            "resolved_historical_bodies_expected": len(expected),
            "unresolved_non_numeric_locators_recorded": unresolved_count,
            "restored_body_rows": sum(len(bodies) for bodies in actual.values()),
            "missing": len(missing_keys),
            "mismatched": len(mismatch_keys),
            "ambiguous_locator_keys": len(ambiguous_keys),
            "result": "all historical bodies exact" if bodies_ok else "historical body mismatch",
        },
        "gate": {
            "passed": gate,
            "checks": [
                f"backup manifest {manifest_count}/{manifest_count} exact" if manifest_ok else "backup manifest failed",
                f"historical bodies {len(expected)}/{len(expected)} exact" if bodies_ok else "historical bodies failed",
                "one-off database destroyed" if destroyed else "one-off database teardown failed",
            ],
        },
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(report["gate"], ensure_ascii=False))
    return 0 if gate else 1


if __name__ == "__main__":
    raise SystemExit(main())
