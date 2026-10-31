"""Production OCR provenance, native preservation, and failure contracts."""

from __future__ import annotations

import json
import subprocess
from unittest.mock import Mock

import pymupdf
import pytest

from plugins.corpus.preparation.contract import DocumentFormat, UnitLocation, UnitStatus
from plugins.corpus.preparation.readers import extractor_rev_for, read_document
from plugins.corpus.preparation.readers import local_ocr as adapter
from plugins.corpus.preparation.readers.base import CandidateUnit, ReaderIssue, ReaderResult
from plugins.corpus.preparation.structure import TextOrigin
from plugins.local_ocr import client, service


@pytest.fixture(autouse=True)
def disabled(monkeypatch):
    monkeypatch.setenv("CORPUS_LOCAL_OCR_ENABLED", "0")


def response():
    return {
        "status": "ok",
        "artifact_id": "a" * 64,
        "lines": ["native words", "new 42.5%"],
        "scores": [0.99, 0.99],
        "boxes_normalized_input": [
            [[0.1, 0.1], [0.5, 0.1], [0.5, 0.2], [0.1, 0.2]],
            [[0.1, 0.4], [0.5, 0.4], [0.5, 0.5], [0.1, 0.5]],
        ],
    }


def test_spatial_native_coverage_suppresses_only_native_words():
    result = adapter.supplemental_lines(response(), [[0.1, 0.1, 0.3, 0.2], [0.3, 0.1, 0.5, 0.2]])
    assert [r[1] for r in result] == ["new 42.5%"]


def test_invalid_coordinate_rejected():
    data = response()
    data["boxes_normalized_input"][0][0][0] = float("nan")
    with pytest.raises(ValueError):
        adapter.supplemental_lines(data, [])


def sample(tmp_path):
    path = tmp_path / "page.pdf"
    with pymupdf.open() as pdf:
        pdf.new_page(width=200, height=200)
        pdf.save(path)
    unit = CandidateUnit(
        0, "paragraph", UnitStatus.KEPT, (), "native untouched", UnitLocation(page=1)
    )
    native = ReaderResult(
        DocumentFormat.PDF,
        "native-rev",
        str(path),
        1,
        (unit,),
        (ReaderIssue("image_only_page", "page:1", "original gap"),),
    )
    return path, native


def test_native_and_structure_preserved_with_explicit_ocr_origin(monkeypatch, tmp_path):
    path, native = sample(tmp_path)
    monkeypatch.setattr(adapter, "configured_release", lambda: "pinned")
    monkeypatch.setattr(adapter, "recognize_page", lambda *_: response())
    result = adapter.enrich(native, path)
    assert result.units[0] == native.units[0]
    assert result.structure.nodes[0] == native.structure.nodes[0]
    assert all(n.text_origin == TextOrigin.OCR for n in result.structure.nodes[1:])
    assert result.issues[0] == native.issues[0]
    assert result.extractor_rev == "native-rev+local-ocr-supplement-1:pinned"
    assert result.units[1].location.element.startswith("local_ocr:")


@pytest.mark.parametrize("status", ["timeout", "error", "busy"])
def test_transient_failure_never_becomes_reusable_parse_checkpoint(monkeypatch, tmp_path, status):
    path, native = sample(tmp_path)
    monkeypatch.setattr(adapter, "configured_release", lambda: "pinned")
    monkeypatch.setattr(adapter, "recognize_page", lambda *_: {"status": status})
    with pytest.raises(RuntimeError, match="no reusable"):
        adapter.enrich(native, path)


def test_unknown_keeps_native_gap_and_records_reason(monkeypatch, tmp_path):
    path, native = sample(tmp_path)
    monkeypatch.setattr(adapter, "configured_release", lambda: "pinned")
    monkeypatch.setattr(
        adapter,
        "recognize_page",
        lambda *_: {"status": "orientation_unknown", "artifact_id": "a" * 64},
    )
    result = adapter.enrich(native, path)
    assert result.units == native.units
    assert result.issues[0] == native.issues[0]
    assert result.issues[-1].code == "local_ocr_unresolved"


def test_disabled_preserves_exact_reader_result(monkeypatch, tmp_path):
    path, native = sample(tmp_path)
    unused = Mock(side_effect=AssertionError("no calls"))
    monkeypatch.setattr(adapter, "recognize_page", unused)
    assert adapter.enrich(native, path) is native
    unused.assert_not_called()


def test_configured_version_invalidates_checkpoints(monkeypatch, tmp_path):
    path, _ = sample(tmp_path)
    before = extractor_rev_for(DocumentFormat.PDF)
    monkeypatch.setenv("CORPUS_LOCAL_OCR_ENABLED", "1")
    monkeypatch.setenv("CORPUS_LOCAL_OCR_RELEASE", "pinned")
    monkeypatch.setenv("READDOC_OCR_URL", "http://localhost:8780")
    assert extractor_rev_for(DocumentFormat.PDF) != before
    # A blank page has no image targets; no OCR request is needed.
    assert read_document(path).extractor_rev == extractor_rev_for(DocumentFormat.PDF)


def test_service_failure_is_persisted_and_retryable(monkeypatch, tmp_path):
    monkeypatch.setattr(service, "ROOT", tmp_path)
    mock = Mock(side_effect=subprocess.TimeoutExpired("ocr", 90))
    monkeypatch.setattr(service.subprocess, "run", mock)
    first = service.process(b"%PDF-fake", 1)
    second = service.process(b"%PDF-fake", 1)
    assert first["status"] == second["status"] == "timeout"
    assert mock.call_count == 2
    assert (tmp_path / first["artifact_id"] / "response.json").is_file()


def test_client_rejects_wrong_release_and_source(monkeypatch, tmp_path):
    path, _ = sample(tmp_path)
    monkeypatch.setenv("CORPUS_LOCAL_OCR_ENABLED", "1")
    monkeypatch.setenv("CORPUS_LOCAL_OCR_RELEASE", "pinned")
    monkeypatch.setenv("READDOC_OCR_URL", "http://localhost:8780")
    import io

    monkeypatch.setattr(
        client.urllib.request,
        "urlopen",
        lambda *a, **k: io.BytesIO(json.dumps({"ocr_release": "wrong"}).encode()),
    )
    with pytest.raises(ValueError, match="provenance"):
        client.recognize_page(path, 1)


def reader_bundle():
    from plugins.tools._doc_reader import reader_src

    namespace = {"__name__": "test_reader"}
    exec(compile(reader_src(), "<reader>", "exec"), namespace)
    return namespace


def test_local_deep_reads_mixed_page_despite_text_route(monkeypatch, tmp_path):
    monkeypatch.setenv("READDOC_LOCAL_OCR_RELEASE", "pinned")
    ns = reader_bundle()
    ns["_pdf_route_decide"] = lambda *_: {"route": "text", "text": "native"}
    ns["_text_body"] = lambda *_: "native"
    ns["_ocr_page"] = lambda *_: "image text"
    body, tag, is_text = ns["_deep_page"]("file", 3, 100, 100, str(tmp_path))
    assert "native" in body and "image text" in body
    assert tag == " | OCR" and not is_text


def test_local_service_receives_exact_page_without_pdfseparate(monkeypatch, tmp_path):
    import hashlib
    import io
    import urllib.request

    monkeypatch.setenv("READDOC_LOCAL_OCR_RELEASE", "pinned")
    monkeypatch.setenv("READDOC_OCR_URL", "http://localhost:8780")
    path, _ = sample(tmp_path)
    ns = reader_bundle()
    ns["_one_page_pdf"] = Mock(side_effect=AssertionError("must not require Poppler"))

    def request(req, **kwargs):
        assert req.headers["X-ocr-page"] == "3"
        assert req.data == path.read_bytes()
        return io.BytesIO(
            json.dumps(
                {
                    "status": "ok",
                    "text": "recognized",
                    "page": 3,
                    "ocr_release": "pinned",
                    "source_pdf_sha256": hashlib.sha256(req.data).hexdigest(),
                }
            ).encode()
        )

    monkeypatch.setattr(urllib.request, "urlopen", request)
    assert "recognized" in ns["_ocr_page"](str(path), 3, str(tmp_path))


def test_local_unknown_remains_visible_in_read_file(monkeypatch, tmp_path):
    monkeypatch.setenv("READDOC_LOCAL_OCR_RELEASE", "pinned")
    ns = reader_bundle()
    ns["_pdf_route_decide"] = lambda *_: {"route": "text", "text": "native"}
    ns["_ocr_page"] = Mock(side_effect=ns["_LocalOCRFailure"]("orientation_unknown"))
    body, tag, _ = ns["_deep_page"]("file", 3, 100, 100, str(tmp_path))
    assert "orientation_unknown" in body and "native" in body
    assert tag == " | OCR failed"


def test_ocr_text_never_implies_full_visual_coverage():
    from plugins.tools.read_file import _structured_read_outcome

    result = _structured_read_outcome("a.pdf", "image", None, "figure not read: OCR text only")
    assert json.loads(result.result)["coverage"]["document_complete"] is False


def test_ocr_workdir_is_bound_to_content_not_filename(tmp_path):
    ns = reader_bundle()
    first = tmp_path / "first" / "same.pdf"
    second = tmp_path / "second" / "same.pdf"
    for p, text in [(first, "first"), (second, "second")]:
        p.parent.mkdir()
        p.write_text(text)
    assert ns["_ocr_workdir"](str(first)) != ns["_ocr_workdir"](str(second))


def test_local_multi_page_read_declares_deferred_pages(monkeypatch):
    monkeypatch.setenv("READDOC_LOCAL_OCR_RELEASE", "pinned")
    ns = reader_bundle()
    ns.update(
        _pdf_page_count=lambda _: 3,
        _pinfo=lambda _: {},
        _ocr_workdir=lambda _: "/tmp",
        _pdf_doc_head=lambda *_: [],
        _deep_page=Mock(return_value=("ocr", " | OCR", False)),
    )
    result = ns["_pdf_to_md"]("file", "image")
    assert "not read: pages 2,3" in result
    assert ns["_deep_page"].call_count == 1


def test_ocr_provenance_survives_compact_fetch():
    import importlib
    from types import SimpleNamespace

    fetch = importlib.import_module("plugins.tools.corpus_fetch")
    evidence = SimpleNamespace(units=[SimpleNamespace(element="local_ocr:line:1")])
    full = {"ok": True, "text": "recognized", **fetch._ocr_metadata(evidence)}
    compact = fetch._compact_payload(full)
    assert compact["text"] == "recognized"
    assert compact["ocr_unverified"] is True
    envelope = json.loads(fetch._compact_envelope({"items": [full]}))
    assert envelope["items"][0]["ocr_unverified"] is True
    assert fetch._ocr_metadata(SimpleNamespace(units=[SimpleNamespace(element=None)])) == {}
