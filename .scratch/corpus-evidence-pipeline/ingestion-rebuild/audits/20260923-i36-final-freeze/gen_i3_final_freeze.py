"""生成 I3-6 不可变最终冻结 manifest（``i3-final-freeze-manifest.json``）。

I3-6（任务清单 §3.6）：结束校准并冻结最终配置、代码、规则、评分器、预期与依赖；
生成不可变最终 manifest，核定需重验的 M4/M5 门。本脚本**只读盘面**并产出 manifest：

- 冻结版本定义：i0c 链头 i0c-r4z（其验证器强制 i0c-current 有效绑定 + i1 链有效绑定）；
  本 manifest 不复制绑定集合，以 validate_i0c_freeze.py 为准；
- 关键资产显式清单：评分器/冻结 policy/金标预期/规则/实现入口/测试锚点/守卫/DDL 哈希；
- 运行时配置：各 REV 常量 + 行为开关默认值 + M6 负例评测口径（abstain=on，I-M6-1）；
- 核定需重验的 M4/M5 门（交 I3-7 执行的清单）；
- 待定项登记（全部为「另立授权」型 not_run，无一为冻结必需待定项）。

零模型、零写库、零 git 操作；产物 write-once（语义逐字段比较，重跑一致则保留）。
用法： uv run python gen_i3_final_freeze.py [--no-write]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path("/home/administrator/FrontierAgent").resolve()
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
FREEZES = BASE / "freezes"
HERE = Path(__file__).resolve().parent
OUT = BASE / "i3-final-freeze-manifest.json"
NON_SEMANTIC = ("generated_at",)


def digest(rel: str) -> str:
    return hashlib.sha256((ROOT / rel).read_bytes()).hexdigest()


def semantic(value):
    if isinstance(value, dict):
        return {k: semantic(v) for k, v in value.items() if k not in NON_SEMANTIC}
    if isinstance(value, list):
        return [semantic(v) for v in value]
    return value


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--no-write", action="store_true")
    args = ap.parse_args()

    manifest_list = json.loads((FREEZES / "freeze-manifest.json").read_text(encoding="utf-8"))
    by_id = {s["snapshot_id"]: s for s in manifest_list["snapshots"]}
    head_id = "i0c-r4z"
    head = by_id[head_id]
    head_sha = digest(
        f".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/{head['file']}")

    code_assets = [
        "plugins/corpus/service.py",
        "plugins/corpus/cli.py",
        "plugins/corpus/audit.py",
        "plugins/corpus/scoring.py",
        "plugins/corpus/claims.py",
        "plugins/corpus/claims_detail.py",
        "plugins/corpus/preparation/contract.py",
        "plugins/corpus/preparation/engine.py",
        "plugins/corpus/preparation/admission.py",
        "plugins/corpus/preparation/source.py",
        "plugins/corpus/preparation/clean.py",
        "plugins/corpus/preparation/chunk.py",
        "plugins/corpus/preparation/selection.py",
        "plugins/corpus/preparation/cross_boundary.py",
        "plugins/corpus/preparation/publication.py",
        "plugins/corpus/preparation/repository.py",
        "plugins/corpus/preparation/repository_pg.py",
        "plugins/corpus/preparation/read_pg.py",
        "plugins/corpus/preparation/search_pg.py",
        "plugins/corpus/preparation/negative_query.py",
        "plugins/corpus/preparation/gaps.py",
        "plugins/corpus/preparation/gap_review.py",
        "plugins/corpus/preparation/pdf_gap_regions.py",
        "plugins/corpus/preparation/guard.py",
        "plugins/corpus/preparation/guard_pytest.py",
        "plugins/corpus/preparation/readers/pdf_reader.py",
        "plugins/corpus/preparation/readers/docx_reader.py",
        "plugins/corpus/preparation/readers/md_reader.py",
    ]
    rule_assets = [
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/admission-policy.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-dev-lane/admission-policy-dev.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/design-review.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-dev-lane/dev-scope-manifest.json",
    ]
    expectation_assets = [
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/query-gold-frozen.jsonl",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/source-gold-frozen.jsonl",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/baseline-bindings.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/calibration-plan-v2.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i33-calibration/source-identity-map.json",
    ]
    guard_assets = [
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i0-inventory.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i0a4-freeze.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i0a4-gold.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i0a5-freeze.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-sandbox.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3.json",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3-e2e.json",
    ]
    infra_assets = [
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/sandbox_schema.sql",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/i2s1_apply.py",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2/i2s1_teardown.py",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-fullchain-review/test_fullchain_probes.py",
    ]
    test_anchors = [
        "tests/test_corpus_gap_dispositions.py",
        "tests/test_corpus_negative_query.py",
        "tests/test_corpus_search_pg.py",
        "tests/test_corpus_selection.py",
        "tests/test_corpus_dev_lane.py",
        "tests/test_corpus_consumers_pg.py",
        "tests/test_corpus_authority_pg.py",
        "tests/test_corpus_cli_pg.py",
        "tests/test_corpus_cli_isolation.py",
        "tests/test_corpus_preparation_publication_pg.py",
        "tests/test_corpus_preparation_repository_pg.py",
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i32-remediation/test_approval_contract.py",
    ]

    snapshot = {
        "artifact": "i3-final-freeze-manifest",
        "task": "I3-6 结束校准并冻结最终配置、代码、规则、评分器、预期与依赖；核定需重验的 M4/M5 门",
        "generated_at": datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds"),
        "frozen_version": {
            "chain_head": {
                "snapshot_id": head_id,
                "file": f".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/{head['file']}",
                "sha256": head_sha,
            },
            "chain_manifest": {
                "file": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/freeze-manifest.json",
                "sha256": digest(".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/freeze-manifest.json"),
                "snapshots": len(manifest_list["snapshots"]),
            },
            "freeze_validator": {
                "file": ".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py",
                "sha256": digest(".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py"),
            },
            "definition": (
                "冻结版本 = i0c 冻结链全链（61+ 快照，追加式）经 validate_i0c_freeze.py 核验的 "
                "i0c-current 有效绑定 + validate_i1_freeze.py 核验的 i1 链有效绑定；"
                "本 manifest 是版本索引与核定记录，不复制绑定集合（以验证器为准），"
                "报告引用运行快照 ID/哈希（架构 §12.1）。"
            ),
        },
        "frozen_assets": {
            "implementation": {p: digest(p) for p in code_assets},
            "rules_and_config": {p: digest(p) for p in rule_assets},
            "expectations_and_policy": {p: digest(p) for p in expectation_assets},
            "guards": {p: digest(p) for p in guard_assets},
            "infra_and_rebuild_path": {p: digest(p) for p in infra_assets},
            "test_anchors": {p: digest(p) for p in test_anchors},
        },
        "runtime_configuration": {
            "revs": {
                "reader_pdf": "reader-pdf-6",
                "reader_docx": "reader-docx-2",
                "reader_md": "reader-md-2",
                "clean": "clean-3",
                "chunk": "chunk-3",
                "index": "index-4-zhcfg-2",
                "ingest": "ingest-1",
                "admission_probe": "admission-probe-1",
            },
            "switches": [
                {"name": "RANK_LEXEME_PRUNE", "default": "on",
                 "scope": "search_pg 双 tsquery 排序信号（r4v；M5 粒度签认 r4w declared）；一级回滚 = False"},
                {"name": "stitch_continuation", "default": "on",
                 "scope": "cross_boundary 续接聚合（r4u，read-side path B）"},
                {"name": "attach_source_note", "default": "on",
                 "scope": "cross_boundary 来源注谓词（r4y）"},
                {"name": "CORPUS_ABSTAIN_NO_ANSWER", "code_default": "off", "m6_eval": "on",
                 "scope": "无答案拒检通道（r4t）；代码字节默认 off，M6 负例评测口径 =on"
                          "（I-M6-1：B2 复验 6/6 hits=0 + abstain=true）"},
                {"name": "CORPUS_READ_CHAIN", "default": "auto",
                 "scope": "fail-closed 探测（目标库有 corpus schema 走 new 链）"},
                {"name": "CORPUS_DEV_LANE", "default": "unset",
                 "scope": "仅 dev lane 两份（工业富联 md / 光模块 docx）装载需 =1"},
            ],
            "frozen_policy": {
                "source": "audits/20260920-i33-calibration/calibration-plan-v2.json",
                "min_rate": "19/20", "top_k": 5, "require_critical_all_pass": True,
                "max_false_positives": 0, "max_fabricated_citations": 0,
            },
        },
        "m4_m5_gates_to_reverify": [
            "I2 全链路回路 12 项（9 链不变量 + check/status 缺口契约）："
            "audits/20260918-i2-fullchain-review/test_fullchain_probes.py（write-once 不修改），"
            "CORPUS_I2_DSN → 重建沙箱",
            "缺口处置契约：tests/test_corpus_gap_dispositions.py",
            "M4 内存链（admission/fidelity/mapping/编排/发布门 + 夹具）：tests/test_corpus_*.py "
            "corpus 家族（plain env）",
            "M4 守卫门（i1 阶段零模型/零网络/六材料范围）：corpus 家族 i1 守卫 env",
            "M5 PG 门（publication_pg/repository_pg/authority/cli_pg/cli_isolation/consumers_pg/"
            "search_pg/a1_ingest_search/claims/metadata）：i2-verify 守卫 env + CORPUS_I2_DSN → 重建沙箱，"
            "核心门零 skip",
            "dev lane 门：tests/test_corpus_dev_lane.py（i3-e2e 守卫 env）",
            "legacy 非回归（旧库 5432 只读）：旧检索 golden 19/19（O6 r27 排除）+ 财务 47/47 + "
            "公式 7/7 + 高盛负控 + 客户表 12/12（冻结 run 复验）+ 正文冻结 2 例 + 宏观 0/3 单列 + "
            "审批契约门 test_approval_contract.py",
            "负例双口径：评分层 false_positives=0（冻结 policy）+ 产品层 CORPUS_ABSTAIN_NO_ANSWER=on "
            "6/6 hits=0 + abstain=true",
            "静态门：ruff（CI 范围）+ pyright + import_smoke --stage 1（分层规则）",
        ],
        "pending_items": [
            {"item": "prose_numbers 重抽取（4 次模型调用）", "status": "not_run_pending_budget",
             "note": "r27：复跑须另立预算授权；非冻结必需项"},
            {"item": "真实答案语义测试", "status": "not_run_pending_authorization",
             "note": "任务行：另定输入/人工判据/有限预算，未授权前 not_run 不计通过；非冻结必需项"},
            {"item": "guosen_maotai 留出 10 格 + customer_table 原文 re-parse",
             "status": "held_out_guard_protected",
             "note": "守卫 forbidden_roots（含 bbba671e）；独立留出另验须 U 显式授权解锁守卫，"
                     "不在 I3-6/I3-7 开发口径内"},
            {"item": "宏观旧规范字段 0/3", "status": "preserved_failure",
             "note": "失败基线保留单列，非待定项"},
        ],
        "calibration_closure": (
            "I3-3 校准按 r39 预定两轮停止后，经 r40—r4x 修复簇（reader-pdf-6 阅读序、clean-3 "
            "句粒度、band/cell 选择、cross_boundary 续接/来源注、prune_fn_punct 排序信号、"
            "abstain 拒检、金标 col 口径 r4x 具名授权）与 b5 盘点收敛：三类 DocRecall=100%、"
            "QuestionPass=24/24、EvidencePass=24/24、关键题 22/22、评分层 FP=0、产品层 abstain "
            "6/6（audits/20260923-b5-final/b5-inventory.json，只读复验）。校准至此结束。"
        ),
        "discipline": {
            "zero_model": True, "db_write": "none（本 manifest 生成零写库）",
            "holdout_read": "none", "git_ops": "none",
            "note": "本 manifest 为 I3-6 冻结产物；I3-7 重验须对本冻结版本执行，"
                    "I3-6 后任何影响运行的变更将使最终报告失效并回到重新冻结与 I3-7（任务清单 §3.6 尾注）。",
        },
    }

    if OUT.exists():
        existing = json.loads(OUT.read_text(encoding="utf-8"))
        if semantic(existing) == semantic(snapshot):
            print("[write-once] i3-final-freeze-manifest.json 语义一致 → 保留原产物")
            return 0
        raise RuntimeError("write-once conflict: i3-final-freeze-manifest.json 语义差异")

    text = json.dumps(snapshot, ensure_ascii=False, indent=1) + "\n"
    if args.no_write:
        print("[--no-write] 预览完成，未写盘")
        print(text[:800])
        return 0
    OUT.write_text(text, encoding="utf-8")
    print(f"[manifest] {OUT.relative_to(ROOT)} sha256={hashlib.sha256(OUT.read_bytes()).hexdigest()[:12]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
