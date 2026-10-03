"""FastAPI application entry point for the投研 Agent web platform.

Routes are wired as they land: M1 brought the run lifecycle, T2.2 adds auth.
``/healthz`` stays public so the container healthcheck and Caddy can probe it
without credentials; everything under ``/api`` is expected to declare the
``get_current_user`` dependency (see ``server/deps.py``) as it is built out.

Two probes, because the remedies differ: ``/healthz`` reports whether storage
answers at all, ``/readyz`` additionally requires the schema this build expects
and a writable run-data root (F19). Startup applies the same gate and refuses to
serve when it fails — except in ``SERVER_DEBUG`` mode.
"""

from __future__ import annotations

import asyncio
import contextlib
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI, Response, status

from server import business_service as biz
from server import store
from server.config import get_config
from server.dispatch_outbox import dispatch_loop
from server.orchestrator import get_orchestrator
from server.readiness import enforce_startup_readiness, storage_readiness
from server.routes import artifacts as artifacts_routes
from server.routes import auth as auth_routes
from server.routes import business as business_routes
from server.routes import llm_configs as llm_configs_routes
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
    with contextlib.suppress(Exception):
        await init_db()
    # F19: a store this build cannot serve must stop the process taking work.
    # Previously every boot error was swallowed and the API answered "ok" on top
    # of a schema from an older revision, so the failure surfaced much later as
    # an opaque query error. Dev mode (SERVER_DEBUG) downgrades this to a loud
    # warning, because local SQLite databases are created unstamped.
    readiness = await storage_readiness()
    enforce_startup_readiness(readiness, debug=get_config().debug)
    # Runs still marked queued/running belong to a worker from a previous
    # process; nothing in this one will ever finish them, so close them out now
    # instead of leaving the UI waiting on a stream that can never end. Skipped
    # when the store is not ready: a dev-mode boot into a broken database must
    # not rewrite run rows it cannot read reliably.
    if readiness.ok:
        with contextlib.suppress(Exception):
            await get_orchestrator().reconcile_orphan_runs()
    # DATA-06: the dispatch loop turns committed outbox intents into workers.
    # It lives with the API process (start/stop with lifespan); multi-process
    # deployments share dispatching safely via SKIP LOCKED claims + leases.
    dispatch_task: asyncio.Task[None] | None = None
    if readiness.ok and get_config().dispatch_enabled:
        dispatch_task = asyncio.create_task(dispatch_loop(get_orchestrator()))
    yield
    if dispatch_task is not None:
        dispatch_task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await dispatch_task
    await get_orchestrator().shutdown()


app = FastAPI(title="FrontierAgent 投研平台", version="0.1.0", lifespan=lifespan)
app.include_router(auth_routes.router)
app.include_router(models_routes.router)
app.include_router(sessions_routes.router)
# F07-KEY-2: masked read-back + key reset for the caller's own LLM configs —
# the HTTP recovery path when SERVER_MASTER_KEY is rotated or lost.
app.include_router(llm_configs_routes.router)
# Artifact listing/download (T2.9) — both routes are authenticated and resolve the
# caller-supplied rel_path through a single containment check.
app.include_router(artifacts_routes.router)
# Run routes are now authenticated (T2.7): the caller's identity binds the run to
# a user, and ownership is enforced at the DB layer (store.get_run filters by
# user_id). The run_id remains an unguessable UUID on top of that.
app.include_router(runs_routes.router)
# 业务资料（DATA-03）：路由只做身份绑定与契约翻译，准入/版本/幂等在 business_service。
app.include_router(business_routes.router)
# 业务错误统一渲染为契约信封（字段定位、冲突、幂等、无权）；注册后才能覆盖默认 500。
app.add_exception_handler(biz.BusinessError, business_routes.business_error_handler)


async def _storage_probe(response: Response) -> dict[str, str]:
    """Storage-connectivity answer (F19, first half).

    A process that is up but cannot reach its database must not be handed new
    work. Before this, health answered 200/``ok`` unconditionally, so a load
    balancer, an orchestrator or a human all read a storage outage as "fine" —
    and ``POST /api/runs`` kept accepting runs whose worker could not persist
    anything. ``store.check_db`` is looked up on the module at call time so the
    probe reflects the live engine (and is patchable in tests).

    Scope: this proves the database ANSWERS. Schema revision and data-root
    writability are added by :func:`readyz` on top, so a deployment whose only
    probe is the container healthcheck keeps its current semantics.
    """
    if not await store.check_db():
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
        return {"status": "storage_unavailable"}
    return {"status": "ok"}


@app.get("/healthz")
async def healthz(response: Response) -> dict[str, str]:
    """Liveness probe, now coupled to storage connectivity (F19).

    The path is unchanged on purpose: the container healthcheck and Caddy
    already probe it, so an existing deployment picks the signal up instead of
    having to be reconfigured to notice a dead store.
    """
    return await _storage_probe(response)


@app.get("/readyz")
async def readyz(response: Response) -> dict[str, object]:
    """Readiness probe: connectivity **and** the schema/data root (F19).

    Distinct from ``/healthz`` because the remedies differ. Connectivity is
    infrastructure (retry); an unready schema means "this build must not run
    against this database until it is migrated", which an operator has to act on
    — and which the process itself now refuses to start with (see ``lifespan``).
    """
    readiness = await storage_readiness()
    if not readiness.ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return readiness.as_body()
