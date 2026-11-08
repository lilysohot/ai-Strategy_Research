"""Independent ingestion-date constraints, evaluated before candidate ranking."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, LiteralString
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from plugins.corpus.publication_dates import PublicationDateOptions, validate_range

DEFAULT_TIMEZONE = "Asia/Shanghai"


class SearchDateOptions(PublicationDateOptions, total=False):
    ingested_from: str | None
    ingested_to: str | None
    ingested_timezone: str


@dataclass(frozen=True)
class IngestionRange:
    start: datetime | None
    end: datetime | None
    timezone: str

    def matches(self, value: str | None) -> bool:
        if not value:
            return False
        stamp = datetime.fromisoformat(value)
        if stamp.tzinfo is None:
            raise ValueError("ingested_at must include a timezone")
        return (self.start is None or stamp >= self.start) and (
            self.end is None or stamp < self.end
        )


def ingestion_range(
    start: str | None, end: str | None, timezone: str = DEFAULT_TIMEZONE
) -> IngestionRange:
    try:
        validate_range(start, end)
    except ValueError as exc:
        raise ValueError(
            str(exc).replace("published_", "ingested_").replace("publication", "ingestion")
        ) from exc
    try:
        zone = ZoneInfo(timezone)
    except (ZoneInfoNotFoundError, ValueError, TypeError) as exc:
        raise ValueError("ingested_timezone must be a valid IANA timezone") from exc
    try:
        lower = datetime.combine(date.fromisoformat(start), time.min, zone) if start else None
        upper = (
            datetime.combine(date.fromisoformat(end) + timedelta(days=1), time.min, zone)
            if end
            else None
        )
    except OverflowError as exc:
        raise ValueError("ingested_to must allow a following calendar day") from exc
    return IngestionRange(lower, upper, timezone)


def search_date_options(
    published_from: str | None = None,
    published_to: str | None = None,
    ingested_from: str | None = None,
    ingested_to: str | None = None,
    ingested_timezone: str = DEFAULT_TIMEZONE,
) -> SearchDateOptions:
    validate_range(published_from, published_to)
    ingestion_range(ingested_from, ingested_to, ingested_timezone)
    options: SearchDateOptions = {}
    if published_from is not None or published_to is not None:
        options.update(published_from=published_from, published_to=published_to)
    if ingested_from is not None or ingested_to is not None:
        options.update(
            ingested_from=ingested_from,
            ingested_to=ingested_to,
            ingested_timezone=ingested_timezone,
        )
    return options


def sql_params(start: str | None, end: str | None, timezone: str) -> dict[str, object]:
    bounds = ingestion_range(start, end, timezone)
    if start is None and end is None:
        return {}
    return {"ingested_start": bounds.start, "ingested_end": bounds.end}


def filter_sql(sql: LiteralString, params: dict[str, Any]) -> LiteralString:
    """Both lexical and dense SQL expose matches before their window/top-k stage."""
    if "ingested_start" not in params:
        return sql
    boundary = "), ranked AS (" if "), source_stats AS (" not in sql else "), source_stats AS ("
    condition = """
    AND EXISTS (SELECT 1 FROM corpus.corpus_sources ingestion_source
                WHERE ingestion_source.source_id=p.source_id
                  AND ingestion_source.ingested_at IS NOT NULL
                  AND (%(ingested_start)s::timestamptz IS NULL
                       OR ingestion_source.ingested_at >= %(ingested_start)s)
                  AND (%(ingested_end)s::timestamptz IS NULL
                       OR ingestion_source.ingested_at < %(ingested_end)s))
"""
    if sql.count(boundary) != 1:
        raise ValueError("ingestion_filter_sql_boundary_missing")
    return sql.replace(boundary, condition + boundary, 1)


def read_times(cur: Any, source_ids: list[str]) -> dict[str, str | None]:
    cur.execute(
        "SELECT source_id,ingested_at FROM corpus.corpus_sources WHERE source_id=ANY(%s::text[])",
        (source_ids,),
    )
    return {
        sid: stamp.astimezone(UTC).isoformat() if stamp else None for sid, stamp in cur.fetchall()
    }


def coverage(start: str | None, end: str | None, timezone: str) -> dict[str, object]:
    bounds = ingestion_range(start, end, timezone)
    return {
        "ingested_from": start,
        "ingested_to": end,
        "timezone": timezone,
        "field": "corpus_sources.ingested_at",
        "meaning": "first_successful_publication",
        "bounds": "inclusive_local_dates",
        "unknown_time_policy": "excluded",
        "start_inclusive": bounds.start.isoformat() if bounds.start else None,
        "end_exclusive": bounds.end.isoformat() if bounds.end else None,
        "combined_with_publication": "intersection",
    }
