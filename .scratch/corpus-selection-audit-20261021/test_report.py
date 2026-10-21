"""Regression: an evidence report must expose the actual returned evidence."""

import json
from pathlib import Path

import pytest

HERE = Path(__file__).resolve().parent


def test_p01_exposes_returned_answer_passage():
    capture = json.loads((HERE / "captures/p01.json").read_text(encoding="utf-8"))
    text = (HERE / "evidence-report.md").read_text(encoding="utf-8")
    section = text.split("## p01：", 1)[1].split("## p02：", 1)[0]
    top_hit = capture["public_hits"][0]
    assert top_hit["chunk_id"] in section, "Actual top-1 evidence omitted from report"
    assert "互连电容" in section, "Report only displays truncated keyword snippets"


@pytest.mark.parametrize("capture_path", sorted((HERE / "captures").glob("*.json")))
def test_every_actual_returned_anchor_has_verifiable_full_text(capture_path):
    capture = json.loads(capture_path.read_text(encoding="utf-8"))
    case_id = capture["case"]
    originals = json.loads(
        (HERE / "returned-text" / f"{case_id}.json").read_text(encoding="utf-8")
    )
    rendered = (HERE / "returned-text" / f"{case_id}.md").read_text(encoding="utf-8")
    report = (HERE / "evidence-report.md").read_text(encoding="utf-8")
    assert f"## {case_id}：" in report  # Includes fallback cases, not only hybrid successes.
    for hit in capture["public_hits"]:
        original = originals["chunks"][hit["chunk_id"]]
        assert original["build_id"] == hit["build_id"]
        assert original["source_id"] == hit["source_id"]
        assert hit["locator"] in rendered
        assert "> " + original["text"].replace("\n", "\n> ") in rendered
