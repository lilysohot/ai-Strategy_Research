"""Conservative BLS HTML extraction; offsets always address the retained raw HTML."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import date, datetime
from html.parser import HTMLParser
from zoneinfo import ZoneInfo

from plugins.corpus.macro_models import ReasonCode, SourceTime

MONTHS = [
    "January",
    "February",
    "March",
    "April",
    "May",
    "June",
    "July",
    "August",
    "September",
    "October",
    "November",
    "December",
]
MONTH_NAMES = {name.lower(): i for i, name in enumerate(MONTHS, 1)}
MONTH_NAMES.update({name[:3].lower(): i for i, name in enumerate(MONTHS, 1)})
VERSION = "bls-archive-1"


class ArchiveBlocked(ValueError):
    def __init__(self, reason: ReasonCode, field_name: str) -> None:
        self.reason: ReasonCode = reason
        self.field_name = field_name
        super().__init__(reason)


@dataclass
class Node:
    tag: str
    start: int
    end: int = 0
    children: list[Node] = field(default_factory=list)
    parts: list[str] = field(default_factory=list)
    attributes: dict[str, str | None] = field(default_factory=dict)

    @property
    def text(self) -> str:
        return " ".join(" ".join(self.parts).split())

    def descendants(self, tags: set[str]) -> list[Node]:
        return [
            node
            for child in self.children
            for node in ([child] if child.tag in tags else child.descendants(tags))
        ]


class ArchiveHTML(HTMLParser):
    """Small source tree, not a browser: no scripts, remote resources or execution."""

    def __init__(self, raw: str) -> None:
        super().__init__(convert_charrefs=True)
        self.raw = raw
        self.lines = [0] + [m.end() for m in re.finditer("\n", raw)]
        self.root = Node("root", 0, len(raw))
        self.stack = [self.root]
        self.feed(raw)
        self.close()
        if len(self.stack) != 1:
            raise ArchiveBlocked("atomic_evidence_mismatch", "html_structure")

    def source_offset(self) -> int:
        line, column = self.getpos()
        return self.lines[line - 1] + column

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if len(self.stack) >= 64:
            raise ArchiveBlocked("atomic_evidence_mismatch", "html_depth_limit")
        node = Node(tag, self.source_offset())
        if len(dict(attrs)) != len(attrs):
            raise ArchiveBlocked("atomic_evidence_mismatch", "duplicate_html_attribute")
        node.attributes = dict(attrs)
        self.stack[-1].children.append(node)
        if tag in {
            "area",
            "base",
            "br",
            "col",
            "embed",
            "hr",
            "img",
            "input",
            "link",
            "meta",
            "param",
            "source",
            "track",
            "wbr",
        }:
            node.end = self.source_offset() + len(self.get_starttag_text() or "")
        else:
            self.stack.append(node)

    def handle_startendtag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        self.handle_starttag(tag, attrs)
        if self.stack[-1].tag == tag:
            self.stack.pop().end = self.source_offset() + len(self.get_starttag_text() or "")

    def handle_endtag(self, tag: str) -> None:
        if len(self.stack) == 1 or self.stack[-1].tag != tag:
            raise ArchiveBlocked("atomic_evidence_mismatch", "html_structure")
        self.stack.pop().end = self.raw.index(">", self.source_offset()) + 1

    def handle_data(self, data: str) -> None:
        if any(node.tag in {"script", "style", "noscript"} for node in self.stack):
            return
        for node in self.stack:
            node.parts.append(data)


def only(nodes: list[Node], field_name: str) -> Node:
    if len(nodes) != 1:
        raise ArchiveBlocked("atomic_evidence_mismatch", field_name)
    return nodes[0]


def month_number(month: str) -> int:
    year, part = map(int, month.split("-"))
    return year * 12 + part - 1


def header_month(text: str) -> str:
    match = re.fullmatch(r"([A-Za-z]+)\.?\s+(\d{4})(?:\s*\(?\s*p\s*\)?)?", text)
    if not match or match[1].lower() not in MONTH_NAMES:
        raise ArchiveBlocked("period_unverified", "table_month")
    return f"{int(match[2]):04d}-{MONTH_NAMES[match[1].lower()]:02d}"


@dataclass(frozen=True)
class ParsedRelease:
    release_at: SourceTime
    release_month: str
    reference_month: str
    value_raw: str
    unit_raw: str
    vintage_kind: str
    # Exact raw source ranges: header, time, scope, row, month, revision policy.
    ranges: tuple[tuple[str, int, int], ...]


def parse_release(raw: str, release_date: date, target_month: str) -> ParsedRelease:
    html = ArchiveHTML(raw)
    pres = html.root.descendants({"pre"})
    header = only([n for n in pres if "THE EMPLOYMENT SITUATION" in n.text], "release_header")
    title = re.findall(r"THE EMPLOYMENT SITUATION\s*--\s*([A-Z]+) (\d{4})", header.text)
    if len(title) != 1 or title[0][0].lower() not in MONTH_NAMES:
        raise ArchiveBlocked("period_unverified", "reference_month")
    current = f"{int(title[0][1]):04d}-{MONTH_NAMES[title[0][0].lower()]:02d}"
    dates = re.findall(
        r"Transmission of material in this news release is embargoed until\s+"
        r"(?:USDL-\d{2}-\d+\s+)?(\d{1,2}):(\d{2}) (a\.m\.|p\.m\.) "
        r"\((ET|EST|EDT)\) (Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday), "
        r"([A-Za-z]+) (\d{1,2}), (\d{4})",
        header.text,
    )
    if len(dates) != 1:
        raise ArchiveBlocked("time_provenance_unverified", "release_at")
    hour, minute, ampm, zone, weekday, month, day, year = dates[0]
    try:
        if not 1 <= int(hour) <= 12:
            raise ValueError("invalid hour")
        stamp = datetime(
            int(year),
            MONTH_NAMES[month.lower()],
            int(day),
            int(hour) % 12 + (12 if ampm == "p.m." else 0),
            int(minute),
            tzinfo=ZoneInfo("America/New_York"),
        )
        if (
            stamp.date() != release_date
            or stamp.strftime("%A") != weekday
            or (zone != "ET" and stamp.tzname() != zone)
            or stamp.replace(fold=1).utcoffset() != stamp.utcoffset()
        ):
            raise ValueError("event date or timezone mismatch")
    except (ValueError, KeyError) as exc:
        raise ArchiveBlocked("time_provenance_unverified", "release_at") from exc
    # Only the normal monthly release cadence is supported. Delayed/combined releases fail closed.
    if month_number(stamp.strftime("%Y-%m")) - month_number(current) != 1:
        raise ArchiveBlocked("vintage_mismatch", "release_cadence")

    table = only(
        [
            n
            for n in html.root.descendants({"table"})
            if re.search(r"Summary table B\. Establishment data, seasonally adjusted", n.text)
        ],
        "summary_table_b",
    )
    caption = only(
        [
            n
            for n in table.descendants({"caption"})
            if n.text == "Summary table B. Establishment data, seasonally adjusted"
        ],
        "seasonally_adjusted_caption",
    )
    rows = table.descendants({"tr"})
    cells = [row.descendants({"th", "td"}) for row in rows]
    header_rows = [row for row in cells if row and row[0].text == "Category"]
    if len(header_rows) != 1 or len(header_rows[0]) != 5:
        raise ArchiveBlocked("period_unverified", "summary_columns")
    headers = header_rows[0][1:]
    if any(n.attributes.get(key, "1") != "1" for n in headers for key in ("rowspan", "colspan")):
        raise ArchiveBlocked("atomic_evidence_mismatch", "merged_month_columns")
    months = [header_month(n.text) for n in headers]
    if (
        len(set(months)) != 4
        or months[-1] != current
        or [month_number(current) - month_number(m) for m in months] != [12, 2, 1, 0]
    ):
        raise ArchiveBlocked("period_unverified", "summary_columns")
    policy = only(
        [
            n
            for n in pres
            if re.search(
                r"establishment survey revises its initial monthly estimates twice, in the "
                r"immediately succeeding 2 months",
                n.text,
            )
        ],
        "revision_policy",
    )
    benchmark = [
        n
        for n in pres
        if re.search(r"establishment survey data released today have been benchmarked", n.text)
    ]
    lag = month_number(current) - month_number(target_month)
    ranges = [
        ("release_at", header.start, header.end),
        ("period", header.start, header.end),
        ("indicator", caption.start, caption.end),
        ("vintage", policy.start, policy.end),
    ]
    if lag not in (0, 1, 2) and not benchmark:
        raise ArchiveBlocked("vintage_mismatch", "historical_vintage")
    if lag < 0:
        raise ArchiveBlocked("period_unverified", "reference_month")

    # Annual benchmark rows contain both levels and changes; select the *revised change* only.
    if lag > 0 and benchmark:
        node = only(benchmark, "benchmark_notice")
        pattern = (
            r"Table A\. Revisions to total nonfarm employment, January to December (\d{4}), "
            r"seasonally adjusted \(Numbers in thousands\)"
        )
        bm = re.search(pattern, node.text)
        if not bm or int(target_month[:4]) != int(bm[1]):
            raise ArchiveBlocked("vintage_mismatch", "benchmark_table")
        # Layout labels are required to prevent mistaking a level or a revision delta for a change.
        if not re.search(r"Level\s*\|\s*Over-the-month change", node.text):
            raise ArchiveBlocked("indicator_mismatch", "benchmark_columns")
        if not re.search(
            r"\|\s*revised\s*\|\s*published\s*\|\s*\|\s*revised\s*\|\s*published\s*\|",
            node.text,
        ):
            raise ArchiveBlocked("atomic_evidence_mismatch", "benchmark_columns")
        original = raw[node.start : node.end]
        if len(re.findall(rf"(?m)^\s*{bm[1]}\s*\|", original)) != 1:
            raise ArchiveBlocked("period_unverified", "benchmark_row_year")
        row_pattern = (
            rf"(?m)^\s*{MONTHS[int(target_month[5:]) - 1]}(?:\(p\))?\.+\s*\|"
            r"\s*([+-]?[\d,]+)\s*\|\s*([+-]?[\d,]+)\s*\|\s*([+-]?[\d,]+)"
            r"\s*\|\s*([+-]?[\d,]+)\s*\|\s*([+-]?[\d,]+)\s*\|\s*([+-]?[\d,]+)\s*$"
        )
        matches = list(re.finditer(row_pattern, original))
        if len(matches) != 1:
            raise ArchiveBlocked("atomic_evidence_mismatch", "benchmark_row")
        match = matches[0]
        value = match[4]
        ranges += [
            ("vintage", node.start, node.end),
            ("unit_mapping", node.start, node.end),
            ("period", node.start, node.end),
            ("value", node.start + match.start(), node.start + match.end()),
        ]
        kind = "benchmark"
        unit_raw = "Numbers in thousands"
    else:
        in_section = False
        candidates: list[tuple[Node, list[Node]]] = []
        units: Node | None = None
        for row, row_cells in zip(rows, cells, strict=True):
            if "(Over-the-month change, in thousands)" in row.text:
                if in_section:
                    raise ArchiveBlocked("atomic_evidence_mismatch", "duplicate_change_section")
                in_section, units = True, row
            elif row.text.startswith("(3-month average change"):
                in_section = False
            if in_section and row_cells and row_cells[0].text == "Total nonfarm":
                candidates.append((row, row_cells))
        if len(candidates) != 1 or units is None or len(candidates[0][1]) != 5:
            raise ArchiveBlocked("atomic_evidence_mismatch", "total_nonfarm_row")
        row, row_cells = candidates[0]
        if any(
            n.attributes.get(key, "1") != "1" for n in row_cells for key in ("rowspan", "colspan")
        ):
            raise ArchiveBlocked("atomic_evidence_mismatch", "merged_value_columns")
        column = months.index(target_month)
        value = row_cells[column + 1].text
        if not re.search(r"\(\s*p\s*\)\s+Preliminary", table.text):
            raise ArchiveBlocked("vintage_mismatch", "preliminary_definition")
        if (lag in (0, 1)) != bool(re.search(r"\bp\b", headers[column].text)):
            raise ArchiveBlocked("vintage_mismatch", "preliminary_marker")
        ranges += [
            ("unit_mapping", units.start, units.end),
            ("period", headers[column].start, headers[column].end),
            ("value", row.start, row.end),
        ]
        kind = ("first", "second", "third")[lag]
        unit_raw = "in thousands"
    if not re.fullmatch(r"[+-]?(?:\d+|\d{1,3}(?:,\d{3})+)", value):
        raise ArchiveBlocked("value_unverified", "value_raw")
    return ParsedRelease(
        SourceTime(raw=stamp.isoformat()),
        current,
        target_month,
        value,
        unit_raw,
        kind,
        tuple(ranges),
    )
