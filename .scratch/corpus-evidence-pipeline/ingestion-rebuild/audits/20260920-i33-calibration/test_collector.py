from pathlib import Path
from types import SimpleNamespace as NS
import importlib.util
import pytest

spec = importlib.util.spec_from_file_location("collector", Path(__file__).with_name("calibrate.py"))
collector = importlib.util.module_from_spec(spec)
spec.loader.exec_module(collector)


def hit(source, chunk, build="build"):
    return NS(source_id=source, chunk_id=chunk, build_id=build)


def test_chunk_duplicates_do_not_consume_document_top_k():
    hits = [hit("A", "1"), hit("A", "2"), hit("B", "3"), hit("C", "4"), hit("A", "5")]
    grouped = collector.group_hits(hits, 2, 2)
    assert list(grouped) == ["A", "B"]
    assert [h.chunk_id for h in grouped["A"]] == ["1", "2"]


def test_mixed_builds_for_same_source_rejected():
    with pytest.raises(ValueError):
        collector.group_hits([hit("A", "1"), hit("A", "2", "other")], 5, 8)


def test_empty_hits_are_no_match_not_failed():
    observation = collector.observations_for("q", {}, lambda _: None, {})
    assert observation.outcome.value == "no_match" and not observation.documents


@pytest.mark.parametrize("fault", ["source", "build", "active", "text", "exception"])
def test_bad_or_failed_fetch_never_becomes_success(fault):
    result = NS(source_id="A", build_id="build", active=True, text="real text",
                units=(NS(page=7, raw_text="real text"),))
    if fault == "source": result.source_id = "wrong"
    if fault == "build": result.build_id = "wrong"
    if fault == "active": result.active = False
    if fault == "text": result.text = "fabricated"
    def fetch(_):
        if fault == "exception": raise RuntimeError("PG unavailable")
        return result
    with pytest.raises((ValueError, RuntimeError)):
        collector.observations_for("q", {"A": [hit("A", "1")]}, fetch, {})


def test_evidence_coordinates_come_from_fetched_units():
    result = NS(source_id="A", build_id="build", active=True, text="real text",
                units=(NS(page=7, raw_text="real text"),))
    observation = collector.observations_for("q", {"A": [hit("A", "1")]}, lambda _: result, {"A": "gold-A"})
    document = observation.documents[0]
    assert document.source_id == "gold-A" and document.build_id == "build"
    assert document.evidence[0].text == "real text"
    assert document.evidence[0].locator == ("page:7",)
    assert document.evidence[0].verified is True
