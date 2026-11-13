"""Anchor failures stay local: fix the listed ids, never regenerate the body.

The fixture is the real rejected ``deliver_answer`` payload from a live run where
five conclusions quoted the *draft* rather than the accepted body, so the whole
answer was regenerated twice for five anchors.
"""

import json
from pathlib import Path

import pytest

from plugins.tools.corpus_manifest import ManifestAnchorError, prepare_final_manifest

FIXTURE = Path(__file__).parent / "fixtures" / "delivery_anchor_payload.json"
PTR = "plugins.tools.corpus_manifest.resolve_evidence_reference"


@pytest.fixture(autouse=True)
def _resolvable_receipts(monkeypatch):
    """Receipts are a separate concern here; only anchor binding is under test."""
    monkeypatch.setattr(
        PTR,
        lambda ref: {"doc_id": "doc", "locator": "L1", "quote": "source", "evidence_ref": ref},
    )


def row(identifier: str, quote: str) -> dict:
    return {
        "id": identifier,
        "report_quote": quote,
        "evidence": [{"evidence_ref": "ce:" + "0" * 32}],
    }


def real_payload() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_real_rejection_names_every_anchor_with_an_exact_body_candidate():
    data = real_payload()
    with pytest.raises(ManifestAnchorError) as caught:
        prepare_final_manifest(data["conclusions"], data["content"])

    error = caught.value
    assert {issue["id"] for issue in error.issues} == {"c17", "c18", "c27", "c28", "c31"}
    for issue in error.issues:
        assert issue["reason"] == "no_verbatim_match"
        assert issue["first_mismatch_offset"] >= 0
        # A paraphrase never binds; the caller is pointed at the real body line.
        assert issue["nearest_line"] in data["content"]
        if "candidate" in issue:
            assert data["content"][issue["candidate_offset"] :].startswith(issue["candidate"])
            # Offset where the submitted wording leaves the candidate line.
            assert issue["first_mismatch"]["offset"] <= len(issue["candidate"])
    # The body the caller already settled on is pinned, not re-derived.
    assert (
        error.content_sha256
        == prepare_final_manifest(
            [
                row
                for row in data["conclusions"]
                if row["id"] not in {i["id"] for i in error.issues}
            ],
            data["content"],
        )["report_binding"]["sha256"]
    )


def test_fixing_only_the_listed_anchors_keeps_the_body_byte_identical():
    data = real_payload()
    with pytest.raises(ManifestAnchorError) as caught:
        prepare_final_manifest(data["conclusions"], data["content"])

    rows = data["conclusions"]
    dropped = set()
    for issue in caught.value.issues:
        if "candidate" not in issue:
            # A paraphrase with no near body line cannot be bound at all; the
            # conclusion is dropped, never the surrounding analysis.
            dropped.add(issue["index"])
            continue
        rows[issue["index"]]["report_quote"] = issue["candidate"]
    rows = [r for index, r in enumerate(rows) if index not in dropped]

    manifest = prepare_final_manifest(rows, data["content"])
    assert manifest["report_binding"]["text"] == data["content"]
    assert manifest["report_binding"]["sha256"] == caught.value.content_sha256
    # An anchor repair must never touch (or launder) the evidence references.
    kept_original = [
        r for index, r in enumerate(real_payload()["conclusions"]) if index not in dropped
    ]
    assert [row["evidence"][0]["evidence_ref"] for row in manifest["conclusions"]] == [
        row["evidence"][0]["evidence_ref"] for row in kept_original
    ]


def test_invalid_evidence_reference_is_never_synthesised_or_repaired():
    data = real_payload()
    ref = "ce:6baa8c732c813afb76dd4cd5ba1d94"  # real one-digit-short ref
    broken = row("c-bad", data["content"].splitlines()[0])
    broken["evidence"] = [{"evidence_ref": ref}]
    manifest = prepare_final_manifest([broken], data["content"])
    # Anchors may be canonicalised; the receipt is passed through verbatim so the
    # downstream tool-reference check still rejects it. Repair never invents proof.
    assert manifest["conclusions"][0]["evidence"][0]["evidence_ref"] == ref


def test_ambiguous_anchor_is_never_auto_bound():
    # Two body lines become identical after width/space folding: a repair would
    # have to pick one, so it must refuse and let the caller disambiguate.
    content = "价格: 100 元\n价格：100 元"
    rows = [row("c1", "价格： 100 元")]
    with pytest.raises(ManifestAnchorError) as caught:
        prepare_final_manifest(rows, content)
    assert caught.value.issues[0]["reason"] == "no_verbatim_match"


def test_formatting_only_difference_binds_the_exact_body_slice():
    content = "本文提出：在轨数据中心（**ODC**）的功率上限为 1 MW。"
    rows = [row("c1", "本文提出: 在轨数据中心(ODC)的功率上限为 1 MW")]
    manifest = prepare_final_manifest(rows, content)
    assert manifest["conclusions"][0]["report_quote"] == (
        "本文提出：在轨数据中心（**ODC**）的功率上限为 1 MW"
    )
    assert manifest["report_binding"]["text"] == content


def test_paraphrase_with_a_different_claim_is_not_repaired():
    content = "基准情景假设 2028 年可用发射次数为 145 次，其中一半用于计算卫星。"
    rows = [row("c1", "基准情景假设 2028 年可用发射次数为 220 次，其中全部用于计算卫星。")]
    with pytest.raises(ManifestAnchorError):
        prepare_final_manifest(rows, content)
