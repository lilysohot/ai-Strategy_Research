"""Read-only quote capability probe. Never print credentials or request headers."""
import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
from dotenv import load_dotenv

from plugins.market.factory import get_api_key, get_base_url

load_dotenv()
if not get_api_key():
    print("market credentials unavailable")
    raise SystemExit(0)
try:
    response = httpx.get(get_base_url() + "/api/a-share/prices/snapshot", params={"thscodes": "601138.SH"},
                         headers={"X-api-key": get_api_key()}, timeout=15)
    print("http_status", response.status_code)
    data = json.loads(response.content, parse_float=Decimal)
    print("top_level_keys", list(data) if isinstance(data, dict) else type(data).__name__)
    envelope = data.get("data", {})
    print("data_keys", list(envelope) if isinstance(envelope, dict) else type(envelope).__name__)
    if isinstance(envelope, dict):
        print("provider_timestamp", envelope.get("timestamp"))
        print("local_received_at", datetime.now(UTC).isoformat())
        rows = envelope.get("item", [])
        if isinstance(rows, dict):
            rows = [rows]
        for row in rows[:1]:
            print("item_keys", list(row))
            print("quote", {k: str(v) for k, v in row.items() if k in {"thscode", "last_price", "timestamp", "trade_time", "date", "time"}})
except Exception as exc:
    print("probe_failed", type(exc).__name__)
