from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

import pytest

ROOT = Path(__file__).resolve().parents[1]
CONTRACT_ROOT = ROOT / ".scratch" / "claims-r2-role-isolation" / "contracts"
V1 = CONTRACT_ROOT / "v1"
FIXTURE_ROOT = ROOT / "tests" / "fixtures" / "corpus_structured_synthetic"
SCHEMAS = (
    "evidence-snapshot",
    "execution-ledger",
    "role-artifact",
    "semantic-publication",
    "semantic-query-page",
    "report-semantic-reference",
)


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _canonical_hash(value: object) -> str:
    encoded = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode()
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _json_type_matches(value: object, expected: str) -> bool:
    return {
        "array": isinstance(value, list),
        "integer": isinstance(value, int) and not isinstance(value, bool),
        "null": value is None,
        "number": isinstance(value, (int, float)) and not isinstance(value, bool),
        "object": isinstance(value, dict),
        "string": isinstance(value, str),
    }[expected]


def _resolve_local_ref(schema: dict[str, Any], ref: str) -> dict[str, Any]:
    assert ref.startswith("#/")
    current: Any = schema
    for part in ref[2:].split("/"):
        current = current[part.replace("~1", "/").replace("~0", "~")]
    assert isinstance(current, dict)
    return current


def _validation_errors(
    value: object,
    rule: dict[str, Any],
    root_schema: dict[str, Any],
    path: str = "$",
) -> list[str]:
    """Validate the deliberately small Draft 2020-12 subset used by these assets."""

    if "$ref" in rule:
        return _validation_errors(
            value, _resolve_local_ref(root_schema, rule["$ref"]), root_schema, path
        )
    if "anyOf" in rule:
        branches = [
            _validation_errors(value, branch, root_schema, path) for branch in rule["anyOf"]
        ]
        return (
            [] if any(not branch for branch in branches) else [f"{path}: no anyOf branch matched"]
        )

    errors: list[str] = []
    expected_type = rule.get("type")
    if expected_type is not None:
        expected_types = [expected_type] if isinstance(expected_type, str) else expected_type
        if not any(_json_type_matches(value, item) for item in expected_types):
            return [f"{path}: expected {expected_types}"]
    if "const" in rule and value != rule["const"]:
        errors.append(f"{path}: expected const {rule['const']!r}")
    if "enum" in rule and value not in rule["enum"]:
        errors.append(f"{path}: value is not in enum")

    if isinstance(value, str):
        if len(value) < rule.get("minLength", 0):
            errors.append(f"{path}: string is too short")
        if "pattern" in rule and re.fullmatch(rule["pattern"], value) is None:
            errors.append(f"{path}: pattern mismatch")
    elif isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in rule and value < rule["minimum"]:
            errors.append(f"{path}: number is below minimum")
    elif isinstance(value, list):
        if len(value) < rule.get("minItems", 0):
            errors.append(f"{path}: array is too short")
        if rule.get("uniqueItems"):
            serialized = [json.dumps(item, sort_keys=True) for item in value]
            if len(serialized) != len(set(serialized)):
                errors.append(f"{path}: array items are not unique")
        item_rule = rule.get("items")
        if item_rule:
            for index, item in enumerate(value):
                errors.extend(_validation_errors(item, item_rule, root_schema, f"{path}[{index}]"))
    elif isinstance(value, dict):
        required = rule.get("required", [])
        errors.extend(f"{path}: missing {key}" for key in required if key not in value)
        if len(value) < rule.get("minProperties", 0):
            errors.append(f"{path}: object has too few properties")
        properties = rule.get("properties", {})
        additional = rule.get("additionalProperties", True)
        for key, item in value.items():
            child_path = f"{path}.{key}"
            if key in properties:
                errors.extend(_validation_errors(item, properties[key], root_schema, child_path))
            elif additional is False:
                errors.append(f"{child_path}: additional property")
            elif isinstance(additional, dict):
                errors.extend(_validation_errors(item, additional, root_schema, child_path))
    return errors


@pytest.mark.parametrize("name", SCHEMAS)
def test_versioned_schema_accepts_legal_and_rejects_illegal_example(name: str) -> None:
    schema = _load(V1 / f"{name}.schema.json")
    assert schema["$schema"] == "https://json-schema.org/draft/2020-12/schema"
    assert schema["$id"].endswith(f"/{name}.schema.json")

    legal = _load(V1 / "examples" / "valid" / f"{name}.json")
    illegal = _load(V1 / "examples" / "invalid" / f"{name}.json")
    assert _validation_errors(legal, schema, schema) == []
    assert _validation_errors(illegal, schema, schema)


def test_snapshot_hash_and_unicode_code_point_contract() -> None:
    snapshot = _load(V1 / "examples" / "valid" / "evidence-snapshot.json")
    unit = snapshot["units"][0]
    span = unit["span"]

    assert unit["text_sha256"] == f"sha256:{hashlib.sha256(unit['text'].encode()).hexdigest()}"
    assert unit["metadata_sha256"] == _canonical_hash(unit["metadata"])
    assert span["coordinate_system"] == "unicode_code_points"
    assert unit["text"][span["start"] : span["end"]] == unit["text"]
    assert snapshot["snapshot_id"] == _canonical_hash(snapshot["identity_input"])
    assert snapshot["identity_input"]["unit_identities"][0]["chunk_id"] == unit["chunk_id"]


def test_state_domains_transitions_and_errors_are_unambiguous() -> None:
    catalogue = _load(V1 / "state-codes.json")
    domains = catalogue["states"]

    assert set(domains) == {
        "execution",
        "protocol",
        "publication",
        "context",
        "mapping",
        "quality",
    }
    for domain, states in domains.items():
        assert len(states) == len(set(states))
        assert set(catalogue["transitions"][domain]) == set(states)
        for source, targets in catalogue["transitions"][domain].items():
            assert source in states
            assert len(targets) == len(set(targets))
            assert set(targets) <= set(states)

    for code, semantics in catalogue["error_codes"].items():
        assert code.startswith("CS_")
        assert semantics["exit_code"] in {2, 3, 4, 5, 6}
        assert isinstance(semantics["retryable"], bool)


def test_contract_and_fixture_manifests_bind_exact_bytes() -> None:
    manifest = _load(CONTRACT_ROOT / "contract-manifest.json")
    for asset in manifest["assets"]:
        path = CONTRACT_ROOT / asset["path"]
        assert path.is_file()
        assert _sha256(path) == asset["sha256"]
    for asset in manifest["fixture_manifests"]:
        path = (CONTRACT_ROOT / asset["path"]).resolve()
        assert path.is_relative_to(ROOT)
        assert _sha256(path) == asset["sha256"]

    fixture_manifest = _load(FIXTURE_ROOT / "asset-manifest.json")
    assert fixture_manifest["synthetic_only"] is True
    assert fixture_manifest["real_source_ids"] == []
    for asset in fixture_manifest["assets"]:
        assert _sha256(FIXTURE_ROOT / asset["path"]) == asset["sha256"]


def test_synthetic_cases_cover_frozen_routing_and_context_scenarios() -> None:
    fixture_manifest = _load(FIXTURE_ROOT / "asset-manifest.json")
    corpus = _load(FIXTURE_ROOT / "cases.json")
    cases = corpus["cases"]
    tags = {tag for case in cases for tag in case["coverage_tags"]}

    assert corpus["synthetic_only"] is True
    assert set(fixture_manifest["required_coverage_tags"]) <= tags
    assert {case["case_id"] for case in cases} >= {
        "ordinary-number",
        "pure-opinion",
        "mixed-condition",
        "negation",
        "forecast-versus-actual",
        "table-header-footnote",
        "cross-packet-qualifier",
        "duplicate-quote",
        "parse-gap",
    }
    assert all(
        case["expected_context_status"] in {"complete", "missing", "ambiguous"} for case in cases
    )
    assert all(
        role in {"claims", "material_items"} for case in cases for role in case["expected_roles"]
    )

    unit_ids = {unit["unit_id"] for case in cases for unit in case["units"]}
    assert all(
        dependency in unit_ids
        for case in cases
        for unit in case["units"]
        for dependency in unit["dependencies"]
    )
    duplicate = next(case for case in cases if case["case_id"] == "duplicate-quote")
    assert duplicate["units"][0]["text"] == duplicate["units"][1]["text"]
    assert duplicate["units"][0]["unit_id"] != duplicate["units"][1]["unit_id"]


def test_manifest_freezes_interfaces_and_role_protocols() -> None:
    manifest = _load(CONTRACT_ROOT / "contract-manifest.json")
    assert manifest["public_interfaces"] == {
        "python_package": "plugins.corpus.structured",
        "research_tool": "corpus_semantic_query",
        "cli_module": "plugins.corpus.structured.cli",
        "commands": ["plan", "execute", "replay", "check", "query"],
    }
    assert manifest["supported_protocols"] == {
        "claims_deterministic": "claims-deterministic-v1",
        "claims_model": "claims-json-v2",
        "material_items": "material-atomic-jsonl-v5",
        "material_relations": "material-relations-jsonl-v1",
    }
    assert manifest["business_schema_reuse"] == {
        "claims": "plugins.corpus.evidence_pipeline.EvidenceRun/EvidenceFact",
        "material": "plugins.corpus.material_semantics.MaterialRun/MaterialUnderstanding",
    }
    assert manifest["real_sample_scope"] == {
        "status": "not_approved_for_this_effort",
        "entries": [],
        "delegated_to_issue": "10-quality-gates",
    }
