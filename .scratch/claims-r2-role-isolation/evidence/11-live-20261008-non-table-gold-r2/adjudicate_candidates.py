"""Build a complete, reviewable candidate adjudication draft without model calls.

This is deliberately an agent-assisted draft.  It never claims the human reviewer
field used by the frozen gold, never mutates the execution stores, and never
publishes a semantic artifact.  A named human must sign or amend every terminal
decision before this can satisfy the human gate in the scoring contract.
"""

from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import Any

from plugins.corpus.structured.query import query_semantic

HERE = Path(__file__).resolve().parent
EVIDENCE = HERE.parent
GOLD = EVIDENCE / "10-quality-gold-freeze-20261008-r2" / "frozen-gold.json"

OUTPUT = HERE / "candidate-adjudications.agent-draft.json"
COVERAGE = HERE / "coverage-observations.agent-draft.json"
SUMMARY = HERE / "candidate-adjudication-summary.agent-draft.md"
MANIFEST = HERE / "adjudication-manifest.agent-draft.json"

SOURCES = {
    "industrial-fulian-md": {
        "source_id": "sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb",
        "build_id": "f16e7fde95537f0656a69cb1547232ca26a0347b3823d0dc1844dbf798149314",
        "claims_payload": "9333dce5601beff301436f6116319226679324e497ec7eb77ea94a7c40ff2c5e",
        "items_payload": "46be8e9e4607a79b699ce572f84b88b8c1de929c80775410b736a04fc81f7008",
    },
    "optical-module-docx": {
        "source_id": "sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f",
        "build_id": "dca4bad7f85b59dce0110ef15037b34223163b88c06685bcae4764e5f700ab96",
        "claims_payload": "b4f923669cf9603e737bfaac2af15933dda97540c984aca73ba48efd161001d0",
        "items_payload": "9a25e2a40a5cd25d2717cfd39a3ebd689edb1813441b2148f7ed37c5d3866f5d",
    },
}

# Human-equivalence suggestions after reading every candidate beside its exact
# source quote.  These are suggestions, not a human signature.  Records omitted
# from these terminal sets are explicitly emitted as ``incorrect`` below.
MATCHED = {
    # Industrial Claims: nine of ten frozen targets.
    "87f1ea03fb845a219e739da3f93e9c2040901bf10ee3991c643a748b0bac1b31": "NT-C09",
    "05852da1406640322e52b330be5b26dac9d0c75ef1ffe2e7cf5fe985106899f8": "NT-C10",
    "e5e36839e69ab078235ad4e54f3b93f673ed4639fe801ba842dda451fe3231b8": "NT-C04",
    "94d0597a38605a6ca507e6fc61f9df86b1aad5190a41c14f4864c080dd151a4f": "NT-C02",
    "046cdfb92834db6ec3681d0bb47c778b307d2ed2cd3145e857d90bc0abfe58cf": "NT-C05",
    "ce2182af37ff43fd4e584c8d6a4a5a1c1bf9667d67ba99b53f58262890af0901": "NT-C06",
    "44384dafbfca4e7af8e36c359db1ded11fb351ed7255d617ae0b99b6a104ee15": "NT-C07",
    "2c3382c25ce7ba7d1096916177c79186fbca4121d921aa950a15af5d21ce79b2": "NT-C08",
    "4f26ee356e75440470cfad883fc067bc3130c1b3b5bd09198990549bffebe06d": "NT-C01",
    # Optical-module Claims: challenged/early-estimate context is present in
    # the delivered source_context, so these may be matched after human review.
    "e5c4a3f8e7558166831195989a4cf0c98e0f99ce42c4fd30a01b73a1489a00f5": "NT-C16",
    "2aac24b72d83513c3fa801caab1af6d7a00b810af805c5aac081ab7169bcde0b": "NT-C17",
    "638633f0733f938beb49d6b25514558fee0535f368528eb00091a27a8a1a5a64": "NT-C18",
    "f75bed21cc98f275e12dbaedf54cd74c06cc344f9b598c43327657eca9da7cfa": "NT-C11",
    "671e67bc7d2c8a6fae97ac430467f1c82c05ceafb6e02a50e191294b9a07e5cc": "NT-C12",
    "2e43aab6e1ea4725d15be4defcdfd1ba40ce389052af506255eeaecd72215f93": "NT-C13",
    # Material items that preserve the frozen item's atomic semantics.
    "itm_da6e3b99b349574b": "NT-I41",
    "itm_eac8fbfb6f37958e": "NT-I44",
    "itm_8baf10c48f51ae02": "NT-I34",
    "itm_d8e0bddb391bb04a": "NT-I28",
}

CORRECT_EXTRA = {
    # Industrial Claims: faithful, atomic metric assertions outside the finite
    # target denominator.
    "0cd2dcface3551944ed2da63656b265d85bf4d04e6927cc37990f696f21bab8b",
    "eebc258845e6294e07c3934c49fb96366104ead3397864b594b32628f61c083c",
    "a70349f1e00753986b7406ccaf8bca6b4e83db37a649330f72ef7c1b464a2b86",
    "f682603abb32e6b3ebf584f2a897284e2f1ed118d7876055464f83ed17e08329",
    "4f2808dd69579be252f3f6d0e85484b038db4896205c83a658ea8ea7196edb49",
    "33f5fe07b49ba8fa0e297d6f5331f930ddac1cb24093890e0df454ccbb90937d",
    "843c107a1fd105fe95961430127cda4dbd404b1d29b909a81fa3ecadadd63d9c",
    "7d44398c985b0b861969cff61ee5421b64010b06ba297118c7c2d5775e1e3d6d",
    "21307ac108fc2556046e754167fdb521678e3654080a09ab8675d13710783961",
    "491b78b84c43a76379957f385cf74b4032a8e0e48571f6320cf27211a6693bda",
    "95b6d76a08feb26cdbab75f76a18039df7b8836b19967a096fefb760e24f4f55",
    "cddbf5e3d87b06b56ded2a31fc539483b80ba75f464b21f883c1431bea432fb0",
    "e88d3b67be4b79d47142cc0b455acc8cba1e564b966b27b1de21bdb67613d77f",
    "aa0e6f0b78e58ac458437a1d603a9bf916eedd066ac329a0f0835aa11674ceeb",
    "1a77d57d83d500a9210895f1ba1827c7455aa767f09133f02f4d98de623245bd",
    "7bea721cb386508d4582ff516c3eee0caf15b483c1afff8edc779965ff3e9824",
    "06992493ba1ea256b42db226da88e6149cb75934b0460ea8c266f4b5cd7aa72e",
    "f6e9153bbfd18494209b83a115609bd426de3c4c4273c04599a685a17d1e3502",
    "ef42a2a915e70ab83a0d61ad916352c288fafc59d2a0548a2b6020066d85d487",
    # Optical Claims: faithful numeric forecasts not selected into frozen gold.
    "78abf19c5fab95ee6c15966a6ccf8445b1bea38c2bd6b6d354f910d74bb35c0b",
    "36ad848a22331a9db066309459dfe5e5b06ddddba92962dd139f119f96b9c9bf",
    "21da10f2ecd353329fdfd8fd0028e03a4a0e31cc0bb8c6a98c2a6d505f33ea46",
    # Industrial material items.
    "itm_415046a74b6ab180",
    "itm_8aa77a288e28b184",
    "itm_1f0b6d4313403c32",
    "itm_1bc6fdb5a18a0036",
    "itm_0ca429ebf3323cf1",
    "itm_434b9fb72448647e",
    "itm_fc374f76e692cb1e",
    "itm_c50d791576b8a1b6",
    "itm_a158bc6c9eaf9820",
    "itm_b9971104007c6bd6",
    "itm_db59bc9aecb3de5e",
    "itm_e4da8103251ebc20",
    "itm_0a9e5ddce99cdf6d",
    "itm_e5b0aaf5608a8da3",
    "itm_7bc9710cf31d9fca",
    "itm_67f4eacb62e37f1c",
    "itm_c94fc066e714cd2c",
    "itm_2b36cdc96d19360b",
    "itm_f69007e6847141ff",
    "itm_906e0261d51bfd9a",
    "itm_e07dba546fb17702",
    "itm_05e025647604e38d",
    # Optical material items.
    "itm_db2c7728a1743d44",
    "itm_066dd672f2e72811",
    "itm_b8e04d327f2a68e8",
    "itm_f26d392feae528ec",
    "itm_c1f4a9045dee3b88",
    "itm_555a078a1657785e",
    "itm_dae489ec79918bf3",
    "itm_a7f2bdfbaa55639b",
    "itm_ad54c99fd5e68ad2",
    "itm_7973bc377c78d328",
    "itm_94243aa91bf537c6",
    "itm_7570f80ca759a46a",
    "itm_24275bb57706274b",
    "itm_00f693bbc8ae8ce6",
    "itm_eae3eccb828b5e06",
    "itm_dd7bdd5ad6d85884",
    "itm_eb6b32d183c19765",
    "itm_7bb87867795bd27b",
    "itm_187426bf9206306f",
    "itm_6e78b3e0d72d4855",
    "itm_d7d6686834aed53b",
    "itm_1098fddd9a3d09dc",
    "itm_60145c6ebaeb1693",
    "itm_00f3cf9ff7f32732",
    "itm_48e8cabaad56b0c9",
    "itm_76e4d936ba23ead7",
    "itm_baf51a391097965b",
    "itm_6bc7ce550d5e6f03",
    "itm_7ca7b3f8e9ca82a8",
    "itm_9033c495be2738f8",
    "itm_a3b72d3b1fb0ab9b",
    "itm_d0a69df10fadf83c",
    "itm_af016c02729f23c3",
    "itm_3720ae815b633ed4",
    "itm_23b240f9d4e44dbc",
    "itm_a418f77e63d21066",
    "itm_d8c421eb1ff82ca8",
    "itm_7113e5515d496dfa",
    "itm_5ee854e753c5d29b",
    "itm_13290648c20a364f",
    "itm_08e5aa27893109a3",
    "itm_b40d8eebc13dfd90",
    "itm_f320fabbf77c7373",
}

# Later exact repetition of the already accepted 2026-08-28 price proposition.
DUPLICATES = {
    "c3d96efdd46b8e25ac411981dffe53b286cab17eeb90ee651b97e30da5bdd676": "4f26ee356e75440470cfad883fc067bc3130c1b3b5bd09198990549bffebe06d",
    "itm_f555a9813590ff32": "itm_0ca429ebf3323cf1",
}


def load(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def object_path(slug: str, digest: str) -> Path:
    return HERE / slug / "store" / "objects" / "sha256" / digest[:2] / f"{digest}.json"


def claim_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    claim = candidate["claim"]
    return {
        "subject": claim.get("subject") or claim.get("subject_raw"),
        "metric": claim.get("metric") or claim.get("metric_raw"),
        "period": claim.get("period_end") or claim.get("period_raw"),
        "value": claim.get("value_num") or claim.get("value_text"),
        "unit": claim.get("unit") or claim.get("unit_raw"),
        "factuality": claim.get("kind"),
        "quality_status": claim.get("quality_status"),
        "reason_codes": candidate.get("reasons", []),
    }


def item_fields(candidate: dict[str, Any]) -> dict[str, Any]:
    return {
        key: candidate.get(key)
        for key in (
            "text",
            "semantic_type",
            "statement_role",
            "speech_role",
            "perspective",
            "speaker_ref",
            "polarity",
            "behavior_status",
            "temporal_frame",
            "unknown_fields",
        )
    }


def candidates() -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for slug, spec in SOURCES.items():
        claims = load(object_path(slug, spec["claims_payload"]))
        items = load(object_path(slug, spec["items_payload"]))
        for value in claims["facts"]:
            result.append(
                {
                    "candidate_id": value["fact_id"],
                    "role": "claims",
                    "source_slug": slug,
                    "source_id": spec["source_id"],
                    "original_candidate": value,
                    "observed_fields": claim_fields(value),
                    "evidence": value["evidence_alignment"]["source_spans"],
                }
            )
        for value in items["understanding"]["items"]:
            result.append(
                {
                    "candidate_id": value["item_id"],
                    "role": "material_items",
                    "source_slug": slug,
                    "source_id": spec["source_id"],
                    "original_candidate": value,
                    "observed_fields": item_fields(value),
                    "evidence": value["evidence"],
                }
            )
    return result


def decision(value: dict[str, Any], gold_by_id: dict[str, dict[str, Any]]) -> dict[str, Any]:
    candidate_id = value["candidate_id"]
    if candidate_id in MATCHED:
        gold_id = MATCHED[candidate_id]
        gold = gold_by_id[gold_id]
        judgement = "matched"
        reason = (
            "代理逐字核对建议：候选与冻结目标在原子命题和关键限定上语义等价；"
            "最终匹配仍须由具名人工审核人签认。"
        )
        canonical = gold["semantic_fields"]
    elif candidate_id in CORRECT_EXTRA:
        gold_id = None
        judgement = "correct_extra"
        reason = (
            "代理逐字核对建议：范围内额外原子命题忠实于引文，未占用冻结召回分母；"
            "最终正确性仍须人工签认。"
        )
        canonical = value["observed_fields"]
    elif candidate_id in DUPLICATES:
        gold_id = None
        judgement = "duplicate"
        reason = f"与较早候选 {DUPLICATES[candidate_id]} 表达同一命题，按契约计重复 FP。"
        canonical = value["observed_fields"]
    else:
        gold_id = None
        judgement = "incorrect"
        if value["role"] == "claims":
            details = value["observed_fields"].get("reason_codes", [])
            reason = (
                "严格 Claims 契约未满足：候选存在主体/指标/期间/值/单位/事实性/归属限定缺失或错误，"
                "或把纯观点、条件、复合命题送入 Claims；运行诊断=" + ",".join(details)
            )
        else:
            fields = value["observed_fields"]
            reason = (
                "严格 R2 items 契约未满足：该条不是一个完整原子命题，或 semantic_type/"
                f"statement_role/polarity/归属与原文不符；观测={fields.get('semantic_type')}/"
                f"{fields.get('statement_role')}/{fields.get('polarity')}。"
            )
        canonical = value["observed_fields"]
    return {
        "candidate_id": candidate_id,
        "stage": "raw_candidate",
        "role": value["role"],
        "source_id": value["source_id"],
        "source_slug": value["source_slug"],
        "original_candidate": value["original_candidate"],
        "judgement": judgement,
        "matched_gold_id": gold_id,
        "canonical_observed_fields": canonical,
        "reviewer": "Codex agent-assisted draft; human reviewer not yet signed",
        "reason": reason,
        "evidence": value["evidence"],
    }


def metric_rows(
    adjudications: list[dict[str, Any]], gold_records: list[dict[str, Any]]
) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for role in ("claims", "material_items", "material_relations"):
        rows = [item for item in adjudications if item["role"] == role]
        counts = Counter(item["judgement"] for item in rows)
        matched = counts["matched"]
        correct = counts["correct_extra"]
        denominator = sum(
            counts[name] for name in ("matched", "correct_extra", "incorrect", "duplicate")
        )
        gold_total = sum(item["role"] == role for item in gold_records)
        result[role] = {
            "raw_candidate_count": len(rows),
            "judgements": dict(sorted(counts.items())),
            "candidate_precision": {
                "numerator": matched + correct,
                "denominator": denominator,
                "decimal": round((matched + correct) / denominator, 6) if denominator else None,
            },
            "target_recall": {
                "numerator": matched,
                "denominator": gold_total,
                "decimal": round(matched / gold_total, 6) if gold_total else None,
            },
        }
    return result


def query_observations() -> list[dict[str, Any]]:
    result = []
    for slug, spec in SOURCES.items():
        page = query_semantic(
            spec["source_id"][7:],
            spec["build_id"],
            purpose="cite",
            query_text="风险",
            store_root=HERE / slug / "store",
        )
        result.append(
            {
                "source_slug": slug,
                "source_id": spec["source_id"],
                "build_id": spec["build_id"],
                "query_text": "风险",
                "purpose": "cite",
                "result": page.model_dump(mode="json"),
                "model_calls": 0,
            }
        )
    return result


def main() -> None:
    outputs = (OUTPUT, COVERAGE, SUMMARY, MANIFEST)
    if any(path.exists() for path in outputs):
        raise SystemExit("refusing to overwrite immutable adjudication draft")
    gold = load(GOLD)
    gold_by_id = {item["record_id"]: item for item in gold["records"]}
    values = candidates()
    ids = [item["candidate_id"] for item in values]
    if len(ids) != 267 or len(set(ids)) != len(ids):
        raise ValueError(f"candidate roster changed: count={len(ids)} unique={len(set(ids))}")
    terminal = set(MATCHED) | CORRECT_EXTRA | set(DUPLICATES)
    unknown = terminal - set(ids)
    if unknown:
        raise ValueError(f"decision table references unknown candidates: {sorted(unknown)}")
    if len(set(MATCHED.values())) != len(MATCHED):
        raise ValueError("one frozen target was matched more than once")
    if not set(MATCHED.values()) <= set(gold_by_id):
        raise ValueError("matched gold id missing from frozen gold")

    adjudications = [decision(item, gold_by_id) for item in values]
    metrics = metric_rows(adjudications, gold["records"])
    payload = {
        "schema_version": "corpus-candidate-adjudications-agent-draft-v1",
        "status": "agent_pre_adjudicated_pending_named_human_signoff",
        "review_scope": "all_raw_candidates_from_signed_r2_bounded_run",
        "human_gate_satisfied": False,
        "gold_sha256": f"sha256:{sha256(GOLD)}",
        "candidate_count": len(adjudications),
        "unresolved_count": 0,
        "metrics": metrics,
        "adjudications": adjudications,
    }
    save(OUTPUT, payload)

    queries = query_observations()
    matched_gold = set(MATCHED.values())
    observations = []
    for target in gold["records"]:
        role = target["role"]
        target_id = target["record_id"]
        observations.extend(
            [
                {"target_id": target_id, "stage": "parse", "outcome": "pass"},
                {"target_id": target_id, "stage": "packet", "outcome": "pass"},
                {"target_id": target_id, "stage": "routing", "outcome": "pass"},
                {
                    "target_id": target_id,
                    "stage": "extraction",
                    "outcome": "pass" if target_id in matched_gold else "missed",
                    "reason": (
                        "agent_draft_semantic_match"
                        if target_id in matched_gold
                        else (
                            "relation_dependency_blocked_no_call"
                            if role == "material_relations"
                            else "no_acceptable_one_to_one_candidate"
                        )
                    ),
                },
                {
                    "target_id": target_id,
                    "stage": "query",
                    "outcome": "missed",
                    "reason": "CS_NOT_PUBLISHED",
                },
                {
                    "target_id": target_id,
                    "stage": "delivery",
                    "outcome": "missed",
                    "reason": "query_not_published_zero_records",
                },
                {
                    "target_id": target_id,
                    "stage": "context_use",
                    "outcome": "missed",
                    "reason": "no_delivered_semantic_evidence_and_no_M_main_call",
                },
            ]
        )
    coverage = {
        "schema_version": "corpus-non-table-r2-stage-observation-agent-draft-v1",
        "status": "observed_prepublication_block",
        "human_gate_satisfied": False,
        "query_observations": queries,
        "delivery_observation": {
            "status": "not_delivered",
            "reason": "both read-only queries returned CS_NOT_PUBLISHED with zero records",
        },
        "context_use_observation": {
            "status": "not_used",
            "reason": "no evidence record entered a successful M_main request; M_main calls remain zero",
        },
        "observations": observations,
    }
    save(COVERAGE, coverage)

    lines = [
        "# r2 candidate adjudication and query/delivery/context_use observation — agent draft",
        "",
        "This is a complete agent-assisted pre-adjudication of the 267 persisted candidates. "
        "It is not a human signature and does not satisfy the named-human gate.",
        "",
        "## Candidate results",
        "",
        "| role | candidates | matched | correct extra | incorrect | duplicate | precision | target recall |",
        "|---|---:|---:|---:|---:|---:|---:|---:|",
    ]
    for role in ("claims", "material_items", "material_relations"):
        row = metrics[role]
        counts = row["judgements"]
        precision = row["candidate_precision"]
        recall = row["target_recall"]
        p = "N/A" if precision["decimal"] is None else f"{precision['decimal']:.2%}"
        r = "N/A" if recall["decimal"] is None else f"{recall['decimal']:.2%}"
        lines.append(
            f"| {role} | {row['raw_candidate_count']} | {counts.get('matched', 0)} | "
            f"{counts.get('correct_extra', 0)} | {counts.get('incorrect', 0)} | "
            f"{counts.get('duplicate', 0)} | {p} | {r} |"
        )
    lines.extend(
        [
            "",
            "## Stage observation",
            "",
            "- Both source/build queries were executed read-only and returned `CS_NOT_PUBLISHED`, "
            "`page_status=not_published`, and zero records.",
            "- `delivery=not_delivered`: no semantic evidence unit was returned for delivery.",
            "- `context_use=not_used`: no semantic evidence entered a successful M_main request; "
            "M_main calls remain zero.",
            "- The publication and quality gates remain closed. No store row, artifact, publication head, "
            "or user model configuration was changed.",
            "",
            "## Required human action",
            "",
            "A named reviewer must inspect every row in `candidate-adjudications.agent-draft.json`, "
            "amend disputed decisions, and append a signed freeze. Until then precision/recall above are "
            "agent suggestions, not the formal quality result.",
        ]
    )
    with SUMMARY.open("x", encoding="utf-8") as stream:
        stream.write("\n".join(lines) + "\n")
    save(
        MANIFEST,
        {
            "schema_version": "corpus-adjudication-agent-draft-manifest-v1",
            "inputs": {
                str(GOLD.relative_to(EVIDENCE)): f"sha256:{sha256(GOLD)}",
                **{
                    str(object_path(slug, spec[key]).relative_to(EVIDENCE)): (
                        f"sha256:{sha256(object_path(slug, spec[key]))}"
                    )
                    for slug, spec in SOURCES.items()
                    for key in ("claims_payload", "items_payload")
                },
                Path(__file__).name: f"sha256:{sha256(Path(__file__))}",
            },
            "outputs": {
                path.name: f"sha256:{sha256(path)}" for path in (OUTPUT, COVERAGE, SUMMARY)
            },
            "model_calls": 0,
            "production_database_access": 0,
            "human_gate_satisfied": False,
        },
    )
    print(json.dumps({"metrics": metrics, "queries": queries}, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
