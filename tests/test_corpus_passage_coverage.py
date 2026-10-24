"""Domain-independent passage selection: freeze these before the gold replay.

The nouns below are interchangeable inputs, not vocabulary for the implementation.
"""

from types import SimpleNamespace

import pytest

from plugins.corpus.retrieval.display import compose, select_passages
from plugins.corpus.retrieval.passage_coverage import PassageCoverage, answer_roles


def block(text):
    return SimpleNamespace(text=text, slices=())


@pytest.mark.parametrize("subject", ["玄星封装", "沙丘灌溉", "星港运输", "虚构对象Z"])
@pytest.mark.parametrize("tail", ["有哪些限制？", "适用条件是什么？"])
def test_shared_subject_does_not_hide_second_question_aspect(subject, tail):
    answer = f"{subject}适用条件受限：仅在低湿度环境下有效。"
    blocks = [
        block(f"{subject}效率提升30%。"),
        block(f"{subject}效率的年度交流会已经召开。"),
        block(answer),
    ]
    output = compose(blocks, f"{subject}效率怎么样，{tail}", max_blocks=2, chars_per_block=90)
    assert "提升30%" in output
    assert answer in output
    assert "交流会" not in output


@pytest.mark.parametrize("subject", ["玄星封装", "沙丘灌溉", "星港运输", "虚构对象Z"])
def test_explanation_can_use_same_query_words_in_another_block(subject):
    blocks = [
        block(f"{subject}采用双轨机制。"),
        block(f"{subject}分工如下：前者承担响应，后者提供缓冲。"),
    ]
    output = compose(blocks, f"{subject}如何工作？", max_blocks=2)
    assert "前者承担响应" in output
    assert "后者提供缓冲" in output


@pytest.mark.parametrize("subject", ["Aster", "Boreal", "Cinder"])
def test_english_multiple_aspects_and_qualification(subject):
    blocks = [
        block(f"{subject} throughput reaches 40 units per hour."),
        block(f"{subject} throughput was discussed at the annual meeting."),
        block(f"{subject} reliability requires dry conditions; wet conditions remain untested."),
    ]
    output = compose(blocks, f"{subject} throughput and reliability?", max_blocks=2)
    assert "40 units" in output and "remain untested" in output
    assert "annual meeting" not in output


def test_repeated_subject_background_does_not_outvote_rare_question_aspect():
    blocks = [block("青穹系统吞吐提升20%。")]
    blocks.extend(block(f"青穹系统吞吐在第{i}期活动中被多次讨论。") for i in range(10))
    blocks.append(block("青穹系统故障恢复需要冷启动，耗时8秒。"))
    output = compose(blocks, "青穹系统吞吐与故障恢复如何？", max_blocks=2)
    assert "提升20%" in output and "耗时8秒" in output


def test_header_cannot_displace_substantive_comparison():
    blocks = [block("系统研究\n吞吐与可靠性"), block("系统吞吐达到40，但可靠性尚未验证。")]
    selected, _ = select_passages(blocks, "系统吞吐与可靠性")
    assert selected[0].block == 1


def test_heading_and_unpunctuated_table_still_available_when_requested():
    assert "吞吐与可靠性" in compose([block("吞吐与可靠性")], "吞吐与可靠性")
    assert "42" in compose([block("吞吐\n42")], "吞吐")


def test_local_weights_ignore_exact_layout_duplicates():
    texts = ["Alpha throughput 40.", "Alpha reliability requires dry conditions."]
    positions = [{0, 1}, {0, 2}]
    original = PassageCoverage(texts, positions)
    duplicated = PassageCoverage([*texts, "Alpha\n throughput 40."], [*positions, positions[0]])
    assert original.weights == duplicated.weights


@pytest.mark.parametrize("second", ["速率不是40。", "速率为42。", "速率为40，但仅限干燥条件。"])
def test_changed_value_negation_and_condition_are_not_deduplicated(second):
    output = compose([block("速率为40。"), block(second)], "速率", max_blocks=2)
    assert second in output


def test_unknown_synthetic_entities_need_no_dictionary():
    # Unknown synthetic entities work with only the offered text and query.
    blocks = [block("ZXQ-713 throughput is 40."), block("ZXQ-713 reliability is untested.")]
    assert "untested" in compose(blocks, "ZXQ-713 throughput and reliability", max_blocks=2)


def test_ngram_similarity_never_becomes_a_hard_evidence_filter():
    coverage = PassageCoverage(["abcdabcd", "bcdabcda"], [{0}, {0}])
    coverage.add("abcdabcd", {0})
    assert coverage.score("bcdabcda", {0}) > 0


@pytest.mark.parametrize("query", ["When does A start?", "How many units?", "什么时候开始？"])
def test_time_and_quantity_questions_are_not_conditions_or_causes(query):
    assert not answer_roles(query, "Only if required, because of conditions.")


def test_role_cue_without_topic_cannot_displace_relevant_passage():
    blocks = [block("玄星系统效率提升30%。"), block("其他对象因为天气原因受限，只有晴天有效。")]
    output = compose(blocks, "玄星系统效率有什么限制，为什么？", max_blocks=2)
    assert "提升30%" in output and "其他对象" not in output


@pytest.mark.parametrize("kind", ["报告", "论文", "文章", "文档", "材料"])
def test_source_reference_cannot_admit_unrelated_body(kind):
    blocks = [block("玄星效率提升30%。"), block(f"本{kind}仅供阅读参考，禁止未经授权的复制。")]
    output = compose(blocks, f"{kind}中玄星效率如何？", max_blocks=2)
    assert "提升30%" in output and "复制" not in output


def test_reports_can_still_be_the_actual_question_subject():
    output = compose([block("报告必须包含方法说明。")], "报告必须包含什么？")
    assert "报告必须包含方法说明" in output


def test_english_source_reference_is_not_a_body_aspect():
    blocks = [block("Aster throughput is 40."), block("This report is protected by copyright.")]
    output = compose(blocks, "The report says what about Aster throughput?", max_blocks=2)
    assert "40" in output and "copyright" not in output
