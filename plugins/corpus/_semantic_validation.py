"""Conservative atomic prose binding, shared by canonical evidence extraction.

This recognizes a small explicit grammar, not arbitrary financial language. A
true number elsewhere in the quote is insufficient; unsupported prose stays citable.
"""

from __future__ import annotations

import re

from plugins.corpus.claims import parse_value
from plugins.corpus.claims_v2 import ClaimRecord

_PERIOD = re.compile(r"20\d{2}(?:[AEF]|年(?:[1-4]季度|上半年|下半年)?|Q[1-4]|H[12])?", re.I)
_PAIR = re.compile(
    r"(?<![\d.])([+\-−]?\(?\d[\d,]*(?:\.\d+)?\)?)"
    r"(百万元|亿美元|亿元|万元|万人|元/股|元/吨|美元|元|%|倍|天|人)"
)
_CONNECTOR = re.compile(r"(?:(?:为|是|达到|实现|约|预计|预测|分别|的|将达)|[:：=])*\Z")


def prose_binding_reasons(record: ClaimRecord, metrics: dict[str, tuple[str, str]]) -> list[str]:
    """Require one metric/value/unit/period atom and source-supported fact kind."""
    quote = re.sub(r"\s+", "", record.evidence_quote or "")
    if record.qualifiers:
        # Adjusted/consolidated/etc. need their own controlled source mapping.
        # A model-provided qualifier must not change the meaning of a verified amount.
        return ["qualifier_definition_unverified"]
    metric = metrics.get(record.metric or "")
    if not metric:
        return ["atomic_evidence_unverified"]
    names = re.compile("|".join(re.escape(name) for name in sorted(metrics, key=len, reverse=True)))
    expected_period = re.sub(r"\s+", "", record.period_raw or "").upper()
    raw_value = parse_value(record.value_text)[0]
    bound = []
    for sentence in re.split(r"[。；;！？!?\n]", quote):
        for pair in _PAIR.finditer(sentence):
            if parse_value(pair[1])[0] != raw_value or pair[2] != record.unit_raw:
                continue
            prefixes = list(names.finditer(sentence[: pair.start()]))
            periods = list(_PERIOD.finditer(sentence[: pair.start()]))
            if not prefixes or not periods:
                continue
            label, period = prefixes[-1], periods[-1]
            if metrics[label[0]][0] != metric[0] or period[0].upper() != expected_period:
                continue
            gap = _PERIOD.sub("", sentence[label.end() : pair.start()])
            if not _CONNECTOR.fullmatch(gap) or "分别" in gap:
                continue
            # A/E/F flags are source evidence, never a model-chosen kind.
            prefix = sentence[: pair.start()]
            predicted = period[0].upper().endswith(("E", "F")) or bool(
                re.search(r"预计|预测|预期|有望", prefix)
            )
            kind = "forecast" if predicted else "fact"
            bound.append(kind)
    if len(bound) != 1:
        return ["atomic_evidence_mismatch" if not bound else "atomic_evidence_ambiguous"]
    return [] if record.kind == bound[0] else ["kind_source_mismatch"]
