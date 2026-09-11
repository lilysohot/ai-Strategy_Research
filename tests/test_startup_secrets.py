"""Startup secret validation (JWT signing key split from the encryption key).

The server signs JWTs with ``SERVER_JWT_SECRET`` and encrypts stored LLM
api_keys with ``SERVER_MASTER_KEY``. Sharing one value means a single leak
gives away both, so a deployment that has not set them must fail to start
rather than silently run on the placeholder shipped in the repository.

Run with::
    uv run pytest tests/test_startup_secrets.py -q
"""

from __future__ import annotations

import pytest

from server.config import INSECURE_DEFAULT_MASTER_KEY, get_config
from server.security import _secret, check_startup_secrets


@pytest.fixture
def cfg():
    """The process-wide config, restored after each test."""
    config = get_config()
    saved = (config.master_key, config.jwt_secret, config.debug)
    yield config
    config.master_key, config.jwt_secret, config.debug = saved


def test_default_master_key_and_no_jwt_secret_refuses_to_start(cfg):
    cfg.master_key = INSECURE_DEFAULT_MASTER_KEY
    cfg.jwt_secret = ""
    cfg.debug = False

    with pytest.raises(RuntimeError) as exc:
        check_startup_secrets()

    message = str(exc.value)
    assert "SERVER_MASTER_KEY" in message
    assert "SERVER_JWT_SECRET" in message


def test_jwt_secret_is_required_even_with_a_real_master_key(cfg):
    """A real master_key alone is not enough — JWTs must not be signed with it."""
    cfg.master_key = "a-real-random-master-key"
    cfg.jwt_secret = ""
    cfg.debug = False

    with pytest.raises(RuntimeError) as exc:
        check_startup_secrets()

    assert "SERVER_JWT_SECRET" in str(exc.value)


def test_both_secrets_set_passes(cfg):
    cfg.master_key = "a-real-random-master-key"
    cfg.jwt_secret = "a-real-random-jwt-secret"
    cfg.debug = False

    check_startup_secrets()  # must not raise


def test_debug_downgrades_to_a_warning(cfg, caplog):
    cfg.master_key = INSECURE_DEFAULT_MASTER_KEY
    cfg.jwt_secret = ""
    cfg.debug = True

    with caplog.at_level("WARNING"):
        check_startup_secrets()  # must not raise

    assert any("SERVER_MASTER_KEY" in r.getMessage() for r in caplog.records)


def test_jwt_secret_wins_over_master_key(cfg):
    cfg.master_key = "encryption-key"
    cfg.jwt_secret = "signing-key"

    assert _secret() == "signing-key"


def test_jwt_falls_back_to_master_key_when_unset(cfg):
    """Pre-split deployments keep working instead of invalidating every token."""
    cfg.master_key = "encryption-key"
    cfg.jwt_secret = ""

    assert _secret() == "encryption-key"
