"""Step-0 probe for the two-arm rerun: is the extraction endpoint actually usable?

Two modes, because the environment lies: `.env` is rewritten by parallel sessions and a
provider can 401 on one path while working on another.

* ``--no-call``  (0a, **zero model calls**): resolve the dedicated extraction
  configuration and report provider / model / base-url host / whether the key is set.
* ``--arm NAME`` (0b, **exactly one 1-token-ish call**): send the smallest possible
  prompt through the real adapter code path and record ``request_model`` vs
  ``response_model`` plus the error code, if any.

The arm is selected by the *environment*, not by a flag, so the probe can never claim to
test one model while actually calling another:

    STRUCTURED_EXTRACTION_MODEL=deepseek-v4-flash \
    STRUCTURED_EXTRACTION_BASE_URL=https://api.deepseek.com \
    STRUCTURED_EXTRACTION_API_KEY=... \
        uv run python probe_extraction_endpoint.py --arm control

Secrets are never printed — only whether the key resolved.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from plugins.corpus.structured.config import (  # noqa: E402 - needs sys.path first
    RequestOptions,
    bind_roles,
    load_extraction_config,
)


def config_report() -> dict[str, object]:
    cfg = load_extraction_config(
        dotenv_path=REPO_ROOT / ".env",
        options=RequestOptions(max_output_tokens=16, timeout_seconds=30.0),
    )
    out: dict[str, object] = {
        "configured": cfg.configured,
        "error_codes": list(cfg.error_codes),
        "missing_fields": list(cfg.missing_fields),
        "reason": cfg.reason,
    }
    if cfg.profile is not None:
        out["provider"] = cfg.profile.provider
        out["request_model"] = cfg.profile.model
        out["base_url_host"] = cfg.profile.base_url.split("//")[-1].split("/")[0]
        out["adapter_version"] = cfg.profile.adapter_version
    out["credential_resolved"] = cfg.credential is not None
    return out


def live_probe(arm: str) -> dict[str, object]:
    """One minimal call through the real adapter path."""

    import httpx

    from plugins.corpus.structured.adapter import ExtractionAdapter

    cfg = load_extraction_config(
        dotenv_path=REPO_ROOT / ".env",
        options=RequestOptions(max_output_tokens=16, timeout_seconds=30.0),
    )
    if not cfg.configured:
        return {"arm": arm, "ok": False, "stage": "config", **config_report()}

    binding = next(b for b in bind_roles(cfg) if b.role == "material_items")
    adapter = ExtractionAdapter(
        binding=binding,
        authorize=lambda intent: f"probe-{intent.request_sha256[7:23]}",
        transport_factory=lambda: httpx.HTTPTransport(),
    )
    try:
        resp = adapter("ping")
    except Exception as exc:  # the probe reports, never raises
        return {
            "arm": arm,
            "ok": False,
            "stage": "call",
            "error": type(exc).__name__,
            "detail": str(exc)[:200],
            **config_report(),
        }
    # LlmResponse is a str subclass (plugins/corpus/claims.py:53): the content IS the value,
    # while response_model/usage live in `.diagnostics`. Reading `.content` / `.model` /
    # `.usage` yields ""/None even for a good call — that produced a false
    # "empty body" verdict on 2026-10-13 and was corrected after the 0c raw-body diagnostic
    # proved the endpoint answers (HTTP 200, real content, real model).
    content = str(resp)
    diagnostics = getattr(resp, "diagnostics", None) or {}
    model = diagnostics.get("response_model") or diagnostics.get("model")
    usage = diagnostics.get("usage")
    ok = bool(content.strip()) and bool(model) and usage is not None
    return {
        "arm": arm,
        "ok": ok,
        "stage": "call",
        "verdict": (
            "endpoint_responds"
            if ok
            else "endpoint_returned_empty_body — 按 fail-closed 判失败，不得投预算"
        ),
        "response_model": model,
        "usage": usage,
        "content_len": len(content),
        "finish_reason": diagnostics.get("finish_reason"),
        "reasoning_tokens": (usage or {}).get("reasoning_tokens")
        if isinstance(usage, dict)
        else None,
        **config_report(),
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-call", action="store_true", help="0a: config only, zero model calls")
    ap.add_argument(
        "--arm", default="", help="0b: one real call, label the arm (control|treatment)"
    )
    args = ap.parse_args()

    if args.no_call or not args.arm:
        print(json.dumps(config_report(), ensure_ascii=False, indent=1))
        return
    print(json.dumps(live_probe(args.arm), ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
