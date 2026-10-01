#!/bin/sh
# Web API container entrypoint.
#
# The migration is an EXPLICIT step here, not something the application does on
# import: `server.app` only ever runs `create_all` (which cannot upgrade an
# existing table), so a container started without this step would serve an old
# schema and fail much later with an opaque column error — the failure mode F19
# is about. `set -e` makes a failed migration abort the container instead of
# starting a half-migrated API.
#
# Ordering: migrate, then serve. `alembic upgrade head` is idempotent, so a
# restart against an already-current database is a no-op. Roll the image back by
# running the previous image's entrypoint against the same database — this
# script never downgrades, and the readiness gate refuses to serve a schema that
# is AHEAD of the build.
set -eu

cd /app

echo "[entrypoint] alembic upgrade head (database: ${SERVER_DATABASE_URL:-<unset>})"
alembic -c server/alembic.ini upgrade head

echo "[entrypoint] starting uvicorn"
exec uvicorn server.app:app --host 0.0.0.0 --port 8000
