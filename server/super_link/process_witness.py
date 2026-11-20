"""Conservative Linux process evidence for abandonment, never successful publication."""

from __future__ import annotations

import uuid
from pathlib import Path

from server import store
from server.super_link import events
from server.super_link import models as sl


def _namespace() -> tuple[str, int]:
    return (
        Path("/proc/sys/kernel/random/boot_id").read_text().strip(),
        Path("/proc/self/ns/pid").stat().st_ino,
    )


def _stat(pid: int) -> tuple[str, int, str]:
    fields = Path(f"/proc/{pid}/stat").read_text().rsplit(") ", 1)[1].split()
    return fields[0], int(fields[2]), fields[19]


def capture(pid: int) -> dict | None:
    try:
        boot, namespace = _namespace()
        _, group, start = _stat(pid)
        if group != pid:
            return None
        return {"pid": pid, "group": group, "start": start, "boot": boot, "namespace": namespace}
    except (OSError, ValueError, IndexError):
        return None


def group_is_gone(identity: dict | None) -> bool:
    """Different host/namespace or unreadable evidence remains unknown, hence held."""
    if not identity:
        return False
    try:
        if _namespace() != (identity["boot"], identity["namespace"]):
            return False
        for entry in Path("/proc").iterdir():
            if not entry.name.isdigit():
                continue
            pid = int(entry.name)
            try:
                state, group, start = _stat(pid)
            except FileNotFoundError:
                continue
            if state not in {"Z", "X"} and (
                group == identity["group"]
                or (pid == identity["pid"] and start == identity["start"])
            ):
                return False
        return True
    except (OSError, ValueError, KeyError, IndexError):
        return False


async def record_launch(run_id: uuid.UUID, pid: int) -> None:
    identity = capture(pid)
    async with store.get_sessionmaker().begin() as session:
        row = await session.get(sl.SuperLinkFinalization, run_id, with_for_update=True)
        if row is not None and row.state == "executing":
            row.process_identity = identity
            run = await session.get(store.Run, run_id)
            if run is not None:
                await events.stage_for_session(
                    session,
                    run.session_id,
                    type="sl.finalization.changed",
                    change_key=f"finalization:{run_id}:launch:1",
                    data={
                        "state": row.state,
                        "worker_exited": row.worker_exited_at is not None,
                        "exit_code": row.exit_code,
                        "error_code": row.error_code,
                        "recovery_attempts": row.recovery_attempts,
                    },
                    invalidate=("runs", "deliveries", "actions"),
                    source_kind="run",
                    source_id=str(run_id),
                    run_id=run_id,
                )
                await events.seal_changes(session)
