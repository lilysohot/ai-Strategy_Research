"""Verified database snapshot plus immutable source archive for the native corpus."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import tempfile
from datetime import UTC, datetime
from pathlib import Path
from typing import BinaryIO

import psycopg
from psycopg import sql
from psycopg.conninfo import conninfo_to_dict, make_conninfo


def pg_command(
    tool: str,
    arguments: list[str],
    *,
    connection: str | None = None,
    container: str | None = None,
    stdin: BinaryIO | None = None,
    stdout: BinaryIO | int = subprocess.PIPE,
) -> subprocess.CompletedProcess:
    """No shell, no password in argv, no provider/connection error bodies in logs."""
    env = os.environ.copy()
    if connection:
        fields = conninfo_to_dict(connection)
        if "password" in fields:
            env["PGPASSWORD"] = str(fields.pop("password"))
        arguments = [*arguments, "--dbname", make_conninfo("", **fields)]
    prefix = ["docker", "exec", "-i", "--env", "PGPASSWORD", container] if container else []
    try:
        result = subprocess.run(
            [*prefix, tool, *arguments],
            env=env,
            stdin=stdin,
            stdout=stdout,
            stderr=subprocess.PIPE,
            check=False,
        )
    except OSError:
        raise RuntimeError(f"{tool}_unavailable") from None
    if result.returncode:
        raise RuntimeError(f"{tool}_failed_exit_{result.returncode}")
    return result


def full_backup(
    connection: str,
    destination: Path,
    *,
    archive_root: Path,
    container: str | None = None,
) -> Path:
    """Export a consistent DB snapshot; publish a manifest only after all checks pass."""
    if destination.exists() and any(destination.iterdir()):
        raise ValueError("backup_destination_not_empty")
    archive = archive_root.resolve(strict=True)
    destination = destination.resolve()
    if not archive.is_dir() or destination.is_relative_to(archive):
        raise ValueError("invalid_backup_archive_path")
    destination.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".corpus-backup-", dir=destination.parent) as temp:
        staging = Path(temp)
        dump = staging / "corpus.dump"
        with psycopg.connect(connection) as conn:
            conn.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
            snapshot_row = conn.execute("SELECT pg_export_snapshot()").fetchone()
            if snapshot_row is None:
                raise RuntimeError("backup_snapshot_unavailable")
            snapshot = snapshot_row[0]
            # pg_dump deliberately omits relations owned by an installed extension:
            # their schema/data is supplied by CREATE EXTENSION on restore.  They
            # are not application tables and therefore must not make a verified
            # application snapshot look incomplete.  A non-empty extension-owned
            # table is different: pg_dump would not preserve its rows, so refuse
            # to produce a misleading "full" backup in that case.
            relations = conn.execute(
                "SELECT n.nspname,c.relname,EXISTS(SELECT 1 FROM pg_depend d "
                "WHERE d.classid='pg_class'::regclass AND d.objid=c.oid "
                "AND d.deptype='e') AS extension_owned FROM pg_class c "
                "JOIN pg_namespace n ON n.oid=c.relnamespace WHERE c.relkind='r' "
                "AND n.nspname NOT IN ('pg_catalog','information_schema') "
                "AND n.nspname NOT LIKE 'pg_toast%%' ORDER BY 1,2"
            ).fetchall()
            counts = {}
            for schema, table, extension_owned in relations:
                row = conn.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                ).fetchone()
                if row is None:
                    raise RuntimeError("backup_count_unavailable")
                if extension_owned:
                    if row[0]:
                        raise RuntimeError("backup_extension_owned_table_has_rows")
                    continue
                counts[f"{schema}.{table}"] = row[0]
            with dump.open("wb") as output:
                pg_command(
                    "pg_dump",
                    ["--format=custom", "--no-owner", "--no-acl", "--snapshot", snapshot],
                    connection=connection,
                    container=container,
                    stdout=output,
                )
            # Copy while the DB snapshot remains open. Source archives are append-only;
            # detect a file changing during copy instead of claiming a consistent backup.
            copied = {}
            for source in sorted(archive.rglob("*")):
                if source.is_symlink():
                    raise RuntimeError("archive_symlink_not_supported")
                if not source.is_file():
                    continue
                relative = source.relative_to(archive)
                if relative.parts[0] == "_staging":
                    continue
                target = staging / "archive" / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                with source.open("rb") as stream:
                    before = hashlib.file_digest(stream, "sha256").hexdigest()
                shutil.copy2(source, target)
                with target.open("rb") as stream:
                    after = hashlib.file_digest(stream, "sha256").hexdigest()
                if before != after:
                    raise RuntimeError("archive_changed_during_backup")
                copied[str(relative)] = after
        with dump.open("rb") as stream:
            listing = pg_command("pg_restore", ["--list"], container=container, stdin=stream)
        entries = set()
        for line in listing.stdout.decode().splitlines():
            tokens = line.partition(";")[2].split()
            if len(tokens) >= 6 and tokens[2:4] == ["TABLE", "DATA"]:
                entries.add(f"{tokens[4]}.{tokens[5]}")
        if not set(counts) <= entries:
            raise RuntimeError("backup_table_coverage_incomplete")
        with dump.open("rb") as stream:
            dump_hash = hashlib.file_digest(stream, "sha256").hexdigest()
        (staging / "manifest.json").write_text(
            json.dumps(
                {
                    "format": "corpus-full-backup-1",
                    "created_at": datetime.now(UTC).isoformat(),
                    "counts": counts,
                    "dump_sha256": dump_hash,
                    "archive_root": str(archive),
                    "archive_files": copied,
                    "restore_verified": False,
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        os.replace(staging, destination)
    return destination / "corpus.dump"


def full_restore(
    connection: str,
    source: Path,
    *,
    archive_out: Path,
    container: str | None = None,
) -> dict[str, int]:
    """Restore only into an empty database/archive, verifying hashes before any writes."""
    root = source.parent if source.is_file() else source
    manifest = json.loads((root / "manifest.json").read_text(encoding="utf-8"))
    if manifest.get("format") != "corpus-full-backup-1":
        raise ValueError("full_backup_manifest_required")
    dump = root / "corpus.dump"
    with dump.open("rb") as stream:
        if hashlib.file_digest(stream, "sha256").hexdigest() != manifest["dump_sha256"]:
            raise ValueError("backup_dump_hash_mismatch")
    files = []
    for relative, expected in manifest["archive_files"].items():
        if Path(relative).is_absolute() or ".." in Path(relative).parts:
            raise ValueError("backup_archive_path_invalid")
        path = (root / "archive" / relative).resolve()
        if not path.is_relative_to((root / "archive").resolve()):
            raise ValueError("backup_archive_path_invalid")
        with path.open("rb") as stream:
            if hashlib.file_digest(stream, "sha256").hexdigest() != expected:
                raise ValueError("backup_archive_hash_mismatch")
        files.append((path, relative))
    if archive_out.exists():
        raise ValueError("restore_archive_destination_exists")
    with psycopg.connect(connection) as conn:
        present = conn.execute(
            "SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace "
            "WHERE c.relkind IN ('r','p') AND n.nspname NOT IN ('pg_catalog','information_schema') "
            "AND n.nspname NOT LIKE 'pg_toast%%' LIMIT 1"
        ).fetchone()
        if present:
            raise ValueError("restore_requires_empty_database")
    archive_out.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".corpus-restore-", dir=archive_out.parent) as temp:
        staging = Path(temp)
        for path, relative in files:
            target = staging / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
        with dump.open("rb") as stream:
            pg_command(
                "pg_restore",
                ["--no-owner", "--no-acl", "--exit-on-error", "--single-transaction"],
                connection=connection,
                container=container,
                stdin=stream,
            )
        with psycopg.connect(connection) as conn:
            for qualified, expected in manifest["counts"].items():
                schema, table = qualified.split(".", 1)
                row = conn.execute(
                    sql.SQL("SELECT count(*) FROM {}.{}").format(
                        sql.Identifier(schema), sql.Identifier(table)
                    )
                ).fetchone()
                if row is None or row[0] != expected:
                    raise RuntimeError("restored_row_count_mismatch")
        os.replace(staging, archive_out)
    return manifest["counts"]
