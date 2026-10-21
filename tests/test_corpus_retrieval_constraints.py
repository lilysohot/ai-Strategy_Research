"""Identity, role and time boundaries, independent of the 32 pilot questions."""

import pytest

from plugins.corpus.retrieval.constraints import AliasEvidence, ConstraintResolver


@pytest.fixture
def resolver():
    return ConstraintResolver(
        (
            AliasEvidence("示例科技", "示例科技股份有限公司", "unit:full-name"),
            AliasEvidence("示例科技", "300001", "unit:ticker"),
            AliasEvidence("示例科技", "ExampleTech", "unit:english-name"),
            AliasEvidence("平安银行", "000001", "unit:bank-ticker"),
        ),
        ("平安", "国信", "国金"),
    )


@pytest.mark.parametrize("name", ["300001", "示例科技股份有限公司", "exampletech"])
def test_attributed_aliases_match_pronoun_source(resolver, name):
    query = resolver.parse(f"请分析{name} 2024年收入")
    assert [e.identities for e in query.entities] == [("示例科技",)]
    result = resolver.match(query, "2024年公司实现收入增长。", source_company="示例科技")
    assert result.entity_status == "matched"
    assert result.inherited_entities == ("示例科技",)
    assert result.year_status == "matched"


@pytest.mark.parametrize("name", ["13000010", "MyExampleTechOther"])
def test_alias_must_not_match_embedded_code_or_latin_substring(resolver, name):
    assert not resolver.parse(f"{name}收入").entities


def test_aliases_require_provenance():
    with pytest.raises(ValueError):
        AliasEvidence("甲公司", "甲", "")


def test_shared_alias_does_not_choose_an_owner():
    resolver = ConstraintResolver(
        (AliasEvidence("甲公司", "ABC", "a"), AliasEvidence("乙公司", "ABC", "b")), ()
    )
    result = resolver.match(resolver.parse("ABC收入"), "甲公司实现增长。")
    assert result.entity_status == "ambiguous"
    assert result.entity_fraction == 0


@pytest.mark.parametrize("query", ["平安银行2024年利润是多少？", "中国平安的保费收入如何？"])
def test_company_reference_is_not_issuer(resolver, query):
    assert resolver.parse(query).issuers == ()


def test_explicit_issuer_and_company_roles_are_separate(resolver):
    query = resolver.parse("请根据平安证券的报告分析示例科技2024年收入")
    assert query.issuers == ("平安",)
    assert query.entities[0].identities == ("示例科技",)
    result = resolver.match(
        query, "2024年公司实现增长", source_company="示例科技", source_issuer="国信"
    )
    assert result.entity_status == "matched"
    assert result.source_status == "different_source"


def test_bare_issuer_name_does_not_imply_source_role(resolver):
    assert resolver.parse("平安的净利润").issuers == ()


def test_unknown_full_company_name_is_retained(resolver):
    query = resolver.parse("陌生光电股份有限公司2024年收入？")
    assert query.entities[0].identities == ("陌生光电股份有限公司",)
    assert (
        resolver.match(query, "2024年公司实现增长", source_company="示例科技").entity_status
        == "not_observed"
    )


def test_unproven_legal_name_is_not_guessed_from_short_name(resolver):
    query = resolver.parse("示例科技集团有限公司2024年收入")
    assert len(query.entities) == 1
    assert (
        resolver.match(query, "示例科技收入", source_company="示例科技").entity_status
        == "not_observed"
    )


def test_entity_pair_without_separately_keyword(resolver):
    query = resolver.parse("比较华工正源和立讯技术的产品")
    assert {e.identities[0] for e in query.entities} == {"华工正源", "立讯技术"}


def test_year_not_found_is_not_treated_as_match(resolver):
    query = resolver.parse("示例科技2034年实际收入")
    result = resolver.match(query, "2024年公司实现收入增长", source_company="示例科技")
    assert result.year_status == "not_observed"
    assert result.fact_status == "unknown"


def test_history_year_and_current_year_are_distinguished(resolver):
    query = resolver.parse("1997年资本补充用了多少资金")
    assert resolver.match(query, "1997年发行特别国债").year_status == "matched"
    assert resolver.match(query, "2024年发行特别国债").year_status == "not_observed"


def test_ranges_remain_multiple_year_requirements(resolver):
    query = resolver.parse("2020至2022年配额能抵扣2024年清缴吗")
    assert query.years == (2020, 2021, 2022, 2024)
    result = resolver.match(query, "2024年需要清缴")
    assert result.year_status == "partial"
    assert result.year_fraction == 0.25


def test_forecast_does_not_become_actual(resolver):
    query = resolver.parse("2028年已经实际出货了吗？")
    assert query.fact_mode == "verify_actual"
    result = resolver.match(query, "预计2028年出货增加。2024年已经实现收入增长。")
    assert result.fact_status == "forecast_cues"
    assert all("2024" not in clause for clause in result.dated_clauses)


def test_mixed_forecast_and_observation_stays_uncertain(resolver):
    query = resolver.parse("2024年实际收入")
    result = resolver.match(query, "2024年实现增长，预计2024年继续增长。")
    assert result.fact_status == "mixed"


def test_years_are_not_inferred_from_current_clock(resolver):
    assert resolver.parse("今年收入").years == ()
    assert (
        resolver.match(resolver.parse("2024年收入"), "今年实现增长").year_status == "not_observed"
    )


def test_comparison_mentions_are_not_semantic_attribution(resolver):
    query = resolver.parse("示例科技2024年收入")
    result = resolver.match(query, "2024年甲公司收入高于示例科技。")
    # The component records literal entity/year presence, not fact entailment.
    assert result.entity_status == "matched"
    assert result.fact_status == "unknown"


@pytest.mark.parametrize(
    "query", ["国信的这份示例科技中报披露了什么？", "请引用国信对示例科技2024年中报的公司点评"]
)
def test_report_source_does_not_become_part_of_company_name(resolver, query):
    constraint = resolver.parse(query)
    assert constraint.issuers == ("国信",)
    assert [e.identities for e in constraint.entities] == [("示例科技",)]


def test_abbreviated_year_is_possible_not_confirmed_century(resolver):
    result = resolver.match(resolver.parse("2028年实际出货了吗？"), "预计28年实现批量供应。")
    assert result.year_status == "abbreviated"
    assert result.abbreviated_years == (2028,)
    assert result.matched_years == ()
    assert result.fact_status == "forecast_cues"


def test_period_abbreviation_and_estimate_suffix(resolver):
    assert resolver.match(resolver.parse("2026年利润"), "26H1公司实现增长").year_status == "matched"
    assert (
        resolver.match(resolver.parse("2026年利润"), "2026E利润100").fact_status == "forecast_cues"
    )
