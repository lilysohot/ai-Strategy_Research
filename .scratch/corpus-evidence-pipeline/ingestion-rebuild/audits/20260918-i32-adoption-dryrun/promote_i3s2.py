"""I3-2 采纳稿**落正式路径**（r26 前置）：归档 → 装新金标 → 重生成候选/裁决件/投影/验证。

步骤（每步打印哈希，便于审计）：

0. 归档 r25 绑定的 ``source-gold-frozen.jsonl`` 字节到 ``before-r26/``（i3-2 产物由各工具
   自带的 ``archive_*`` 归档为 ``-vN``）；
1. 装入新金标版本：``source-gold-frozen.jsonl`` ← 采纳稿（36 槽位），
   负例近似命中库进 ``i3-2/source-gold-nearmiss-library.jsonl``；
2. 重跑生成器（正式路径）→ 候选/核对单/裁决单（rule 仍是 evidence-mapping-6）；
3. 落裁决件：终稿 + 正式 ``based_on`` 哈希（去掉 dryrun 标记）；
4. 跑应用器 → ``approval-report.json`` + ``evidence-targets-approved.json``（批准投影）；
5. 修正验证器 P5 期望值（版本化改动，写明理由）→ 跑验证器 → ``evidence-targets-verification.json``。

**不动**：``query-gold-frozen.jsonl``、``guards/i3.json``、``freezes/*``、``plugins/``、``tests/``。
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))

SOURCE_GOLD = BASE / "source-gold-frozen.jsonl"
QUERY_GOLD = BASE / "query-gold-frozen.jsonl"
CANDIDATES = BASE / "i3-2/evidence-targets-candidates.json"
DECISIONS = BASE / "i3-2/evidence-targets-decisions.json"
VERIFICATION = BASE / "i3-2/evidence-targets-verification.json"
APPROVED = BASE / "i3-2/evidence-targets-approved.json"
REPORT = BASE / "i3-2/approval-report.json"
BEFORE = HERE / "before-r26"
V4 = HERE / "source-gold-v4-candidate.jsonl"
LIBRARY = HERE / "source-gold-nearmiss-library.jsonl"
FINAL_DECISIONS = HERE / "decisions-final-dryrun.json"
VERIFIER = BASE / "i3s2_verify_candidates.py"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def rel(path: Path) -> str:
    return str(path.relative_to(ROOT))


def archive(relative: str) -> dict:
    source = ROOT / relative
    target = BEFORE / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, target)
    return {"path": relative, "archived_as": rel(target), "sha256": digest(target)}


def main() -> int:
    log: dict[str, object] = {"generated_at": now(), "steps": []}
    if V4.read_text(encoding="utf-8").splitlines()[0] != SOURCE_GOLD.read_text(
        encoding="utf-8"
    ).splitlines()[0]:
        pass  # 仅提示，不阻断（两版第一行本就可能相同）

    # 0. 归档 r25 绑定的金标字节
    archived = [archive(rel(SOURCE_GOLD))]
    log["steps"].append({"step": "archive", "items": archived})

    # 1. 装新金标 + 负例库
    before_sha = digest(SOURCE_GOLD)
    shutil.copy2(V4, SOURCE_GOLD)
    shutil.copy2(LIBRARY, BASE / "i3-2/source-gold-nearmiss-library.jsonl")
    log["steps"].append(
        {
            "step": "install_source_gold",
            "before_sha256": before_sha,
            "after_sha256": digest(SOURCE_GOLD),
            "slots": len([line for line in SOURCE_GOLD.read_text(encoding="utf-8").splitlines() if line.strip()]),
            "library_sha256": digest(BASE / "i3-2/source-gold-nearmiss-library.jsonl"),
        }
    )

    # 2. 生成器（正式路径）
    generator = load_module(BASE / "i3s2_evidence_targets.py", "i3s2_generator_formal")
    assert Path(generator.SOURCE_GOLD) == SOURCE_GOLD, "生成器输入不是正式金标，拒绝继续"
    assert Path(generator.OUT_JSON) == CANDIDATES, "生成器输出不是正式候选，拒绝继续"
    generator_code = generator.main()
    log["steps"].append(
        {
            "step": "generator",
            "exit_code": generator_code,
            "candidates_sha256": digest(CANDIDATES),
            "summary": json.loads(CANDIDATES.read_text(encoding="utf-8"))["summary"],
        }
    )

    # 3. 落裁决件（终稿 + 正式 based_on）
    decisions = json.loads(FINAL_DECISIONS.read_text(encoding="utf-8"))
    decisions.pop("dryrun", None)
    decisions.pop("not_filed", None)
    decisions["filed_at"] = now()
    decisions["filed_note"] = (
        "本件由采纳稿落正式路径产生：决定 1（AI 核验锚点逐项同义确认，门记 warning）、"
        "决定 2（无内容词元 span 不作承载映射）、决定 3（chosen 收窄到最小覆盖集，"
        "移出者记 supporting_anchors）、决定 4（blocked 题由人工裁定覆盖，机器状态原样保留）。"
    )
    decisions["based_on"] = {
        "candidates_sha256": digest(CANDIDATES),
        "query_gold_sha256": digest(QUERY_GOLD),
        "source_gold_sha256": digest(SOURCE_GOLD),
    }
    DECISIONS.write_text(json.dumps(decisions, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    log["steps"].append(
        {"step": "decisions", "sha256": digest(DECISIONS), "facet_decisions": len(decisions["facet_decisions"])}
    )

    # 4. 应用器 → 门报告 + 批准投影
    applier = load_module(BASE / "i3s2_apply_decisions.py", "i3s2_applier_formal")
    assert Path(applier.CANDIDATES) == CANDIDATES and Path(applier.DECISIONS) == DECISIONS
    applier_code = applier.main()
    report = json.loads(REPORT.read_text(encoding="utf-8"))
    projection = json.loads(APPROVED.read_text(encoding="utf-8")) if APPROVED.is_file() else None
    log["steps"].append(
        {
            "step": "applier",
            "exit_code": applier_code,
            "ready": report["ready"],
            "blockers": len(report.get("blockers") or []),
            "warnings": len(report.get("warnings") or []),
            "approval_report_sha256": digest(REPORT),
            "approved_sha256": digest(APPROVED) if APPROVED.is_file() else None,
            "projection": None
            if projection is None
            else {
                "questions": len(projection["questions"]),
                "approved_required": sum(len(q["approved_required"]) for q in projection["questions"]),
                "supplementary": sum(len(q["supplementary"]) for q in projection["questions"]),
            },
        }
    )
    if not report["ready"]:
        log["aborted"] = "门未通过，未生成批准投影；停止后续步骤"
        (HERE / "promote-log.json").write_text(
            json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        print(json.dumps(log["steps"][-1], ensure_ascii=False, indent=2))
        return 1

    # 5. 版本化修正验证器 P5 期望值 + 跑验证器
    text = VERIFIER.read_text(encoding="utf-8")
    old_expect = '        item.evidence_pass is True and supplementary == ["company-024-claim-001"],'
    new_expect = (
        "        # r26：补证采纳后 company-005 的补充目标新增 p3 槽位两条（非必需语义不变）。\n"
        "        item.evidence_pass is True\n"
        "        and supplementary\n"
        '        == [\n'
        '            "company-024-claim-001",\n'
        '            "company-ai-supplement-2026-09-06_dddc7cd0-p3",\n'
        '            "company-ai-supplement-2026-09-06_dddc7cd0-p3",\n'
        "        ],"
    )
    if old_expect in text:
        text = text.replace(old_expect, new_expect, 1)
        text = text.replace(
            '        "company-005 的第2页型号清单属补充证据（非必需），缺失不得判失败",',
            '        "company-005 的第2页型号清单属补充证据（非必需），缺失不得判失败'
            '（r26 期望值随补证采纳更新：新增 p3 槽位两条补充目标）",',
            1,
        )
        VERIFIER.write_text(text, encoding="utf-8")
        log["steps"].append({"step": "verifier_p5_updated", "sha256": digest(VERIFIER)})
    else:
        log["steps"].append({"step": "verifier_p5_updated", "skipped": "未找到 r25 期望值（可能已更新）"})

    verifier = load_module(VERIFIER, "i3s2_verifier_formal")
    verifier_code = verifier.main()
    verification = json.loads(VERIFICATION.read_text(encoding="utf-8"))
    log["steps"].append(
        {
            "step": "verifier",
            "exit_code": verifier_code,
            "sha256": digest(VERIFICATION),
            "self_consistency_failed": verification["self_consistency"]["failed"],
            "probes_failed": verification["regression_probes"]["failed"],
            "gate_ready": verification["completeness_gate"].get("ready"),
            "gate_blockers": len(verification["completeness_gate"].get("blockers") or []),
        }
    )

    log["result_hashes"] = {
        name: digest(path)
        for name, path in (
            ("source-gold-frozen.jsonl", SOURCE_GOLD),
            ("i3-2/evidence-targets-candidates.json", CANDIDATES),
            ("i3-2/evidence-targets-decisions.json", DECISIONS),
            ("i3-2/evidence-targets-approved.json", APPROVED),
            ("i3-2/approval-report.json", REPORT),
            ("i3-2/evidence-targets-verification.json", VERIFICATION),
            ("i3s2_verify_candidates.py", VERIFIER),
        )
        if path.is_file()
    }
    (HERE / "promote-log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(json.dumps({"steps": log["steps"][1:], "result_hashes": log["result_hashes"]}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
