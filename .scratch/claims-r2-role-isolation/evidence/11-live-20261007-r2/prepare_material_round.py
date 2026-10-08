"""Freeze a fail-fast, segment-by-segment live material-items round."""

from __future__ import annotations

import hashlib
import json
import time
from pathlib import Path

from plugins.corpus.evidence_pipeline import evidence_document_from_snapshot
from plugins.corpus.material_semantics import build_candidate_slots, build_material_structure
from plugins.corpus.structured.config import RequestOptions, canonical_hash, load_extraction_config
from plugins.corpus.structured.ledger import plan_batch
from plugins.corpus.structured.snapshot import (
    SnapshotBuildSource,
    SnapshotDocumentSource,
    SnapshotHead,
    SnapshotUnitSource,
    build_snapshot,
)

ROOT = Path(__file__).resolve().parent
REPO = ROOT.parents[3]
SOURCE_RUN = ROOT.parent / "11-live-20261004-r1"
SOURCE = REPO / (
    "data/corpus/2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司研究-"
    "业绩点评-贵州茅台-600519-报表实质扎实-经营底部已过-贵州茅台-600519-"
    "2026年中报点评-e034bdac.pdf"
)
SOURCE_SHA256 = "6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11"
SEGMENTS = {
    "01_results": ((12, 0, None),),
    "02_channels": ((15, 0, None),),
    "03_quality_cashflow": ((17, 0, None),),
    "04_reform_actions": ((19, 0, 218),),
    "05_reform_outlook": ((19, 218, None),),
    "06_recommendation_basis": ((21, 0, 180),),
    "07_recommendation_conclusion": ((21, 180, None),),
    "08_risks": ((23, 0, None),),
}


def save(path: Path, value: object) -> None:
    with path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write("\n")


class FrozenReader:
    def __init__(self, payload: SnapshotBuildSource) -> None:
        self.payload = payload

    def read_head(self, source_id: str) -> SnapshotHead:
        assert source_id == self.payload.head.source_id
        return self.payload.head

    def read_build(self, head: SnapshotHead) -> SnapshotBuildSource:
        assert head == self.payload.head
        return self.payload


def snapshot_for(
    name: str, spans: tuple[tuple[int, int, int | None], ...], capture: dict
) -> object:
    by_ordinal = {unit["ordinal"]: unit for unit in capture["reader"]["units"]}
    selected = []
    for ordinal, start, end in spans:
        unit = by_ordinal[ordinal]
        stop = len(unit["raw_text"]) if end is None else end
        assert 0 <= start < stop <= len(unit["raw_text"])
        selected.append(
            {"unit": unit, "start": start, "end": stop, "text": unit["raw_text"][start:stop]}
        )
    assert all(
        item["unit"]["location"]["page"] == 1 and item["unit"]["status"] == "kept"
        for item in selected
    )
    versions = {
        "parse": capture["reader"]["extractor_rev"],
        "clean": capture["clean"]["clean_rev"],
        "chunk": capture["chunks"]["chunk_rev"],
        "adapter": "approved-page1-material-segments-v2",
    }
    build_id = canonical_hash(
        {"source": SOURCE_SHA256, "versions": versions, "segment": name, "units": selected}
    )[7:]
    payload = SnapshotBuildSource(
        head=SnapshotHead(source_id=SOURCE_SHA256, build_id=build_id, publication_generation=1),
        parser_versions=versions,
        document=SnapshotDocumentSource(
            title="华创证券：贵州茅台（600519）2026年中报点评",
            subject="600519.SH",
            published="2026-08-16",
        ),
        units=tuple(
            SnapshotUnitSource(
                source_unit_id=(
                    f"pdf-unit-{item['unit']['ordinal']}-span-{item['start']}-{item['end']}"
                ),
                chunk_id=f"material-segment:{name}",
                kind="prose",
                text=item["text"],
                locator=(
                    f"page:1/unit:{item['unit']['ordinal']}/span:{item['start']}-{item['end']}"
                ),
                page=1,
                ordinal=item["unit"]["ordinal"],
                metadata={
                    "reader_kind": item["unit"]["kind"],
                    "bbox": item["unit"]["location"]["bbox"],
                    "reader_source_span": [item["start"], item["end"]],
                    "semantic_scope": name,
                    "document_voice": "华创证券研究报告",
                },
            )
            for item in selected
        ),
    )
    return build_snapshot(FrozenReader(payload), SOURCE_SHA256)


def main() -> None:
    assert hashlib.sha256(SOURCE.read_bytes()).hexdigest() == SOURCE_SHA256
    capture = json.loads((SOURCE_RUN / "reader-capture.json").read_text(encoding="utf-8"))
    config = load_extraction_config(
        dotenv_path=REPO / ".env",
        options=RequestOptions(max_output_tokens=8192),
    )
    config.require_profile()
    prepared: list[tuple[str, object, object, int]] = []
    for name, spans in SEGMENTS.items():
        snapshot = snapshot_for(name, spans, capture)
        document = evidence_document_from_snapshot(snapshot, role="material_items")
        slots = build_candidate_slots(document, build_material_structure(document))
        print(json.dumps({"segment": name, "candidate_slots": len(slots)}, ensure_ascii=False))
        plan = plan_batch(
            snapshot,
            config=config,
            max_attempts=2,
            role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 1},
            relations_enabled=True,
            max_relation_tasks=1,
            max_relation_attempts=1,
            deadline_epoch=time.time() + 7200,
        )
        item_tasks = [task for task in plan.tasks if task.role == "material_items"]
        assert len(item_tasks) == 1 and item_tasks[0].max_attempts == 1
        prepared.append((name, snapshot, plan, len(slots)))

    oversized = [(name, count) for name, _snapshot, _plan, count in prepared if count > 8]
    assert not oversized, oversized

    ROOT.mkdir(exist_ok=True)
    assert not (ROOT / "manifest.json").exists()
    assert all(not (ROOT / name).exists() for name in SEGMENTS)
    runner_hashes = {
        filename: hashlib.sha256((ROOT / filename).read_bytes()).hexdigest()
        for filename in ("prepare_material_round.py", "execute_material_segment.py")
    }
    manifest = {
        "stage": "material_items_and_explicit_relations_segmented_r2",
        "source_sha256": SOURCE_SHA256,
        "scope": "page 1 narrative reader units 12,15,17,19,21,23",
        "semantic_targets": [
            "fact",
            "forecast",
            "opinion",
            "argument",
            "risk",
            "condition",
            "explicit_relation",
        ],
        "model": config.require_profile().model,
        "profile_sha256": config.require_profile().fingerprint,
        "max_output_tokens_per_call": 8192,
        "automatic_retries": 0,
        "concurrency": 1,
        "failure_policy": "execute one segment, audit it, stop before the next on failure",
        "runner_sha256": runner_hashes,
        "segments": [],
    }
    for name, snapshot, plan, slot_count in prepared:
        run = ROOT / name
        run.mkdir()
        save(run / "snapshot.json", snapshot.model_dump(mode="json"))
        save(run / "plan.json", plan.model_dump(mode="json"))
        freeze = {
            "segment": name,
            "batch_id": plan.batch_id,
            "snapshot_id": snapshot.snapshot_id,
            "candidate_slot_count": slot_count,
            "material_items_call_ceiling": 1,
            "material_relations_call_ceiling": 1,
            "runner_sha256": runner_hashes,
            "source_sha256": SOURCE_SHA256,
            "user_authorization": (
                "2026-10-04 unlimited calls without loops; 2026-10-07 requested full semantic "
                "round with material_items isolated"
            ),
        }
        save(run / "freeze.json", freeze)
        manifest["segments"].append(
            {
                "name": name,
                "source_spans": [list(span) for span in SEGMENTS[name]],
                "candidate_slot_count": slot_count,
                "batch_id": plan.batch_id,
                "snapshot_id": snapshot.snapshot_id,
            }
        )
    save(ROOT / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
