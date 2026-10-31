"""Add provenance-tagged OCR supplements without rewriting native evidence."""

from __future__ import annotations

import math
import time
from dataclasses import replace
from pathlib import Path
from typing import Any

import pymupdf

from plugins.corpus.preparation.contract import UnitLocation, UnitStatus
from plugins.corpus.preparation.readers.base import CandidateUnit, ReaderIssue, ReaderResult
from plugins.corpus.preparation.structure import StructuredDocument, StructureNode, TextOrigin
from plugins.local_ocr.client import configured_release, recognize_page

TARGET_GAPS = frozenset({"image_only_page", "image_region_unreadable", "garbled_text"})


def native_coverage(box: list[float], words: list[list[float]]) -> float:
    x0, y0, x1, y1 = box
    middle = (y0 + y1) / 2
    intervals = sorted(
        (max(x0, a), min(x1, c))
        for a, b, c, d in words
        if b <= middle <= d and min(x1, c) > max(x0, a)
    )
    covered, end = 0.0, x0
    for lo, hi in intervals:
        covered += max(0.0, hi - max(lo, end))
        end = max(end, hi)
    return covered / (x1 - x0)


def supplemental_lines(
    response: dict[str, Any], words: list[list[float]]
) -> list[tuple[int, str, list[float]]]:
    lines, boxes, scores = response["lines"], response["boxes_normalized_input"], response["scores"]
    if len(lines) != len(boxes) or len(lines) != len(scores):
        raise ValueError("OCR coordinate lengths disagree")
    supplements = []
    for i, (text, quad, score) in enumerate(zip(lines, boxes, scores, strict=True)):
        if (
            not isinstance(text, str)
            or len(quad) != 4
            or not math.isfinite(score)
            or not 0 <= score <= 1
        ):
            raise ValueError("Invalid OCR line metadata")
        if any(len(p) != 2 or not all(math.isfinite(v) and 0 <= v <= 1 for v in p) for p in quad):
            raise ValueError("Invalid OCR coordinates")
        box = [
            min(p[0] for p in quad),
            min(p[1] for p in quad),
            max(p[0] for p in quad),
            max(p[1] for p in quad),
        ]
        if box[2] <= box[0] or box[3] <= box[1]:
            raise ValueError("Degenerate OCR coordinates")
        if text.strip() and native_coverage(box, words) < 0.65:
            supplements.append((i, text, box))
    return supplements


def enrich(native: ReaderResult, path: Path) -> ReaderResult:
    release = configured_release()
    if not release:
        return native
    assert native.structure is not None
    nodes = list(native.structure.nodes)
    units = list(native.units)
    issues = list(native.issues)
    pages = sorted(
        {
            int(i.location.split(":")[1])
            for i in issues
            if i.code in TARGET_GAPS and i.location.startswith("page:")
        }
    )
    # Preserve unresolved original image/table gaps: recognition is not chart semantics.
    deadline = time.monotonic() + 600
    ordinal = max((u.ordinal for u in units), default=-1) + 1
    with pymupdf.open(path) as doc:
        for page_no in pages:
            if time.monotonic() >= deadline:
                raise RuntimeError(
                    "OCR document budget exhausted; retry build, not a partial checkpoint"
                )
            response = recognize_page(path, page_no)
            if response["status"] not in {"ok", "orientation_unknown", "empty"}:
                raise RuntimeError(
                    f"OCR failed: {response['status']}; no reusable success checkpoint"
                )
            if response["status"] != "ok":
                issues.append(
                    ReaderIssue(
                        "local_ocr_unresolved",
                        f"page:{page_no}",
                        f"{response['status']}; artifact={response['artifact_id']}; release={release}",
                    )
                )
                continue
            page = doc[page_no - 1]
            w, h = page.rect.width, page.rect.height
            words = []
            for word in page.get_text("words"):
                r = pymupdf.Rect(word[:4]) * page.rotation_matrix
                words.append([r.x0 / w, r.y0 / h, r.x1 / w, r.y1 / h])
            for index, text, box in supplemental_lines(response, words):
                reasons = (
                    "local_ocr_unverified",
                    f"ocr_release:{release}",
                    f"ocr_artifact:{response['artifact_id']}",
                )
                # Keep source-page coordinates even when OCR rotated its working image.
                location = UnitLocation(
                    page=page_no,
                    element=f"local_ocr:line:{index}",
                    bbox=(box[0] * w, box[1] * h, box[2] * w, box[3] * h),
                )
                unit = CandidateUnit(ordinal, "paragraph", UnitStatus.KEPT, reasons, text, location)
                units.append(unit)
                nodes.append(
                    StructureNode(
                        f"ocr:{page_no}:{index}",
                        ordinal,
                        unit.kind,
                        unit.status,
                        unit.reasons,
                        unit.raw_text,
                        unit.location,
                        TextOrigin.OCR,
                    )
                )
                ordinal += 1
            issues.append(
                ReaderIssue(
                    "local_ocr_applied",
                    f"page:{page_no}",
                    f"文字 OCR 补充，非人工逐字校验；图表语义仍未读取；artifact={response['artifact_id']}; release={release}",
                )
            )
    return replace(
        native,
        extractor_rev=revision(native.extractor_rev, release),
        units=tuple(units),
        issues=tuple(issues),
        structure=StructuredDocument(tuple(nodes), native.structure.relations),
    )


def revision(native_rev: str, release: str) -> str:
    return f"{native_rev}+local-ocr-supplement-1:{release}" if release else native_rev
