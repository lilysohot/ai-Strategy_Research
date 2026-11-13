"""Model-visible projections of corpus search, fetch and manifest results.

The complete tool result stays on the internal side of the boundary: observers
read it from :func:`try_materialize` (or directly at ``on_tool_result``), while
the model receives a whitelist-built view. Nothing is produced by string
trimming of serialized JSON, no ``text`` field is ever dropped, and unknown
new fields never enter the model view by default.

Before a view can hide anything, the complete result is persisted as a
content-addressed ``cmeta`` receipt (see :mod:`plugins.corpus.tool_refs`). A
failed search/fetch write degrades to the full self-contained body with an explicit marker;
it never emits a handle that cannot be resolved. The receipt is associated
with ``tool_call_id`` in the consumer ledger and can be rebuilt from inherited
receipts after a worker restart.
Navigation manifest feedback instead fails explicitly on a failed snapshot;
its internal coordinates and exception details must never be replayed to the model.
"""

from __future__ import annotations

import json
import os
import threading
from typing import Any

from plugins.corpus import tool_refs

#: Field projection protocol. Kept distinct from the existing result contracts:
#: hiding metadata must not silently change what counts as delivered evidence.
VISIBLE_VERSION = "corpus-visible-v1"
#: Optional navigation protocol (search selects, fetch delivers verbatim text).
NAVIGATION_VERSION = "corpus-navigation-v1"
UNAVAILABLE_VERSION = "corpus-visible-unavailable"

TOOL_SEARCH = "corpus_search"
TOOL_FETCH = "corpus_fetch"
TOOL_MANIFEST = "corpus_submit_manifest"
_TOOL_NAMES = frozenset({TOOL_SEARCH, TOOL_FETCH, TOOL_MANIFEST})
_PREVIEW_LIMIT = 200
_MAX_LIMITATIONS = 6
_MAX_INDEX = 2048

NAV_SEARCH_HINT = (
    "hits 只是候选：ref 交给 corpus_fetch 读取原文；preview 不可引用。"
    "filename 是真实文件名，document_title 是文档标题，section_title 只是命中的章节小标题；"
    "回答「文件名」类问题用 filename，不要把 section_title 当成文件名。"
    "evidence 只填实际读到的 evidence_ref，不要复制候选身份字段。"
)
NAV_FETCH_HINT = (
    "source.filename/document_title 标明所属文档，section_title 只是章节小标题；"
    "items 是逐字原文；引用只用 evidence_ref。只传 next_cursor 续读，"
    "fetch_complete=false 或 limitations 非空时不得声称已读完或内容完整。"
)


class MetadataSnapshotError(ValueError):
    """The complete result behind a projected view is missing or unusable."""


# ── step 1: whitespace-style whitelists (explicit field projection) ─────

#: Outer search fields. ``coverage`` / ``delivery`` are full diagnostics: the
#: conclusion-relevant subset becomes short ``limitations`` instead.
_SEARCH_OUTER_KEYS = (
    "ok",
    "query",
    "count",
    "hits",
    "hits_total",
    "hits_elided",
    "previews_elided",
    "diagnostics_elided",
    "plans_compacted",
    "budget",
    "error",
    "abstain",
    "reference_storage",
    "delivery_preview",
    "delivery_preview_error",
    "hint",
    "limitations",
)

#: Compatible view: everything the current next call still needs (doc_id,
#: locator/context_locators, evidence refs, scope_ref and the cursor plan) stays.
#: Only duplicate identities, block/chunk coordinates and ranking diagnostics go.
_SEARCH_HIT_KEYS = (
    "doc_id",
    "title",
    "filename",
    "document_title",
    "section_title",
    "published",
    "ingested_at",
    "publication_date_basis",
    "snippet",
    "evidence_contract",
    "evidence_spans",
    "excerpts",
    "preview",
    "locator",
    "context_locators",
    "fetch_plan",
    "core_fetch_plan",
    "scope_ref",
    "available_blocks",
    "expansion",
    "delivery_hint",
)

#: Outer fetch fields. Everything else (build/source IDs, hashes, geometry,
#: schema/page IDs, block_evidence, units, semantic_cells ...) stays后台.
_FETCH_OUTER_KEYS = (
    "ok",
    "error",
    "code",
    "retryable",
    "failure_scope",
    "doc_id",
    "locator",
    "kind",
    "view",
    "title",
    "filename",
    "document_title",
    "section_title",
    "text",
    "evidence_ref",
    "page",
    "pages",
    "unit_id",
    "content_role",
    "relations",
    "relation_status",
    "relation_count",
    "relations_elided",
    "label_path",
    "label_path_count",
    "label_path_elided",
    "structure_status",
    "content_status",
    "content_scope",
    "display_groups",
    "table_row",
    "pagination_policy_version",
    "max_chars",
    "ocr_unverified",
    "ocr_notice",
    "text_origin",
    "status",
    "view_fallback",
    "diagnostics_elided",
    "items",
    "item_errors",
    "item_errors_count",
    "unresolved",
    "unresolved_count",
    "next_cursor",
    "retry_cursor",
    "cursor_omitted",
    "exhausted",
    "fetch_complete",
    "scope",
    "coverage_scope",
    "unit_range",
    "position",
    "hint",
    "limitations",
)

_FETCH_ITEM_KEYS = (
    "locator",
    "unit_id",
    "kind",
    "section_title",
    "page",
    "pages",
    "text",
    "evidence_ref",
    "fragment",
    "content_role",
    "relations",
    "relation_status",
    "relation_count",
    "relations_elided",
    "label_path",
    "label_path_count",
    "label_path_elided",
    "structure_status",
    "content_status",
    "content_scope",
    "display_groups",
    "table_row",
    "pagination_policy_version",
    "max_chars",
    "ocr_unverified",
    "ocr_notice",
    "text_origin",
    "status",
    "view_fallback",
    "next_cursor",
)


_NAVIGATION_DISABLED = frozenset({"0", "off", "false", "no"})


def navigation_enabled() -> bool:
    """Navigation is on by default; set ``CORPUS_NAVIGATION_MODE=off`` to disable.

    Both the tool-result projection and the Web prompt addendum must read this
    one switch, otherwise the model gets a nav view with legacy instructions
    (or vice versa).
    """
    return (
        os.environ.get("CORPUS_NAVIGATION_MODE", "on").strip().lower() not in _NAVIGATION_DISABLED
    )


def short_preview(value: Any) -> Any:
    if not isinstance(value, str) or len(value) <= _PREVIEW_LIMIT:
        return value
    return value[:_PREVIEW_LIMIT] + "…（预览截断，仅供定位，不可引用）"


def _bounded(limitations: list[str]) -> list[str]:
    out: list[str] = []
    for item in limitations:
        if item and item not in out:
            out.append(str(item)[:100])
        if len(out) >= _MAX_LIMITATIONS:
            break
    return out


def search_limitations(coverage: Any, payload: dict[str, Any]) -> list[str]:
    """Turn conclusion-relevant coverage states into short readable notes."""
    out: list[str] = []
    if not isinstance(coverage, dict):
        out.append("本次检索覆盖信息不可用；未命中不代表资料不存在。")
    else:
        if coverage.get("abstain"):
            out.append("检索被判为无实质答案（abstain），不等于全库无资料。")
        elif coverage.get("query_status") == "no_match":
            out.append("当前检索范围无匹配，不等于资料不存在。")
        processing = coverage.get("processing")
        if isinstance(processing, str) and processing not in ("full", "complete", "ok"):
            out.append(f"检索范围受限（processing={processing}），结果不覆盖全部已发布资料。")
        purity = coverage.get("purity")
        if isinstance(purity, dict) and purity.get("sources_filtered"):
            out.append("部分候选经相关性与结构筛选排除，不代表资料库无答案。")
        if coverage.get("date_filter"):
            out.append("本次按发布日期筛选；日期未知或仅由文件名推断的资料可能未纳入。")
        if coverage.get("ingestion_filter"):
            out.append("本次按首次入库日期筛选，范围外的资料未纳入。")
        native = coverage.get("native") or {}
        if isinstance(native, dict):
            count = native.get("unknown_date_source_count")
            if isinstance(count, int) and count > 0:
                out.append(f"{count} 个来源发布日期未知，时效判断需注意。")
            if native.get("degraded") or native.get("fallback"):
                out.append("检索曾降级，结果不是完整排序视图；请如实说明限制。")
        codes = coverage.get("reason_codes")
        if isinstance(codes, (list, tuple)) and codes:
            out.append("检索限制：" + "、".join(str(c) for c in codes[:3]))
    if payload.get("reference_storage") == "unavailable_v1_fallback":
        out.append("引用收据存储不可用，本次改用自包含旧结果；校验仍按原规则执行。")
    if payload.get("hits_elided"):
        out.append(f"有 {payload['hits_elided']} 条尾部命中因预算被整条省略，未被读取。")
    if payload.get("previews_elided") or payload.get("diagnostics_elided"):
        out.append("部分预览或诊断信息因预算省略；可见正文未被字符截断。")
    if payload.get("ok") is False and payload.get("error"):
        out.append("本次工具调用失败；不得把未送达结果当作证据。")
    return _bounded(out)


def _copy(source: dict[str, Any], keys: tuple[str, ...]) -> dict[str, Any]:
    return {key: source[key] for key in keys if key in source}


def project_search_result(full: dict[str, Any]) -> dict[str, Any]:
    """Whitelist projection for the compatible (non-navigation) search view."""
    visible = _copy(full, _SEARCH_OUTER_KEYS)
    hits = full.get("hits")
    if isinstance(hits, list):
        projected = []
        for hit in hits:
            if not isinstance(hit, dict):
                continue
            row = _copy(hit, _SEARCH_HIT_KEYS)
            for key in ("table_chunks_scope", "source_table_count"):
                if key in hit:
                    row[key] = hit[key]
            if "preview" in row:
                row["preview"] = short_preview(row["preview"])
            projected.append(row)
        visible["hits"] = projected
    visible["limitations"] = search_limitations(full.get("coverage"), full)
    return visible


def project_fetch_result(full: dict[str, Any], *, navigation: bool = False) -> dict[str, Any]:
    """Whitelist projection for fetch; navigation drops legacy handles too."""
    if navigation:
        return _project_navigation_fetch(full)
    visible = _copy(full, _FETCH_OUTER_KEYS)
    items = full.get("items")
    if isinstance(items, list):
        visible["items"] = [
            _copy(item, _FETCH_ITEM_KEYS) for item in items if isinstance(item, dict)
        ]
    existing = full.get("limitations")
    notes = [str(item) for item in existing] if isinstance(existing, list) else []
    visible["limitations"] = _bounded([*notes, *_fetch_limitations(full)])
    return visible


# ── step 2: optional navigation view ──────────────────────────────────


def _location(item: dict[str, Any]) -> str | None:
    pages = item.get("pages")
    if not isinstance(pages, list) or not pages:
        page = item.get("page")
        pages = [page] if isinstance(page, int) else []
    pages = [p for p in pages if isinstance(p, int) and not isinstance(p, bool)]
    if pages:
        return "第 " + "、".join(str(p) for p in sorted(set(pages))) + " 页"
    label_path = item.get("label_path")
    if isinstance(label_path, list) and label_path:
        return "章节：" + " / ".join(str(part) for part in label_path[:3])
    return None


def _fetch_limitations(full: dict[str, Any]) -> list[str]:
    out: list[str] = []
    errors = full.get("item_errors") or []
    if errors:
        out.append(f"{len(errors)} 个块读取失败；对应内容未送达，不得当作已读。")
    if full.get("item_errors_count"):
        out.append(f"{full['item_errors_count']} 个块读取失败（明细因预算省略）。")
    unresolved = full.get("unresolved") or []
    if unresolved:
        out.append(f"{len(unresolved)} 个成员未解决；本页不完整。")
    if full.get("unresolved_count"):
        out.append(f"{full['unresolved_count']} 个成员未解决（明细因预算省略）。")
    if full.get("cursor_omitted"):
        out.append("续读游标因预算省略；请用原请求重取本页，不要前移。")
    if full.get("fetch_complete") is False:
        out.append("请求范围内入库文本尚未读完；不能声称全文已读。")
    if full.get("source_coverage") not in (None, "complete", "full"):
        out.append("源文档提取完整性未知；fetch_complete 不证明原 PDF 内容齐全。")
    if full.get("diagnostics_elided") or full.get("view_fallback"):
        out.append("完整结构诊断已移至后台保存；可见正文逐字未变。")
    if any(
        item.get("ocr_unverified") or item.get("text_origin") == "ocr"
        for item in (full.get("items") or [full])
        if isinstance(item, dict)
    ):
        out.append("含 OCR 识别文字，未逐字人工校验；表格结构与图表语义未验证。")
    return _bounded(out)


def _project_navigation_fetch(full: dict[str, Any]) -> dict[str, Any]:
    """Target navigation view: one readable source, text, refs and continuation."""
    source: dict[str, Any] = {}
    for key in ("filename", "document_title", "section_title"):
        value = full.get(key)
        if isinstance(value, str) and value:
            source[key] = value
    if source.get("document_title") == source.get("filename"):
        source.pop("document_title", None)
    if not source.get("filename") and full.get("original_names"):
        source["filename"] = str(full["original_names"][0])
    if "section_title" not in source and isinstance(full.get("title"), str) and full["title"]:
        source["section_title"] = full["title"]
    if isinstance(full.get("ref"), str) and full["ref"].startswith("sref:"):
        source["ref"] = full["ref"]
    visible: dict[str, Any] = {
        "ok": full.get("ok") is True,
        "source": source,
        "scope": full.get("scope") or "candidates",
        "items": [],
        "next_cursor": full.get("next_cursor"),
        "fetch_complete": bool(full.get("fetch_complete")),
        "limitations": _fetch_limitations(full),
        "hint": NAV_FETCH_HINT,
    }
    if full.get("content_scope") == "ingested_text_only":
        visible.update(content_scope="ingested_text_only", content_status="ingested_text",
                       structure_status="unknown")
    raw_items = full.get("items")
    candidates = raw_items if isinstance(raw_items, list) else [full]
    for item in candidates:
        if not isinstance(item, dict) or not isinstance(item.get("text"), str):
            continue
        row: dict[str, Any] = {"text": item["text"]}
        if isinstance(item.get("evidence_ref"), str):
            row["evidence_ref"] = item["evidence_ref"]
        location = _location(item)
        if location:
            row["location"] = location
        if item.get("content_role"):
            row["content_role"] = item["content_role"]
        for key in ("content_status", "structure_status", "text_origin", "ocr_unverified"):
            if key in item and item[key] != visible.get(key):
                row[key] = item[key]
        visible["items"].append(row)
    groups = []
    for group in full.get("display_groups") or []:
        refs = [r["evidence_ref"] for r in group.get("unit_ranges", []) if r.get("evidence_ref")]
        if refs:
            groups.append({"kind": group["kind"], "relation_status": group.get("relation_status", "unverified"),
                           "evidence_refs": refs})
    if groups:
        visible["display_groups"] = groups
    if full.get("ok") is not True:
        visible["error"] = full.get("error")
    return visible


def render_fetch_view(full: dict[str, Any]) -> str:
    """Pure sizing/rendering shared by the document pager and message boundary."""
    visible = project_fetch_result(full, navigation=navigation_enabled())
    visible["protocol"] = NAVIGATION_VERSION if navigation_enabled() else VISIBLE_VERSION
    return json.dumps(visible, ensure_ascii=False, separators=(",", ":"))


def process_document_result(body: str, *, tool_call_id: str = "") -> str | None:
    """v2 document pages have their own visible budget; other fetch paths are unchanged."""
    try:
        full = json.loads(body)
    except (TypeError, ValueError):
        return None
    if not isinstance(full, dict):
        return None
    full = try_materialize(TOOL_FETCH, body, tool_call_id=tool_call_id)
    if not full or full.get("scope") != "document" or full.get("pagination_policy_version") != 2:
        return None
    from plugins.corpus.pagination_policy import DOCUMENT_VISIBLE_CAP
    from plugins.tools.corpus_fetch import fit_structured_payload

    return fit_structured_payload(body, DOCUMENT_VISIBLE_CAP)


# ── receipt-backed association ────────────────────────────────────────

_lock = threading.Lock()
_BY_VISIBLE: dict[str, str] = {}
_BY_CALL: dict[str, str] = {}
_KNOWN_PROTOCOLS = frozenset({VISIBLE_VERSION, NAVIGATION_VERSION})


def _digest(body: str) -> str:
    import hashlib

    return hashlib.sha256(body.encode("utf-8", "replace")).hexdigest()


def _remember(visible_digest: str, ref: str, tool_call_id: str) -> None:
    with _lock:
        if len(_BY_VISIBLE) >= _MAX_INDEX:
            _BY_VISIBLE.clear()
            _BY_CALL.clear()
        _BY_VISIBLE[visible_digest] = ref
        if tool_call_id:
            _BY_CALL[tool_call_id] = ref


def remember_snapshot(visible_body: str, ref: str, tool_call_id: str = "") -> None:
    """Register an externally written snapshot (navigation search results)."""
    _remember(_digest(visible_body), ref, tool_call_id)


def reset_snapshot_index() -> None:
    """Drop process-local bindings (worker restart / isolated replay tests)."""
    with _lock:
        _BY_VISIBLE.clear()
        _BY_CALL.clear()


def call_snapshot_refs() -> dict[str, str]:
    """Snapshot of ``tool_call_id -> cmeta`` bindings for the ledger artifact."""
    with _lock:
        return dict(_BY_CALL)


def _snapshot_ref(body: str, tool_call_id: str) -> str | None:
    digest = _digest(body)
    with _lock:
        ref = _BY_VISIBLE.get(digest)
        if ref is None and tool_call_id:
            ref = _BY_CALL.get(tool_call_id)
    if ref is None:
        ref = tool_refs.metadata_snapshot_index().get(digest)
        if ref:
            _remember(digest, ref, tool_call_id)
    return ref


def _degrade(payload: dict[str, Any]) -> str:
    """Keep the full self-contained result when the snapshot cannot be saved."""
    degraded = dict(payload)
    degraded["protocol"] = UNAVAILABLE_VERSION
    existing = payload.get("limitations")
    notes = [str(item) for item in existing] if isinstance(existing, list) else []
    notes.append("完整元数据快照不可用：未隐藏任何字段，继续按原结果校验。")
    degraded["limitations"] = _bounded(notes)
    return json.dumps(degraded, ensure_ascii=False)


def fetch_error_view(payload: dict[str, Any]) -> dict[str, Any]:
    """Expose failure kinds and recovery, never per-unit internal coordinates."""
    errors = [e for e in payload.get("item_errors", []) if isinstance(e, dict)]
    counts: dict[str, int] = {}
    for error in errors:
        code = str(error.get("code") or "fetch_failed")[:80]
        counts[code] = counts.get(code, 0) + 1
    code = str(payload.get("code") or (next(iter(counts)) if len(counts) == 1 else
                                      "fetch_failed"))[:80]
    out: dict[str, Any] = {
        "ok": False, "code": code, "error": code,
        "item_errors_count": len(errors),
        "unresolved_count": len(payload.get("unresolved") or []),
        "fetch_complete": False,
        "hint": ("Increase max_chars or narrow the request; retry the same ref."
                 if code in {"budget_exceeded", "unit_too_large"}
                 else "Fetch failed; no source evidence was delivered. Check the request or retry."),
    }
    if len(counts) > 1:
        out["error_codes"] = counts
    for key in ("retryable", "failure_scope"):
        if key in payload:
            out[key] = payload[key]
    cursor = payload.get("next_cursor")
    if isinstance(cursor, str) and cursor.startswith("cpage:") and len(cursor) <= 256:
        out["next_cursor"] = cursor
    elif cursor:
        out["cursor_omitted"] = True
    retry = payload.get("retry_cursor")
    if isinstance(retry, str) and retry.startswith("cpage:") and len(retry) <= 256:
        out["retry_cursor"] = retry
    return out


def project_tool_result(
    name: str, body: str, *, tool_call_id: str = "", error_budget: int = 1500,
) -> str:
    """Build and persist the model-visible view of one corpus tool result.

    Called at the message boundary (the workflow result post-processors),
    after the structured budget fitter has finished for successful search/fetch.
    Failed fetch envelopes also call this before returning to honor max_chars. Manifest
    feedback is projected before any generic character cap. Observers at
    ``on_tool_result`` therefore still receive the complete internal result.
    """
    if name not in _TOOL_NAMES or not isinstance(body, str):
        return body
    try:
        full = json.loads(body)
    except (TypeError, ValueError):
        if name == TOOL_MANIFEST and navigation_enabled():
            from plugins.corpus.manifest_view import unavailable_manifest_result

            return json.dumps(unavailable_manifest_result(), ensure_ascii=False)
        return body
    if not isinstance(full, dict):
        if name == TOOL_MANIFEST and navigation_enabled():
            from plugins.corpus.manifest_view import unavailable_manifest_result

            return json.dumps(unavailable_manifest_result(), ensure_ascii=False)
        return body
    protocol = full.get("protocol")
    if protocol in (VISIBLE_VERSION, NAVIGATION_VERSION, UNAVAILABLE_VERSION):
        return body
    navigation = navigation_enabled()
    manifest = name == TOOL_MANIFEST
    if manifest and not navigation:
        return body
    fetch_error = name == TOOL_FETCH and full.get("ok") is False and (
        isinstance(full.get("items"), list) or bool(full.get("code"))
    )
    if full.get("ok") is not True and not manifest and not (navigation and fetch_error):
        return body
    if navigation and name == TOOL_SEARCH:
        # corpus_search emits its own navigation view; receipts hold the rest.
        return body
    if manifest:
        from plugins.corpus.manifest_view import project_manifest_result

        visible = project_manifest_result(full)
        version = NAVIGATION_VERSION
    elif navigation and fetch_error:
        visible = fetch_error_view(full)
        version = NAVIGATION_VERSION
    elif navigation and name == TOOL_FETCH:
        visible = _project_navigation_fetch(full)
        version = NAVIGATION_VERSION
    elif name == TOOL_SEARCH:
        visible = project_search_result(full)
        version = VISIBLE_VERSION
    else:
        visible = project_fetch_result(full)
        version = VISIBLE_VERSION
    visible["protocol"] = version
    rendered = json.dumps(visible, ensure_ascii=False, separators=(",", ":"))
    if fetch_error and len(rendered) > max(400, error_budget):
        for key in ("error_codes", "failure_scope", "hint", "next_cursor", "retry_cursor"):
            if key == "next_cursor" and visible.get(key):
                visible["cursor_omitted"] = True
            visible.pop(key, None)
            rendered = json.dumps(visible, ensure_ascii=False, separators=(",", ":"))
            if len(rendered) <= max(400, error_budget):
                break
    try:
        ref = tool_refs.store_metadata_snapshot(
            name,
            full,
            protocol=version,
            visible_digest=_digest(rendered),
            tool_call_id=tool_call_id,
        )
    except (OSError, tool_refs.ToolReferenceError, TypeError, ValueError):
        if fetch_error:
            # Audit failure must not re-expose the unbounded internal envelope.
            return json.dumps({"ok": False, "code": "metadata_unavailable",
                               "protocol": NAVIGATION_VERSION,
                               "fetch_complete": False}, ensure_ascii=False)
        if manifest:
            from plugins.corpus.manifest_view import unavailable_manifest_result

            # Preserve the navigation boundary even when its audit store fails.
            unavailable = unavailable_manifest_result()
            unavailable["protocol"] = NAVIGATION_VERSION
            return json.dumps(unavailable, ensure_ascii=False)
        return _degrade(full)
    _remember(_digest(rendered), ref, tool_call_id)
    return rendered


def try_materialize(name: str, body: str, *, tool_call_id: str = "") -> dict[str, Any] | None:
    """Recover the complete internal result behind one visible tool message.

    Returns ``None`` when the receipt is missing, damaged, or belongs to a
    different protocol/tool. Callers must degrade conservatively, never treat
    a hidden field as if it had been read from the model message.
    """
    if not isinstance(body, str):
        return None
    try:
        visible = json.loads(body)
    except (TypeError, ValueError):
        return None
    if not isinstance(visible, dict):
        return None
    protocol = visible.get("protocol")
    if protocol not in _KNOWN_PROTOCOLS:
        return visible
    ref = _snapshot_ref(body, tool_call_id)
    if not ref:
        if protocol == NAVIGATION_VERSION and name == TOOL_SEARCH:
            # Navigation search is self-contained for consumers: its candidate
            # text lives in search-refs receipts, never in the model message.
            return visible
        return None
    try:
        value = tool_refs.resolve_metadata_snapshot(ref)
    except (OSError, tool_refs.ToolReferenceError):
        return None
    canonical_digest = _digest(json.dumps(visible, ensure_ascii=False, separators=(",", ":")))
    if (value.get("protocol") != protocol or value.get("tool") != name
            or value.get("visible_digest") not in {_digest(body), canonical_digest}):
        return None
    if tool_call_id:
        _remember(_digest(body), ref, tool_call_id)
    full = value.get("payload")
    return full if isinstance(full, dict) else None


def materialize(name: str, body: str, *, tool_call_id: str = "") -> dict[str, Any]:
    """Strict variant for code paths that must fail closed on a missing receipt."""
    full = try_materialize(name, body, tool_call_id=tool_call_id)
    if full is None:
        raise MetadataSnapshotError("corpus_metadata_snapshot_unavailable_or_invalid")
    return full


__all__ = [
    "NAVIGATION_VERSION",
    "NAV_FETCH_HINT",
    "NAV_SEARCH_HINT",
    "UNAVAILABLE_VERSION",
    "VISIBLE_VERSION",
    "MetadataSnapshotError",
    "call_snapshot_refs",
    "materialize",
    "navigation_enabled",
    "project_fetch_result",
    "project_search_result",
    "project_tool_result",
    "remember_snapshot",
    "reset_snapshot_index",
    "search_limitations",
    "short_preview",
    "try_materialize",
]
