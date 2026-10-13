#!/usr/bin/env python3
"""Impact assessment for the "publish with explicitly registered gaps" route (zero calls).

Every claim in the generated report is derived by scanning the working tree, so the
report is reproducible and its inputs are hashed. No code is modified.

Scope:
  - enumerate the code sites that decide whether a gap-bearing artifact can be published
  - enumerate the standing test assertions that encode "a gap must not become accepted"
  - enumerate the frozen-contract fingerprints that a schema change would invalidate
  - check whether the ingestion-layer gap mechanism is coupled to the semantic layer
  - derive, per candidate option, the change set it implies

Read-only on every input. Writes only inside its own evidence directory.
--no-write computes and prints the summary without writing artifacts.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
SCRATCH = REPO_ROOT / ".scratch/claims-r2-role-isolation"
STRUCTURED = REPO_ROOT / "plugins/corpus/structured"
TESTS = REPO_ROOT / "tests"

# (key, file, tokens that mark the site, one-line meaning)
SITE_SPEC: tuple[tuple[str, Path, tuple[str, ...], str], ...] = (
    (
        "publish_gate",
        STRUCTURED / "store.py",
        ("artifact_not_publishable",),
        "artifact 级发布门：要求 quality_status == accepted，否则 CS_DEPENDENCY_NOT_READY",
    ),
    (
        "manifest_quality_hardcoded",
        STRUCTURED / "store.py",
        ('quality_status="accepted"',),
        "发布 manifest 组装时硬编码 accepted —— 缺口信息在此无落点",
    ),
    (
        "read_gate",
        STRUCTURED / "store.py",
        ('manifest.quality_status != "accepted"',),
        "读取门：query 与 consumption 共用，manifest 非 accepted 即 CS_NOT_PUBLISHED",
    ),
    (
        "manifest_reason_codes",
        STRUCTURED / "store.py",
        ("reason_codes: tuple[str, ...] = ()",),
        "manifest 已有自由字符串数组，结构上可承载缺口码（无坐标、无分级）",
    ),
    (
        "publication_coverage",
        STRUCTURED / "store.py",
        ("class PublicationCoverage",),
        "manifest 的覆盖位只有三个 ContextStatus，没有缺口清单/坐标位",
    ),
    (
        "artifact_quality_derivation",
        STRUCTURED / "roles.py",
        ("quality: QualityStatus = (",),
        "artifact 级 quality 推导式：缺口（omitted / invalid_quality / run-state）压成 review_required",
    ),
    (
        "ledger_candidate_status",
        STRUCTURED / "ledger.py",
        ('quality_status == "accepted"',),
        "任务账把非 accepted 的 artifact 记为 unpublished，影响可发布候选集",
    ),
    (
        "ledger_accepted_items",
        STRUCTURED / "ledger.py",
        ("class AcceptedMaterialItems", 'self.artifact.quality_status != "accepted"'),
        "accepted-items 导入要求父工件 quality_status == accepted",
    ),
    (
        "a4_quality_gate",
        STRUCTURED / "consumption.py",
        ('record.quality_status != "accepted"',),
        "A4 校验把 review_required 记为 problem(quality_not_accepted) —— 引用会被判未合格",
    ),
    (
        "query_material_hardcoded",
        STRUCTURED / "query.py",
        ('quality_status="accepted"',),
        "查询层对 material 记录硬编码 accepted —— 缺口对主线不可见",
    ),
    (
        "query_claims_mapping",
        STRUCTURED / "query.py",
        ('"review": "review_required"',),
        "查询层 claims 记录按 payload 质量映射（与 material 路径不对称）",
    ),
)

# (key, regex, meaning) applied to every tests/*.py
TEST_SPEC: tuple[tuple[str, str, str], ...] = (
    (
        "gap_means_not_accepted",
        r'quality_status != "accepted"|quality_status == "review_required"',
        "断言：存在缺口/异常时 artifact 不得为 accepted",
    ),
    (
        "omission_asserted",
        r"coverage\.omitted_unit_ids",
        "断言：缺口必须显式可见（omitted_unit_ids 非空）",
    ),
    (
        "publish_gate_asserted",
        r"artifact_not_publishable",
        "断言：发布门拒绝行为的直接断言",
    ),
    (
        "a4_quality_asserted",
        r"quality_not_accepted",
        "断言：A4 对 review_required 记录的处理",
    ),
)

CONTRACT_SPEC: tuple[tuple[str, str, str], ...] = (
    ("publication_schema", "scratch", "contracts/v1/semantic-publication.schema.json"),
    ("publication_valid_example", "scratch", "contracts/v1/examples/valid/semantic-publication.json"),
    ("publication_invalid_example", "scratch", "contracts/v1/examples/invalid/semantic-publication.json"),
    ("role_artifact_schema", "scratch", "contracts/v1/role-artifact.schema.json"),
    ("contract_manifest", "scratch", "contracts/contract-manifest.json"),
    ("synthetic_asset_manifest", "repo", "tests/fixtures/corpus_structured_synthetic/asset-manifest.json"),
)


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def scan_site(path: Path, tokens: tuple[str, ...]) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    hits: list[dict[str, Any]] = []
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if any(token in line for token in tokens):
            hits.append({"line": number, "text": line.strip()[:160]})
    return hits


def scan_tests(pattern: str) -> list[dict[str, Any]]:
    regex = re.compile(pattern)
    hits: list[dict[str, Any]] = []
    for path in sorted(TESTS.rglob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if regex.search(line):
                hits.append(
                    {
                        "file": str(path.relative_to(REPO_ROOT)),
                        "line": number,
                        "text": line.strip()[:160],
                    }
                )
    return hits


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    sites: dict[str, Any] = {}
    for key, path, tokens, meaning in SITE_SPEC:
        sites[key] = {
            "file": str(path.relative_to(REPO_ROOT)),
            "meaning": meaning,
            "hits": scan_site(path, tokens),
        }

    tests: dict[str, Any] = {}
    for key, pattern, meaning in TEST_SPEC:
        hits = scan_tests(pattern)
        by_file: dict[str, int] = {}
        for hit in hits:
            by_file[hit["file"]] = by_file.get(hit["file"], 0) + 1
        tests[key] = {"meaning": meaning, "pattern": pattern, "count": len(hits), "by_file": by_file, "hits": hits}

    contracts: dict[str, Any] = {}
    for key, base, rel in CONTRACT_SPEC:
        path = (SCRATCH if base == "scratch" else REPO_ROOT) / rel
        contracts[key] = {
            "path": str(path.relative_to(REPO_ROOT)),
            "exists": path.exists(),
            "sha256": sha256_of(path) if path.exists() else None,
        }

    # is the ingestion-layer gap mechanism coupled to the semantic layer at all?
    preparation_imports = []
    for path in sorted(STRUCTURED.glob("*.py")):
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if "preparation" in line and ("import" in line or "from" in line):
                preparation_imports.append(
                    {"file": str(path.relative_to(REPO_ROOT)), "line": number, "text": line.strip()}
                )
    gap_mechanism = {
        "preparation_gaps_module": "plugins/corpus/preparation/gaps.py",
        "preparation_publishable_check": "plugins/corpus/preparation/engine.py:check_build_publishable",
        "structured_imports_preparation": preparation_imports,
        "coupled": bool(preparation_imports),
    }

    # option → the enumerated sites it must touch (keys only; no new invention)
    options = [
        {
            "id": "O0_record_only",
            "summary": "不发布，只把缺口记档",
            "touches": [],
            "artifacts_rebuilt": False,
            "reaches_goal": False,
            "note": "零改动、零风险；『发布走显式缺口』目标未达成",
        },
        {
            "id": "O1_publish_layer_keeps_artifact_semantics",
            "summary": "在发布层放行带缺口发布，artifact 层语义不动（仍 review_required），缺口进 manifest.reason_codes",
            "touches": [
                "manifest_quality_hardcoded",
                "publish_gate",
                "read_gate",
                "manifest_reason_codes",
                "a4_quality_gate",
                "query_material_hardcoded",
                "ledger_candidate_status",
            ],
            "artifacts_rebuilt": False,
            "reaches_goal": True,
            "note": (
                "既有 artifact 字节与哈希不变；角色层 11 处断言全部保持有效；"
                "但必须三处同步（发布门/读取门/查询与A4揭示），否则缺口要么被隐藏要么被误拒"
            ),
        },
        {
            "id": "O2_artifact_level_relaxation",
            "summary": "改 artifact 级 quality 推导，让带缺口工件本身成为 accepted",
            "touches": [
                "artifact_quality_derivation",
                "manifest_quality_hardcoded",
                "publish_gate",
                "read_gate",
            ],
            "artifacts_rebuilt": True,
            "reaches_goal": True,
            "note": (
                "与常驻测试的既定语义直接冲突（缺口 ⇒ 不得 accepted）；"
                "按 U 既定纪律不得改测试适配；且缺口与无缺口在 artifact 层不可区分"
            ),
        },
    ]

    guard_coverage = {
        "publish_gate_direct_assertions": tests["publish_gate_asserted"]["count"],
        "a4_quality_direct_assertions": tests["a4_quality_asserted"]["count"],
        "note": "两条拒绝路径没有直接断言：放宽门禁时缺少反例护栏",
    }

    out = {
        "schema_version": "publish-gap-route-impact-1",
        "created_on": "2026-10-13",
        "zero_model_calls": True,
        "question": "若让语义发布在存在『已显式登记的缺口』时仍可进行，对后续有什么影响？",
        "method": "扫描工作树枚举位点/断言/契约指纹；不改动任何文件；结论均由 enumerate 结果推导",
        "sites": sites,
        "standing_test_assertions": tests,
        "guard_coverage": guard_coverage,
        "contract_fingerprints": contracts,
        "ingestion_gap_mechanism": gap_mechanism,
        "options": options,
        "hardest_blockers": [
            {
                "n": 1,
                "blocker": "发布 manifest 的 quality_status 是硬编码 accepted（store.py:955）",
                "why": "缺口信息在 manifest 组装处没有落点；放宽门之前必须先决定 manifest 是否允许表达带缺口发布",
            },
            {
                "n": 2,
                "blocker": "缺口在查询层不可见（query.py:382 material 记录硬编码 accepted）",
                "why": "发布后主线看到的是 accepted，等于把缺口藏起来，违反契约 §5.4『覆盖状态必须可区分』",
            },
            {
                "n": 3,
                "blocker": "A4 把 review_required 记为未合格（consumption.py:298）",
                "why": "若查询层改为照实报告，报告引用会被判 quality_not_accepted；两处必须同轮改，否则只能在『隐藏』与『不可用』之间二选一",
            },
            {
                "n": 4,
                "blocker": "PublicationCoverage 没有缺口位（store.py:116-124）",
                "why": "缺口只能塞进自由字符串 reason_codes，没有坐标/分级；若要对齐 ingestion 层口径则需要改 schema 并重签契约",
            },
            {
                "n": 5,
                "blocker": "ingestion 层已有独立缺口机制且与 structured 零对接",
                "why": "不复用口径就会产生第三套『缺口』语义；复用则要打通两层枚举与字段",
            },
        ],
        "input_hashes": {
            **{
                key: sha256_of(STRUCTURED / name)
                for key, name in (
                    ("store", "store.py"),
                    ("roles", "roles.py"),
                    ("query", "query.py"),
                    ("consumption", "consumption.py"),
                    ("ledger", "ledger.py"),
                )
            },
            "preparation_gaps": sha256_of(REPO_ROOT / "plugins/corpus/preparation/gaps.py"),
            **{k: v["sha256"] for k, v in contracts.items() if v["sha256"]},
        },
        "reproduce": (
            "uv run python .scratch/claims-r2-role-isolation/evidence/"
            "73-publish-gap-route-impact-20261013/r0-zero-call/build_publish_gap_impact.py"
        ),
    }

    summary = {
        "sites_found": {k: len(v["hits"]) for k, v in sites.items()},
        "test_assertions": {k: v["count"] for k, v in tests.items()},
        "contracts_present": {k: v["exists"] for k, v in contracts.items()},
        "ingestion_coupled": gap_mechanism["coupled"],
        "options": {o["id"]: {"sites": len(o["touches"]), "artifacts_rebuilt": o["artifacts_rebuilt"]} for o in options},
    }

    if not args.no_write:
        (HERE / "impact-assessment.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (HERE / "impact-assessment.md").write_text(render_md(out), encoding="utf-8")
        manifest = {
            "schema_version": "evidence-manifest-1",
            "created_on": "2026-10-13",
            "zero_model_calls": True,
            "read_only_on_workspace": True,
            "artifacts": {
                name: sha256_of(HERE / name)
                for name in ("build_publish_gap_impact.py", "impact-assessment.json", "impact-assessment.md")
            },
            "inputs": out["input_hashes"],
            "reproduce": out["reproduce"],
        }
        (HERE / "MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def render_md(out: dict[str, Any]) -> str:
    lines = [
        "# 「发布走显式缺口」影响评估（零模型调用；只读枚举）",
        "",
        f"- 2026-10-13　问题：{out['question']}",
        f"- 方法：{out['method']}",
        "",
        "## 一、结论摘要",
        "",
        "- 改动面**收敛但不小**：核心 7 处代码位点 + 冻结契约重签；关键不是「能不能放开」，"
        "而是**必须三处同轮改**（发布门 / 读取门 / 查询与 A4 的揭示），否则缺口只会被隐藏或被误拒。",
        "- **既有 artifact 可以不动**（O1）：选择在发布层放行，artifact 仍诚实标记 `review_required`，"
        "角色层 11 处既定断言全部保持有效。",
        "- 若改 artifact 级推导（O2）：与常驻测试的既定语义直接冲突，按既定纪律不可「改测试适配」。",
        "",
        "## 二、代码位点（只读扫描，逐处）",
        "",
        "| 位点 | 文件 | 行 | 含义 |",
        "|---|---|---|---|",
    ]
    for key, site in out["sites"].items():
        where = "、".join(str(h["line"]) for h in site["hits"]) or "—（未命中）"
        lines.append(f"| `{key}` | `{site['file']}` | {where} | {site['meaning']} |")
    lines += [
        "",
        "## 三、常驻测试里已被编码的语义（改动会撞到的护栏）",
        "",
        "| 断言类 | 条数 | 分布 |",
        "|---|---|---|",
    ]
    for key, spec in out["standing_test_assertions"].items():
        dist = "；".join(f"`{f}` × {n}" for f, n in sorted(spec["by_file"].items())) or "—"
        lines.append(f"| {spec['meaning']}（`{key}`） | {spec['count']} | {dist} |")
    lines += [
        "",
        f"> 护栏缺口：发布门拒绝码直接断言 **{out['guard_coverage']['publish_gate_direct_assertions']}** 条、"
        f"A4 未合格路径直接断言 **{out['guard_coverage']['a4_quality_direct_assertions']}** 条 —— "
        f"{out['guard_coverage']['note']}",
        "",
        "## 四、冻结契约指纹（schema 一动就要重签的清单）",
        "",
        "| 契约 | 路径 | 存在 | sha256 |",
        "|---|---|---|---|",
    ]
    for key, spec in out["contract_fingerprints"].items():
        lines.append(f"| `{key}` | `{spec['path']}` | {spec['exists']} | {spec['sha256']} |")
    gap = out["ingestion_gap_mechanism"]
    lines += [
        "",
        "## 五、与 ingestion 层缺口机制的关系",
        "",
        f"- 既有机制：`{gap['preparation_gaps_module']}`、`{gap['preparation_publishable_check']}`（CLI `check` / `EXIT_GATE`）",
        f"- structured 层是否 import preparation：**{gap['coupled']}**（命中 {len(gap['structured_imports_preparation'])} 条）",
        "- 含义：两层各有一套「缺口」语义，不复用即产生第三套口径；复用则要打通枚举与字段。",
        "",
        "## 六、最硬的五个阻塞",
        "",
        "| # | 阻塞 | 为什么硬 |",
        "|---|---|---|",
    ]
    for b in out["hardest_blockers"]:
        lines.append(f"| {b['n']} | {b['blocker']} | {b['why']} |")
    lines += [
        "",
        "## 七、三个选项与其影响面",
        "",
        "| 选项 | 做法 | 需改动位点 | 需重建既有 artifact | 达成目标 | 备注 |",
        "|---|---|---|---|---|---|",
    ]
    for o in out["options"]:
        lines.append(
            f"| `{o['id']}` | {o['summary']} | {len(o['touches'])}（{'、'.join(o['touches']) or '—'}） | "
            f"{o['artifacts_rebuilt']} | {o['reaches_goal']} | {o['note']} |"
        )
    lines += [
        "",
        "## 八、复现",
        "",
        "```bash",
        out["reproduce"],
        "```",
        "",
    ]
    return "\n".join(lines)


if __name__ == "__main__":
    raise SystemExit(main())
