"""Deterministic data-delivery validation for the frozen E5 corpus.

The retriever sees only each normal user question. Gold source identities and
quotes are used after retrieval to score whether the production search/fetch
path delivered the required authoritative text. No model is called.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[2]
SAMPLES = ROOT / ".scratch/corpus-access-validation/samples.jsonl"
DEFAULT_OUT = ROOT / ".scratch/corpus-access-validation/e5-data-delivery.json"

_WS = re.compile(r"[\s\u3000\xa0\u200b]+")
_NOTE_TAG = re.compile(r"[（(](?:表注|图注|注)[）)]")
_LABEL_PARTS = re.compile(r"[^\W_]+", re.UNICODE)


def _norm(value: object) -> str:
    return _WS.sub("", str(value or ""))


def _quote_in_text(quote: str, text: str) -> bool:
    quote_n = _norm(quote)
    text_n = _norm(text)
    if not quote_n:
        return False
    if quote_n in text_n:
        return True
    tokens = [_norm(token) for token in re.split(r"\s+", quote.strip()) if len(_norm(token)) >= 2]
    return bool(tokens) and all(token in text_n for token in tokens)


def _structured_label_in_text(label: str, text: str, *, max_span: int = 600) -> bool:
    """Match a table label whose name and unit may be split into adjacent cells.

    ``收盘价（元）`` is commonly persisted as ``收盘价 … （元）`` because the PDF
    stores the unit on a second header row.  Require every lexical component in
    source order and within a bounded span; this accepts the structural split
    without treating arbitrary document-wide term overlap as evidence.
    """
    label_n = _norm(label)
    text_n = _norm(text)
    if label_n in text_n:
        return True
    parts = [part for part in _LABEL_PARTS.findall(label) if part]
    if not parts:
        return False
    start = -1
    cursor = 0
    for part in parts:
        pos = text_n.find(_norm(part), cursor)
        if pos < 0:
            return False
        if start < 0:
            start = pos
        cursor = pos + len(_norm(part))
    return cursor - start <= max_span


def _dependency_checks(target: dict[str, Any], text: str) -> dict[str, bool]:
    checks: dict[str, bool] = {}
    for field in ("header_refs", "row_labels"):
        values = [str(value) for value in (target.get(field) or []) if str(value).strip()]
        checks[field] = all(_structured_label_in_text(value, text) for value in values)
    footnote = str(target.get("footnotes") or "").strip()
    # ``（表注）``/``（图注）`` are reviewer annotations identifying the source
    # location, not verbatim source content; they are excluded from evidence text.
    footnote_evidence = _NOTE_TAG.sub("", footnote).strip()
    checks["footnotes"] = not footnote_evidence or _quote_in_text(footnote_evidence, text)
    return checks


def _load_samples(split: str, sample_ids: set[str]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for line in SAMPLES.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        row = json.loads(line)
        if split != "all" and row.get("split") != split:
            continue
        if sample_ids and row.get("sample_id") not in sample_ids:
            continue
        if row.get("query_kind") == "no_answer" or not row.get("targets"):
            continue
        rows.append(row)
    return rows


def _delivered_result(tool_name: str, raw: str, budget: int) -> str:
    """Apply the same structured-result budget path used by the ReAct workflow."""
    from plugins.tools._overflow import structured_result_fit

    fitted = structured_result_fit(tool_name, raw, budget)
    if fitted is not None:
        return fitted
    # Non-success payloads are handed back to the ordinary result processor.
    # These error envelopes are intentionally short; preserve them verbatim.
    return raw if len(raw) <= budget else raw[:budget]


async def _search(question: str) -> tuple[dict[str, Any], str]:
    from plugins.tools.corpus_search import corpus_search

    raw = await corpus_search.func(question, limit=10)
    delivered = _delivered_result("corpus_search", raw, 20_000)
    return json.loads(delivered), delivered


async def _fetch_plan(plan: dict[str, Any]) -> dict[str, Any]:
    from plugins.tools.corpus_fetch import corpus_fetch

    doc_id = str(plan.get("doc_id") or "")
    locators = [str(value) for value in (plan.get("locators") or []) if str(value)]
    view = str(plan.get("view") or "compact")
    pages: list[dict[str, Any]] = []
    page_sizes: list[dict[str, int]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()
    for _ in range(100):
        if cursor is None:
            raw = await corpus_fetch.func(
                doc_id=doc_id, locators=locators, view=view, max_chars=6000
            )
        else:
            raw = await corpus_fetch.func(doc_id=doc_id, cursor=cursor, max_chars=6000)
        delivered = _delivered_result("corpus_fetch", raw, 6000)
        payload = json.loads(delivered)
        page_sizes.append({"raw": len(raw), "delivered": len(delivered)})
        pages.append(payload)
        if not isinstance(payload.get("items", []), list):
            return {
                "ok": False,
                "error": str(payload.get("error") or "delivered_items_not_list"),
                "doc_id": doc_id,
                "locators": locators,
                "pages": len(pages),
                "page_sizes": page_sizes,
                "items": [],
                "item_errors": (
                    payload.get("item_errors")
                    if isinstance(payload.get("item_errors"), list)
                    else []
                ),
                "unresolved": (
                    payload.get("unresolved")
                    if isinstance(payload.get("unresolved"), list)
                    else []
                ),
                "fetch_complete": False,
            }
        cursor = payload.get("next_cursor")
        if not cursor:
            break
        if cursor in seen_cursors:
            return {
                "ok": False,
                "error": "cursor_cycle",
                "doc_id": doc_id,
                "locators": locators,
                "pages": pages,
            }
        seen_cursors.add(cursor)
    else:
        return {
            "ok": False,
            "error": "page_limit_exceeded",
            "doc_id": doc_id,
            "locators": locators,
            "pages": pages,
        }

    items = [
        item
        for page in pages
        for item in (page.get("items") or [])
        if isinstance(item, dict)
    ]
    errors = [
        error
        for page in pages
        for error in (page.get("item_errors") or [])
        if isinstance(error, dict)
    ]
    unresolved = list(
        dict.fromkeys(
            str(locator)
            for page in pages
            for locator in (page.get("unresolved") or [])
            if str(locator)
        )
    )
    return {
        "ok": all(page.get("ok") is True for page in pages),
        "doc_id": doc_id,
        "locators": locators,
        "pages": len(pages),
        "page_sizes": page_sizes,
        "items": items,
        "item_errors": errors,
        "unresolved": unresolved,
        "fetch_complete": bool(pages) and pages[-1].get("fetch_complete") is True,
    }


def _assemble_text(fetches: list[dict[str, Any]]) -> tuple[str, list[str]]:
    fragments: dict[str, list[tuple[int, str]]] = {}
    labels: dict[str, list[str]] = {}
    order: list[str] = []
    for fetch in fetches:
        for item in fetch.get("items") or []:
            locator = str(item.get("locator") or "")
            text = item.get("text")
            if not locator or not isinstance(text, str):
                continue
            if locator not in fragments:
                fragments[locator] = []
                order.append(locator)
            labels.setdefault(locator, []).extend(
                str(label) for label in (item.get("label_path") or []) if str(label).strip()
            )
            fragment = item.get("fragment") or {}
            start = int(fragment.get("start") or 0)
            fragments[locator].append((start, text))
    parts = []
    for locator in order:
        parts.append("".join(text for _, text in sorted(fragments[locator])))
        parts.extend(dict.fromkeys(labels.get(locator, [])))
    return "\n".join(parts), order


async def _score_target(
    sample: dict[str, Any],
    target: dict[str, Any],
    search_cache: dict[str, tuple[dict[str, Any], str]],
    fetch_cache: dict[tuple[str, tuple[str, ...]], dict[str, Any]],
) -> dict[str, Any]:
    question = str(target.get("question") or sample.get("question") or "").strip()
    if question not in search_cache:
        search_cache[question] = await _search(question)
    search, delivered_search = search_cache[question]
    doc_identity = str(target.get("doc_identity") or sample.get("doc_identity") or "")
    doc_short = doc_identity[:8]
    hits = [hit for hit in (search.get("hits") or []) if isinstance(hit, dict)]
    source_hits = [
        hit
        for hit in hits
        if doc_short and doc_short in str(hit.get("source_id") or "")
    ]
    plans: list[dict[str, Any]] = []
    seen_plans: set[tuple[str, tuple[str, ...]]] = set()
    for hit in source_hits:
        plan = hit.get("fetch_plan") or {
            "doc_id": hit.get("doc_id"),
            "locators": hit.get("context_locators") or [hit.get("locator")],
            "scope_id": hit.get("scope_id"),
        }
        key = (
            str(plan.get("doc_id") or ""),
            tuple(str(value) for value in (plan.get("locators") or [])),
        )
        if key not in seen_plans:
            seen_plans.add(key)
            plans.append(plan)

    fetches: list[dict[str, Any]] = []
    for plan in plans:
        key = (
            str(plan.get("doc_id") or ""),
            tuple(str(value) for value in (plan.get("locators") or [])),
        )
        if key not in fetch_cache:
            fetch_cache[key] = await _fetch_plan(plan)
        fetches.append(fetch_cache[key])
    delivered_text, delivered_locators = _assemble_text(fetches)
    dependencies = _dependency_checks(target, delivered_text)
    quote_ok = _quote_in_text(str(target.get("verbatim_quote") or ""), delivered_text)
    search_ok = search.get("ok") is True
    source_offered = bool(source_hits)
    fetch_complete = bool(fetches) and all(
        fetch.get("ok") is True and fetch.get("fetch_complete") is True for fetch in fetches
    )
    all_pass = search_ok and source_offered and fetch_complete and quote_ok and all(
        dependencies.values()
    )
    if not search_ok:
        first_fail = "search_error"
    elif not source_offered:
        first_fail = "source_not_offered"
    elif not fetch_complete:
        first_fail = "fetch_incomplete"
    elif not quote_ok:
        first_fail = "quote_not_delivered"
    elif not all(dependencies.values()):
        first_fail = "dependency_not_delivered"
    else:
        first_fail = None
    return {
        "sample_id": sample.get("sample_id"),
        "split": sample.get("split"),
        "domain": sample.get("domain"),
        "target_id": target.get("target_id"),
        "role": target.get("role") or target.get("evidence_role"),
        "question": question,
        "doc_identity": doc_identity,
        "search_ok": search_ok,
        "search_hits": len(hits),
        "delivered_search_chars": len(delivered_search),
        "source_offered": source_offered,
        "source_hit_ids": [str(hit.get("source_id") or "") for hit in source_hits],
        "source_hit_summaries": [
            {
                "locator": hit.get("locator"),
                "context_count": len(hit.get("context_locators") or []),
                "snippet": str(hit.get("snippet") or "")[:240],
            }
            for hit in source_hits
        ],
        "plans": len(plans),
        "requested_locators": sum(len(fetch.get("locators") or []) for fetch in fetches),
        "delivered_locators": delivered_locators,
        "pages": sum(int(fetch.get("pages") or 0) for fetch in fetches),
        "fetch_complete": fetch_complete,
        "unresolved": [
            locator for fetch in fetches for locator in (fetch.get("unresolved") or [])
        ],
        "item_errors": [
            error for fetch in fetches for error in (fetch.get("item_errors") or [])
        ],
        "fetch_errors": [str(fetch.get("error")) for fetch in fetches if fetch.get("error")],
        "page_sizes": [
            size for fetch in fetches for size in (fetch.get("page_sizes") or [])
        ],
        "quote_delivered": quote_ok,
        "expected_quote": str(target.get("verbatim_quote") or ""),
        "dependencies": dependencies,
        "delivered_chars": len(delivered_text),
        "all_pass": all_pass,
        "first_fail": first_fail,
    }


async def _run(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results: list[dict[str, Any]] = []
    search_cache: dict[str, tuple[dict[str, Any], str]] = {}
    fetch_cache: dict[tuple[str, tuple[str, ...]], dict[str, Any]] = {}
    for sample in rows:
        for target in sample.get("targets") or []:
            results.append(await _score_target(sample, target, search_cache, fetch_cache))
    return results


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", choices=("dev", "holdout", "all"), default="all")
    parser.add_argument("--sample", action="append", default=[])
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()

    rows = _load_samples(args.split, set(args.sample))
    targets = asyncio.run(_run(rows))
    failures = [target for target in targets if not target["all_pass"]]
    by_role: dict[str, dict[str, object]] = {}
    for role in sorted({str(target.get("role") or "unknown") for target in targets}):
        role_targets = [target for target in targets if str(target.get("role") or "unknown") == role]
        role_failures = [target for target in role_targets if not target["all_pass"]]
        by_role[role] = {
            "passed": len(role_targets) - len(role_failures),
            "failed": len(role_failures),
            "pass_rate": (
                (len(role_targets) - len(role_failures)) / len(role_targets)
                if role_targets
                else 0.0
            ),
            "failure_classes": dict(
                Counter(target["first_fail"] for target in role_failures)
            ),
        }
    result = {
        "artifact": "e5-data-delivery",
        "generated_at": datetime.now(UTC).isoformat(),
        "policy": (
            "zero-model; normal question -> corpus_search(limit=10) -> same-hit fetch_plan -> "
            "corpus_fetch(all cursor pages); exact quote or frozen equivalent structural evidence; "
            "ReAct budgets search=20000/fetch=6000"
        ),
        "scope": {
            "split": args.split,
            "samples": len(rows),
            "targets": len(targets),
        },
        "summary": {
            "passed": len(targets) - len(failures),
            "failed": len(failures),
            "pass_rate": (len(targets) - len(failures)) / len(targets) if targets else 0.0,
            "failure_classes": dict(Counter(target["first_fail"] for target in failures)),
            "by_role": by_role,
        },
        "targets": targets,
    }
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result["summary"], ensure_ascii=False, indent=2))
    print(f"artifact={args.out}")
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
