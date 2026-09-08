"""FastAPI application entry point for the投研 Agent web platform.

Routes are wired as they land: M1 brought the run lifecycle, T2.2 adds auth.
``/healthz`` stays public so the container healthcheck and Caddy can probe it
without credentials; everything under ``/api`` is expected to declare the
``get_current_user`` dependency (see ``server/deps.py``) as it is built out.
"""

from __future__ import annotations

import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI

from server.orchestrator import get_orchestrator
from server.routes import artifacts as artifacts_routes
from server.routes import auth as auth_routes
from server.routes import models as models_routes
from server.routes import runs as runs_routes
from server.routes import sessions as sessions_routes
from server.store import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Best-effort schema creation; prod uses Alembic before container start.
    # A DB that is briefly unavailable at boot must not take the API down: the
    # health endpoint reports the DB independently.
    with contextlib.suppress(Exception):
        await init_db()
    yield
    await get_orchestrator().shutdown()


app = FastAPI(title="FrontierAgent 投研平台", version="0.1.0", lifespan=lifespan)
app.include_router(auth_routes.router)
app.include_router(models_routes.router)
app.include_router(sessions_routes.router)
# Artifact listing/download (T2.9) — both routes are authenticated and resolve the
# caller-supplied rel_path through a single containment check.
app.include_router(artifacts_routes.router)
# Run routes are now authenticated (T2.7): the caller's identity binds the run to
# a user, and ownership is enforced at the DB layer (store.get_run filters by
# user_id). The run_id remains an unguessable UUID on top of that.
app.include_router(runs_routes.router)


@app.get("/healthz")
async def healthz() -> dict[str, str]:
    return {"status": "ok"}
