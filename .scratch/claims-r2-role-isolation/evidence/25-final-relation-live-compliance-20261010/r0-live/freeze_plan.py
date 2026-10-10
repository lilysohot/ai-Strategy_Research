"""Freeze the final relation boolean-v2 live plan without model calls."""

from __future__ import annotations

import hashlib
import json
import os
import tempfile
from contextlib import suppress
from pathlib import Path

from plugins.corpus.material_semantics import MaterialRun
from plugins.corpus.structured.config import RequestOptions, load_extraction_config
from plugins.corpus.structured.ledger import AcceptedMaterialItems, plan_batch
from plugins.corpus.structured.roles import RoleArtifact
from plugins.corpus.structured.snapshot import EvidenceSnapshot

ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
CLAIMS = ROOT / ".scratch" / "claims-r2-role-isolation"
EVIDENCE = CLAIMS / "evidence"
P12 = EVIDENCE / "18-material-extractor-replacement-20261009" / "p12-relation-selector-v2-zero-call"
ISSUE22 = EVIDENCE / "22-doubao-lite-provider-ceiling-20261010" / "p0-256k-minimal-live"
ISSUE23 = EVIDENCE / "23-relation-adjudication-correction-20261010" / "r0-zero-call"
SNAPSHOT = (
    EVIDENCE
    / "17-structured-extraction-convergence-closure-20261009"
    / "p1-plan-freeze"
    / "copper-items-relations"
    / "snapshot.json"
)


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".pending", dir=path.parent
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as stream:
            stream.write(content)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        with suppress(FileNotFoundError):
            os.unlink(temporary)


def _sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def request_options() -> RequestOptions:
    return RequestOptions(
        timeout_seconds=300.0,
        max_output_tokens=262144,
        token_parameter="max_tokens",
        reasoning_effort="minimal",
    )


def main() -> None:
    snapshot = EvidenceSnapshot.model_validate_json(SNAPSHOT.read_text(encoding="utf-8"))
    snapshot.verify_identity()
    imported = AcceptedMaterialItems(
        artifact=RoleArtifact.model_validate_json(
            (P12 / "accepted-items-artifact.json").read_text(encoding="utf-8")
        ),
        payload=MaterialRun.model_validate_json(
            (P12 / "accepted-items-payload.json").read_text(encoding="utf-8")
        ),
    )
    gold = json.loads((ISSUE23 / "gold-v2.agent-draft.json").read_text(encoding="utf-8"))
    if (
        gold.get("status") != "human_signed"
        or gold.get("signoff", {}).get("name") != "xyl"
        or gold.get("eligible_case_count") != 38
    ):
        raise RuntimeError("signed gold-v2 identity is unavailable")
    config = load_extraction_config(dotenv_path=ROOT / ".env", options=request_options())
    profile = config.require_profile()
    if profile.model != "doubao-seed-2.1-lite":
        raise RuntimeError("doubao-seed-2.1-lite is not the configured extraction model")
    plan = plan_batch(
        snapshot,
        config=config,
        max_attempts=4,
        role_max_attempts={"claims": 0, "material_items": 0, "material_relations": 4},
        relations_enabled=True,
        max_relation_tasks=1,
        max_relation_attempts=4,
        relation_dependency_policy="complete_parent",
        enabled_roles=("material_items", "material_relations"),
        material_items_protocol="material-atomic-selector-jsonl-v5",
        material_relations_protocol="material-relations-question-group-jsonl-v2",
        imported_material_items=imported,
    )
    plan.verify_identity()
    gate = {
        "schema_version": "relation-question-group-boolean-final-gate-1",
        "created_on": "2026-10-10",
        "status": "frozen_before_execution",
        "protocol": "material-relations-question-group-jsonl-v2",
        "source_sample_id": gold["source_sample_id"],
        "candidate_set_id": gold["candidate_set_id"],
        "gold_v2_sha256": _sha256(ISSUE23 / "gold-v2.agent-draft.json"),
        "execution_requirements": {
            "claims_attempts": 0,
            "items_attempts": 0,
            "relation_attempts_max": 4,
            "automatic_retries": 0,
            "expected_relation_packets": 4,
            "completed_packets_min": 4,
            "partial_packets_max": 0,
            "failed_packets_max": 0,
            "missing_duplicate_invalid_max": 0,
        },
        "quality_requirements": {
            "signed_cases_total": 38,
            "signed_cases_correct_min": 35,
            "known_error_cases_total": 9,
            "known_error_cases_correct_min": 7,
            "previously_correct_cases_total": 29,
            "previously_correct_regressions_max": 2,
            "target_relations_total": 4,
            "target_relations_matched_min": 4,
            "supports_conditions_regressions_max": 0,
        },
        "target_groups": [
            {
                "gold_relation": "dec-answer-capex-relation",
                "candidate_pair_ids": ["pair_82e38a002735f044"],
            },
            {
                "gold_relation": "dec-answer-yield-relation",
                "candidate_pair_ids": [
                    "pair_1d4865edce7c70e5",
                    "pair_2c4fe7749a0e9dbb",
                    "pair_bb4f5d074a054e75",
                    "pair_bfa03df7eea2a12a",
                ],
            },
            {
                "gold_relation": "dec-quoted-yield-support",
                "candidate_pair_ids": ["pair_e0122f78caaf1a43"],
            },
            {
                "gold_relation": "dec-answer-mitsui-relation",
                "candidate_pair_ids": ["pair_9ac292fbb05063a7", "pair_ad507c2bfb7a7872"],
            },
        ],
        "scope_constraints": {
            "new_gold_allowed": False,
            "candidate_rule_change_allowed": False,
            "items_change_allowed": False,
            "prompt_revision_after_execution_allowed": False,
            "publication_authorized": False,
            "query_delivery_context_use_authorized": False,
        },
        "terminal_decision": {
            "on_pass": "close relation extractor repair; no additional extraction calls",
            "on_fail": "close current model plus extractor route; no prompt or threshold relaxation",
        },
    }
    _atomic_write(HERE / "plan.json", plan.model_dump_json(indent=2))
    _atomic_write(HERE / "final-gate.json", json.dumps(gate, ensure_ascii=False, indent=2))
    manifest = {
        "schema_version": "issue25-final-live-freeze-manifest-1",
        "created_on": "2026-10-10",
        "status": "frozen_not_executed",
        "batch_id": plan.batch_id,
        "plan_sha256": plan.plan_sha256,
        "files_sha256": {
            "plan.json": _sha256(HERE / "plan.json"),
            "final-gate.json": _sha256(HERE / "final-gate.json"),
        },
        "model_requests_during_freeze": 0,
        "authorized_relation_attempts_max": 4,
    }
    _atomic_write(HERE / "freeze-manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
    print(
        json.dumps(
            {
                "batch_id": plan.batch_id,
                "plan_sha256": plan.plan_sha256,
                "snapshot_id": plan.snapshot.snapshot_id,
                "model": profile.model,
                "max_output_tokens": profile.options.max_output_tokens,
                "reasoning_effort": profile.options.reasoning_effort,
                "protocol": "material-relations-question-group-jsonl-v2",
                "model_requests": 0,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
