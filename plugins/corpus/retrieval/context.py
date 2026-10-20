"""Reviewed source metadata and deterministic embedding context."""

from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from typing import cast

from plugins.corpus.retrieval.embedding import EmbeddingError

_SOURCE_ID_RE = re.compile(r"[0-9a-f]{64}")
_FIELD_NAMES = ("report_title", "institution", "confirmed_publication_date")


def _single_line(value: object, field: str, *, required: bool = False) -> str | None:
    if value is None:
        if required:
            raise EmbeddingError(f"source_metadata_{field}_missing")
        return None
    if not isinstance(value, str):
        raise EmbeddingError(f"source_metadata_{field}_invalid")
    normalized = " ".join(value.split())
    if not normalized:
        if required:
            raise EmbeddingError(f"source_metadata_{field}_missing")
        return None
    if len(normalized) > 500:
        raise EmbeddingError(f"source_metadata_{field}_too_long")
    return normalized


@dataclass(frozen=True)
class SourceMetadata:
    """Human-reviewed fields used only by the retrieval side index."""

    source_id: str
    report_title: str
    institution: str | None
    confirmed_publication_date: str | None
    field_evidence: dict[str, tuple[str, ...]]
    reviewed_by: str
    reviewed_at: str

    def __post_init__(self) -> None:
        if not _SOURCE_ID_RE.fullmatch(self.source_id):
            raise EmbeddingError("source_metadata_source_id_invalid")
        object.__setattr__(
            self, "report_title", _single_line(self.report_title, "report_title", required=True)
        )
        object.__setattr__(self, "institution", _single_line(self.institution, "institution"))
        published = _single_line(self.confirmed_publication_date, "confirmed_publication_date")
        if published is not None:
            try:
                if date.fromisoformat(published).isoformat() != published:
                    raise ValueError
            except ValueError:
                raise EmbeddingError("source_metadata_date_invalid") from None
        object.__setattr__(self, "confirmed_publication_date", published)
        reviewer = _single_line(self.reviewed_by, "reviewed_by", required=True)
        object.__setattr__(self, "reviewed_by", reviewer)
        try:
            parsed = datetime.fromisoformat(self.reviewed_at.replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                raise ValueError
        except (AttributeError, ValueError):
            raise EmbeddingError("source_metadata_reviewed_at_invalid") from None

        clean_evidence: dict[str, tuple[str, ...]] = {}
        if not isinstance(self.field_evidence, dict):
            raise EmbeddingError("source_metadata_evidence_invalid")
        for field in _FIELD_NAMES:
            raw_refs = self.field_evidence.get(field, ())
            if not isinstance(raw_refs, (list, tuple)):
                raise EmbeddingError("source_metadata_evidence_invalid")
            refs = tuple(ref for item in raw_refs if (ref := _single_line(item, "evidence")))
            value = getattr(self, field)
            if value is not None and not refs:
                raise EmbeddingError(f"source_metadata_{field}_evidence_missing")
            clean_evidence[field] = refs
        unknown = set(self.field_evidence) - set(_FIELD_NAMES)
        if unknown:
            raise EmbeddingError("source_metadata_evidence_unknown_field")
        object.__setattr__(self, "field_evidence", clean_evidence)

    @property
    def metadata_hash(self) -> str:
        payload = {
            "source_id": self.source_id,
            "report_title": self.report_title,
            "institution": self.institution,
            "confirmed_publication_date": self.confirmed_publication_date,
            "field_evidence": self.field_evidence,
        }
        return hashlib.sha256(
            json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
        ).hexdigest()


def load_source_metadata(path: Path) -> tuple[SourceMetadata, ...]:
    """Load a complete reviewed manifest; duplicate sources fail closed."""
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        raise EmbeddingError("source_metadata_manifest_unreadable") from None
    if not isinstance(raw, dict) or raw.get("schema_version") != "retrieval-source-metadata-v1":
        raise EmbeddingError("source_metadata_manifest_schema_invalid")
    reviewer = raw.get("reviewed_by")
    reviewed_at = raw.get("reviewed_at")
    entries = raw.get("sources")
    if (
        not isinstance(reviewer, str)
        or not isinstance(reviewed_at, str)
        or not isinstance(entries, list)
    ):
        raise EmbeddingError("source_metadata_manifest_sources_invalid")
    result: list[SourceMetadata] = []
    seen: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise EmbeddingError("source_metadata_entry_invalid")
        source_id = entry.get("source_id")
        report_title = entry.get("report_title")
        institution = entry.get("institution")
        published = entry.get("confirmed_publication_date")
        evidence = entry.get("field_evidence", {})
        if (
            not isinstance(source_id, str)
            or not isinstance(report_title, str)
            or (institution is not None and not isinstance(institution, str))
            or (published is not None and not isinstance(published, str))
        ):
            raise EmbeddingError("source_metadata_entry_invalid")
        metadata = SourceMetadata(
            source_id=source_id,
            report_title=report_title,
            institution=institution,
            confirmed_publication_date=published,
            field_evidence=cast(dict[str, tuple[str, ...]], evidence),
            reviewed_by=reviewer,
            reviewed_at=reviewed_at,
        )
        if metadata.source_id in seen:
            raise EmbeddingError("source_metadata_duplicate_source")
        seen.add(metadata.source_id)
        result.append(metadata)
    return tuple(result)


def deterministic_context_prefix(metadata: SourceMetadata, section_path: tuple[str, ...]) -> str:
    """Build context without generation, inference, or evidence-text rewriting."""
    lines = ["[来源元数据]", f"报告标题：{metadata.report_title}"]
    if metadata.institution:
        lines.append(f"研究机构：{metadata.institution}")
    if metadata.confirmed_publication_date:
        lines.append(f"已确认发布日期：{metadata.confirmed_publication_date}")
    clean_path = tuple(" ".join(part.split()) for part in section_path if part.strip())
    if clean_path:
        lines.append("章节路径：" + " > ".join(clean_path))
    return "\n".join(lines)


def contextual_model_input(prefix: str, source_text: str) -> str:
    """Keep stored source/context separate and combine only at the provider boundary."""
    return f"{prefix}\n[原文片段]\n{source_text}"
