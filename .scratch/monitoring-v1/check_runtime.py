"""Read-only deployment precheck, intentionally excludes credentials and conversation content."""
import asyncio
from urllib.parse import urlparse

from sqlalchemy import text

from server.config import get_config
from server.store import get_engine


async def main():
    cfg = get_config()
    parsed = urlparse(cfg.database_url)
    print("database", parsed.hostname, parsed.port, parsed.path)
    print("monitor_flags", cfg.monitor_enabled, cfg.monitor_streams_enabled, cfg.auto_enabled)
    async with get_engine().connect() as conn:
        print("schema", (await conn.execute(text("select version_num from alembic_version"))).scalars().all())
        print("active_runs", (await conn.execute(text("select status, count(*) from runs where status in ('queued','running','waiting_approval') group by status"))).all())
        print("current_monitor_count", (await conn.execute(text("select count(*) from watch_rules where status <> 'cancelled'"))).scalar())
        print("database_size_bytes", (await conn.execute(text("select pg_database_size(current_database())"))).scalar())
        print("monitor_workers", (await conn.execute(text("select role, heartbeat_at, last_error from monitor_workers order by role"))).all())
    await get_engine().dispose()


asyncio.run(main())
