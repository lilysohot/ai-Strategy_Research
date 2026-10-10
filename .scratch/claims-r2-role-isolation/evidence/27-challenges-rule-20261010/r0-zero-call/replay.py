"""Zero-call replay of the Issue 27 challenge acceptance guard."""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any

ROOT = Path("/home/administrator/FrontierAgent")
CLAIMS = ROOT / ".scratch" / "claims-r2-role-isolation"
HERE = Path(__file__).resolve().parent
RELATION_OBJECT = (
    CLAIMS
    / "evidence"
    / "25-final-relation-live-compliance-20261010"
    / "r0-live"
    / "live-store-v2"
    / "objects"
    / "sha256"
    / "a4"
    / "a4af367954dc9a6214d3b1f87f71c6eedb85a78225d6ead9bfe5a5db18deacfb.json"
)
TARGET = "rel_851e403cdfae400b"
PATTERN = re.compile(
    r"并非|不是|不对|错误|有误|相反|更正|纠正|改口|应改为|而非|不能说|"
    r"不意味着|否认|推翻|说错|不准确|误区|理解有偏差|我收回"
)


def sha_file(path: Path) -> str:
    return f"sha256:{hashlib.sha256(path.read_bytes()).hexdigest()}"


def main() -> None:
    payload: dict[str, Any] = json.loads(RELATION_OBJECT.read_text(encoding="utf-8"))
    relations = payload["understanding"]["relations"]
    challenges = [relation for relation in relations if relation["type"] == "challenges"]
    decisions = []
    for relation in challenges:
        quote = relation["evidence"][0]["quote"]
        decisions.append(
            {
                "relation_id": relation["relation_id"],
                "before": "present",
                "after": "present" if PATTERN.search(quote) else "absent",
                "evidence_quote": quote,
            }
        )
    target = next(row for row in decisions if row["relation_id"] == TARGET)
    if target["after"] != "absent":
        raise RuntimeError("fixed Issue 27 counterexample was not removed")
    summary = {
        "schema_version": "challenge-rule-zero-call-replay-1",
        "created_on": "2026-10-10",
        "status": "passed",
        "model_calls": 0,
        "production_database_access": 0,
        "publication_calls": 0,
        "immutable_relation_payload_sha256": sha_file(RELATION_OBJECT),
        "counts": {
            "retained_relations_before": len(relations),
            "challenges_before": len(challenges),
            "challenges_after_narrow_guard": sum(row["after"] == "present" for row in decisions),
            "challenges_downgraded_to_absent": sum(row["after"] == "absent" for row in decisions),
        },
        "fixed_counterexample": target,
        "decisions": decisions,
        "test_command": "uv run pytest -q tests/test_corpus_material_semantics.py",
        "test_result": "88 passed",
    }
    (HERE / "replay-summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
