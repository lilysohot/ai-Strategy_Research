"""V1 internal communication contracts; these are not A2A wire models."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

# Stored in the existing outbox envelope so disabling Super-link holds queued
# work without querying optional tables in an ordinary installation.
DISPATCH_MARKER = "[super-link-dispatch-v1]\n"


class DeliveryContent(BaseModel):
    """Self-contained text only until the attachment publication adapter lands.

    Text may describe evidence, but no path/URL is automatically read or granted to
    the recipient. Inspection is still required before any execution acceptance.
    """

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    schema_version: Literal[1] = 1
    body: str = Field(min_length=1, max_length=64_000)
    requests_execution: bool = False

    @field_validator("body")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("empty_delivery")
        return value


class EvidenceReference(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    rel_path: str = Field(min_length=1, max_length=500)
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")


class EvidenceDelivery(BaseModel):
    """V2 explicitly names final UTF-8 outputs to snapshot after worker exit."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)
    schema_version: Literal[2] = 2
    body: str = Field(min_length=1, max_length=64_000)
    requests_execution: bool = False
    artifacts: list[EvidenceReference] = Field(max_length=4)

    @field_validator("body")
    @classmethod
    def nonblank(cls, value: str) -> str:
        return DeliveryContent.nonblank(value)


def parse_content(value: dict) -> DeliveryContent | EvidenceDelivery:
    if value.get("schema_version") == 2:
        return EvidenceDelivery.model_validate(value)
    return DeliveryContent.model_validate(value)


def content_digest(content: DeliveryContent | EvidenceDelivery) -> str:
    payload = json.dumps(content.model_dump(), sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


@dataclass(frozen=True)
class SenderBinding:
    """Trusted host identity, never constructed from model-supplied owner fields."""

    user_id: uuid.UUID
    space_id: uuid.UUID
    participant_id: uuid.UUID
    run_id: uuid.UUID


@dataclass(frozen=True)
class Pair:
    space_id: uuid.UUID
    team_id: uuid.UUID
    team_session_id: uuid.UUID
    single_id: uuid.UUID
    single_session_id: uuid.UUID


class CollaborationError(ValueError):
    """Stable error code, with no credentials or peer content attached."""
