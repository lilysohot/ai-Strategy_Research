"""One-shot Chat Completions adapter for an explicitly frozen role/model binding.

No main-agent client, SDK environment defaults, tools, retries, redirects or
provider fallback. The mandatory authorizer is a seam for issue 05's durable
attempt reservation, not a replacement ledger. Without it there is no I/O.
"""

from __future__ import annotations

import re
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import httpx

from plugins.corpus.claims import LlmCallError, LlmResponse
from plugins.corpus.structured.config import (
    ExtractionConfigError,
    RoleBinding,
    canonical_hash,
    validate_endpoint,
)


@dataclass(frozen=True)
class RequestIntent:
    """Credential-free request identity passed to the attempt authorizer before I/O."""

    role: str
    protocol: str
    provider: str
    request_model: str
    profile_sha256: str
    role_profile_sha256: str
    request_sha256: str


AuthorizeAttempt = Callable[[RequestIntent], str]
TransportFactory = Callable[[], httpx.BaseTransport]

_AUTHORIZATION_ERROR_CODES = {
    "CS_BUDGET_EXHAUSTED",
    "CS_CONFIG_MISSING",
    "CS_DEPENDENCY_NOT_READY",
    "CS_INPUT_INVALID",
    "CS_OUTCOME_UNKNOWN",
}
_AUTHORIZATION_STATUSES = {"blocked", "cancelled", "deferred", "failed", "outcome_unknown"}


def _token_count(value: object) -> int | None:
    return value if type(value) is int and value >= 0 else None


def _safe_response_model(value: object, secret: str) -> str | None:
    if (
        isinstance(value, str)
        and secret not in value
        and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", value)
    ):
        return value
    return None


@dataclass(frozen=True)
class ExtractionAdapter:
    """Execute one authorized Chat Completions request without retries or env fallback."""

    binding: RoleBinding
    authorize: AuthorizeAttempt | None = field(default=None, repr=False)
    transport_factory: TransportFactory | None = field(default=None, repr=False)

    def __call__(self, prompt: str) -> LlmResponse:
        """Authorize once, send once, retain unknown usage/model, and never auto-retry."""
        profile = self.binding.config.require_profile()
        credential = self.binding.config.credential
        if credential is None:
            raise ExtractionConfigError("credentials_not_restored")
        secret = credential.get_secret_value()
        if (
            profile.provider != "openai_compat"
            or not secret
            or not validate_endpoint(profile.base_url, secret)
        ):
            raise ExtractionConfigError("invalid_dedicated_config")
        if not isinstance(prompt, str) or not prompt.strip():
            raise ValueError("CS_INPUT_INVALID: empty extraction prompt")
        body: dict[str, Any] = {
            "model": profile.model,
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            profile.options.token_parameter: profile.options.max_output_tokens,
        }
        intent = RequestIntent(
            role=self.binding.role,
            protocol=self.binding.protocol,
            provider=profile.provider,
            request_model=profile.model,
            profile_sha256=profile.fingerprint,
            role_profile_sha256=self.binding.fingerprint,
            request_sha256=canonical_hash(
                {
                    "profile": profile.fingerprint,
                    "role_profile": self.binding.fingerprint,
                    "body": body,
                }
            ),
        )
        if self.authorize is None:
            raise ValueError("CS_BUDGET_EXHAUSTED: explicit attempt authorizer required")
        attempt_id: str | None = None
        authorization_error: dict[str, str] | None = None
        try:
            attempt_id = self.authorize(intent)
        except LlmCallError as exc:
            status = exc.diagnostics.get("execution_status")
            error_code = exc.diagnostics.get("error_code")
            if status in _AUTHORIZATION_STATUSES and error_code in _AUTHORIZATION_ERROR_CODES:
                authorization_error = {
                    "execution_status": status,
                    "error_code": error_code,
                }
        except Exception:
            pass
        if authorization_error is not None:
            raise LlmCallError(authorization_error)
        if (
            not isinstance(attempt_id, str)
            or secret in attempt_id
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,199}", attempt_id)
        ):
            raise ValueError("CS_BUDGET_EXHAUSTED: invalid attempt authorization")

        diagnostics: dict[str, Any] = {
            "adapter_version": profile.adapter_version,
            "role": intent.role,
            "protocol": intent.protocol,
            "provider": intent.provider,
            "model": intent.request_model,
            "request_model": intent.request_model,
            "response_model": None,
            "profile_sha256": intent.profile_sha256,
            "role_profile_sha256": intent.role_profile_sha256,
            "request_sha256": intent.request_sha256,
            "attempt_id": attempt_id,
            "attempts": 0,
            "usage": None,
            "cost": None,
            "prompt_tokens": None,
            "completion_tokens": None,
            "reasoning_tokens": None,
        }
        started = time.monotonic()
        failed = False
        content = ""
        phase = "prepare"
        try:
            transport = (
                self.transport_factory()
                if self.transport_factory is not None
                else httpx.HTTPTransport(retries=0, trust_env=False)
            )
            with httpx.Client(
                transport=transport,
                timeout=profile.options.timeout_seconds,
                trust_env=False,
                follow_redirects=False,
            ) as client:
                phase = "send"
                diagnostics["attempts"] = 1
                response = client.post(
                    profile.base_url + "/chat/completions",
                    headers={"Authorization": f"Bearer {secret}"},
                    json=body,
                )
                phase = "parse"
            diagnostics["http_status"] = response.status_code
            if not 200 <= response.status_code < 300:
                diagnostics.update(error_type="HttpResponseError", execution_status="failed")
                failed = True
            else:
                data = response.json()
                if not isinstance(data, dict):
                    raise ValueError("invalid response envelope")
                diagnostics["response_model"] = _safe_response_model(data.get("model"), secret)
                usage = data.get("usage")
                if isinstance(usage, dict):
                    details = usage.get("completion_tokens_details")
                    counts = {
                        "prompt_tokens": _token_count(usage.get("prompt_tokens")),
                        "completion_tokens": _token_count(usage.get("completion_tokens")),
                        "total_tokens": _token_count(usage.get("total_tokens")),
                        "reasoning_tokens": _token_count(details.get("reasoning_tokens"))
                        if isinstance(details, dict)
                        else None,
                    }
                    diagnostics.update(counts)
                    diagnostics["usage"] = counts
                choices = data.get("choices")
                if not isinstance(choices, list) or len(choices) != 1:
                    raise ValueError("invalid choices")
                choice = choices[0]
                content = choice["message"].get("content")
                if not isinstance(content, str) or secret in content:
                    raise ValueError("invalid or credential-bearing content")
                finish = choice.get("finish_reason")
                diagnostics["finish_reason"] = (
                    finish
                    if finish
                    in {
                        "stop",
                        "length",
                        "content_filter",
                        "tool_calls",
                        "function_call",
                    }
                    else "unknown"
                )
                diagnostics["execution_status"] = "succeeded"
                diagnostics["content_chars"] = len(content)
        except Exception:
            # Never propagate provider text, headers, URLs, exception names or chained errors.
            if phase == "send":
                diagnostics.update(
                    error_type="TransportOutcomeUnknown",
                    error_code="CS_OUTCOME_UNKNOWN",
                    execution_status="outcome_unknown",
                )
            elif phase == "prepare":
                diagnostics.update(error_type="TransportSetupError", execution_status="failed")
            else:
                diagnostics.update(
                    error_type="InvalidResponse",
                    protocol_status="invalid",
                    execution_status="failed",
                )
            failed = True
        diagnostics["duration_ms"] = round((time.monotonic() - started) * 1000)
        if failed:
            # Raised outside except so no credential-bearing exception context survives.
            raise LlmCallError(diagnostics)
        return LlmResponse(content, diagnostics)
