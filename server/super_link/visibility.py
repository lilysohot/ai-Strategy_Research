"""Keep collaboration sessions out of the ordinary workbench, even when disabled."""

from sqlalchemy import inspect, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.sql.elements import ColumnElement

from server import store


async def ordinary_sessions(session: AsyncSession) -> ColumnElement[bool] | None:
    # Optional migrations may never have been installed. Inspect schema rather
    # than querying a missing table or depending on the runtime enable switch.
    connection = await session.connection()
    installed = await connection.run_sync(
        lambda sync: inspect(sync).has_table("super_link_participants")
    )
    if not installed:
        return None
    from server.super_link.models import SuperLinkParticipant

    return store.Session.id.not_in(select(SuperLinkParticipant.session_id))
