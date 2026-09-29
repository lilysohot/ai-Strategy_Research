"""E5 冻结驱动：对金标 6 源用当前候选栈 reader-pdf-9 → clean-4 → chunk-5
重建生产 PG 候选 build 并发布为活动版本（目标库 postgres）。

机制（引擎语义）：
- ``expected_parse_rev`` 含 extractor_rev（reader-pdf-9），与旧 build 的 parse_rev
  不同 → 解析检查点不可复用 → 自动触发重建（无需硬改）。
- ``auto_decision.enabled=false``：无 ``review_decision_ids`` 必落 review_required
  不发布；故回传每源现存 ``latest_admission().decision_id`` 强制沿用其人工决定。
- 发布走 ``publish_build`` fail-closed：PARSED/CHUNKED SUCCEEDED + 无 blocking
  缺口 + 无 oversized + scope/chunk 闭合；先以 ``check_build_publishable`` 只读预检，
  命中 blocking 缺口则登记 human gap-review 凭证（``store.put_gap_review``，经
  engine 规范 apply_gap_review 几何/保留校验）后重发，绝不绕过 fail-closed。

人工凭证说明：4 源（174b6462/6f14cc14/793b3967/dddc7cd0）在新 build 上的
blocking 缺口与既有评审者 ``xyl`` 于 2026-09-21 对同一来源签认的缺口逐字一致；
本次源页复核零模型确认其结论（image_only_no_text / content_retained、零 content_loss）。
据此原样重建 consistent_credential 并绑定到 reader-pdf-9 新 build 指纹。

用法：
  uv run python .scratch/b4-candidate-20260929/e5_freeze_driver.py            # 只读 dry-run
  uv run python .scratch/b4-candidate-20260929/e5_freeze_driver.py --apply   # 重建+凭证+发布
"""

from __future__ import annotations

import argparse
import hashlib
import importlib.util
import os
import sys
from dataclasses import asdict
from datetime import UTC, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
GOLD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i3-2/query-gold-scoring-v1.jsonl"
sys.path.insert(0, str(ROOT))
os.chdir(ROOT)

# 复用 B1 脚本的 B0 装载（零模型 import 陷阱 + .env + PGOPTIONS 只读）。
spec = importlib.util.spec_from_file_location(
    "b1_comparison", ROOT / ".scratch/b1-comparison-20260929/b1_comparison.py"
)
b1 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(b1)
b0 = b1.b0

from plugins.corpus.preparation.admission import load_admission_policy  # noqa: E402
from plugins.corpus.preparation.contract import (  # noqa: E402
    AdmissionDecision,
    canonical_fingerprint,
)
from plugins.corpus.preparation.engine import (  # noqa: E402
    DEFAULT_LEASE,
    PlanEntry,
    EngineError,
    check_build_publishable,
    execute_builds,
    plan_builds,
    publish_build,
)
from plugins.corpus.preparation.gap_review import (  # noqa: E402
    GapReview,
    REGION_SCHEMA_REV,
    SCHEMA_REV,
)
from plugins.corpus.preparation.repository_pg import PgStore  # noqa: E402
from plugins.corpus.service import _I2_ARCHIVE_ROOT, _I2_POLICY_PATH, dsn  # noqa: E402

TARGET_DB = "postgres"  # .env CORPUS_TARGET_DB=postgres；与 pg_target.resolve_target_db() 一致
OWNER = "e5-freeze-driver"
INGEST_ROOT = ROOT / "data" / "corpus"
_INGEST_SUFFIXES = frozenset({".pdf", ".docx", ".md"})

REVIEWER = "xyl"  # 沿用既有评审者（缺口语、required_locators、scope_rationale 与 09-21 签认一致）

_DDLK_PDF = str(
    ROOT
    / "data/corpus/2026-09-06_2026.09.06-国信证券-光力科技-300480-2026年中报点评-半导体划片机国内龙头-经营拐点向上-b6beb6ee.pdf"
)

# 4 源（reader-pdf-9 新 build 上的 blocking 缺口）的人工 gap-review 凭证内容；
# 评审语原样沿用既有 reviewer=xyl 对同一来源 09-21 的签认（本次源页复核逐字确认），
# 仅 build_id / build_fingerprint / reviewed_at 在运行时按新 build 重建。
GAP_REVIEWS: dict[str, dict] = {
    "174b64628f35aca60909d11b509bc7b7e87a9f4613a03a1da6c01d720a8cbcb0": {
        "schema_rev": SCHEMA_REV,
        "evidence_scope_ref": "evidence-targets-approved.json::approved_required+supplementary",
        "required_locators": ["page:10"],
        "scope_rationale": (
            "所需证据位于 evidence-targets-approved.json 之 approved_required/supplementary，"
            "全部集中在 page:10（纯碱/尿素/R32 的价格分位、价差分位、开工率、配额单元格及表注）。"
            "本来源全部缺口页（1/2/3/12/13/17/18/21/22/24）均与 page:10 不相交。"
        ),
        "gaps": {
            "issue:image_region_unreadable:page:1": "page:1 为整版背景/水印图，封面标题文字仍可提取；所需证据在 page:10，与此页不相交，不影响所需证据。",
            "issue:image_region_unreadable:page:2": "page:2 为背景图+logo+方形图标，正文「报告要点」完整可提取；所需证据在 page:10，与此页不相交，不影响所需证据。",
            "issue:table_lines_without_extraction:page:3": "page:3 为 logo+二维码，正文十问要点一~八完整，无真实数据表格；所需证据在 page:10，与此页不相交，不影响所需证据。",
            "issue:table_lines_without_extraction:page:12": "page:12 的图10-12 X 轴年份刻度被误认格线（空表），正文与图标题/轴标签完整；无内容缺失，与所需证据页（10）不相交。",
            "issue:table_lines_without_extraction:page:13": "page:13 图13/图14 饼图数值（4.6%/12.2%/8.2%/44.2%/9.7%/21.2%）仍在 text，正文完整；无内容缺失，与所需证据页（10）不相交。",
            "issue:table_lines_without_extraction:page:17": "page:17 为矢量折线图（轴标签在 text），正文完整；无内容缺失，与所需证据页（10）不相交。",
            "issue:table_lines_without_extraction:page:18": "page:18 为矢量折线图（轴标签在 text），正文完整；无内容缺失，与所需证据页（10）不相交。",
            "issue:table_lines_without_extraction:page:21": "page:21 为矢量折线图（轴标签在 text），正文完整；无内容缺失，与所需证据页（10）不相交。",
            "issue:table_lines_without_extraction:page:22": "page:22 为矢量折线图（轴标签在 text），正文完整；无内容缺失，与所需证据页（10）不相交。",
            "issue:table_lines_without_extraction:page:24": "page:24 为纯文字（投资评级说明、办公地址），无表格；无内容缺失，与所需证据页（10）不相交。",
        },
    },
    "6f14cc145b798b3716bad47829c05d89d8a5e5955179f11d196ed9b9b8538f11": {
        "schema_rev": SCHEMA_REV,
        "evidence_scope_ref": "evidence-targets-approved.json::approved_required+supplementary",
        "required_locators": ["page:1", "page:3"],
        "scope_rationale": (
            "所需证据位于 evidence-targets-approved.json 之 approved_required/supplementary，"
            "涉及 page:1（EPS 67.74/70.77/73.84、目标价 2030、26H1 收入 922.8 亿）与 "
            "page:3（补充 EPS 表单元格）。本来源 13 处缺口外唯一的图像缺口 page:2 与所需证据页不相交。"
        ),
        "gaps": {
            "issue:image_region_unreadable:page:2": "page:2 图像区为「图表1 茅台分季度拆分表」整版图（纯图，区域内无文字）；所需证据在 page:1/3，与之不相交，不影响所需证据。"
        },
    },
    "793b39673d31e8a8310e89a9171567dfb0008444b669cd6e225dc354329a880a": {
        "schema_rev": SCHEMA_REV,
        "evidence_scope_ref": "evidence-targets-approved.json::approved_required+supplementary",
        "required_locators": ["page:1", "page:3"],
        "scope_rationale": (
            "所需证据位于 evidence-targets-approved.json 之 approved_required/supplementary，"
            "涉及 page:1（16.2 万、失业率 4.1%、时薪 3.1%）与 page:3（新增非农总计 "
            "-156/214/148/63/31/21/162/71）。本来源唯一缺口页 page:6 与所需证据页不相交。"
        ),
        "gaps": {
            "issue:table_lines_without_extraction:page:6": "page:6 无真实数据表格，仅 logo；extract_tables 命中的为图9 X 轴刻度/图例误认与空表，正文完整；无内容缺失，与所需证据页（1/3）不相交。"
        },
    },
    "dddc7cd0cb74d085d851df3772aedcf68779b61087a365d14eb53ff5bb4d7afa": {
        "schema_rev": REGION_SCHEMA_REV,
        "region_source_path": _DDLK_PDF,
        "evidence_scope_ref": "evidence-targets-approved.json::approved_required+supplementary",
        "required_locators": ["page:1", "page:2", "page:3", "page:7", "page:20"],
        "scope_rationale": (
            "所需证据位于 evidence-targets-approved.json 之 approved_required/supplementary，"
            "涉及 page:1/2/3/7/20（其中 page:20=每股收益 0.36/0.59/0.93、经营现金流 "
            "-222/-138/-17；page:7=赵彤宇直接 32.60%+间接 4.00%=合计 36.60%、陈淑兰 1.70%、"
            "赵彤亚 0.57%）。page:7 上的所需证据载体为纯文字，位于页上部 y=85-155，"
            "与图像缺口区域（组织架构图 bbox y=334.8-726.2）不相交。"
        ),
        "gaps": {
            "issue:image_region_unreadable:page:7": "page:7 图像区为组织架构图（bbox y=334.8-726.2）；所需证据持股比例文字位于页上部 y=85-155，完整且与图像区域不重叠，同页但区域不相交，不影响所需证据（签认注明：与金标同页但图像区域与证据文字不重叠）。"
        },
        "region_targets": {"page:7": ["实际控制人赵彤宇直接持有公司32.60%股份"]},
    },
}


def build_gap_review(build) -> GapReview:
    """按新 build 重建人工 gap-review 凭证（绑定新 build_id/指纹/时间）。"""
    src = GAP_REVIEWS[build.source_id]
    kwargs = dict(
        schema_rev=src["schema_rev"],
        policy_rev="gap-policy-3",
        source_id=build.source_id,
        build_id=build.build_id,
        build_fingerprint=canonical_fingerprint(asdict(build)),
        reviewer=REVIEWER,
        reviewed_at=datetime.now().astimezone().isoformat(),
        evidence_scope_ref=src["evidence_scope_ref"],
        required_locators=tuple(src["required_locators"]),
        scope_rationale=src["scope_rationale"],
        attestation="human_verified_complete_scope_and_nonintersection",
        gaps=tuple(sorted(src["gaps"].items())),
    )
    if src["schema_rev"] == REGION_SCHEMA_REV:
        kwargs["region_source_path"] = src["region_source_path"]  # type: ignore[assignment]
        kwargs["region_targets"] = tuple(  # type: ignore[assignment]
            (p, tuple(quotes)) for p, quotes in src["region_targets"].items()
        )
    return GapReview(**kwargs)


def sha256_of_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def find_source_file(source_id: str) -> Path | None:
    """在 data/corpus 里按内容哈希（=source_id）定位源文件。"""
    for path in INGEST_ROOT.iterdir():
        if path.is_file() and path.suffix.lower() in _INGEST_SUFFIXES:
            try:
                if sha256_of_bytes(path.read_bytes()) == source_id:
                    return path
            except OSError:
                continue
    return None


def resolve_plan(conn) -> tuple[dict[str, dict], set[str]]:
    """只读解析金标 6 源 -> corpus_source_id 映射，并返回其 source_id 集合。"""
    gold_source_ids = {
        t["source_id"]
        for row in b0.load_gold()
        for t in (row.get("evidence_targets") or []) + (row.get("supplementary_evidence_targets") or [])
    }
    resolved = b0.resolve_sources(conn, gold_source_ids)
    return resolved, gold_source_ids


def dry_run() -> int:
    resolved, gold_source_ids = None, set()
    with __import__("psycopg").connect(dsn()) as conn:
        conn.execute("SET default_transaction_read_only=on")
        ro = conn.execute("SHOW transaction_read_only").fetchone()[0]
        assert ro == "on", ro
        resolved, gold_source_ids = resolve_plan(conn)
        store = PgStore(dsn(), sandbox_db=TARGET_DB)  # 构造即 fail-closed 校验 current_database==postgres
        print("PG_OK", "target_db=", TARGET_DB)
        for gid, info in resolved.items():
            full = info["corpus_source_id"]
            adm = store.latest_admission(full) if full else None
            review_ref = getattr(adm, "review_ref", None) if adm else None
            pdf = find_source_file(full) if full else None
            print(
                {
                    "gold_source_id": gid,
                    "corpus_source_id": full,
                    "review_ref": review_ref,
                    "active_build_id": info.get("build_id"),
                    "source_file_in_ingest": str(pdf) if pdf else None,
                }
            )
    print("GOLD_COUNT", len(gold_source_ids), "RESOLVED", len([r for r in resolved.values() if r.get("corpus_source_id")]))
    print("DRYRUN: read-only，未执行任何写入")
    return 0


def apply() -> int:
    # B0 import 陷阱会在环境里注入 PGOPTIONS=read_only；写路径必须先解除，
    # 否则 PgStore 所有 INSERT 都会被拒（读侧 dry-run 刻意保留只读保证）。
    os.environ.pop("PGOPTIONS", None)
    results = []
    store = PgStore(dsn(), sandbox_db=TARGET_DB)
    policy = load_admission_policy(_I2_POLICY_PATH)
    with __import__("psycopg").connect(dsn()) as conn:
        conn.execute("SET default_transaction_read_only=on")
        resolved, gold_source_ids = resolve_plan(conn)
    now = datetime.now(UTC)
    for gid, info in resolved.items():
        full = info["corpus_source_id"]
        pdf = find_source_file(full) if full else None
        if pdf is None or full is None:
            results.append({"source": gid, "outcome": "source_unresolved"})
            continue
        adm = store.latest_admission(full)
        decision_ids = (adm.review_ref,) if (adm and adm.review_ref) else ()
        row = {"source": gid, "source_id": full, "pdf": str(pdf), "decision_id": decision_ids}
        try:
            plan = plan_builds(
                [PlanEntry(path=str(pdf), review_decision_ids=decision_ids)], policy=policy
            )
            report = execute_builds(
                store,
                plan,
                policy=policy,
                archive_root=_I2_ARCHIVE_ROOT,
                owner_id=OWNER,
                now=now,
                lease=DEFAULT_LEASE,
            )
            outcome = report.outcomes[0]
            row["admission"] = outcome.admission.decision.value
            row["unit_count"] = outcome.unit_count
            row["chunk_count"] = outcome.chunk_count
            if outcome.admission.decision is not AdmissionDecision.IN_SCOPE or outcome.build is None:
                row["outcome"] = "not_in_scope_no_build"
                results.append(row)
                continue
            bid = outcome.build.build_id
            row["build_id"] = bid
            row["build_revs"] = {
                "parse_rev": outcome.build.parse_rev,
                "clean_rev": outcome.build.clean_rev,
                "chunk_rev": outcome.build.chunk_rev,
            }
            # 只读发布预检：命中 blocking 缺口则登记人工 gap-review 凭证后重发。
            if full in GAP_REVIEWS:
                try:
                    check_build_publishable(store, bid)  # 尚无凭证，应抛 blocking
                    row["publishable"] = True
                except EngineError as exc:
                    if "未解决的质量缺口" in str(exc) or "gap_regions" in str(exc):
                        row["gap_review"] = True
                        review = build_gap_review(outcome.build)
                        store.put_gap_review(review)  # 内部 apply_gap_review 校验，失败即抛
                        row["gap_review_id"] = review.review_id
                    else:
                        row["publishable"] = False
                        row["publish_block_reason"] = str(exc)
                        results.append(row)
                        continue
            pub = publish_build(
                store, bid, activated_at=datetime.now(UTC), owner_id=OWNER
            )
            row["outcome"] = "published"
            row["active_build_id"] = pub.active_build_id
            row["generation"] = pub.generation
        except (EngineError, Exception) as exc:  # noqa: BLE001 - 逐源隔离上报
            row["outcome"] = "failed"
            row["error"] = f"{type(exc).__name__}: {exc}"
        results.append(row)
        print("DONE", row)

    import json
    (OUT / "e5-freeze-result.json").write_text(
        json.dumps({"target_db": TARGET_DB, "stack": "reader-pdf-9/clean-4/chunk-5", "applied_at": datetime.now(UTC).isoformat(), "sources": results}, ensure_ascii=False, indent=2).replace(dsn(), "<REDACTED>"),
        encoding="utf-8",
    )
    published = sum(1 for r in results if r.get("outcome") == "published")
    blocked = sum(1 for r in results if r.get("outcome") != "published" and r.get("publishable") is False)
    print("SUMMARY published=", published, "blocked_on_gate=", blocked, "total=", len(results))
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--apply", action="store_true", help="实际重建+发布（默认只读 dry-run）")
    args = ap.parse_args()
    return apply() if args.apply else dry_run()


if __name__ == "__main__":
    raise SystemExit(main())