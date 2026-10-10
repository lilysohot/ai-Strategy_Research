"""Freeze the authorized GLM 16K plan without making model requests."""

from __future__ import annotations

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
EVIDENCE = HERE.parents[1]
P12 = EVIDENCE / "18-material-extractor-replacement-20261009" / "p12-relation-selector-v2-zero-call"
SNAPSHOT = (
    EVIDENCE
    / "17-structured-extraction-convergence-closure-20261009"
    / "p1-plan-freeze"
    / "copper-items-relations"
    / "snapshot.json"
)


def _write_plan(path: Path, content: str) -> None:
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
    config = load_extraction_config(
        dotenv_path=ROOT / ".env",
        options=RequestOptions(
            timeout_seconds=300.0,
            max_output_tokens=16384,
            token_parameter="max_tokens",
        ),
    )
    if config.require_profile().model != "glm-5.3-flash":
        raise RuntimeError("glm-5.3-flash is not the configured extraction model")
    plan = plan_batch(
        snapshot,
        config=config,
        max_attempts=4,
        role_max_attempts={
            "claims": 0,
            "material_items": 0,
            "material_relations": 4,
        },
        relations_enabled=True,
        max_relation_tasks=1,
        max_relation_attempts=4,
        relation_dependency_policy="complete_parent",
        enabled_roles=("material_items", "material_relations"),
        material_items_protocol="material-atomic-selector-jsonl-v5",
        material_relations_protocol="material-relations-question-group-jsonl-v1",
        imported_material_items=imported,
    )
    plan.verify_identity()
    _write_plan(HERE / "plan.json", plan.model_dump_json(indent=2))
    print(
        {
            "batch_id": plan.batch_id,
            "plan_sha256": plan.plan_sha256,
            "snapshot_id": plan.snapshot.snapshot_id,
            "model": config.require_profile().model,
            "max_output_tokens": 16384,
            "model_requests": 0,
        }
    )


if __name__ == "__main__":
    main()
