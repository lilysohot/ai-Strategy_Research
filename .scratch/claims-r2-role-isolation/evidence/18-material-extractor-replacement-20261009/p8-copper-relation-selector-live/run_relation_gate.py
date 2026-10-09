"""Bounded relation-only gate over the signed P7 items artifact.

This evidence runner exists because the batch ledger currently cannot import an
accepted replay-mode items artifact into a live-mode relation task.  It keeps
the production role executor and adapter, persists authorization before I/O,
allows at most four sends, and never retries an unknown outcome.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any

from plugins.corpus.claims import LlmCallError, LlmResponse
from plugins.corpus.material_semantics import (
    MATERIAL_ITEMS_VALIDATION_VERSION,
    RELATION_CANDIDATE_RULE_VERSION,
    MaterialRun,
    build_relation_candidate_set,
)
from plugins.corpus.structured.adapter import ExtractionAdapter, RequestIntent
from plugins.corpus.structured.config import (
    RequestOptions,
    RoleBinding,
    canonical_hash,
    load_extraction_config,
)
from plugins.corpus.structured.roles import (
    MATERIAL_RELATION_SELECTOR_JSONL_VERSION,
    RoleArtifact,
    RoleExecution,
    RoleRequest,
    execute_material_relations_role,
)
from plugins.corpus.structured.snapshot import EvidenceSnapshot


ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
P7 = HERE.parent / "p7-copper-selector-v5-zero-call"
P7_STORE = P7 / "replay-store"
SNAPSHOT_PATH = (
    HERE.parents[1]
    / "17-structured-extraction-convergence-closure-20261009"
    / "p1-plan-freeze"
    / "copper-items-relations"
    / "snapshot.json"
)
ITEMS_ARTIFACT_SHA = "80e4c3a25150f10729185c97184ae849c2688d828e0544f3da0df1ab79a507a8"
ITEMS_PAYLOAD_SHA = "592065e674a8a0c1b2ff6764014781b029f8e22f616f0460dc921426b8a2c896"
MAX_CALLS = 4
P8_RELATION_RULE_VERSION = "material-relation-candidates-v3"


def _object_path(digest: str) -> Path:
    return P7_STORE / "objects" / "sha256" / digest[:2] / f"{digest}.json"


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass


def _read_verified(path: Path, expected: str) -> dict[str, Any]:
    data = path.read_bytes()
    if _sha256_bytes(data) != expected:
        raise RuntimeError(f"hash mismatch: {path.name}")
    value = json.loads(data)
    if not isinstance(value, dict):
        raise RuntimeError(f"invalid object: {path.name}")
    return value


def _signed_gate() -> dict[str, Any]:
    value = json.loads((P7 / "candidate-adjudications.agent-draft.json").read_text())
    signoff = value.get("signoff", {})
    if value.get("status") != "human_signed" or signoff.get("name") != "xyl":
        raise RuntimeError("P7 adjudication is not signed by xyl")
    return value


def _inputs() -> tuple[EvidenceSnapshot, RoleExecution, tuple[str, ...]]:
    snapshot = EvidenceSnapshot.model_validate_json(SNAPSHOT_PATH.read_text())
    snapshot.verify_identity()
    artifact = RoleArtifact.model_validate(
        _read_verified(_object_path(ITEMS_ARTIFACT_SHA), ITEMS_ARTIFACT_SHA)
    )
    payload = MaterialRun.model_validate(
        _read_verified(_object_path(ITEMS_PAYLOAD_SHA), ITEMS_PAYLOAD_SHA)
    )
    artifact.verify_identity()
    payload.verify_identity()
    if artifact.payload_sha256 != f"sha256:{ITEMS_PAYLOAD_SHA}":
        raise RuntimeError("items artifact/payload binding mismatch")
    endpoint_ids = tuple(
        item_ref
        for entry in payload.understanding.coverage.slot_ledger
        if entry.status == "extracted"
        for item_ref in entry.item_refs
    )
    if len(endpoint_ids) != len(set(endpoint_ids)):
        raise RuntimeError("duplicate qualified relation endpoint")
    return snapshot, RoleExecution(artifact=artifact, payload=payload), endpoint_ids


def _plan() -> tuple[dict[str, Any], Any, EvidenceSnapshot, RoleExecution, tuple[str, ...]]:
    signoff = _signed_gate()
    snapshot, items, endpoint_ids = _inputs()
    config = load_extraction_config(
        dotenv_path=ROOT / ".env",
        options=RequestOptions(timeout_seconds=300, max_output_tokens=16384),
    )
    profile = config.require_profile()
    binding = RoleBinding(
        role="material_relations",
        protocol=MATERIAL_RELATION_SELECTOR_JSONL_VERSION,
        config=config,
    )
    candidates = build_relation_candidate_set(
        snapshot,
        items.payload,
        endpoint_item_ids=endpoint_ids,
        items_validation_version=MATERIAL_ITEMS_VALIDATION_VERSION,
        rule_version=P8_RELATION_RULE_VERSION,
    )
    packet_ids = tuple(dict.fromkeys(candidate.packet_id for candidate in candidates.candidates))
    task_identity = {
        "snapshot_id": snapshot.snapshot_id,
        "items_artifact_id": items.artifact.artifact_id,
        "items_run_id": items.payload.run_id,
        "candidate_set_id": candidates.candidate_set_id,
        "endpoint_item_ids": endpoint_ids,
        "role_profile_sha256": binding.fingerprint,
        "protocol": MATERIAL_RELATION_SELECTOR_JSONL_VERSION,
        "max_calls": MAX_CALLS,
    }
    task_id = "task:" + canonical_hash(task_identity)[7:]
    plan = {
        "schema_version": "bounded-relation-gate-plan-1",
        "authorization": signoff["signoff"],
        "task_id": task_id,
        "snapshot_id": snapshot.snapshot_id,
        "items_artifact_id": items.artifact.artifact_id,
        "items_artifact_sha256": f"sha256:{ITEMS_ARTIFACT_SHA}",
        "items_payload_sha256": f"sha256:{ITEMS_PAYLOAD_SHA}",
        "items_run_id": items.payload.run_id,
        "endpoint_count": len(endpoint_ids),
        "endpoint_item_ids_sha256": canonical_hash(endpoint_ids),
        "candidate_set_id": candidates.candidate_set_id,
        "candidate_count": len(candidates.candidates),
        "packet_ids": packet_ids,
        "expected_calls": len(packet_ids),
        "max_calls": MAX_CALLS,
        "retry_limit": 0,
        "stop_after_outcome_unknown": True,
        "protocol": MATERIAL_RELATION_SELECTOR_JSONL_VERSION,
        "items_validation_version": MATERIAL_ITEMS_VALIDATION_VERSION,
        "candidate_rule_version": P8_RELATION_RULE_VERSION,
        "profile": {
            "provider": profile.provider,
            "model": profile.model,
            "base_url_sha256": canonical_hash(profile.base_url),
            "credential_ref": profile.credential_ref,
            "profile_sha256": profile.fingerprint,
            "role_profile_sha256": binding.fingerprint,
            "adapter_version": profile.adapter_version,
            "options": profile.options.model_dump(mode="json"),
        },
        "publication_query_delivery_context_use": 0,
    }
    if len(packet_ids) > MAX_CALLS:
        raise RuntimeError("relation packet count exceeds signed call ceiling")
    return plan, binding, snapshot, items, endpoint_ids


class GateLedger:
    def __init__(self, plan: dict[str, Any]) -> None:
        self.path = HERE / "attempt-ledger.json"
        self.responses = HERE / "responses"
        self.plan = plan
        self.stop = False
        if self.path.exists() or (HERE / "relation-execution.json").exists():
            raise RuntimeError("gate already started; automatic rerun is forbidden")
        self.value: dict[str, Any] = {
            "schema_version": "bounded-relation-attempt-ledger-1",
            "task_id": plan["task_id"],
            "max_calls": MAX_CALLS,
            "retry_limit": 0,
            "attempts": [],
        }
        _write_json(self.path, self.value)

    def authorize(self, intent: RequestIntent) -> str:
        attempts = self.value["attempts"]
        if self.stop:
            raise LlmCallError(
                {"execution_status": "blocked", "error_code": "CS_OUTCOME_UNKNOWN"}
            )
        if len(attempts) >= MAX_CALLS:
            raise LlmCallError(
                {"execution_status": "blocked", "error_code": "CS_BUDGET_EXHAUSTED"}
            )
        if (
            intent.role != "material_relations"
            or intent.protocol != self.plan["protocol"]
            or intent.profile_sha256 != self.plan["profile"]["profile_sha256"]
            or intent.role_profile_sha256
            != self.plan["profile"]["role_profile_sha256"]
        ):
            raise LlmCallError(
                {"execution_status": "failed", "error_code": "CS_INPUT_INVALID"}
            )
        number = len(attempts) + 1
        attempt_id = "attempt:" + canonical_hash(
            {
                "task_id": self.plan["task_id"],
                "attempt_number": number,
                "request_sha256": intent.request_sha256,
            }
        )[7:]
        attempts.append(
            {
                "attempt_id": attempt_id,
                "attempt_number": number,
                "execution_status": "running",
                "role": intent.role,
                "protocol": intent.protocol,
                "provider": intent.provider,
                "request_model": intent.request_model,
                "profile_sha256": intent.profile_sha256,
                "role_profile_sha256": intent.role_profile_sha256,
                "request_sha256": intent.request_sha256,
            }
        )
        _write_json(self.path, self.value)
        return attempt_id

    def dispatch(self, adapter: ExtractionAdapter, request: RoleRequest) -> str:
        if self.stop:
            raise LlmCallError(
                {"execution_status": "blocked", "error_code": "CS_OUTCOME_UNKNOWN"}
            )
        try:
            response = adapter(request.prompt)
        except LlmCallError as exc:
            if self.value["attempts"]:
                row = self.value["attempts"][-1]
                if row["execution_status"] == "running":
                    row["execution_status"] = exc.diagnostics.get(
                        "execution_status", "failed"
                    )
                    row["diagnostics"] = exc.diagnostics
                    if row["execution_status"] == "outcome_unknown":
                        self.stop = True
                    _write_json(self.path, self.value)
            raise
        row = self.value["attempts"][-1]
        row["execution_status"] = "succeeded"
        row["response_sha256"] = canonical_hash(str(response))
        row["diagnostics"] = response.diagnostics
        _write_json(self.path, self.value)
        _write_json(
            self.responses / f"relations-{row['attempt_number']:02d}.json",
            {
                "task_id": request.task_id,
                "role": request.role,
                "protocol": request.protocol,
                "sequence": request.sequence,
                "request_sha256": request.request_sha256,
                "content": str(response),
                "diagnostics": response.diagnostics,
            },
        )
        return response


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--execute", action="store_true")
    parser.add_argument("--finalize", action="store_true")
    args = parser.parse_args()
    if args.execute and args.finalize:
        raise RuntimeError("choose execute or finalize")
    plan, binding, snapshot, items, endpoint_ids = _plan()
    _write_json(HERE / "plan.json", plan)
    print(
        json.dumps(
            {
                "task_id": plan["task_id"],
                "candidate_count": plan["candidate_count"],
                "packet_count": len(plan["packet_ids"]),
                "model_calls": 0,
                "plan_file": str(HERE / "plan.json"),
            },
            ensure_ascii=False,
        )
    )
    if not args.execute and not args.finalize:
        return 0
    ledger: GateLedger | None = None
    if args.execute:
        ledger = GateLedger(plan)
        adapter = ExtractionAdapter(binding=binding, authorize=ledger.authorize)
        dispatch = lambda request: ledger.dispatch(adapter, request)
    else:
        ledger_value = json.loads((HERE / "attempt-ledger.json").read_text())
        if (
            len(ledger_value.get("attempts", ())) != plan["expected_calls"]
            or any(
                attempt.get("execution_status") != "succeeded"
                for attempt in ledger_value["attempts"]
            )
        ):
            raise RuntimeError("live attempt ledger is not fully succeeded")
        responses = {
            value["sequence"]: value
            for path in sorted((HERE / "responses").glob("relations-*.json"))
            for value in (json.loads(path.read_text()),)
        }
        if len(responses) != plan["expected_calls"]:
            raise RuntimeError("saved relation response set is incomplete")

        def dispatch(request: RoleRequest) -> str:
            value = responses.get(request.sequence)
            if value is None or any(
                value.get(field) != getattr(request, field)
                for field in ("task_id", "role", "protocol", "request_sha256")
            ):
                raise RuntimeError("saved relation response binding mismatch")
            return LlmResponse(value["content"], value.get("diagnostics", {}))

    execution = execute_material_relations_role(
        snapshot,
        task_id=plan["task_id"],
        protocol=plan["protocol"],
        items_execution=items,
        endpoint_item_ids=endpoint_ids,
        items_validation_version=plan["items_validation_version"],
        candidate_rule_version=plan["candidate_rule_version"],
        max_calls=MAX_CALLS,
        dispatch=dispatch,
    )
    execution_json = {
        "artifact": execution.artifact.model_dump(mode="json"),
        "payload": execution.payload.model_dump(mode="json"),
        "relation_candidates": (
            execution.relation_candidates.model_dump(mode="json")
            if execution.relation_candidates is not None
            else None
        ),
        "calls": [
            {
                "request": {
                    "task_id": call.request.task_id,
                    "role": call.request.role,
                    "protocol": call.request.protocol,
                    "snapshot_id": call.request.snapshot_id,
                    "input_sha256": call.request.input_sha256,
                    "request_sha256": call.request.request_sha256,
                    "prompt": call.request.prompt,
                    "sequence": call.request.sequence,
                },
                "response_sha256": call.response_sha256,
                "execution_status": call.execution_status,
                "diagnostics": call.diagnostics,
            }
            for call in execution.calls
        ],
    }
    _write_json(HERE / "relation-execution.json", execution_json)
    _write_json(HERE / "relation-artifact.json", execution.artifact.model_dump(mode="json"))
    _write_json(HERE / "relation-payload.json", execution.payload.model_dump(mode="json"))
    summary = {
        "schema_version": "bounded-relation-gate-execution-1",
        "task_id": plan["task_id"],
        "execution_status": execution.artifact.execution_status,
        "protocol_status": execution.artifact.protocol_status,
        "quality_status": execution.artifact.quality_status,
        "artifact_id": execution.artifact.artifact_id,
        "payload_sha256": execution.artifact.payload_sha256,
        "candidate_count": len(execution.relation_candidates.candidates),
        "relations": len(execution.payload.understanding.relations),
        "accepted_candidate_rate": (
            len(execution.payload.understanding.relations)
            / len(execution.relation_candidates.candidates)
        ),
        "packet_candidate_decisions": [
            {
                "packet_id": packet.packet_id,
                "candidates": packet.diagnostics.get("candidate_pairs"),
                "present": packet.records,
            }
            for packet in execution.payload.packet_runs
        ],
        "packet_status": {
            status: sum(packet.status == status for packet in execution.payload.packet_runs)
            for status in ("completed", "partial", "failed", "deferred")
        },
        "attempts": len(
            ledger.value["attempts"] if ledger is not None else ledger_value["attempts"]
        ),
        "attempt_status": {
            status: sum(
                attempt["execution_status"] == status
                for attempt in (
                    ledger.value["attempts"]
                    if ledger is not None
                    else ledger_value["attempts"]
                )
            )
            for status in ("succeeded", "failed", "outcome_unknown", "blocked")
        },
        "usage": {
            key: sum(
                (attempt.get("diagnostics") or {}).get(key) or 0
                for attempt in (
                    ledger.value["attempts"]
                    if ledger is not None
                    else ledger_value["attempts"]
                )
            )
            for key in (
                "prompt_tokens",
                "completion_tokens",
                "reasoning_tokens",
                "total_tokens",
            )
        },
        "cost": {
            "known_attempts": sum(
                (attempt.get("diagnostics") or {}).get("cost") is not None
                for attempt in (
                    ledger.value["attempts"]
                    if ledger is not None
                    else ledger_value["attempts"]
                )
            ),
            "status": "unavailable",
            "not_assumed_zero": True,
        },
        "publication_query_delivery_context_use": 0,
    }
    _write_json(HERE / "execution-summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False))
    return 0 if ledger is None or not ledger.stop else 6


if __name__ == "__main__":
    raise SystemExit(main())
