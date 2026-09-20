"""I3-1 dev lane 轮次的取样前强制核对（第 ④ 条）——扩展版（**新增**，旧 r32 版逐字节不动）。

与 r32 版（`audits/20260919-i3-1-e2e/preflight_scope_check.py`，sha256 9fb5ea01…）的关系：
本文件是同一判据的**加严扩展**，唯一新增能力是 `--dev-lane`（U 2026-09-20 裁决）；
不给 `--dev-lane` 时语义与 r32 版一致（据测试锁定），故可用于 fail-closed 反例对照。

核对五个权威源（每个都记录路径 + sha256，保证可审计）：
1. `i0a2-adjudicated-20260915.json`：73 条终态（`decision` / `material_type`）+ `dev_selection_approved`；
2. `guards/i3.json`：`forbidden_roots`（留出件，不可用作开发样本）；
3. `dev-manifest.json`：**非权威**（`dev_selection_candidates` 是登记期旧文案，只作交叉参考）；
4. 支持格式集：PDF/DOCX/MD（架构 §12.1 要求每种声称支持的格式有真实样本）；
5. `admission-policy-dev.json`（**仅当显式 `--dev-lane` 传入**）：dev lane 逐源清单。

判定规则（fail-closed）：
- 默认：只有「在 `dev_selection_approved` 内 ∧ 裁定 `admitted` ∧ `material_type=research_report`
  ∧ 非留出」才算合规样本；其余一律 `FAIL`。
- 给 `--dev-lane` 时新增 `DEV_LANE_OK`：来源必须在 dev lane 清单内、其 `i0a2` 终态与清单声明
  一致、`material_type` 与清单声明**如实**一致（不得伪写研报）、`source_id` 为完整 sha256、
  格式受支持；且清单必须显式 `scope=dev` + `production_in_scope_unchanged=true`。
  **dev lane 不放宽任何其他来源**——不在清单里的来源判定与默认完全一致。
- 额外区分两类越权：**裁定冲突**（用了被排除的材料）与**范围偏离**（用了 admitted 但不在批准开发集内的材料）。

用法::

    uv run python preflight_scope_check.py --manifest <manifest.json> [--label 说明] [--out <path>]
    uv run python preflight_scope_check.py --manifest <manifest.json> --dev-lane <admission-policy-dev.json>
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
    parser.add_argument(
        "--dev-lane",
        default=None,
        help="dev lane 清单（admission-policy-dev.json）；不给则严格按默认口径判（fail-closed）",
    )
    parser.add_argument("--out", default=None, help="报告输出路径（默认本目录 preflight-scope-check.json）")
    args = parser.parse_args()

    adjudicated = load(ADJUDICATED)
    guard = load(GUARD_I3)
    dev_manifest = load(DEV_MANIFEST)
    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path
    manifest = load(manifest_path)
    out_path = Path(args.out) if args.out else OUT
    if not out_path.is_absolute():
        out_path = ROOT / out_path

    dev_lane: dict | None = None
    dev_lane_path: Path | None = None
    dev_lane_by_path: dict[str, dict] = {}
    if args.dev_lane:
        dev_lane_path = Path(args.dev_lane)
        if not dev_lane_path.is_absolute():
            dev_lane_path = ROOT / dev_lane_path
        dev_lane = load(dev_lane_path)
        if dev_lane.get("scope") != "dev" or dev_lane.get("production_in_scope_unchanged") is not True:
            raise SystemExit("dev lane 清单必须显式 scope=dev 且 production_in_scope_unchanged=true")
        for item in (dev_lane.get("dev_lane") or {}).get("sources") or []:
            dev_lane_by_path[normalise(str(item["path"]))] = item
        if not dev_lane_by_path:
            raise SystemExit("dev lane 清单未列出任何来源")

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
        fmt = Path(path).suffix.lower().lstrip(".")
        lane = dev_lane_by_path.get(path)
        if lane is not None:
            # dev lane（U 2026-09-20 裁决）：逐源核对「i0a2 终态 + 材料类型如实 + source_id + 格式」；
            # 缺任一项即 FAIL。授权本身由清单提供，故不判 not_in_approved_dev_selection。
            lane_problems: list[str] = []
            lane_decision = str(lane.get("i0a2_decision") or "")
            if path in holdouts:
                lane_problems.append("holdout_protected")
            if decision != lane_decision:
                lane_problems.append(f"dev_lane_adjudication_mismatch={decision}/{lane_decision}")
            if material != str(lane.get("material_type") or ""):
                lane_problems.append(
                    f"dev_lane_material_mismatch={material or 'missing'}/{lane.get('material_type')}"
                )
            if len(str(lane.get("source_id") or "")) != 64:
                lane_problems.append("dev_lane_source_id_not_sha256")
            if fmt not in SUPPORTED_FORMATS:
                lane_problems.append(f"unsupported_format={fmt}")
            rows.append(
                {
                    "path": path,
                    "format": fmt,
                    "adjudicated_decision": decision,
                    "adjudicated_material_type": record.get("material_type"),
                    "in_approved_dev_selection": path in approved,
                    "approved_scope": (approved.get(path) or {}).get("scope"),
                    "holdout": path in holdouts,
                    "authorized_by": "dev_lane",
                    "dev_lane": {
                        "lane_id": (dev_lane or {}).get("dev_lane", {}).get("lane_id"),
                        "declared_material_type": lane.get("material_type"),
                        "declared_domain": lane.get("domain"),
                        "i0a2_decision": lane_decision,
                    },
                    "verdict": "DEV_LANE_OK" if not lane_problems else "FAIL",
                    "problems": lane_problems,
                }
            )
            continue
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
    dev_lane_rows = [r for r in rows if r["verdict"] == "DEV_LANE_OK"]
    formats_present = sorted({r["format"] for r in rows if r["verdict"] != "FAIL"})
    authoritative: dict[str, object] = {
        "adjudication": {"path": str(ADJUDICATED.relative_to(ROOT)), "sha256": digest(ADJUDICATED),
                         "decision_by": str(adjudicated["sources"][0].get("decision_by"))},
        "guard_forbidden_roots": {"path": str(GUARD_I3.relative_to(ROOT)), "sha256": digest(GUARD_I3),
                                  "count": len(holdouts)},
        "dev_manifest": {"path": str(DEV_MANIFEST.relative_to(ROOT)), "sha256": digest(DEV_MANIFEST),
                         "role": "非权威（dev_selection_candidates 为登记期旧文案，仅交叉参考）"},
    }
    if dev_lane_path is not None:
        authoritative["dev_lane"] = {
            "path": str(dev_lane_path.relative_to(ROOT)),
            "sha256": digest(dev_lane_path),
            "policy_rev": (dev_lane or {}).get("policy_rev"),
            "lane_id": (dev_lane or {}).get("dev_lane", {}).get("lane_id"),
            "approved_by": (dev_lane or {}).get("dev_lane", {}).get("approved_by"),
            "role": "dev-only：只对清单内来源放宽材料类型，不改变生产 in_scope 判定",
        }
    report = {
        "artifact": "preflight-scope-check",
        "generated_at": datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
        "label": args.label,
        "manifest": {"path": str(manifest_path.relative_to(ROOT)), "sha256": digest(manifest_path)},
        "authoritative_sources": authoritative,
        "summary": {
            "sources": len(rows),
            "pass": len(rows) - len(violations),
            "fail": len(violations),
            "adjudication_conflicts": len(adjudication_conflicts),
            "scope_drifts": len(scope_drifts),
            "dev_lane_authorized": len(dev_lane_rows),
            "approved_dev_selection_size": len(approved),
            "formats_covered_by_pass_set": formats_present,
            "verdict": "PASS" if not violations else "FAIL",
        },
        "rows": rows,
        "note": (
            "PASS 仅表示『取样未偏离裁定、未越权』（dev lane 行经 U 2026-09-20 裁决显式授权），"
            "不等于这些材料都能发布——门（blocking 缺口）是另一层，须看 check/publish 结果。"
            "不带 --dev-lane 时，dev lane 来源按默认口径判 FAIL（fail-closed 反例）。"
        ),
    }
    out_path.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"summary": report["summary"], "out": str(out_path.relative_to(ROOT)),
                      "violations": [
        {"path": Path(r["path"]).name[:46], "problems": r["problems"]} for r in violations]},
        ensure_ascii=False, indent=2))
    return 0 if not violations else 1


if __name__ == "__main__":
    sys.exit(main())
