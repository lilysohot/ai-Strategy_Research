"""Run-local writable receipts remain resolvable on the next committed turn."""

import json

from plugins.corpus.tool_refs import (
    fetch_evidence_ref,
    publish_fetch_references,
    resolve_evidence_reference,
)
from server.corpus_receipts import stage_corpus_receipts


def test_receipts_survive_worker_change_without_rewriting_history(tmp_path, monkeypatch):
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    root = previous / "run/corpus/tool-refs"
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(root))
    item = {"locator": "chunk:c1", "text": "AI\u00a0Control\nTower"}
    item["evidence_ref"] = fetch_evidence_ref("doc", item)
    payload = {"doc_id": "doc", "items": [item]}
    raw = publish_fetch_references(json.dumps(payload))
    ref = json.loads(raw)["items"][0]["evidence_ref"]
    stage_corpus_receipts(target_run_dir=current, source_runs=[("previous", previous)])
    monkeypatch.setenv("CORPUS_TOOL_REF_ROOT", str(current / "run/corpus/tool-refs"))
    assert resolve_evidence_reference(ref)["quote"] == item["text"]


def test_invalid_or_symlinked_receipts_are_not_inherited(tmp_path):
    previous = tmp_path / "previous"
    current = tmp_path / "current"
    root = previous / "run/corpus/tool-refs"
    root.mkdir(parents=True)
    (root / ("a" * 32 + ".json")).write_text("tampered")
    (root / ("b" * 32 + ".json")).symlink_to(root / ("a" * 32 + ".json"))
    stage_corpus_receipts(target_run_dir=current, source_runs=[("previous", previous)])
    assert not list(current.rglob("*.json"))
