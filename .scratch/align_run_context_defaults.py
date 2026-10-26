import asyncio
from sqlalchemy import text
from server.store import get_engine, reset_engine

async def main():
    engine = get_engine()
    async with engine.begin() as conn:
        await conn.execute(text("ALTER TABLE run_context_sources ALTER COLUMN pipeline_id SET DEFAULT ''"))
        await conn.execute(text("ALTER TABLE run_context_sources ALTER COLUMN completeness_json SET DEFAULT '{}'::json"))
    await reset_engine()

asyncio.run(main())
