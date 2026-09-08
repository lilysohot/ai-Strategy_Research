"""T2.3 — user_llm_configs storage layer.

Maps to the T2.3 checklist:
    * Fernet encrypt/decrypt round-trip (no plaintext at rest)
    * API key is ALWAYS masked in responses / serialized views
    * CRUD: create / list / get / update / delete / set_default
    * exactly one default per user (mutual exclusion on promote)
    * ownership enforced: a user cannot read/modify another's config (IDOR guard)
    * deleting the only default is refused; deleting a default with others
      promotes the most recent remaining one
    * no plaintext api_key anywhere: not in DB column, not in list response,
      not in logs (we assert the ciphertext column holds bytes, not the key)

Run with::
    uv run pytest tests/test_llm_config_t23.py -q
"""

from __future__ import annotations

import uuid

import pytest
from cryptography.fernet import InvalidToken

from server.config import get_config
from server.crypto import decrypt_api_key, encrypt_api_key, mask_api_key
from server.store import (
    ConfigNotFoundError,
    OnlyOneDefaultAllowed,
    create_llm_config,
    create_user,
    delete_llm_config,
    get_decrypted_api_key,
    get_default_llm_config,
    get_llm_config,
    list_llm_configs,
    set_default_llm_config,
    update_llm_config,
)


@pytest.fixture
async def users(tmp_path):
    """Two users + a fresh DB, so configs are isolated per owner."""
    from server.config import get_config
    from server.store import init_db, reset_engine

    db = tmp_path / "test.db"
    cfg = get_config()
    orig_url = cfg.database_url
    orig_key = cfg.master_key
    cfg.database_url = f"sqlite+aiosqlite:///{db}"
    cfg.master_key = f"test-master-{uuid.uuid4().hex}"
    await reset_engine()
    await init_db()

    alice = await create_user(username="alice", password_hash="x")
    bob = await create_user(username="bob", password_hash="x")

    yield alice, bob

    cfg.database_url = orig_url
    cfg.master_key = orig_key
    await reset_engine()


def _spec(**over) -> dict:
    base = dict(
        name="my-glm",
        base_url="https://open.bigmodel.cn/api/paas/v4",
        model="glm-4.5-flash",
        api_key="sk-abcdefghijklmnopqrstuvwxyz123456",
        params={"temperature": 0.3},
    )
    base.update(over)
    return base


# ── crypto round-trip ────────────────────────────────────────────
@pytest.mark.asyncio
async def test_fernet_round_trip():
    plain = "sk-secret-value-12345"
    cipher = encrypt_api_key(plain)
    assert isinstance(cipher, bytes)
    assert plain.encode() not in cipher  # not stored in the clear
    assert decrypt_api_key(cipher) == plain


@pytest.mark.asyncio
async def test_decrypt_wrong_key_fails(users):
    alice, _ = users
    cfg = await create_llm_config(user_id=alice.id, **_spec())
    original = get_config().master_key
    get_config().master_key = "a-different-master-key"
    try:
        # The ciphertext was encrypted under the original key; a key change
        # must make decryption fail rather than leak or silently succeed.
        with pytest.raises(InvalidToken):
            await get_decrypted_api_key(user_id=alice.id, config_id=uuid.UUID(cfg["id"]))
    finally:
        get_config().master_key = original


# ── masking ──────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_mask_keeps_prefix_and_tail_only():
    masked = mask_api_key("sk-abcdefghijklmnop")
    assert "abcdefghijklmnop" not in masked
    assert masked.startswith("sk-")
    assert masked.endswith("mnop")
    assert "···" in masked


@pytest.mark.asyncio
async def test_serialized_view_never_contains_plaintext(users):
    alice, _ = users
    plain = "sk-ABCDEFGHIJKLMNOPQRSTUVWXYZ987654"
    cfg = await create_llm_config(user_id=alice.id, **_spec(api_key=plain))
    assert plain not in cfg
    assert cfg["masked_api_key"] != plain
    assert "api_key" not in cfg  # raw field name must not appear at all
    # Mask keeps the `sk-` prefix and the final 4 chars (`7654`), hiding the
    # middle. The long body must not appear anywhere in the masked value.
    assert cfg["masked_api_key"].startswith("sk-")
    assert "ABCDEFGHIJKLMNOPQRSTUVWXYZ" not in cfg["masked_api_key"]
    assert "7654" in cfg["masked_api_key"]


@pytest.mark.asyncio
async def test_ciphertext_column_is_encrypted_bytes(users):
    from server.store import UserLLMConfig, get_sessionmaker

    alice, _ = users
    plain = "sk-SUPERSECRETKEYVALUE000000000000"
    created = await create_llm_config(user_id=alice.id, **_spec(api_key=plain))
    async with get_sessionmaker()() as s:
        row = await s.get(UserLLMConfig, uuid.UUID(created["id"]))
        assert isinstance(row.api_key_cipher, (bytes, bytearray))
        assert plain.encode() not in bytes(row.api_key_cipher)


# ── CRUD ─────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_create_and_list(users):
    alice, _ = users
    c1 = await create_llm_config(user_id=alice.id, **_spec(name="c1"))
    c2 = await create_llm_config(user_id=alice.id, **_spec(name="c2"))
    listed = await list_llm_configs(user_id=alice.id)
    assert {c["id"] for c in listed} == {c1["id"], c2["id"]}
    assert {c["name"] for c in listed} == {"c1", "c2"}


@pytest.mark.asyncio
async def test_get_not_found_is_404_style(users):
    alice, _ = users
    with pytest.raises(ConfigNotFoundError):
        await get_llm_config(user_id=alice.id, config_id=uuid.uuid4())


@pytest.mark.asyncio
async def test_update_patches_selected_fields(users):
    alice, _ = users
    c = await create_llm_config(user_id=alice.id, **_spec(name="old", model="m1"))
    updated = await update_llm_config(
        user_id=alice.id,
        config_id=uuid.UUID(c["id"]),
        name="new",
        api_key="sk-CHANGEDKEY00000000000000000000",
    )
    assert updated["name"] == "new"
    assert updated["model"] == "m1"  # unchanged
    # new key is masked and different from the old mask
    assert updated["masked_api_key"].endswith("0000")
    assert updated["masked_api_key"] != c["masked_api_key"]


@pytest.mark.asyncio
async def test_delete(users):
    alice, _ = users
    c = await create_llm_config(user_id=alice.id, **_spec())
    await delete_llm_config(user_id=alice.id, config_id=uuid.UUID(c["id"]))
    assert await list_llm_configs(user_id=alice.id) == []


# ── default mutual exclusion ─────────────────────────────────────
@pytest.mark.asyncio
async def test_set_default_promotes_and_demotes_others(users):
    alice, _ = users
    c1 = await create_llm_config(user_id=alice.id, **_spec(name="c1"), is_default=True)
    c2 = await create_llm_config(user_id=alice.id, **_spec(name="c2"))
    assert (await get_llm_config(user_id=alice.id, config_id=uuid.UUID(c1["id"])))["is_default"]
    assert not (await get_llm_config(user_id=alice.id, config_id=uuid.UUID(c2["id"])))["is_default"]

    await set_default_llm_config(user_id=alice.id, config_id=uuid.UUID(c2["id"]))
    assert not (await get_llm_config(user_id=alice.id, config_id=uuid.UUID(c1["id"])))["is_default"]
    assert (await get_llm_config(user_id=alice.id, config_id=uuid.UUID(c2["id"])))["is_default"]


@pytest.mark.asyncio
async def test_only_one_default_at_all_times(users):
    alice, _ = users
    await create_llm_config(user_id=alice.id, **_spec(name="c1"), is_default=True)
    c2 = await create_llm_config(user_id=alice.id, **_spec(name="c2"), is_default=True)
    defaults = [
        c for c in await list_llm_configs(user_id=alice.id) if c["is_default"]
    ]
    assert len(defaults) == 1
    # c2 won the promotion race
    assert defaults[0]["id"] == c2["id"]


@pytest.mark.asyncio
async def test_get_default_returns_promoted(users):
    alice, _ = users
    await create_llm_config(user_id=alice.id, **_spec(name="c1"), is_default=True)
    c2 = await create_llm_config(user_id=alice.id, **_spec(name="c2"))
    await set_default_llm_config(user_id=alice.id, config_id=uuid.UUID(c2["id"]))
    default = await get_default_llm_config(user_id=alice.id)
    assert default is not None and default.name == "c2"


# ── delete-default protection ───────────────────────────────────
@pytest.mark.asyncio
async def test_cannot_delete_only_config(users):
    alice, _ = users
    c = await create_llm_config(user_id=alice.id, **_spec(), is_default=True)
    with pytest.raises(OnlyOneDefaultAllowed):
        await delete_llm_config(user_id=alice.id, config_id=uuid.UUID(c["id"]))


@pytest.mark.asyncio
async def test_deleting_default_promotes_most_recent(users):
    alice, _ = users
    c1 = await create_llm_config(user_id=alice.id, **_spec(name="c1"), is_default=True)
    c2 = await create_llm_config(user_id=alice.id, **_spec(name="c2"))
    # delete the default -> c2 (only remaining) should become default
    await delete_llm_config(user_id=alice.id, config_id=uuid.UUID(c1["id"]))
    remaining = await list_llm_configs(user_id=alice.id)
    assert len(remaining) == 1
    assert remaining[0]["id"] == c2["id"]
    assert remaining[0]["is_default"]


# ── ownership / IDOR guard ──────────────────────────────────────
@pytest.mark.asyncio
async def test_user_cannot_access_another_users_config(users):
    alice, bob = users
    c = await create_llm_config(user_id=alice.id, **_spec())
    # bob must not be able to read alice's config
    with pytest.raises(ConfigNotFoundError):
        await get_llm_config(user_id=bob.id, config_id=uuid.UUID(c["id"]))
    with pytest.raises(ConfigNotFoundError):
        await update_llm_config(
            user_id=bob.id, config_id=uuid.UUID(c["id"]), name="hacked"
        )
    with pytest.raises(ConfigNotFoundError):
        await delete_llm_config(user_id=bob.id, config_id=uuid.UUID(c["id"]))
    # alice's data is intact
    assert (await get_llm_config(user_id=alice.id, config_id=uuid.UUID(c["id"])))["name"] == "my-glm"


@pytest.mark.asyncio
async def test_each_user_has_separate_config_list(users):
    alice, bob = users
    await create_llm_config(user_id=alice.id, **_spec(name="a"))
    await create_llm_config(user_id=bob.id, **_spec(name="b"))
    assert len(await list_llm_configs(user_id=alice.id)) == 1
    assert len(await list_llm_configs(user_id=bob.id)) == 1
    assert (await list_llm_configs(user_id=alice.id))[0]["name"] == "a"
