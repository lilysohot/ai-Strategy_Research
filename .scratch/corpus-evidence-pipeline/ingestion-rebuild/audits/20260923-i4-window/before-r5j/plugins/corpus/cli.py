"""I2-4 语料 CLI 六职责（架构 §9）：plan / build / check / publish / status / rebuild-plan。

纪律：

- **CLI 不复制规则**：清单校验/编排/发布门一律调用
  :mod:`plugins.corpus.preparation.engine`（``plan_builds`` / ``execute_builds`` /
  ``check_build_publishable`` / ``publish_build``）与 ``Store``（``PgStore``）；
  本模块只做参数解析、结果呈现与退出码映射，不内联任何判定规则。
- **精确目标 fail-closed**：``--dsn`` 默认取 ``CORPUS_I2_DSN``（不隐式连生产库），
  ``PgStore``/读侧 Adapter 自带隔离库校验与 apodex 生产实例反证。
- **阶段守卫**：所有子命令先做目标校验；无 ``--force`` 之类旁路，无越权参数。
- **操作者与 generation**：``publish`` 必须给 ``--operator``，操作者与该次
  generation 记入 PUBLISHED job 的 checkpoint（``publish-record-1``）。
- **缺口可见（架构 §9 + RM-FC-0）**：``check``（含被拒时）与 ``status`` 都输出结构化
  ``gaps``（码/坐标/状态/分级/依据/恢复路径）、``gap_summary`` 与 ``recovery``；
  ``check`` 与 ``plan`` 的缺口判定共用 ``engine.gap_records_of``/``gaps.*``
  同一实现（不得各算一套）。被拒的 ``error`` 文案仍保留给人工阅读。
- **plan 预检**：``plan`` 额外做**只读可发布性预检**（跑读取器 + 缺口记账，同一分级
  口径；无 PG 写入、无模型）。预检不带 scope（无 PG，取不到准入决定），因此只可能比
  ``check`` **更严**（有 scope 时部分缺口会被判为「范围外」而放行），不会更宽。

退出码（**同一前置条件跨命令同码**，RM-I28-10）：

| 码 | 含义 | 触发示例 |
| -- | ---- | -------- |
| 0 | 成功 | 门通过、发布完成 |
| 2 | 输入/清单/参数非法 | manifest 缺字段、文件不存在、缺必填参数 |
| 3 | 目标或守卫拒绝 | 未声明 DSN、非隔离目标、legacy 降级请求 |
| 4 | 门未过（对象存在但不可发布/校验失败） | 质量缺口、阶段未成功、准入非 in_scope |
| 5 | **目标不存在/无可用版本或未决** | `check`/`status` 的 build 不存在、未发布 |

``argparse`` 的缺参错误由 :func:`main` 捕获 ``SystemExit`` 后归一为 ``2``（程序化调用者
也拿到返回码而非异常）。

用法::

    uv run python -m plugins.corpus.cli plan --manifest plan.json
    uv run python -m plugins.corpus.cli build --manifest plan.json --archive-root data/corpus-archive
    uv run python -m plugins.corpus.cli check --build <build_id>
    uv run python -m plugins.corpus.cli publish --build <build_id> --operator alice
    uv run python -m plugins.corpus.cli status --build <build_id>
    uv run python -m plugins.corpus.cli rebuild-plan --build <build_id>
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from plugins.corpus.preparation import read_pg
from plugins.corpus.preparation.admission import AdmissionPolicy, load_admission_policy
from plugins.corpus.preparation.clean import clean_reader_result
from plugins.corpus.preparation.contract import Build, JobStage, ResearchDomain
from plugins.corpus.preparation.engine import (
    DEFAULT_LEASE,
    EngineError,
    PlanEntry,
    PlannedSource,
    check_build_publishable,
    current_revs,
    execute_builds,
    expected_parse_rev,
    gap_records_of,
    plan_builds,
    publish_build,
)
from plugins.corpus.preparation.gaps import (
    GAP_POLICY_REV,
    blocking_gaps,
    evaluate_against_scope,
    gap_records,
    gap_summary,
    recovery_paths,
)
from plugins.corpus.preparation.pg_target import resolve_target_db
from plugins.corpus.preparation.readers import read_document
from plugins.corpus.preparation.repository import Store, StoreError
from plugins.corpus.preparation.repository_pg import PgStore

EXIT_OK = 0
EXIT_INPUT = 2
EXIT_TARGET = 3
EXIT_GATE = 4
EXIT_UNAVAILABLE = 5

_SANDBOX_DB = resolve_target_db()
_DEFAULT_POLICY = (
    Path(__file__).resolve().parents[2]
    / ".scratch"
    / "corpus-evidence-pipeline"
    / "ingestion-rebuild"
    / "admission-policy.json"
)
# dev lane 显式开关（U 2026-09-20 裁决）：未设置时 dev 政策一律拒绝装载。
_DEV_LANE_ENV = "CORPUS_DEV_LANE"
_STAGES = (
    JobStage.REGISTERED,
    JobStage.ADMISSION_DECIDED,
    JobStage.PARSED,
    JobStage.CLEANED,
    JobStage.CHUNKED,
    JobStage.STAGED,
    JobStage.INDEXED,
    JobStage.VERIFIED,
    JobStage.PUBLISHED,
)


def _emit(payload: dict[str, object]) -> None:
    print(json.dumps(payload, ensure_ascii=False, indent=2))


def _open_store(args: argparse.Namespace) -> PgStore:
    """目标 PgStore：DSN 未声明即拒绝（不猜生产库），目标校验由 Store 负责。"""
    dsn = (args.dsn or os.environ.get("CORPUS_I2_DSN", "")).strip()
    if not dsn:
        raise StoreError("拒绝：未声明目标库（--dsn 或 CORPUS_I2_DSN），CLI 不隐式连任何库")
    return PgStore(dsn, sandbox_db=_SANDBOX_DB)


def _load_manifest(path: Path) -> tuple[list[PlanEntry], Path | None, Path | None]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError("manifest 必须是 JSON 对象")
    sources = data.get("sources")
    if not isinstance(sources, list) or not sources:
        raise ValueError("manifest.sources 必须是非空数组（显式清单，不递归扫描目录）")
    entries: list[PlanEntry] = []
    for item in sources:
        if not isinstance(item, dict) or not item.get("path"):
            raise ValueError("每个来源必须含 path 字段")
        raw_domain = item.get("domain_hint")
        entries.append(
            PlanEntry(
                path=str(item["path"]),
                original_name=item.get("original_name"),
                domain_hint=ResearchDomain(raw_domain) if raw_domain else None,
                review_decision_ids=tuple(item.get("review_decision_ids") or ()),
            )
        )
    archive_root = data.get("archive_root")
    policy = data.get("policy")
    return (
        entries,
        Path(str(archive_root)) if archive_root else None,
        Path(str(policy)) if policy else None,
    )


def _load_policy(args: argparse.Namespace, manifest_policy: Path | None) -> AdmissionPolicy:
    path = (
        Path(args.policy) if getattr(args, "policy", None) else manifest_policy or _DEFAULT_POLICY
    )
    # dev lane（U 2026-09-20 裁决）：dev 政策必须由显式 env 开关放行，否则 fail-closed。
    return load_admission_policy(path, allow_dev_lane=os.environ.get(_DEV_LANE_ENV) == "1")


def _resolve_archive_root(args: argparse.Namespace, manifest_root: Path | None) -> Path:
    value = getattr(args, "archive_root", None)
    if value:
        return Path(value)
    if manifest_root is not None:
        return manifest_root
    raise ValueError("必须声明 archive-root（CLI 参数或 manifest.archive_root）")


# ── 缺口视图（check/status 共用；判定实现来自 engine/gaps，不在此复制规则） ──


@dataclass(frozen=True)
class _GapView:
    """缺口视图（check/status 共用的机读字段）。"""

    gaps: list[dict[str, object]]
    summary: dict[str, object]
    recovery: list[dict[str, object]]
    error: str | None = None

    @property
    def blocking_count(self) -> int:
        value = self.summary.get("blocking", 0)
        return int(value) if isinstance(value, int) else 0

    def as_payload(self) -> dict[str, object]:
        payload: dict[str, object] = {
            "gap_policy_rev": GAP_POLICY_REV,
            "gap_summary": self.summary,
            "gaps": self.gaps,
            "recovery": self.recovery,
        }
        if self.error is not None:
            payload["gaps_error"] = self.error
        return payload


def _gap_view(build: Build, store: Store | None = None) -> _GapView:
    """build 的结构化缺口视图；台账不可读时显式报告，不伪装成「没有缺口」。"""
    try:
        records = gap_records_of(build, store=store)
    except EngineError as exc:
        return _GapView(
            gaps=[],
            summary={"total": 0, "policy_rev": GAP_POLICY_REV},
            recovery=[],
            error=str(exc),
        )
    return _GapView(
        gaps=[record.as_payload() for record in records],
        summary=gap_summary(records),
        recovery=recovery_paths(records),
    )


def _precheck_entry(entry: PlannedSource) -> dict[str, object]:
    """只读可发布性预检：跑读取器 + 缺口记账，用与发布门同一分级口径判预判。

    无 PG（取不到准入 scope）⇒ 按「无 scope」判定；因此预判只可能比 ``check``
    更严（有 scope 时部分缺口会因落在批准范围之外而放行），不会更宽。
    读取失败按 fail-closed 报告（``publishable_prejudgement=None`` + ``error``），
    绝不把「读不了」当成「没问题」。
    """
    try:
        reader_result = read_document(entry.path)
        clean = clean_reader_result(reader_result)
    except (OSError, ValueError, ImportError) as exc:
        return {
            "scope": "unscoped_precheck",
            "publishable_prejudgement": None,
            "error": f"{type(exc).__name__}: {exc}",
            "gaps": [],
            "recovery": [],
        }
    gap_keys = [region.key for region in clean.regions if region.ordinal is None]
    records = evaluate_against_scope(gap_records(gap_keys), ())
    return {
        "scope": "unscoped_precheck",
        "publishable_prejudgement": not blocking_gaps(records),
        "gap_summary": gap_summary(records),
        "gaps": [record.as_payload() for record in records],
        "recovery": recovery_paths(records),
    }


# ── plan ──────────────────────────────────────────────────────


def _cmd_plan(args: argparse.Namespace) -> int:
    entries, _manifest_root, manifest_policy = _load_manifest(Path(args.manifest))
    policy = _load_policy(args, manifest_policy)
    plan = plan_builds(entries, policy=policy)
    prechecks = [_precheck_entry(entry) for entry in plan.entries]
    _emit(
        {
            "ok": True,
            "command": "plan",
            "policy_rev": plan.policy_rev,
            "count": len(plan.entries),
            "gap_policy_rev": GAP_POLICY_REV,
            "entries": [
                {
                    "path": entry.path,
                    "original_name": entry.original_name,
                    "format": entry.format.value,
                    "size_bytes": entry.size_bytes,
                    "domain_hint": entry.domain_hint.value if entry.domain_hint else None,
                    "review_decision_ids": list(entry.review_decision_ids),
                    "precheck": precheck,
                }
                for entry, precheck in zip(plan.entries, prechecks, strict=True)
            ],
            "precheck_summary": {
                "publishable": sum(
                    1 for item in prechecks if item["publishable_prejudgement"] is True
                ),
                "not_publishable": sum(
                    1 for item in prechecks if item["publishable_prejudgement"] is False
                ),
                "unreadable": sum(
                    1 for item in prechecks if item["publishable_prejudgement"] is None
                ),
                "scope": "unscoped_precheck",
                "note": "预检为预判（无 PG/无 scope）；发布门与 check 才是权威判定",
            },
            "hint": "plan 只读：不写 PG、不调模型；预检读取来源文件以做缺口记账",
        }
    )
    return EXIT_OK


# ── build ─────────────────────────────────────────────────────


def _cmd_build(args: argparse.Namespace) -> int:
    entries, manifest_root, manifest_policy = _load_manifest(Path(args.manifest))
    policy = _load_policy(args, manifest_policy)
    archive_root = _resolve_archive_root(args, manifest_root)
    plan = plan_builds(entries, policy=policy)
    owner = args.owner or "cli-build"
    with _open_store(args) as store:
        report = execute_builds(
            store,
            plan,
            policy=policy,
            archive_root=archive_root,
            owner_id=owner,
            now=datetime.now(UTC),
            lease=DEFAULT_LEASE,
        )
    outcomes = [
        {
            "original_name": outcome.original_name,
            "source_id": outcome.source.source_id,
            "decision_id": outcome.admission.decision_id,
            "decision": outcome.admission.decision.value,
            "build_id": outcome.build.build_id if outcome.build else None,
            "unit_count": outcome.unit_count,
            "chunk_count": outcome.chunk_count,
            "source_reused": outcome.source_reused,
            "archive_reused": outcome.archive_reused,
        }
        for outcome in report.outcomes
    ]
    _emit(
        {
            "ok": True,
            "command": "build",
            "owner_id": owner,
            "archive_root": str(archive_root),
            "count": len(outcomes),
            "outcomes": outcomes,
            "hint": "build 不自动发布；发布请用 publish --build <id> --operator <who>",
        }
    )
    return EXIT_OK


# ── check ─────────────────────────────────────────────────────


def _cmd_check(args: argparse.Namespace) -> int:
    """核验产物/索引/取证/状态（架构 §9）；被拒时同样输出结构化缺口与恢复路径。

    缺口可见性与发布门同源（``engine.gap_records_of``）：拒绝时 ``gaps`` 非空且
    ``gap_summary.blocking`` ≥ 1（或 ``gaps_error`` 说明台账不可读），脚本据此
    自动路由（补 OCR / 转 review_required / 换料），不必解析自然语言 ``error``。
    """
    dsn = (args.dsn or os.environ.get("CORPUS_I2_DSN", "")).strip()
    with _open_store(args) as store:
        # 目标不存在与「门未过」是两种前置条件：前者 5、后者 4（跨命令同码）
        build = store.get_build(args.build)
        if build is None:
            _emit({"ok": False, "command": "check", "error": f"build 不存在: {args.build}"})
            return EXIT_UNAVAILABLE
        view = _gap_view(build, store)
        try:
            build = check_build_publishable(store, args.build)
        except EngineError as exc:
            _emit(
                {
                    "ok": False,
                    "command": "check",
                    "build_id": args.build,
                    "source_id": build.source_id,
                    "publishable": False,
                    "error": str(exc),
                    **view.as_payload(),
                }
            )
            return EXIT_GATE
        units = store.get_units(args.build)
        chunks = store.get_chunks(args.build)
        publication = store.get_publication(build.source_id)
    coverage = read_pg.coverage_snapshot(dsn, sandbox_db=_SANDBOX_DB, query_status="unknown")
    _emit(
        {
            "ok": True,
            "command": "check",
            "build_id": args.build,
            "source_id": build.source_id,
            "decision_id": build.decision_id,
            "unit_count": len(units),
            "chunk_count": len(chunks),
            "index_rev": build.index_rev,
            "publishable": True,
            "publication": (
                {
                    "current_decision_id": publication.current_decision_id,
                    "active_build_id": publication.active_build_id,
                    "generation": publication.generation,
                    "active": publication.active_build_id == args.build,
                }
                if publication is not None
                else None
            ),
            "coverage": coverage,
            **view.as_payload(),
        }
    )
    return EXIT_OK


# ── publish ───────────────────────────────────────────────────


def _cmd_gap_review(args: argparse.Namespace) -> int:
    """Export an unsigned template, or register a human-supplied immutable credential."""
    from plugins.corpus.preparation.gap_review import GapReview, review_template

    with _open_store(args) as store:
        build = store.get_build(args.build)
        if build is None:
            raise EngineError(f"build 不存在: {args.build}")
        if args.record is None:
            _emit(review_template(build, gap_records_of(build)))
            return EXIT_OK
        review = GapReview.from_json(Path(args.record).read_text(encoding="utf-8"))
        if review.build_id != build.build_id:
            raise EngineError("human gap review --build 与凭证绑定不一致")
        store.put_gap_review(review)
        _emit(
            {
                "ok": True,
                "command": "gap-review",
                "build_id": build.build_id,
                "review_id": review.review_id,
                "reviewer": review.reviewer,
                "evidence_scope_ref": review.evidence_scope_ref,
                **_gap_view(build, store).as_payload(),
            }
        )
    return EXIT_OK


def _cmd_publish(args: argparse.Namespace) -> int:
    operator = args.operator
    with _open_store(args) as store:
        publication = publish_build(
            store,
            args.build,
            activated_at=datetime.now(UTC),
            owner_id=f"cli:{operator}",
            operator=operator,
        )
        job = store.get_job(args.build, JobStage.PUBLISHED)
    _emit(
        {
            "ok": True,
            "command": "publish",
            "operator": operator,
            "source_id": publication.source_id,
            "decision_id": publication.current_decision_id,
            "active_build_id": publication.active_build_id,
            "generation": publication.generation,
            "activated_at": (
                publication.activated_at.isoformat() if publication.activated_at else None
            ),
            "record": json.loads(job.checkpoint) if job is not None and job.checkpoint else None,
        }
    )
    return EXIT_OK


# ── status ────────────────────────────────────────────────────


def _cmd_status(args: argparse.Namespace) -> int:
    """显示该 build 的逐阶段状态、失败、缺口与可执行恢复路径（架构 §9）。

    ``gaps``/``gap_summary``/``recovery`` 是机读字段（码/坐标/状态/分级/依据/动作），
    ``next`` 是给人看的一句话；两者由同一缺口裁决得出，不会互相矛盾。
    """
    dsn = (args.dsn or os.environ.get("CORPUS_I2_DSN", "")).strip()
    with _open_store(args) as store:
        build = store.get_build(args.build)
        if build is None:
            _emit({"ok": False, "command": "status", "error": f"build 不存在: {args.build}"})
            return EXIT_UNAVAILABLE
        jobs: list[dict[str, object]] = []
        for stage in _STAGES:
            job = store.get_job(args.build, stage)
            jobs.append(
                {
                    "stage": stage.value,
                    "job": (
                        {
                            "attempt": job.attempt,
                            "state": job.state.value,
                            "owner_id": job.owner_id,
                            "error": job.error,
                            "checkpoint": json.loads(job.checkpoint) if job.checkpoint else None,
                        }
                        if job is not None
                        else None
                    ),
                }
            )
        publication = store.get_publication(build.source_id)
        admission = store.latest_admission(build.source_id)
        view = _gap_view(build, store)
    coverage = read_pg.coverage_snapshot(dsn, sandbox_db=_SANDBOX_DB)
    failed = [
        str(entry["stage"])
        for entry in jobs
        if isinstance(entry["job"], dict) and entry["job"].get("state") == "failed"
    ]
    pending = admission is not None and admission.decision.value == "review_required"
    blocking_count = view.blocking_count
    active = publication is not None and publication.active_build_id == args.build
    if pending:
        next_hint = "admission 未决：先完成人工复核，不得发布"
    elif failed:
        next_hint = "存在失败阶段：从该阶段恢复（重跑对应 build 阶段）"
    elif blocking_count:
        next_hint = (
            f"存在 {blocking_count} 处阻断发布的缺口：按 recovery 处置（补 OCR/复核/换料）"
            "后重跑 build；或按 §7.3 口径人工裁定"
        )
    elif active:
        next_hint = (
            "已发布"
            if not view.gaps
            else f"已发布（含 {len(view.gaps)} 处已放行缺口：coverage 记为 scoped）"
        )
    else:
        next_hint = "可发布"
    recovery: list[dict[str, object]] = list(view.recovery)
    recovery.extend(
        {
            "stage": stage,
            "action": "重跑该 build 阶段（检查点保留已完成阶段）",
            "command": (
                "uv run python -m plugins.corpus.cli build --manifest "
                "<manifest.json>（同清单重跑得到同 build_id）"
            ),
        }
        for stage in failed
    )
    if pending:
        recovery.append(
            {
                "action": "先完成准入复核：决定 in_scope 后方可发布",
                "command": "人工复核队列 → 更新准入决定 → 再跑 check/publish",
            }
        )
    _emit(
        {
            "ok": True,
            "command": "status",
            "build_id": args.build,
            "source_id": build.source_id,
            "decision_id": build.decision_id,
            "admission": admission.decision.value if admission is not None else None,
            "failed_stages": failed,
            "jobs": jobs,
            **view.as_payload(),
            "recovery": recovery,
            "publication": (
                {
                    "active_build_id": publication.active_build_id,
                    "generation": publication.generation,
                }
                if publication is not None
                else None
            ),
            "coverage": coverage,
            "next": next_hint,
        }
    )
    return EXIT_OK


# ── rebuild-plan ──────────────────────────────────────────────


def _cmd_rebuild_plan(args: argparse.Namespace) -> int:
    with _open_store(args) as store:
        build = store.get_build(args.build)
        if build is None:
            _emit({"ok": False, "command": "rebuild-plan", "error": f"build 不存在: {args.build}"})
            return EXIT_UNAVAILABLE
        source = store.get_source(build.source_id)
    revs = current_revs()
    # parse 阶段：用与引擎同一公式重算（parse_rule_rev + 源哈希 + 当前读取器版本），
    # 相等即检查点可复用；读取器/规则/源字节任一变化都会得到不同 parse_rev。
    parse_reuse = "unknown"
    parse_expected = None
    if source is not None:
        # RM-I28-9：期望 parse_rev 由引擎公开 API 计算（CLI 不复制公式）
        parse_expected = expected_parse_rev(source)
        parse_reuse = "reuse" if parse_expected == build.parse_rev else "rebuild"
    stages: dict[str, dict[str, object]] = {
        "parse": {
            "current_rev": str(parse_expected) if parse_expected else "source 未登记",
            "recorded_rev": build.parse_rev,
            "reuse": parse_reuse,
            "note": "源哈希未变且读取器版本一致才可复用解析检查点；否则重解析",
        },
        "clean": {
            "current_rev": revs["clean_rev"],
            "recorded_rev": build.clean_rev,
            "reuse": "reuse" if build.clean_rev == revs["clean_rev"] else "rebuild",
        },
        "chunk": {
            "current_rev": revs["chunk_rev"],
            "recorded_rev": build.chunk_rev,
            "reuse": "reuse" if build.chunk_rev == revs["chunk_rev"] else "rebuild",
        },
        "index": {
            "current_rev": revs["index_rev"],
            "recorded_rev": build.index_rev,
            "reuse": "reuse" if build.index_rev == revs["index_rev"] else "rebuild",
        },
    }
    rebuild = [name for name, info in stages.items() if info["reuse"] == "rebuild"]
    _emit(
        {
            "ok": True,
            "command": "rebuild-plan",
            "build_id": args.build,
            "stages": stages,
            "rebuild_stages": rebuild,
            "hint": (
                "规则版本升级必须生成新 build（不做原地重写）；解析阶段可复用同一 parse_rev "
                "的不可变中间产物，不重新读取/解析全部文件"
            ),
        }
    )
    return EXIT_OK


# ── 入口 ──────────────────────────────────────────────────────


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="corpus",
        description="语料 CLI 六职责（I2-4）：plan/build/check/publish/status/rebuild-plan",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    for name in ("plan", "build"):
        cmd = sub.add_parser(name)
        cmd.add_argument("--manifest", required=True, help="显式清单 JSON（sources 非空数组）")
        cmd.add_argument("--dsn", default=None, help="隔离目标库 DSN（默认 CORPUS_I2_DSN）")
        cmd.add_argument("--policy", default=None, help="准入政策 JSON（默认冻结政策）")
        if name == "build":
            cmd.add_argument("--archive-root", default=None, help="内容寻址归档根目录")
            cmd.add_argument("--owner", default=None, help="job 租约 owner_id（默认 cli-build）")

    check = sub.add_parser("check")
    check.add_argument("--build", required=True)
    check.add_argument("--dsn", default=None)

    publish = sub.add_parser("publish")
    publish.add_argument("--build", required=True)
    publish.add_argument("--operator", required=True, help="操作者（记入 generation 审计记录）")
    publish.add_argument("--dsn", default=None)

    gap_review = sub.add_parser("gap-review", help="导出未签署模板或登记具名人工判级凭证")
    gap_review.add_argument("--build", required=True)
    gap_review.add_argument("--record", help="人工签署 JSON；省略时只输出未签署模板")
    gap_review.add_argument("--dsn", default=None)

    status = sub.add_parser("status")
    status.add_argument("--build", required=True)
    status.add_argument("--dsn", default=None)

    rebuild = sub.add_parser("rebuild-plan")
    rebuild.add_argument("--build", required=True)
    rebuild.add_argument("--dsn", default=None)
    return parser


_HANDLERS = {
    "plan": _cmd_plan,
    "build": _cmd_build,
    "check": _cmd_check,
    "publish": _cmd_publish,
    "gap-review": _cmd_gap_review,
    "status": _cmd_status,
    "rebuild-plan": _cmd_rebuild_plan,
}

#: 输入类异常 → exit 2；门未过 → exit 4（由命令归属决定）。
_INPUT_COMMANDS = frozenset({"plan", "rebuild-plan"})


def main(argv: list[str] | None = None) -> int:
    """CLI 入口：解析参数 → 目标校验 → 复用正式编排 → 退出码映射。"""
    parser = _build_parser()
    try:
        args = parser.parse_args(argv)
    except SystemExit:  # argparse 缺参/非法值：归一为 EXIT_INPUT（返回码而非异常）
        return EXIT_INPUT
    handler = _HANDLERS[args.command]
    try:
        return handler(args)
    except StoreError as exc:
        # PgStore/读侧的目标与守卫拒绝统一以「拒绝」开头：判为目标类（exit 3）；
        # 其余 Store 一致性错误属门未过（exit 4）。不区分命令，保持同一映射。
        if str(exc).startswith("拒绝"):
            _emit({"ok": False, "command": args.command, "error": str(exc)})
            return EXIT_TARGET
        _emit({"ok": False, "command": args.command, "error": str(exc)})
        return EXIT_GATE
    except EngineError as exc:
        code = EXIT_INPUT if args.command in _INPUT_COMMANDS else EXIT_GATE
        _emit({"ok": False, "command": args.command, "error": str(exc)})
        return code
    except (OSError, ValueError, json.JSONDecodeError, KeyError) as exc:
        _emit({"ok": False, "command": args.command, "error": f"{type(exc).__name__}: {exc}"})
        return EXIT_INPUT


if __name__ == "__main__":  # pragma: no cover - 进程入口
    sys.exit(main())
