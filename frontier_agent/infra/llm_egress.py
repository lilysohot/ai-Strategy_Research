"""Fail before sending when a test run is not pointed at a local endpoint.

A worker subprocess resolves its provider from the *server's* configuration, not
from whatever a test's own process monkeypatched: on 2026-11-17 two integration
tests that believed they were talking to ``MockLLMServer`` instead reached the
production gateway and spent 18,878 input tokens. "Not counted against the
experiment quota" is an accounting answer, not an isolation one.

Set ``FRONTIER_LLM_LOCAL_ONLY=1`` to make that impossible: any client built for a
non-loopback host raises here, before a single byte leaves the process. The test
suite turns it on globally (``tests/conftest.py``), so an integration test that
forgets to redirect the worker fails loudly instead of spending money.
"""

from __future__ import annotations

import os
from urllib.parse import urlparse

#: Opt-in flag. Absent (production) means no restriction at all.
LOCAL_ONLY_ENV = "FRONTIER_LLM_LOCAL_ONLY"

_LOOPBACK_HOSTS = frozenset({"127.0.0.1", "localhost", "::1", "0.0.0.0"})


def local_only() -> bool:
    return os.environ.get(LOCAL_ONLY_ENV, "").strip().lower() in {"1", "true", "yes", "on"}


def assert_local_endpoint(base_url: str, *, model: str = "") -> None:
    """Raise when ``base_url`` is not loopback while local-only mode is on.

    An empty ``base_url`` is allowed through: the SDK then falls back to
    ``OPENAI_API_KEY``/``OPENAI_BASE_URL``, and a caller that supplied nothing has
    no host for us to judge. Tests set both explicitly, so the check still bites
    where it matters.
    """
    if not local_only():
        return
    target = (base_url or os.environ.get("OPENAI_BASE_URL", "")).strip()
    if not target:
        return
    host = (urlparse(target).hostname or "").lower()
    if host in _LOOPBACK_HOSTS:
        return
    raise RuntimeError(
        f"{LOCAL_ONLY_ENV}=1 refuses a non-loopback LLM endpoint "
        f"(model={model or 'unset'}, host={host or 'unparsed'}); "
        "point the run at the local mock instead of a real provider"
    )
