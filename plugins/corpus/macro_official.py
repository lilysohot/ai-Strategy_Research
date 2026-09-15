"""M2: pinned BLS Employment Situation archives, never latest or calculation permission.

The host owns trusted transport, pin selection and archive retention. Replaying arbitrary
agent-supplied bytes with a matching hash is not proof of official origin.
"""

from __future__ import annotations

import hashlib
import json
import re
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, Self

import httpx
from pydantic import model_validator

from plugins.corpus._bls_archive import VERSION, ArchiveBlocked, parse_release
from plugins.corpus.evidence import EvidenceDocument, EvidencePacket, Span, fingerprint
from plugins.corpus.evidence_pipeline import EvidenceRun, PacketRun
from plugins.corpus.macro_models import (
    BlockedInput,
    Dimensions,
    EvidenceBinding,
    EvidenceReference,
    FrozenModel,
    Hash,
    MacroObservation,
    Month,
    RawAmount,
    ReleaseEvent,
    Scope,
    SourceTime,
    VerificationRecord,
    Vintage,
    resolve_reference,
)
from plugins.corpus.macro_verification import VerificationAuthority

MAX_ARCHIVE_BYTES = 2_000_000


class OfficialReleaseRequest(FrozenModel):
    archive_uri: str
    expected_sha256: Hash
    release_date: date
    reference_month: Month
    vintage_kind: Literal["first", "second", "third", "benchmark"]

    @model_validator(mode="after")
    def pinned_archive(self) -> Self:
        expected = (
            f"https://www.bls.gov/news.release/archives/empsit_{self.release_date:%m%d%Y}.htm"
        )
        if self.archive_uri != expected:
            raise ValueError("explicit canonical BLS archive URL must match release_date")
        return self


@dataclass(frozen=True)
class CapturedArchive:
    """Raw response plus acquisition metadata. Immutable bytes, not an authenticity certificate."""

    uri: str
    status_code: int
    content_type: str
    body: bytes
    retrieved_at: SourceTime

    @property
    def sha256(self) -> str:
        return hashlib.sha256(self.body).hexdigest()

    def save(self, directory: Path) -> tuple[Path, Path]:
        """Explicit append-only archival delivery; never overwrite a historical blob or receipt."""
        directory.mkdir(parents=True, exist_ok=True)
        metadata = json.dumps(
            {
                "uri": self.uri,
                "status_code": self.status_code,
                "content_type": self.content_type,
                "sha256": self.sha256,
                "retrieved_at": self.retrieved_at.raw,
            },
            sort_keys=True,
        ).encode()
        blob = directory / f"{self.sha256}.body"
        receipt = directory / f"{hashlib.sha256(metadata).hexdigest()}.json"
        for path, content in ((blob, self.body), (receipt, metadata)):
            try:
                with path.open("xb") as stream:
                    stream.write(content)
            except FileExistsError:
                if path.read_bytes() != content:
                    raise ValueError("source_hash_mismatch") from None
        return blob, receipt


@dataclass(frozen=True)
class OfficialReleaseResult:
    archive: CapturedArchive | None
    blocked: BlockedInput | None = None
    run: EvidenceRun | None = None
    event: ReleaseEvent | None = None
    vintage: Vintage | None = None
    observation: MacroObservation | None = None
    verifications: tuple[VerificationRecord, ...] = ()
    calculation_permitted: Literal[False] = False


class BlsReleaseAdapter:
    """One bounded fetch or offline replay; no discovery, fallback URL, LLM, or database writes.

    Injected clients and replay archives must be controlled by the host, not the model.
    Once pinned, a URI cannot change content in this adapter. Persist the request for restarts.
    """

    def __init__(self, client: httpx.Client | None = None) -> None:
        self._client = client
        self._runs: dict[str, EvidenceRun] = {}
        self._pins: dict[str, str] = {}
        self.authority = VerificationAuthority(
            issuer_id="bls-employment-situation-adapter",
            issuer_role="source_adapter",
            policy_version=VERSION,
            resolve=self._resolve,
        )
        self._results: dict[str, OfficialReleaseResult] = {}
        self._receipts: dict[str, VerificationRecord] = {}

    def _resolve(self, reference: EvidenceReference) -> str:
        return resolve_reference(reference, self._runs[reference.run_id])

    def _approve(
        self,
        subject: ReleaseEvent | Vintage | MacroObservation,
        scopes: tuple[Scope, ...],
        reviewed_at: SourceTime,
    ) -> VerificationRecord:
        key = fingerprint([subject.record_id, scopes, reviewed_at.raw])
        if key not in self._receipts:
            self._receipts[key] = self.authority.issue(
                subject,
                scopes=scopes,
                reviewed_at=reviewed_at,
                decision="approved",
                evidence=tuple(dict.fromkeys(b.reference for b in subject.evidence)),
            )
        return self._receipts[key]

    def fetch(self, request: OfficialReleaseRequest) -> OfficialReleaseResult:
        request = OfficialReleaseRequest.model_validate(request)
        if self._client is not None:
            return self._fetch(request, self._client)
        with httpx.Client(trust_env=False) as client:
            return self._fetch(request, client)

    def _fetch(
        self, request: OfficialReleaseRequest, client: httpx.Client
    ) -> OfficialReleaseResult:
        try:
            deadline = time.monotonic() + 30
            with client.stream(
                "GET",
                request.archive_uri,
                follow_redirects=False,
                timeout=20,
                headers={"Accept": "text/html", "Accept-Encoding": "identity"},
            ) as response:
                if response.headers.get("content-encoding", "identity").lower() != "identity":
                    raise ArchiveBlocked("source_conflict", "archive_content_encoding")
                chunks: list[bytes] = []
                size = 0
                for chunk in response.iter_bytes(chunk_size=65536):
                    if time.monotonic() > deadline:
                        raise ArchiveBlocked("source_conflict", "archive_time_limit")
                    size += len(chunk)
                    if size > MAX_ARCHIVE_BYTES:
                        raise ArchiveBlocked("source_conflict", "archive_size_limit")
                    chunks.append(chunk)
                archive = CapturedArchive(
                    uri=str(response.url),
                    status_code=response.status_code,
                    content_type=response.headers.get("content-type", ""),
                    body=b"".join(chunks),
                    retrieved_at=SourceTime(raw=datetime.now(UTC).isoformat()),
                )
        except (httpx.HTTPError, ArchiveBlocked) as exc:
            field = exc.field_name if isinstance(exc, ArchiveBlocked) else "archive_transport"
            return self._blocked(request, None, ArchiveBlocked("source_conflict", field))
        return self.replay(request, archive)

    @staticmethod
    def _blocked(
        request: OfficialReleaseRequest, archive: CapturedArchive | None, error: ArchiveBlocked
    ) -> OfficialReleaseResult:
        identities = (fingerprint(request.model_dump(mode="json")),)
        if archive is not None:
            identities += (archive.sha256,)
        return OfficialReleaseResult(
            archive=archive,
            blocked=BlockedInput(
                input_ids=identities,
                reason_codes=(error.reason,),
                missing_fields=(error.field_name,),
            ),
        )

    def replay(
        self, request: OfficialReleaseRequest, archive: CapturedArchive
    ) -> OfficialReleaseResult:
        """Re-verify retained host-owned bytes. No trust is restored merely by loading JSON."""
        request = OfficialReleaseRequest.model_validate(request)
        try:
            pinned = self._pins.setdefault(request.archive_uri, request.expected_sha256)
            if pinned != request.expected_sha256:
                raise ArchiveBlocked("source_hash_mismatch", "previous_archive_pin")
            if archive.uri != request.archive_uri or archive.status_code != 200:
                raise ArchiveBlocked("source_conflict", "official_archive_response")
            if len(archive.body) > MAX_ARCHIVE_BYTES:
                raise ArchiveBlocked("source_conflict", "archive_size_limit")
            if archive.sha256 != request.expected_sha256:
                raise ArchiveBlocked("source_hash_mismatch", "archive_sha256")
            if not re.fullmatch(r"text/html(?:;\s*charset=(?:utf-8|UTF-8))?", archive.content_type):
                raise ArchiveBlocked("source_conflict", "archive_content_type")
            try:
                raw = archive.body.decode("utf-8", errors="strict")
            except UnicodeDecodeError as exc:
                raise ArchiveBlocked("source_conflict", "archive_encoding") from exc
            parsed = parse_release(raw, request.release_date, request.reference_month)
            if parsed.vintage_kind != request.vintage_kind:
                raise ArchiveBlocked("vintage_mismatch", "requested_vintage")
            if archive.retrieved_at.utc < parsed.release_at.utc:
                raise ArchiveBlocked("time_provenance_unverified", "retrieved_at")
        except ArchiveBlocked as exc:
            return self._blocked(request, archive, exc)

        key = fingerprint(
            [request.model_dump(mode="json"), archive.sha256, archive.retrieved_at.raw]
        )
        if key in self._results:
            return self._results[key]
        # Reuse existing EvidenceRun identity and readers; keep raw HTML as the citation surface.
        parse_rev = fingerprint([archive.sha256, VERSION])
        packet = EvidencePacket(
            packet_id=fingerprint([parse_rev, raw]),
            locator="html:0",
            kind="official_archive",
            text=raw,
            spans=(Span(locator="html:0", text=raw, start=0, end=len(raw)),),
        )
        document = EvidenceDocument(
            doc_id=fingerprint(request.archive_uri),
            title=f"BLS Employment Situation {request.release_date}",
            source_path=request.archive_uri,
            source_rev=archive.sha256,
            parse_rev=parse_rev,
            parser_version=VERSION,
            subject="US",
            published=None,
            pages=packet.spans,
            packets=(packet,),
        )
        run = EvidenceRun(
            run_id="",
            document=document,
            pipeline_version=VERSION,
            extractor_version=VERSION,
            lint_version=VERSION,
            facts=(),
            packet_runs=(
                PacketRun(
                    packet_id=packet.packet_id,
                    status="complete",
                    method=VERSION,
                    records=0,
                ),
            ),
        )
        payload = run.model_dump(mode="json")
        payload.pop("run_id")
        run = run.model_copy(update={"run_id": fingerprint(payload)})
        run.verify_identity()
        bindings = tuple(
            EvidenceBinding.model_validate(
                {
                    "field": scope,
                    "reference": EvidenceReference(
                        run_id=run.run_id,
                        source_rev=archive.sha256,
                        packet_id=packet.packet_id,
                        locator=packet.locator,
                        quote=raw[start:end],
                        start=start,
                        end=end,
                    ),
                }
            )
            for scope, start, end in parsed.ranges
        )
        time_binding = next(b for b in bindings if b.field == "release_at")
        bindings += (EvidenceBinding(field="known_at", reference=time_binding.reference),)
        event = ReleaseEvent(
            publisher="U.S. Bureau of Labor Statistics",
            release_key=f"empsit:{request.release_date}",
            reference_month=parsed.release_month,
            release_at=parsed.release_at,
            archive_uri=archive.uri,
            archive_hash=archive.sha256,
            evidence=tuple(
                b
                for b in bindings
                if b.field in {"period", "release_at"} and b.reference == time_binding.reference
            ),
        )
        vintage = Vintage(
            release_event_id=event.record_id,
            reference_month=request.reference_month,
            vintage_kind=request.vintage_kind,
            published_at=parsed.release_at,
            evidence=tuple(b for b in bindings if b.field in {"vintage", "period", "release_at"}),
        )
        observation = MacroObservation(
            dimensions=Dimensions(
                country="US",
                indicator="US.NFP_CHANGE_SA",
                population="nonfarm_payroll_jobs",
                transform="month_change",
                adjustment="SA",
            ),
            reference_month=request.reference_month,
            role="actual",
            kind="observed",
            amount=RawAmount(value_raw=parsed.value_raw, unit_raw=parsed.unit_raw),
            release_event_id=event.record_id,
            vintage_id=vintage.record_id,
            known_at=parsed.release_at,
            ingested_at=archive.retrieved_at,
            evidence=bindings,
        )
        self._runs[run.run_id] = run
        scopes: tuple[Scope, ...] = (
            "indicator",
            "period",
            "value",
            "release_at",
            "known_at",
            "vintage",
            "unit_mapping",
        )
        receipts = (
            self._approve(event, ("period", "release_at"), archive.retrieved_at),
            self._approve(vintage, ("period", "vintage", "release_at"), archive.retrieved_at),
            self._approve(observation, scopes, archive.retrieved_at),
        )
        result = OfficialReleaseResult(
            archive=archive,
            run=run,
            event=event,
            vintage=vintage,
            observation=observation,
            verifications=receipts,
        )
        self._results[key] = result
        return result
