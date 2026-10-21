"""Pure, evidence-backed query constraints for opt-in retrieval experiments.

No provider, database, current-clock dependency or implicit candidate filtering.
Unknown identities/years remain unknown, never proof of corpus-wide absence.
"""

from __future__ import annotations

import re
from dataclasses import dataclass


def normalize(text: str) -> str:
    """Fold case and layout whitespace, preserving identity punctuation."""
    return "".join(text.casefold().split())


@dataclass(frozen=True)
class AliasEvidence:
    """One supplied, attributable identity relation; provenance is mandatory."""

    canonical: str
    alias: str
    evidence_ref: str

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.canonical, self.alias, self.evidence_ref)):
            raise ValueError("alias identity and evidence reference must be nonempty")


@dataclass(frozen=True)
class EntityRef:
    surface: str
    identities: tuple[str, ...]
    evidence_refs: tuple[str, ...] = ()


@dataclass(frozen=True)
class QueryConstraints:
    entities: tuple[EntityRef, ...]
    issuers: tuple[str, ...]
    years: tuple[int, ...]
    fact_mode: str  # unspecified / actual / forecast / verify_actual


@dataclass(frozen=True)
class ConstraintMatch:
    entity_status: str
    entity_fraction: float
    direct_entities: tuple[str, ...]
    inherited_entities: tuple[str, ...]
    source_status: str
    year_status: str
    matched_years: tuple[int, ...]
    abbreviated_years: tuple[int, ...]
    year_fraction: float
    dated_clauses: tuple[str, ...]
    fact_status: str


_YEAR = re.compile(r"(?<!\d)((?:19|20)\d{2})(?!\d)")
_CORPORATE = re.compile(r"[\u4e00-\u9fffA-Za-z]{2,30}?(?:股份有限公司|有限责任公司|有限公司)")
_OBJECT = re.compile(
    r"[\u4e00-\u9fff]{2,12}?(?:科技|技术|正源|电机|银行|保险|集团)"
    r"(?=\d{4}|这份|这家|的|和|与|及|分别|[，,？?]|$)"
)
_PREFIX = re.compile(r"^(?:请(?:问|比较|分析)?|只根据资料库|按照|根据|截至|比较|分析)")
_SOURCE_CUE = re.compile(
    r"^(?:证券(?:研究所)?)?(?:的|这份|本次)*(?:"
    r"[^，。！？?；;]{0,18}(?:报告|研报|周报|纪要|点评|中报|年报|前瞻)|《|"
    r"认为|如何|为什么|是否|判断|解释|改变[^，。！？?；;]{0,15}判断|"
    r"通过[^，。！？?；;]{0,20}判断)"
)
_COMPANY_TAIL = re.compile(r"^(?:银行|保险|科技|集团|股份|人寿|有限公司)")
_FORECAST = re.compile(r"预计|预测|预期|有望|计划|目标|估计|测算|假设|(?:19|20)\d{2}e(?![a-z])")
_OBSERVED = re.compile(r"实现|已签|已披露|截至|同比|实际|已审计|已出货")


def _contains(text: str, alias: str) -> bool:
    needle = normalize(alias)
    if re.fullmatch(r"\d{6}(?:\.[a-z]{2})?", needle):
        return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?!\d)", text) is not None
    if re.fullmatch(r"[a-z][a-z0-9]+", needle):
        return re.search(r"(?<![a-z0-9])" + re.escape(needle) + r"(?![a-z0-9])", text) is not None
    return needle in text


def _years(text: str) -> tuple[int, ...]:
    years = {int(m.group(1)) for m in _YEAR.finditer(text)}
    years.update(
        2000 + int(m.group(1))
        for m in re.finditer(r"(?<!\d)(\d{2})(?:h[12]|q[1-4])(?!\d)", text.casefold())
    )
    for match in re.finditer(r"((?:19|20)\d{2})年?[至到—–-]((?:19|20)\d{2})", text):
        start, end = map(int, match.groups())
        if 0 <= end - start <= 20:
            years.update(range(start, end + 1))
    return tuple(sorted(years))


def _year_clauses(text: str) -> tuple[str, ...]:
    # Layout line breaks are not sentence boundaries. Decimal points are retained.
    return tuple(
        part
        for part in re.split(
            r"[。！？!?；;]|，(?=(?:预计|预测|预期|计划|截至|(?:19|20)\d{2}))", normalize(text)
        )
        if part
    )


class ConstraintResolver:
    """Resolve only attributable aliases; shared aliases remain ambiguous."""

    def __init__(self, aliases: tuple[AliasEvidence, ...], issuers: tuple[str, ...]) -> None:
        self._aliases: dict[str, dict[str, set[str]]] = {}
        for row in aliases:
            for name in (row.canonical, row.alias):
                self._aliases.setdefault(normalize(name), {}).setdefault(row.canonical, set()).add(
                    row.evidence_ref
                )
        self._issuers = tuple(sorted(set(issuers), key=lambda item: (-len(item), item)))

    def parse(self, query: str) -> QueryConstraints:
        """Separate research objects, named report sources and literal evidence years."""
        text = query.casefold().strip()
        found: list[tuple[int, int, EntityRef]] = []
        for alias, identities in sorted(self._aliases.items(), key=lambda item: -len(item[0])):
            if not _contains(text, alias):
                continue
            for match in re.finditer(re.escape(alias), text):
                if any(a <= match.start() and match.end() <= b for a, b, _ in found):
                    continue
                found.append(
                    (
                        match.start(),
                        match.end(),
                        EntityRef(
                            alias,
                            tuple(sorted(identities)),
                            tuple(sorted({ref for refs in identities.values() for ref in refs})),
                        ),
                    )
                )
        for pattern in (_CORPORATE, _OBJECT):
            for match in pattern.finditer(text):
                surface = _PREFIX.sub("", match.group())
                # Conjunctions and clause boundaries must not become part of a name.
                surface = re.split(r"[和与及对，,]|分析|比较|报告|根据|按照|引用", surface)[-1]
                start = match.end() - len(surface)
                if len(surface) < 3 or any(a <= start and match.end() <= b for a, b, _ in found):
                    continue
                found = [
                    (a, b, entity)
                    for a, b, entity in found
                    if not (start <= a and b <= match.end())
                ]
                found.append((start, match.end(), EntityRef(surface, (surface,))))
        issuer_matches: list[str] = []
        for issuer in self._issuers:
            for match in re.finditer(re.escape(normalize(issuer)), text):
                tail = text[match.end() :]
                prefix = text[: match.start()]
                if (
                    prefix
                    and re.search(r"[\u4e00-\u9fff]$", prefix)
                    and not re.search(r"(?:按|按照|根据|引用|参考|结合|对照|让)$", prefix)
                ):
                    continue
                if any(a <= match.start() < b for a, b, _ in found):
                    continue
                if not _COMPANY_TAIL.match(tail) and _SOURCE_CUE.match(tail):
                    issuer_matches.append(issuer)
                    break
        unique: dict[tuple[str, ...], EntityRef] = {}
        for _, _, entity in sorted(found, key=lambda row: row[0]):
            unique.setdefault(entity.identities, entity)
        actual = bool(re.search(r"实际|已审计|已经实现|已经.*出货", text))
        verification = bool(re.search(r"吗|是否|证明|了吗", text))
        mode = (
            "verify_actual"
            if actual and verification
            else "actual"
            if actual
            else "forecast"
            if re.search(r"预测|预计|预期", text)
            else "unspecified"
        )
        return QueryConstraints(
            tuple(unique.values()), tuple(sorted(set(issuer_matches))), _years(text), mode
        )

    def _identity_in_text(self, text: str, identity: str) -> bool:
        if _contains(text, identity):
            return True
        return any(
            len(owners) == 1 and identity in owners and _contains(text, alias)
            for alias, owners in self._aliases.items()
        )

    def match(
        self,
        constraints: QueryConstraints,
        body: str,
        *,
        source_company: str | None = None,
        source_issuer: str | None = None,
    ) -> ConstraintMatch:
        """Classify evidence support. Report dates and headings are not body years.

        The caller supplies a role-cleaned body and a verified single-company
        source identity. A title inheritance proves topic attribution only.
        """
        text = normalize(body)
        direct: list[str] = []
        inherited: list[str] = []
        ambiguous = False
        for entity in constraints.entities:
            if len(entity.identities) != 1:
                ambiguous = True
                continue
            identity = entity.identities[0]
            if self._identity_in_text(text, identity):
                direct.append(identity)
            elif source_company == identity:
                inherited.append(identity)
        covered = len(direct) + len(inherited)
        total = len(constraints.entities)
        entity_status = (
            "unconstrained"
            if not total
            else "ambiguous"
            if ambiguous
            else "matched"
            if covered == total
            else "partial"
            if covered
            else "not_observed"
        )
        source_status = (
            "unconstrained"
            if not constraints.issuers
            else "unknown"
            if source_issuer is None
            else "matched"
            if source_issuer in constraints.issuers
            else "different_source"
        )
        clauses = _year_clauses(body)
        matched_years = tuple(sorted(set(constraints.years) & set(_years(text))))
        abbreviated = tuple(
            y
            for y in constraints.years
            if y not in matched_years and re.search(rf"(?<!\d){y % 100:02d}年", text)
        )
        dated = tuple(
            c
            for c in clauses
            if set(_years(c)) & set(constraints.years)
            or any(re.search(rf"(?<!\d){y % 100:02d}年", c) for y in abbreviated)
        )
        year_status = (
            "unconstrained"
            if not constraints.years
            else "matched"
            if len(matched_years) == len(constraints.years)
            else "partial"
            if matched_years
            else "abbreviated"
            if abbreviated
            else "not_observed"
        )
        # A forecast for another year cannot classify the requested year's claim.
        relevant = dated if constraints.years else clauses
        forecast = any(_FORECAST.search(c) for c in relevant)
        observed = any(_OBSERVED.search(c) and not _FORECAST.search(c) for c in relevant)
        fact_status = (
            "mixed"
            if forecast and observed
            else "forecast_cues"
            if forecast
            else "observed_cues"
            if observed
            else "unknown"
        )
        return ConstraintMatch(
            entity_status,
            covered / total if total else 0.0,
            tuple(direct),
            tuple(inherited),
            source_status,
            year_status,
            matched_years,
            abbreviated,
            (len(matched_years) + 0.5 * len(abbreviated)) / len(constraints.years)
            if constraints.years
            else 0.0,
            dated,
            fact_status,
        )
