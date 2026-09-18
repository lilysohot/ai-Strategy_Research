"""I2-7：研报发布日期探查（契约 §4.3 唯一落点；doc_id 前缀派生废弃）。

R4 复核（2026-09-17）：只认原文**显式报告日期声明**（报告发布日期/发布日期/出具
日期/落款日期等字段）；文件名日期前缀、正文历史事件日期（成立日/财报截止日/回顾）
均不构成发布依据，歧义/无声明落 unknown。已知日期必须带原文依据 evidence_refs。
"""

from plugins.corpus.preparation.admission import ProbeInput
from plugins.corpus.preparation.contract import (
    PublicationDateOrigin,
    PublicationDatePrecision,
    PublicationDateStatus,
)
from plugins.corpus.preparation.publication import probe_report_publication


def _payload(title: str = "", head: str = "", *lines: str) -> ProbeInput:
    return ProbeInput(title=title, head_text=head, body_lines=tuple(lines), heading_texts=())


def test_explicit_report_date_declaration() -> None:
    rp = probe_report_publication(_payload("公司研究", "报告发布日期：2026年9月17日"))
    assert rp.status is PublicationDateStatus.KNOWN
    assert rp.value == "2026-09-17"
    assert rp.precision is PublicationDatePrecision.DATE
    assert rp.origin is PublicationDateOrigin.SOURCE_EXPLICIT
    assert rp.evidence_refs == ("report_date=2026-09-17:head[0:400]",)


def test_filename_date_is_not_publication_evidence() -> None:
    # 文件名日期前缀不是原文依据（R4）：仅文件名，无正文 → unknown。
    rp = probe_report_publication(_payload("2026.08.17-某券商-公司研究.md"))
    assert rp.status is PublicationDateStatus.UNKNOWN
    assert rp.value is None
    assert rp.evidence_refs == ()


def test_event_date_is_not_report_publication() -> None:
    # 正文历史事件日期（成立日）不等于报告发布日期。
    rp = probe_report_publication(
        _payload("公司经营回顾", "公司于2020年1月2日成立，本报告回顾其发展历史。")
    )
    assert rp.status is PublicationDateStatus.UNKNOWN


def test_explicit_date_in_body_line_with_locator() -> None:
    rp = probe_report_publication(_payload("无题", "头部无声明", "发布日期：2026/09/08"))
    assert rp.status is PublicationDateStatus.KNOWN
    assert rp.value == "2026-09-08"
    assert rp.evidence_refs == ("report_date=2026-09-08:lines[0]",)


def test_invalid_declaration_skipped_until_valid_one() -> None:
    rp = probe_report_publication(
        _payload("无题", "报告发布日期：2026/13/45", "出具日期：2026-09-08")
    )
    assert rp.value == "2026-09-08"


def test_financial_period_end_date_is_not_publication() -> None:
    # 财报截止日/期间日期不是报告发布日期。
    rp = probe_report_publication(_payload("无题", "财报截止日：2026/06/30", "正文无发布声明"))
    assert rp.status is PublicationDateStatus.UNKNOWN


def test_absent_declaration_explicit_unknown() -> None:
    rp = probe_report_publication(_payload("无题", "头部没有日期", "正文也没有"))
    assert rp.status is PublicationDateStatus.UNKNOWN
    assert rp.value is None
    assert rp.precision is PublicationDatePrecision.UNKNOWN
    assert rp.origin is None
    assert rp.evidence_refs == ()
