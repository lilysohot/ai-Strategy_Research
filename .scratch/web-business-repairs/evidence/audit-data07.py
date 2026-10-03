"""Post-fix DATA-07 verification; writes only an ephemeral PostgreSQL container."""

import asyncio
import json
import secrets
import subprocess
import time
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from server import business_events, input_requests, store
from server.input_requests import _merge_collected


def command(*args: str) -> str:
    return subprocess.check_output(args, text=True).strip()


async def check_cursor(url: str) -> None:
    engine = create_async_engine(url)
    try:
        async with engine.begin() as connection:
            await connection.run_sync(store.Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        uid, first_research, second_research = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
        async with sessions.begin() as session:
            session.add(store.User(id=uid, username="audit", password_hash="unused"))
            await session.flush()
            session.add_all(
                [
                    store.Session(id=first_research, user_id=uid, title="first"),
                    store.Session(id=second_research, user_id=uid, title="second"),
                ]
            )
        async with sessions() as earlier:
            first = await business_events.add_event(
                earlier,
                user_id=uid,
                research_id=first_research,
                kind="input_required",
                title="first allocated",
                summary="audit",
            )
            await earlier.flush()

            async def add_second() -> store.BusinessEvent:
                async with sessions.begin() as later:
                    return await business_events.add_event(
                        later,
                        user_id=uid,
                        research_id=second_research,
                        kind="input_required",
                        title="second allocated",
                        summary="audit",
                    )

            second_task = asyncio.create_task(add_second())
            await asyncio.sleep(0.1)
            serialized_while_first_uncommitted = not second_task.done()
            await earlier.commit()
            second = await asyncio.wait_for(second_task, timeout=5)
            async with sessions() as reader:
                all_rows, cursor = await business_events.list_events(
                    reader,
                    user_id=uid,
                    after=0,
                    limit=100,
                )
            allocated = [first.cursor, second.cursor]
            committed = [row.cursor for row in all_rows]
            assert serialized_while_first_uncommitted
            assert allocated == [1, 2]
            assert committed == [1, 2]
            print(
                json.dumps(
                    {
                        "case": "event_allocation_serialized",
                        "second_blocked_before_first_commit": serialized_while_first_uncommitted,
                        "allocated": allocated,
                        "all_committed": committed,
                        "resume_after": cursor,
                    }
                )
            )

        request_id = uuid.uuid4()
        async with sessions.begin() as session:
            session.add(
                store.InputRequest(
                    id=request_id,
                    user_id=uid,
                    research_id=first_research,
                    use_case="general_reading",
                    fields_json=[{"name": "account.total_capital"}],
                    expires_at=datetime.now(UTC) - timedelta(seconds=1),
                )
            )
        async with sessions() as answering:
            request = (
                await answering.execute(
                    select(store.InputRequest)
                    .where(store.InputRequest.id == request_id)
                    .with_for_update()
                )
            ).scalar_one()
            # Isolate the row-lock/commit tail of an answer that passed expiry
            # validation before its deadline, then finished after the deadline.
            request.status = "answered"
            request.revision += 1
            await answering.flush()

            async def expire() -> None:
                async with sessions() as expiry:
                    await input_requests.expire_due(expiry, user_id=uid)
                    await expiry.commit()

            expiring = asyncio.create_task(expire())
            await asyncio.sleep(0.1)
            expiry_waited_for_answer = not expiring.done()
            await answering.commit()
            await asyncio.wait_for(expiring, timeout=5)
        async with sessions() as reader:
            request = await reader.get(store.InputRequest, request_id)
            assert expiry_waited_for_answer
            assert request.status == "answered"
            print(
                json.dumps(
                    {
                        "case": "expiry_preserves_committed_answer",
                        "expiry_blocked_on_answer": expiry_waited_for_answer,
                        "final_status": request.status,
                    }
                )
            )
    finally:
        await engine.dispose()


first, _, _ = _merge_collected({}, {"account": {"total_capital": "80000"}})
second, _, _ = _merge_collected(
    first,
    {
        "account": {"total_capital": {"value": "80000", "status": "pending_clarification"}},
    },
)
third, _, ambiguous = _merge_collected(second, {"plan": {"target_price": "28"}})
complete = {"account.total_capital", "plan.target_price"} <= {
    f"{group}.{name}" for group, fields in third.items() for name in fields
} and not ambiguous
assert not complete
assert "account" not in third
print(json.dumps({"case": "withdrawn_fact", "collected": third, "would_continue": complete}))

name = "frontier-data07-audit-" + uuid.uuid4().hex[:10]
password = secrets.token_hex(20)
try:
    command(
        "docker",
        "run",
        "--rm",
        "-d",
        "--name",
        name,
        "-e",
        "POSTGRES_USER=audit",
        "-e",
        "POSTGRES_PASSWORD=" + password,
        "-e",
        "POSTGRES_DB=frontier_business_audit",
        "-p",
        "127.0.0.1::5432",
        "postgres:15-alpine",
    )
    for _attempt in range(60):
        if (
            subprocess.run(
                ["docker", "exec", name, "pg_isready", "-h", "127.0.0.1", "-U", "audit"],
                capture_output=True,
            ).returncode
            == 0
        ):
            break
        time.sleep(0.25)
    port = command("docker", "port", name, "5432/tcp").rsplit(":", 1)[1]
    asyncio.run(
        check_cursor(
            f"postgresql+asyncpg://audit:{password}@127.0.0.1:{port}/frontier_business_audit"
        )
    )
finally:
    subprocess.run(["docker", "rm", "-f", name], capture_output=True)
    print("isolated audit container removed")
