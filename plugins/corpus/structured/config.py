"""Explicit, immutable extraction configuration; never consult main-agent defaults.

Only an explicitly supplied dotenv path is read. Interpolation is disabled, so a
dedicated variable cannot become a hidden alias of OPENAI_*. Process environment
values override file values, including an explicit empty value. Nothing is written
to os.environ. Credentials are frozen in memory and excluded from serialization;
restoring a public profile alone never restores authority to make a request.
"""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Literal
from urllib.parse import unquote, urlsplit

from dotenv import dotenv_values
from pydantic import BaseModel, ConfigDict, Field, SecretStr

CONFIG_KEYS = tuple(
    f"STRUCTURED_EXTRACTION_{suffix}"
    for suffix in (
        "PROVIDER",
        "MODEL",
        "BASE_URL",
        "API_KEY",
    )
)
ADAPTER_VERSION = "structured-chat-http-1"
Role = Literal["claims", "material_items", "material_relations"]
PROTOCOLS: dict[str, str] = {
    "claims": "claims-json-v2",
    "material_items": "material-atomic-jsonl-v4",
    "material_relations": "material-relations-jsonl-v1",
}


def canonical_hash(value: object) -> str:
    """Return the frozen UTF-8 canonical-JSON SHA-256 identity for ``value``."""

    encoded = json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(encoded.encode("utf-8")).hexdigest()


class ExtractionConfigError(ValueError):
    """A value-free error: neither malformed URLs nor credentials escape in messages."""

    code = "CS_CONFIG_MISSING"

    def __init__(self, reason: str) -> None:
        self.reason = reason
        super().__init__(f"{self.code}: {reason}")


class RequestOptions(BaseModel):
    """Frozen transport limits sent explicitly by the extraction adapter."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    timeout_seconds: float = Field(default=300.0, gt=0, allow_inf_nan=False)
    max_output_tokens: int = Field(default=4096, gt=0, strict=True)
    token_parameter: Literal["max_tokens", "max_completion_tokens"] = "max_tokens"
    # No implicit temperature/thinking/reasoning options or compatibility retries.


class ExtractionProfile(BaseModel):
    """Serializable, credential-free identity of one extraction endpoint and model."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    schema_version: Literal["corpus-extraction-profile-v1"] = "corpus-extraction-profile-v1"
    name: Literal["structured_extraction"] = "structured_extraction"
    provider: Literal["openai_compat"]
    model: str
    base_url: str
    credential_ref: Literal["env:STRUCTURED_EXTRACTION_API_KEY"] = (
        "env:STRUCTURED_EXTRACTION_API_KEY"
    )
    adapter_version: Literal["structured-chat-http-1"] = ADAPTER_VERSION
    options: RequestOptions = Field(default_factory=RequestOptions)

    @property
    def fingerprint(self) -> str:
        """Hash the frozen public model configuration without its credential value."""
        return canonical_hash(self.model_dump(mode="json"))


class ExtractionConfig(BaseModel):
    """Frozen profile plus its non-serializable in-memory credential authority."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    profile: ExtractionProfile | None = None
    credential: SecretStr | None = Field(default=None, exclude=True, repr=False)
    error_codes: tuple[str, ...] = ()
    missing_fields: tuple[str, ...] = ()
    reason: str | None = None

    @property
    def configured(self) -> bool:
        """Report whether a profile and its in-memory credential are available."""
        return self.profile is not None and self.credential is not None and not self.error_codes

    def require_profile(self) -> ExtractionProfile:
        """Return the configured profile or raise a credential-free configuration error."""
        if not self.configured or self.profile is None:
            raise ExtractionConfigError(self.reason or "credentials_not_restored")
        return self.profile


def _identifier(value: str) -> bool:
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", value))


def validate_endpoint(value: str, secret: str) -> bool:
    """Reject credential-bearing URLs, URL interpolation and non-HTTP transports."""
    try:
        parsed = urlsplit(value)
        valid = (
            parsed.scheme in {"https", "http"}
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and not parsed.query
            and not parsed.fragment
            and not any(char.isspace() or ord(char) < 32 for char in value)
            and not any(char in value for char in ("$", "\\"))
            and secret not in unquote(value)
            and (parsed.port is None or 0 < parsed.port < 65536)
        )
        return bool(valid)
    except ValueError:
        return False


def load_extraction_config(
    *,
    environ: Mapping[str, str] | None = None,
    dotenv_path: str | Path | None = None,
    options: RequestOptions | None = None,
) -> ExtractionConfig:
    """Load only dedicated keys, with no cwd search, provider registry or env expansion."""
    values: dict[str, str] = {}
    if dotenv_path is not None:
        try:
            with Path(dotenv_path).open(encoding="utf-8") as stream:
                file_values = dotenv_values(stream=stream, interpolate=False)
            values.update({key: file_values.get(key) or "" for key in CONFIG_KEYS})
        except (OSError, UnicodeError):
            return ExtractionConfig(error_codes=("CS_CONFIG_MISSING",), reason="dotenv_unreadable")
    env = os.environ if environ is None else environ
    values.update({key: env[key] for key in CONFIG_KEYS if key in env})
    missing = tuple(key for key in CONFIG_KEYS if not values.get(key, "").strip())
    if missing:
        return ExtractionConfig(
            error_codes=("CS_CONFIG_MISSING",),
            missing_fields=missing,
            reason="required_fields_missing",
        )
    if any("$" in values[key] for key in CONFIG_KEYS):
        return ExtractionConfig(
            error_codes=("CS_CONFIG_MISSING",), reason="interpolation_forbidden"
        )
    provider, model, base_url, secret = (values[key].strip() for key in CONFIG_KEYS)
    if provider != "openai_compat":
        return ExtractionConfig(error_codes=("CS_CONFIG_MISSING",), reason="provider_unsupported")
    if (
        not _identifier(model)
        or secret in model
        or secret in provider
        or any(ord(char) < 33 or ord(char) > 126 for char in secret)
        or not validate_endpoint(base_url, secret)
    ):
        return ExtractionConfig(
            error_codes=("CS_CONFIG_MISSING",), reason="invalid_dedicated_config"
        )
    request_options = options or RequestOptions()
    if not math.isfinite(request_options.timeout_seconds):
        raise ExtractionConfigError("invalid_request_options")
    profile = ExtractionProfile(
        provider="openai_compat",
        model=model,
        base_url=base_url.rstrip("/"),
        options=request_options,
    )
    return ExtractionConfig(profile=profile, credential=SecretStr(secret))


class RoleBinding(BaseModel):
    """Bind one extraction role and protocol to an immutable model configuration."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    role: Role
    protocol: str
    config: ExtractionConfig = Field(repr=False, exclude=True)

    @property
    def fingerprint(self) -> str:
        """Hash the role, frozen protocol and configured model identity together."""
        return canonical_hash(
            {
                "role": self.role,
                "protocol": self.protocol,
                "model_profile": self.config.require_profile().fingerprint,
            }
        )


def bind_roles(
    config: ExtractionConfig, *, overrides: Mapping[Role, ExtractionConfig] | None = None
) -> tuple[RoleBinding, ...]:
    """Bind roles independently; explicit frozen overrides support fake multi-model tests."""
    replacements = overrides or {}
    if set(replacements) - set(PROTOCOLS):
        raise ExtractionConfigError("unknown_role")
    roles: tuple[Role, ...] = ("claims", "material_items", "material_relations")
    return tuple(
        RoleBinding(role=role, protocol=PROTOCOLS[role], config=replacements.get(role, config))
        for role in roles
    )
