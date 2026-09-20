"""Recompute image-region separation from hash-verified PDF bytes and kept units.

Only geometry is inspected. No OCR, quote reconstruction, source edits or caller-supplied
boxes. Human completeness/meaning remains the responsibility of the signed credential.
"""

from __future__ import annotations

import math
from pathlib import Path
from typing import TYPE_CHECKING

from plugins.corpus.preparation.contract import Unit, sha256_of_bytes

if TYPE_CHECKING:
    from plugins.corpus.preparation.gap_review import GapReview


def _box(value: object) -> tuple[float, float, float, float]:
    if not isinstance(value, (tuple, list)) or len(value) != 4:
        raise ValueError("missing region box")
    if any(
        isinstance(v, bool) or not isinstance(v, (float, int)) or not math.isfinite(v)
        for v in value
    ):
        raise ValueError("nonfinite or malformed region box")
    x0, y0, x1, y1 = (float(v) for v in value)
    if x0 >= x1 or y0 >= y1:
        raise ValueError("empty or inverted region box")
    return x0, y0, x1, y1


def verify_region_targets(review: GapReview, kept: tuple[Unit, ...]) -> set[int]:
    """All signed quotes must survive in geometrically verified, disjoint full units.

    Conservative limits: unrotated PDF pages and quotes contained in individual kept
    units only. Every image placement and every matching unit is checked; ambiguous
    duplicates cannot be resolved by choosing the convenient location.
    """
    import pymupdf

    raw = Path(review.region_source_path).read_bytes()
    if sha256_of_bytes(raw) != review.source_id:
        raise ValueError("region source bytes differ from signed source hash")
    pages: set[int] = set()
    with pymupdf.open(stream=raw, filetype="pdf") as document:
        if not document.is_pdf or document.needs_pass:
            raise ValueError("region proof requires an accessible PDF")
        for locator, quotes in review.region_targets:
            number = int(locator.split(":")[1])
            if not 1 <= number <= len(document):
                raise ValueError("region page outside PDF")
            page = document[number - 1]
            if page.rotation:
                raise ValueError("rotated region coordinates are not supported")
            bounds = _box(tuple(page.rect))
            images = [_box(info["bbox"]) for info in page.get_image_info()]
            if not images:
                raise ValueError("image gap has no verifiable image placements")
            for quote in quotes:
                matches = [u for u in kept if u.location.page == number and quote in u.raw_text]
                if not matches:
                    raise ValueError("required region quote is not fully retained in a unit")
                for unit in matches:
                    box = _box(unit.location.bbox)
                    if not (
                        bounds[0] <= box[0] < box[2] <= bounds[2]
                        and bounds[1] <= box[1] < box[3] <= bounds[3]
                    ):
                        raise ValueError("evidence box outside page bounds")
                    # Exact quote matching above is never normalized. Whitespace-only
                    # normalization here checks geometry against PDF's native text layout.
                    clipped = page.get_textbox(pymupdf.Rect(box))
                    if "".join(unit.raw_text.split()) not in "".join(clipped.split()):
                        raise ValueError("unit text is not backed by its PDF box")
                    if any(
                        not (
                            box[2] < image[0]
                            or image[2] < box[0]
                            or box[3] < image[1]
                            or image[3] < box[1]
                        )
                        for image in images
                    ):
                        raise ValueError("image and required evidence boxes intersect or touch")
            pages.add(number)
    return pages
