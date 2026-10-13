#!/usr/bin/env python3
"""0c: dump the raw response body of one minimal call (diagnostic scope).

Purpose: the 0b probe reported ``ok=true`` while returning an empty body, and the
fail-closed re-probe reported ``ok=false``. Both were guesses about *why* — this
script spends one call to print the actual HTTP status, a safe header subset and
the raw body, so the cause is known instead of inferred.

Faithful to the adapter path (plugins/corpus/structured/adapter.py:185-192):
POST ``{base_url}/chat/completions`` with ``Authorization`` + ``Idempotency-Key``,
body = messages + stream:False + token parameter + tool_choice:"none". The adapter
deliberately never sends ``response_format``; this diagnostic does not either.

The credential is never printed: only its length and a masked prefix are shown.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.structured.config import (  # noqa: E402 - needs sys.path first
    RequestOptions,
    load_extraction_config,
)

RAW_LIMIT = 1200
SAFE_HEADERS = ("content-type", "content-length", "x-request-id", "server", "date")


def _mask(secret: str) -> str:
    if not secret:
        return "<empty>"
    return f"{secret[:4]}…({len(secret)} chars)"


def diagnose() -> dict[str, Any]:
    import httpx

    cfg = load_extraction_config(
        dotenv_path=REPO_ROOT / ".env",
        options=RequestOptions(max_output_tokens=16, timeout_seconds=30.0),
    )
    if not cfg.configured:
        return {"ok": False, "stage": "config", "error_codes": list(cfg.error_codes)}

    profile = cfg.require_profile()
    credential = cfg.credential
    if credential is None:
        return {"ok": False, "stage": "config", "error_codes": ["CS_CREDENTIAL_MISSING"]}
    secret = credential.get_secret_value()
    body: dict[str, Any] = {
        "model": profile.model,
        "messages": [{"role": "user", "content": "ping"}],
        "stream": False,
        profile.options.token_parameter: profile.options.max_output_tokens,
        "tool_choice": "none",
    }
    report: dict[str, Any] = {
        "request": {
            "url": profile.base_url + "/chat/completions",
            "base_url_host": profile.base_url.split("/")[2],
            "model": profile.model,
            "body_keys": sorted(body),
            "token_parameter": profile.options.token_parameter,
            "response_format_sent": False,
            "tool_choice": body["tool_choice"],
            "authorization": _mask(secret),
        }
    }
    try:
        with httpx.Client(
            transport=httpx.HTTPTransport(),
            timeout=profile.options.timeout_seconds,
            trust_env=False,
            follow_redirects=False,
        ) as client:
            response = client.post(
                report["request"]["url"],
                headers={
                    "Authorization": f"Bearer {secret}",
                    "Idempotency-Key": "diagnostic-0c-empty-body",
                },
                json=body,
            )
    except Exception as exc:  # the diagnostic reports, never raises
        report.update(ok=False, stage="send", error_type=type(exc).__name__)
        report["error_detail"] = str(exc)[:200]
        return report

    raw = response.text
    report.update(
        ok=200 <= response.status_code < 300 and bool(raw.strip()),
        stage="call",
        http_status=response.status_code,
        headers={k: v for k, v in response.headers.items() if k in SAFE_HEADERS},
        raw_len=len(raw),
        raw_body=raw[:RAW_LIMIT],
    )
    try:
        payload = response.json()
    except ValueError:
        report["json_parse"] = "failed (not valid JSON)"
        return report
    if isinstance(payload, dict):
        report["json_top_keys"] = sorted(payload)
        report["json_model"] = payload.get("model")
        report["json_usage"] = payload.get("usage")
        choices = payload.get("choices")
        if isinstance(choices, list) and choices:
            first = choices[0] if isinstance(choices[0], dict) else {}
            message = first.get("message")
            report["json_finish_reason"] = first.get("finish_reason")
            report["json_message_keys"] = (
                sorted(message) if isinstance(message, dict) else f"<{type(message).__name__}>"
            )
            report["json_content_len"] = (
                len((message or {}).get("content") or "") if isinstance(message, dict) else None
            )
        else:
            report["json_choices"] = f"<{type(choices).__name__}> len=0 or absent"
    else:
        report["json_top_type"] = type(payload).__name__
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-call", action="store_true", help="config only, zero model calls")
    args = parser.parse_args()
    if args.no_call:
        print(json.dumps({"scope": "0c", "model_calls": 0}, ensure_ascii=False))
        return
    print(json.dumps(diagnose(), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
