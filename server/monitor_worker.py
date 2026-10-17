"""Run independently: python -m server.monitor_worker [--role all|collector|delivery|scheduler]."""

from __future__ import annotations

import argparse
import asyncio
import logging
import uuid
from collections.abc import Awaitable, Callable

import httpx
from dotenv import load_dotenv
from redis.asyncio import Redis

from plugins.market.factory import get_api_key, get_base_url, is_enabled
from server import monitor_pipeline as pipeline
from server import restore_check
from server.config import get_config
from server.monitor_source import HttpPriceSource
from server.readiness import storage_readiness

logger = logging.getLogger(__name__)


async def loop(role: str, action: Callable[[], Awaitable[object]], interval: float) -> None:
    while True:
        error = None
        try:
            if not restore_check.background_tasks_allowed():
                error = "restore_mode"
            else:
                await action()
        except Exception as exc:
            error = type(exc).__name__
            logger.error("monitor role=%s error=%s", role, error)
        try:
            await pipeline.worker_health(role, error)
        except Exception:
            logger.error("monitor health unavailable role=%s", role)
        await asyncio.sleep(interval)


async def serve(role: str) -> None:
    load_dotenv(override=False)
    cfg = get_config()
    if not cfg.monitor_streams_enabled or not cfg.monitor_enabled:
        raise RuntimeError(
            "Enable SERVER_MONITOR_ENABLED and SERVER_MONITOR_STREAMS_ENABLED explicitly"
        )
    readiness = await storage_readiness()
    if not readiness.ok:
        raise RuntimeError(
            "Database schema/storage not ready; run migrations before starting monitoring"
        )
    redis = Redis.from_url(
        cfg.monitor_redis_url, decode_responses=True, socket_connect_timeout=3, socket_timeout=5
    )
    async with httpx.AsyncClient(
        base_url=get_base_url(),
        headers={"X-api-key": get_api_key()},
        timeout=10,
        follow_redirects=False,
    ) as client:
        source = HttpPriceSource(client, timestamp_verified=cfg.monitor_vendor_time_verified)

        async def collect() -> object:
            if not is_enabled() or not get_api_key():
                raise RuntimeError("market_source_unconfigured")
            return await pipeline.collect_once(source)

        async def deliver() -> None:
            await delivery.relay("quotes")
            await delivery.consume("quotes")
            await delivery.relay("triggers")
            await delivery.consume("triggers")
            await pipeline.prune()

        async def schedule() -> object:
            if not cfg.auto_enabled:
                raise RuntimeError("scheduler_disabled")
            return await pipeline.schedule_received()

        delivery = pipeline.Delivery(redis)
        jobs = {"collector": (collect, 5), "delivery": (deliver, 1), "scheduler": (schedule, 2)}
        try:
            await asyncio.gather(
                *(
                    loop(name, action, interval)
                    for name, (action, interval) in jobs.items()
                    if role in {"all", name}
                )
            )
        finally:
            await redis.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--role", choices=["all", "collector", "delivery", "scheduler"], default="all"
    )
    parser.add_argument(
        "--retry-message",
        type=uuid.UUID,
        help="Retry one quarantined durable message without changing its identity",
    )
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    if args.retry_message:
        recovered = asyncio.run(pipeline.retry_quarantined(args.retry_message))
        print("message requeued" if recovered else "message not found or not quarantined")
    else:
        asyncio.run(serve(args.role))


if __name__ == "__main__":
    main()
