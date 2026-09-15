"""Offline-only adapter: require runtime audit proof before creating P2-A input.

Production must never import this file, the old evaluator or scratch plan types.
No semantic fields, gold decisions or missing wire data are synthesized here.
"""

from dataclasses import asdict

import p1_planner_spec as old
import r2_evaluation_v1 as evaluation

from plugins.corpus import _r2_runtime as runtime
from plugins.corpus._r2_audit import AuditSnapshot


def project(
    prepared: runtime.Prepared,
    result: runtime.RunResult,
    snapshot: AuditSnapshot,
    *,
    expected_audit_sha: str,
    expected_result_sha: str,
) -> tuple[old.Source, old.Plan, evaluation.Result]:
    report = runtime.validate(
        prepared,
        result,
        snapshot,
        expected_audit_sha=expected_audit_sha,
        expected_result_sha=expected_result_sha,
    )
    if prepared.task != "items":
        raise ValueError("item_projection_only")
    source = old.Source(
        prepared.source.evidence_run_id,
        prepared.source.source_rev,
        prepared.source.parse_rev,
        tuple(old.Packet(**asdict(p)) for p in prepared.source.packets),
    )
    plan = old.prepare(
        source,
        old.source_binding(source),
        tuple(old.Scope(**asdict(s)) for s in prepared.plan.scopes),
        old.Limits(**asdict(prepared.plan.limits)),
    )
    if asdict(plan) != asdict(prepared.plan):
        raise ValueError("planner_projection_drift")
    records = tuple(
        evaluation.Record.model_validate_json(r.model_dump_json()) for r in result.records
    )
    projected = evaluation.Result(
        protocol_version=evaluation.PROTOCOL,
        plan_id=plan.plan_id,
        result_id="",
        records=records,
        protocol_errors=result.errors,
        audit_complete=report.audit_complete,
    )
    return source, plan, evaluation.seal_result(projected)
