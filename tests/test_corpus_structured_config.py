"""Synthetic configuration and real-wire mock-transport checks; no live credentials or I/O."""

from __future__ import annotations

import json
import logging
import socket
import traceback
from pathlib import Path

import httpx
import pytest

from plugins.corpus.claims import LlmCallError, LlmResponse
from plugins.corpus.structured.adapter import ExtractionAdapter
from plugins.corpus.structured.config import (
    CONFIG_KEYS,
    ExtractionConfig,
    ExtractionConfigError,
    RequestOptions,
    bind_roles,
    load_extraction_config,
)

KEY = "sk-synthetic-extraction-not-real"
MAIN_KEY = "sk-synthetic-main-not-real"


def config_env(**changes):
    values = dict(
        zip(
            CONFIG_KEYS,
            (
                "openai_compat",
                "synthetic-extract-a",
                "https://extract.invalid/v1",
                KEY,
            ),
            strict=True,
        )
    )
    values.update(changes)
    return values


@pytest.fixture(autouse=True)
def block_external_io_and_real_env(monkeypatch):
    def denied(*args, **kwargs):
        raise AssertionError("real model/network/database access forbidden")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    original_open = Path.open
    real_env = Path(__file__).resolve().parents[1] / ".env"

    def guarded_open(path, *args, **kwargs):
        assert path.resolve() != real_env, "real .env must not be read"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", guarded_open)
    for key in CONFIG_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setenv("OPENAI_API_KEY", MAIN_KEY)
    monkeypatch.setenv("OPENAI_MODEL", "main-only")
    monkeypatch.setenv("OPENAI_BASE_URL", "https://main.invalid/v1")
    monkeypatch.setenv("OPENAI_CUSTOM_HEADERS", f"X-Main-Secret: {MAIN_KEY}")
    monkeypatch.setenv("OPENAI_PROJECT_ID", "main-project")
    monkeypatch.setenv("HTTP_PROXY", "http://invalid-proxy.invalid:1")


class RecordingWire:
    def __init__(self, *, data=None, status=200, exception=None):
        self.requests = []
        self.intents = []
        self.data = (
            data
            if data is not None
            else {
                "model": "synthetic-served-a",
                "choices": [
                    {
                        "message": {"content": "[]"},
                        "finish_reason": "stop",
                    }
                ],
                "usage": {"prompt_tokens": 8, "completion_tokens": 2, "total_tokens": 10},
            }
        )
        self.status = status
        self.exception = exception

    def authorize(self, intent):
        self.intents.append(intent)
        return f"synthetic-attempt-{len(self.intents)}"

    def handle(self, request):
        self.requests.append(request)
        if self.exception:
            raise self.exception
        return httpx.Response(self.status, json=self.data)

    def adapter(self, config=None, role_index=0):
        config = config if config is not None else load_extraction_config(environ=config_env())
        return ExtractionAdapter(
            bind_roles(config)[role_index], self.authorize, lambda: httpx.MockTransport(self.handle)
        )


@pytest.mark.parametrize("missing", CONFIG_KEYS)
def test_no_main_fallback_for_each_missing_dedicated_value(missing):
    values = config_env(**{missing: ""})
    values.update(
        OPENAI_API_KEY=MAIN_KEY, OPENAI_MODEL="main", OPENAI_BASE_URL="https://main.invalid"
    )
    config = load_extraction_config(environ=values)
    assert not config.configured
    assert config.error_codes == ("CS_CONFIG_MISSING",)
    assert config.missing_fields == (missing,)
    wire = RecordingWire()
    with pytest.raises(ExtractionConfigError):
        wire.adapter(config)("synthetic prompt")
    assert not wire.requests and not wire.intents


def test_unconfigured_loader_is_lazy_and_does_not_find_dotenv():
    assert not load_extraction_config().configured
    assert not load_extraction_config(environ={}).configured
    # Binding without executing is allowed for deterministic/query planning.
    assert len(bind_roles(load_extraction_config(environ={}))) == 3


@pytest.mark.parametrize(
    "field,value",
    [
        ("PROVIDER", "unknown-provider"),
        ("MODEL", "${OPENAI_MODEL}"),
        ("API_KEY", "${OPENAI_API_KEY}"),
        ("BASE_URL", "https://u:secret@extract.invalid/v1"),
        ("BASE_URL", "https://extract.invalid/v1?api_key=secret"),
        ("BASE_URL", "https://extract.invalid/v1#secret"),
        ("BASE_URL", f"https://extract.invalid/{KEY}"),
        ("BASE_URL", "https://extract.invalid:bad/v1"),
        ("BASE_URL", "file:///tmp/model"),
        ("BASE_URL", "https://extract.invalid/\nsecret"),
    ],
)
def test_invalid_config_is_value_free_and_non_callable(field, value):
    config = load_extraction_config(environ=config_env(**{f"STRUCTURED_EXTRACTION_{field}": value}))
    assert not config.configured
    assert value not in config.model_dump_json()
    with pytest.raises(ExtractionConfigError) as error:
        config.require_profile()
    assert value not in str(error.value)


def test_explicit_dotenv_is_literal_non_mutating_and_empty_env_overrides(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("\n".join(f"{key}={value}" for key, value in config_env().items()))
    config = load_extraction_config(environ={}, dotenv_path=path)
    assert config.require_profile().model == "synthetic-extract-a"
    assert not load_extraction_config().configured
    assert not load_extraction_config(environ={CONFIG_KEYS[1]: ""}, dotenv_path=path).configured
    path.write_text(path.read_text().replace("synthetic-extract-a", "${OPENAI_MODEL}"))
    assert load_extraction_config(environ={}, dotenv_path=path).reason == "interpolation_forbidden"


def test_credential_not_serialized_and_public_snapshot_cannot_restore_authority():
    config = load_extraction_config(environ=config_env())
    for value in (str(config), repr(config), config.model_dump_json(), repr(bind_roles(config))):
        assert KEY not in value
    restored = ExtractionConfig.model_validate_json(config.model_dump_json())
    assert not restored.configured
    with pytest.raises(ExtractionConfigError, match="credentials_not_restored"):
        restored.require_profile()


def test_three_roles_share_model_but_not_role_identity():
    config = load_extraction_config(environ=config_env())
    bindings = bind_roles(config)
    assert len({binding.config.require_profile().fingerprint for binding in bindings}) == 1
    assert len({binding.fingerprint for binding in bindings}) == 3
    wire = RecordingWire()
    for index in range(3):
        result = wire.adapter(config, index)("synthetic prompt")
        assert isinstance(result, LlmResponse)
    assert [intent.role for intent in wire.intents] == [
        "claims",
        "material_items",
        "material_relations",
    ]
    for request in wire.requests:
        assert str(request.url) == "https://extract.invalid/v1/chat/completions"
        assert request.headers["authorization"] == f"Bearer {KEY}"
        assert "x-main-secret" not in request.headers
        assert "openai-project" not in request.headers
        body = json.loads(request.content)
        assert body["model"] == "synthetic-extract-a"
        assert body["max_tokens"] == 4096
        assert "tools" not in body and "thinking" not in body and "temperature" not in body
    assert result.diagnostics["response_model"] == "synthetic-served-a"
    assert result.diagnostics["usage"]["prompt_tokens"] == 8
    assert result.diagnostics["cost"] is None


def test_existing_role_binding_does_not_drift_when_new_protocol_defaults_change(monkeypatch):
    from plugins.corpus.structured.config import PROTOCOLS

    binding = bind_roles(load_extraction_config(environ=config_env()))[0]
    identity = binding.fingerprint
    monkeypatch.setitem(PROTOCOLS, "claims", "future-protocol")
    assert binding.protocol == "claims-json-v2"
    assert binding.fingerprint == identity


def test_inflight_configuration_does_not_drift_with_environment(monkeypatch):
    for key, value in config_env().items():
        monkeypatch.setenv(key, value)
    config = load_extraction_config()
    wire = RecordingWire()
    adapter = wire.adapter(config)
    adapter("first")
    for key in CONFIG_KEYS:
        monkeypatch.setenv(key, "changed-after-freeze")
    monkeypatch.setenv("OPENAI_MODEL", "also-changed")
    adapter("second")
    assert all(
        json.loads(request.content)["model"] == "synthetic-extract-a" for request in wire.requests
    )
    assert all(request.headers["authorization"] == f"Bearer {KEY}" for request in wire.requests)
    assert wire.intents[0].profile_sha256 == wire.intents[1].profile_sha256


def test_explicit_multi_model_overrides_change_actual_endpoint_credentials_and_identity():
    a = load_extraction_config(environ=config_env())
    b = load_extraction_config(
        environ=config_env(
            STRUCTURED_EXTRACTION_MODEL="synthetic-extract-b",
            STRUCTURED_EXTRACTION_BASE_URL="https://second.invalid/api",
            STRUCTURED_EXTRACTION_API_KEY="sk-synthetic-second-not-real",
        ),
        options=RequestOptions(max_output_tokens=123, token_parameter="max_completion_tokens"),
    )
    bindings = bind_roles(a, overrides={"material_items": b})
    wire = RecordingWire()
    for binding in bindings:
        ExtractionAdapter(binding, wire.authorize, lambda: httpx.MockTransport(wire.handle))(
            "input"
        )
    assert wire.requests[1].url.host == "second.invalid"
    assert wire.requests[1].headers["authorization"] == "Bearer sk-synthetic-second-not-real"
    body = json.loads(wire.requests[1].content)
    assert body["model"] == "synthetic-extract-b" and body["max_completion_tokens"] == 123
    assert "max_tokens" not in body
    assert wire.intents[0].profile_sha256 != wire.intents[1].profile_sha256
    assert len(wire.requests) == len(wire.intents) == 3


def test_authorization_required_before_client_or_transport_construction():
    binding = bind_roles(load_extraction_config(environ=config_env()))[0]

    def denied_transport():
        pytest.fail("authorization must precede transport construction")

    with pytest.raises(ValueError, match="authorizer required"):
        ExtractionAdapter(binding, transport_factory=denied_transport)("input")
    with pytest.raises(ValueError, match="invalid attempt"):
        ExtractionAdapter(binding, lambda intent: "", denied_transport)("input")


@pytest.mark.parametrize("status", [301, 307, 400, 401, 429, 500, 503])
def test_no_retries_redirects_or_compatibility_resend(status, caplog):
    caplog.set_level(logging.DEBUG)
    wire = RecordingWire(status=status, data={"error": f"thinking unsupported {KEY}"})
    with pytest.raises(LlmCallError) as error:
        wire.adapter()("input")
    assert len(wire.requests) == len(wire.intents) == 1
    assert error.value.diagnostics["attempts"] == 1
    assert error.value.diagnostics["usage"] is None
    assert error.value.diagnostics["cost"] is None
    assert KEY not in str(error.value) + repr(error.value.diagnostics) + caplog.text
    assert error.value.__context__ is None


def test_transport_failure_is_unknown_and_does_not_leak_exception_or_retry():
    wire = RecordingWire(exception=httpx.ReadTimeout(f"sensitive failure {KEY}"))
    with pytest.raises(LlmCallError) as error:
        wire.adapter()("input")
    assert len(wire.requests) == len(wire.intents) == 1
    assert error.value.diagnostics["execution_status"] == "outcome_unknown"
    assert error.value.diagnostics["error_code"] == "CS_OUTCOME_UNKNOWN"
    assert KEY not in "".join(traceback.format_exception(error.value))
    assert error.value.__context__ is None


def test_usage_and_response_model_can_remain_unknown():
    wire = RecordingWire(
        data={"choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}]}
    )
    result = wire.adapter()("input")
    assert result.diagnostics["response_model"] is None
    assert result.diagnostics["usage"] is None
    assert result.diagnostics["prompt_tokens"] is None
    assert result.diagnostics["completion_tokens"] is None
    assert result.diagnostics["cost"] is None


def test_invalid_usage_fields_are_unknown_not_zero_or_inferred():
    wire = RecordingWire(
        data={
            "choices": [{"message": {"content": "[]"}, "finish_reason": "stop"}],
            "model": KEY,
            "usage": {"prompt_tokens": -1, "completion_tokens": True, "total_tokens": "12"},
        }
    )
    result = wire.adapter()("input")
    assert result.diagnostics["response_model"] is None
    assert all(value is None for value in result.diagnostics["usage"].values())
    assert KEY not in repr(result.diagnostics)


def test_response_echoing_credentials_is_rejected_without_content_in_error():
    wire = RecordingWire(data={"choices": [{"message": {"content": KEY}, "finish_reason": "stop"}]})
    with pytest.raises(LlmCallError) as error:
        wire.adapter()("input")
    assert KEY not in repr(error.value.diagnostics) + str(error.value)


def test_wire_options_participate_in_frozen_identity():
    a = load_extraction_config(environ=config_env()).require_profile()
    b = load_extraction_config(
        environ=config_env(), options=RequestOptions(max_output_tokens=10)
    ).require_profile()
    assert a.fingerprint != b.fingerprint
    with pytest.raises(ValueError):
        a.model = "mutated"


def test_authorizer_failure_has_no_secret_exception_context_or_transport():
    def denied(intent):
        raise RuntimeError(KEY)

    binding = bind_roles(load_extraction_config(environ=config_env()))[0]
    with pytest.raises(ValueError) as error:
        ExtractionAdapter(binding, denied)("input")
    assert KEY not in "".join(traceback.format_exception(error.value))
    assert error.value.__context__ is None


def test_authorizer_preserves_only_bounded_ledger_rejection():
    def denied(_intent):
        raise LlmCallError(
            {
                "execution_status": "blocked",
                "error_code": "CS_BUDGET_EXHAUSTED",
                "error_type": KEY,
            }
        )

    binding = bind_roles(load_extraction_config(environ=config_env()))[0]
    with pytest.raises(LlmCallError) as error:
        ExtractionAdapter(binding, denied)("input")
    assert error.value.diagnostics == {
        "execution_status": "blocked",
        "error_code": "CS_BUDGET_EXHAUSTED",
    }
    assert KEY not in "".join(traceback.format_exception(error.value))
    assert error.value.__context__ is None


def test_transport_setup_failure_does_not_claim_an_actual_request():
    def broken_factory():
        raise RuntimeError(KEY)

    wire = RecordingWire()
    binding = bind_roles(load_extraction_config(environ=config_env()))[0]
    with pytest.raises(LlmCallError) as error:
        ExtractionAdapter(binding, wire.authorize, broken_factory)("input")
    assert len(wire.intents) == 1
    assert error.value.diagnostics["attempts"] == 0
    assert error.value.diagnostics["cost"] is None
    assert error.value.diagnostics["error_type"] == "TransportSetupError"


def test_unexpected_send_error_is_unknown_not_known_failed():
    wire = RecordingWire(exception=RuntimeError(KEY))
    with pytest.raises(LlmCallError) as error:
        wire.adapter()("input")
    assert error.value.diagnostics["execution_status"] == "outcome_unknown"
    assert error.value.diagnostics["attempts"] == 1


def test_default_transport_explicitly_disables_retries_and_environment(monkeypatch):
    transport_options = []
    wire = RecordingWire()

    def mock_transport(**kwargs):
        transport_options.append(kwargs)
        return httpx.MockTransport(wire.handle)

    monkeypatch.setattr(httpx, "HTTPTransport", mock_transport)
    binding = bind_roles(load_extraction_config(environ=config_env()))[0]
    ExtractionAdapter(binding, wire.authorize)("input")
    assert transport_options == [{"retries": 0, "trust_env": False}]
    assert len(wire.requests) == 1


def test_unknown_finish_reason_is_not_silently_successful():
    wire = RecordingWire(data={"choices": [{"message": {"content": "[]"}}]})
    result = wire.adapter()("input")
    assert result.diagnostics["finish_reason"] == "unknown"


def test_real_claims_and_material_consumers_accept_adapter_without_default_client(tmp_path):
    from plugins.corpus.evidence_pipeline import build_evidence_run
    from plugins.corpus.material_semantics import extract_material_understanding

    path = tmp_path / "synthetic.md"
    path.write_text("# 合成材料\n\n预计2027年营业收入达到100亿元，仅在并购完成时成立。\n")
    wire = RecordingWire()
    claims = build_evidence_run(
        path, llm=wire.adapter(), model="synthetic-extract-a", max_prose_calls=1
    )
    assert len(wire.requests) == 1
    packet = next(run for run in claims.packet_runs if run.method == "llm")
    assert packet.diagnostics["request_model"] == "synthetic-extract-a"
    assert packet.diagnostics["role"] == "claims"

    items_wire = RecordingWire(
        data={
            "choices": [
                {
                    "message": {"content": ""},
                    "finish_reason": "stop",
                }
            ]
        }
    )
    result = extract_material_understanding(
        claims,
        llm=items_wire.adapter(role_index=1),
        max_calls=1,
        staged_jsonl=True,
        extract_relations=False,
    )
    assert len(items_wire.requests) == 1
    assert not result.understanding.relations
    assert items_wire.intents[0].protocol == "material-atomic-jsonl-v5"
