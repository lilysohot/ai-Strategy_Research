"""Contextual Retrieval：说明只助检索，原文身份与切片不变。"""

import hashlib
import json
from unittest.mock import MagicMock, Mock

import pytest

from plugins.corpus.preparation.read_pg import IntegrityError
from plugins.corpus.retrieval import contextual
from plugins.corpus.retrieval.contextual import ContextNoteError
from plugins.corpus.retrieval.native import NativeIndex, index_input, raw_slices
from plugins.corpus.retrieval.native_pg import _prepare

TEXT = "公司A计划2027年扩建产品B产线，投产取决于设备到货。"


def test_index_text_keeps_original_chunk_as_tail_and_changes_input_identity():
    note = "公司A的产能计划与条件"
    combined = contextual.index_text(note, TEXT)
    assert combined.endswith(TEXT)
    assert combined != TEXT
    assert contextual.input_hash(note, TEXT) != hashlib.sha256(TEXT.encode()).hexdigest()
    assert contextual.chunk_hash(TEXT) == hashlib.sha256(TEXT.encode()).hexdigest()
    with pytest.raises(ContextNoteError, match="note_empty"):
        contextual.index_text("  ", TEXT)


def test_note_validation_rejects_invented_numbers_and_attribution():
    document = f"{TEXT}\n公司A预计2027年三季度投产。"
    contextual.validate_note("公司A的2027年扩产计划及设备到货条件", document)
    with pytest.raises(ContextNoteError, match="note_number_not_in_source"):
        contextual.validate_note("公司A的2028年扩产计划", document)
    with pytest.raises(ContextNoteError, match="note_attribution_not_in_source"):
        contextual.validate_note("公司A承诺2027年投产", document)
    with pytest.raises(ContextNoteError, match="note_too_long"):
        contextual.validate_note("扩" * (contextual.NOTE_MAX_CHARS + 1), document)
    with pytest.raises(ContextNoteError, match="note_empty"):
        contextual.validate_note("   ", document)
    with pytest.raises(ContextNoteError, match="note_marker_leak"):
        contextual.validate_note("[原文片段] 公司A扩产", document)


def test_note_normalization_is_single_line_and_label_free():
    assert contextual.normalize_note("  上下文：公司A\n  扩产计划  ") == "公司A 扩产计划"
    assert contextual.normalize_note("“公司A扩产”") == "公司A扩产"


def test_parse_notes_accepts_fenced_json_and_ignores_unknown_ids():
    raw = '```json\n{"notes":[{"chunk_id":"c1","note":"公司A扩产"},{"chunk_id":"zz","note":"x"}]}\n```'
    assert contextual.parse_notes(raw, ["c1"]) == {"c1": "公司A扩产"}
    with pytest.raises(ContextNoteError) as exc:
        contextual.parse_notes("not json", ["c1"])
    assert exc.value.uncertain is True


def test_build_messages_sends_document_once_for_a_batch():
    messages = contextual.build_messages(TEXT, [("c1", TEXT), ("c2", TEXT), ("c3", TEXT)])
    assert messages[0]["role"] == "system"
    user = messages[1]["content"]
    assert user.count("<document>\n") == 1
    assert user.count("<chunk id=") == 3
    assert TEXT in user


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


def bundle(tmp_path, *, note="公司A的扩产计划与到货条件", schema_extra=None):
    index_text = contextual.index_text(note, TEXT)
    payload = {
        "chunks.json": [
            {
                "source_id": "s",
                "build_id": "b",
                "chunk_id": "c",
                "kind": "body",
                "unit_refs": ["u"],
                "title_text": None,
                "section_path": [],
                "search_text": TEXT,
                "index_text": index_text,
                "input_hash": contextual.input_hash(note, TEXT),
            }
        ],
        "units.json": [dict(unit(TEXT), source_id="s")],
        "vectors.json": {contextual.input_hash(note, TEXT): {"vector": [1.0, 0.0]}},
        "dates.json": [{"source_id": "s", "date": None, "basis": "unknown", "names": ["x"]}],
        "notes.json": [
            {
                "build_id": "b",
                "chunk_id": "c",
                "note": note,
                "context_version": contextual.CONTEXT_VERSION,
                "prompt_version": contextual.PROMPT_VERSION,
            }
        ],
    }
    hashes = {}
    for name, value in payload.items():
        raw = json.dumps(value).encode()
        (tmp_path / name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    manifest = {
        "schema": "native-evidence-contextual-1",
        "target_db": "vector_pilot_test",
        "profile": "profile",
        "dimensions": 2,
        "source_allowlist": ["s"],
        "excluded_source_ids": ["ocr"],
        "publications": [["s", "b", 1]],
        "files": hashes,
        "cutoff": "2026-10-23",
        "release_id": "contextual-test",
        "context_version": contextual.CONTEXT_VERSION,
        "prompt_version": contextual.PROMPT_VERSION,
    }
    manifest.update(schema_extra or {})
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    return path


def test_contextual_pack_requires_note_and_keeps_projection_identity(tmp_path):
    index = NativeIndex(bundle(tmp_path))
    assert index.contextual is True
    assert index.notes[("b", "c")] == "公司A的扩产计划与到货条件"
    chunk = index.chunks[0]
    # 切片与取证只看原文投影；说明只出现在索引输入里。
    assert chunk["search_text"] == TEXT
    assert raw_slices(chunk["search_text"], [unit(TEXT)])[0].text == TEXT
    assert index_input(chunk).endswith(TEXT)


def test_contextual_pack_rejects_index_text_without_original_tail(tmp_path):
    path = bundle(tmp_path)
    chunks = json.loads((tmp_path / "chunks.json").read_text())
    chunks[0]["index_text"] = "只有说明"
    chunks[0]["input_hash"] = hashlib.sha256("只有说明".encode()).hexdigest()
    (tmp_path / "chunks.json").write_text(json.dumps(chunks))
    manifest = json.loads(path.read_text())
    manifest["files"]["chunks.json"] = hashlib.sha256(
        (tmp_path / "chunks.json").read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(manifest))
    with pytest.raises(IntegrityError, match="index_text_not_tail"):
        NativeIndex(path)


def test_contextual_pack_rejects_missing_note(tmp_path):
    path = bundle(tmp_path)
    (tmp_path / "notes.json").write_text("[]")
    manifest = json.loads(path.read_text())
    manifest["files"]["notes.json"] = hashlib.sha256(
        (tmp_path / "notes.json").read_bytes()
    ).hexdigest()
    path.write_text(json.dumps(manifest))
    with pytest.raises(IntegrityError, match="notes_incomplete"):
        NativeIndex(path)


def test_contextual_pack_requires_context_version(tmp_path):
    path = bundle(tmp_path, schema_extra={"context_version": ""})
    with pytest.raises(ValueError, match="context_version"):
        NativeIndex(path)


def test_short_fragment_keeps_plain_index_and_must_not_carry_a_note(tmp_path):
    """碎片（页码/图表残片）不叠说明；叠了就必须有 notes.json 记录，反之亦然。"""
    fragment = "3/ 8"
    payload = {
        "chunks.json": [
            {
                "source_id": "s",
                "build_id": "b",
                "chunk_id": "f",
                "kind": "heading",
                "unit_refs": ["u"],
                "title_text": None,
                "section_path": [],
                "search_text": fragment,
                "index_text": fragment,
                "input_hash": hashlib.sha256(fragment.encode()).hexdigest(),
            }
        ],
        "units.json": [dict(unit(fragment), source_id="s")],
        "vectors.json": {hashlib.sha256(fragment.encode()).hexdigest(): {"vector": [1.0, 0.0]}},
        "dates.json": [{"source_id": "s", "date": None, "basis": "unknown", "names": ["x"]}],
        "notes.json": [],
    }
    hashes = {}
    for name, value in payload.items():
        raw = json.dumps(value).encode()
        (tmp_path / name).write_bytes(raw)
        hashes[name] = hashlib.sha256(raw).hexdigest()
    manifest = {
        "schema": "native-evidence-contextual-1",
        "target_db": "vector_pilot_test",
        "profile": "profile",
        "dimensions": 2,
        "source_allowlist": ["s"],
        "excluded_source_ids": ["ocr"],
        "publications": [["s", "b", 1]],
        "files": hashes,
        "cutoff": "2026-10-23",
        "release_id": "contextual-test",
        "context_version": contextual.CONTEXT_VERSION,
    }
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    assert NativeIndex(path).notes == {}
    assert contextual.note_applies(fragment) is False
    assert contextual.note_applies(TEXT) is True
    # 同一片段若偷偷叠了说明却没有记录，建包/加载必须拒绝。
    (tmp_path / "notes.json").write_text(
        json.dumps([{"build_id": "b", "chunk_id": "f", "note": "说明"}])
    )
    hashes["notes.json"] = hashlib.sha256((tmp_path / "notes.json").read_bytes()).hexdigest()
    manifest["files"] = hashes
    path.write_text(json.dumps(manifest))
    with pytest.raises(IntegrityError, match="note_not_applied"):
        NativeIndex(path)


def test_lexical_index_uses_context_text_but_display_keeps_projection(tmp_path):
    index = NativeIndex(bundle(tmp_path))
    conn = MagicMock()
    cur = Mock()
    conn.cursor.return_value.__enter__.return_value = cur
    _prepare(conn, index)
    rows = cur.executemany.call_args[0][1]
    _build, _chunk, _kind, _title, _section, _refs, search_text, tsv_text, _context, _vector = rows[
        0
    ]
    assert search_text == TEXT  # snippet/展示仍取原文
    assert tsv_text.endswith(TEXT) and tsv_text != TEXT  # 词法索引吃上下文
    assert index_input(index.chunks[0]) == tsv_text
