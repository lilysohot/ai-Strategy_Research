"""Apply the NT-I43 polarity-seam erratum signoff (111 号, zero model calls).

Reads the draft instrument and its signoff markdown, refuses anything that is
not properly signed, then materialises the effective record next to the draft.

Rules enforced:
- signoff md must carry non-empty reviewer / adjudicator / signed_on lines;
- draft instrument hash must match the value recorded in MANIFEST.json;
- the effective file is never overwritten (re-run is a no-op error).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
DRAFT = DIR / "i43-polarity-seam-erratum.proposed.json"
SIGNOFF = DIR / "i43-polarity-seam-erratum-signoff.md"
MANIFEST = DIR / "MANIFEST.json"
EFFECTIVE = DIR / "i43-polarity-seam-erratum.json"


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def extract_signoff(md_text: str) -> dict[str, str]:
    """Parse the fenced signature block line-by-line.

    A field only counts when the value sits on the SAME line after the colon;
    empty values (including bare ``` fences) must refuse — fail-closed, never
    pre-fill signature fields (109 号 P4 预填教训).
    """
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
    recorded = manifest["files"]["i43-polarity-seam-erratum.proposed.json"]["sha256"]
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
    effective["model_requests"] = 0
    effective["production_database_access"] = 0

    EFFECTIVE.write_text(
        json.dumps(effective, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"OK: wrote {EFFECTIVE.name} (signed by {fields['reviewer']} on {fields['signed_on']})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
