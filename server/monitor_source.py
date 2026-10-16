"""HTTP acquisition port. Never turn a response-receipt time into a quote time."""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from decimal import Decimal
from typing import Protocol

import httpx

from server.watch_eval import MonitoringObservation


class PriceSource(Protocol):
    async def fetch(
        self, symbol: str, market: str, currency: str, basis: str
    ) -> MonitoringObservation: ...


class HttpPriceSource:
    def __init__(self, client: httpx.AsyncClient, *, timestamp_verified: bool = False) -> None:
        self.client = client
        self.timestamp_verified = timestamp_verified

    async def fetch(
        self, symbol: str, market: str, currency: str, basis: str
    ) -> MonitoringObservation:
        # This endpoint only documents mainland equities. Other adapters can implement
        # the same port later; do not relabel an equity quote as futures/index data.
        if (
            market != "CN"
            or currency != "CNY"
            or basis not in {"last", "last_trade"}
            or not re.fullmatch(r"(?:6\d{5}\.SH|[03]\d{5}\.SZ)", symbol)
        ):
            raise ValueError("unsupported_instrument")
        response = await self.client.get(
            "/api/a-share/prices/snapshot", params={"thscodes": symbol}
        )
        response.raise_for_status()
        if len(response.content) > 1_000_000:
            raise ValueError("quote_payload_too_large")
        envelope = json.loads(response.content, parse_float=Decimal)
        if not isinstance(envelope, dict) or envelope.get("code") not in (None, 0):
            raise ValueError("provider_business_error")
        data = envelope.get("data")
        if not isinstance(data, dict):
            raise ValueError("invalid_quote_payload")
        items = data.get("item", [])
        if isinstance(items, dict):
            items = [items]
        rows = [item for item in items if isinstance(item, dict) and item.get("thscode") == symbol]
        if len(rows) != 1:
            raise ValueError("quote_symbol_missing_or_ambiguous")
        raw = rows[0].get("last_price")
        if isinstance(raw, bool) or not isinstance(raw, (str, int, Decimal)):
            raise ValueError("invalid_quote_price")
        ts = data.get("timestamp")
        # The provider envelope timestamp is accepted only after deployment verification.
        stamp = int(ts) if isinstance(ts, (int, Decimal)) and ts == int(ts) and ts > 0 else None
        return MonitoringObservation(
            thscode=symbol,
            market="CN",
            currency="CNY",
            price=Decimal(raw),
            received_at_ms=int(datetime.now(UTC).timestamp() * 1000),
            observed_at_ms=stamp,
            time_source="vendor" if self.timestamp_verified and stamp else "unknown",
            quote_basis=basis,
            source_ref="fuyao:/api/a-share/prices/snapshot",
        )
