"""Capture the repository reader's approved PDF scope without model or database I/O."""

from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict
from pathlib import Path

from plugins.corpus.preparation.clean import clean_reader_result
from plugins.corpus.preparation.chunk import chunk_clean_result
from plugins.corpus.preparation.readers import read_document


def main() -> None:
    root = Path(__file__).resolve().parent
    source = json.loads((root / "source-inspection.json").read_text())["source_path"]
    reader = read_document(source)
    clean = clean_reader_result(reader)
    chunks = chunk_clean_result(reader, clean)
    payload = {"reader": asdict(reader), "clean": asdict(clean), "chunks": asdict(chunks)}
    with (root / "reader-capture.json").open("x", encoding="utf-8") as stream:
        json.dump(payload, stream, ensure_ascii=False, indent=2)
    scoped = [unit for unit in reader.units if unit.location.page in (1, 2, 3)]
    print(json.dumps({
        "extractor_rev": reader.extractor_rev,
        "scope_units": len(scoped),
        "scope_statuses": dict(Counter(unit.status for unit in scoped)),
        "issues": [asdict(issue) for issue in reader.issues if issue.location.startswith(("page:1", "page:2", "page:3"))],
        "sample_units": [asdict(unit) for unit in scoped[:8]],
    }, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
