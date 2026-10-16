"""Materialise the 112 号 budget + frozen-questions authorisation (zero model calls).

Fail-closed: a missing ceiling or a question that is neither adopted nor rewritten
refuses to produce the record; the run must not start without it (99/102 号先例).
"""

from __future__ import annotations

import hashlib
import json
import re
import sys
from pathlib import Path

DIR = Path(__file__).resolve().parent
SOURCE = DIR / "budget-and-questions-authorisation.md"
OUT = DIR / "authorisation-112.json"
MANIFEST = DIR / "MANIFEST.json"


def parse_authorisation(text: str) -> dict:
    ceiling_match = re.search(r"^ceiling_tokens\s*:\s*(\d+)\s*$", text, re.MULTILINE)
    if not ceiling_match:
        raise SystemExit("REFUSE: ceiling_tokens not filled — 未填预算不得起跑")
    ceiling = int(ceiling_match.group(1))

    structural = bool(re.search(r"勾选\s*[:：]\s*√", text))
    questions: list[dict] = []
    for idx, source in enumerate(("f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb",
                                  "48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f"), 1):
        block = text.split(f"**题 {idx}**", 1)[-1].split("**题", 1)[0]
        proposed = re.search(r"拟题\s*[:：]\s*(.+?)\s*$", block, re.MULTILINE)
        adopted = re.search(r"采用\s*[:：]\s*√", block)
        rewritten = re.search(r"改为\s*[:：]\s*([^\s_].*?)\s*$", block, re.MULTILINE)
        if not proposed:
            raise SystemExit(f"REFUSE: 题 {idx} 无拟题")
        if rewritten and rewritten.group(1).strip() and not rewritten.group(1).startswith("___"):
            question = rewritten.group(1).strip()
            origin = "u_rewritten"
        elif adopted:
            question = proposed.group(1).strip()
            origin = "adopted_proposed"
        else:
            raise SystemExit(f"REFUSE: 题 {idx} 未采用也未改写 — 问题必须冻结后执行")
        questions.append({"index": idx, "source_id": source, "question": question, "origin": origin})

    return {
        "ceiling_tokens": ceiling,
        "structural_bounds": {
            "declared": structural,
            "questions": 2,
            "max_turns": 8,
            "concurrency": 1,
        },
        "questions": questions,
    }


def main() -> int:
    if OUT.exists():
        raise SystemExit("REFUSE: authorisation already exists — 永不覆盖重出")
    parsed = parse_authorisation(SOURCE.read_text(encoding="utf-8"))
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    recorded = manifest["files"].get(SOURCE.name, {}).get("sha256")
    actual = hashlib.sha256(SOURCE.read_bytes()).hexdigest()
    if recorded is None:
        raise SystemExit("REFUSE: MANIFEST 未登记本件哈希")
    if recorded != actual:
        raise SystemExit(f"REFUSE: hash drift — MANIFEST {recorded[:12]}… != disk {actual[:12]}…")

    record = {
        "schema": "authorisation-112-v1",
        "record_id": "112-production-read-chain-consumption-authorisation",
        "created_on": "2026-10-15",
        "status": "stated_effective_filled",
        "source_instrument": {"file": SOURCE.name, "sha256": actual},
        "runnable": True,
        "model_requests": 0,
        "production_database_access": 0,
        **parsed,
    }
    OUT.write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(f"OK: {OUT.name} runnable=True ceiling={parsed['ceiling_tokens']}")
    for q in parsed["questions"]:
        print(f"  Q{q['index']} [{q['origin']}] {q['question']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
