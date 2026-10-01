#!/usr/bin/env python3
"""Single-command operational backup for the投研 Agent platform (F07).

Wraps ``pg_dump -Fc`` (custom format) for the business database with:

* **fail-closed target**: the output directory must exist and be writable
  (a real-bytes probe — the same lesson as the ``/readyz`` probe), otherwise
  the script exits 1 before touching anything;
* **post-dump integrity check**: ``pg_restore --list`` must succeed, so
  "backup exists" means "backup is restorable", not just a non-zero file;
* **sidecar manifest**: ts / db / bytes / sha256 / retention-days beside the
  dump, so a later audit can diff without re-reading;
* **retention pruning**: older dumps are pruned (default ``--keep-days 30``).
  The default is a documented maintenance decision, not a silent behaviour —
  ``--dry-run`` prints exactly what would be pruned first.

The dump lands in a configurable ``--out-dir``: point it at a mount or a
remote path for off-machine storage. (真正跨机异地仍需运维把第二台机器挂载为
该目录，本脚本保证的是"目标不可写就拒绝、备份可被 pg_restore 读取"。）

DB URL resolution order: ``--db-url`` > ``$SERVER_DATABASE_URL`` >
``<repo>/.env``. The ``+asyncpg`` scheme is converted to ``postgres://`` for
the pg client. No host pg client is required: when ``pg_dump`` is not on
``PATH``, the script falls back to ``docker exec <pg-container>``.

Exit codes: 0 = backup produced and verified; 1 = anything failed (nothing is
claimed on a partial/failed run).
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from pathlib import Path
from typing import BinaryIO

DB_URL_RE = re.compile(
    r"^(?P<scheme>[a-z]+)://(?P<user>[^:]+):(?P<pass>[^@]+)@(?P<host>[^:/]+)(?P<port>:\d+)?/(?P<db>[^?]+)"
)


def _repo_root() -> Path:
    return Path(__file__).resolve().parents[1]


def resolve_db_url(cli: str | None) -> str:
    """Resolve the business DB URL from CLI > env > <repo>/.env."""
    if cli:
        return cli
    if os.environ.get("SERVER_DATABASE_URL"):
        return os.environ["SERVER_DATABASE_URL"]
    env_file = _repo_root() / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line.startswith("SERVER_DATABASE_URL="):
                return line.split("=", 1)[1]
    raise SystemExit("无法解析业务库 URL：请用 --db-url / SERVER_DATABASE_URL / 仓库 .env")


def parse_url(url: str) -> dict[str, str]:
    """Split a DB URL into pg-client pieces, normalising the +asyncpg scheme."""
    plain = url.replace("+asyncpg", "").replace("+psycopg", "")
    match = DB_URL_RE.match(plain)
    if not match:
        raise SystemExit(f"无法解析数据库 URL（scheme://user:pass@host[:port]/db）：{plain[:60]}…")
    parts = match.groupdict()
    return {
        "scheme": parts["scheme"],
        "user": parts["user"],
        "password": parts["pass"],
        "host": parts["host"],
        "port": parts["port"].lstrip(":") if parts["port"] else "5432",
        "db": parts["db"],
    }


def _pg_client() -> tuple[str, list[str], str | None]:
    """Return (kind, base-command, cwd) for pg_dump/pg_restore invocation."""
    host_dump = shutil.which("pg_dump")
    if host_dump:
        return "host", [host_dump], None
    return "docker", ["docker", "exec", "-i", "pg"], None


def _run(
    cmd: list[str], *, stdout_fh: BinaryIO | None = None, env: dict[str, str] | None = None
) -> int:
    return subprocess.run(cmd, stdout=stdout_fh, stderr=subprocess.PIPE, env=env).returncode


def probe_dir(path: Path) -> None:
    """Fail-closed: the target must exist and accept a real write."""
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / f".backup-probe-{uuid.uuid4().hex[:8]}"
        probe.write_bytes(b"backup-probe")
        probe.unlink()
    except OSError as exc:
        raise SystemExit(f"备份目标不可写（{path}）：{exc}") from exc


def verify_restorable(dump: Path, pg: tuple[str, list[str], str | None]) -> None:
    """``pg_restore --list`` must succeed — else the backup is worthless."""
    kind, base, _ = pg
    if kind == "host":
        cmd = [*base, "--list", str(dump)]
        cmd = [cmd[0].replace("pg_dump", "pg_restore"), *cmd[1:]]
        code = _run(cmd)
    else:
        # No host client: copy the dump in, list it, remove it.
        container = "pg"
        tmp = f"/tmp/backup-check-{uuid.uuid4().hex[:8]}.dump"
        _run(["docker", "exec", container, "rm", "-f", tmp])
        subprocess.run(["docker", "cp", str(dump), f"{container}:{tmp}"], check=False)
        code = _run(["docker", "exec", container, "pg_restore", "--list", tmp])
        _run(["docker", "exec", container, "rm", "-f", tmp])
    if code != 0:
        raise SystemExit(f"完整性校验失败：pg_restore --list 退出码 {code}（{dump}）")


def prune(out_dir: Path, prefix: str, keep_days: int, dry_run: bool) -> list[Path]:
    """Prune dumps older than ``keep_days``; return what would/was removed."""
    cutoff = dt.datetime.now(dt.UTC) - dt.timedelta(days=keep_days)
    old: list[Path] = []
    for candidate in out_dir.glob(f"{prefix}-*.dump"):
        try:
            if dt.datetime.fromtimestamp(candidate.stat().st_mtime, tz=dt.UTC) < cutoff:
                old.append(candidate)
        except OSError:
            continue
    if dry_run:
        return old
    for path in old:
        path.unlink(missing_ok=True)
    return old


def main() -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--out-dir", required=True, help="备份落盘目录（异地存放请指向挂载点/远程路径）"
    )
    parser.add_argument("--prefix", default="apodex", help="备份文件前缀（默认 apodex）")
    parser.add_argument(
        "--keep-days", type=int, default=30, help="保留天数（默认 30，维护决策默认值）"
    )
    parser.add_argument(
        "--db-url", default=None, help="业务库 URL（默认读 SERVER_DATABASE_URL / .env）"
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将删除的旧备份，不写任何文件")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser()
    probe_dir(out_dir)

    if args.dry_run:
        stale = prune(out_dir, args.prefix, args.keep_days, dry_run=True)
        print(f"[dry-run] {len(stale)} 个旧备份将删除（保留 {args.keep_days} 天）：")
        for path in stale:
            print(f"  {path.name}")
        return 0

    url = resolve_db_url(args.db_url)
    info = parse_url(url)
    kind, base, _ = _pg_client()
    ts = dt.datetime.now(dt.UTC).strftime("%Y%m%dT%H%M%SZ")
    dump = out_dir / f"{args.prefix}-{ts}.dump"
    env = {**os.environ, "PGPASSWORD": info["password"]}

    # Dump. ``docker exec`` writes binary custom-format to stdout → file.
    if kind == "host":
        cmd = [
            *base,
            "--no-owner",
            "--no-acl",
            "-Fc",
            "-h",
            info["host"],
            "-p",
            info["port"],
            "-U",
            info["user"],
            "-d",
            info["db"],
        ]
    else:
        # ``docker exec -i pg pg_dump ...``: the base is the docker prefix, so
        # the program name must be appended here (the host branch already has it
        # in ``base``). ``-i`` keeps stdin open so the binary custom-format
        # stream is written to our stdout file handle, not a TTY.
        cmd = [
            *base,
            "pg_dump",
            "--no-owner",
            "--no-acl",
            "-Fc",
            "-U",
            info["user"],
            "-d",
            info["db"],
        ]
    with dump.open("wb") as fh:
        code = _run(cmd, stdout_fh=fh, env=env)
    if code != 0:
        dump.unlink(missing_ok=True)
        raise SystemExit(f"pg_dump 失败（退出码 {code}），未产生备份，已清理残留")

    verify_restorable(dump, _pg_client())

    manifest = {
        "tool": "scripts/web_backup.py",
        "created_utc": ts,
        "database": info["db"],
        "host": info["host"],
        "file": dump.name,
        "bytes": dump.stat().st_size,
        "sha256": hashlib.sha256(dump.read_bytes()).hexdigest(),
        "keep_days": args.keep_days,
        "format": "pg_dump -Fc (custom)",
    }
    (out_dir / f"{args.prefix}-{ts}.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    stale = prune(out_dir, args.prefix, args.keep_days, dry_run=False)
    print(f"备份完成并校验通过：{dump}")
    print(
        f"  数据库 {info['db']}@{info['host']}，{manifest['bytes']} 字节，sha256 {manifest['sha256'][:16]}…"
    )
    print(f"  保留 {args.keep_days} 天；清理旧备份 {len(stale)} 个")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit as exc:
        sys.exit(exc.code)
