from datetime import UTC, datetime, timedelta
from decimal import Decimal

import httpx
import pytest

from server.monitor_source import HttpPriceSource
from server.watch_eval import quote_rejection


async def test_http_source_preserves_decimal_and_requires_verified_vendor_time():
    now = datetime.now(UTC)
    ts = int(now.timestamp() * 1000)
    raw = f'{{"data":{{"timestamp":{ts},"item":[{{"thscode":"601138.SH","last_price":48.820000000001}}]}}}}'
    requests = []

    def handle(request):
        requests.append(request)
        return httpx.Response(200, text=raw)

    async with httpx.AsyncClient(
        transport=httpx.MockTransport(handle), base_url="https://source.test"
    ) as client:
        unknown = await HttpPriceSource(client).fetch("601138.SH", "CN", "CNY", "last")
        assert quote_rejection(unknown, now=now) == "unverified_quote_time"
        obs = await HttpPriceSource(client, timestamp_verified=True).fetch(
            "601138.SH", "CN", "CNY", "last"
        )
        assert obs.price == Decimal("48.820000000001")
        assert not obs.precision_limited
        assert quote_rejection(obs, now=now) is None
        assert quote_rejection(obs, now=now + timedelta(minutes=5)) == "stale_quote"
        assert quote_rejection(obs, now=now - timedelta(minutes=1)) == "future_quote"
        with pytest.raises(ValueError, match="unsupported_instrument"):
            await HttpPriceSource(client).fetch("GC", "US", "USD", "last")
    assert requests[0].url.params["thscodes"] == "601138.SH"


@pytest.mark.parametrize(
    "body",
    [
        '{"data":{"item":[{"thscode":"601138.SH","last_price":48.82}]}}',
        '{"data":{"timestamp":null,"item":[{"thscode":"601138.SH","last_price":48.82}]}}',
    ],
)
async def test_missing_time_never_falls_back_to_local_clock(body):
    async with httpx.AsyncClient(
        transport=httpx.MockTransport(lambda _: httpx.Response(200, text=body)),
        base_url="https://source.test",
    ) as client:
        obs = await HttpPriceSource(client, timestamp_verified=True).fetch(
            "601138.SH", "CN", "CNY", "last"
        )
    assert obs.observed_at_ms is None
    assert quote_rejection(obs, now=datetime.now(UTC)) == "unverified_quote_time"
