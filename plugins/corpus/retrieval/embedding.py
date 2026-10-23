"""Text-only Doubao embedding contract and a versioned retrieval space."""

from __future__ import annotations

import hashlib
import json
import math
import os
import re
from dataclasses import dataclass, field, replace
from typing import Literal, cast
from urllib.parse import urlsplit

import httpx

Role = Literal["document", "query"]
#: ``contextual-note-v1`` = 说明 + 原文片段（Contextual Retrieval）；只用于原生索引包，
#: 旧 ``VectorIndex`` 侧表构建会显式拒绝，避免两种输入口径混进同一向量空间。
InputVariant = Literal[
    "published-search-text-v1", "reviewed-context-prefix-v1", "contextual-note-v1"
]


class EmbeddingError(RuntimeError):
    """Safe error code: never includes provider bodies, credentials or report text."""

    def __init__(self, code: str, *, uncertain: bool = False) -> None:
        super().__init__(code)
        self.code = code
        self.uncertain = uncertain


@dataclass(frozen=True)
class VectorConfig:
    # Standard Ark defaults only. from_env() supplies the runtime values, including
    # Agent Plan's model alias; revision identifies the local cache, not the API model.
    api_url: str = "https://ark.cn-beijing.volces.com/api/v3/embeddings/multimodal"
    api_key: str = field(default="", repr=False)
    model: str = "doubao-embedding-vision-251215"
    revision: str = "doubao-embedding-vision-251215"
    dimensions: int = 2048
    target_db: str = "vector_pilot_corpus_20261020"
    timeout: float = 15.0
    max_chars: int = 16000
    input_variant: InputVariant = "published-search-text-v1"
    document_instruction: str = "Instruction:Compress the text into one word.\nQuery:"
    query_instruction: str = (
        "Target_modality: text.\nInstruction:为这个句子生成表示以用于检索相关文章\nQuery:"
    )

    @classmethod
    def from_env(cls) -> VectorConfig:
        """Read only this feature's configuration; no fallback to a chat API key."""
        defaults = cls()
        cfg = cls(
            api_url=os.getenv("CORPUS_VECTOR_API_URL", defaults.api_url).strip(),
            api_key=os.getenv("CORPUS_VECTOR_API_KEY", "").strip(),
            model=os.getenv("CORPUS_VECTOR_MODEL", defaults.model).strip(),
            revision=os.getenv("CORPUS_VECTOR_REVISION", defaults.revision).strip(),
            dimensions=int(os.getenv("CORPUS_VECTOR_DIMENSIONS", str(defaults.dimensions))),
            target_db=os.getenv("CORPUS_VECTOR_TARGET_DB", defaults.target_db).strip(),
            timeout=float(os.getenv("CORPUS_VECTOR_TIMEOUT_SECONDS", str(defaults.timeout))),
            max_chars=int(os.getenv("CORPUS_VECTOR_MAX_CHARS", str(defaults.max_chars))),
            input_variant=cast(
                InputVariant,
                os.getenv("CORPUS_VECTOR_INPUT_VARIANT", defaults.input_variant).strip(),
            ),
        )
        parsed = urlsplit(cfg.api_url)
        if (
            parsed.scheme != "https"
            or not parsed.netloc
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise EmbeddingError("invalid_api_url")
        if not cfg.model or not cfg.revision or not cfg.target_db:
            raise EmbeddingError("missing_model_revision_or_target")
        if cfg.dimensions not in (1024, 2048):
            raise EmbeddingError("unsupported_dimensions")
        if cfg.input_variant not in (
            "published-search-text-v1",
            "reviewed-context-prefix-v1",
            "contextual-note-v1",
        ):
            raise EmbeddingError("unsupported_input_variant")
        if not math.isfinite(cfg.timeout) or not 0 < cfg.timeout <= 120 or cfg.max_chars < 1:
            raise EmbeddingError("invalid_request_limits")
        # Ark examples configure SDK Base URLs. This adapter uses raw HTTP and must
        # append the resource itself, preserving /plan and the caller's model alias.
        # Already-complete endpoints and other providers' URLs remain untouched.
        if parsed.hostname == "ark.cn-beijing.volces.com" and parsed.path.rstrip("/") in (
            "/api/v3",
            "/api/plan/v3",
        ):
            cfg = replace(cfg, api_url=cfg.api_url.rstrip("/") + "/embeddings/multimodal")
        return cfg

    @property
    def profile(self) -> str:
        """Configuration changes create a new vector space; secrets do not."""
        return hashlib.sha256(json.dumps(self.definition(), sort_keys=True).encode()).hexdigest()

    def definition(self) -> dict[str, object]:
        """Persisted model/input contract without API credentials."""
        return {
            "provider": self.api_url,
            "model": self.model,
            "revision": self.revision,
            "dimensions": self.dimensions,
            "document_instruction": self.document_instruction,
            "query_instruction": self.query_instruction,
            "input_variant": self.input_variant,
            "distance": "cosine",
        }


def text_hash(text: str) -> str:
    """Hash the exact model input without trimming or rewriting the evidence text."""
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def validate_vector(value: object, dimensions: int) -> tuple[float, ...]:
    if not isinstance(value, (list, tuple)) or len(value) != dimensions:
        raise EmbeddingError("invalid_embedding_dimensions", uncertain=True)
    if any(isinstance(v, bool) or not isinstance(v, (int, float)) for v in value):
        raise EmbeddingError("invalid_embedding_values", uncertain=True)
    vector = tuple(float(v) for v in value)
    if not all(math.isfinite(v) for v in vector) or not any(vector):
        raise EmbeddingError("invalid_embedding_values", uncertain=True)
    return vector


@dataclass(frozen=True)
class EmbeddingResult:
    vector: tuple[float, ...]
    usage: dict[str, int]


class DoubaoEmbedder:
    """One text per request. The multimodal input array is NOT a text batch."""

    def __init__(
        self, config: VectorConfig, *, transport: httpx.BaseTransport | None = None
    ) -> None:
        self.config = config
        self.transport = transport

    def embed(self, text: str, role: Role) -> EmbeddingResult:
        cfg = self.config
        if not text.strip():
            raise EmbeddingError("empty_input")
        if len(text) > cfg.max_chars:
            raise EmbeddingError("input_exceeds_character_guard")
        if not cfg.api_key:
            raise EmbeddingError("api_key_missing")
        payload = {
            "model": cfg.model,
            "encoding_format": "float",
            "dimensions": cfg.dimensions,
            "instructions": (
                cfg.document_instruction if role == "document" else cfg.query_instruction
            ),
            "input": [{"type": "text", "text": text}],
        }
        try:
            with httpx.Client(
                timeout=cfg.timeout, transport=self.transport, follow_redirects=False
            ) as client:
                response = client.post(
                    cfg.api_url,
                    headers={"Authorization": f"Bearer {cfg.api_key}"},
                    json=payload,
                )
        except httpx.HTTPError:
            # A timeout does not prove that the provider did not process/charge the input.
            raise EmbeddingError("provider_transport_uncertain", uncertain=True) from None
        if response.status_code != 200:
            raise EmbeddingError(
                f"provider_http_{response.status_code}",
                uncertain=response.status_code >= 500,
            )
        try:
            body = response.json()
            returned_model = body.get("model")
            # Alias/endpoint routing can change without changing the request model.
            # If a concrete Doubao revision is pinned, reject a reported mismatch.
            if (
                re.fullmatch(r"doubao-embedding-vision-\d{6}", cfg.revision)
                and isinstance(returned_model, str)
                and returned_model != cfg.revision
            ):
                raise EmbeddingError("embedding_model_revision_mismatch", uncertain=True)
            vector = validate_vector(body["data"]["embedding"], cfg.dimensions)
            raw_usage = body.get("usage", {})
            usage = {
                str(k): v
                for k, v in raw_usage.items()
                if isinstance(v, int) and not isinstance(v, bool) and v >= 0
            }
        except (ValueError, KeyError, TypeError, AttributeError):
            raise EmbeddingError("provider_response_uncertain", uncertain=True) from None
        return EmbeddingResult(vector, usage)
