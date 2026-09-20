"""Preserve submitted bytes, prepare objective scope references, validate without publishing."""
from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import sys

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
sys.path.insert(0, str(ROOT))


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_once(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.read_bytes() != data:
            raise RuntimeError(f"Refusing to replace existing submission: {path.name}")
    else:
        path.write_bytes(data)


def encode(data: object) -> bytes:
    return (json.dumps(data, ensure_ascii=False, indent=2) + "\n").encode()


def main() -> None:
    from plugins.corpus.preparation import guard
    guard.install(BASE / "guards/i3.json")
    from plugins.corpus.preparation.gap_review import GapReview, GapReviewError

    old = BASE / "audits/20260920-i31-human-gap-review"
    r36 = json.loads((BASE / "freezes/i0c-r36.json").read_text())
    binding = r36["binding"]["human_gap_evidence"]
    gold_path = BASE / "source-gold-frozen.jsonl"
    approved_path = BASE / "i3-2/evidence-targets-approved.json"
    gold = [json.loads(line) for line in gold_path.read_text().splitlines() if line.strip()]
    approved = json.loads(approved_path.read_text())
    evidence_refs = [f"{path.relative_to(ROOT)}@sha256:{digest(path.read_bytes())}"
                     for path in (gold_path, approved_path)]
    results = []
    restoration = []
    # Prepare every recovery candidate before restoring any frozen path.
    for short in ("6f14cc14", "dddc7cd0", "174b6462", "793b3967"):
        path = old / f"unsigned-{short}.json"
        preserved = HERE / "submitted-originals" / path.name
        raw = preserved.read_bytes() if preserved.exists() else path.read_bytes()
        data = json.loads(raw)
        frozen = dict(data, reviewer="", reviewed_at="")
        restored_bytes = encode(frozen)
        expected = binding[str(path.relative_to(ROOT))]
        if digest(restored_bytes) != expected:
            raise RuntimeError(f"Cannot prove original frozen bytes: {path.name}")
        write_once(preserved, raw)
        restoration.append((path, restored_bytes, expected))

        try:
            GapReview.from_json(raw.decode())
            parser_error = None
        except GapReviewError as exc:
            parser_error = str(exc)
        missing = [key for key in ("evidence_scope_ref", "required_locators", "scope_rationale", "attestation")
                   if not data.get(key)]
        if datetime.fromisoformat(data["reviewed_at"]).utcoffset() is None:
            missing.append("reviewed_at: actual time and timezone required")
        missing.extend(f"gaps.{key}: rationale missing" for key, value in data["gaps"].items() if not value.strip())

        source_rows = [row for row in gold if row.get("source_sha256") == data["source_id"] and row.get("must_preserve") is True]
        pages = {int(row["locator"]["page"]) for row in source_rows if str(row.get("locator", {}).get("page", "")).isdigit()}
        projected = []
        for question in approved["questions"]:
            for target in question.get("approved_required", []):
                if target["source_id"].endswith("_" + short):
                    projected.append({"query_id": question["query_id"], "target_id": target["target_id"], "locator": target["locator"]})
                    pages.update(int(locator.split(":")[1]) for locator in target["locator"]
                                 if locator.startswith("page:") and locator.split(":")[1].isdigit())
        locators = [f"page:{page}" for page in sorted(pages)]
        overlapping = [key for key in data["gaps"] if key.rsplit(":", 1)[-1].isdigit()
                       and int(key.rsplit(":", 1)[-1]) in pages]
        draft = dict(data, evidence_scope_ref="; ".join(evidence_refs), required_locators=locators)
        draft_path = HERE / f"review-{short}.json"
        write_once(draft_path, encode(draft))
        results.append({"source_id": data["source_id"], "build_id": data["build_id"],
                        "submitted_file": str(preserved.relative_to(ROOT)), "submitted_sha256": digest(raw),
                        "draft": draft_path.name, "parser_error": parser_error, "missing": missing,
                        "suggested_required_locators": locators,
                        "source_gold_ids": [row["gold_id"] for row in source_rows],
                        "approved_required_targets": projected,
                        "page_level_overlaps": overlapping,
                        "scope_status": "derived_from_frozen_required_evidence_pending_human_completeness_confirmation"})
    for path, original_bytes, expected in restoration:
        if digest(path.read_bytes()) != expected:
            path.write_bytes(original_bytes)
        if digest(path.read_bytes()) != expected:
            raise RuntimeError("Frozen template restoration failed")
    report = {"status": "incomplete_submission", "real_review_records_written": 0,
              "real_sources_published": 0, "frozen_templates_restored_exactly": True,
              "evidence_refs": evidence_refs, "submissions": results}
    (HERE / "submission-precheck.json").write_bytes(encode(report))
    print(json.dumps({"status": report["status"], "submissions": [
        {key: row[key] for key in ("draft", "parser_error", "suggested_required_locators", "page_level_overlaps")}
        for row in results]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
