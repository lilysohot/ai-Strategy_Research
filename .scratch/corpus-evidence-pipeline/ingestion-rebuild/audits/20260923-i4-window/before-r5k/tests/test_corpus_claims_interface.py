"""The canonical service/CLI seam; old tables must never be an implicit fallback."""

import json
import sys
from dataclasses import replace
from decimal import Decimal
from unittest.mock import Mock

import pytest

from plugins.corpus.evidence import fingerprint
from plugins.corpus.evidence_pipeline import EvidenceRun, project_claims
from plugins.corpus.service import CorpusService, _main


@pytest.fixture
def source(tmp_path):
    path = tmp_path / "2026-08-16_600519.SH.md"
    # I2-7：文件名日期前缀会被 _title_from_filename 剥掉、不再派生 published，
    # 来源日期必须由正文显式给出（source_explicit 语义）。
    path.write_text(
        "# 600519.SH\n发布日期：2026-08-16。\n2025A 营业收入100元。2026E 营业收入120元。",
        encoding="utf-8",
    )
    return path


def response(_prompt):
    return json.dumps(
        [
            {
                "claim_text": f"{period} 营业收入{value}元",
                "evidence_quote": f"{period} 营业收入{value}元",
                "scope": "company",
                "subject": "600519.SH",
                "metric": "营业收入",
                "value_text": f"{value}元",
                "period_raw": period,
                "kind": kind,
            }
            for period, value, kind in [("2025A", "100", "fact"), ("2026E", "120", "forecast")]
        ],
        ensure_ascii=False,
    )


@pytest.fixture
def service(monkeypatch, source):
    svc = CorpusService("postgresql://unused")
    stored = {}

    def save(run):
        run.verify_identity()
        stored[run.run_id] = run.model_dump_json()
        return run.run_id

    def load(run_id):
        return EvidenceRun.model_validate_json(stored[run_id])

    # R1：extract_claims 由同源 corpus_units 投影，不再二次解析原文件。这里模拟
    # 已入链的活动 build：单 prose 单元（raw_text=源全文），发布日期读 admission
    # report_publication（R4 唯一落点）。_connect 仍作为「旧 blocks 直连」的绊线。
    def units_for(source_id):
        del source_id
        return [{"seq": 0, "locator": "document", "text": source.read_text(encoding="utf-8")}]

    def published_for(source_id):
        del source_id
        return "2026-08-16"  # 来源正文「发布日期：2026-08-16」→ report_publication.value

    monkeypatch.setattr(svc, "save_evidence_run", save)
    monkeypatch.setattr(svc, "load_evidence_run", load)
    monkeypatch.setattr(svc, "_connect", Mock(side_effect=AssertionError("legacy DB access")))
    monkeypatch.setattr(svc, "_active_build_units", units_for)
    monkeypatch.setattr(svc, "_active_report_publication", published_for)
    return svc


def rehash(run, **changes):
    changed = run.model_copy(update=changes)
    payload = changed.model_dump(mode="json")
    payload.pop("run_id")
    return changed.model_copy(update={"run_id": fingerprint(payload)})


def test_canonical_extract_read_fetch_and_calculate(service, source):
    run = service.extract_claims(source, llm=response, model="fake", max_prose_calls=1)
    result = service.claims_of(run_id=run.run_id, purpose="calculate", limit=1)
    assert result["total"] == 2 and result["has_more"]
    assert result["coverage_status"] == "available"
    assert result["scope"]["completeness_applies_to"] == "selected_source_scope_only"
    assert result["complete"] and result["validation_current"]
    first = result["items"][0]
    assert first["source_rev"] == run.document.source_rev
    assert first["parse_rev"] == run.document.parse_rev
    evidence = service.fetch_evidence(run.run_id, first["packet_id"])
    assert first["evidence_quote"] in evidence["text"]
    second = service.claims_of(run_id=run.run_id, purpose="calculate", offset=1)["items"][0]
    calculation = service.derive_claims(
        run_id=run.run_id,
        formula="revenue_growth",
        input_ids=(second["fact_id"], first["fact_id"]),
    )
    assert calculation.value == Decimal("20")
    assert calculation.run_id == run.run_id
    assert service.claim_observation_projection(run_id=run.run_id)["total"] == 2
    assert service.claims_of(run_id=run.run_id, subject="other")["total"] == 0
    assert service.claims_of(run_id=run.run_id, kind="forecast")["total"] == 1


def test_default_budget_is_deferred_and_no_legacy_fallback(service, source, monkeypatch):
    monkeypatch.setattr(
        "plugins.corpus.service.build_default_llm", Mock(side_effect=AssertionError)
    )
    run = service.extract_claims(source)
    result = service.claims_of(run_id=run.run_id)
    assert not result["items"] and result["coverage_status"] == "unknown"
    assert not result["complete"]
    with pytest.raises(KeyError):
        service.claims_of(run_id="legacy-document-id")
    with pytest.raises(TypeError):
        service.claims_of()


def test_quality_ok_is_not_comparison_permission(service, source):
    run = service.extract_claims(source, llm=response, max_prose_calls=1)
    cite_only = tuple(f.model_copy(update={"usable_for": ("cite",)}) for f in run.facts)
    run = rehash(run, facts=cite_only)
    service.save_evidence_run(run)
    assert service.claims_of(run_id=run.run_id)["total"] == 2
    assert service.claim_observation_projection(run_id=run.run_id)["total"] == 0
    with pytest.raises(ValueError, match="not_calculation_ready"):
        service.derive_claims(
            run_id=run.run_id,
            formula="revenue_growth",
            input_ids=tuple(f.fact_id for f in reversed(run.facts)),
        )


@pytest.mark.parametrize("field", ["pipeline_version", "extractor_version", "lint_version"])
def test_old_validation_is_readable_but_not_calculable(service, source, field):
    run = service.extract_claims(source, llm=response, max_prose_calls=1)
    old = rehash(run, **{field: "old-version"})
    service.save_evidence_run(old)
    result = service.claims_of(run_id=old.run_id)
    assert result["total"] == 2 and not result["validation_current"]
    assert result["calculation_ready"] == 0
    assert all(row["usable_for"] == ["cite"] for row in result["items"])
    assert service.claim_observation_projection(run_id=old.run_id)["coverage_status"] == "unknown"
    with pytest.raises(ValueError, match="validation_version_stale"):
        service.derive_claims(run_id=old.run_id, formula="revenue_growth", input_ids=())


def test_rejected_is_audit_only_and_tamper_is_refused(service, source):
    run = service.extract_claims(source, llm=response, max_prose_calls=1)
    facts = tuple(
        f.model_copy(
            update={
                "claim": replace(f.claim, quality_status="rejected"),
                "usable_for": (),
            }
        )
        for f in run.facts
    )
    rejected = rehash(run, facts=facts)
    assert project_claims(rejected, quality_status=None)["total"] == 0
    assert project_claims(rejected, quality_status=None, purpose="audit")["total"] == 2
    with pytest.raises(ValueError, match="hash mismatch"):
        project_claims(run.model_copy(update={"model": "tampered"}))


@pytest.mark.parametrize(
    "kwargs",
    [
        {"purpose": "anything"},
        {"quality_status": "anything"},
        {"kind": "anything"},
        {"limit": 0},
        {"limit": 1001},
        {"offset": -1},
    ],
)
def test_invalid_filters_fail_closed(service, source, kwargs):
    run = service.extract_claims(source)
    with pytest.raises(ValueError):
        service.claims_of(run_id=run.run_id, **kwargs)


@pytest.mark.parametrize(
    "args",
    [
        ["extract-claims"],
        ["extract-claims", "--doc", "legacy-doc"],
        ["extract-claims", "--source", "test.md", "--dry-run"],
        ["extract-claims", "--source", "test.md", "--legacy"],
        ["claims"],
        ["claims", "--doc", "legacy-doc"],
        ["claims", "--legacy", "--purpose", "calculate"],
        ["claims", "--legacy", "--run-id", "test"],
    ],
)
def test_cli_requires_explicit_source_revision_or_legacy(monkeypatch, args):
    monkeypatch.setattr(sys, "argv", ["corpus", *args])
    monkeypatch.setattr("plugins.corpus.service.get_service", Mock(side_effect=AssertionError))
    with pytest.raises(SystemExit) as exc:
        _main()
    assert exc.value.code == 2


def test_cli_default_and_explicit_legacy_routing(service, source, monkeypatch, capsys):
    monkeypatch.setattr("plugins.corpus.service.get_service", lambda _: service)
    monkeypatch.setattr(sys, "argv", ["corpus", "extract-claims", "--source", str(source)])
    assert _main() == 1  # Successfully persisted, but prose intentionally deferred.
    result = json.loads(capsys.readouterr().out)
    monkeypatch.setattr(sys, "argv", ["corpus", "claims", "--run-id", result["run_id"]])
    assert _main() == 0
    assert json.loads(capsys.readouterr().out)["coverage_status"] == "unknown"
    legacy = Mock(return_value=[{"claim_text": "legacy"}])
    monkeypatch.setattr(service, "legacy_claims_of", legacy)
    monkeypatch.setattr(sys, "argv", ["corpus", "claims", "--legacy"])
    assert _main() == 0
    legacy.assert_called_once()


def test_revision_selection_does_not_merge_a_later_failed_run(service, source):
    good = service.extract_claims(source, llm=response, max_prose_calls=1)
    failed = service.extract_claims(source, llm=lambda _: "", max_prose_calls=1)
    assert good.run_id != failed.run_id
    assert service.claims_of(run_id=good.run_id)["total"] == 2
    result = service.claims_of(run_id=failed.run_id)
    assert result["total"] == 0 and result["coverage_status"] == "unknown"
    with pytest.raises(ValueError, match="unknown_fact"):
        service.derive_claims(
            run_id=failed.run_id,
            formula="revenue_growth",
            input_ids=tuple(f.fact_id for f in good.facts),
        )


def test_cli_evidence_and_calculation_share_revision(service, source, monkeypatch, capsys):
    run = service.extract_claims(source, llm=response, max_prose_calls=1)
    monkeypatch.setattr("plugins.corpus.service.get_service", lambda _: service)
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "corpus",
            "claim-evidence",
            "--run-id",
            run.run_id,
            "--packet-id",
            run.facts[0].packet_id,
        ],
    )
    assert _main() == 0
    assert json.loads(capsys.readouterr().out)["packet_id"] == run.facts[0].packet_id
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "corpus",
            "derive-claims",
            "--run-id",
            run.run_id,
            "--formula",
            "revenue_growth",
            "--inputs",
            run.facts[1].fact_id,
            run.facts[0].fact_id,
        ],
    )
    assert _main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["run_id"] == run.run_id and result["value"] == "20.0"


def test_explicit_budget_selects_adapter_but_preview_does_not_write(service, source, monkeypatch):
    adapter = Mock(return_value=response)
    monkeypatch.setattr("plugins.corpus.service.build_default_llm", adapter)
    monkeypatch.setattr("plugins.corpus.service.configured_model", lambda: "fake")
    run = service.extract_claims(source, max_prose_calls=1, persist=False)
    adapter.assert_called_once()
    assert run.model == "fake" and len(run.facts) == 2
    with pytest.raises(KeyError):
        service.claims_of(run_id=run.run_id)


@pytest.mark.parametrize(
    "kwargs",
    [
        {"max_prose_calls": -1},
        {"packet_chars": 99},
        {"packet_chars": 2501},
        {"pages": ()},
    ],
)
def test_invalid_extraction_scope_fails_before_provider(service, source, kwargs, monkeypatch):
    monkeypatch.setattr(
        "plugins.corpus.service.build_default_llm", Mock(side_effect=AssertionError)
    )
    with pytest.raises(ValueError):
        service.extract_claims(source, **kwargs)


def test_extract_claims_projects_from_units_not_reparse(tmp_path, monkeypatch):
    """R1：extract_claims 由同源 corpus_units 投影，禁止二次解析原文件。

    对应审核反例 test_extract_claims_does_not_reparse_source：即使来源未入链
    （units 为空），extract_claims 也绝不调用 parse_evidence 独立解析原文件。
    """
    from plugins.corpus import evidence_pipeline

    path = tmp_path / "report.md"
    path.write_text("# synthetic company report\n收入保持稳定。", encoding="utf-8")
    parser = Mock(wraps=evidence_pipeline.parse_evidence)
    monkeypatch.setattr(evidence_pipeline, "parse_evidence", parser)

    svc = CorpusService("postgresql://unused")
    units_calls = []
    monkeypatch.setattr(
        svc,
        "_active_build_units",
        lambda _: units_calls.append(1) or [],
    )
    monkeypatch.setattr(svc, "_active_report_publication", lambda _: None)

    run = svc.extract_claims(path, persist=False, max_prose_calls=0)
    assert not parser.called, "extract_claims 不应二次解析原文件（parse_evidence）"
    assert units_calls, "extract_claims 应经 _active_build_units 从 units 投影"
    assert run.facts == ()  # 未入链（无 units）→ 空 facts 的确定性空 run
