"""The browser's Chinese plan form persists with its ASCII retry identity."""

import uuid

import httpx

from server import store
from server.app import app
from server.security import create_access_token


async def test_chinese_plan_form_save_retry_and_primary_link():
    await store.init_db()
    user = await store.create_user(username="plan-form-save", password_hash="unused")
    research = await store.create_session(user_id=user.id)
    headers = {"Authorization": f"Bearer {create_access_token(user.id)}"}
    key = f"plan.create:{uuid.uuid4()}"
    body = {
        "name": "工业富联回调买入",
        "declared": {
            "symbol": {"value": "601138.SH"},
            "market": {"value": "CN"},
            "direction": {"value": "buy"},
            "allocated_capital": {"value": "10000"},
        },
        "allow_incomplete": True,
        "source_kind": "form",
    }
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://plan-form.test"
    ) as client:
        path = f"/api/business/sessions/{research.id}"
        first = await client.post(
            f"{path}/plans", json=body, headers={**headers, "Idempotency-Key": key}
        )
        assert first.status_code == 201, first.text
        repeated = await client.post(
            f"{path}/plans", json=body, headers={**headers, "Idempotency-Key": key}
        )
        assert repeated.status_code == 201, repeated.text
        assert repeated.json()["plan_id"] == first.json()["plan_id"]
        assert repeated.json()["replayed"] is True
        linked = await client.put(
            f"{path}/link",
            json={"account_id": None, "primary_plan_id": first.json()["plan_id"]},
            headers={**headers, "Idempotency-Key": f"{key}:link"},
        )
        assert linked.status_code == 200, linked.text
        listing = (await client.get(f"{path}/plans", headers=headers)).json()["plans"]
        assert len(listing) == 1
        assert listing[0]["name"] == body["name"]
        assert listing[0]["values"]["symbol"] == "601138.SH"
        restored_link = (await client.get(f"{path}/link", headers=headers)).json()
        assert restored_link["primary_plan_id"] == listing[0]["id"]
