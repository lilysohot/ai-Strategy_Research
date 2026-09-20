"""生成 P2（阈值/关键题/负例确认单）、P3（旧基线映射对账 + 漂移核验）、P4（试验初始版本清单）。

全部产物留在本审计目录（未落正式路径、未改冻结件）。U 的口径（2026-09-19）：
**阈值按默认 + 关键题维持 28/30 + 负例全 critical**。
"""

from __future__ import annotations

import hashlib
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

GOLD = BASE / "query-gold-frozen.jsonl"
SOURCE_GOLD = BASE / "source-gold-frozen.jsonl"
PROJECTION = BASE / "i3-2/evidence-targets-approved.json"
DECISIONS = BASE / "i3-2/evidence-targets-decisions.json"
PROJECTION = BASE / "i3-2/evidence-targets-approved.json"
DECISIONS = BASE / "i3-2/evidence-targets-decisions.json"
SCORER = ROOT / "plugins/corpus/scoring.py"
BASELINE = BASE / "baseline-bindings.json"
V3 = BASE / "i0a4-candidates-v3-20260915.json"
P1_JSONL = HERE / "p1/query-gold-with-targets.jsonl"
SCORING_INPUT = BASE / "i3-2/query-gold-scoring-v1.jsonl"
SCORING_MANIFEST = BASE / "i3-2/scoring-input-manifest.json"
P1_REPORT = HERE / "p1/materialization-report.json"
FREEZES = BASE / "freezes"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def write(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix == ".json":
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    else:
        path.write_text(str(payload), encoding="utf-8")


# ───────────────────────────────────────────────────────────── P2


def build_p2() -> dict:
    scoring = __import__("plugins.corpus.scoring", fromlist=["DEFAULT_POLICY"])
    policy = scoring.DEFAULT_POLICY
    gold = load_jsonl(GOLD)
    critical = [str(r["query_id"]) for r in gold if r.get("critical")]
    non_critical = [str(r["query_id"]) for r in gold if not r.get("critical")]
    negatives = [str(r["query_id"]) for r in gold if r.get("answer_existence") == "no_answer"]

    payload = {
        "artifact": "i3-2-p2-policy-and-lists-confirmation",
        "generated_at": now(),
        "decided_by": "U",
        "decided_at": "2026-09-19",
        "decision_text": "P2 按默认 + 关键题维持 28/30 + 负例全 critical",
        "not_filed": "确认单：位于审计目录；随 P1 落正式时一并进 r27 绑定",
        "items": [
            {
                "id": "P2-1",
                "name": "各类阈值（ScoringPolicy 取值）",
                "decision": "按默认确认（不改代码）",
                "values": {
                    "top_k": policy.top_k,
                    "min_rate": str(policy.min_rate),
                    "require_critical_all_pass": policy.require_critical_all_pass,
                    "max_false_positives": policy.max_false_positives,
                    "max_fabricated_citations": policy.max_fabricated_citations,
                },
                "semantics": [
                    "min_rate 用 Fraction(19,20)=95%，10 题则要求 10/10（精确比较，无浮点漂移）",
                    "任意领域 DocRecall/QuestionPass/EvidencePass 低于 95% ⇒ below_threshold blocker",
                    "关键题未全过 ⇒ critical_question_failed blocker",
                    "误报、伪造引用上限均为 0（超出即 blocker）",
                ],
                "evidence": {
                    "source": "plugins/corpus/scoring.py::ScoringPolicy（默认值即架构 §12.3 开发基线）",
                    "scorer_sha256": digest(SCORER),
                    "bound_in": ["i0c-r19", "i0c-r21"],
                },
                "effect": "不改评分器、不改金标；取值随 r27 记录为冻结口径",
            },
            {
                "id": "P2-2",
                "name": "关键题清单",
                "decision": "维持 28/30（全项否决口径不变）",
                "critical_count": len(critical),
                "total": len(gold),
                "critical_ids": critical,
                "non_critical_ids": non_critical,
                "critical_list_sha256": digest_text("\n".join(critical) + "\n"),
                "evidence": {"query_gold_sha256": digest(GOLD), "field": "critical"},
                "note": "非关键仅 industry-006、macro-004；6 道无答案负例也全部为关键题（见 P2-3）",
                "effect": "不改金标；清单哈希随 r27 记录",
            },
            {
                "id": "P2-3",
                "name": "负例口径",
                "decision": "6 道负例全 critical；误报上限 0；负例不进三指标分母；负例不需要 evidence_targets",
                "negative_ids": negatives,
                "negative_count": len(negatives),
                "negative_list_sha256": digest_text("\n".join(negatives) + "\n"),
                "scorer_semantics": [
                    "answer_existence=no_answer ⇒ _evidence_required=False、is_evidence_question=False ⇒ EvidencePass 不计入负例",
                    "max_false_positives=0：把无答案题答成有答案即 blocker",
                    "负例另设 require_critical_all_pass 项：负例答错同样否决",
                ],
                "evidence": {
                    "decisions_negative_reviews": "i3-2/evidence-targets-decisions.json 中 negative_reviews × 6（full_text_coverage_confirmed=true）",
                    "near_miss_library": "i3-2/source-gold-nearmiss-library.jsonl（7 条近似命中隔离，不入映射池）",
                },
                "effect": "不改金标与评分器；口径随 r27 记录",
            },
        ],
        "gaps_from_inventory": {
            "closed_by_this": ["I3-2-3 阈值", "I3-2-4 关键题", "I3-2-5 负例口径"],
            "still_open": ["I3-2-2 材料化落正式", "I3-2-6 旧基线重绑", "I3-2-8 试验初始版本"],
        },
    }
    write(HERE / "p2/policy-and-lists-confirmation.json", payload)

    md = ["# P2 确认单：阈值 / 关键题 / 负例（U 已裁决，未落正式）", ""]
    md.append(f"- 裁决：**{payload['decision_text']}**（U，{payload['decided_at']}）")
    md.append(f"- 评分器：`plugins/corpus/scoring.py` `{payload['items'][0]['evidence']['scorer_sha256'][:12]}…`"
              f"（绑定 i0c-r19 / i0c-r21）")
    md.append("")
    md.append("## P2-1 阈值（按默认确认）")
    md.append("")
    md.append("| 取值 | 冻结值 |")
    md.append("|---|---|")
    for key, value in payload["items"][0]["values"].items():
        md.append(f"| `{key}` | `{value}` |")
    md.append("")
    for line in payload["items"][0]["semantics"]:
        md.append(f"- {line}")
    md.append("")
    md.append(f"## P2-2 关键题（维持 {len(critical)}/{len(gold)}）")
    md.append("")
    md.append(f"- 关键题 {len(critical)} 题（清单哈希 `{payload['items'][1]['critical_list_sha256'][:12]}…`）")
    md.append(f"- 非关键 {len(non_critical)} 题：{'、'.join(non_critical)}")
    md.append("- 口径不变：`require_critical_all_pass=True` ⇒ 任一关键题未过即否决")
    md.append("")
    md.append(f"## P2-3 负例（{len(negatives)} 道全 critical）")
    md.append("")
    md.append(f"- 负例题号：{'、'.join(negatives)}（清单哈希 `{payload['items'][2]['negative_list_sha256'][:12]}…`）")
    for line in payload["items"][2]["scorer_semantics"]:
        md.append(f"- {line}")
    md.append("")
    md.append("> 三项均**不改评分器、不改金标**：只把取值/清单/口径固化记录，随 P1 落正式时一并进 r27 绑定。")
    write(HERE / "p2/policy-and-lists-confirmation.md", "\n".join(md) + "\n")
    return payload


# ───────────────────────────────────────────────────────────── P3


def _hash_of(rel: str) -> dict:
    path = ROOT / rel
    if not path.is_file():
        return {"path": rel, "exists": False, "sha256": None, "matches_declared": None}
    current = digest(path)
    return {"path": rel, "exists": True, "sha256": current, "matches_declared": None}


def _bound_in(rel: str) -> list[str]:
    hits = []
    for path in sorted(FREEZES.glob("i0c-r*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        for group, items in (data.get("binding") or {}).items():
            if rel in items:
                hits.append(data.get("snapshot_id") or path.stem)
    return hits


def build_p3() -> dict:
    index = json.loads(BASELINE.read_text(encoding="utf-8"))
    v3 = json.loads(V3.read_text(encoding="utf-8"))
    v3_bindings = v3.get("baseline_bindings_v3") or {}

    rows = []
    drift = []
    for entry in index["bindings"]:
        category = str(entry["category"])
        detail = v3_bindings.get(category)
        nested_under = None
        if detail is None:  # v3 把 formula_7 作为 financial_controlled_recalc_57 的子节点
            for parent, node in v3_bindings.items():
                if isinstance(node, dict) and category in node:
                    detail, nested_under = node[category], parent
        row: dict[str, object] = {
            "category": category,
            "index_entry": {
                "asset": entry.get("asset"),
                "sha256": entry.get("sha256"),
                "sha256_report": entry.get("sha256_report"),
                "status": entry.get("status"),
                "target": entry.get("target"),
                "binding_detail": entry.get("binding_detail"),
                "verified": entry.get("verified"),
            },
            "v3_detail_present": detail is not None,
            "v3_detail_nested_under": nested_under,
            "v3_detail_keys": sorted(detail) if isinstance(detail, dict) else None,
            "inline_in_index": bool(entry.get("binding_detail")) is False,
        }
        checks = []
        if isinstance(detail, dict):
            for role in ("expectation_asset", "runnable_entry", "machine_record"):
                node = detail.get(role)
                if not isinstance(node, dict) or not node.get("path"):
                    continue
                info = _hash_of(str(node["path"]))
                declared = node.get("sha256")
                info["role"] = role
                info["declared_sha256"] = declared
                if declared and info["exists"]:
                    info["matches_declared"] = info["sha256"] == declared
                    if not info["matches_declared"]:
                        drift.append(
                            {"category": category, "role": role, **info}
                        )
                checks.append(info)
        row["hash_checks"] = checks
        # 可绑定度：能否做"非重跑绑定"（有路径 + 有声明哈希）
        hash_checked = [c for c in checks if c.get("declared_sha256")]
        path_no_hash = [c for c in checks if not c.get("declared_sha256")]
        if hash_checked:
            row["bindability"] = "hash_bound"
        elif path_no_hash:
            row["bindability"] = "path_without_hash"
        else:
            row["bindability"] = "prose_only"
        row["bindability_detail"] = {
            "hash_checked": [{"role": c["role"], "path": c["path"], "consistent": c.get("matches_declared")}
                             for c in hash_checked],
            "path_without_hash": [{"role": c["role"], "path": c["path"]} for c in path_no_hash],
        }
        rows.append(row)

    index_bound = _bound_in(
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/baseline-bindings.json"
    )
    v3_bound = _bound_in(".scratch/corpus-evidence-pipeline/ingestion-rebuild/i0a4-candidates-v3-20260915.json")
    missing_categories = [row["category"] for row in rows if not row["v3_detail_present"]]

    payload = {
        "artifact": "i3-2-p3-baseline-mapping-reconciliation",
        "generated_at": now(),
        "inputs": {
            "baseline-bindings.json": {
                "sha256": digest(BASELINE),
                "git_head": index.get("git_head"),
                "date": index.get("date"),
                "bound_in": index_bound,
            },
            "i0a4-candidates-v3-20260915.json": {
                "sha256": digest(V3),
                "bound_in": v3_bound,
                "has_case_level_detail": sorted(v3_bindings),
            },
        },
        "rows": rows,
        "findings": [
            (
                "指针 vs 内联：`baseline-bindings.json` 的 5 个类别只写『见 i0a4-candidates-v3… "
                "baseline_bindings_v3.<x>』，用例级明细（预期资产+hash、可跑入口+hash、params/副作用/DB、"
                "机器记录）都在候选包 v3 里；两者哈希口径不同（index 里 `sha256: null` + `sha256_report`）"
            ),
            (
                "缺项：候选包 v3 只有 5 类，`old_doc_kind_review_export` 无用例级明细"
                "（该类别注记『权威版本待 U 确认（.audit 共 88 个 2026-09-12 工件）』）"
            ),
            (
                "重跑能力：v3 的 `runnable_entry` 明确带『向原库写 corpus_evidence_runs 新行（零模型但非零写）』"
                "与 `db: 原库 5432`，`prose_numbers_3` 标注『复跑须另立预算授权』——**在 I3 守卫（零写、无 PG、无网络）"
                "下不能重跑**，因此 I3-2 的『旧通过能力不退化』只能做非重跑绑定（期望资产 + 入口字节 + 机器记录），"
                "真实重验按既有分工排 I3-5 并需单独授权"
            ),
            (
                "绑定状态：`baseline-bindings.json` 仅 {} 绑定；**候选包 v3 未被任何修订绑定**（{}）⇒ "
                "`baseline-bindings.json` 的 `binding_detail` 指向一个未入链的文件，I3-2 冻结时必须一起处理"
            ).format(index_bound or "未绑定", v3_bound or "未绑定"),
            (
                "可绑定度：7 类中只有 2 类可做『非重跑绑定』（`legacy_retrieval_golden` 的 "
                "`plugins/corpus/golden.py`、`financial_controlled_recalc_57` 的 `pilot_manifest.json` + "
                "`verify_claims_entry.py`，声明哈希与现况一致、0 漂移）；3 类（`customer_table_12`、"
                "`prose_numbers_3`、`macro_legacy_fields_0_of_3`）的用例级明细是**纯描述**（run_id／source_anchor／"
                "expected／status，无 path、无 sha256），因此目前无法作为非重跑绑定；`financial_controlled_recalc_57` "
                "的 `machine_record` 有路径但**未声明哈希**"
            ),
        ],
        "drift": drift,
        "missing_case_level_categories": missing_categories,
        "recommendation": {
            "I3-2": [
                "把 v3 的用例级明细**内联或强引用（双哈希：index sha + v3 sha）**后随 r27 重绑，"
                "避免『指针指向未被绑定的文件』（现 v3 零绑定）",
                "给 3 个纯描述类目补 `path` + `sha256`（`customer_table_12` 用冻结 run "
                "`0a1dbf39…`、`prose_numbers_3` 用冻结目标/报告、`macro_legacy_fields_0_of_3` 用字段清单），"
                "并给 `financial_controlled_recalc_57.machine_record` 补声明哈希——否则『不退化』只能靠散文声明",
                "`old_doc_kind_review_export` 在 v3 无条目：需 U 圈定权威版本（.audit 88 个工件）或明确降级",
                "在冻结清单里写明：旧基线在 I3 守卫下**不重跑**，只作非重跑绑定；重验排 I3-5 + 单独授权",
            ],
            "对照方法（新旧口径）": [
                "对每个旧基线用例：只比对『预期资产 + 机器记录』（历史通过数字）与新口径下的**同一用例**重评结果；"
                "旧口径（逐题通过含 require_all）与新召回标准**分别报告，不互相替代**",
                "新链路跑不通时按 fail-closed 计入 `blockers`，不得以旧数字顶替",
            ],
        },
    }
    write(HERE / "p3/baseline-mapping-reconciliation.json", payload)

    md = ["# P3 旧基线映射对账（未落正式）", ""]
    md.append(f"- `baseline-bindings.json` `{payload['inputs']['baseline-bindings.json']['sha256'][:12]}…`"
              f"（I0A-4 {index.get('date')}，git_head `{str(index.get('git_head'))[:8]}`）"
              f"｜绑定：{'、'.join(index_bound) or '未绑定'}")
    md.append(f"- 候选包 v3 `{payload['inputs']['i0a4-candidates-v3-20260915.json']['sha256'][:12]}…`"
              f"（用例级 {len(v3_bindings)} 类）｜绑定：{'、'.join(v3_bound) or '未绑定'}")
    md.append("")
    md.append("| 类别 | v3 用例级明细 | 可绑定度 | 已核哈希 | 漂移 |")
    md.append("|---|---|---|---|---|")
    labels = {
        "hash_bound": "可非重跑绑定",
        "path_without_hash": "有路径无哈希",
        "prose_only": "**纯描述（不可绑定）**",
    }
    for row in rows:
        checks = row["hash_checks"]
        bad = [c for c in checks if c.get("matches_declared") is False]
        checked = [c for c in checks if c.get("declared_sha256")]
        assets = "／".join(str(c["path"]).split("/")[-1] for c in checked) or "—"
        detail = "有" if row["v3_detail_present"] else "**缺**"
        if row.get("v3_detail_nested_under"):
            detail += f"（嵌套于 {row['v3_detail_nested_under']}）"
        md.append(
            f"| {row['category']} | {detail} | {labels[row['bindability']]} | {assets} | "
            f"{'漂移 ' + str(len(bad)) + ' 项' if bad else '0'} |"
        )
    md.append("")
    md.append("## 结论与建议")
    md.append("")
    for line in payload["findings"]:
        md.append(f"- {line}")
    md.append("")
    md.append("**I3-2 动作**：")
    for line in payload["recommendation"]["I3-2"]:
        md.append(f"- {line}")
    md.append("")
    md.append("**新旧口径对照方法**：")
    for line in payload["recommendation"]["对照方法（新旧口径）"]:
        md.append(f"- {line}")
    if drift:
        md.append("")
        md.append("## 哈希漂移明细")
        md.append("")
        for item in drift:
            md.append(f"- {item['category']}／{item['role']}：`{item['path']}` 现况 `{str(item['sha256'])[:12]}…`"
                      f" ≠ 声明 `{str(item['declared_sha256'])[:12]}…`")
    write(HERE / "p3/baseline-mapping-reconciliation.md", "\n".join(md) + "\n")
    return payload


# ───────────────────────────────────────────────────────────── P4


def build_p4(p2: dict, p3: dict) -> dict:
    p1 = json.loads(P1_REPORT.read_text(encoding="utf-8"))
    payload = {
        "artifact": "i3-2-p4-experiment-initial-version",
        "generated_at": now(),
        "phase": "I3-2 → I3-1 起点",
        "status": "frozen_r28",
        "not_filed": "清单草稿：随 P1 落正式 + r27 绑定后生效",
        "purpose": "冻结『试验初始版本』：I3-1（E2E）与后续对照都以本清单为准，不得凭记忆或事后补录",
        "components": {
            "scorer": {
                "path": "plugins/corpus/scoring.py",
                "sha256": digest(SCORER),
                "entry": "gold_from_records(records) + score(questions, observations)",
                "bound_in": ["i0c-r19", "i0c-r21"],
            },
            "query_gold": {
                "scoring_input_path": str(SCORING_INPUT.relative_to(ROOT)),
                "scoring_input_sha256": digest(SCORING_INPUT),
                "scoring_input_manifest": str(SCORING_MANIFEST.relative_to(ROOT)),
                "scoring_input_manifest_sha256": digest(SCORING_MANIFEST),
                "unique": True,
                "note": (
                    "执行器**只允许**读 scoring_input_path 指定的正式派生件（经 manifest 哈希校验，"
                    "load_scoring_input）；query-gold-frozen.jsonl 仅作 lineage，不得作为评分输入"
                ),
                "lineage": {
                    "query_gold_frozen": {"path": str(GOLD.relative_to(ROOT)), "sha256": digest(GOLD)},
                    "p1_draft_reference_only": {
                        "path": str(P1_JSONL.relative_to(ROOT)),
                        "sha256": digest(P1_JSONL),
                        "note": "仅作确定性对照（派生件与其逐字节一致），不是评分输入",
                    },
                    "materialization_report_sha256": digest(P1_REPORT),
                },
            },
            "execution": {
                "status": "not_executable_yet",
                "commands": [
                    "（评分契约）python -c \"from plugins.corpus.scoring import gold_from_records, score\"",
                    "（本清单校验）uv run python .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i3_2_completion.py",
                ],
                "runtime_policy": "运行时显式构造 ScoringPolicy（不依赖默认值），取值见 policy 段",
                "environment": "I3-2 仍用 guards/i3.json（零模型/无网络/无来源读取）；I3-1 前另建 i3-e2e 配置",
                "initial_params": {
                    "top_k": p2["items"][0]["values"]["top_k"],
                    "min_rate": p2["items"][0]["values"]["min_rate"],
                    "dev_scope": "3 类 × ≥2 份开发材料（见 dev-manifest.json）",
                },
                "unimplemented_entrypoints": [
                    "I3-1 三类开发 E2E 运行入口（登记为前置，未实现，不得写成已可执行）",
                    "chunk→document Top-k 归并、真实 build_id、fetch/verify 故障与 no_match 转换规则（接线契约待实现）",
                ],
            },
            "approved_projection": {
                "path": str(PROJECTION.relative_to(ROOT)),
                "sha256": digest(PROJECTION),
                "counts": {"approved_required": 79, "supplementary": 20, "questions": 30},
            },
            "decisions": {"path": str(DECISIONS.relative_to(ROOT)), "sha256": digest(DECISIONS)},
            "source_gold": {
                "path": str(SOURCE_GOLD.relative_to(ROOT)),
                "sha256": digest(BASE / "source-gold-frozen.jsonl"),
                "bound_in": ["i0c-r26"],
            },
            "policy": {
                "values": p2["items"][0]["values"],
                "confirmation": str((HERE / "p2/policy-and-lists-confirmation.json").relative_to(ROOT)),
                "sha256": digest(HERE / "p2/policy-and-lists-confirmation.json"),
            },
            "lists": {
                "critical": {
                    "count": p2["items"][1]["critical_count"],
                    "sha256": p2["items"][1]["critical_list_sha256"],
                    "non_critical": p2["items"][1]["non_critical_ids"],
                },
                "negatives": {
                    "count": p2["items"][2]["negative_count"],
                    "sha256": p2["items"][2]["negative_list_sha256"],
                    "ids": p2["items"][2]["negative_ids"],
                },
            },
            "baseline_mapping": {
                "index": {"path": str(BASELINE.relative_to(ROOT)), "sha256": digest(BASELINE)},
                "case_level": {"path": str(V3.relative_to(ROOT)), "sha256": digest(V3)},
                "reconciliation": str((HERE / "p3/baseline-mapping-reconciliation.json").relative_to(ROOT)),
                "reconciliation_sha256": digest(HERE / "p3/baseline-mapping-reconciliation.json"),
                "drift": len(p3["drift"]),
            },
        },
        "declarations": [
            "零模型：不调用任何模型客户端（i3 守卫 blocked_modules + poisoned_env）",
            "零数据库写入：I3 阶段守卫 read_roots 为空、无网络；旧基线**不重跑**（其入口非零写 + 原库 5432，需 I3-5 单独授权）",
            "未读候选业务结果：本清单只绑定预期/金标/配置字节，不含任何检索或答案输出",
            "留出隔离：3 份留出件仍在守卫 forbidden_roots 内（i3.json）",
        ],
        "pending_before_effective": [
            "P1 材料化落正式（新 query-gold 版本）+ U 签认",
            "P3 建议的旧基线重绑方式（内联或双哈希强引用）确认",
            "r27 冻结：绑定上述全部 + P2/P3/P4 产物 + 台账回填",
            "I3-1（E2E）另需 PG/模型与预算授权，且需 `i3-e2e.json` 阶段守卫（i3.json 注记）",
        ],
        "gaps_from_inventory": {
            "closed_by_this": ["I3-2-8 试验初始版本（清单已建）"],
            "still_open": ["I3-2-2 材料化落正式", "I3-2-6 旧基线重绑", "I3-1/I3-5、20 条同义映射审计、macro-004 blocked"],
        },
    }
    write(HERE / "p4/experiment-initial-version.json", payload)

    md = ["# P4 试验初始版本清单（草稿，未落正式）", ""]
    md.append(f"- 生成：{payload['generated_at']}；状态：**{payload['status']}**")
    md.append(f"- 用途：{payload['purpose']}")
    md.append("")
    md.append("## 组成（每项带哈希）")
    md.append("")
    md.append("| 组成 | 路径 | sha256 |")
    md.append("|---|---|---|")
    c = payload["components"]
    md.append(f"| 评分器 | `{c['scorer']['path']}` | `{c['scorer']['sha256'][:12]}…` |")
    md.append(f"| **评分输入（唯一）** | `{c['query_gold']['scoring_input_path']}` | "
              f"`{c['query_gold']['scoring_input_sha256'][:12]}…` |")
    md.append(f"| 评分输入清单 | `{c['query_gold']['scoring_input_manifest']}` | "
              f"`{c['query_gold']['scoring_input_manifest_sha256'][:12]}…` |")
    md.append(f"| query-gold-frozen（仅 lineage） | `{c['query_gold']['lineage']['query_gold_frozen']['path']}` | "
              f"`{c['query_gold']['lineage']['query_gold_frozen']['sha256'][:12]}…` |")
    md.append(f"| 批准投影 | `{c['approved_projection']['path']}` | `{c['approved_projection']['sha256'][:12]}…` |")
    md.append(f"| 裁决件 | `{c['decisions']['path']}` | `{c['decisions']['sha256'][:12]}…` |")
    md.append(f"| source-gold | `{c['source_gold']['path']}` | `{c['source_gold']['sha256'][:12]}…` |")
    md.append(f"| 阈值确认单 | `{c['policy']['confirmation']}` | `{c['policy']['sha256'][:12]}…` |")
    md.append(f"| 旧基线索引/用例级 | `{c['baseline_mapping']['index']['path']}` ／ "
              f"`{c['baseline_mapping']['case_level']['path']}` | "
              f"`{c['baseline_mapping']['index']['sha256'][:12]}…` ／ "
              f"`{c['baseline_mapping']['case_level']['sha256'][:12]}…` |")
    md.append("")
    md.append("## 冻结口径（取自 P2）")
    md.append("")
    for key, value in c["policy"]["values"].items():
        md.append(f"- `{key}` = `{value}`")
    md.append(f"- 关键题 {c['lists']['critical']['count']} 题（非关键：{'、'.join(c['lists']['critical']['non_critical'])}）")
    md.append(f"- 负例 {c['lists']['negatives']['count']} 题（全 critical）")
    md.append("")
    md.append("## 声明")
    md.append("")
    for line in payload["declarations"]:
        md.append(f"- {line}")
    md.append("")
    md.append("## 生效前必须完成")
    md.append("")
    for line in payload["pending_before_effective"]:
        md.append(f"- {line}")
    write(HERE / "p4/experiment-initial-version.md", "\n".join(md) + "\n")
    return payload


def main() -> int:
    p2 = build_p2()
    p3 = build_p3()
    p4 = build_p4(p2, p3)
    print(json.dumps(
        {
            "p2": {"items": len(p2["items"]), "policy": p2["items"][0]["values"],
                   "critical": p2["items"][1]["critical_count"],
                   "negatives": p2["items"][2]["negative_count"]},
            "p3": {"categories": len(p3["rows"]), "drift": len(p3["drift"]),
                   "missing_case_level": p3["missing_case_level_categories"],
                   "baseline_bound_in": p3["inputs"]["baseline-bindings.json"]["bound_in"],
                   "v3_bound_in": p3["inputs"]["i0a4-candidates-v3-20260915.json"]["bound_in"]},
            "p4": {"status": p4["status"], "pending": len(p4["pending_before_effective"])},
        },
        ensure_ascii=False, indent=2,
    ))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
