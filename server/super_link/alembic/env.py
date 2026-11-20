"""Explicit optional-schema migration; never advances the legacy schema head."""

from __future__ import annotations

import asyncio

from alembic import context
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import create_async_engine
from sqlalchemy.pool import NullPool

from server.config import get_config
from server.super_link.models import Base

VERSION_TABLE = "super_link_alembic_version"


def migrate(connection: Connection) -> None:
    context.configure(
        connection=connection, target_metadata=Base.metadata, version_table=VERSION_TABLE
    )
    with context.begin_transaction():
        context.run_migrations()


async def online() -> None:
    engine = create_async_engine(get_config().database_url, poolclass=NullPool)
    try:
        async with engine.connect() as connection:
            await connection.run_sync(migrate)
    finally:
        await engine.dispose()


if context.is_offline_mode():
    context.configure(
        url=get_config().database_url,
        target_metadata=Base.metadata,
        version_table=VERSION_TABLE,
        literal_binds=True,
    )
    with context.begin_transaction():
        context.run_migrations()
else:
    asyncio.run(online())
