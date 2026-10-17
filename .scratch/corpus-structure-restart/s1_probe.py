"""Print the S1 structure context for the two scoped targets."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

from plugins.corpus.preparation.readers import read_document

ROOT = Path(__file__).resolve().parents[2]
HERE = ROOT / ".scratch/corpus-access-validation"
CASES = (
    ("f86c6d2c054a835de4de3707c984529580e8ce57628d59f60b6aeca7a0f61fd2", 4),
    ("f3b28791e1355dc371206b10a003dc2ef6c65f88f631c77ea7578be145f28279", 10),
)


def main() -> None:
    inventory = json.loads((HERE / "e2-inventory.json").read_text(encoding="utf-8"))
    file_by_hash = {row["sha256"]: row["file"] for row in inventory["entries"]}
    for source_id, page in CASES:
        result = read_document(ROOT / "data/corpus" / file_by_hash[source_id])
        print(f"\n{source_id[:8]} {result.extractor_rev}")
        for unit in result.units:
            if (
                unit.location.page == page
                and unit.kind == "table_row"
                and (source_id.startswith("f86c6d2c") or "板块" in unit.raw_text)
            ):
                print(unit.ordinal, unit.location.label_path[:1])
                print(unit.raw_text[:80].replace("\n", " / "))
                break
        assert result.structure is not None
        print(
            "nodes",
            len(result.structure.nodes),
            "nonprojected",
            sum(node.ordinal is None for node in result.structure.nodes),
            "relations",
            Counter(relation.kind.value for relation in result.structure.relations),
        )
        nodes = {node.node_id: node for node in result.structure.nodes}
        for relation in result.structure.relations:
            if (
                relation.kind.value in {"caption_of", "footnote_of"}
                and f"p{page:04d}" in relation.target_id
            ):
                print(relation.kind.value, nodes[relation.source_id].raw_text)


if __name__ == "__main__":
    main()
