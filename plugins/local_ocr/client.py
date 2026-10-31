"""Version-pinned production client. Missing or failed OCR is never success."""

from __future__ import annotations

import hashlib
import json
import os
import urllib.error
import urllib.request
from pathlib import Path
from typing import Any


def configured_release() -> str:
    if os.environ.get("CORPUS_LOCAL_OCR_ENABLED", "").lower() not in {"1", "true"}:
        return ""
    release = os.environ.get("CORPUS_LOCAL_OCR_RELEASE", "")
    if not release or not os.environ.get("READDOC_OCR_URL"):
        raise ValueError("Enabled corpus OCR requires URL and a pinned release")
    return release


def recognize_page(path: Path, page: int) -> dict[str, Any]:
    release = configured_release()
    if not release:
        raise ValueError("Local OCR is disabled")
    data = path.read_bytes()
    if len(data) > 100 * 1024 * 1024:
        raise ValueError("OCR input exceeds 100 MiB")
    req = urllib.request.Request(
        os.environ["READDOC_OCR_URL"].rstrip("/") + "/ocr",
        data=data,
        headers={
            "Authorization": os.environ.get("READDOC_OCR_KEY", ""),
            "Content-Type": "application/pdf",
            "X-OCR-Page": str(page),
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=100) as response:
            result = json.load(response)
    except urllib.error.HTTPError as exc:
        if exc.code != 422:
            raise
        result = json.loads(exc.read())
    if (
        result.get("ocr_release") != release
        or result.get("source_pdf_sha256") != hashlib.sha256(data).hexdigest()
        or result.get("page") != page
    ):
        raise ValueError("OCR provenance/version mismatch")
    return result
