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

from fastapi import FastAPI, Response, status

from server import store
from server.orchestrator import get_orchestrator
from server.routes import artifacts as artifacts_routes
from server.routes import auth as auth_routes
from server.routes import models as models_routes
from server.routes import runs as runs_routes
from server.routes import sessions as sessions_routes
from server.security import check_startup_secrets
from server.store import init_db


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    # Fail before serving traffic: a server started with the shipped keys signs
    # tokens with a secret anyone can read out of the repository.
    check_startup_secrets()
    # Best-effort schema creation; prod uses Alembic before container start.
    # A DB that is briefly unavailable at boot must not take the API down: the
    # health endpoint reports the DB independently.
    with contextlib.suppress(Exception):
        await init_db()
    # Runs still marked queued/running belong to a worker from a previous
    # process; nothing in this one will ever finish them, so close them out now
    # instead of leaving the UI waiting on a stream that can never end.
    with contextlib.suppress(Exception):
        await get_orchestrator().reconcile_orphan_runs()
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


async def _storage_probe(response: Response) -> dict[str, str]:
    """Shared liveness+readiness answer (F19).

    A process that is up but cannot reach its database must not be handed new
    work. Before this, health answered 200/``ok`` unconditionally, so a load
    balancer, an orchestrator or a human all read a storage outage as "fine" —
    and ``POST /api/runs`` kept accepting runs whose worker could not persist
    anything. ``store.check_db`` is looked up on the module at call time so the
    probe reflects the live engine (and is patchable in tests).

    Scope note: this proves the database ANSWERS. It does not yet assert that
    the schema is the one this build expects — that check belongs with the
    migration story (F19's remaining half) rather than here.
    """
    if not await store.check_db():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "storage_unavailable"}
    return {"status": "ok"}


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, str]:
    """Liveness probe, now coupled to storage readiness (F19).

    The path is unchanged on purpose: the container healthcheck and Caddy
    already probe it, so an existing deployment picks the signal up instead of
    having to be reconfigured to notice a dead store.
    """
    return await _storage_probe(response)


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, str]:
    """Explicit readiness probe (F19), for orchestrators that separate the two."""
    return await _storage_probe(response)
