"""Opt-in body ranking; immutable corpus features and query-local decisions.

Entity coverage adjusts candidates within their existing source order. Source
roles and guarded year coverage order selected bands without changing their scope.
Missing evidence is diagnostic, never an instruction to discard a candidate.
"""

from __future__ import annotations

import math
import re
from collections.abc import Mapping
from dataclasses import asdict, dataclass, replace
from types import MappingProxyType

from plugins.corpus.preparation.read_pg import ChunkEvidence
from plugins.corpus.preparation.search_pg import SearchHit
from plugins.corpus.retrieval.constraints import (
    AliasEvidence,
    ConstraintMatch,
    ConstraintResolver,
    QueryConstraints,
    normalize,
)

REVISION = "body-constraints-v1"
_STOP = frozenset(
    [
        "报告",
        "认为",
        "如何",
        "怎样",
        "为什么",
        "什么",
        "哪些",
        "哪一",
        "这次",
        "这轮",
        "这份",
        "分别",
        "是否",
        "多少",
        "已经",
        "还有",
        "可以",
        "能否",
        "判断",
        "描述",
        "解释",
        "开始",
        "关注",
        "根据",
        "按照",
        "给出",
        "引用",
        "说明",
        "对吗",
        "里",
        "中",
        "年",
        "月",
        "日",
        "至",
        "从",
        "到",
        "的",
        "和",
        "与",
        "及",
        "为",
        "对",
        "了",
        "是",
        "在",
        "用",
        "其",
        "个",
        "让",
        "却",
        "仍",
        "再",
        "还",
        "不",
        "多",
        "少",
        "说",
        "做",
        "按",
    ]
)
Key = tuple[str, str]


@dataclass(frozen=True)
class RankingSource:
    source_id: str
    build_id: str
    original_names: tuple[str, ...]
    institution: str | None
    # All units are hash-verified by the loader; aliases retain their unit identity.
    units: tuple[tuple[str, str], ...]


def scoring_body(
    evidence: ChunkEvidence, context_refs: tuple[str, ...], kinds: Mapping[str, str]
) -> str:
    """Exclude provenance-only text from scores, leaving returned evidence untouched."""
    pieces = [
        evidence.text[start:end]
        for uid, start, end in evidence.spans
        if uid not in context_refs and kinds[uid] not in ("heading", "title")
    ]
    return normalize(
        "\n".join(
            line
            for line in "\n".join(pieces).splitlines()
            if not re.match(r"^\s*(资料来源\s*[:：]|请.*阅读.*免责声明|仅供内部参考)", line)
        )
    )


class RankingCorpus:
    """Read-only features shared across requests, with no query/result cache."""

    def __init__(self, sources: tuple[RankingSource, ...], bodies: Mapping[Key, str]) -> None:
        self.bodies = MappingProxyType(dict(bodies))
        companies: dict[str, str] = {}
        issuers: dict[str, str] = {}
        aliases: list[AliasEvidence] = []
        for source in sources:
            names = "\n".join(source.original_names)
            found = set(re.findall(r"-([\u4e00-\u9fff]{2,10})-\d{6}(?=[-_.])", names))
            for name in source.original_names:
                match = re.match(r"^([\u4e00-\u9fff]{2,10})_投委会", name)
                if match:
                    found.add(match[1])
            if len(found) == 1:
                company = next(iter(found))
                companies[source.source_id] = company
                aliases.append(
                    AliasEvidence(company, company, f"source:{source.source_id}:original_names")
                )
                for uid, raw in source.units:
                    pattern = re.escape(company) + r"[（(](\d{6}(?:\.[A-Za-z]{2})?)[）)]"
                    for match in re.finditer(pattern, "".join(raw.split())):
                        code = match[1]
                        ref = f"{source.build_id}:{uid}"
                        aliases.append(AliasEvidence(company, code, ref))
                        if "." in code:
                            aliases.append(AliasEvidence(company, code.split(".")[0], ref))
            for uid, raw in source.units:
                for match in re.finditer(
                    r"资料来源[:：]\s*([\u4e00-\u9fff]{2,8})([A-Z][A-Za-z]{3,})", raw
                ):
                    aliases.append(AliasEvidence(match[1], match[2], f"{source.build_id}:{uid}"))
            if source.institution:
                issuer = re.sub(r"(证券)?研究所$", "", source.institution)
                issuer = re.sub(r"证券$", "", issuer)
                if len(issuer) >= 2:
                    issuers[source.source_id] = issuer
        self.companies = MappingProxyType(companies)
        self.issuers = MappingProxyType(issuers)
        self.aliases = tuple(dict.fromkeys(aliases))
        self.resolver = ConstraintResolver(self.aliases, tuple(issuers.values()))


@dataclass(frozen=True)
class Feature:
    match: ConstraintMatch
    facet: float
    source_hint: int


class RankingSession:
    """A single search's signals, attached only after successful hybrid retrieval."""

    def __init__(self, query: str, lexemes: tuple[str, ...]) -> None:
        self.query = query
        self.lexemes = lexemes
        self.features: dict[Key, Feature] = {}
        self.constraints: QueryConstraints | None = None
        self.cache_hit = False

    def prepare(self, corpus: RankingCorpus, hits: tuple[SearchHit, ...]) -> None:
        self.constraints = corpus.resolver.parse(self.query)
        # Keep the validated body-topic signal stable: source/entity strings are
        # not topic votes. Alias matching itself is handled by the resolver below.
        entities = {v for v in corpus.companies.values() if v in self.query}
        entities.update(
            re.findall(
                r"[\u4e00-\u9fffA-Za-z]{2,25}(?:股份有限公司|有限责任公司|有限公司)", self.query
            )
        )
        pair = (
            r"([\u4e00-\u9fff]{2,8}(?:科技|技术|正源|电机|股份|集团))和"
            r"([\u4e00-\u9fff]{2,8}(?:科技|技术|正源|电机|股份|集团))(?=分别)"
        )
        for first, second in re.findall(pair, self.query):
            entities.update((first, second))
        source_names = {v for v in corpus.issuers.values() if v in self.query}
        tokens = {
            t.casefold()
            for t in self.lexemes
            if len(t) >= 2
            and t.casefold() not in _STOP
            and not t.isdigit()
            and not any(t.casefold() in normalize(v) for v in (*entities, *source_names))
        }
        weights = {
            t: 1
            + math.log(
                (1 + len(corpus.bodies)) / (1 + sum(t in body for body in corpus.bodies.values()))
            )
            for t in sorted(tokens)
        }
        denominator = sum(weights.values())
        for hit in hits:
            key = (hit.build_id, hit.chunk_id)
            body = corpus.bodies[key]
            match = corpus.resolver.match(
                self.constraints,
                body,
                source_company=corpus.companies.get(hit.source_id),
                source_issuer=corpus.issuers.get(hit.source_id),
            )
            facet = (
                sum(w for t, w in weights.items() if t in body) / denominator if denominator else 0
            )
            hint = int(
                match.source_status == "matched"
                and facet > 0
                and match.entity_status in ("unconstrained", "matched", "partial")
            )
            self.features[key] = Feature(match, facet, hint)

    def rerank(self, hits: tuple[SearchHit, ...]) -> tuple[SearchHit, ...]:
        positions = {sid: i for i, sid in enumerate(dict.fromkeys(h.source_id for h in hits))}
        scored = (
            replace(
                h,
                score=h.score * (1 + self.features[(h.build_id, h.chunk_id)].match.entity_fraction),
            )
            for h in hits
        )
        return tuple(sorted(scored, key=lambda h: (positions[h.source_id], -h.score, h.chunk_id)))

    def order_selected(self, hits: tuple[SearchHit, ...]) -> tuple[SearchHit, ...]:
        if self.constraints is None:
            return hits
        rows = sorted(hits, key=lambda h: -self.features[(h.build_id, h.chunk_id)].source_hint)
        for i, current in enumerate(rows):
            if current.kind != "body":
                continue
            old = self.features[(current.build_id, current.chunk_id)]
            candidates = []
            for j, hit in enumerate(rows[i + 1 :], i + 1):
                f = self.features[(hit.build_id, hit.chunk_id)]
                if hit.source_id != current.source_id or hit.kind != "body":
                    continue
                if f.match.entity_fraction < old.match.entity_fraction or f.facet < old.facet:
                    continue
                if (
                    f.source_hint < old.source_hint
                    or f.match.year_fraction <= old.match.year_fraction
                ):
                    continue
                if self.constraints.fact_mode == "actual" and f.match.fact_status in (
                    "forecast_cues",
                    "mixed",
                ):
                    continue
                candidates.append(j)
            if candidates:
                j = max(
                    candidates,
                    key=lambda n: (
                        self.features[(rows[n].build_id, rows[n].chunk_id)].match.year_fraction
                    ),
                )
                rows[i], rows[j] = rows[j], rows[i]
        return tuple(rows)

    def diagnostics(self, hits: tuple[SearchHit, ...]) -> dict[str, object]:
        if self.constraints is None:
            return {"requested": REVISION, "used": "off", "reason": "hybrid_unavailable"}
        return {
            "requested": REVISION,
            "used": REVISION,
            "feature_cache_hit": self.cache_hit,
            "query_constraints": asdict(self.constraints),
            "matches": [
                {
                    "build_id": h.build_id,
                    "chunk_id": h.chunk_id,
                    **asdict(self.features[(h.build_id, h.chunk_id)].match),
                }
                for h in hits
            ],
            "hard_filter": False,
        }
