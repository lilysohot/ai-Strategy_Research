"""Inspect configured model identities without printing credentials or making requests."""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from dotenv import dotenv_values

from plugins.corpus.structured.config import load_extraction_config


def main() -> None:
    repo = Path(__file__).resolve().parents[4]
    dotenv_path = repo / ".env"
    config = load_extraction_config(dotenv_path=dotenv_path)
    profile = config.profile
    values = dotenv_values(dotenv_path, interpolate=False) if dotenv_path.is_file() else {}
    keys = ("OPENAI_PROVIDER", "OPENAI_MODEL", "OPENAI_BASE_URL", "OPENAI_API_KEY")
    main_values = {key: os.environ.get(key, values.get(key) or "") for key in keys}
    model = main_values["OPENAI_MODEL"]
    safe_model = model if re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,199}", model) else None
    print(
        json.dumps(
            {
                "network_requests": 0,
                "dotenv_exists": dotenv_path.is_file(),
                "extraction": {
                    "configured": config.configured,
                    "missing_fields": config.missing_fields,
                    "reason": config.reason,
                    "provider": profile.provider if profile else None,
                    "model": profile.model if profile else None,
                    "fingerprint": profile.fingerprint if profile else None,
                },
                "main": {
                    "model": safe_model,
                    "fields_present": {
                        key: bool(value.strip()) for key, value in main_values.items()
                    },
                },
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
