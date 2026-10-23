"""Display-only coverage utility; no domain vocabulary or generated evidence.

Query positions, rather than token counts, prevent overlapping n-grams from
voting twice. Local document frequency discounts a subject repeated throughout
a source. Diminishing returns still allow a second explanation of that subject.
This module must not participate in source admission or handle construction.
"""

from __future__ import annotations

import math
import re
from collections import Counter
from collections.abc import Sequence

from plugins.corpus.retrieval.text_quality import comparison_text

# Grammatical answer roles, not a subject/industry synonym dictionary. These are
# weak signals only: a passage still needs an actual query-topic match in display.
_ROLES = (
    (
        r"限制|条件|前提|要求|\b(?:limitations?|conditions?|requirements?)\b",
        r"仅[在当限]|只有|除非|前提|条件|要求|受限|必须|\b(?:only|unless|requires?|provided|if)\b",
    ),
    (
        r"为什么|为何|原因|如何|怎么|\b(?:why|causes?)\b|\bhow\b(?!\s+(?:many|much|long|often))",
        r"因为|由于|因此|通过|从而|使得|以便|原因|\b(?:because|due to|therefore|by|enables?)\b",
    ),
    (
        r"区别|差异|相比|比较|\b(?:difference|compare|versus|vs)\b",
        r"而非|不同|区别|相比|前者|后者|分别|\b(?:whereas|unlike|instead|while)\b",
    ),
)

_SOURCE_FRAME = re.compile(
    r"(?:报告|论文|文章|文档|材料)(?:中|里|认为|指出|提到|显示|提出|称|介绍|记载|提及)"
    r"|\b(?:report|paper|article|document)\s+(?:says|states|mentions|describes)\b",
    re.I,
)


def content_query(query: str) -> str:
    """Remove grammatical source references for display matching only.

    'The report says ...' names where the question came from, not what its body
    must answer. Standalone questions about reports/documents remain untouched.
    """
    return _SOURCE_FRAME.sub(" ", query)


def answer_roles(query: str, text: str) -> set[int]:
    """Three virtual positions per requested role; source query terms stay intact."""
    return {
        -1 - role * 3 - offset
        for role, (question, evidence) in enumerate(_ROLES)
        if re.search(question, query, re.I) and re.search(evidence, text, re.I)
        for offset in range(3)
    }


class PassageCoverage:
    """A small weighted set-cover objective over the offered source passages."""

    def __init__(self, texts: Sequence[str], positions: Sequence[set[int]]) -> None:
        # Repeated PDF extraction must not change the query weights.
        unique = {comparison_text(text): p for text, p in zip(texts, positions, strict=True)}
        frequency: Counter[int] = Counter()
        for covered in unique.values():
            frequency.update(covered)
        self.weights = {
            p: 1.0 + math.log((len(unique) + 1) / (count + 1)) for p, count in frequency.items()
        }
        self.counts: Counter[int] = Counter()
        self.selected: list[set[str]] = []

    @staticmethod
    def _grams(text: str) -> set[str]:
        normalized = comparison_text(text)
        return {normalized[i : i + 4] for i in range(max(1, len(normalized) - 3))}

    def score(self, text: str, positions: set[int]) -> float:
        """Prefer uncovered question aspects, then nonduplicate supporting prose.

        A repeated aspect keeps a quarter of its weight, then a ninth, etc.
        Similarity is a soft penalty: a changed number or negation is not deduped.
        Length normalization is bounded so short headings cannot win on density
        alone and a full explanatory paragraph remains competitive.
        """
        gain = sum(self.weights.get(p, 1.0) / (1 + self.counts[p]) ** 2 for p in positions)
        grams = self._grams(text)
        similarity = max(
            (len(grams & prior) / max(1, len(grams | prior)) for prior in self.selected),
            default=0.0,
        )
        length = len(comparison_text(text))
        density = 0.5 + 0.5 * min(1.0, 120 / max(1, length))
        return gain * density * (1 - 0.5 * similarity)

    def add(self, text: str, positions: set[int]) -> None:
        self.counts.update(positions)
        self.selected.append(self._grams(text))
