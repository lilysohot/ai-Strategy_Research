"""Independent I1-9 acceptance: frozen fixture quality gate and release evidence.

No original fixtures, production code, or historical assertions are modified.
"""

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from plugins.corpus.preparation.admission import AdmissionPolicy, POLICY_REV_V1
from plugins.corpus.preparation.contract import (
    LeaseConfig, ResearchDomain, ReviewedDecision, ReviewDecision, source_id_from_bytes,
)
from plugins.corpus.preparation.engine import (
    EngineError, PlanEntry, execute_builds, plan_builds, publish_build,
)
from plugins.corpus.preparation.repository import MemoryStore, StoreError

ROOT = Path(__file__).resolve().parents[5]
FIXTURES = ROOT / "tests/fixtures/corpus_preparation"
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
NOW = datetime(2026, 9, 16, 12, tzinfo=UTC)
POLICY = AdmissionPolicy(POLICY_REV_V1, tuple(ResearchDomain))


def prepare(tmp_path, suffix):
    path = FIXTURES / f"synthetic-company-report.{suffix}"
    store = MemoryStore(clock=lambda: NOW)
    source_id = source_id_from_bytes(path.read_bytes())
    store.put_reviewed_decision(ReviewedDecision(
        "r1", source_id, "synthetic-reviewer", NOW,
        ReviewDecision.ADMITTED, "synthetic whole-source admission, no quality waiver",
    ))
    plan = plan_builds([PlanEntry(
        str(path), domain_hint=ResearchDomain.COMPANY, review_decision_ids=("r1",),
    )], policy=POLICY)
    outcome = execute_builds(
        store, plan, policy=POLICY, archive_root=tmp_path / "archive",
        owner_id="i1-9-audit", now=NOW, lease=LeaseConfig(300, 60, 600, 3),
    ).outcomes[0]
    return store, outcome


def test_frozen_pdf_with_unresolved_gaps_cannot_publish(tmp_path):
    store, outcome = prepare(tmp_path, "pdf")
    assert outcome.build is not None
    quality = json.loads(outcome.build.quality_report)
    assert quality["gap_regions"], "fixture must actually exercise unresolved quality"
    assert any("image_only_page" in gap for gap in quality["gap_regions"])
    with pytest.raises((EngineError, StoreError)):
        publish_build(store, outcome.build.build_id, activated_at=NOW)


def test_control_clean_md_can_exercise_generation_independently(tmp_path):
    store, outcome = prepare(tmp_path, "md")
    assert outcome.build is not None
    quality = json.loads(outcome.build.quality_report)
    assert quality == {"gap_regions": [], "oversized_chunks": []}
    first = publish_build(store, outcome.build.build_id, activated_at=NOW)
    assert publish_build(store, outcome.build.build_id, activated_at=NOW) == first
    second = publish_build(
        store, outcome.build.build_id, activated_at=NOW + timedelta(seconds=1),
    )
    assert (first.generation, second.generation) == (1, 2)


def test_acceptance_freeze_does_not_omit_latest_known_chain_tests():
    """Acceptance completeness, not a demand to rewrite the historical r1 snapshot."""
    freeze = json.loads((BASE / "freezes/i1-r1.json").read_text(encoding="utf-8"))
    bound = {path for group in freeze["binding"].values() for path in group}
    required = (
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/"
        "20260916-i1-full-review/test_chain_contracts.py"
    )
    assert required in bound, "i1-r1 cannot be release evidence: latest 11 chain tests omitted"
