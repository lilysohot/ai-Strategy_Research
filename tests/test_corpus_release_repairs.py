"""Regressions for the 2026-11-17 release blockers, through real entry points."""

import sys
from unittest.mock import MagicMock, Mock

import pytest
from docx import Document
from docx.oxml import OxmlElement

from plugins.corpus.preparation.readers.docx_reader import read_docx
from plugins.corpus.retrieval import cli, contextual, contextual_pg
from plugins.corpus.retrieval.embedding import VectorConfig
from plugins.corpus.service import CorpusService


@pytest.fixture
def command(monkeypatch):
    config = VectorConfig(target_db="vector_pilot_test", dimensions=2)
    monkeypatch.setattr(cli, "load_dotenv", lambda: None)
    monkeypatch.setattr(VectorConfig, "from_env", lambda: config)
    monkeypatch.setattr(cli, "pilot_dsn", lambda cfg: "unused")
    monkeypatch.setattr(cli, "VectorIndex", Mock())
    monkeypatch.setattr(contextual_pg, "status", lambda *a, **kw: {})
    monkeypatch.setattr(
        contextual.NoteConfig,
        "from_env",
        lambda: contextual.NoteConfig(
            api_url="https://example.test", model="test", chunks_per_request=12
        ),
    )

    def run(*args):
        monkeypatch.setattr(sys, "argv", ["retrieval", *args])
        return cli.main()

    return run


def test_generate_honors_explicit_batch_size_and_reports_incomplete(command, monkeypatch):
    generate = Mock(return_value={"missing": 1, "error_code": None})
    monkeypatch.setattr(contextual_pg, "generate", generate)
    assert command("context-generate", "--chunks-per-request", "1") == 1
    assert generate.call_args.args[2].chunks_per_request == 1


def test_generate_preserves_env_default(command, monkeypatch):
    generate = Mock(return_value={"missing": 0})
    monkeypatch.setattr(contextual_pg, "generate", generate)
    assert command("context-generate") == 0
    assert generate.call_args.args[2].chunks_per_request == 12


def test_pack_forwards_retry_flags(command, monkeypatch, tmp_path):
    build = Mock(return_value={})
    monkeypatch.setattr(contextual_pg, "build_pack", build)
    assert (
        command(
            "native-pack",
            "--out",
            str(tmp_path),
            "--max-requests",
            "1",
            "--retry-uncertain",
            "--retry-failed",
        )
        == 0
    )
    assert build.call_args.kwargs["retry_uncertain"] is True
    assert build.call_args.kwargs["retry_failed"] is True


def test_unrelated_commands_reject_ignored_flags(command):
    with pytest.raises(SystemExit) as exc:
        command("context-status", "--retry-uncertain")
    assert exc.value.code == 2


def test_docx_bookmarks_are_not_gaps_and_do_not_shift_coordinates(tmp_path):
    document = Document()
    document.add_paragraph("第一段")
    marker = OxmlElement("w:bookmarkEnd")
    document.element.body.insert(1, marker)
    document.add_paragraph("第二段")
    path = tmp_path / "bookmarks.docx"
    document.save(path)
    result = read_docx(path)
    assert not result.issues
    assert [u.location.element for u in result.units] == ["body[0]", "body[2]"]


def test_docx_content_disguised_as_bookmark_still_is_a_gap(tmp_path):
    document = Document()
    marker = OxmlElement("w:bookmarkEnd")
    marker.append(OxmlElement("w:drawing"))
    document.element.body.insert(0, marker)
    path = tmp_path / "invalid.docx"
    document.save(path)
    assert read_docx(path).issues[0].code == "unknown_body_element"


def test_csv_backup_cannot_claim_new_chain_coverage(monkeypatch, tmp_path):
    service = CorpusService("unused")
    conn = MagicMock()
    conn.__enter__.return_value = conn
    conn.execute.return_value.fetchone.return_value = {"present": True}
    monkeypatch.setattr(service, "_connect", lambda: conn)
    monkeypatch.setattr(service, "_pg_tool", lambda name: None)
    csv = Mock()
    monkeypatch.setattr(service, "_backup_csv", csv)
    with pytest.raises(RuntimeError, match="new_chain_requires_pg_dump"):
        service.backup(tmp_path, mode="auto")
    csv.assert_not_called()


@pytest.mark.parametrize(
    "text",
    [
        "2026.11.1310:16期五。公司扩展产能。",
        "预计2026-28年收入分别为10亿元、12亿元、14亿元。",
        "东北证券预计公司归母净利润增长。",
    ],
)
def test_extractive_recovery_is_exact_and_tamper_evident(text):
    note, provenance = contextual.extract_note(text, text)
    contextual.validate_stored_note(note, text, provenance)
    with pytest.raises(contextual.ContextNoteError, match="extractive_context_invalid"):
        contextual.validate_stored_note(note + "新增", text, provenance)
    with pytest.raises(contextual.ContextNoteError, match="extractive_context_invalid"):
        contextual.validate_stored_note(note, text + "改动", provenance)


def test_extract_does_not_cut_long_sentences_or_invent_facts():
    with pytest.raises(contextual.ContextNoteError, match="extractive_context_unavailable"):
        contextual.extract_note("扩" * 200, "扩" * 200, ["不存在的标题"])
    with pytest.raises(contextual.ContextNoteError, match="note_number_not_in_source"):
        contextual.validate_note("2028年收入20亿元", "2026-28年收入10亿元")


def test_historical_source_review_note_uses_prose_validation_not_extractive_ranges():
    contextual.validate_stored_note(
        "公司2026年收入增长计划", "公司2026年收入增长计划", {"method": "agent_source_review"}
    )
    with pytest.raises(contextual.ContextNoteError, match="note_number_not_in_source"):
        contextual.validate_stored_note(
            "公司2027年收入增长计划", "公司2026年收入增长计划", {"method": "agent_source_review"}
        )
