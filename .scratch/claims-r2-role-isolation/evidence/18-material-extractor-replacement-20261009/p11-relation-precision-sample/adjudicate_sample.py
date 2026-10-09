"""Apply the agent's review to the frozen P11 sample and compute draft metrics."""

from __future__ import annotations

import json
import math
from collections import defaultdict
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent

# Decisions are intentionally keyed by immutable controller-owned pair identity.
DECISIONS: dict[str, tuple[str, str]] = {
    # P10 present predictions: accept means the typed edge is explicit.
    "pair_c8a2e609d0bf69ac": ("reject", "The pricing-ambition atom does not answer which foil thickness will be expanded."),
    "pair_656be2399f54e209": ("accept", "The reply explicitly confirms that carrier copper foil is different."),
    "pair_75e57fa1a91444d1": ("accept", "The reply directly begins the requested explanation of carrier foil."),
    "pair_5956d4ff0f239792": ("reject", "The atom compares technical requirements but does not answer the 3 versus 4.5 hundred-million value question."),
    "pair_948115917d484326": ("accept", "The reply explicitly says expansion will target ultra-thin foil."),
    "pair_accf55e14399b995": ("accept", "The because-clause explicitly supports the whole-solution and external-procurement statement."),
    "pair_867bb55010d3409f": ("accept", "The because-clause explicitly justifies using lower-cost, lower-precision control for thicker foil."),
    "pair_0fe2596533c9062c": ("accept", "Existing supply and thinner new demand explicitly support not expanding 6–8 micrometre output."),
    "pair_7ebcec23ea283bfd": ("accept", "The stated process difficulty explicitly supports the higher equipment price."),
    "pair_1a9d24af1bf7107f": ("reject", "Replacement frequency alone does not answer the requested next-year revenue scale."),
    "pair_e30e95a14e98a666": ("accept", "The affirmative reply explicitly answers the caller's confirmation question."),
    "pair_99ad745a830b3057": ("reject", "Accompanying the customer during testing explains payment uncertainty but does not itself answer delivery timing."),
    "pair_dc4f0640ec6b4b11": ("reject", "Low Japanese expansion intent supports low external sourcing probability but is not itself an answer to make-versus-buy."),
    "pair_b017f3137cc2221f": ("accept", "The signed volume and annual capacity directly evidence the requested industry recovery."),
    "pair_cd8df0324de3133f": ("accept", "The HVLP customer condition explicitly supports why full acceptance payment may not arrive."),
    "pair_1d89be203265a027": ("accept", "In-house development explicitly supports the claim that Mitsui will not buy the machine externally."),
    "pair_05ccd9efcd925fec": ("accept", "Low expansion intent explicitly supports low external procurement probability."),
    "pair_98a33a34ca0f5047": ("accept", "The availability of larger sizes explicitly supports a higher possible price."),
    "pair_ef91d55f1e0d8c3b": ("accept", "Customer uncertainty explicitly supports uniform pricing."),
    "pair_e0122f78caaf1a43": ("accept", "The quoted 60/40 process-equipment split explicitly supports the process-driven conclusion."),
    "pair_681736d2478dab48": ("accept", "The but-clause explicitly counters the lack-of-validation qualification."),
    "pair_17b50dc36d3bd69e": ("accept", "The if-clause is an explicit condition for gaining the advantage."),
    "pair_3e579daa7d92e267": ("accept", "Successful validation is an explicit condition for market capture."),
    "pair_b95e823f9f6d51d9": ("accept", "The immediately following reply explicitly answers what the stated standard means in capacity terms."),
    "pair_82e38a002735f044": ("accept", "The reply directly gives lithium-foil equipment capex per ten thousand tonnes."),
    "pair_741c3dce009fa24b": ("accept", "The range elaboration directly answers the capex question."),
    "pair_a93079679e270f02": ("accept", "The but-clause explicitly contrasts the good-margin price with the current-market price."),
    "pair_20e579667066bca6": ("accept", "The but-clause explicitly contrasts similar front-end equipment with the additional back-end machine."),
    "pair_f88743227fb48b8b": ("accept", "Delayed acceptance payments explicitly qualify the forecast of sharply higher annual revenue."),
    "pair_421fb2d822b8dc15": ("accept", "The but-clause explicitly qualifies leading equipment precision with process-driven yield."),
    "pair_907f2c22d4ddec7a": ("accept", "Different equipment requirements explicitly support splitting capex by foil type."),
    "pair_71d4c1fe205c3723": ("accept", "The need to produce electrolyte explicitly supports the need for front-end dissolution equipment."),
    # P10 absent decisions: overturn means an explicit edge was missed.
    "pair_af4a1d9299403d27": ("accept", "Capacity and product mix are compatible facts; no challenge is expressed."),
    "pair_4adac65ac8099417": ("accept", "Being above 6–8 and below sub-3.5 requirements is compatible, not a challenge."),
    "pair_0cc897a5c1f55daf": ("accept", "Delivery completion and receipt of all acceptance payments are distinct claims."),
    "pair_1f74637d78897251": ("accept", "A good historical period and a better future period are compatible."),
    "pair_535c3958c2f89841": ("accept", "Domestic procurement preference does not answer whether the named foreign suppliers stopped HTE."),
    "pair_d7b6eabfa488078d": ("accept", "The target atom is an underspecified fragment, so the criticism cannot bind to it as an atomic answer."),
    "pair_4f11ea4b329aa628": ("overturn", "The reply explicitly lists global suppliers in direct answer to the global-landscape question."),
    "pair_c47aa4dc2cd74bc3": ("overturn", "The speaker explicitly challenges their own preceding machining-versus-control assumption."),
    "pair_f483497489fe4b6e": ("accept", "The foreign firms' non-expansion does not support the separate claim about Chinese labour and assembly."),
    "pair_603d2b449da00930": ("overturn", "The reply directly corrects the question's false premise about an anode-plated cathode roller."),
    "pair_1b5d94210a126af9": ("overturn", "The amount explicitly supplies the value component of the question about the remaining capex."),
    "pair_c513a3e6c490fa9a": ("accept", "Low processing fees explain acceleration, not the composition of one machine set."),
}


def _write(name: str, value: object) -> None:
    (HERE / name).write_text(
        json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def main() -> None:
    sample = json.loads((HERE / "sample-plan.json").read_text(encoding="utf-8"))
    sampled = sample["precision_sample"] + sample["recall_sentinel_sample"]
    sampled_ids = {row["candidate_pair_id"] for row in sampled}
    if sampled_ids != set(DECISIONS):
        raise RuntimeError(
            f"decision identity mismatch missing={sorted(sampled_ids - set(DECISIONS))} "
            f"extra={sorted(set(DECISIONS) - sampled_ids)}"
        )

    precision_decisions = []
    sentinel_decisions = []
    by_stratum: dict[tuple[str, str], list[bool]] = defaultdict(list)
    for row in sample["precision_sample"]:
        decision, reason = DECISIONS[row["candidate_pair_id"]]
        correct = decision == "accept"
        by_stratum[(row["packet_id"], row["allowed_type"])].append(correct)
        precision_decisions.append(
            {
                "candidate_pair_id": row["candidate_pair_id"],
                "agent_decision": "accept_present" if correct else "reject_false_positive",
                "reason": reason,
                "human_decision": None,
            }
        )
    for row in sample["recall_sentinel_sample"]:
        decision, reason = DECISIONS[row["candidate_pair_id"]]
        sentinel_decisions.append(
            {
                "candidate_pair_id": row["candidate_pair_id"],
                "agent_decision": (
                    "accept_absent" if decision == "accept" else "overturn_false_negative"
                ),
                "reason": reason,
                "human_decision": None,
            }
        )

    present_strata = {
        (row["packet_id"], row["allowed_type"]): row
        for row in sample["strata"]
        if row["selector_decision"] == "present"
    }
    estimated_correct = 0.0
    variance_total = 0.0
    estimates = []
    for key, decisions in sorted(by_stratum.items()):
        stratum = present_strata[key]
        population = stratum["universe_count"]
        sample_count = len(decisions)
        accepted = sum(decisions)
        proportion = accepted / sample_count
        expanded_correct = population * proportion
        estimated_correct += expanded_correct
        if sample_count > 1 and sample_count < population:
            sample_variance = (
                sum((int(value) - proportion) ** 2 for value in decisions)
                / (sample_count - 1)
            )
            variance_total += (
                population**2
                * (1 - sample_count / population)
                * sample_variance
                / sample_count
            )
        estimates.append(
            {
                "packet_id": key[0],
                "allowed_type": key[1],
                "population": population,
                "sample": sample_count,
                "accepted": accepted,
                "sample_acceptance": proportion,
                "expanded_correct": expanded_correct,
            }
        )
    population_total = sample["counts"]["present_universe"]
    estimate = estimated_correct / population_total
    standard_error = math.sqrt(variance_total) / population_total
    normal_low = max(0.0, estimate - 1.96 * standard_error)
    normal_high = min(1.0, estimate + 1.96 * standard_error)

    draft = {
        "schema_version": "relation-adjudication-draft-1",
        "sample_id": sample["sample_id"],
        "status": "agent_draft_unsigned",
        "human_signoff_required": True,
        "adjudication_rule": {
            "present": "accept only when the typed relation is explicit in the frozen pair window",
            "absent": "accept when no typed relation is explicit; absent rows are recall sentinels only",
            "endpoint_rule": "judge the atomic endpoint texts, not topical co-occurrence alone",
        },
        "precision_decisions": precision_decisions,
        "recall_sentinel_decisions": sentinel_decisions,
        "signoff": {
            "required": True,
            "name": None,
            "signed_at": None,
            "authorization": None,
        },
    }
    evaluation: dict[str, Any] = {
        "schema_version": "relation-precision-agent-estimate-1",
        "sample_id": sample["sample_id"],
        "status": "agent_draft_not_a_quality_gate",
        "precision": {
            "present_population": population_total,
            "sample_size": len(sample["precision_sample"]),
            "sample_correct": sum(
                decision["agent_decision"] == "accept_present"
                for decision in precision_decisions
            ),
            "unweighted_sample_acceptance": sum(
                decision["agent_decision"] == "accept_present"
                for decision in precision_decisions
            )
            / len(precision_decisions),
            "stratified_estimated_correct": estimated_correct,
            "stratified_precision_estimate": estimate,
            "estimated_standard_error": standard_error,
            "normal_95_interval_diagnostic": [normal_low, normal_high],
            "strata": estimates,
            "interpretation": (
                "Directional estimate only: the interval is too wide for a release gate, and "
                "all labels remain an unsigned agent draft."
            ),
        },
        "recall_sentinels": {
            "sample_size": len(sample["recall_sentinel_sample"]),
            "false_negatives": sum(
                decision["agent_decision"] == "overturn_false_negative"
                for decision in sentinel_decisions
            ),
            "rate_is_not_recall": True,
            "interpretation": (
                "The sentinel sample is not probability-weighted for recall. Any overturned row "
                "is a concrete missed edge, but the count must not be reported as document recall."
            ),
        },
        "observed_failure_modes": [
            {
                "code": "answer_topic_drift",
                "example_pair_ids": [
                    "pair_c8a2e609d0bf69ac",
                    "pair_dc4f0640ec6b4b11",
                ],
                "implication": "turn-level adjacency is insufficient; the answer atom must resolve the question predicate",
            },
            {
                "code": "partial_answer_bound_as_full_answer",
                "example_pair_ids": [
                    "pair_5956d4ff0f239792",
                    "pair_1a9d24af1bf7107f",
                    "pair_99ad745a830b3057",
                ],
                "implication": "the selector needs an explicit complete-or-directly-responsive answer test",
            },
            {
                "code": "selector_false_negative_on_direct_reply_or_self_correction",
                "example_pair_ids": [
                    "pair_4f11ea4b329aa628",
                    "pair_c47aa4dc2cd74bc3",
                    "pair_603d2b449da00930",
                    "pair_1b5d94210a126af9",
                ],
                "implication": "prompt examples should cover list answers, premise correction, and atomic value answers",
            },
        ],
        "recommended_next_step": (
            "Do not spend another live call. First add zero-call candidate/selector rules and regression "
            "fixtures for these failure modes, then replay the immutable P10 decisions where possible."
        ),
        "publication_query_delivery_context_use": 0,
    }
    _write("candidate-adjudications.agent-draft.json", draft)
    _write("evaluation-summary.agent-draft.json", evaluation)
    print(json.dumps(evaluation, ensure_ascii=False))


if __name__ == "__main__":
    main()
