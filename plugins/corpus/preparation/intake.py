"""Validate explicit source authorization receipts before registering admission.

This records user authorization, not a claim of human transcription verification.
Admission policy and publication checks remain owned by the existing engine.
"""

from __future__ import annotations

import hashlib
import json
from datetime import datetime
from pathlib import Path

from plugins.corpus.preparation.contract import (
    MaterialType,
    ResearchDomain,
    ReviewDecision,
    ReviewedDecision,
)
from plugins.corpus.preparation.repository import Store, StoreError


def source_hash(path: str) -> str:
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def required_text(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError(f"{name} requires nonempty text")
    return value


def authorization_decisions(manifest: dict, record: dict) -> list[ReviewedDecision]:
    """Bind an entire receipt to exact bytes and decision IDs; no writes here."""
    if set(record) != {
        "operator",
        "authorized_by",
        "authorization_ref",
        "authorized_at",
        "sources",
    }:
        raise ValueError(
            "invalid authorization fields; only whole-source authorization is supported"
        )
    operator, authorizer, reference, timestamp = (
        required_text(record.get(key), key)
        for key in ("operator", "authorized_by", "authorization_ref", "authorized_at")
    )
    when = datetime.fromisoformat(timestamp)
    if when.utcoffset() is None:
        raise ValueError("authorized_at requires timezone")
    sources, decisions = manifest.get("sources"), record.get("sources")
    if not isinstance(sources, list) or not sources or not isinstance(decisions, list):
        raise ValueError("manifest and authorization require sources arrays")
    by_source = {}
    for item in sources:
        if not isinstance(item, dict):
            raise ValueError("invalid manifest source")
        sid = required_text(item.get("source_id"), "source_id")
        if sid != source_hash(required_text(item.get("path"), "path")):
            raise ValueError(f"source hash mismatch: {sid}")
        if sid in by_source:
            raise ValueError("duplicate manifest source")
        by_source[sid] = item
    result = []
    seen = set()
    ids = set()
    for item in decisions:
        if not isinstance(item, dict):
            raise ValueError("invalid authorization source")
        if set(item) != {"source_id", "decision_id", "material_type", "research_domain"}:
            raise ValueError("invalid authorization source fields; partial scope is not supported")
        sid = required_text(item.get("source_id"), "source_id")
        did = required_text(item.get("decision_id"), "decision_id")
        if sid not in by_source or sid in seen or did in ids:
            raise ValueError("authorization source/decision is duplicate or outside manifest")
        source = by_source[sid]
        if source.get("review_decision_ids") != [did]:
            raise ValueError("manifest must reference exactly its authorization decision")
        domain = ResearchDomain(item["research_domain"])
        if source.get("domain_hint") != domain.value:
            raise ValueError("manifest and authorization domain mismatch")
        result.append(
            ReviewedDecision(
                decision_id=did,
                source_id=sid,
                reviewer=authorizer,
                reviewed_at=when,
                decision=ReviewDecision.ADMITTED,
                rationale=json.dumps(
                    {
                        "kind": "user_source_authorization",
                        "operator": operator,
                        "authorization_ref": reference,
                        "coverage_claim": "no_transcription_or_completeness_attestation",
                    },
                    ensure_ascii=False,
                    sort_keys=True,
                ),
                material_type=MaterialType(item["material_type"]),
                research_domain=domain,
            )
        )
        seen.add(sid)
        ids.add(did)
    if seen != set(by_source):
        raise ValueError("authorization must cover exactly the manifest")
    return result


def register_authorizations(store: Store, decisions: list[ReviewedDecision]) -> None:
    """Preflight all conflicts; replay is idempotent, partial failures can resume."""
    for decision in decisions:
        old = store.get_reviewed_decision(decision.decision_id)
        if old is not None and old != decision:
            raise StoreError(f"authorization conflict: {decision.decision_id}")
    for decision in decisions:
        store.put_reviewed_decision(decision)
