"""统一 P4 内所有路径字段为『仓库根相对』，再按纪律出 r29 修订。"""

from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent")
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
GEN = BASE / "audits/20260918-i32-remaining-inventory/generate_p2_p3_p4.py"

REPS = [
    ('"path": "query-gold-frozen.jsonl", "sha256": digest(GOLD)',
     '"path": str(GOLD.relative_to(ROOT)), "sha256": digest(GOLD)'),
    ('"path": "i3-2/evidence-targets-approved.json",',
     '"path": str(PROJECTION.relative_to(ROOT)),'),
    ('"decisions": {"path": "i3-2/evidence-targets-decisions.json", "sha256": digest(DECISIONS)}',
     '"decisions": {"path": str(DECISIONS.relative_to(ROOT)), "sha256": digest(DECISIONS)}'),
    ('"path": "source-gold-frozen.jsonl",',
     '"path": str(SOURCE_GOLD.relative_to(ROOT)),'),
    ('"index": {"path": "baseline-bindings.json", "sha256": digest(BASELINE)}',
     '"index": {"path": str(BASELINE.relative_to(ROOT)), "sha256": digest(BASELINE)}'),
    ('"case_level": {"path": "i0a4-candidates-v3-20260915.json", "sha256": digest(V3)}',
     '"case_level": {"path": str(V3.relative_to(ROOT)), "sha256": digest(V3)}'),
    ('"reconciliation": "audits/20260918-i32-remaining-inventory/p3/baseline-mapping-reconciliation.json",',
     '"reconciliation": str((HERE / "p3/baseline-mapping-reconciliation.json").relative_to(ROOT)),'),
]


def main() -> int:
    text = GEN.read_text(encoding="utf-8")
    # 补常量（若缺）
    if "SOURCE_GOLD = " not in text:
        text = text.replace(
            'GOLD = BASE / "query-gold-frozen.jsonl"',
            'GOLD = BASE / "query-gold-frozen.jsonl"\n'
            'SOURCE_GOLD = BASE / "source-gold-frozen.jsonl"\n'
            'PROJECTION = BASE / "i3-2/evidence-targets-approved.json"\n'
            'DECISIONS = BASE / "i3-2/evidence-targets-decisions.json"',
            1,
        )
    for old, new in REPS:
        if old not in text:
            print("MISS:", old[:70])
            continue
        text = text.replace(old, new, 1)
    GEN.write_text(text, encoding="utf-8")
    import ast

    ast.parse(text)
    print("P4 路径字段统一为仓库根相对")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
