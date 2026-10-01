"""E6 放行驱动：对剩余被阻断材料登记人工 gap-review 后发布（隔离库）。

仅处理 e6-holdout-build.json 中最新 build 仍被发布门阻断的 4 份材料：
- 证据页与缺口页不相交的 → PAGE 级 gap-review（schema human-gap-review-1）；
- industry-006 的 glp1 证据与页 6 图片缺口同页 → region schema（human-gap-review-2），
  引文取该页 kept 单元的实际保留文本，几何校验单元 bbox 与该页图像不相交。

reviewer=xyl（与复核包签认一致）。不触碰生产库；只写隔离库 e6_holdout_corpus。
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
TARGET_DB = "e6_holdout_corpus"
RESULT = HERE / "e6-holdout-build.json"

sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

import dotenv  # noqa: E402

dotenv.load_dotenv(ROOT / ".env")
os.environ["CORPUS_TARGET_DB"] = TARGET_DB
os.environ.pop("PGOPTIONS", None)

import psycopg  # noqa: E402
from psycopg.conninfo import conninfo_to_dict, make_conninfo  # noqa: E402

from plugins.corpus.preparation.contract import canonical_fingerprint  # noqa: E402
from plugins.corpus.preparation.engine import (  # noqa: E402
    DEFAULT_LEASE,
    check_build_publishable,
    publish_build,
)
from plugins.corpus.preparation.gap_review import (  # noqa: E402
    ATTESTATION,
    GapReview,
    REGION_SCHEMA_REV,
    SCHEMA_REV,
)
from plugins.corpus.preparation.repository_pg import PgStore  # noqa: E402
from plugins.corpus.service import dsn  # noqa: E402

REVIEWER = "xyl"

# 各材料被阻断目标的证据页（页号；与缺口页不相交则 PAGE 级即可）。
# industry-006 的 glp1 证据在 page 6（= 图片缺口页），用 region schema。
EVIDENCE_PAGES = {
    "holdout-industry-006": ["page:1", "page:3", "page:4", "page:5", "page:6", "page:15"],
    "holdout-macro-008": ["page:1"],
    "holdout-macro-009": ["page:1", "page:7", "page:8", "page:10"],
    "holdout-macro-012": ["page:1", "page:2", "page:3", "page:6", "page:10"],
}

# industry-006 region 证明：glp1 引文（取 kept 单元实际保留文本，精确匹配 raw_text）。
GLP1_QUOTE = (
    "2026H1，两款GLP-1减重降糖大单品替尔泊肽、司美格鲁肽全球销售额合计超\n"
    "450 亿美元，分别登顶全球药品销售额第一名/第二名。"
)

# region 页：glp1 证据页（页 6）。
REGION_TARGETS = {"holdout-industry-006": {"page:6": [GLP1_QUOTE]}}


def target_dsn() -> str:
    base = conninfo_to_dict(dsn())
    return make_conninfo(**{**base, "dbname": TARGET_DB})


def main() -> int:
    build_data = json.loads(RESULT.read_text(encoding="utf-8"))
    blocked = [
        s for s in build_data["sources"] if s.get("outcome") == "blocked_by_publish_gate"
    ]
    store = PgStore(target_dsn(), sandbox_db=TARGET_DB)
    results = []
    for src in blocked:
        sample_id = src["sample_id"]
        bid = src["build_id"]
        build = store.get_build(bid)
        if build is None:
            results.append({"sample_id": sample_id, "outcome": "build_missing"})
            continue
        gaps = [
            g for g in src["quality_report"]["gap_regions"]
            if "image_region_small" not in g
        ]
        rationale = {
            g: _gap_rationale(sample_id, g) for g in gaps
        }
        kwargs = dict(
            schema_rev=SCHEMA_REV,
            policy_rev="gap-policy-3",
            source_id=build.source_id,
            build_id=bid,
            build_fingerprint=canonical_fingerprint(asdict(build)),
            reviewer=REVIEWER,
            reviewed_at=datetime.now().astimezone().isoformat(),
            evidence_scope_ref="e6-human-gap-review-packet.json::blocked_targets",
            required_locators=tuple(EVIDENCE_PAGES[sample_id]),
            scope_rationale=(
                f"所需证据位于 e6-human-gap-review-packet.json 之 blocked_targets；"
                f"证据页 {EVIDENCE_PAGES[sample_id]} 与缺口逐页比对，详见各 gap 理由。"
            ),
            attestation=ATTESTATION,
            gaps=tuple(sorted(rationale.items())),
        )
        if sample_id in REGION_TARGETS:
            kwargs["schema_rev"] = REGION_SCHEMA_REV
            kwargs["region_source_path"] = str(
                HERE / "e6-holdout-archive" / src["source_id"][:2] / f"{src['source_id']}.pdf"
            )
            kwargs["region_targets"] = tuple(
                (p, tuple(q)) for p, q in REGION_TARGETS[sample_id].items()
            )
        review = GapReview(**kwargs)
        try:
            check_build_publishable(store, bid)
            results.append({"sample_id": sample_id, "outcome": "already_publishable"})
            continue
        except Exception:  # noqa: BLE001
            pass
        try:
            store.put_gap_review(review)
            pub = publish_build(
                store, bid, activated_at=datetime.now(UTC), owner_id="e6-holdout-publisher"
            )
            results.append({
                "sample_id": sample_id,
                "outcome": "published",
                "review_id": review.review_id,
                "generation": pub.generation,
            })
        except Exception as exc:  # noqa: BLE001
            results.append({"sample_id": sample_id, "outcome": "failed", "error": f"{type(exc).__name__}: {exc}"})
        print(json.dumps(results[-1], ensure_ascii=False))
    print("SUMMARY", json.dumps(results, ensure_ascii=False, indent=1))
    return 0 if all(r.get("outcome") == "published" for r in results) else 1


def _gap_rationale(sample_id: str, gap_key: str) -> str:
    """逐缺口理由（源页复核结论，与 e6-human-gap-review-packet.md 裁决一致）。"""
    if gap_key.startswith("issue:image_region_unreadable"):
        if sample_id == "holdout-industry-006":
            return (
                "page:6 图像区为图7（CRDMO/CDMO 在手订单情况，占页 32%）；glp1 证据单元 "
                "unit:0188 bbox(35.4,529.9)-(389.7,633.0) 与该页全部图像不相交（region 几何已证），"
                "cxo-h1/wuqi/medamt/cxotable 证据页均非 6。缺口不覆盖目标证据。"
            )
        if sample_id == "holdout-macro-008":
            return (
                "page:11 图像区为图表34/35（占页 26%）；全部 5 项目标证据均在 page:1，"
                "与缺口页不相交，不影响所需证据。"
            )
        if sample_id == "holdout-macro-009":
            return (
                "page:9 图像区占页 50%（纯图表页）；目标证据在 page:1/7/8/10，"
                "与缺口页不相交，不影响所需证据。"
            )
    if gap_key.startswith("issue:table_lines_without_extraction"):
        return (
            f"{gap_key} 对应页为真实表格（图11 会议梳理）；table1 证据在 page:10，"
            "其余目标证据在 page:1/2/3/6，均与缺口页不相交，不影响所需证据。"
        )
    return "源页复核：缺口不覆盖目标证据页，不影响所需证据。"


if __name__ == "__main__":
    raise SystemExit(main())
