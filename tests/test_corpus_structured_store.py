"""Immutable structured store and read-only adapter tests; no external I/O."""

from __future__ import annotations

import json
import os
import socket
import sqlite3
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from test_corpus_structured_execution import BUILD_ID, SOURCE_ID, replay_fixture, snapshot

from plugins.corpus.service import CorpusService
from plugins.corpus.structured.ledger import (
    StructuredExecutionError,
    _hash_bytes,
    plan_batch,
    replay_batch,
)
from plugins.corpus.structured.store import (
    ArtifactReference,
    SemanticPublication,
    publish_semantic,
    read_semantic,
)


@pytest.fixture(autouse=True)
def deny_external_io(monkeypatch: pytest.MonkeyPatch) -> None:
    def denied(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("store tests must not access network, models, or production DB")

    monkeypatch.setattr(socket.socket, "connect", denied)
    monkeypatch.setattr(httpx.HTTPTransport, "handle_request", denied)
    monkeypatch.setattr(CorpusService, "_connect", denied)


def prepared(tmp_path: Path):
    value = snapshot()
    plan = plan_batch(
        value,
        max_attempts=1,
        role_max_attempts={"claims": 0, "material_items": 1, "material_relations": 0},
        relations_enabled=False,
    )
    responses = tmp_path / "responses"
    replay_fixture(value, plan, responses)
    root = tmp_path / "store"
    checked = replay_batch(plan, responses=responses, store_root=root)
    references = {
        task.role: ArtifactReference(
            batch_id=plan.batch_id,
            task_id=task.task_id,
            artifact_sha256=task.artifact_sha256,
        )
        for task in checked.ledger.tasks
        if task.artifact_sha256 is not None
    }
    return value, plan, root, references


def publish_primary(tmp_path: Path):
    value, plan, root, references = prepared(tmp_path)
    manifest = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references["material_items"],),
        expected_parent_publication_id=None,
        store_root=root,
    )
    return value, plan, root, references, manifest


def test_objects_are_not_publications_and_reader_never_uses_old_loader(tmp_path: Path) -> None:
    value, _plan, root, references = prepared(tmp_path)
    assert (root / "objects" / "sha256").is_dir()
    with pytest.raises(StructuredExecutionError, match="CS_NOT_PUBLISHED"):
        read_semantic(value.source_id, value.build_id, store_root=root)

    manifest = publish_semantic(
        source_id=value.source_id,
        build_id=value.build_id,
        snapshot_id=value.snapshot_id,
        artifacts=(references["material_items"],),
        expected_parent_publication_id=None,
        store_root=root,
    )
    view = read_semantic(value.source_id, value.build_id, store_root=root)
    assert view.manifest == manifest
    assert [item.artifact.role for item in view.artifacts] == ["material_items"]
    assert all(item.payload.__class__.__name__ == "MaterialRun" for item in view.artifacts)


def test_manifest_matches_v1_schema_and_object_layout(tmp_path: Path) -> None:
    _value, _plan, root, references, manifest = publish_primary(tmp_path)
    from test_corpus_structured_contracts import V1, _load, _validation_errors

    schema = _load(V1 / "semantic-publication.schema.json")
    assert _validation_errors(manifest.model_dump(mode="json"), schema, schema) == []
    manifest.verify_identity()
    path = root / "manifests" / f"{manifest.publication_id}.json"
    assert json.loads(path.read_text(encoding="utf-8")) == manifest.model_dump(mode="json")
    digest = references["material_items"].artifact_sha256[7:]
    assert (root / "objects" / "sha256" / digest[:2] / f"{digest}.json").is_file()


def test_real_subprocess_reader_survives_writer_exit_and_different_cwd(tmp_path: Path) -> None:
    value, _plan, root, _references, manifest = publish_primary(tmp_path)
    other = tmp_path / "research-run" / "cwd"
    other.mkdir(parents=True)
    script = (
        "import json; from plugins.corpus.structured.store import read_semantic; "
        f"v=read_semantic({value.source_id!r},{value.build_id!r}); "
        "print(json.dumps({'id':v.manifest.publication_id,'roles':[a.artifact.role for a in v.artifacts]}))"
    )
    for index, cwd in enumerate((other, tmp_path / "second-research-run")):
        cwd.mkdir(parents=True, exist_ok=True)
        completed = subprocess.run(
            [sys.executable, "-c", script],
            cwd=cwd,
            text=True,
            capture_output=True,
            check=False,
            env={
                **os.environ,
                "PYTHONPATH": str(Path(__file__).resolve().parents[1]),
                "CORPUS_STRUCTURED_ROOT": str(root),
                "RESEARCH_RUN_ID": f"synthetic-{index}",
            },
        )
        assert completed.returncode == 0, completed.stderr
        assert json.loads(completed.stdout) == {
            "id": manifest.publication_id,
            "roles": ["material_items"],
        }


def test_authoritative_db_head_ignores_missing_or_corrupt_cache(tmp_path: Path) -> None:
    value, _plan, root, _references, manifest = publish_primary(tmp_path)
    cache_files = list((root / "cache" / "heads").glob("*.json"))
    assert len(cache_files) == 1
    cache_files[0].write_text("corrupt cache", encoding="utf-8")
    assert read_semantic(value.source_id, value.build_id, store_root=root).manifest == manifest
    cache_files[0].unlink()
    assert read_semantic(value.source_id, value.build_id, store_root=root).manifest == manifest


def test_corrupt_manifest_hash_and_unknown_schema_are_distinct(tmp_path: Path) -> None:
    value, _plan, root, _references, manifest = publish_primary(tmp_path)
    path = root / "manifests" / f"{manifest.publication_id}.json"
    original = path.read_bytes()
    path.write_bytes(original + b" ")
    with pytest.raises(StructuredExecutionError, match="manifest_hash_mismatch"):
        read_semantic(value.source_id, value.build_id, store_root=root)

    payload = json.loads(original)
    payload["schema_version"] = "corpus-semantic-publication-v999"
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    path.write_bytes(raw)
    connection = sqlite3.connect(root / "index" / "structured.sqlite3")
    connection.execute(
        "UPDATE semantic_publications SET manifest_sha256=? WHERE publication_id=?",
        (_hash_bytes(raw), manifest.publication_id),
    )
    connection.commit()
    connection.close()
    with pytest.raises(StructuredExecutionError, match="CS_SCHEMA_UNSUPPORTED"):
        read_semantic(value.source_id, value.build_id, store_root=root)


def test_corrupt_role_artifact_is_rejected_after_publication(tmp_path: Path) -> None:
    value, _plan, root, references, _manifest = publish_primary(tmp_path)
    digest = references["material_items"].artifact_sha256[7:]
    path = root / "objects" / "sha256" / digest[:2] / f"{digest}.json"
    path.write_text("{}", encoding="utf-8")
    with pytest.raises(StructuredExecutionError, match="CS_ARTIFACT_CORRUPT"):
        read_semantic(value.source_id, value.build_id, store_root=root)


def test_permission_failure_is_not_reported_as_no_publication(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    value, _plan, root, _references, manifest = publish_primary(tmp_path)
    target = (root / "manifests" / f"{manifest.publication_id}.json").resolve()
    original = Path.read_bytes

    def denied(path: Path) -> bytes:
        if path.resolve() == target:
            raise PermissionError("synthetic")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", denied)
    with pytest.raises(StructuredExecutionError, match="structured_store_permission_denied"):
        read_semantic(value.source_id, value.build_id, store_root=root)


def test_reader_projection_excludes_attempt_diagnostics_and_credentials(tmp_path: Path) -> None:
    value, _plan, root, _references, _manifest = publish_primary(tmp_path)
    serialized = read_semantic(value.source_id, value.build_id, store_root=root).model_dump_json()
    assert "synthetic-not-a-secret" not in serialized
    assert "STRUCTURED_EXTRACTION_API_KEY" not in serialized
    assert "https://synthetic.invalid" not in serialized
    assert "authorization" not in serialized.lower()


def test_missing_root_relative_root_and_unindexed_manifest_fail_separately(
    tmp_path: Path,
) -> None:
    with pytest.raises(StructuredExecutionError, match="CS_NOT_FOUND"):
        read_semantic(SOURCE_ID, BUILD_ID, store_root=tmp_path / "missing")
    with pytest.raises(StructuredExecutionError, match="CS_PATH_OUTSIDE_ROOT"):
        read_semantic(SOURCE_ID, BUILD_ID, store_root=Path("relative"))

    root = tmp_path / "orphan"
    root.mkdir()
    (root / "manifests").mkdir()
    fake = SemanticPublication(
        publication_id="sha256:" + "0" * 64,
        source_id=SOURCE_ID,
        build_id=BUILD_ID,
        snapshot_id="sha256:" + "1" * 64,
        generation=1,
        parent_publication_id=None,
        artifacts=("sha256:" + "2" * 64,),
        coverage={
            "claims": "complete",
            "material_items": "missing",
            "material_relations": "missing",
        },
        publication_status="published",
        quality_status="accepted",
    )
    (root / "manifests" / "orphan.json").write_text(fake.model_dump_json(), encoding="utf-8")
    with pytest.raises(StructuredExecutionError, match="CS_NOT_FOUND"):
        read_semantic(SOURCE_ID, BUILD_ID, store_root=root)


def test_manifest_path_is_confined_and_symlink_escape_is_rejected(tmp_path: Path) -> None:
    value, _plan, root, references = prepared(tmp_path)
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "manifests").symlink_to(outside, target_is_directory=True)
    with pytest.raises(StructuredExecutionError, match="CS_PATH_OUTSIDE_ROOT"):
        publish_semantic(
            source_id=value.source_id,
            build_id=value.build_id,
            snapshot_id=value.snapshot_id,
            artifacts=(references["material_items"],),
            expected_parent_publication_id=None,
            store_root=root,
        )


def test_reader_opens_sqlite_query_only_and_does_not_mutate_store(tmp_path: Path) -> None:
    value, _plan, root, _references, _manifest = publish_primary(tmp_path)
    database = root / "index" / "structured.sqlite3"
    before = database.stat().st_mtime_ns
    read_semantic(value.source_id, value.build_id, store_root=root)
    assert database.stat().st_mtime_ns == before
