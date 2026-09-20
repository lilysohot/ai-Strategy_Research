"""I3-1 三类开发 E2E 首次入链（2026-09-19，U 指示）：台账回填 + I3-1 产物 / 批准集来源副本 /
i3-e2e 阶段守卫与其合成反例自检纳入 **i0c-r32** + 跑三门。

范围（U 指示逐条对应）：
1. **台账回填 I3-1 真实结果**：``docs/plan/corpus-ingestion-rebuild-tasks.md``（§3.6 章节 + I3-1 任务行 +
   导航行）与 ``docs/plan/claims-market-closed-loop-plan.md``（r32 优先状态 + I3-1 详情节 + I3 状态行）；
2. **I3-1 产物入链**：审计目录文本产物（记录/脚本/清单，**不含** ``archive/`` 素材副本）+
   批准集来源副本（``archive-approved/``，内容寻址：文件名 = 内容 sha256）+
   ``i3-e2e`` 守卫与其自检报告（``i3_e2e_guard_selfcheck.py`` → ``i3-e2e-guard-report.json``）+ 环境预检报告；
3. **跑三门**：冻结链 ``validate_i0c_freeze.py``、I3-2 完成门 ``validate_i3_2_completion.py``、
   Step5 复核 ``step5_review.py --no-write``。

本修订在**首冻之前**修正两处配置/机制缺陷（均已登记在 ``corrections``，非静默改动）：
- **i3-e2e 守卫 model 段比 ``guards/i3.json`` 弱**（只拦 ``openai``）：自检 24 项中
  ``import anthropic`` 与 ``import plugins.corpus.material_semantics`` 两项未被拒（实测）→
  对齐 i3.json 的封锁面（4 个模块 + 前缀 + 3 个投毒 env）。E2E 实际运行期间 0 次模型调用，收紧不改变已记录结果；
- **归档忠实性比对按字典序合并修订**（``i0c-r9`` 排在 ``i0c-r32`` 之后 → 取到旧绑定）→
  ``freezes/freeze_utils.py`` 与验证器 ``merged_binding_from_all_but`` 改为**按修订号数值**排序。
"""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
FREEZES = BASE / "freezes"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
GATE = FREEZES / "validate_i3_2_completion.py"
REVIEW = BASE / "audits/20260919-i32-diagnosis/step5_review.py"
FREEZE_UTILS = FREEZES / "freeze_utils.py"
MANIFEST = FREEZES / "freeze-manifest.json"
R32 = FREEZES / "i0c-r32.json"
BEFORE = HERE / "before-r32"
TASKS = ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md"
PLAN = ROOT / "docs/plan/claims-market-closed-loop-plan.md"
GUARD = BASE / "guards/i3-e2e.json"
GUARD_I3 = BASE / "guards/i3.json"
SELFCHECK = HERE / "i3_e2e_guard_selfcheck.py"
REPORT = HERE / "i3-e2e-guard-report.json"
PRECHECK = BASE / "audits/20260919-i3-1-precheck"

AUDIT_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e"
PRE_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-precheck"
BASE_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"

# I3-1 审计目录的**文本**产物（排除 archive/ 与 archive-approved/ 素材副本、以及本生成器自身）
E2E_FILES = (
    "apply_docx_coverage.py",
    "apply_retraction.py",
    "dev-scope-approved.json",
    "dev-scope-manifest-v2.json",
    "dev-scope-manifest-v3.json",
    "dev-scope-manifest.json",
    "i3-1-e2e-approved-set-rerun.json",
    "i3-1-e2e-approved-set-rerun.md",
    "i3-1-e2e-approved-set.json",
    "i3-1-e2e-approved-set.md",
    "i3-1-e2e-final.json",
    "i3-1-e2e-final.md",
    "i3-1-e2e-format-probe.json",
    "i3-1-e2e-format-probe.md",
    "i3-1-e2e-record.json",
    "i3-1-e2e-record.md",
    "i3-1-e2e-scope-v2.json",
    "i3-1-e2e-scope-v2.md",
    "i3-1-e2e-sources.json",
    "i3-1-e2e-sources.md",
    "i3-1-retraction-record.json",
    "i3-1-retraction-record.md",
    "i3-1-screening.json",
    "i3-1-screening.md",
    "preflight-scope-check.json",
    "preflight-scope-check.withdrawn.json",
    "preflight_scope_check.py",
    "retrospective-i3-1-scope.md",
    "run_i3_1_approved_set.py",
    "run_i3_1_e2e.py",
    "run_i3_1_e2e_sources.py",
    "run_i3_1_format_probe.py",
    "run_i3_1_scope_v2.py",
    "run_i3_1_screening.py",
    "screening-manifest.json",
    "summarize_i3_1_e2e.py",
)

PRECHECK_FILES = (
    "i3-1-environment-precheck.json",
    "i3-1-environment-precheck.md",
    "run_i3_1_precheck.py",
)

GUARD_NOTE = (
    "I3-1 三类开发 E2E 阶段守卫（独立于 guards/i3.json：本阶段允许真实读取开发来源与隔离 PG 写入）。"
    "允许路径历史：预检 6 → 换料自选 8/15 → **2026-09-19 深夜撤回 Agent 自选范围**，重置为 U 2026-09-15 "
    "批准的 dev_selection_approved 6 份（i0a2-adjudicated-20260915.json）。启用条件：① 开发范围经 U 批准并生成 "
    "dev-scope-manifest.json；② 隔离目标可达（127.0.0.1:543 的 corpus-db 容器，库名 i2_sandbox_corpus）；"
    "③ 守卫自检通过（i3-e2e-guard-report.json 合成反例全过）。2026-09-19（r32 首冻）：model 封锁面对齐 "
    "guards/i3.json（此前只拦 openai，自检实测 anthropic / material_semantics 未被拒），note 去重。"
)


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def load_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def revision_order(path: Path) -> tuple[int, str]:
    """按**修订号数值**排序：字典序会把 ``i0c-r9`` 排在 ``i0c-r32`` 之后，导致合并取到旧绑定。"""

    stem = path.stem
    try:
        return (int(stem.rsplit("-r", 1)[1]), stem)
    except (IndexError, ValueError):
        return (-1, stem)


def previous_binding() -> dict[str, str]:
    """合并除本修订外的全部绑定，按修订号数值升序（最新修订优先）。"""

    current: dict[str, str] = {}
    paths = sorted((BASE / "freezes").glob("i0c-r*.json"), key=revision_order) + sorted(
        (BASE / "freezes").glob("i1-*.json"), key=revision_order
    )
    for path in paths:
        if path.stem == "i0c-r32":
            continue
        for items in (load_json(path).get("binding") or {}).values():
            for key, value in items.items():
                current.pop(key, None)
                current[key] = value
    return current


def approved_archive_files() -> list[str]:
    files = sorted(p for p in (HERE / "archive-approved").rglob("*") if p.is_file())
    return [rel(p) for p in files]


def py_set(items: list[str], indent: int = 8) -> str:
    pad = " " * indent
    body = "".join(f'{pad}    "{item}",\n' for item in items)
    return "{\n" + body + pad + "}"


# ────────────────────────────────── 1. 守卫：model 封锁对齐 + note 去重（首冻前）


def fix_guard() -> dict:
    before = load_json(GUARD)
    cfg = load_json(GUARD)
    i3 = load_json(GUARD_I3)
    cfg["model"] = i3["model"]
    cfg["note"] = GUARD_NOTE
    GUARD.write_text(json.dumps(cfg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    after = load_json(GUARD)
    for key in ("config_version", "phase", "network", "sources"):
        assert after[key] == before[key], f"i3-e2e 守卫操作字段被意外改动：{key}"
    assert after["model"] == i3["model"], "i3-e2e model 未对齐 i3.json"
    return {
        "model_blocked_modules": after["model"]["blocked_modules"],
        "allowed_source_paths": len(after["sources"]["allowed_source_paths"]),
        "forbidden_roots": len(after["sources"]["forbidden_roots"]),
        "sha256": digest(GUARD),
    }


def run_selfcheck() -> dict:
    reused = False
    if REPORT.exists():
        existing = load_json(REPORT)
        if existing.get("passed") is True and existing.get("config_sha256") == digest(GUARD):
            reused = True
        else:
            raise RuntimeError(f"{REPORT.name} 已存在且与当前守卫不符（write-once，需人工处置）")
    if not reused:
        env = {key: value for key, value in os.environ.items() if key != "PYTHONPATH"}
        proc = subprocess.run(
            [sys.executable, str(SELFCHECK)], cwd=str(ROOT), env=env, capture_output=True, text=True, check=False
        )
        assert REPORT.is_file(), f"自检未生成报告：{proc.stdout}\n{proc.stderr}"
    report = load_json(REPORT)
    failed = [item["case"] for item in report.get("cases", []) if not item.get("passed")]
    assert report.get("passed") is True and not failed, f"i3-e2e 自检未全过：{failed}"
    assert report.get("config_sha256") == digest(GUARD), "自检报告与守卫字节不一致"
    return {
        "passed": report.get("passed"),
        "cases": len(report.get("cases", [])),
        "config_sha256": report.get("config_sha256"),
        "report_sha256": digest(REPORT),
        "reused_existing_report": reused,
    }


# ────────────────────────────────── 2. 台账回填


TASKS_SECTION = """**I3-1 三类开发 E2E 已真实执行（2026-09-19 深夜，照 U 批准的开发集；**i0c-r32** 首次入链）**：
环境 = 隔离沙箱 `corpus-db`（`127.0.0.1:543`，库 `i2_sandbox_corpus`，`corpus` schema 九表）；
阶段守卫 [guards/i3-e2e.json](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json)
（`config_version=1`、网络 allowlist 仅 `127.0.0.1:543`、零模型、`allowed_source_paths` = 批准集 6 份、
留出根与 `guards/i3.json` 逐字一致），合成反例自检 **24/24**
（[报告](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-e2e-guard-report.json)，
write-once；首冻前发现 `model` 封锁面弱于 `guards/i3.json`——`anthropic` 与 `plugins.corpus.material_semantics`
未被拒，已对齐后重跑）。范围唯一权威源 = `i0a2-adjudicated-20260915.json` 的 `dev_selection_approved`
（U 2026-09-15 批准 6 份 PDF），取样前
[preflight_scope_check.py](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/preflight_scope_check.py)
判 **PASS**；**Agent 自选/换料范围已撤回**（保留
[撤回记录](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-retraction-record.md)，
守卫允许路径 15→6；沙箱数据层 teardown（`residue=0`）+ 重建后按批准集重跑，逐源与矩阵**完全复现**）。
真实结果（[批准集记录](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-approved-set.md)
+ [干净沙箱重跑](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/i3-1-e2e-approved-set-rerun.md)）：
6 份 build 全成功（**4305 单元 / 767 切块**），**可发布 2/6**（company 0/2、industry 1/2、macro 1/2），
阻断缺口 **13 处**（`table_lines_without_extraction` 9 + `image_region_unreadable` 4），检索 `同比` 4 命中、
取证核验全过、被拒句柄 0、`audit_corpus_chain` 冲突 0、coverage `scoped`/`matched`。
**判定：I3-1 未完成** —— `per_class_min_2_satisfied=false`（"三类每类≥2 份"在**现行门 + 现行裁定**下无解：
阻断缺口无合法处置路径）；格式覆盖**仅 PDF**（DOCX/MD 在准入口径下 0 份，§12.1 未满足）。两项**待 U 裁定**：
①阻断缺口的处置路径（补 OCR／人工认可入口／换料／显式登记不覆盖）；②MD·DOCX 是否声称覆盖。
**本轮初步结果不得直接放行 I4**；I3-3/I3-4/I3-5/I3-7 另做（缺口分布 F1—F10 见
[复盘](../../.scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260919-i3-1-e2e/retrospective-i3-1-scope.md)）。

"""

TASKS_NAV_ROW = (
    "| I3-1 三类 E2E | [照 U 批准集真实执行（6 份 → 可发布 2/6、阻断缺口 13 处、格式覆盖仅 PDF）；"
    "判定未完成，两项待 U 裁定；i0c-r32 首次入链](claims-market-closed-loop-plan.md#i3-1-e2e) |\n"
)

TASKS_ROW_TAIL_OLD = "先用 `corpus-plan` 预检筛料 |"
TASKS_ROW_TAIL_NEW = (
    "先用 `corpus-plan` 预检筛料。**2026-09-19 实跑（i0c-r32 入链）**：照 U 批准集 6 份 → 可发布 2/6"
    "（company 0/2、industry 1/2、macro 1/2）、阻断缺口 13 处、格式覆盖仅 PDF；`per_class_min_2` 未满足，"
    "判定**未完成**，待 U 裁定缺口处置路径与 MD/DOCX 覆盖声称 |"
)

PLAN_SECTION = """<a id="i3-1-e2e"></a>

### 2026-09-19 I3-1 三类开发 E2E（照 U 批准集执行；i0c-r32 首次入链）

**范围**：唯一权威源 `i0a2-adjudicated-20260915.json` 的 `dev_selection_approved`（U 2026-09-15 批准 6 份 PDF：
company 华创茅台 `e034bdac` / 国信光力 `b6beb6ee`、industry 长江化工 `7463f4d0` / 华福新材料 `aa8e026a`、
macro 华创宏观 `81e10069` / 光大非农 `6fc25e24`）。取样前 `preflight_scope_check.py` 判 **PASS**。
Agent 早期"自选 + 换料"范围**已撤回**（`i3-1-retraction-record.*`；守卫允许路径 15→6；沙箱数据层
teardown + 重建后按批准集重跑，逐源与矩阵完全复现）。

**环境与守卫**：隔离沙箱 `corpus-db`（`127.0.0.1:543`，库 `i2_sandbox_corpus`，`corpus` schema 九表由
`i2/i2s1_apply.py` 建、`i2s1_teardown.py` 拆）；阶段守卫 `guards/i3-e2e.json`
（`config_version=1`、网络 allowlist 仅 `127.0.0.1:543`、零模型、`allowed_source_paths` = 批准集 6 份、
`forbidden_roots` 与 `guards/i3.json` 逐字一致）**独立于** `guards/i3.json`；
`i3-e2e-guard-report.json` 合成反例自检 **24/24**（write-once）。首冻前修正：该守卫 `model` 封锁面原先弱于
`guards/i3.json`（只拦 `openai`，实测 `anthropic` / `plugins.corpus.material_semantics` 未被拒）→ 已对齐后重跑自检。

**真实结果**（`i3-1-e2e-approved-set.{json,md}`、`-rerun.{json,md}`、`-record.*`、`-sources.*`）：
6 份 build 全成功（**4305 单元 / 767 切块**）；**可发布 2/6**（company 0/2、industry 1/2、macro 1/2）；
阻断缺口 **13 处**（`table_lines_without_extraction` 9 + `image_region_unreadable` 4）；检索 `同比` 4 命中、
取证核验全过、被拒句柄 0、`audit_corpus_chain` 冲突 0、coverage `scoped`/`matched`。

**判定（不得读成通过）**：`per_class_min_2_satisfied=false` —— I3-1 任务行的"三类每类≥2 份"在**现行门 +
现行裁定**下无解（阻断缺口无处置路径）；格式覆盖仅 PDF（DOCX/MD 准入口径 0 份，§12.1 未满足）。
两项**待 U 裁定**：①阻断缺口处置路径（补 OCR／人工认可入口／换料／显式登记不覆盖）；②MD·DOCX 是否声称覆盖。
本轮初步结果**不得直接放行 I4**；I3-3/I3-4/I3-5/I3-7 另做（`i3-1-e2e-final.*` 第九/十节 +
`retrospective-i3-1-scope.md` F1—F10）。

**r32 优先状态（2026-09-19，I3-1 首次入链）**：台账回填 I3-1 真实结果；I3-1 审计产物（记录/脚本/清单）+
批准集来源副本（`archive-approved/`，内容寻址）+ `i3-e2e` 守卫与自检 + 环境预检报告 + 台账 + 验证器
绑定为 **i0c-r32**（parent=r31）。**判定：I3-1 未完成**（见上节两项待裁定）；I3-3/I3-4/I3-5/I3-6/I3-7 未做。
I3-1 初步结果不构成 I4 放行依据。

**r31 历史状态**"""


def patch_docs() -> list[str]:
    tasks = TASKS.read_text(encoding="utf-8")
    plan = PLAN.read_text(encoding="utf-8")
    touched: list[str] = []

    if "**I3-1 三类开发 E2E 已真实执行" not in tasks:
        anchor = "**I3-2 采纳稿已落正式路径并冻结（2026-09-18，A 侧，规则仍"
        assert anchor in tasks, "tasks.md 未找到 I3-2 采纳稿锚点"
        tasks = tasks.replace(anchor, TASKS_SECTION + anchor, 1)
        nav_anchor = "| I3-2 补料 | [证据目标候选 v7"
        assert nav_anchor in tasks, "tasks.md 未找到导航表 I3-2 行"
        tasks = tasks.replace(nav_anchor, TASKS_NAV_ROW + nav_anchor, 1)
        assert TASKS_ROW_TAIL_OLD in tasks, "tasks.md 未找到 I3-1 任务行尾"
        tasks = tasks.replace(TASKS_ROW_TAIL_OLD, TASKS_ROW_TAIL_NEW, 1)
        TASKS.write_text(tasks, encoding="utf-8")
        touched.append("tasks")

    if "I3-1 三类开发 E2E（照 U 批准集执行" not in plan:
        anchor = "**r31 优先状态（2026-09-19，I3-2 尾巴收口）**"
        assert anchor in plan, "plan.md 未找到 r31 优先状态锚点"
        plan = plan.replace(anchor, PLAN_SECTION, 1)
        row_old = "；I3-1 前置（缺口分级/坐标）已闭环；最终版本逐类指标"
        assert row_old in plan, "plan.md 未找到 I3 状态行"
        row_new = (
            "；I3-1 前置（缺口分级/坐标）已闭环；**I3-1 三类 E2E 已照 U 批准集真实执行（2026-09-19，"
            "i0c-r32 入链）：6 份 → 可发布 2/6、阻断缺口 13 处、格式覆盖仅 PDF；判定未完成，"
            "阻断处置路径与 MD/DOCX 覆盖声称两项待 U 裁定**；最终版本逐类指标"
        )
        plan = plan.replace(row_old, row_new, 1)
        PLAN.write_text(plan, encoding="utf-8")
        touched.append("plan")

    return touched or ["already_patched"]


# ────────────────────────────────── 3. 验证器 r32 规则

R32_TEMPLATE = '''
if "i0c-r32" in by_id:
    i0c32 = load_json(BASE / by_id["i0c-r32"].get("file", ""))
    parent = i0c32.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r31"]["file"]
    check(parent.get("snapshot_id") == "i0c-r31", "r32 parent must be r31")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r32 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r32 parent bytes mismatch")
    binding32 = i0c32.get("binding", {})
    corrections = i0c32.get("corrections", {})
    for finding in ("I3-1_executed_approved_set", "I3-1_not_passing", "I3-1_e2e_guard_first_freeze",
                    "I3-1_guard_model_and_note_fix", "I3-1_withdrawn_archive_excluded",
                    "I3-1_freeze_utils_ordering_fix", "I3-5"):
        check(finding in corrections, f"r32 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260919-i3-1-e2e"
    pre = f"{base}/audits/20260919-i3-1-precheck"
    allowed = {
        "i3_1_e2e": __E2E__,
        "i3_1_approved_archive": __ARCH__,
        "i3_1_precheck": __PRE__,
        "i3_e2e_guard": {
            f"{base}/guards/i3-e2e.json",
            f"{audit}/i3_e2e_guard_selfcheck.py",
            f"{audit}/i3-e2e-guard-report.json",
        },
        "i3_1_freeze": {
            f"{audit}/freeze_r32.py",
            f"{base}/freezes/freeze_utils.py",
        },
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py"},
    }
    check(set(binding32) == set(allowed) | {"i3_1_archive"}, "r32 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding32.get(group, {})) == expected, f"r32 unexpected {group} scope")
    # 归档忠实性**正不变量**：每条都必须等于上一修订对该原路径的绑定（按修订号数值合并；空组合法）
    prev32: dict[str, str] = {}
    for _file in sorted(BASE.glob("i0c-r*.json"), key=revision_order):
        if _file.stem == "i0c-r32":
            continue
        for _items in (load_json(_file).get("binding") or {}).values():
            for _key, _value in _items.items():
                prev32.pop(_key, None)
                prev32[_key] = _value
    check(bool(binding32.get("i3_1_archive")), "r32 必须归档本修订覆盖的绑定文件（archive-first）")
    for key, sha in binding32.get("i3_1_archive", {}).items():
        original32 = next((p for p in prev32 if key.endswith(p)), None)
        check(original32 is not None, f"r32 归档路径无法对应到上一绑定：{key}")
        if original32 is not None:
            check(prev32[original32] == sha, f"r32 归档不是真实 pre-r32 字节：{original32}")
    # 批准集来源副本：内容寻址（文件名 = 内容 sha256）
    check(len(binding32.get("i3_1_approved_archive", {})) == 6,
          "r32 批准集来源副本应为 6 份")
    for key in binding32.get("i3_1_approved_archive", {}):
        check(key.startswith(f"{audit}/archive-approved/"), f"r32 批准集副本路径越界：{key}")
        check(digest(ROOT / key) == key.rsplit("/", 1)[-1].rsplit(".", 1)[0],
              f"r32 批准集副本内容与文件名（内容寻址）不符：{key}")
    check(not [k for k in binding32.get("i3_1_e2e", {}) if "/archive" in k],
          "r32 不得把素材副本目录（archive/、archive-approved/）混进 i3_1_e2e 组")
    # i3-e2e 守卫：身份、网络、来源、留出、自检
    guard = load_json(ROOT / f"{base}/guards/i3-e2e.json")
    check(guard.get("config_version") == 1, "r32 i3-e2e config_version 必须为整数 1")
    net = guard.get("network") or {}
    targets = net.get("allowed_targets") or []
    check(net.get("mode") == "allowlist", "r32 i3-e2e 网络必须是 allowlist")
    check(len(targets) == 1 and targets[0].get("host") == "127.0.0.1"
          and int(targets[0].get("port", 0)) == 543,
          "r32 i3-e2e 网络只允许 127.0.0.1:543（隔离沙箱）")
    srcs = guard.get("sources") or {}
    check(len(srcs.get("allowed_source_paths") or []) == 6, "r32 i3-e2e 允许来源必须为 U 批准集 6 份")
    holdout = load_json(ROOT / f"{base}/guards/i3.json")["sources"]["forbidden_roots"]
    check(sorted(srcs.get("forbidden_roots") or []) == sorted(holdout),
          "r32 i3-e2e 留出根必须与 guards/i3.json 逐字一致")
    check(not (set(srcs.get("allowed_source_paths") or []) & set(srcs.get("forbidden_roots") or [])),
          "r32 i3-e2e 允许来源不得与留出相交")
    guard_model = (guard.get("model") or {}).get("blocked_modules") or []
    i3_model = (load_json(ROOT / f"{base}/guards/i3.json").get("model") or {}).get("blocked_modules") or []
    check(sorted(guard_model) == sorted(i3_model), "r32 i3-e2e 模型封锁面必须与 i3.json 一致（不得更弱）")
    report = load_json(ROOT / f"{audit}/i3-e2e-guard-report.json")
    check(report.get("passed") is True, "r32 i3-e2e 守卫自检必须 passed")
    check(report.get("config_sha256") == digest(ROOT / f"{base}/guards/i3-e2e.json"),
          "r32 i3-e2e 自检报告与守卫字节不一致")
    check(len(report.get("cases") or []) >= 24, "r32 i3-e2e 自检用例数不足 24")
    # I3-1 真实结果：不得被读成通过
    record = load_json(ROOT / f"{audit}/i3-1-e2e-approved-set.json")
    summary = record.get("summary") or {}
    check(summary.get("sources") == 6 and summary.get("publishable") == 2,
          "r32 批准集记录应记 6 份来源、可发布 2 份")
    check(summary.get("per_class_min_2_satisfied") is False,
          "r32 必须如实登记 per_class_min_2_satisfied=false（不得读成通过）")
    check((record.get("rerun_confirmation") or {}).get("identical") is True,
          "r32 批准集记录应含一致重跑确认")
    for group, items in binding32.items():
        for rel_ in items:
            check(not rel_.startswith(("plugins/", "tests/")), f"r32 越界绑定 {rel_}")
    merge_binding(i0c_current_binding, binding32)

'''


def build_r32_block() -> str:
    return (
        R32_TEMPLATE.replace("__E2E__", py_set([f"{AUDIT_REL}/{name}" for name in E2E_FILES]))
        .replace("__ARCH__", py_set(approved_archive_files()))
        .replace("__PRE__", py_set([f"{PRE_REL}/{name}" for name in PRECHECK_FILES]))
    )


def patch_validator() -> dict:
    text = VALIDATOR.read_text(encoding="utf-8")
    if 'if "i0c-r32" in by_id:' in text:
        return {"already_patched": True}
    marker = 'check("i0c-r31" in by_id, "索引缺少 i0c-r31 条目")'
    assert marker in text
    text = text.replace(marker, marker + '\ncheck("i0c-r32" in by_id, "索引缺少 i0c-r32 条目")', 1)
    # 修订号数值排序修正（字典序会把 i0c-r9 排在 i0c-r32 之后）
    helper = '''def revision_order(path: Path) -> tuple[int, str]:
    """按修订号数值排序（字典序会让 i0c-r9 排在 i0c-r32 之后，合并会取到旧绑定）。"""

    stem = path.stem
    try:
        return (int(stem.rsplit("-r", 1)[1]), stem)
    except (IndexError, ValueError):
        return (-1, stem)


def merged_binding_from_all_but(exclude: str) -> dict:'''
    old_def = "def merged_binding_from_all_but(exclude: str) -> dict:"
    assert old_def in text
    text = text.replace(old_def, helper, 1)
    old_loop = '    for path in sorted(BASE.glob("i0c-r*.json")) + sorted(BASE.glob("i1-*.json")):'
    assert old_loop in text
    text = text.replace(
        old_loop,
        '    for path in sorted(BASE.glob("i0c-r*.json"), key=revision_order) + sorted(\n'
        '        BASE.glob("i1-*.json"), key=revision_order\n'
        '    ):',
        1,
    )
    # r27 守卫 supersession 白名单纳入 r32
    text = text.replace(
        'for sid in ("i0c-r28", "i0c-r29", "i0c-r30", "i0c-r31"):',
        'for sid in ("i0c-r28", "i0c-r29", "i0c-r30", "i0c-r31", "i0c-r32"):',
        1,
    )
    anchor = "# 最新修订绑定优先（supersession）：i0c-r2..r31 显式重绑的路径改由合并后的"
    assert anchor in text
    text = text.replace(anchor, build_r32_block() + anchor.replace("..r31", "..r32"), 1)
    # 成功消息
    tail = '''("; r31 I3-2 tail closure (prose holdout guarded, mapping rule-verified, warnings accepted) verified" if "i0c-r31" in by_id else ""))'''
    assert tail in text
    text = text.replace(
        tail,
        '''("; r31 I3-2 tail closure (prose holdout guarded, mapping rule-verified, warnings accepted) verified" if "i0c-r31" in by_id else "")
      + ("; r32 I3-1 three-class dev E2E on the U-approved set filed (6 sources -> 2 publishable, 13 blocking gaps, per_class_min_2 NOT satisfied, i3-e2e guard + selfcheck frozen)" if "i0c-r32" in by_id else ""))''',
        1,
    )
    # 顶部 docstring 追加 r32 条目
    doc_tail = '"""\nfrom __future__ import annotations'
    assert doc_tail in text
    text = text.replace(
        doc_tail,
        "14. i0c-r32 = **I3-1 三类开发 E2E（照 U 批准集）首次入链**：绑 I3-1 审计文本产物（**不含** `archive/`\n"
        "   素材副本）、批准集来源副本（内容寻址 `archive-approved/`）、`i3-e2e` 阶段守卫与其合成反例自检、\n"
        "   环境预检报告、台账与验证器；**不得**出现 ``plugins/``／``tests/`` 绑定。同时修正归档合并顺序\n"
        "   （按修订号数值）并首冻 `guards/i3-e2e.json`（model 封锁面已对齐 `guards/i3.json`）。\n"
        '"""\nfrom __future__ import annotations',
        1,
    )
    VALIDATOR.write_text(text, encoding="utf-8")
    import ast

    ast.parse(text)
    return {"already_patched": False, "sha256": digest(VALIDATOR)}


FREEZE_UTILS_NOTE = '''def revision_order(path: Path) -> tuple[int, str]:
    """按**修订号数值**排序：字典序会把 ``i0c-r9`` 排在 ``i0c-r32`` 之后，合并会取到旧绑定。"""

    stem = path.stem
    try:
        return (int(stem.rsplit("-r", 1)[1]), stem)
    except (IndexError, ValueError):
        return (-1, stem)


def merged_binding('''


def patch_freeze_utils() -> dict:
    text = FREEZE_UTILS.read_text(encoding="utf-8")
    if "def revision_order(" in text:
        return {"already_patched": True}
    old_def = "def merged_binding("
    assert old_def in text
    text = text.replace(old_def, FREEZE_UTILS_NOTE, 1)
    old_loop = '    paths = sorted(Path(freezes_dir).glob("i0c-r*.json")) + sorted(Path(freezes_dir).glob("i1-*.json"))'
    assert old_loop in text
    text = text.replace(
        old_loop,
        '    paths = sorted(Path(freezes_dir).glob("i0c-r*.json"), key=revision_order) + sorted(\n'
        '        Path(freezes_dir).glob("i1-*.json"), key=revision_order\n'
        '    )',
        1,
    )
    FREEZE_UTILS.write_text(text, encoding="utf-8")
    import ast

    ast.parse(text)
    return {"already_patched": False, "sha256": digest(FREEZE_UTILS)}


# ────────────────────────────────── 4. 归档（archive-first）+ r32 快照


def archive(relative: str) -> dict:
    target = BEFORE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.is_file():
        shutil.copy2(ROOT / relative, target)
    expected = previous_binding().get(relative)
    actual = digest(target)
    return {
        "path": relative,
        "archived_as": rel(target),
        "sha256": actual,
        "matches_previous_binding": expected is None or expected == actual,
    }


def build_r32(archived: list[dict], guard_result: dict, selfcheck: dict, docs: list[str]) -> dict:
    archive = approved_archive_files()
    return {
        "snapshot_id": "i0c-r32",
        "revision": "r32",
        "phase": "i0c",
        "task": (
            "I3-1 three-class dev E2E (U-approved set) filed: ledger backfill + I3-1 audit artifacts + "
            "approved-set source copies (content-addressed) + i3-e2e stage guard and its synthetic-counterexample "
            "selfcheck + environment precheck bound; e2e guard model denylist aligned with guards/i3.json and "
            "archive fidelity merge switched to numeric revision order"
        ),
        "parent_snapshot": {
            "snapshot_id": "i0c-r31",
            "path": rel(FREEZES / "i0c-r31.json"),
            "sha256": digest(FREEZES / "i0c-r31.json"),
        },
        "binding": {
            "i3_1_e2e": {f"{AUDIT_REL}/{name}": digest(ROOT / AUDIT_REL / name) for name in E2E_FILES},
            "i3_1_approved_archive": {path: digest(ROOT / path) for path in archive},
            "i3_1_precheck": {f"{PRE_REL}/{name}": digest(PRECHECK / name) for name in PRECHECK_FILES},
            "i3_e2e_guard": {
                f"{BASE_REL}/guards/i3-e2e.json": digest(GUARD),
                f"{AUDIT_REL}/i3_e2e_guard_selfcheck.py": digest(SELFCHECK),
                f"{AUDIT_REL}/i3-e2e-guard-report.json": digest(REPORT),
            },
            "i3_1_freeze": {
                f"{AUDIT_REL}/freeze_r32.py": digest(HERE / "freeze_r32.py"),
                f"{BASE_REL}/freezes/freeze_utils.py": digest(FREEZE_UTILS),
            },
            "i3_1_archive": {item["archived_as"]: item["sha256"] for item in archived},
            "docs": {rel(TASKS): digest(TASKS), rel(PLAN): digest(PLAN)},
            "freeze_validator": {rel(VALIDATOR): digest(VALIDATOR)},
        },
        "corrections": {
            "I3-1_executed_approved_set": (
                "I3-1 三类开发 E2E 已**照 U 批准集**（i0a2 dev_selection_approved，6 份 PDF）真实执行：6 份 build 全成功"
                "（4305 单元/767 切块）；可发布 2/6（company 0/2、industry 1/2、macro 1/2）；阻断缺口 13 处；"
                "检索/取证/审计链路全通；干净沙箱重跑逐源复现。Agent 自选换料范围已撤回并重置沙箱。"
            ),
            "I3-1_not_passing": (
                "**I3-1 未完成，不得读成通过**：per_class_min_2_satisfied=false（现行门 + 现行裁定下『三类每类≥2 份』无解，"
                "阻断缺口无处置路径）；格式覆盖仅 PDF（DOCX/MD 准入口径 0 份，§12.1 未满足）。两项待 U 裁定；"
                "本轮初步结果不得直接放行 I4"
            ),
            "I3-1_e2e_guard_first_freeze": (
                "guards/i3-e2e.json 首次冻结（独立于 guards/i3.json）：config_version=1、网络 allowlist 仅 127.0.0.1:543、"
                "allowed_source_paths = 批准集 6 份、forbidden_roots 与 i3.json 逐字一致；自检报告 "
                "i3-e2e-guard-report.json（合成反例 24/24，write-once）一并入链"
            ),
            "I3-1_guard_model_and_note_fix": (
                "**首冻前修正两处**（非静默改动）：① i3-e2e 守卫 model 封锁面原只拦 openai，自检实测 "
                "`import anthropic` 与 `import plugins.corpus.material_semantics` **未被拒** → 已对齐 guards/i3.json 的 "
                "4 个模块 + 前缀 + 3 个投毒 env 后重跑自检 24/24（更严，E2E 期间 0 次模型调用，不影响已记录结果）；"
                "② note 文案去重（apply_docx_coverage/apply_retraction 多次追加留下同一行重复 4 次），"
                "操作字段 config_version/phase/network/sources 逐字未变（生成器内断言）"
            ),
            "I3-1_ledger_backfill": (
                "台账回填 I3-1 真实结果：tasks.md §3.6 章节 + I3-1 任务行 + 导航行；plan.md r32 优先状态 + I3-1 详情节 + "
                "I3 状态行。此前两份台账均写『I3-1 未执行』，与事实不符（原记录的 F5 交付缺口）"
            ),
            "I3-1_withdrawn_archive_excluded": (
                "`archive/`（撤回的自选/换料素材副本 12 PDF + 2 MD + 1 DOCX）**不入链**：它们属已撤回范围，"
                "其留存与处置由 i3-1-retraction-record.* 记录；`archive-approved/`（批准集 6 份，内容寻址）入链，"
                "作为 E2E 所用来源字节的身份凭据"
            ),
            "I3-1_freeze_utils_ordering_fix": (
                "**机制缺陷修正**：freeze_utils.merged_binding/previous_binding 与验证器 merged_binding_from_all_but 原按"
                "**字典序**合并修订（'i0c-r9' 排在 'i0c-r32' 之后）→ 归档忠实性断言对 docs/plan 等早期即被绑定的路径取到旧值，"
                "会把真实归档误判为不忠实（实测：字典序取到 r9 的 6dfe7612…，数值序取到 r31 的 2c52d0fa…）。r32 起改为按"
                "**修订号数值**排序，与验证器主流程的合并顺序一致；r31 的 i3_2_archive 为空组、r28 只判存在性、r29 仅打印 "
                "NOTE，历史修订块语义不受影响"
            ),
            "I3-1_record_pending_field": (
                "i3-1-e2e-approved-set.json 的 `pending.sandbox_data_reset` 字段写于沙箱不可用时；该事项随后已完成"
                "（teardown residue=0 → 重建 → 重跑，见 rerun_confirmation）。字段**原样保留**供审计，语义以 "
                "rerun_confirmation 与 i3-1-e2e-approved-set-rerun.* 为准"
            ),
            "I3-5": (
                "I3-5 真实非回归（旧检索/财务/公式/客户表/正文/宏观）与 I3-3/I3-4/I3-6/I3-7 仍未执行："
                "需原库 5432 + 预算授权 + 最终版本冻结；真实答案语义验收未授权，not_run"
            ),
        },
        "created_at": datetime.now(timezone.utc).isoformat(),
        "notes": [
            "零模型、零生产库写入；本轮改动限于台账、i3-e2e 守卫（首冻 + model 封锁对齐）、验证器与归档顺序修正。",
            f"i3-e2e 守卫自检：cases={selfcheck['cases']} passed={selfcheck['passed']}；"
            f"guard sha256={guard_result['sha256'][:12]}…；台账回填={docs}。",
            "**I3-1 未完成**：per_class_min_2_satisfied=false 与 §12.1 格式覆盖未满足均如实登记，"
            "不得用本修订代替业务通过或 I4 放行。",
        ],
    }


def main() -> int:
    # archive-first：任何写入之前归档本修订将覆盖的绑定路径
    planned = [rel(TASKS), rel(PLAN), rel(VALIDATOR), rel(FREEZE_UTILS)]
    archived = [archive(path) for path in planned]
    unfaithful = [item["path"] for item in archived if not item["matches_previous_binding"]]
    if unfaithful:
        raise SystemExit(f"归档与上一修订绑定不符（先改后归档？）：{unfaithful}")

    guard_result = fix_guard()
    selfcheck = run_selfcheck()
    docs = patch_docs()
    validator = patch_validator()
    utils = patch_freeze_utils()

    r32 = build_r32(archived, guard_result, selfcheck, docs)
    R32.write_text(json.dumps(r32, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = load_json(MANIFEST)
    manifest["snapshots"] = [s for s in manifest["snapshots"] if s.get("snapshot_id") != "i0c-r32"] + [
        {
            "snapshot_id": "i0c-r32",
            "file": "i0c-r32.json",
            "sha256": digest(R32),
            "parent_snapshot_id": "i0c-r31",
            "created_at": r32["created_at"],
        }
    ]
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    def run(cmd: list[str]) -> int:
        return subprocess.run(cmd, capture_output=True, text=True, cwd=str(ROOT), check=False).returncode

    chain = run([sys.executable, str(VALIDATOR)])
    gate = run([sys.executable, str(GATE)])
    review = run([sys.executable, str(REVIEW), "--no-write"])
    chain_after = run([sys.executable, str(VALIDATOR)])
    chain_result = subprocess.run(
        [sys.executable, str(VALIDATOR)], capture_output=True, text=True, cwd=str(ROOT), check=False
    )
    print(
        json.dumps(
            {
                "archived": [{k: v for k, v in item.items() if k != "archived_as"} for item in archived],
                "guard": guard_result,
                "selfcheck": selfcheck,
                "docs": docs,
                "validator": validator,
                "freeze_utils": utils,
                "r32_sha256": digest(R32),
                "chain": chain,
                "gate": gate,
                "review": review,
                "chain_after": chain_after,
                "chain_tail": chain_result.stdout.strip().splitlines()[-1][-260:],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if chain == 0 and gate == 0 and chain_after == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
