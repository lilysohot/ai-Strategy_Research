"""Authenticated OCR HTTP endpoint; no database access or model downloads."""

from __future__ import annotations

import hashlib
import hmac
import json
import os
import subprocess
import sys
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

ROOT = Path(os.environ.get("OCR_DATA_ROOT", "/results"))
RELEASE = os.environ.get("OCR_RELEASE", "rapidocr-production-v1")
LOCK = threading.BoundedSemaphore(1)
MAX_BYTES = 100 * 1024 * 1024


def process(data: bytes, page: int) -> dict[str, Any]:
    source_sha = hashlib.sha256(data).hexdigest()
    key = hashlib.sha256(f"{RELEASE}:{source_sha}:{page}".encode()).hexdigest()
    folder = ROOT / key
    folder.mkdir(parents=True, exist_ok=True)
    final = folder / "response.json"
    if final.exists():
        cached = json.loads(final.read_text())
        if cached["status"] in {"ok", "orientation_unknown", "empty"}:
            return cached
    (folder / "input.pdf").write_bytes(data)
    worker_result = folder / "worker.json"
    worker_result.unlink(missing_ok=True)
    try:
        with (folder / "worker.log").open("wb") as log:
            subprocess.run(
                [
                    sys.executable,
                    "/opt/ocr-code/worker.py",
                    str(folder / "input.pdf"),
                    str(page),
                    str(worker_result),
                ],
                stdout=log,
                stderr=subprocess.STDOUT,
                check=True,
                timeout=90,
                env={
                    "PATH": os.environ["PATH"],
                    "OMP_NUM_THREADS": "1",
                    "PYTHONDONTWRITEBYTECODE": "1",
                },
            )
        result = json.loads(worker_result.read_text())
    except subprocess.TimeoutExpired:
        result = {"status": "timeout", "text": ""}
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        result = {"status": "error", "text": "", "error_type": type(exc).__name__}
    response = {
        **result,
        "artifact_id": key,
        "ocr_release": RELEASE,
        "source_pdf_sha256": source_sha,
        "page": page,
        "text_origin": "ocr",
        "human_verified": False,
        "text_only": True,
        "chart_semantics_verified": False,
        "table_structure_verified": False,
    }
    temporary = folder / "response.tmp"
    temporary.write_text(json.dumps(response, ensure_ascii=False), encoding="utf8")
    temporary.replace(final)
    return response


class Handler(BaseHTTPRequestHandler):
    def reply(self, status: int, value: object) -> None:
        data = json.dumps(value, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_GET(self) -> None:
        if self.path == "/healthz":
            self.reply(200, {"status": "ready", "ocr_release": RELEASE})
        else:
            self.reply(404, {"status": "not_found"})

    def do_POST(self) -> None:
        token = Path(os.environ["OCR_TOKEN_FILE"]).read_text().strip()
        if not token or not hmac.compare_digest(self.headers.get("Authorization", ""), token):
            self.reply(401, {"status": "unauthorized"})
            return
        if self.path != "/ocr":
            self.reply(404, {"status": "not_found"})
            return
        try:
            length = int(self.headers.get("Content-Length", "0"))
            page = int(self.headers.get("X-OCR-Page", "1"))
            if not 0 < length <= MAX_BYTES or page < 1:
                raise ValueError
        except ValueError:
            self.reply(400, {"status": "invalid_request"})
            return
        if not LOCK.acquire(blocking=False):
            self.reply(429, {"status": "busy"})
            return
        try:
            self.connection.settimeout(20)
            data = self.rfile.read(length)
            if len(data) != length or not data.startswith(b"%PDF-"):
                self.reply(400, {"status": "invalid_pdf"})
                return
            result = process(data, page)
            self.reply(200 if result["status"] == "ok" else 422, result)
        finally:
            LOCK.release()

    def log_message(self, format: str, *args: object) -> None:
        # Never log headers, credentials, PDF text or user-controlled request paths.
        return


if __name__ == "__main__":
    ROOT.mkdir(parents=True, exist_ok=True)
    if not Path(os.environ["OCR_TOKEN_FILE"]).read_text().strip():
        raise RuntimeError("OCR token must be configured")
    ThreadingHTTPServer(("0.0.0.0", 8780), Handler).serve_forever()
