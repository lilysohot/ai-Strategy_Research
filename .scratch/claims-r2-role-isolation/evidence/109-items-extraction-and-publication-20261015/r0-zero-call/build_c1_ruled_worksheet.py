"""按 U 的裁定把 92 号 29 条的处置落回工作表（器件原意位置），并出定稿记录。

U 于 2026-10-15 的裁定（原话）：
    「序号2，有相似的词，但是含义主体不同。8是 18是、25是。24/9/17/20 都不是」

落位：
* 判 covered 的 3 条（#8/#18/#25）写 `disposition=covered_by_candidate` + `covered_by_candidate_id`；
* 其余写 `disposition=no_candidate`。其中 U 明确点到的 12 条（#2 及 24/9/17/20 等）为**显式裁定**；
  U 未指名的 7 条按机械初判（也即建议档）记为 no_candidate，并在记录里标 `confirmed_by_omission`，
  以便复核时一眼看到哪些是"没被点名"而不是"被点名否掉"。
* 工作表只填两个既有字段，不新增 schema（`adjudication_fields_required_by_contract` 不变）。

零模型调用；旧版工作表字节保留、不改。

Usage:
    python build_c1_ruled_worksheet.py [--no-write] [--force]
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
REPO_ROOT = ROOT.parents[1]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import write_once  # noqa: E402

CREATED_ON = "2026-10-15"

SCOREABLE_COPY = (
    HERE / "items-reextract-adjudication-r3-blank/candidate-adjudications.worksheet.json"
)
AUTHORED_SET = HERE / "items-reextract-adjudication-r3/candidate-adjudications.worksheet.json"
REVIEW_LISTING = HERE / "p4-c1-review-listing.json"
OUT_DIR = HERE / "items-reextract-adjudication-r3-c1ruled"
OUT_WORKSHEET = OUT_DIR / "candidate-adjudications.worksheet.json"
OUT_RECORD = HERE / "p4-c1-disposition-final.json"

U_RULING_VERBATIM = "序号2，有相似的词，但是含义主体不同。8是 18是、25是。24/9/17/20 都不是"

# U 明确裁决的序号 → 方向。未列出的序号按机械初判（= 建议记缺口）落档，并标 confirmed_by_omission。
EXPLICIT_RULINGS: dict[int, str] = {
    2: "no_candidate",
    8: "covered_by_candidate",
    18: "covered_by_candidate",
    25: "covered_by_candidate",
    24: "no_candidate",
    9: "no_candidate",
    17: "no_candidate",
    20: "no_candidate",
}
U_REASON = {2: "有相似的词，但是含义主体不同"}
# 承载候选由复核清单给出（同一条池内句可承载多条 C1 内容）
CARRIERS = {8: "itm_8de34fd51247bddf", 18: "itm_8de34fd51247bddf", 25: "itm_8c4a2ad0e2114d84"}


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def build() -> tuple[dict[str, Any], dict[str, Any]]:
    worksheet = json.loads(SCOREABLE_COPY.read_text(encoding="utf-8"))
    listing = json.loads(REVIEW_LISTING.read_text(encoding="utf-8"))
    checklist = worksheet["c1_pending_coverage"]
    if len(checklist) != 29:
        raise SystemExit(f"C1 count drift: {len(checklist)}")
    if any(entry["disposition"] is not None for entry in checklist):
        raise SystemExit("工作表 checklist 已被填过：不得覆盖，须另立修订版")

    rows = {row["serial"]: row for row in listing["rows"]}
    by_c1 = {row["c1_candidate_id"]: row for row in listing["rows"]}
    if set(rows) != set(range(1, 30)):
        raise SystemExit("复核清单序号不是 1..29")

    dispositions: list[dict[str, Any]] = []
    for entry in checklist:
        row = by_c1[entry["c1_candidate_id"]]
        serial = row["serial"]
        if serial in EXPLICIT_RULINGS:
            disposition = EXPLICIT_RULINGS[serial]
            provenance = "explicit_u_ruling"
            reason = U_REASON.get(serial)
        else:
            disposition = row["machine_disposition_v1"]
            provenance = "confirmed_by_omission"
            reason = None
        carrier = CARRIERS.get(serial) if disposition == "covered_by_candidate" else None
        entry["disposition"] = disposition
        entry["covered_by_candidate_id"] = carrier
        dispositions.append(
            {
                "serial": serial,
                "c1_candidate_id": entry["c1_candidate_id"],
                "claim_text": entry["claim_text"],
                "role_external_reason": entry["role_external_reason"],
                "machine_similarity": row["closest_pool_candidates"][0]["similarity"],
                "machine_disposition_v1": row["machine_disposition_v1"],
                "disposition": disposition,
                "covered_by_candidate_id": carrier,
                "provenance": provenance,
                "u_reason": reason,
            }
        )

    unresolved = [row["serial"] for row in dispositions if row["disposition"] is None]
    if unresolved:
        raise SystemExit(f"仍有未落档条目：{unresolved}")

    covered = [row for row in dispositions if row["disposition"] == "covered_by_candidate"]
    uncovered = [row for row in dispositions if row["disposition"] == "no_candidate"]
    flips = [row for row in dispositions if row["machine_disposition_v1"] != row["disposition"]]

    record = {
        "schema_version": "items-c1-disposition-final-1",
        "id": "109-p4-c1-disposition-final",
        "created_on": CREATED_ON,
        "model_calls": 0,
        "production_pg_writes": 0,
        "status": "ruled_by_u_recorded",
        "title": "92 号 29 条 pending_coverage 的最终处置（U 具名）",
        "u_ruling_verbatim": U_RULING_VERBATIM,
        "ruled_by": "U（xyl）",
        "ruled_on": CREATED_ON,
        "ruling_scope": "只重裁此前被 assistant 机械判为 no_candidate 的 15 条；其余 14 条机械判 covered 未获异议，维持",
        "basis": {
            "worksheet_before": {
                "path": str(SCOREABLE_COPY.relative_to(ROOT)),
                "sha256": sha256(SCOREABLE_COPY),
            },
            "worksheet_after": {
                "path": str(OUT_WORKSHEET.relative_to(ROOT)),
                "sha256": None,  # 写出后回填
            },
            "u_authored_set_unchanged": {
                "path": str(AUTHORED_SET.relative_to(ROOT)),
                "sha256": sha256(AUTHORED_SET),
                "note": "U 亲填原件字节未动；本修订版在其可出分副本上仅补 29 个 disposition 字段",
            },
            "review_listing": {
                "path": str(REVIEW_LISTING.relative_to(ROOT)),
                "sha256": sha256(REVIEW_LISTING),
            },
        },
        "summary": {
            "total": len(dispositions),
            "covered_by_candidate": len(covered),
            "no_candidate": len(uncovered),
            "re_ruled": len(EXPLICIT_RULINGS) + 7,
            "flipped_from_machine": len(flips),
            "flipped_serials": [row["serial"] for row in flips],
            "explicit_u_rulings": len(EXPLICIT_RULINGS),
            "confirmed_by_omission": len(dispositions) - len(EXPLICIT_RULINGS),
        },
        "assistant_correction": {
            "item": "序号 2",
            "my_earlier_claim": "曾把 #2『观察仓止损条件为下季OCF/扣非<0.5』与池内『下季 OCF 盖不住扣非的一半（OCF/扣非<0.5）』判为同一断言",
            "u_finding": "有相似的词，但是含义主体不同",
            "why_i_was_wrong": "两者共享数值表达式，但主体不同：池内句陈述财务指标事实，C1 句陈述观察仓的止损条件 ⇒ 字面重合掩盖了主体差异",
            "consequence": "该条维持 no_candidate（跨角色仍未被覆盖），并列入发布件缺口；机械/字面法在此类『同词不同主体』上系统性失效，这正是人判不可替代的证据",
        },
        "dispositions": dispositions,
        "worksheet_delta": {
            "fields_written": [
                "c1_pending_coverage[].disposition",
                "c1_pending_coverage[].covered_by_candidate_id",
            ],
            "schema_change": "无——未新增任何字段",
            "adjudications_untouched": "199 行 candidate 裁定与 8 行 matched_gold_id 置空（前批已登记）逐字节不变",
        },
        "untouched": [
            "U 亲填候选集（2e574b6e…）字节未动",
            "可出分副本（02e5dcfb…）字节未动（本修订版另存新目录）",
            "92 号登记件、预注册 v1/v2、门 v3、契约 v4.3、83–108 号产物：字节全未动",
        ],
    }
    return worksheet, record


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--no-write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args(argv)
    worksheet, record = build()
    if args.no_write:
        print(json.dumps(record["summary"], ensure_ascii=False, indent=2))
        return 0
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    write_once(
        OUT_WORKSHEET,
        json.dumps(worksheet, ensure_ascii=False, indent=2) + "\n",
        reason="29 条处置定稿工作表",
        allow_overwrite=args.force,
    )
    record["basis"]["worksheet_after"]["sha256"] = sha256(OUT_WORKSHEET)
    write_once(
        OUT_RECORD,
        json.dumps(record, ensure_ascii=False, indent=2) + "\n",
        reason="29 条处置定稿记录",
        allow_overwrite=args.force,
    )
    print(f"wrote {OUT_WORKSHEET.relative_to(ROOT)}")
    print(f"wrote {OUT_RECORD.name}")
    print(json.dumps(record["summary"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
