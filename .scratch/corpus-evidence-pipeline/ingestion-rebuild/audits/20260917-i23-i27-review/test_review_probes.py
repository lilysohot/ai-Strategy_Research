"""I2-3/I2-7 review: synthetic inputs, zero database/model calls.

Assertions describe acceptance requirements, not the existing wrong behavior.
"""

from types import SimpleNamespace
from unittest.mock import MagicMock
from pathlib import Path
import runpy

import pytest

from plugins.corpus.preparation.admission import ProbeInput
from plugins.corpus.preparation.contract import PublicationDateStatus
from plugins.corpus.preparation.engine import _probe_input
from plugins.corpus.preparation.publication import probe_report_publication
from plugins.corpus.service import CorpusService


@pytest.mark.parametrize("review_ids", [("new-exclusion-review",), ("new-scope-review",)])
def test_reingestion_must_evaluate_explicit_new_review(tmp_path, monkeypatch, review_ids):
    path = tmp_path / "report.md"
    path.write_text("# synthetic report\nunchanged source bytes", encoding="utf-8")
    store = MagicMock()
    store.get_publication.return_value = SimpleNamespace(active_build_id="old-build")
    store.get_source.return_value = SimpleNamespace(original_names=(path.name,))
    service = CorpusService("postgresql://unused/unused")
    monkeypatch.setattr(service, "_preparation_context", lambda: (store, object()))
    planner = MagicMock(side_effect=RuntimeError("planner-reached"))
    monkeypatch.setattr("plugins.corpus.service.plan_builds", planner)
    try:
        service.ingest_path(path, review_decision_ids=review_ids)
    except RuntimeError as exc:
        assert str(exc) == "planner-reached"
    assert planner.called, "Existing publication bypassed the explicitly supplied new review"


def test_filename_cannot_become_publication_evidence():
    descriptor = SimpleNamespace(title="2026.08.17-某券商-公司研究.md")
    # No date or title in actual canonical units.
    payload = _probe_input(descriptor, SimpleNamespace(units=()))
    publication = probe_report_publication(payload)
    assert publication.status is PublicationDateStatus.UNKNOWN, publication


def test_event_date_is_not_report_publication():
    payload = ProbeInput(
        title="公司经营回顾",
        head_text="公司于2020年1月2日成立，本报告回顾其发展历史。",
        body_lines=(), heading_texts=(),
    )
    publication = probe_report_publication(payload)
    assert publication.status is PublicationDateStatus.UNKNOWN, publication


def test_document_text_must_not_query_legacy_blocks(monkeypatch):
    service = CorpusService("postgresql://unused/unused")
    conn, cur = MagicMock(), MagicMock()
    conn.__enter__.return_value = conn
    conn.cursor.return_value = cur
    cur.__enter__.return_value = cur
    cur.fetchone.return_value = {"t": "old independent body"}
    monkeypatch.setattr(service, "_connect", lambda: conn)
    service.document_text("cv2:" + "a" * 64)
    statements = [call.args[0] for call in cur.execute.call_args_list]
    assert not any("FROM blocks" in statement for statement in statements), statements


def test_extract_claims_does_not_reparse_source(tmp_path, monkeypatch):
    from plugins.corpus import evidence_pipeline

    path = tmp_path / "report.md"
    path.write_text("# synthetic company report\n收入保持稳定。", encoding="utf-8")
    parser = MagicMock(wraps=evidence_pipeline.parse_evidence)
    monkeypatch.setattr(evidence_pipeline, "parse_evidence", parser)
    service = CorpusService("postgresql://unused/unused")
    service.extract_claims(path, persist=False, max_prose_calls=0)
    assert not parser.called, "I2-7 still creates independent Evidence text by parsing raw files"


def test_explicit_report_date_control():
    payload = ProbeInput(
        title="公司研究", head_text="报告发布日期：2026年9月17日", body_lines=(), heading_texts=()
    )
    assert probe_report_publication(payload).value == "2026-09-17"


def test_freeze_detects_new_publication_module_drift(monkeypatch):
    root = Path(__file__).resolve().parents[5]
    target = root / "plugins/corpus/preparation/publication.py"
    read_bytes = Path.read_bytes

    def simulated_drift(path):
        data = read_bytes(path)
        return data + b"\n# simulated drift; disk untouched\n" if path == target else data

    monkeypatch.setattr(Path, "read_bytes", simulated_drift)
    with pytest.raises(SystemExit) as result:
        runpy.run_path(
            str(root / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"),
            run_name="__main__",
        )
    assert result.value.code != 0
