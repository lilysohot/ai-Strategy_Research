"""Apply the 112 号 production read-chain consumption signoff (zero model calls).

Fail-closed:
- signoff md must carry reviewer / adjudicator / signed_on on the SAME line;
- draft instrument hash must match MANIFEST.json;
- the effective record is never overwritten.

Execution gating is deliberately NOT part of this script: with
`budget.ceiling_tokens` still null the run must not start (99 号/102 号先例).
"""

from __future__ import annotations

import hashlib
import json
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
DRAFT = DIR / "production-read-chain-consumption.proposed.json"
SIGNOFF = DIR / "production-read-chain-consumption-signoff.md"
MANIFEST = DIR / "MANIFEST.json"
EFFECTIVE = DIR / "production-read-chain-consumption.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_signoff(md_text: str) -> dict[str, str]:
    block = md_text.split("## 四、签认", 1)[-1]
    lines = [line.strip() for line in block.splitlines()]
    fields: dict[str, str] = {}
    for key in ("reviewer", "adjudicator", "signed_on"):
        value: str | None = None
        for line in lines:
            if line.startswith(f"{key}:"):
                value = line[len(key) + 1 :].strip().strip("`").strip()
                break
        if not value or value == "```":
            raise SystemExit(f"REFUSE: signoff field '{key}' is empty — 不代填签名栏")
        if ":" in value:
            raise SystemExit(f"REFUSE: signoff field '{key}' looks malformed: {value!r}")
        fields[key] = value
    return fields


def main() -> int:
    if EFFECTIVE.exists():
        raise SystemExit("REFUSE: effective record already exists — 永不覆盖重出")

    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    recorded = manifest["files"][DRAFT.name]["sha256"]
    actual = sha256_file(DRAFT)
    if recorded != actual:
        raise SystemExit(
            f"REFUSE: draft hash drifted — MANIFEST {recorded[:12]}… != disk {actual[:12]}…"
        )

    fields = extract_signoff(SIGNOFF.read_text(encoding="utf-8"))
    instrument = json.loads(DRAFT.read_text(encoding="utf-8"))

    effective = dict(instrument)
    effective["status"] = "decided_signed"
    effective["reviewer"] = fields["reviewer"]
    effective["adjudicator"] = fields["adjudicator"]
    effective["signed_on"] = fields["signed_on"]
    effective["signed_instrument"] = {
        "file": SIGNOFF.name,
        "sha256": sha256_file(SIGNOFF),
        "draft_sha256": actual,
    }
    ceiling = instrument.get("budget", {}).get("ceiling_tokens")
    effective["runnable"] = ceiling is not None
    effective["runnable_note"] = (
        "预算 ceiling 已填，可执行" if ceiling is not None
        else "预算 ceiling 与问题文本未填 ⇒ 不可起跑（99 号/102 号先例）"
    )
    effective["model_requests"] = 0
    effective["production_database_access"] = 0

    EFFECTIVE.write_text(
        json.dumps(effective, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"OK: wrote {EFFECTIVE.name} (signed by {fields['reviewer']} on {fields['signed_on']})")
    print(f"runnable={effective['runnable']} — {effective['runnable_note']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
