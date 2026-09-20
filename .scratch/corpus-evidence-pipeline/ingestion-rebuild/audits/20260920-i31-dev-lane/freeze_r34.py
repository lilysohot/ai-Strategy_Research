"""冻结 i0c-r34（I3-1 第二轮：dev lane 纳入 MD/DOCX）→ 复跑冻结链门。

顺序（重要，先例 r33 / M5 / I3-2）：
1. **先归档**本轮覆盖的绑定路径的**改动前字节**，并逐条与合并后的上一修订绑定比对
   （archive-first；任一不符即拒绝冻结，不留假归档）。
   - 4 个文件的改动前字节 = git HEAD（已核对与绑定一致）：3 份代码 + 架构文档；
   - 4 个文件的改动前字节由本脚本按「编辑逆向」精确还原（tasks/plan/tests/守卫），
     还原后逐条断言 sha256 == 上一绑定，否则中止。
2. 给验证器加 r34 规则；写 r34 + 索引；
3. 跑冻结链门（validate_i0c_freeze.py），exit 0 即收口。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-dev-lane/freeze_r34.py
"""

from __future__ import annotations

import ast
import hashlib
import json
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
FREEZES = BASE / "freezes"
VALIDATOR = FREEZES / "validate_i0c_freeze.py"
MANIFEST = FREEZES / "freeze-manifest.json"
R34 = FREEZES / "i0c-r34.json"
BEFORE = HERE / "before-r34"
DEV_POLICY = HERE / "admission-policy-dev.json"
DEV_MANIFEST = HERE / "dev-scope-manifest.json"
PREFLIGHT = HERE / "preflight_scope_check.py"
PREFLIGHT_JSON = HERE / "preflight-scope-check.json"
PREFLIGHT_FAILCLOSED = HERE / "preflight-scope-check.failclosed-no-dev-lane.json"
SELFCHECK = HERE / "i3_e2e_guard_selfcheck.py"
GUARD_REPORT = HERE / "i3-e2e-guard-report.json"
RUNNER = HERE / "run_i3_1_dev_lane.py"
E2E_JSON = HERE / "i3-1-dev-lane-e2e.json"
E2E_MD = HERE / "i3-1-dev-lane-e2e.md"
VERIFIER = HERE / "verify_dev_lane_admissions.py"
VERIFY_JSON = HERE / "dev-lane-admission-verification.json"
ARCHIVE_DIR = HERE / "archive-dev-lane"
GUARD = BASE / "guards/i3-e2e.json"
TASKS = ROOT / "docs/plan/corpus-ingestion-rebuild-tasks.md"
PLAN = ROOT / "docs/plan/claims-market-closed-loop-plan.md"
ARCH = ROOT / "docs/plan/corpus-ingestion-rebuild-architecture.md"
CODE = [
    ROOT / "plugins/corpus/preparation/admission.py",
    ROOT / "plugins/corpus/preparation/contract.py",
    ROOT / "plugins/corpus/cli.py",
]
TESTS = ROOT / "tests/test_corpus_preparation_admission.py"
BASE_REL = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
AUDIT_REL = f"{BASE_REL}/audits/20260920-i31-dev-lane"

# --- 改动前字节还原：git HEAD 可还原的路径（已核对绑定 == HEAD） ---
GIT_RESTORE = [
    "plugins/corpus/preparation/admission.py",
    "plugins/corpus/preparation/contract.py",
    "plugins/corpus/cli.py",
    "docs/plan/corpus-ingestion-rebuild-architecture.md",
]

# --- 其余路径：按「编辑逆向」精确还原（new → old）；None 表示标记式截断 ---
REVERSES: list[tuple[str, object, object]] = [
    # tests/test_corpus_preparation_admission.py（3 处）
    (
        "tests/test_corpus_preparation_admission.py",
        "from plugins.corpus.preparation.admission import (\n    POLICY_REV_V1,\n    POLICY_REV_V2_DEV,\n    PROBE_REV,\n    RULE_REV,\n    AdmissionError,\n    AdmissionPolicy,\n    ProbeInput,\n    ProbeValue,\n    SourceDescriptor,\n    decide_admission,\n    load_admission_policy,\n    probe_features,\n)\nfrom plugins.corpus.preparation.contract import (\n    Admission,\n    AdmissionDecision,\n    ContractError,\n    DocumentFormat,\n    MaterialType,\n    ResearchDomain,\n    ReviewDecision,\n    ReviewedDecision,\n)",
        "from plugins.corpus.preparation.admission import (\n    POLICY_REV_V1,\n    PROBE_REV,\n    RULE_REV,\n    AdmissionError,\n    AdmissionPolicy,\n    ProbeInput,\n    ProbeValue,\n    SourceDescriptor,\n    decide_admission,\n    load_admission_policy,\n    probe_features,\n)\nfrom plugins.corpus.preparation.contract import (\n    AdmissionDecision,\n    DocumentFormat,\n    MaterialType,\n    ResearchDomain,\n    ReviewDecision,\n    ReviewedDecision,\n)",
    ),
    (
        "tests/test_corpus_preparation_admission.py",
        'DEV_MD_SID = hashlib.sha256((REPO / DEV_MD_PATH).read_bytes()).hexdigest()\nDEV_DOCX_SID = hashlib.sha256((REPO / DEV_DOCX_PATH).read_bytes()).hexdigest()',
        'DEV_MD_SID = _sid("工业富联_投委会决策报告_20260829.md")\nDEV_DOCX_SID = _sid("9月8日 光模块技术演进与供应链重构.docx")',
    ),
    (
        "tests/test_corpus_preparation_admission.py",
        "TRUNCATE_AT",
        "\n\n\n# --- dev lane（U 2026-09-20 裁决）：只对 dev 构建生效，生产 in_scope 判定不变 ---",
    ),
    # docs/plan/corpus-ingestion-rebuild-tasks.md（3 处）
    (
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
        "`per_class_min_2` 未满足，判定**未完成**，待 U 裁定缺口处置路径与 MD/DOCX 覆盖声称。**2026-09-20 第二轮（U 裁决新建 dev lane，i0c-r34 入链）**：dev lane 纳入 U 指定 2 份（`工业富联_投委会决策报告_20260829.md` / `9月8日 光模块…docx`，材料类型如实为 `internal_committee_report` / `internal_unattributed`），与批准集 6 份合计 8 份真跑 → 可发布 **4/8**；**架构 §12.1 格式门满足=true**（pdf 2/6、docx 1/1、md 1/1 均有可发布样本）；逐类可发布 company 1/3、industry 2/3、macro 1/2 → **『每类≥2』仍为 False（裁定①未解，company 0/2 的 13 处阻断缺口依旧）**；证据 `audits/20260920-i31-dev-lane/i3-1-dev-lane-e2e.{json,md}`；生产判定不变由 dev lane 反例族 + 预检 fail-closed 反例双证",
        "`per_class_min_2` 未满足，判定**未完成**，待 U 裁定缺口处置路径与 MD/DOCX 覆盖声称",
    ),
    (
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
        "；**产出 `format_availability` 对账表（架构 §12.1：声称格式 × 已准入可得性，缺格须显式处置）**",
        "",
    ),
    (
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
        "；**缺格式格未处置（补料工单或 U 显式改声称）不得进 I3-1 取样**",
        "",
    ),
    (
        "docs/plan/corpus-ingestion-rebuild-tasks.md",
        "\n| I3-1 第二轮 dev lane | [U 裁决 dev lane 纳入 MD/DOCX（8 份 → 可发布 4/8、**§12.1 格式门 true**、`每类≥2` 仍 false）；生产判定不变由 dev lane 反例族 + 预检 fail-closed 反例双证；i0c-r34 入链](claims-market-closed-loop-plan.md#i3-1-dev-lane) |",
        "",
    ),
    # docs/plan/claims-market-closed-loop-plan.md（2 处）
    (
        "docs/plan/claims-market-closed-loop-plan.md",
        "**I3-1 已真跑两轮：①照 U 批准集 6 份（2026-09-19，i0c-r32）→ 可发布 2/6、阻断缺口 13 处、格式覆盖仅 PDF；②dev lane 纳入 MD/DOCX（2026-09-20，i0c-r34）→ 8 份可发布 4/8、`pdf 2/6 + docx 1/1 + md 1/1` 使**架构 §12.1 格式门=true**、新增检索命中 工业富联/光模块、审计冲突 0，但 `per_class_min_2` 仍为 **false**。裁定②已按「dev lane + 类型如实」口径满足（非生产放宽）；**裁定①（阻断缺口处置路径）未解**，I3-1 判定仍**未完成**（company 0/2）**；",
        "**I3-1 三类 E2E 已照 U 批准集真实执行（2026-09-19，i0c-r32 入链）：6 份 → 可发布 2/6、阻断缺口 13 处、格式覆盖仅 PDF；判定未完成，阻断处置路径与 MD/DOCX 覆盖声称两项待 U 裁定**；",
    ),
    (
        "docs/plan/claims-market-closed-loop-plan.md",
        "SECTION_CUT",
        '\n\n<a id="i3-1-dev-lane"></a>',
    ),
    # guards/i3-e2e.json（2 处）
    (
        f"{BASE_REL}/guards/i3-e2e.json",
        "  \"note\": \"I3-1 三类开发 E2E 阶段守卫（独立于 guards/i3.json：本阶段允许真实读取开发来源与隔离 PG 写入）。允许路径历史：预检 6 → 换料自选 8/15 → **2026-09-19 深夜撤回 Agent 自选范围**，重置为 U 2026-09-15 批准的 dev_selection_approved 6 份（i0a2-adjudicated-20260915.json）→ **2026-09-20 U 裁决新建 dev lane（只对 dev 生效）**，追加 U 指定 2 份（MD 内部投委会报告 + DOCX 无署名内部材料），合计 8 份，授权清单见 audits/20260920-i31-dev-lane/admission-policy-dev.json。启用条件：① 开发范围经 U 批准并生成 dev-scope-manifest.json；② 隔离目标可达（127.0.0.1:543 的 corpus-db 容器，库名 i2_sandbox_corpus）；③ 守卫自检通过（i3-e2e-guard-report.json 合成反例全过）。2026-09-19（r32 首冻）：model 封锁面对齐 guards/i3.json（此前只拦 openai，自检实测 anthropic / material_semantics 未被拒），note 去重。2026-09-20：允许路径 6→8（dev lane 新产物），自检报告重生成于 audits/20260920-i31-dev-lane/（旧报告 write-once 保留）。\",",
        "  \"note\": \"I3-1 三类开发 E2E 阶段守卫（独立于 guards/i3.json：本阶段允许真实读取开发来源与隔离 PG 写入）。允许路径历史：预检 6 → 换料自选 8/15 → **2026-09-19 深夜撤回 Agent 自选范围**，重置为 U 2026-09-15 批准的 dev_selection_approved 6 份（i0a2-adjudicated-20260915.json）。启用条件：① 开发范围经 U 批准并生成 dev-scope-manifest.json；② 隔离目标可达（127.0.0.1:543 的 corpus-db 容器，库名 i2_sandbox_corpus）；③ 守卫自检通过（i3-e2e-guard-report.json 合成反例全过）。2026-09-19（r32 首冻）：model 封锁面对齐 guards/i3.json（此前只拦 openai，自检实测 anthropic / material_semantics 未被拒），note 去重。\",",
    ),
    (
        f"{BASE_REL}/guards/i3-e2e.json",
        '      "data/corpus/2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据点评-强非农降低了年内加息的门槛-6fc25e24.pdf",\n      "data/corpus/工业富联_投委会决策报告_20260829.md",\n      "data/corpus/9月8日 光模块技术演进与供应链重构：从1.6T到3.2T的路径、格局.docx"\n    ],',
        '      "data/corpus/2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据点评-强非农降低了年内加息的门槛-6fc25e24.pdf"\n    ],',
    ),
]

R34_BLOCK = '''
if "i0c-r34" in by_id:
    i0c34 = load_json(BASE / by_id["i0c-r34"].get("file", ""))
    parent = i0c34.get("parent_snapshot", {})
    expected_parent = BASE / by_id["i0c-r33"]["file"]
    check(parent.get("snapshot_id") == "i0c-r33", "r34 parent must be r33")
    check(parent.get("path") == str(expected_parent.relative_to(ROOT)), "r34 parent path mismatch")
    check(parent.get("sha256") == digest(expected_parent), "r34 parent bytes mismatch")
    binding34 = i0c34.get("binding", {})
    corrections = i0c34.get("corrections", {})
    for finding in ("I3-1_format_gate", "I3-1_dev_lane_design", "I3-1_per_class_still_false",
                    "I3-1_production_unchanged_evidence", "I3-1_contract_policy_bound_material",
                    "I3-1_supersedes_r32_guard_scope", "I3-1_supersedes_r32_selfcheck",
                    "I3-1_i1r4_supersession_fix", "I3-1_archive_discipline",
                    "I3-1_review_evidence"):
        check(finding in corrections, f"r34 missing correction {finding}")
    base = ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
    audit = f"{base}/audits/20260920-i31-dev-lane"
    allowed = {
        "i3_1_dev_lane_policy": {f"{audit}/admission-policy-dev.json",
                                 f"{audit}/dev-scope-manifest.json"},
        "i3_1_dev_lane_preflight": {f"{audit}/preflight_scope_check.py",
                                    f"{audit}/preflight-scope-check.json",
                                    f"{audit}/preflight-scope-check.failclosed-no-dev-lane.json"},
        "i3_1_dev_lane_guard": {f"{audit}/i3_e2e_guard_selfcheck.py",
                                f"{audit}/i3-e2e-guard-report.json",
                                f"{base}/guards/i3-e2e.json"},
        "i3_1_dev_lane_run": {f"{audit}/run_i3_1_dev_lane.py",
                              f"{audit}/i3-1-dev-lane-e2e.json",
                              f"{audit}/i3-1-dev-lane-e2e.md",
                              f"{audit}/verify_dev_lane_admissions.py",
                              f"{audit}/dev-lane-admission-verification.json",
                              f"{audit}/freeze_r34.py"},
        "i3_1_dev_lane_review": {f"{audit}/run_review.py",
                                 f"{audit}/test_dev_lane_probes.py",
                                 f"{audit}/freeze-validation.txt",
                                 f"{audit}/baseline.txt",
                                 f"{audit}/independent-probes-r33.txt",
                                 f"{audit}/independent-probes-dev-lane.txt",
                                 f"{audit}/m5-evidence-recheck.json"},
        "i3_1_dev_lane_code": {"plugins/corpus/preparation/admission.py",
                               "plugins/corpus/preparation/contract.py",
                               "plugins/corpus/cli.py",
                               "tests/test_corpus_preparation_admission.py"},
        "docs": {"docs/plan/corpus-ingestion-rebuild-tasks.md",
                 "docs/plan/claims-market-closed-loop-plan.md",
                 "docs/plan/corpus-ingestion-rebuild-architecture.md"},
        "freeze_validator": {f"{base}/freezes/validate_i0c_freeze.py"},
    }
    check(set(binding34) == set(allowed) | {"i3_1_dev_lane_archive", "i3_1_dev_lane_sources"},
          "r34 binding groups mismatch")
    for group, expected in allowed.items():
        check(set(binding34.get(group, {})) == expected, f"r34 unexpected {group} scope")
    prev34 = merged_binding_upto_revision(33)
    for _key, _value in merged_binding_from_all_but("i0c-r34").items():
        prev34.setdefault(_key, _value)
    check(bool(binding34.get("i3_1_dev_lane_archive")), "r34 必须归档本修订覆盖的绑定文件（archive-first）")
    for key, sha in binding34.get("i3_1_dev_lane_archive", {}).items():
        original = next((p for p in prev34 if key.endswith(p)), None)
        check(original is not None, f"r34 归档路径无法对应到上一绑定：{key}")
        if original is not None:
            check(prev34[original] == sha, f"r34 归档不是真实 pre-r34 字节：{original}")
    for key, sha in binding34.get("i3_1_dev_lane_sources", {}).items():
        check(key.startswith(f"{audit}/archive-dev-lane/"), f"r34 来源副本路径越界：{key}")
    e2e = load_json(ROOT / f"{audit}/i3-1-dev-lane-e2e.json")
    summary = e2e.get("summary", {})
    check(summary.get("format_gate_section_12_1_satisfied") is True,
          "r34 需要 §12.1 格式门为真（三格式均有可发布样本）")
    check(summary.get("per_class_min_2_satisfied") is False,
          "r34 必须如实登记『每类≥2』仍不满足（裁定①未解）")
    check(summary.get("audit_conflicts") == [], "r34 需要审计链零冲突")
    verification = load_json(ROOT / f"{audit}/dev-lane-admission-verification.json")
    check(verification.get("verdict") == "PASS", "r34 需要 dev lane 落库核验 PASS（材料类型如实）")
    mat = {row.get("material_type") for row in verification.get("rows", [])}
    check("research_report" not in mat, "r34 材料类型不得被伪写为 research_report")
    preflight34 = load_json(ROOT / f"{audit}/preflight-scope-check.json")
    check(preflight34.get("summary", {}).get("verdict") == "PASS", "r34 预检 PASS 缺失")
    failclosed = load_json(ROOT / f"{audit}/preflight-scope-check.failclosed-no-dev-lane.json")
    check(failclosed.get("summary", {}).get("verdict") == "FAIL",
          "r34 必须有 fail-closed 反例（不给 --dev-lane 判 FAIL）")
    guard_report = load_json(ROOT / f"{audit}/i3-e2e-guard-report.json")
    check(guard_report.get("passed") is True, "r34 守卫自检必须通过")
    policy = load_json(ROOT / f"{audit}/admission-policy-dev.json")
    check(policy.get("scope") == "dev" and policy.get("production_in_scope_unchanged") is True,
          "r34 dev 政策必须声明 dev-only 且生产判定不变")
    _review_logs = {
        _name: (ROOT / f"{audit}/{_name}").read_text(encoding="utf-8")
        for _name in ("freeze-validation.txt", "baseline.txt",
                      "independent-probes-r33.txt", "independent-probes-dev-lane.txt")
    }
    check(
        all(
            _text.rstrip().endswith("exit=0")
            for _name, _text in _review_logs.items()
            if _name != "freeze-validation.txt"
        ),
        "r34 复核 pytest 日志必须 exit=0（评分器基线 + 两组独立反例）",
    )
    # 子串 "exit=0" 会被失败文案自身命中（假绿），故只用末行判定；
    # 冻结链门的绿性由本验证器自身的 in-process 检查承担，日志只作入链留证。
    check("r34" in _review_logs["freeze-validation.txt"],
          "r34 复核日志须来自 r34 感知的冻结链门运行")
    check("failed" not in _review_logs["independent-probes-dev-lane.txt"].lower(),
          "r34 dev lane 独立反例不得有失败项")
    _recheck = load_json(ROOT / f"{audit}/m5-evidence-recheck.json")
    check(not _recheck.get("misses") and not _recheck.get("errors"),
          "r34 M5 证据只读复算必须零 miss / 零 error")
    merge_binding(i0c_current_binding, binding34)

'''


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def revision_order(path: Path) -> tuple[int, str]:
    stem = path.stem
    try:
        return (int(stem.rsplit("-r", 1)[1]), stem)
    except (IndexError, ValueError):
        return (-1, stem)


def merged_binding(exclude: tuple[str, ...] = ()) -> dict[str, str]:
    current: dict[str, str] = {}
    for path in sorted(FREEZES.glob("i0c-r*.json"), key=revision_order) + sorted(
        FREEZES.glob("i1-*.json"), key=revision_order
    ):
        if path.stem in exclude:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for items in (data.get("binding") or {}).values():
            for key, value in items.items():
                current.pop(key, None)
                current[key] = value
    return current


def merged_binding_upto_revision(max_revision: int) -> dict[str, str]:
    """只合并**修订号 <= max_revision** 的 i0c 绑定（时间稳定，不被后续修订重绑污染）。

    必要性：``merged_binding_from_all_but`` 会把 *所有* 快照合并，于是 r34 一旦存在，
    r33 块的归档忠实性检查会随后续修订变化而失真（同 r33 修 r32 的机制缺陷）。另注意
    字典序/合并序问题：``i1-*`` 排在 ``i0c-*`` 之后，会把 i0c-r5/r6 绑定的路径覆盖成
    i1-r4 的**陈旧**值，故 i0c 在效绑定必须只按 i0c 链计算。
    """

    current: dict[str, str] = {}
    for path in sorted(FREEZES.glob("i0c-r*.json"), key=revision_order):
        if revision_order(path)[0] > max_revision:
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for items in (data.get("binding") or {}).values():
            for key, value in items.items():
                current.pop(key, None)
                current[key] = value
    return current


def previous_effective_binding() -> dict[str, str]:
    """在效的「上一修订绑定」：i0c ≤33 合并值优先，缺失路径回落全量合并。

    - 只在 i0c 链上绑定的路径（如 guards/i3-e2e.json、docs/、tests/test_…_admission.py）
      取 i0c ≤33 的值——这是验证器 i0c-current 实际核对的值；
    - 只被 i1-* 绑定的路径（plugins/corpus/preparation/admission.py、contract.py）
      才回落到全量合并（i1-r4）。
    """

    effective = merged_binding_upto_revision(33)
    for key, value in merged_binding(exclude=("i0c-r34",)).items():
        effective.setdefault(key, value)
    return effective


def must_replace(text: str, old: str, new: str) -> str:
    assert text.count(old) == 1, f"锚点不唯一或缺失：{old[:60]!r}"
    return text.replace(old, new, 1)


def reconstruct() -> dict[str, bytes]:
    """产出每个被覆盖绑定路径的 pre-r34 字节。"""
    originals: dict[str, bytes] = {}
    for relative in GIT_RESTORE:
        proc = subprocess.run(
            ["git", "show", f"HEAD:{relative}"], cwd=str(ROOT), capture_output=True, check=False
        )
        assert proc.returncode == 0, f"git 无法还原 {relative}"
        originals[relative] = proc.stdout
    grouped: dict[str, list[tuple[object, object]]] = {}
    for path, new, old in REVERSES:
        grouped.setdefault(path, []).append((new, old))
    for relative, ops in grouped.items():
        text = (ROOT / relative).read_text(encoding="utf-8")
        for new, old in ops:
            if new == "TRUNCATE_AT":
                marker = str(old)
                assert marker in text, f"{relative} 缺少截断标记"
                text = text[: text.index(marker)] + "\n"
                continue
            if new == "SECTION_CUT":
                marker = str(old)
                assert marker in text, f"{relative} 缺少节标记"
                start = text.index(marker)
                end = text.index("\n\n**r31 历史状态**", start)
                text = text[:start] + text[end:]
                continue
            count = text.count(str(new))
            assert count == 1, f"{relative} 逆向锚点命中 {count} 次：{str(new)[:60]!r}"
            text = text.replace(str(new), str(old), 1)
        # 结尾保证与原文件一致（文件均以换行结尾）
        if not text.endswith("\n"):
            text += "\n"
        originals[relative] = text.encode("utf-8")
    return originals


def archive(originals: dict[str, bytes], previous: dict[str, str]) -> list[dict]:
    records: list[dict] = []
    for relative, payload in originals.items():
        target = BEFORE / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(payload)
        actual = hashlib.sha256(payload).hexdigest()
        expected = previous.get(relative)
        records.append(
            {
                "path": relative,
                "archived_as": str(target.relative_to(ROOT)),
                "sha256": actual,
                "matches_previous_binding": expected is not None and expected == actual,
                "previous_binding": expected,
            }
        )
    return records


HELPER = '''
def merged_binding_upto_revision(max_revision: int) -> dict:
    """只合并**修订号 <= max_revision** 的 i0c 绑定（时间稳定；不被后续修订重绑污染）。

    r34 引入：``merged_binding_from_all_but`` 会合并全部快照，导致历史块的归档忠实性检查
    随后续修订失真（r33 已用同法修 r32）。i0c 在效绑定也必须只按 i0c 链计算——``i1-*``
    在合并序上晚于 ``i0c-*``，会把 i0c-r5/r6 绑定的路径覆盖成 i1-r4 的陈旧值。
    """

    current: dict = {}
    for path in sorted(BASE.glob("i0c-r*.json"), key=revision_order):
        if revision_order(path)[0] > max_revision:
            continue
        data = load_json(path)
        for items in (data.get("binding") or {}).values():
            for key, value in items.items():
                current.pop(key, None)
                current[key] = value
    return current

'''


BROKEN_R32_TAIL = '''    srcs = guard.get("sources") or {}
    expected_guard_sources = 6
    
'''

R32_TAIL = '''    srcs = guard.get("sources") or {}
    expected_guard_sources = 6
    if "i0c-r34" in by_id:
        _dev_policy = load_json(
            ROOT / f"{base}/audits/20260920-i31-dev-lane/admission-policy-dev.json"
        )
        _lane_paths = {
            item.get("path")
            for item in (_dev_policy.get("dev_lane") or {}).get("sources") or []
        }
        _approved_paths = {
            item.get("path")
            for item in load_json(
                ROOT / f"{base}/i0a2-adjudicated-20260915.json"
            )["dev_selection_approved"]
        }
        expected_guard_sources = len(_approved_paths) + len(_lane_paths)
        check(set(srcs.get("allowed_source_paths") or []) == _approved_paths | _lane_paths,
              "r32 i3-e2e 允许来源在 r34 下应为批准集 + dev lane 清单（逐条一致）")
    check(len(srcs.get("allowed_source_paths") or []) == expected_guard_sources,
          "r32 i3-e2e 允许来源必须为 U 批准集 6 份（r34 后为 6 + dev lane）")
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
    _guard_sha = digest(ROOT / f"{base}/guards/i3-e2e.json")
    if "i0c-r34" in by_id:
        _new_report = load_json(
            ROOT / f"{base}/audits/20260920-i31-dev-lane/i3-e2e-guard-report.json"
        )
        check(_new_report.get("passed") is True
              and _new_report.get("config_sha256") == _guard_sha,
              "r32 i3-e2e 自检报告与守卫字节不一致（r34 后须由 dev lane 报告承担）")
    else:
        check(report.get("config_sha256") == _guard_sha,
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


def repair_r32_tail(text: str) -> str:
    """还原被上一次可重入更新误删的 r32 块尾部（含 binding32 合并）。"""

    if BROKEN_R32_TAIL not in text:
        return text
    return must_replace(text, BROKEN_R32_TAIL, R32_TAIL)


def patch_validator() -> dict:
    text = VALIDATOR.read_text(encoding="utf-8")
    # (A) 修复：上一次「可重入更新」用 index 命中了 **r32 块内缩进的**同名字符串，
    # 把它到 supersession 注释之间的内容整体删除 → r32 块尾部与 binding32 合并丢失。
    # 该缺陷会导致 freeze_utils.py 落到 r31 的 i3_2_closure 组（陈旧值）而失配。
    text = repair_r32_tail(text)
    # (B) r34 块：可重入更新（只在顶层 `if "i0c-r34" in by_id:` 处，注意前面的换行）
    if '\nif "i0c-r34" in by_id:' in text:
        start = text.index('\nif "i0c-r34" in by_id:') + 1
        end = text.index("# 最新修订绑定优先（supersession）", start)
        if text[start:end] == R34_BLOCK:
            if text != VALIDATOR.read_text(encoding="utf-8"):
                VALIDATOR.write_text(text, encoding="utf-8")
                return {"repaired": True, "sha256": digest(VALIDATOR)}
            return {"already_patched": True}
        text = text[:start] + R34_BLOCK + text[end:]
        ast.parse(text)
        VALIDATOR.write_text(text, encoding="utf-8")
        return {"updated": True, "sha256": digest(VALIDATOR)}
    marker = 'check("i0c-r33" in by_id, "索引缺少 i0c-r33 条目")'
    text = must_replace(text, marker, marker + '\ncheck("i0c-r34" in by_id, "索引缺少 i0c-r34 条目")')
    # 1) 新增时间稳定的合并辅助（供 r33/r34 块使用）
    text = must_replace(
        text,
        "def merged_binding_from_all_but(exclude: str) -> dict:",
        HELPER + "def merged_binding_from_all_but(exclude: str) -> dict:",
    )
    # 2) r33 块的时间依赖修复：只合并 <= r32
    text = must_replace(
        text,
        '    prev33 = merged_binding_from_all_but("i0c-r33")',
        "    prev33 = merged_binding_upto_revision(32)  # 时间稳定（r34+ 的重绑不回写）",
    )
    # 3) r32 块：允许来源数随 r34 放宽为 6 + dev lane 清单（逐条核对，不得多不得少）
    text = must_replace(
        text,
        '    check(len(srcs.get("allowed_source_paths") or []) == 6, '
        '"r32 i3-e2e 允许来源必须为 U 批准集 6 份")',
        "    expected_guard_sources = 6\n"
        '    if "i0c-r34" in by_id:\n'
        "        _dev_policy = load_json(\n"
        "            ROOT / f\"{base}/audits/20260920-i31-dev-lane/admission-policy-dev.json\"\n"
        "        )\n"
        "        _lane_paths = {\n"
        "            item.get(\"path\")\n"
        "            for item in (_dev_policy.get(\"dev_lane\") or {}).get(\"sources\") or []\n"
        "        }\n"
        "        _approved_paths = {\n"
        "            item.get(\"path\")\n"
        "            for item in load_json(\n"
        "                ROOT / f\"{base}/i0a2-adjudicated-20260915.json\"\n"
        "            )[\"dev_selection_approved\"]\n"
        "        }\n"
        "        expected_guard_sources = len(_approved_paths) + len(_lane_paths)\n"
        "        check(set(srcs.get(\"allowed_source_paths\") or []) == _approved_paths | _lane_paths,\n"
        "              \"r32 i3-e2e 允许来源在 r34 下应为批准集 + dev lane 清单（逐条一致）\")\n"
        '    check(len(srcs.get("allowed_source_paths") or []) == expected_guard_sources,\n'
        '          "r32 i3-e2e 允许来源必须为 U 批准集 6 份（r34 后为 6 + dev lane）")',
    )
    # 4) r32 块：守卫字节自检改由 r34 目录的新报告承担
    text = must_replace(
        text,
        '    check(report.get("config_sha256") == digest(ROOT / f"{base}/guards/i3-e2e.json"),\n'
        '          "r32 i3-e2e 自检报告与守卫字节不一致")',
        '    _guard_sha = digest(ROOT / f"{base}/guards/i3-e2e.json")\n'
        '    if "i0c-r34" in by_id:\n'
        "        _new_report = load_json(\n"
        "            ROOT / f\"{base}/audits/20260920-i31-dev-lane/i3-e2e-guard-report.json\"\n"
        "        )\n"
        '        check(_new_report.get("passed") is True\n'
        '              and _new_report.get("config_sha256") == _guard_sha,\n'
        '              "r32 i3-e2e 自检报告与守卫字节不一致（r34 后须由 dev lane 报告承担）")\n'
        "    else:\n"
        '        check(report.get("config_sha256") == _guard_sha,\n'
        '              "r32 i3-e2e 自检报告与守卫字节不一致")',
    )
    # 5) 插入 r34 块
    text = must_replace(text, anchor, R34_BLOCK + anchor.replace("..r33", "..r34"))
    # 4b) i1-r4 的 supersession 列表补齐到 r34（使代码与其自身注释「i0c-r2..r33/r34 显式重绑
    #     的路径改由 i0c-current 核对」一致）；否则 r34 重绑的 i1-r4 路径（preparation/admission.py、
    #     contract.py）会被 i1-r4 的陈旧值判失配。
    text = must_replace(
        text,
        '"i0c-r24", "i0c-r25"):',
        '"i0c-r24", "i0c-r25", "i0c-r26", "i0c-r27", "i0c-r28", "i0c-r29", "i0c-r30", '
        '"i0c-r31", "i0c-r32", "i0c-r33", "i0c-r34"):',
    )
    anchor = "# 最新修订绑定优先（supersession）：i0c-r2..r33 显式重绑的路径改由合并后的"
    text = must_replace(text, anchor, R34_BLOCK + anchor.replace("..r33", "..r34"))

    # 6) 汇总串追加 r34 说明
    tail = 'if "i0c-r33" in by_id else ""))'
    text = must_replace(
        text,
        tail,
        'if "i0c-r33" in by_id else "") + ("; r34 I3-1 dev-lane MD/DOCX coverage: format gate '
        '(pdf/docx/md all publishable) satisfied, per_class_min_2 still false, production in_scope '
        'unchanged (dev-only policy + truthful material types)" if "i0c-r34" in by_id else ""))',
    )
    ast.parse(text)
    VALIDATOR.write_text(text, encoding="utf-8")
    return {"already_patched": False, "sha256": digest(VALIDATOR)}


def build_r34(archived: list[dict]) -> dict:
    binding: dict[str, dict[str, str]] = {
        "i3_1_dev_lane_policy": {
            f"{AUDIT_REL}/admission-policy-dev.json": digest(DEV_POLICY),
            f"{AUDIT_REL}/dev-scope-manifest.json": digest(DEV_MANIFEST),
        },
        "i3_1_dev_lane_preflight": {
            f"{AUDIT_REL}/preflight_scope_check.py": digest(PREFLIGHT),
            f"{AUDIT_REL}/preflight-scope-check.json": digest(PREFLIGHT_JSON),
            f"{AUDIT_REL}/preflight-scope-check.failclosed-no-dev-lane.json": digest(PREFLIGHT_FAILCLOSED),
        },
        "i3_1_dev_lane_guard": {
            f"{AUDIT_REL}/i3_e2e_guard_selfcheck.py": digest(SELFCHECK),
            f"{AUDIT_REL}/i3-e2e-guard-report.json": digest(GUARD_REPORT),
            rel(GUARD): digest(GUARD),
        },
        "i3_1_dev_lane_run": {
            f"{AUDIT_REL}/run_i3_1_dev_lane.py": digest(RUNNER),
            f"{AUDIT_REL}/i3-1-dev-lane-e2e.json": digest(E2E_JSON),
            f"{AUDIT_REL}/i3-1-dev-lane-e2e.md": digest(E2E_MD),
            f"{AUDIT_REL}/verify_dev_lane_admissions.py": digest(VERIFIER),
            f"{AUDIT_REL}/dev-lane-admission-verification.json": digest(VERIFY_JSON),
            f"{AUDIT_REL}/freeze_r34.py": digest(HERE / "freeze_r34.py"),
        },
        "i3_1_dev_lane_review": {
            f"{AUDIT_REL}/run_review.py": digest(HERE / "run_review.py"),
            f"{AUDIT_REL}/test_dev_lane_probes.py": digest(HERE / "test_dev_lane_probes.py"),
            f"{AUDIT_REL}/freeze-validation.txt": digest(HERE / "freeze-validation.txt"),
            f"{AUDIT_REL}/baseline.txt": digest(HERE / "baseline.txt"),
            f"{AUDIT_REL}/independent-probes-r33.txt": digest(HERE / "independent-probes-r33.txt"),
            f"{AUDIT_REL}/independent-probes-dev-lane.txt": digest(
                HERE / "independent-probes-dev-lane.txt"
            ),
            f"{AUDIT_REL}/m5-evidence-recheck.json": digest(HERE / "m5-evidence-recheck.json"),
        },
        "i3_1_dev_lane_code": {rel(path): digest(path) for path in [*CODE, TESTS]},
        "docs": {rel(TASKS): digest(TASKS), rel(PLAN): digest(PLAN), rel(ARCH): digest(ARCH)},
        "i3_1_dev_lane_archive": {item["archived_as"]: item["sha256"] for item in archived},
        "i3_1_dev_lane_sources": {
            rel(path): digest(path)
            for path in sorted(ARCHIVE_DIR.rglob("*"))
            if path.is_file() and "_staging" not in path.parts
        },
        "freeze_validator": {rel(VALIDATOR): digest(VALIDATOR)},
    }
    return {
        "snapshot_id": "i0c-r34",
        "revision": "r34",
        "phase": "i0c",
        "task": (
            "I3-1 second run under U-decided dev lane: MD/DOCX real dev samples admitted dev-only, "
            "architecture §12.1 format gate satisfied while production in_scope judgement stays unchanged"
        ),
        "parent_snapshot": {
            "snapshot_id": "i0c-r33",
            "path": rel(FREEZES / "i0c-r33.json"),
            "sha256": digest(FREEZES / "i0c-r33.json"),
        },
        "binding": binding,
        "corrections": {
            "I3-1_format_gate": (
                "§12.1 格式门满足：pdf 2/6 + docx 1/1 + md 1/1 均有可发布样本（8 份真跑，"
                "4440 单元 / 794 切块，审计冲突 0）"
            ),
            "I3-1_dev_lane_design": (
                "dev lane 为独立政策文件（policy_rev=v2-dev-20260920、scope=dev、"
                "production_in_scope_unchanged=true、逐源 dev_lane.sources），装载需显式 allow_dev_lane"
                "（CLI CORPUS_DEV_LANE=1），否则 fail-closed；生产政策 admission-policy.json(v1) 与 "
                "i0a2 终态逐字不改"
            ),
            "I3-1_per_class_still_false": (
                "逐类可发布 company 1/3、industry 2/3、macro 1/2 → per_class_min_2 仍为 false"
                "（裁定①阻断缺口处置路径未解，company 0/2 的 13 处缺口依旧）；本轮结果不构成 I4 放行依据"
            ),
            "I3-1_production_unchanged_evidence": (
                "双证：①dev lane 反例族（不给 allow_dev_lane 装载被拒 / v1 政策下仍 policy_conflict / "
                "未列入清单来源不放宽）；②预检 fail-closed 反例（同清单不给 --dev-lane 判 FAIL、"
                "裁定冲突 2、格式仅 pdf）"
            ),
            "I3-1_contract_policy_bound_material": (
                "in_scope 允许材料类型改为按 policy_rev 绑定（contract.IN_SCOPE_MATERIALS_BY_POLICY_REV）；"
                "v1 逐字不变，未知 rev 落最严默认（fail-closed）；dev 落库材料类型如实为 "
                "internal_committee_report / internal_unattributed"
            ),
            "I3-1_scope_eligibility_conflict": (
                "§5.2 新增对账条款：准入按材料类型/领域判、不按文件后缀判；格式可得性为 §12.1 对账项，"
                "dev lane 是唯一分层例外；§12.1 增 format_availability 对账表与 I0A-2 前置"
            ),
            "I3-1_supersedes_r32_guard_scope": (
                "机制修正：r32 块断言 i3-e2e 守卫允许来源恰为批准集 6 份；r34 依 U 裁决追加 dev lane 2 份"
                "（合计 8）。r32 块改为在 r34 存在时按『批准集 + dev lane 清单』逐条一致核对"
                "（不得多、不得少），数量断言随之取 6 + len(dev_lane.sources)"
            ),
            "I3-1_supersedes_r32_selfcheck": (
                "机制修正：守卫配置变更使 r32 目录的旧自检报告不再等于当前守卫字节（旧报告 write-once 保留）。"
                "r32 块改为在 r34 存在时由 dev lane 目录的新自检报告（passed=true 且 config_sha256=当前守卫）承担"
            ),
            "I3-1_review_evidence": (
                "复核面与裁决面同一：本轮复核入口 run_review.py + 新增独立反例 test_dev_lane_probes.py（11 例）"
                "+ 日志（冻结链门/评分器基线 46 passed/r33 探针 10 passed/M5 证据 20 blocks 零 miss 零 error）"
                "一并入链；r33 目录绑定件未被重写（另建入口，写本目录）"
            ),
            "I3-1_i1r4_supersession_fix": (
                "机制修正：i1-r4 的 supersession 跳过集合原硬编码为 i0c-r2..r25，与其自身注释"
                "（『i0c-r2..r33 显式重绑的路径改由 i0c-current 核对』）不一致；r34 重绑了两条只被 "
                "i1-r4 绑定的路径（preparation/admission.py、contract.py），故把列表补齐到 i0c-r34"
            ),
            "I3-1_archive_discipline": (
                "归档忠实性：本修订覆盖 8 条绑定路径，其 pre-r34 字节以两法取得并逐条断言等于在效的上一修订绑定——"
                "①4 条由 git HEAD 还原（已核对 HEAD == 绑定）；②4 条由脚本逆向还原（tests/…admission.py、"
                "tasks.md、plan.md、guards/i3-e2e.json）。**在效绑定的取值口径**：只在 i0c 链上绑定的路径必须取 "
                "i0c ≤33 的合并值——`i1-*` 在合并序上晚于 `i0c-*`，会把 tests/test_…_admission.py 覆盖成 i1-r4 的"
                "陈旧值（38739f39…，真实在效值为 i0c-r5/r6 的 062953f2…）；只被 i1-* 绑定的路径"
                "（preparation/admission.py、contract.py）才回落到 i1-r4。验证器 r33 块的"
                "`merged_binding_from_all_but(\"i0c-r33\")` 同步改为 `merged_binding_upto_revision(32)`，"
                "消除其时间依赖（同 r33 修 r32 的先例）"
            ),
        },
        "created_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "notes": [
            "零模型、零生产库写入；沙箱（i2_sandbox_corpus）先 teardown residue=0 后重建再执行。",
            "改动前字节以 git HEAD（4 路径）与脚本逆向还原（4 路径）两法取得，均逐条断言 == 上一修订绑定。",
            "dev lane 附加材料类型（internal_committee_report / internal_unattributed）仅在该政策 + "
            "该来源清单内可进入 in_scope，且 evidence_refs 带 dev_lane= 标记。",
        ],
    }


def main() -> int:
    previous = previous_effective_binding()
    originals = reconstruct()
    archived = archive(originals, previous)
    bad = [item for item in archived if not item["matches_previous_binding"]]
    if bad:
        print("I0C-R34 FREEZE FAILED: 归档与上一修订绑定不符：")
        for item in bad:
            print(f"  {item['path']}\n    archived={item['sha256']}\n    binding ={item['previous_binding']}")
        return 1
    validator = patch_validator()
    r34 = build_r34(archived)
    R34.write_text(json.dumps(r34, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["snapshots"] = [s for s in manifest["snapshots"] if s.get("snapshot_id") != "i0c-r34"] + [
        {"snapshot_id": "i0c-r34", "file": "i0c-r34.json", "sha256": digest(R34),
         "parent_snapshot_id": "i0c-r33", "created_at": r34["created_at"]}
    ]
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    proc = subprocess.run([sys.executable, str(VALIDATOR)], capture_output=True, text=True,
                          cwd=str(ROOT), check=False)
    print(json.dumps({
        "archived": [{"file": item["archived_as"].split("audits/")[-1],
                      "match": item["matches_previous_binding"]} for item in archived],
        "validator": validator, "r34_sha256": digest(R34),
        "chain_exit": proc.returncode,
        "chain_out": (proc.stdout or "").strip().splitlines()[-2:],
    }, ensure_ascii=False, indent=2))
    return 0 if proc.returncode == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
