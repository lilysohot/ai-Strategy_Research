"""Native pilot boundaries: raw delivery, immutable scope, and stale read rejection."""

import hashlib
import json
from dataclasses import asdict
from types import SimpleNamespace
from unittest.mock import MagicMock, Mock

import pytest

from plugins.corpus.preparation.read_pg import IntegrityError, WithdrawnError
from plugins.corpus.retrieval.native import (
    NativeBlock,
    NativeIndex,
    NativeSpan,
    normalized,
    raw_slices,
    select_native,
)
from plugins.corpus.retrieval.native_pg import _load_blocks, _snapshot, search_native


def unit(raw, **kwargs):
    return {
        "build_id": "b",
        "unit_id": "u",
        "kind": "paragraph",
        "status": "kept",
        "raw_text": raw,
        "content_hash": hashlib.sha256(raw.encode()).hexdigest(),
        "location": {"page": 3, "char_span": None},
        "eligible": True,
        **kwargs,
    }


def test_maps_only_matching_interval_of_long_unit_and_keeps_percentage():
    raw = "前文" * 1000 + "收入增长 12.5%。" + "后文" * 1000
    slices = raw_slices("收入增长12.5。", [unit(raw)])
    assert len(slices) == 1
    s = slices[0]
    assert s.text == "收入增长 12.5%。" == raw[s.start : s.end]
    assert s.start == 2000 and s.page == 3


def test_clean_view_omissions_become_separate_raw_spans():
    raw = "收入增长。页脚噪声利润改善。"
    slices = raw_slices("收入增长。利润改善。", [unit(raw)])
    assert [s.text for s in slices] == ["收入增长。", "利润改善。"]
    assert all(s.text == raw[s.start : s.end] for s in slices)


def test_projection_across_units_keeps_each_source_coordinate():
    slices = raw_slices("毛利率12.5 增长", [unit("毛利率12.5%"), unit("增长", unit_id="v")])
    assert [(s.unit_id, s.text) for s in slices] == [("u", "毛利率12.5%"), ("v", "增长")]
    assert normalized("".join(s.text for s in slices)) == normalized("毛利率12.5 增长")


@pytest.mark.parametrize(
    "change", [{"kind": "table"}, {"status": "dropped"}, {"content_hash": "bad"}]
)
def test_raw_mapping_rejects_unsafe_or_corrupt_unit(change):
    with pytest.raises(IntegrityError):
        raw_slices("原文", [unit("原文", **change)])


def test_unmappable_projection_does_not_return_search_text_as_evidence():
    with pytest.raises(IntegrityError, match="not_mappable"):
        raw_slices("原文中不存在的结论", [unit("原文")])


def test_budget_uses_raw_whitespace_and_does_not_duplicate_text_in_spans():
    a = NativeBlock("s", "b", "a", None, "收入 12.5%", (NativeSpan("u", 3, 0, 8, "h"),))
    b = NativeBlock("s", "b", "b", None, "其他", ())
    blocks = {("b", "a"): a, ("b", "b"): b}
    assert select_native(list(blocks), blocks, char_budget=7, limit=20) == (b,)
    assert select_native(
        [("b", "a"), ("b", "a"), ("b", "b")], blocks, char_budget=10, limit=20
    ) == (a, b)
    assert "text" not in asdict(a)["slices"][0]


@pytest.mark.parametrize("budget,limit", [(0, 20), (16001, 20), (16000, 0), (16000, 21)])
def test_invalid_budget_rejected(budget, limit):
    with pytest.raises(ValueError):
        select_native([], {}, char_budget=budget, limit=limit)


def bundle(tmp_path, **overrides):
    text = "原文"
    h = hashlib.sha256(text.encode()).hexdigest()
    payload = {
        "chunks.json": [
            {
                "source_id": "s",
                "build_id": "b",
                "chunk_id": "c",
                "kind": "body",
                "unit_refs": ["u"],
                "search_text": text,
                "input_hash": h,
            }
        ],
        "units.json": [unit(text)],
        "vectors.json": {h: {"vector": [1.0, 0.0]}},
        "dates.json": [{"source_id": "s", "date": None, "basis": "unknown", "names": ["x"]}],
    }
    payload.update(overrides)
    hashes = {}
    for name, value in payload.items():
        raw = json.dumps(value).encode()
        (tmp_path / name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    manifest = {
        "schema": "native-evidence-pilot-1",
        "target_db": "vector_pilot_test",
        "profile": "profile",
        "dimensions": 2,
        "source_allowlist": ["s"],
        "excluded_source_ids": ["ocr"],
        "publications": [["s", "b", 1]],
        "files": hashes,
        "cutoff": "2026-10-21",
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_bundle_hash_must_match_before_any_search(tmp_path):
    path = bundle(tmp_path)
    assert NativeIndex(path).target == "vector_pilot_test"
    (tmp_path / "chunks.json").write_text("[]")
    with pytest.raises(IntegrityError, match="file_hash"):
        NativeIndex(path)


def test_bundle_cannot_attach_chunk_to_wrong_active_build(tmp_path):
    path = bundle(tmp_path)
    manifest = json.loads(path.read_text())
    manifest["publications"][0][1] = "other"
    path.write_text(json.dumps(manifest))
    with pytest.raises(IntegrityError, match="chunk_scope"):
        NativeIndex(path)


def test_bundle_requires_dates_for_entire_allowlist(tmp_path):
    with pytest.raises(IntegrityError, match="dates_incomplete"):
        NativeIndex(bundle(tmp_path, **{"dates.json": []}))


@pytest.mark.parametrize(
    "live, error",
    [
        ([], WithdrawnError),
        ([("s", "excluded", ["x"], None)], WithdrawnError),
        ([("s", "in_scope", ["renamed"], None)], IntegrityError),
        ([("s", "in_scope", ["x"], "2026-10-22")], IntegrityError),
    ],
)
def test_snapshot_rejects_withdrawal_or_metadata_drift(tmp_path, live, error):
    index = NativeIndex(bundle(tmp_path))
    cur = Mock()
    cur.fetchall.side_effect = [[("s", "b", 1)], live]
    with pytest.raises(error):
        _snapshot(cur, index)


def test_snapshot_rejects_changed_generation(tmp_path):
    index = NativeIndex(bundle(tmp_path))
    cur = Mock()
    cur.fetchall.return_value = [("s", "b", 2)]
    with pytest.raises(IntegrityError, match="publications_changed"):
        _snapshot(cur, index)


def test_raw_reader_normalizes_span_storage_but_checks_actual_coordinates(tmp_path):
    path = bundle(
        tmp_path,
        **{"units.json": [unit("原文", location={"page": 3, "char_span": {"start": 1, "end": 3}})]},
    )
    index = NativeIndex(path)
    cur = Mock()
    h = index.units["b", "u"]["content_hash"]
    cur.fetchall.return_value = [
        ("b", "u", "paragraph", "原文", {"page": 3, "char_span": [1, 3]}, h, "kept")
    ]
    assert _load_blocks(cur, index)["b", "c"].text == "原文"
    cur.fetchall.return_value[0][4]["page"] = 4
    with pytest.raises(IntegrityError, match="unit_changed"):
        _load_blocks(cur, index)


def test_nonpilot_target_rejected_before_vector_or_database(monkeypatch):
    connect = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr("plugins.corpus.retrieval.native_pg.psycopg.connect", connect)
    with pytest.raises(ValueError, match="target_mismatch"):
        search_native("", "production", "query", SimpleNamespace(target="vector_pilot_test"))
    connect.assert_not_called()


def test_profile_mismatch_rejected_before_vector_or_database(tmp_path, monkeypatch):
    index = NativeIndex(bundle(tmp_path))
    config = SimpleNamespace(target_db=index.target, profile="other")
    monkeypatch.setattr("plugins.corpus.retrieval.native_pg.VectorConfig.from_env", lambda: config)
    connect = Mock(side_effect=AssertionError("must not connect"))
    monkeypatch.setattr("plugins.corpus.retrieval.native_pg.psycopg.connect", connect)
    with pytest.raises(ValueError, match="profile_or_target"):
        search_native("", index.target, "query", index)
    connect.assert_not_called()


@pytest.mark.parametrize("failure", ["embedding", "publication_race"])
def test_failed_embedding_or_publication_race_never_delivers_unfiltered_evidence(
    tmp_path, monkeypatch, failure
):
    from plugins.corpus.retrieval import native_pg
    from plugins.corpus.retrieval.embedding import EmbeddingError

    index = NativeIndex(bundle(tmp_path))
    config = SimpleNamespace(target_db=index.target, profile="profile", dimensions=2)
    monkeypatch.setattr(native_pg.VectorConfig, "from_env", lambda: config)
    conn = MagicMock()
    conn.__enter__.return_value = conn
    monkeypatch.setattr(native_pg.psycopg, "connect", Mock(return_value=conn))
    monkeypatch.setattr(native_pg, "_check_target", Mock())
    snapshot = Mock(side_effect=[None, IntegrityError("changed")])
    monkeypatch.setattr(native_pg, "_snapshot", snapshot)
    embed = Mock(return_value=([1.0, 0.0], 0, 0))
    if failure == "embedding":
        embed.side_effect = EmbeddingError("provider_failed")
    monkeypatch.setattr(native_pg, "query_vector", embed)
    prepare = Mock()
    load = Mock(side_effect=AssertionError("must not load or return evidence"))
    monkeypatch.setattr(native_pg, "_prepare", prepare)
    monkeypatch.setattr(native_pg, "_load_blocks", load)
    with pytest.raises(EmbeddingError if failure == "embedding" else IntegrityError):
        search_native("", index.target, "query", index)
    assert snapshot.call_count == (1 if failure == "embedding" else 2)
    assert prepare.call_count == (0 if failure == "embedding" else 1)
    load.assert_not_called()
