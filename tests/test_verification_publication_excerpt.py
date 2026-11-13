"""Only the publishable passage is bound verbatim; judging rules never are.

A live run bound ``subject.text`` that carried both the passages and the rubric
("判定标准 … 判 FAIL"). Because a passing ``publication_excerpt`` must appear in
the final answer verbatim, the model had to paste the rubric into the report to
satisfy the check.
"""

import pytest

from frontier_agent.components.agent_bus import AgentBus
from plugins.tools._verification import (
    VerificationCheck,
    bind_checks,
    missing_publication_excerpts,
    split_publication_subject,
)
from tests.test_agent_team_verification import add_job

QUOTES = [
    "「2026 年将首次产生收入，2027 年达到 95 亿美元」",
    "「单位面积发电能力是地面数据中心的 8 倍」",
    "「基准情形对应约 1.43 GW，乐观情形约 0.86 GW」",
]

MIXED_SUBJECT = (
    "以下引文均声称逐字来自该研报原文（用于最终答复，须逐字保真）：\n"
    + "\n".join(f"{index + 1}. {quote}" for index, quote in enumerate(QUOTES))
    + "\n判定标准：逐条对照原文文字（允许全角/半角标点、空格差异）；"
    "凡原文无此句、或意思被改写、或系解读方推断，判 FAIL 并给出原文实际表述。"
)


def planned(check_id: str = "quotes", criterion: str = "Exit quotes verbatim") -> list[dict]:
    return [
        {
            "id": "t1",
            "verification_required": True,
            "verification_requirements": [{"check_id": check_id, "criterion": criterion}],
        }
    ]


def dispatch(bus, spec, tmp_path, work_items):
    return bind_checks(
        [spec],
        bus=bus,
        task_id="run",
        work_items=work_items,
        required=True,
        outputs_root=tmp_path,
    )


def test_mixed_rubric_requires_explicit_separation():
    with pytest.raises(ValueError, match="put rules in criterion"):
        split_publication_subject(MIXED_SUBJECT)


def test_subject_of_only_instructions_is_rejected():
    with pytest.raises(ValueError, match="judging instructions"):
        split_publication_subject("判定标准：判 FAIL 时说明原文实际表述。")


def test_publication_check_rejects_mixed_text_before_binding(tmp_path):
    bus = AgentBus()
    add_job(bus, "source", [])
    spec = VerificationCheck(
        check_id="quotes",
        work_item_id="t1",
        criterion="Exit quotes verbatim",
        subject={"text": MIXED_SUBJECT},
        evidence=[{"job_id": "source"}],
        publication_excerpt=True,
    )
    with pytest.raises(ValueError, match="put rules in criterion"):
        dispatch(bus, spec, tmp_path, planned())


def test_rubric_is_no_longer_required_in_the_final_answer(tmp_path):
    bus = AgentBus()
    add_job(bus, "source", [])
    excerpt = "\n".join(QUOTES)
    criterion = "判定标准：逐条对照原文；不符则判 FAIL。"
    spec = VerificationCheck(
        check_id="quotes",
        work_item_id="t1",
        criterion=criterion,
        subject={"text": excerpt},
        evidence=[{"job_id": "source"}],
        publication_excerpt=True,
    )
    bound, prompt = dispatch(bus, spec, tmp_path, planned(criterion=criterion))
    assert bound[0]["subject"]["text"] == excerpt
    assert bound[0]["criterion"] == criterion
    assert criterion in prompt
    checks = [{**bound[0], "verdict": "pass"}]

    body = "结论如下：\n" + excerpt
    assert missing_publication_excerpts(checks, body) == []
    # The old behaviour required the rubric too, which is what leaked it into prose.
    assert missing_publication_excerpts(checks, body + "\n判定标准：逐条对照。") == []


@pytest.mark.parametrize("condition", [
    "条件：只有取得许可才可实现 1 GW。",
    "说明：上述数字为乐观情景。",
    "要求：必须取得发射许可。",
    "1. 「原文的判定标准是不满足条件则判 FAIL。」",
    "Pass rates depend on operating conditions.",
])
def test_publication_preserves_substantive_conditions(tmp_path, condition):
    bus = AgentBus()
    add_job(bus, "source", [])
    statement = "预计可实现 1 GW。"
    passage = statement + "\n" + condition
    spec = VerificationCheck(
        check_id="quotes", work_item_id="t1", criterion="Exit quotes verbatim",
        subject={"text": passage}, evidence=[{"job_id": "source"}], publication_excerpt=True,
    )
    bound, _ = dispatch(bus, spec, tmp_path, planned())
    assert bound[0]["subject"]["text"] == passage
    checks = [{**bound[0], "verdict": "pass"}]
    assert missing_publication_excerpts(checks, statement) == ["quotes"]
    assert missing_publication_excerpts(checks, passage) == []


def test_non_publication_check_keeps_its_subject_untouched(tmp_path):
    bus = AgentBus()
    add_job(bus, "source", [])
    spec = VerificationCheck(
        check_id="quotes",
        work_item_id="t1",
        criterion="Exit quotes verbatim",
        subject={"text": MIXED_SUBJECT},
        evidence=[{"job_id": "source"}],
    )
    bound, _ = dispatch(bus, spec, tmp_path, planned())
    assert bound[0]["subject"]["text"] == MIXED_SUBJECT
    assert "subject_instructions" not in bound[0]
