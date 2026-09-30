"""E2 · 把留出集 12 篇源页证据目标合并进 samples.jsonl。

零模型、只读。读取 e2_holdout_targets.json 与现有 samples.jsonl：
- 保留 dev 条目不变；
- 对每个 holdout 条目，按其 doc_sha256_8 匹配 build 好的目标，
  把 status 从 needs_source_page_review 置为 source_page_verified，
  填充 targets、question、required_dependencies、score_evidence 等字段与被核对的源页 provenance。
产物：覆盖 samples.jsonl（本目录）
"""

from __future__ import annotations

import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SAMPLES = HERE / "samples.jsonl"
TARGETS = HERE / "e2_holdout_targets.json"

STATUS_DONE = "source_page_verified"
REVIEWED_AT = "2026-09-30"
REVIEWER = "agent-e2-source-page"


def main() -> None:
    built = {p["doc_sha256_8"]: p for p in json.loads(TARGETS.read_text(encoding="utf-8"))}

    with SAMPLES.open(encoding="utf-8") as f:
        samples = [json.loads(line) for line in f if line.strip()]

    updated = 0
    for s in samples:
        if s["split"] != "holdout":
            continue
        sha8 = s.get("doc_identity", "")[:8]
        p = built.get(sha8)
        if p is None:
            raise SystemExit(f"holdout {s['sample_id']} doc_identity {sha8} 未在 e2_holdout_targets.json 找到")
        if p["sample_id"] != s["sample_id"]:
            raise SystemExit(f"sample_id 不一致: json={p['sample_id']} vs samples={s['sample_id']}")
        n = len(p["targets"])
        s["status"] = STATUS_DONE
        s["targets"] = p["targets"]
        # question/required_dependencies 取自 targets；以第一条 required 为主 question
        s["question"] = next(
            (t["question"] for t in p["targets"] if t["evidence_role"] == "required"), None
        )
        s["required_dependencies"] = list(
            {d for t in p["targets"] for d in t.get("required_dependencies", [])}
        )
        s["evidence_roles"] = {"required": 0, "supplementary": 0}
        for t in p["targets"]:
            s["evidence_roles"][t["evidence_role"]] = s["evidence_roles"].get(t["evidence_role"], 0) + 1
        s["target_count"] = n
        s["source_page_review"] = {
            "method": "pypdf逐页抽取，逐字引文与源页折叠空白后核对",
            "reviewer": REVIEWER,
            "reviewed_at": REVIEWED_AT,
        }
        s["provenance"] = "E2 人工挑选（e2-inventory.json）+ 分三个子代理逐篇源页建目标，2026-09-30 合并"
        updated += 1

    with SAMPLES.open("w", encoding="utf-8") as f:
        for s in samples:
            f.write(json.dumps(s, ensure_ascii=False) + "\n")

    holdout = [s for s in samples if s["split"] == "holdout"]
    dev = sum(1 for s in samples if s["split"] == "dev")
    print(f"samples={len(samples)} dev={dev} holdout={len(holdout)} updated={updated}")
    print("per-paper target counts:")
    for s in holdout:
        print(f"  {s['sample_id']}({s['doc_identity'][:8]}): targets={s['target_count']} "
              f"roles={s['evidence_roles']} status={s['status']}")


if __name__ == "__main__":
    main()