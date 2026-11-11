"""Fixed service data under production corpus tools; no database fallthrough."""

from __future__ import annotations

import hashlib
import importlib
import json
import os
import sys
import time
from collections.abc import Iterator
from contextlib import ExitStack, contextmanager
from dataclasses import replace
from pathlib import Path
from typing import Any
from unittest.mock import patch

from benchmarks.team_workflow.fixtures import COORDINATION
from frontier_agent.core.execution_context import get_current_execution_scope
from frontier_agent.core.tool import Tool
from plugins.corpus.preparation.document_read import DocumentUnit, DocumentUnits, unit_locator
from plugins.corpus.preparation.read_pg import ChunkEvidence, UnitEvidence, WithdrawnError
from plugins.corpus.service import SearchHit, context_scope_id
from plugins.tools import get_builtin_tools

HINT_B = (
    "excerpts 可引用，清单用 evidence_ref=ref；preview 不可引用。证据足够即停止；"
    "缺局部用 ref 作 locator 补读，候选目录用 scope_ref；"
    '需全文时用 corpus_fetch(doc_id, scope="document")，按游标续读。'
)
CORPUS_TOOLS = ("corpus_search", "corpus_fetch", "corpus_inventory", "corpus_submit_manifest")


class FixedCorpus:
    """The minimal service interface used by the unmodified production tools."""

    def __init__(self, case: dict[str, Any], out: Path) -> None:
        source = case["sources"][0]
        root = Path(__file__).parent.resolve()
        path = (root / source["fixture_file"]).resolve()
        if not path.is_relative_to(root):
            raise ValueError("fixture outside benchmark directory")
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != source["fixture_sha256"]:
            raise ValueError("fixture hash changed")
        document = json.loads(raw)["documents"][source["document_key"]]
        self.doc_id = document["doc_id"]
        self.build_id = self.doc_id[4:]
        self.title = document["title"]
        self.config = case["fixture_contract"]
        self.units = {
            row["unit_id"]: UnitEvidence(row["unit_id"], row["text"], row["page"], None, ())
            for row in document["units"]
        }
        self.locators = {
            uid: f"chunk:native1/{uid}/{hashlib.sha256(unit.raw_text.encode()).hexdigest()[:16]}"
            for uid, unit in self.units.items()
        }
        self.reverse = {value: uid for uid, value in self.locators.items()}
        self.reverse.update({unit_locator(uid): uid for uid in self.units})
        self.revoked = False
        self.pages = 0
        self.out = out
        self.started = time.monotonic()

    def check(self, doc_id: str) -> None:
        if doc_id != self.doc_id:
            raise ValueError("unknown_document")
        if self.revoked:
            raise WithdrawnError("source_withdrawn")

    def document_units(self, doc_id: str) -> DocumentUnits:
        self.check(doc_id)
        return DocumentUnits(
            self.build_id,
            self.build_id,
            True,
            tuple(DocumentUnit(unit, "body", "kept") for unit in self.units.values()),
        )

    def fetch_verbatim(self, doc_id: str, locator: str) -> ChunkEvidence:
        self.check(doc_id)
        unit = self.units[self.reverse[locator]]
        return ChunkEvidence(
            source_id=self.build_id,
            build_id=self.build_id,
            chunk_id=locator.removeprefix("chunk:"),
            kind="body",
            title_text=None,
            section_path=(),
            units=(unit,),
            text=unit.raw_text,
            source_ranges=((0, len(unit.raw_text)),),
            spans=((unit.unit_id, 0, len(unit.raw_text)),),
            active=True,
        )

    def emit_cells(self, evidence: ChunkEvidence) -> tuple[()]:
        return ()

    def context_relations(self, doc_id: str, locators: list[str]) -> dict[str, Any]:
        self.check(doc_id)
        return {}

    def context_inventory(self, doc_id: str, locators: list[str]) -> dict[str, Any]:
        self.check(doc_id)
        members = []
        for locator in locators:
            unit = self.units[self.reverse[locator]]
            members.append(
                {
                    "locator": locator,
                    "kind": "body",
                    "page_range": [unit.page, unit.page],
                    "content_role": "body",
                    "structure_status": "unknown",
                    "region_ids": [],
                    "table_ref": None,
                    "table_rows": None,
                    "table_cols": None,
                    "relations": [],
                    "relation_status": "unknown",
                }
            )
        return {
            "doc_id": doc_id,
            "build_id": self.build_id,
            "scope_id": context_scope_id(self.build_id, locators),
            "members": members,
            "total_chunks": len(members),
            "by_kind": {"body": len(members)},
            "table_chunks": 0,
            "regions": [],
            "unknown_members": 0,
        }

    def search_with_coverage(
        self, query: str, limit: int = 10, **options: Any
    ) -> tuple[list[SearchHit], dict[str, Any]]:
        self.check(self.doc_id)
        candidates = self.config["candidate_inventory_units"]
        excerpts = self.config["search_excerpt_units"]
        previews = self.config["search_preview_units"]
        snippet = ""
        spans = []
        for uid in excerpts:
            text = self.units[uid].raw_text
            left = len(snippet)
            snippet += text
            sha = hashlib.sha256(text.encode()).hexdigest()
            spans.append(
                {
                    "member": candidates.index(uid) + 1,
                    "start": 0,
                    "end": len(text),
                    "snippet_start": left,
                    "snippet_end": len(snippet),
                    "text_chars": len(text),
                    "text_sha256": sha,
                    "quote_sha256": sha,
                }
            )
        snippet += "".join(self.units[uid].raw_text for uid in previews)
        locators = tuple(self.locators[uid] for uid in candidates)
        hit = SearchHit(
            doc_id=self.doc_id,
            locator=locators[0],
            title=self.title,
            snippet=snippet,
            score=1.0,
            published="",
            source_id=self.build_id,
            build_id=self.build_id,
            chunk_id=locators[0][6:],
            context_locators=locators,
            scope_id=context_scope_id(self.build_id, locators),
            context_by_kind=(("body", len(candidates)),),
            evidence_spans=tuple(spans),
        )
        return [hit], {
            "native": {"policy": "native1"},
            "query_status": "matched",
            "availability": "unknown",
            "processing": "unknown",
        }

    def observed(self, name: str, args: dict[str, Any], raw: str) -> None:
        payload = json.loads(raw)
        from plugins.corpus.search_evidence import search_evidence_items

        intervals = []
        items = (
            [item for hit in payload.get("hits", []) for item in search_evidence_items(hit)]
            if name == "corpus_search"
            else payload.get("items", [payload])
            if name == "corpus_fetch"
            else []
        )
        for item in items:
            text = item.get("text")
            uid = item.get("unit_id") or self.reverse.get(item.get("locator", ""))
            if text and uid:
                start = (item.get("fragment") or {}).get("start", 0)
                intervals.append({"unit_id": uid, "start": start, "end": start + len(text)})
        search_module = importlib.import_module("plugins.tools.corpus_search")
        scope = get_current_execution_scope()
        row = {
            "time_s": time.monotonic() - self.started,
            "owner": getattr(scope, "task_id", None),
            "name": name,
            "args": args,
            "result": payload,
            "returned_intervals": intervals,
            "wire_chars": len(raw),
            "reference_hint_emitted": payload.get("hint", "").startswith(
                search_module.REFERENCE_HINT
            ),
        }
        with (self.out / "corpus-tools.jsonl").open("a") as stream:
            stream.write(json.dumps(row, ensure_ascii=False) + "\n")
        if name == "corpus_fetch" and payload.get("scope") == "document" and payload.get("ok"):
            self.pages += 1
            failure = self.config.get("failure")
            if failure and self.pages >= failure["after_successful_document_pages"]:
                self.revoked = True


@contextmanager
def fixed_corpus_tools(case: dict[str, Any], out: Path, arm: str) -> Iterator[dict[str, Tool]]:
    """Process-local substitution, restored on exit; LLM transport remains real."""
    if arm not in {"A", "B"}:
        raise ValueError("unknown hint arm")
    service = FixedCorpus(case, out)
    builtins = get_builtin_tools()
    modules = [
        importlib.import_module(f"plugins.tools.{name}")
        for name in (
            "corpus_search",
            "corpus_fetch",
            "corpus_inventory",
            "corpus_manifest",
        )
    ]
    service_module = importlib.import_module("plugins.corpus.service")
    original = service_module.get_service
    hint = modules[0].REFERENCE_HINT if arm == "A" else HINT_B
    with ExitStack() as stack:
        stack.enter_context(
            patch.dict(
                os.environ,
                {
                    "APODEX_RUN_DIR": str(out),
                    "CORPUS_TOOL_REF_ROOT": str(out / "tool-refs"),
                    "CORPUS_SEARCH_REF_ROOT": str(out / "search-refs"),
                },
            )
        )
        # Include already-imported aliases used by report publication and verification.
        for module in list(sys.modules.values()):
            if getattr(module, "__name__", "").startswith("plugins.") and (
                getattr(module, "get_service", None) is original
            ):
                stack.enter_context(patch.object(module, "get_service", lambda: service))
        stack.enter_context(
            patch("psycopg.connect", side_effect=RuntimeError("fixture forbids DB"))
        )
        stack.enter_context(patch.object(modules[0], "REFERENCE_HINT", hint))
        (out / "hint.json").write_text(
            json.dumps({"arm": arm, "REFERENCE_HINT": hint}, ensure_ascii=False)
        )
        result = {name: builtins[name] for name in COORDINATION}

        def wrap(tool: Tool) -> Tool:
            async def call(**kwargs: Any) -> str:
                raw = await tool.func(**kwargs)
                service.observed(tool.name, kwargs, raw)
                return raw

            return replace(tool, func=call)

        for name in CORPUS_TOOLS:
            result[name] = wrap(builtins[name])
        yield result


def measure_corpus(trial: Path) -> dict[str, Any]:
    """Tool-return telemetry; actual model delivery and sufficiency need trace review.

    Only accepted attempts are booked. A failed call neither counts as a repeat
    nor establishes the redundancy baseline, so a retry after an identical failed
    call is recovery resampling, not waste; redundancy means repeating a success.
    Repeats are also content-grounded: identical arguments can be different
    effective requests under per-range clamps (cursor tokens collide across
    ranges), so a re-issue only books when the majority of its delivered chars
    were already delivered before.
    """
    from collections import Counter

    path = trial / "corpus-tools.jsonl"
    if not path.exists():
        return {"available": False}
    rows = [json.loads(line) for line in path.read_text().splitlines()]

    def accepted(row: dict[str, Any]) -> bool:
        result = row.get("result") or {}
        return result.get("ok") is not False and result.get("error") is None

    def key(row: dict[str, Any]) -> str:
        return row["name"] + " " + json.dumps(row["args"], sort_keys=True)

    names = Counter(row["name"] for row in rows)
    repeats: Counter[str] = Counter()
    query_repeats: Counter[str] = Counter()
    previously_accepted: dict[str, bool] = {}
    seen: dict[str, list[tuple[int, int]]] = {}
    repeated_chars = total_chars = 0
    for row in rows:
        request_key = key(row)
        query = str(row["args"].get("query")) if row["name"] == "corpus_search" else None
        if not accepted(row):
            previously_accepted[request_key] = False
            if query is not None:
                previously_accepted["query " + query] = False
            continue
        was_accepted = previously_accepted.get(request_key)
        recovery = was_accepted is False
        delivered_chars = overlap_chars = 0
        for span in row["returned_intervals"]:
            unit, left, right = span["unit_id"], span["start"], span["end"]
            delivered_chars += right - left
            total_chars += right - left
            previous = seen.get(unit, [])
            hit = sum(max(0, min(right, b) - max(left, a)) for a, b in previous)
            overlap_chars += hit
            if not recovery:
                repeated_chars += hit
            merged: list[tuple[int, int]] = []
            for a, b in sorted([*previous, (left, right)]):
                if merged and a <= merged[-1][1]:
                    merged[-1] = (merged[-1][0], max(b, merged[-1][1]))
                else:
                    merged.append((a, b))
            seen[unit] = merged
        if not recovery:
            grounded = (
                overlap_chars * 2 >= delivered_chars if delivered_chars else was_accepted is True
            )
            if grounded:
                repeats[request_key] += 1
                if query is not None:
                    query_repeats[query] += 1
        previously_accepted[request_key] = True
        if query is not None:
            previously_accepted["query " + query] = True
    document_returns = [
        r for r in rows if r["name"] == "corpus_fetch" and r["result"].get("scope") == "document"
    ]
    pages = [r for r in document_returns if r["result"].get("ok") is True]
    return {
        "available": True,
        "tool_calls": dict(names),
        "same_tool_reuses": sum(n - 1 for n in names.values()),
        "exact_repeated_requests": sum(repeats.values()),
        "repeated_query_strings": sum(query_repeats.values()),
        "reference_hint_emissions": sum(r["reference_hint_emitted"] for r in rows),
        "document_pages_returned": len(pages),
        "document_failure_returns": len(document_returns) - len(pages),
        "document_completion_returns": sum(bool(r["result"].get("fetch_complete")) for r in pages),
        "original_chars_returned": total_chars,
        "repeated_original_chars": repeated_chars,
        "returned_unit_ranges": seen,
        "scope": "accepted tool returns before runtime delivery; not a semantic verdict",
    }
