"""Exercise the actual SDK adapter and extraction boundary without network or secrets."""

from types import SimpleNamespace

import httpx
import openai
import pytest

from plugins.corpus.claims import build_default_llm
from plugins.corpus.evidence_pipeline import build_evidence_run


def adapter(monkeypatch, *, content="", finish="length", error=None):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-secret")
    monkeypatch.setenv("OPENAI_MODEL", "test-model")
    monkeypatch.setenv("CORPUS_LLM_THINKING", "enabled")

    def create(**kwargs):
        if error:
            raise error
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    finish_reason=finish,
                    message=SimpleNamespace(
                        content=content, reasoning_content="private reasoning must not be persisted"
                    ),
                )
            ],
            usage=SimpleNamespace(
                prompt_tokens=937,
                completion_tokens=4096,
                completion_tokens_details=SimpleNamespace(reasoning_tokens=4096),
            ),
        )

    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    return build_default_llm()


def test_empty_length_response_preserves_safe_diagnostics(monkeypatch):
    result = adapter(monkeypatch)("private source")
    assert isinstance(result, str) and result == ""
    assert result.diagnostics["finish_reason"] == "length"
    assert result.diagnostics["reasoning_tokens"] == 4096
    assert result.diagnostics["content_chars"] == 0
    assert "private" not in str(result.diagnostics)


@pytest.mark.parametrize(
    "content,finish,reason",
    [
        ("[]", "length", "output_truncated"),
        ("", "stop", "empty_response"),
        ("not json", "stop", "invalid_json"),
    ],
)
def test_failed_output_is_not_a_successful_empty_packet(
    tmp_path, monkeypatch, content, finish, reason
):
    path = tmp_path / "source.md"
    path.write_text("2026 年8 月美国新增非农就业16.2万人。", encoding="utf-8")
    run = build_evidence_run(
        path, llm=adapter(monkeypatch, content=content, finish=finish), max_prose_calls=1
    )
    assert run.packet_runs[0].status == "failed"
    assert reason in run.packet_runs[0].reasons
    assert run.packet_runs[0].diagnostics["finish_reason"] == finish


def test_timeout_records_type_not_provider_message(tmp_path, monkeypatch):
    path = tmp_path / "source.md"
    path.write_text("2026 年8 月美国新增非农就业16.2万人。", encoding="utf-8")
    error = openai.APITimeoutError(request=httpx.Request("POST", "https://private.example/token"))
    run = build_evidence_run(path, llm=adapter(monkeypatch, error=error), max_prose_calls=1)
    assert run.packet_runs[0].diagnostics["error_type"] == "APITimeoutError"
    assert "private.example" not in run.model_dump_json()


def test_macro_raw_aliases_and_layout_whitespace_resolve_to_exact_source(tmp_path):
    import json

    path = tmp_path / "2026-09-05_macro.md"
    source = "2026 年8 月美国新增非农就业16.2\n万人，预期5.6 万人。"
    path.write_text(source, encoding="utf-8")
    payload = [
        {
            "claim_text": "美国非农实际值16.2万人",
            "evidence_quote": "新增非农就业16.2万人",
            "scope": "macro",
            "subject_raw": "美国",
            "subject": "US",
            "metric_raw": "新增非农就业",
            "metric": "NFP",
            "value_text": "16.2",
            "unit_raw": "万人",
            "period_raw": "2026年8月",
            "qualifiers": {"state": "actual"},
        }
    ]
    run = build_evidence_run(path, llm=lambda _: json.dumps(payload), max_prose_calls=1)
    fact = run.facts[0]
    assert (fact.claim.subject, fact.claim.metric) == ("US", "NFP")
    assert (fact.claim.subject_raw, fact.claim.metric_raw) == ("美国", "新增非农就业")
    assert fact.claim.quality_status == "ok"
    assert fact.claim.evidence_quote in source
    assert fact.evidence_alignment["model_quote"] == "新增非农就业16.2万人"
    assert "period_not_in_packet" not in fact.reasons


def test_whitespace_alignment_must_not_invent_a_numeric_token(tmp_path):
    import json

    path = tmp_path / "source.md"
    path.write_text("2026年8月美国非农新增就业1 20万人。", encoding="utf-8")
    payload = [
        {
            "claim_text": "美国新增非农120万人",
            "evidence_quote": "非农新增就业120万人",
            "scope": "macro",
            "subject": "US",
            "metric": "NFP",
            "value_text": "120",
            "unit_raw": "万人",
            "period_raw": "2026年8月",
        }
    ]
    run = build_evidence_run(path, llm=lambda _: json.dumps(payload), max_prose_calls=1)
    assert run.facts[0].claim.quality_status == "rejected"


def test_glm53_corpus_default_is_low_effort_without_disabled_thinking(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "test-not-a-secret")
    monkeypatch.setenv("OPENAI_MODEL", "glm-5.3-flash")
    monkeypatch.delenv("CORPUS_LLM_THINKING", raising=False)
    monkeypatch.delenv("CORPUS_LLM_REASONING_EFFORT", raising=False)
    requests = []

    def create(**kwargs):
        requests.append(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(finish_reason="stop", message=SimpleNamespace(content="[]"))],
            usage=None,
        )

    monkeypatch.setattr(
        openai,
        "OpenAI",
        lambda **kwargs: SimpleNamespace(
            chat=SimpleNamespace(completions=SimpleNamespace(create=create))
        ),
    )
    result = build_default_llm()("source")
    assert requests[0]["extra_body"] == {"reasoning_effort": "low"}
    assert result.diagnostics["reasoning_effort"] == "low"


def test_model_supplied_year_without_source_anchor_is_not_a_normalized_period(tmp_path):
    import json

    path = tmp_path / "2026-09-06_macro.md"
    path.write_text("美国8月新增非农就业16.2万人。", encoding="utf-8")
    payload = [
        {
            "claim_text": "美国8月非农16.2万人",
            "evidence_quote": "新增非农就业16.2万人",
            "scope": "macro",
            "subject": "US",
            "metric": "NFP",
            "value_text": "16.2",
            "unit_raw": "万人",
            "period_raw": "2026年8月",
        }
    ]
    run = build_evidence_run(path, llm=lambda _: json.dumps(payload), max_prose_calls=1)
    assert run.facts[0].claim.period_end is None
    assert run.facts[0].claim.period_raw == "2026年8月"
    assert run.facts[0].claim.quality_status == "review"
    assert "period_unanchored" in run.facts[0].reasons


@pytest.mark.parametrize("version", [1, 2, 3, 4])
def test_old_evidence_identity_contracts_remain_readable(tmp_path, version):
    from plugins.corpus.evidence import fingerprint
    from plugins.corpus.evidence_pipeline import EvidenceRun

    path = tmp_path / "source.md"
    path.write_text("2026年8月美国非农16.2万人", encoding="utf-8")
    run = build_evidence_run(path)
    payload = run.model_dump(mode="json")
    payload["pipeline_version"] = f"evidence-pipeline-{version}"
    payload.pop("run_id")
    if version <= 2:
        for packet in payload["packet_runs"]:
            packet.pop("diagnostics")
    if version <= 3:
        for fact in payload["facts"]:
            fact.pop("evidence_alignment")
    payload["run_id"] = fingerprint(payload)
    restored = EvidenceRun.model_validate(payload)
    restored.verify_identity()
    with pytest.raises(ValueError, match="hash mismatch"):
        restored.model_copy(update={"model": "tampered"}).verify_identity()


@pytest.mark.parametrize("content", ["[null]", "[1]", "[{}]"])
def test_nonempty_invalid_schema_cannot_become_empty_success(tmp_path, monkeypatch, content):
    path = tmp_path / "source.md"
    path.write_text("2026年8月美国非农16.2万人", encoding="utf-8")
    run = build_evidence_run(
        path, llm=adapter(monkeypatch, content=content, finish="stop"), max_prose_calls=1
    )
    assert run.packet_runs[0].status == "failed"


def test_explicit_empty_array_with_stop_is_legitimate_empty_success(tmp_path, monkeypatch):
    path = tmp_path / "source.md"
    path.write_text("2026年8月美国非农16.2万人", encoding="utf-8")
    run = build_evidence_run(
        path, llm=adapter(monkeypatch, content="[]", finish="stop"), max_prose_calls=1
    )
    assert run.packet_runs[0].status == "completed"
    assert not run.facts
