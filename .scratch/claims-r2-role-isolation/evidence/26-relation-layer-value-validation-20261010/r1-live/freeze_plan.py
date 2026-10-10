"""Freeze the signed Issue 26 paired-ablation inputs without model calls."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

ROOT = Path("/home/administrator/FrontierAgent")
CLAIMS = ROOT / ".scratch" / "claims-r2-role-isolation"
R0 = CLAIMS / "evidence" / "26-relation-layer-value-validation-20261010" / "r0-preflight"
HERE = Path(__file__).resolve().parent
STORE = (
    CLAIMS
    / "evidence"
    / "25-final-relation-live-compliance-20261010"
    / "r0-live"
    / "live-store-v2"
)
GOLD = R0 / "utility-gold.agent-draft.json"
HUMAN_REVIEW = R0 / "human-review.md"
ISSUE26 = CLAIMS / "issues" / "26-relation-layer-value-validation.md"
ISSUE27 = CLAIMS / "issues" / "27-challenges-rule-propositional-conflict.md"

EXPECTED = {
    "snapshot_id": "sha256:561401b409e329fba8306c392bfc203da23ff1cc666faf9b7e919d88c2a9f080",
    "batch_id": "batch:3269051ddc97ebc979132d5110bdf923c22f28b9f87dd579717b27acb120f920",
    "candidate_set_id": "sha256:0e93746e5edf13547b7d149c90ebfa586ed48910707db5aceefac2379f100613",
    "items_payload": "sha256:592065e674a8a0c1b2ff6764014781b029f8e22f616f0460dc921426b8a2c896",
    "relations_payload": "sha256:a4af367954dc9a6214d3b1f87f71c6eedb85a78225d6ead9bfe5a5db18deacfb",
}


def canonical_bytes(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha_bytes(raw: bytes) -> str:
    return f"sha256:{hashlib.sha256(raw).hexdigest()}"


def sha_file(path: Path) -> str:
    return sha_bytes(path.read_bytes())


def read_json(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise RuntimeError(f"expected JSON object: {path}")
    return value


def read_object(identity: str) -> dict[str, Any]:
    digest = identity.removeprefix("sha256:")
    path = STORE / "objects" / "sha256" / digest[:2] / f"{digest}.json"
    raw = path.read_bytes()
    if sha_bytes(raw) != identity:
        raise RuntimeError(f"immutable object hash mismatch: {identity}")
    return json.loads(raw)


def item_record(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "item_id": item["item_id"],
        "text": item["text"],
        "semantic_type": item["semantic_type"],
        "speech_role": item["speech_role"],
        "statement_role": item["statement_role"],
        "polarity": item["polarity"],
        "temporal_frame": item["temporal_frame"],
        "evidence": [
            {
                "quote": evidence["quote"],
                "locator": evidence["locator"],
                "start": evidence["start"],
                "end": evidence["end"],
            }
            for evidence in item["evidence"]
        ],
    }


def relation_record(relation: dict[str, Any]) -> dict[str, Any]:
    return {
        "relation_id": relation["relation_id"],
        "type": relation["type"],
        "from_item": relation["from_item"],
        "to_item": relation["to_item"],
        "provenance": relation["provenance"],
        "evidence": [
            {
                "quote": evidence["quote"],
                "locator": evidence["locator"],
                "start": evidence["start"],
                "end": evidence["end"],
            }
            for evidence in relation["evidence"]
        ],
    }


def main() -> None:
    from frontier_agent.infra.config import get_config

    generated = {
        "delivery-packs",
        "freeze-manifest.json",
        "execution-summary.json",
        "results",
    }
    if HERE.exists() and any((HERE / name).exists() for name in generated):
        raise RuntimeError(f"freeze outputs already exist: {HERE}")
    HERE.mkdir(parents=True, exist_ok=True)
    (HERE / "delivery-packs").mkdir()

    gold = read_json(GOLD)
    review = HUMAN_REVIEW.read_text(encoding="utf-8")
    if gold["status"] != "human_signed_off":
        raise RuntimeError("utility gold is not signed off")
    if gold["signoff"] != {
        "required": True,
        "reviewer": "xyl",
        "authorization": "已签认",
        "signed_at": "2026-10-10",
    }:
        raise RuntimeError("utility-gold signoff identity drifted")
    if any(q["human_review"]["decision"] != "approved" for q in gold["questions"]):
        raise RuntimeError("not every utility question is approved")
    for required_text in (
        "签认人：`xyl`",
        "签认语：`签认 Issue 26 utility-gold draft`",
        "日期：`2026-10-10`",
    ):
        if required_text not in review:
            raise RuntimeError(f"human review is missing: {required_text}")
    if review.count("`[x] 接受`") != 5:
        raise RuntimeError("human review does not approve exactly five questions")
    for key, gold_key in (
        ("snapshot_id", "source_snapshot_id"),
        ("batch_id", "source_batch_id"),
        ("candidate_set_id", "candidate_set_id"),
        ("items_payload", "items_payload_sha256"),
        ("relations_payload", "relations_payload_sha256"),
    ):
        if gold[gold_key] != EXPECTED[key]:
            raise RuntimeError(f"signed input identity drifted: {gold_key}")

    items_payload = read_object(EXPECTED["items_payload"])
    relations_payload = read_object(EXPECTED["relations_payload"])
    items = {
        item["item_id"]: item
        for item in items_payload["understanding"]["items"]
    }
    relations = {
        relation["relation_id"]: relation
        for relation in relations_payload["understanding"]["relations"]
    }
    if len(items) != 469 or len(relations) != 213:
        raise RuntimeError("frozen payload counts drifted")

    pack_hashes: dict[str, dict[str, str]] = {}
    for question in gold["questions"]:
        question_id = question["question_id"]
        relation_ids = question["target_relation_ids"]
        selected_relations = []
        selected_item_ids = {anchor["item_id"] for anchor in question["evidence_anchors"]}
        for relation_id in relation_ids:
            relation = relations.get(relation_id)
            if relation is None:
                raise RuntimeError(f"missing frozen relation: {relation_id}")
            selected_relations.append(relation_record(relation))
            selected_item_ids.update((relation["from_item"], relation["to_item"]))
        for anchor in question["evidence_anchors"]:
            item = items.get(anchor["item_id"])
            if item is None:
                raise RuntimeError(f"missing frozen item: {anchor['item_id']}")
            if anchor["quote"] not in {e["quote"] for e in item["evidence"]}:
                raise RuntimeError(f"signed evidence quote drifted: {anchor['item_id']}")

        delivered_items = [item_record(items[item_id]) for item_id in sorted(selected_item_ids)]
        base = {
            "schema_version": "relation-utility-delivery-pack-1",
            "question_id": question_id,
            "question": question["prompt"],
            "source_snapshot_id": EXPECTED["snapshot_id"],
            "material_items": delivered_items,
        }
        a_pack = {**base, "delivery_contract": "material_items_only"}
        b_pack = {
            **base,
            "delivery_contract": "material_items_plus_frozen_relations",
            "material_relations": selected_relations,
        }
        pack_hashes[question_id] = {}
        for condition, pack in (("A", a_pack), ("B", b_pack)):
            path = HERE / "delivery-packs" / f"{question_id}-{condition}.json"
            raw = json.dumps(pack, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
            path.write_text(raw, encoding="utf-8")
            pack_hashes[question_id][condition] = sha_file(path)
        if a_pack["material_items"] != b_pack["material_items"]:
            raise RuntimeError(f"A/B item delivery differs for {question_id}")

    gold_hash = sha_file(GOLD)
    cells = [f"{q['question_id']}-{condition}" for q in gold["questions"] for condition in ("A", "B")]
    order = sorted(
        cells,
        key=lambda cell: hashlib.sha256(
            f"{gold_hash}|issue26-order-v1|{cell}".encode()
        ).hexdigest(),
    )
    config = get_config()
    if config.llm_fallback_chain or config.llm_fallback_model:
        raise RuntimeError("fallback must be disabled so one cell equals one physical call")
    model = config.openai_model
    if not model or not config.openai_api_key or not config.openai_base_url:
        raise RuntimeError("main-model endpoint is not fully configured")
    manifest = {
        "schema_version": "relation-utility-freeze-manifest-1",
        "created_on": "2026-10-10",
        "status": "frozen_ready_to_execute",
        "authorization": {
            "reviewer": "xyl",
            "signed_at": "2026-10-10",
            "utility_gold_status": gold["status"],
        },
        "immutable_inputs": {
            "utility_gold_sha256": gold_hash,
            "human_review_sha256": sha_file(HUMAN_REVIEW),
            "issue26_sha256": sha_file(ISSUE26),
            "issue27_sha256": sha_file(ISSUE27),
            **EXPECTED,
        },
        "experiment": {
            "main_runs_max": 10,
            "relation_extraction_calls": 0,
            "judge_calls": 0,
            "publication_calls": 0,
            "production_database_access": 0,
            "temperature": 0.0,
            "max_output_tokens": 2048,
            "concurrency": 1,
            "automatic_retries_per_cell": 0,
            "tools": [],
            "independent_single_turn_contexts": True,
            "order_derivation": "sha256(signed_gold_hash|issue26-order-v1|cell), ascending",
            "run_order": order,
        },
        "model": {
            "provider": config.llm_provider,
            "request_model": model,
            "base_host": urlsplit(config.openai_base_url).hostname,
            "api_key_present": True,
        },
        "delivery_pack_hashes": pack_hashes,
    }
    (HERE / "freeze-manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
