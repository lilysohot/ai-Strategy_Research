"""Published semantic records with complete, purpose-bound evidence units."""

from __future__ import annotations

import json
from typing import Literal

from frontier_agent.core.tool import tool
from plugins.corpus.cursor import SEMANTIC_QUERY, CursorError, decode_cursor, encode_cursor
from plugins.corpus.structured.query import (
    QUERY_SCHEMA_VERSION,
    SemanticQueryPage,
    query_semantic,
)


@tool
async def corpus_semantic_query(
    source_id: str,
    build_id: str,
    purpose: Literal["cite", "compare", "calculate"],
    query_text: str = "",
    limit: int = 10,
    cursor: str | None = None,
    max_chars: int = 5_500,
    field_filters: dict[str, str] | None = None,
) -> str:
    """Query one accepted semantic publication without extraction or repair.

    The returned records contain exact source ranges plus all known required
    dependencies as one delivery unit.  An empty page is scoped: it reports
    whether the build is unpublished, not extracted for the requested purpose,
    checked with no supported records, or simply has no lexical match.

    Recovery: CS_CURSOR_STALE means restart without cursor; never continue across
    publication versions. budget_limited is not completion: a no-progress page
    requires more delivery capacity, a smaller query/limit, or source fallback.
    A withdrawn publication, missing dependency or inaccessible store cannot
    support a report. Requery a valid version, use corpus_fetch for the specific
    missing original evidence, or revise/remove the unsupported conclusion.
    Complete evidence actually delivered by this tool is already a legal source;
    do not routinely corpus_fetch it again. Submit semantic_references through
    corpus_submit_manifest and follow its per-conclusion feedback.

    Args:
        source_id: Exact immutable source identifier.
        build_id: Exact immutable parsed build identifier.
        purpose: Intended evidence use: cite, compare, or calculate.
        query_text: Optional deterministic lexical query. No model rewrites it.
        limit: Maximum complete records on this page, from 1 through 100.
        cursor: Opaque continuation token returned by the preceding identical query.
        max_chars: Response budget; whole records are omitted rather than cut.
        field_filters: Optional exact filters for record_id, role, mapping_status,
            quality_status, or context_status.

    Returns:
        A ``corpus-semantic-query-page-v1`` JSON string. ``budget_limited`` and
        ``cursor_stale`` are explicit protocol states; JSON, evidence ranges,
        dependencies, and cursor tokens are never character-truncated.
        A downstream budget gap with ``CS_CURSOR_STALE`` requires a fresh query
        (omit cursor, reduce limit/max_chars to the delivery budget). Never treat
        ``budget_limited`` with no cursor as completion. An empty budget-limited
        page with a cursor makes no progress; increase delivery capacity or restart.
    """
    page = query_semantic(
        source_id,
        build_id,
        purpose=purpose,
        query_text=query_text,
        limit=limit,
        cursor=cursor,
        max_chars=max_chars,
        field_filters=field_filters,
    )
    return page.model_dump_json()


def fit_structured_payload(body: str, budget: int) -> str | None:
    """Fit a semantic page by dropping only whole tail records.

    This is the last-resort protection for both overflow and runtime gates.  The
    query implementation normally fits its own response first; this function
    handles a stricter downstream budget without ever slicing JSON, a record,
    an evidence range, a dependency, or a cursor token. Continuations rewind by
    the number of removed records. Without a valid continuation (notably on a
    terminal page), return an explicit restart gap instead of losing records.
    """
    if budget <= 0 or not isinstance(body, str):
        return None
    try:
        payload = json.loads(body)
    except (TypeError, ValueError):
        return None
    if not isinstance(payload, dict) or payload.get("schema_version") != QUERY_SCHEMA_VERSION:
        return None
    try:
        payload = SemanticQueryPage.model_validate(payload).model_dump(mode="json")
    except ValueError:
        return None
    if len(body) <= budget:
        return body
    records = payload.get("records")
    errors = payload.get("error_codes")
    if not isinstance(records, list) or not isinstance(errors, list):
        return None
    payload["page_status"] = "budget_limited"
    payload["error_codes"] = list(dict.fromkeys((*errors, "CS_BUDGET_EXHAUSTED")))
    continuation = None
    try:
        token = decode_cursor(payload["next_cursor"])
        if (
            token.get("type") == SEMANTIC_QUERY
            and token.get("query_sha256") == payload["query_sha256"]
            and token.get("publication_id") == payload["publication_id"]
            and token.get("sort_version") == payload["sort_version"]
            and type(token.get("generation")) is int
            and token["generation"] >= 1
            and type(token.get("position")) is int
            and token["position"] >= len(records)
        ):
            continuation = token
    except CursorError:
        pass
    if records and continuation is None:
        # A terminal page has no generation/position token. Do not invent one
        # or present a truncated terminal page as the end of the result set.
        payload["records"] = []
        payload["next_cursor"] = None
        payload["error_codes"].append("CS_CURSOR_STALE")
        return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
    while records:
        records.pop()
        assert continuation is not None
        continuation["position"] -= 1
        payload["next_cursor"] = encode_cursor(continuation)
        encoded = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
        if len(encoded) <= budget:
            return encoded
    # A protocol envelope can be larger than an unusually tiny downstream cap.
    # Returning the intact envelope is safer than passing it to a character cut.
    return json.dumps(payload, ensure_ascii=False, separators=(",", ":"))


__all__ = ["corpus_semantic_query", "fit_structured_payload"]
