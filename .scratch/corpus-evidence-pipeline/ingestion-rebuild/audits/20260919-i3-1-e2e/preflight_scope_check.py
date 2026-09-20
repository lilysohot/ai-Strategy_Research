"""取样前强制核对（第 ④ 条）：任何 I3-1/E2E 取样前必须跑，用于判定"本次取样是否偏离裁定/越权"。

核对四个权威源（每个都记录路径 + sha256，保证可审计）：
1. `i0a2-adjudicated-20260915.json`：73 条终态（`decision` / `material_type`）+ `dev_selection_approved`；
2. `guards/i3.json`：`forbidden_roots`（留出件，不可用作开发样本）；
3. `dev-manifest.json`：**非权威**（`dev_selection_candidates` 是登记期旧文案，只作交叉参考）；
4. 支持格式集：PDF/DOCX/MD（架构 §12.1 要求每种声称支持的格式有真实样本）。

判定规则（fail-closed）：
- 只有「在 `dev_selection_approved` 内 ∧ 裁定 `admitted` ∧ `material_type=research_report` ∧ 非留出」才算合规样本；
- 其余一律标 `FAIL` 并给出逐条原因（`excluded_from_active` / `internal_committee_report` / `not_in_approved_dev_selection` / `holdout` …）；
- 额外区分两类越权：**裁定冲突**（用了被排除的材料）与**范围偏离**（用了 admitted 但不在批准开发集内的材料）。

用法::

    uv run python preflight_scope_check.py --manifest <manifest.json> [--label 说明]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
ADJUDICATED = BASE / "i0a2-adjudicated-20260915.json"
GUARD_I3 = BASE / "guards/i3.json"
DEV_MANIFEST = BASE / "dev-manifest.json"
OUT = HERE / "preflight-scope-check.json"
SUPPORTED_FORMATS = {"pdf", "docx", "md"}


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def normalise(path: str) -> str:
    return str(Path(path).as_posix())


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", required=True, help="待检查的取样清单（sources[].path）")
    parser.add_argument("--label", default="")
    args = parser.parse_args()

    adjudicated = load(ADJUDICATED)
    guard = load(GUARD_I3)
    dev_manifest = load(DEV_MANIFEST)
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    manifest = load(manifest_path)

    by_path = {normalise(str(r["path"])): r for r in adjudicated["sources"]}
    approved = {normalise(str(x["path"])): x for x in adjudicated["dev_selection_approved"]}
    holdouts = {normalise(p) for p in guard["sources"]["forbidden_roots"] if p}
    candidates = {
        normalise(str(p))
        for group in ("company", "industry", "macro")
        for p in (dev_manifest["dev_selection_candidates"].get(group) or [])
    }

    rows = []
    for entry in manifest["sources"]:
        path = normalise(str(entry["path"]))
        record = by_path.get(path) or {}
        decision = record.get("decision")
        material = str(record.get("material_type") or "")
        problems: list[str] = []
        if not record:
            problems.append("not_in_adjudication")
        if decision != "admitted":
            problems.append(f"adjudication={decision}")
        if material != "research_report":
            problems.append(f"material_type={material or 'missing'}")
        if path in holdouts:
            problems.append("holdout_protected")
        if path not in approved:
            problems.append("not_in_approved_dev_selection")
        if path in candidates and path not in approved:
            problems.append("dev_selection_candidates_only（旧文案，非批准）")
        fmt = Path(path).suffix.lower().lstrip(".")
        if fmt not in SUPPORTED_FORMATS:
            problems.append(f"unsupported_format={fmt}")
        rows.append(
            {
                "path": path,
                "format": fmt,
                "adjudicated_decision": decision,
                "adjudicated_material_type": record.get("material_type"),
                "in_approved_dev_selection": path in approved,
                "approved_scope": (approved.get(path) or {}).get("scope"),
                "holdout": path in holdouts,
                "verdict": "PASS" if not problems else "FAIL",
                "problems": problems,
            }
        )

    violations = [r for r in rows if r["verdict"] == "FAIL"]
    adjudication_conflicts = [r for r in violations if any(p.startswith(("adjudication=", "material_type=",
                                                                        "not_in_adjudication", "holdout"))
                                                      for p in r["problems"])]
    scope_drifts = [r for r in violations if "not_in_approved_dev_selection" in r["problems"]
                    and not any(p.startswith(("adjudication=", "material_type=", "holdout"))
                                for p in r["problems"])]
    formats_present = sorted({r["format"] for r in rows if r["verdict"] == "PASS"})
    report = {
        "artifact": "preflight-scope-check",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "label": args.label,
        "manifest": {"path": str(manifest_path.relative_to(ROOT)), "sha256": digest(manifest_path)},
        "authoritative_sources": {
            "adjudication": {"path": str(ADJUDICATED.relative_to(ROOT)), "sha256": digest(ADJUDICATED),
                             "decision_by": str(adjudicated["sources"][0].get("decision_by"))},
            "guard_forbidden_roots": {"path": str(GUARD_I3.relative_to(ROOT)), "sha256": digest(GUARD_I3),
                                      "count": len(holdouts)},
            "dev_manifest": {"path": str(DEV_MANIFEST.relative_to(ROOT)), "sha256": digest(DEV_MANIFEST),
                             "role": "非权威（dev_selection_candidates 为登记期旧文案，仅交叉参考）"},
        },
        "summary": {
            "sources": len(rows),
            "pass": len(rows) - len(violations),
            "fail": len(violations),
            "adjudication_conflicts": len(adjudication_conflicts),
            "scope_drifts": len(scope_drifts),
            "approved_dev_selection_size": len(approved),
            "formats_covered_by_pass_set": formats_present,
            "verdict": "PASS" if not violations else "FAIL",
        },
        "rows": rows,
        "note": (
            "PASS 仅表示『取样未偏离裁定、未越权』，不等于这些材料都能发布——"
            "门（blocking 缺口）是另一层，须看 check/publish 结果。"
        ),
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": report["summary"], "violations": [
        {"path": Path(r["path"]).name[:46], "problems": r["problems"]} for r in violations]},
        ensure_ascii=False, indent=2))
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
