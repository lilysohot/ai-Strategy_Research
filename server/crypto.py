"""Symmetric encryption for user secrets (T2.3).

User-supplied LLM api_keys are encrypted at rest with Fernet (AES-128-CBC +
HMAC-SHA256) using a key derived from ``ServerConfig.master_key``. The key is
never persisted and the plaintext api_key is never returned by the store layer —
routes get a masked value, and only the internal injection chain (T2.5) is
allowed to decrypt.

Why Fernet: it is authenticated (tamper-evident) and nonce-safe by construction,
so we cannot accidentally reuse a nonce or store an unauthenticated blob. The
library raises ``InvalidToken`` on any corruption or wrong key, which is exactly
the failure signal we want when decrypting.
"""

from __future__ import annotations

from cryptography.fernet import Fernet, InvalidToken

from server.config import get_config


def _fernet() -> Fernet:
    """Build a Fernet instance from the derived master key."""
    return Fernet(get_config().fernet_key)


def encrypt_api_key(plaintext: str) -> bytes:
    """Encrypt an api_key; returns raw ciphertext bytes for the DB column.

    ``LargeBinary`` columns store the bytes directly. We deliberately do NOT
    base64-encode here — Fernet tokens are already url-safe bytes and the column
    is binary, so an extra encoding layer would only add noise.
    """
    return _fernet().encrypt(plaintext.encode("utf-8"))


def decrypt_api_key(ciphertext: bytes) -> str:
    """Decrypt an api_key. Raises ``InvalidToken`` on tamper / wrong key.

    Callers must treat the result as a secret: never log it, never return it in
    a response. This is the single function the injection chain is allowed to use.
    """
    if not ciphertext:
        raise InvalidToken("empty ciphertext")
    return _fernet().decrypt(bytes(ciphertext)).decode("utf-8")


def mask_api_key(api_key: str, *, visible: int = 4) -> str:
    """Return a display-safe mask of an api_key.

    ``sk-abcdefghijklmnop`` → ``sk-…mnop``. The prefix up to the first separator
    is kept so users can recognise which provider key they stored, and only the
    final ``visible`` characters are shown. Short keys collapse to a fixed mask.
    """
    if not api_key:
        return "····"
    sep = api_key.find("-")
    prefix = api_key[: sep + 1] if sep != -1 else ""
    tail = api_key[sep + 1 :] if sep != -1 else api_key
    if len(tail) <= visible:
        return f"{prefix}····"
    return f"{prefix}···{tail[-visible:]}"
