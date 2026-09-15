"""Financial calculations with explicit, versioned evidence inputs."""

from __future__ import annotations

import re
from collections import Counter
from decimal import Decimal
from typing import Any

from pydantic import BaseModel, ConfigDict

from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import (
    EvidenceFact,
    EvidenceRun,
    duplicate_fact_ids,
    validation_is_current,
)

FORMULA_VERSION = "corpus-financial-formulas-1"
RECIPES = {
    "revenue_growth": ("revenue", "revenue"),
    "parent_profit_growth": ("parent_net_profit", "parent_net_profit"),
    "operating_cash_growth": ("operating_cash_flow", "operating_cash_flow"),
    "cash_profit_ratio": ("operating_cash_flow", "parent_net_profit"),
    "net_margin": ("net_profit", "revenue"),
    "balance_residual": ("assets", "liabilities", "equity"),
    "profit_residual": ("net_profit", "parent_net_profit", "minority_profit"),
}


class Calculation(BaseModel):
    model_config = ConfigDict(frozen=True)
    calculation_id: str
    formula: str
    computed_by: str = FORMULA_VERSION
    run_id: str
    inputs: tuple[str, ...]
    input_values: tuple[Decimal, ...]
    value: Decimal
    unit: str
    basis: str
    period: str


def derive(run: EvidenceRun, formula: str, input_ids: tuple[str, ...]) -> Calculation:
    """Refuse missing, conflicting or dimensionally incompatible inputs before arithmetic.

    Growth inputs are current/previous; ratios numerator/denominator; residuals
    total/part1/part2. Cross-source model mixing is not implicitly permitted.
    """
    run.verify_identity()
    if not validation_is_current(run):
        raise ValueError("validation_version_stale")
    if duplicate_fact_ids(run):
        raise ValueError("duplicate_fact_ids")
    if formula not in RECIPES:
        raise ValueError("unsupported_formula")
    by_id = {f.fact_id: f for f in run.facts}
    try:
        inputs = [by_id[i] for i in input_ids]
    except KeyError as exc:
        raise ValueError("unknown_fact") from exc
    if len(set(input_ids)) != len(input_ids):
        raise ValueError("duplicate_inputs")
    if tuple(f.metric_id for f in inputs) != RECIPES[formula]:
        raise ValueError("metric_mismatch")
    if any("calculate" not in f.usable_for for f in inputs):
        raise ValueError("input_not_calculation_ready")
    claims = [f.claim for f in inputs]
    if len({c.subject for c in claims}) != 1:
        raise ValueError("subject_mismatch")
    if len({(c.doc_id, c.source_rev) for c in claims}) != 1:
        raise ValueError("source_revision_mismatch")
    if len({c.unit for c in claims}) != 1:
        raise ValueError("unit_mismatch")
    if len({(c.period_grain, tuple(sorted(c.qualifiers.items()))) for c in claims}) != 1:
        raise ValueError("basis_mismatch")
    values = tuple(c.value_num for c in claims if c.value_num is not None)
    if len(values) != len(claims):
        raise ValueError("missing_value")
    if formula.endswith("_growth"):
        current, previous = claims
        if current.period_grain != "annual" or not current.period_end or not previous.period_end:
            raise ValueError("growth_requires_annual_periods")
        if int(current.period_end[:4]) != int(previous.period_end[:4]) + 1:
            raise ValueError("growth_requires_consecutive_periods")
        if values[1] <= 0:
            raise ValueError("growth_base_nonpositive")
        value, unit = (values[0] / values[1] - 1) * 100, "%"
    else:
        if len({(c.period_end, c.kind) for c in claims}) != 1:
            raise ValueError("period_or_kind_mismatch")
        if formula.endswith("_residual"):
            value, unit = values[0] - sum(values[1:]), str(claims[0].unit)
        else:
            if values[1] == 0:
                raise ValueError("zero_denominator")
            value, unit = values[0] / values[1] * 100, "%"
    return Calculation(
        calculation_id=fingerprint([run.run_id, FORMULA_VERSION, formula, input_ids]),
        formula=formula,
        run_id=run.run_id,
        inputs=input_ids,
        input_values=values,
        value=value,
        unit=unit,
        basis="source_forecast" if any(c.kind == "forecast" for c in claims) else "source_reported",
        period=str(claims[0].period_end),
    )


def reconcile_net_margin(run: EvidenceRun) -> list[dict[str, Any]]:
    """Compare source ratios to an explicit candidate formula, never infer its definition.

    This is read-only review, including historical runs. Agreement within display
    precision is not proof of the author's accounting basis or computation permission.
    Missing/ambiguous inputs remain unverifiable; do not choose a nearby number.
    """
    run.verify_identity()
    duplicate_ids = any(n > 1 for n in Counter(f.fact_id for f in run.facts).values())

    def coordinates(fact: EvidenceFact) -> tuple[object, ...]:
        c = fact.claim
        return (
            c.doc_id,
            c.source_rev,
            c.scope,
            c.subject,
            c.period_end,
            c.period_grain,
            c.kind,
            tuple(sorted(c.qualifiers.items())),
        )

    def reference(fact: EvidenceFact) -> dict[str, object]:
        c = fact.claim
        return {
            "fact_id": fact.fact_id,
            "packet_id": fact.packet_id,
            "locator": c.locator,
            "metric_raw": c.metric_raw,
            "value_text": c.value_text,
            "unit_raw": c.unit_raw,
            "table_ref": c.table_ref,
            "evidence_quote": c.evidence_quote,
        }

    results = []
    for source in run.facts:
        if source.metric_id != "net_margin":
            continue
        c = source.claim
        row: dict[str, Any] = {
            "review_version": "net-margin-review-1",
            "run_id": run.run_id,
            "metric": "net_margin",
            "period": c.period_raw,
            "source_fact_id": source.fact_id,
            "source_value": str(c.value_num),
            "source": reference(source),
            "definition_verified": False,
            "source_usable_for": [p for p in source.usable_for if p == "cite"],
            "status": "unverifiable",
        }
        try:
            if duplicate_ids:
                raise ValueError("duplicate_fact_ids")
            if c.quality_status != "ok" or c.value_num is None or c.unit != "%":
                raise ValueError("source_ratio_not_validated")
            if not c.period_end or not c.subject:
                raise ValueError("source_coordinate_missing")

            def one(metric: str, source: EvidenceFact = source) -> EvidenceFact:
                matches = [
                    f
                    for f in run.facts
                    if f.metric_id == metric and coordinates(f) == coordinates(source)
                ]
                if len(matches) != 1:
                    raise ValueError(f"missing_or_ambiguous:{metric}")
                return matches[0]

            profit, revenue = one("net_profit"), one("revenue")
            calculation = derive(run, "net_margin", (profit.fact_id, revenue.fact_id))
            raw_number = re.search(r"[+-]?\d[\d,]*(?:\.\d+)?", c.value_text or "")
            if raw_number is None:
                raise ValueError("source_display_precision_missing")
            displayed = Decimal(raw_number[0].replace(",", ""))
            tolerance = Decimal(10) ** int(displayed.as_tuple().exponent) / 2
            delta = calculation.value - c.value_num
            row.update(
                candidate_definition=f"{profit.claim.metric}/{revenue.claim.metric}*100",
                input_fact_ids=list(calculation.inputs),
                input_evidence=[reference(profit), reference(revenue)],
                calculation=calculation.model_dump(mode="json"),
                derived_value=str(calculation.value),
                difference_percentage_points=str(delta),
                tolerance_percentage_points=str(tolerance),
                status="consistent_with_candidate_definition"
                if abs(delta) <= tolerance
                else "review_definition_or_source",
            )
            # A sensitivity calculation only, not an observed or substituted denominator.
            if c.value_num > 0 and profit.claim.value_num is not None:
                row["implied_denominator_not_source_data"] = str(
                    profit.claim.value_num / (c.value_num / 100)
                )
            try:
                parent, minority = one("parent_net_profit"), one("minority_profit")
                residual = derive(
                    run,
                    "profit_residual",
                    (profit.fact_id, parent.fact_id, minority.fact_id),
                )
                row["profit_residual"] = str(residual.value)
                row["profit_residual_calculation"] = residual.model_dump(mode="json")
                if parent.claim.value_num is not None and revenue.claim.value_num:
                    row["parent_profit_ratio_candidate"] = str(
                        parent.claim.value_num / revenue.claim.value_num * 100
                    )
            except ValueError as exc:
                row["profit_residual_unavailable"] = str(exc)
        except ValueError as exc:
            row["reason"] = str(exc)
        results.append(row)
    return results
