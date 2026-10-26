import asyncio
from sqlalchemy import text
from server.store import get_engine, reset_engine

async def main():
    engine = get_engine()
    async with engine.connect() as conn:
        cols = (await conn.execute(text("""
            SELECT column_name, data_type, is_nullable, column_default
            FROM information_schema.columns
            WHERE table_schema = current_schema() AND table_name = 'run_context_sources'
            ORDER BY ordinal_position
        """))).all()
        constraints = (await conn.execute(text("""
            SELECT conname, contype, pg_get_constraintdef(oid)
            FROM pg_constraint
            WHERE conrelid = 'run_context_sources'::regclass
            ORDER BY conname
        """))).all()
        indexes = (await conn.execute(text("""
            SELECT indexname, indexdef FROM pg_indexes
            WHERE schemaname = current_schema() AND tablename = 'run_context_sources'
            ORDER BY indexname
        """))).all()
        count = (await conn.execute(text("SELECT count(*) FROM run_context_sources"))).scalar_one()
        print('COLUMNS', cols)
        print('CONSTRAINTS', constraints)
        print('INDEXES', indexes)
        print('ROWS', count)
    await reset_engine()

asyncio.run(main())
