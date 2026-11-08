"""All authoritative read paths expose typed retry policy without prose matching."""

import importlib
import json

import pytest

from plugins.corpus.preparation import read_pg
from plugins.corpus.read_errors import read_failure


@pytest.mark.parametrize("error,code,retryable,scope", [
    (read_pg.WithdrawnError("revoked"), "withdrawn", False, "document"),
    (read_pg.IntegrityError("hash"), "integrity", False, "request"),
    (read_pg.UnknownHandleError("missing"), "unknown_handle", False, "request"),
    (read_pg.LegacyHandleError("old"), "archive_required", False, "request"),
    (TimeoutError("source_withdrawn in an untrusted diagnostic"), "fetch_failed", True, "request"),
])
def test_recovery_depends_on_exception_type(error, code, retryable, scope):
    assert read_failure(error) == {"code": code, "retryable": retryable, "failure_scope": scope}


@pytest.mark.parametrize("mode", ["single", "batch", "inventory", "document"])
@pytest.mark.parametrize("error", [read_pg.WithdrawnError("revoked"), TimeoutError("temporary")])
async def test_read_modes_preserve_failure_contract(monkeypatch, mode, error):
    fetch = importlib.import_module("plugins.tools.corpus_fetch")
    inventory = importlib.import_module("plugins.tools.corpus_inventory")

    class Service:
        def __getattr__(self, name):
            def fail(*args, **kwargs):
                raise error
            return fail

    monkeypatch.setattr(fetch, "get_service", Service)
    monkeypatch.setattr(inventory, "get_service", Service)
    doc = "cv2:" + "a" * 64
    args = {
        "single": {"locator": "chunk:unit"}, "batch": {"locators": ["chunk:unit"]},
        "document": {"scope": "document"}, "inventory": {"locators": ["chunk:unit"]},
    }[mode]
    tool = inventory.corpus_inventory if mode == "inventory" else fetch.corpus_fetch
    result = json.loads(await tool.func(doc_id=doc, **args))
    assert result["ok"] is False
    assert result["doc_id"] == doc
    assert all(result[k] == v for k, v in read_failure(error).items())
