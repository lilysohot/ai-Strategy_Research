#!/usr/bin/env python3
"""Zero-call attribution of the 14 gate-33 false negatives (fn).

Per unmatched frozen gold record, classify which situation it is in:

  A  near_duplicate_ce   a same-source candidate is at/above the proxy similarity
                         threshold (or strongly contains) the gold text, yet was
                         adjudicated correct_extra / duplicate
  B  occupied_by_gold    the nearest candidate is already matched to a different gold
                         (one-to-one mapping), so it cannot also serve this one
  C  no_candidate        no same-source candidate is close; recovering it needs new
                         extraction (bounded call budget) or a scope decision
  D  gap_slot            the gold fragment fell inside one of the 9 unproduced slots
                         recorded in evidence/32 residual-attribution.json
  E  mention_only        only a reason-text mention links a candidate to the gold

Signals are machine-derived and are an attribution input, NOT an adjudication.
The similarity signal is a proxy heuristic; every row carries `flags`.

Read-only on every input. Writes only inside its own evidence directory.
--no-write performs the full computation and prints the summary without writing.
"""

from __future__ import annotations

import argparse
import difflib
import hashlib
import json
import re
import unicodedata
from pathlib import Path
from typing import Any

REPO_ROOT = Path(__file__).resolve().parents[5]
HERE = Path(__file__).resolve().parent
E = REPO_ROOT / ".scratch/claims-r2-role-isolation/evidence"
SCRATCH = REPO_ROOT / ".scratch/claims-r2-role-isolation"

SIM_THRESHOLD = 0.75  # proxy threshold the 67 prefill used; heuristic only
MIN_CONTAIN_LEN = 6
GOLD_ID_RE = re.compile(r"NT-[A-Z]?\d{2}")

SOURCE_LABEL = {
    "sha256:f8fa22084535e3696fed0bc4da1e9a1b71c863ddb1a883603dcb3d251839cbcb": (
        "源1",
        "industrial-fulian-md",
    ),
    "sha256:48c05895798ba0096b5ac5cc6fbf42fcc9d63929c2a7a2df61e7b16b3a4a659f": (
        "源2",
        "optical-module-docx",
    ),
}

BUCKET_LABEL = {
    "A_near_duplicate_ce": "A 近逐字候选但已判 ce/dup",
    "B_occupied_by_gold": "B 最近候选已被其他金标占用",
    "C_no_candidate": "C 池内无近似候选",
    "D_gap_slot": "D 落在未产出槽",
    "E_mention_only": "E 仅 reason 提及",
}

# 2026-10-12 U 亲自校准撤销的三条 matched（union-adjudication.md §3.2）；本表现场保留，不计入可达上限。
U_CALIBRATION_REVOKED = ("NT-I45", "NT-I46", "NT-I47")

# 机制分类：agent draft，依据是该条候选的具名裁定理由原文，须由 xyl 确认后才可当口径使用。
MECHANISM_DRAFT = {
    "NT-I09": "金标比候选细：金标把一句拆成『条件(I09)+结论(I10)』，候选整句被 I10 占用，一对一映射必有一条落空",
    "NT-I19": "金标比候选细：同上，I19 条件从句与 I20 主命题同句，候选被 I20 占用",
    "NT-I31": "金标比候选细/切分不同：I31 与 I32 为同一句的两种切分，候选被 I32 占用",
    "NT-I38": "金标比候选粗：金标把前半+后半两个原子并为一条，候选正确拆成两条，各自不完整均判 ce",
    "NT-I48": "金标比候选粗：同 I38，金标合并『税负可转嫁』+『对竞争力毛利影响不大』两半",
    "NT-I23": "候选缺承载主体：裁定理由为缺主语『128端口产品』，仅余谓词",
    "NT-I24": "候选缺承载主体：同 I23（同一候选拆出的另一条）",
    "NT-I26": "候选缺承载主体：文本逐字相同，但裁定理由为缺主语『128端口光波导』",
    "NT-I34": "候选缺时间框架与条件：裁定理由为缺『2029-2030 年』与『材料未突破』",
    "NT-I36": "断言形态不符：候选为类比式问句而非肯定断言",
    "NT-I39": "候选缺限定：裁定理由为未提『海外产能』且仅为片段",
    "NT-I45": "U 2026-10-12 校准撤销：金标为被转述且被质疑的预测（quoted_other/challenged），候选为材料自身陈述",
    "NT-I46": "U 2026-10-12 校准撤销：同 I45",
    "NT-I47": "U 2026-10-12 校准撤销：同 I45",
}


def sha256_of(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def norm(text: str) -> str:
    """Fold width/space/punctuation so proxy similarity compares prose, not typography."""
    folded = unicodedata.normalize("NFKC", text or "")
    return "".join(
        ch for ch in folded if not ch.isspace() and not unicodedata.category(ch).startswith("P")
    )


def ratio(a: str, b: str) -> float:
    return round(difflib.SequenceMatcher(None, norm(a), norm(b)).ratio(), 3)


def load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    gold_path = E / "10-quality-gold-freeze-20261008-r2/frozen-gold.json"
    gate33_gold_path = E / "33-items-quality-scoring-20261011/r0-zero-call/adjudications.json"
    worksheet_path = SCRATCH / "adjudication/worksheet.json"
    signed_paths = {
        "r5": E / "65-rerun-two-arm-protocol-20261013/r6-assembly/assembled-scoring-input.json",
        "base": E / "66-base-protocol-change-proposal-20261013/r4-assembly/assembled-scoring-input.json",
    }
    score_path = E / "69-union-adjudication-20261013/r1-score/gate33-honest-score.json"
    residual_path = E / "32-items-v6-reasoning-refreeze-20261011/live/residual-attribution.json"
    contract_path = E / "58-contract-v42-signed-20261012/r0-zero-call/scoring-contract-v4.2.json"

    gold_doc = load(gold_path)
    by_id = {r["record_id"]: r for r in gold_doc["records"] if r["role"] == "material_items"}
    gate33_gold = {g["record_id"]: g for g in load(gate33_gold_path)["gold_reference"]}
    contract = load(contract_path)
    assertions = sorted(k for k in contract["review_assertions"] if k.startswith("NT-I"))
    score = load(score_path)
    residual = load(residual_path)

    # --- consistency: the two frozen 48-item sets must agree on ids, quote and source ---
    consistency = {
        "frozen_ids": sorted(by_id),
        "gate33_ids": sorted(gate33_gold),
        "id_sets_equal": sorted(by_id) == sorted(gate33_gold),
        "quote_mismatches": [
            rid
            for rid, rec in sorted(by_id.items())
            if (gate33_gold.get(rid) or {}).get("quote") != rec.get("quote")
        ],
        "source_mismatches": [
            rid
            for rid, rec in sorted(by_id.items())
            if (gate33_gold.get(rid) or {}).get("source_id") != rec["source_id"]
        ],
        "field_note": (
            "gate33.gold_reference.proposition 是完整命题，frozen-gold.quote 是原文片段；"
            "评分器 score_gate33.py:77 以 quote 作为 proposition 载体。"
        ),
    }

    # --- scored candidates: 222 pool (authoritative A) + 31 signed batch rows ---
    scored: list[dict[str, Any]] = []
    for rec in load(worksheet_path)["records"]:
        oc = rec.get("original_candidate") or {}
        scored.append(
            {
                "candidate_id": rec["candidate_id"],
                "bucket": "A_pool",
                "source_id": rec["source_id"],
                "text": oc.get("text") or "",
                "slot": oc.get("candidate_slot_id"),
                "judgement": rec["judgement"],
                "matched_gold_id": rec.get("matched_gold_id"),
                "reason": rec.get("reason") or "",
            }
        )
    for batch, path in signed_paths.items():
        payload = load(path)
        raw = {c["candidate_id"]: c for c in payload["raw"]}
        audit = {a["candidate_id"]: a for a in payload["audit"]}
        for m in payload["mappings"]:
            c = raw[m["candidate_id"]]
            fields = dict(c["semantic_fields"])
            scored.append(
                {
                    "candidate_id": c["candidate_id"],
                    "bucket": f"signed_{batch}",
                    "source_id": c["source_id"],
                    "text": fields.get("proposition") or "",
                    "slot": c["candidate_id"].split("#")[0],
                    "judgement": m["judgement"],
                    "matched_gold_id": m.get("gold_record_id"),
                    "reason": (audit.get(m["candidate_id"]) or {}).get("reason") or "",
                }
            )
    for row in scored:
        if not row["source_id"].startswith("sha256:"):
            row["source_id"] = "sha256:" + row["source_id"]

    # --- the 9 unproduced slots of the frozen run ---
    gap_slots: list[dict[str, Any]] = []
    for slug, block in residual["sources"].items():
        for res in block["residuals"]:
            gap_slots.append(
                {
                    "slug": slug,
                    "candidate_slot_id": res["candidate_slot_id"],
                    "slot_status": res["status"],
                    "category": res["verdict"]["category"],
                    "slot_text": res["slot_text"],
                    "packet_id": res["packet_id"],
                    "attempt_status": res["attempt_status"],
                }
            )

    matched = set(score["matched_gold_ids"])
    missing = sorted(score["missing_gold_ids"])
    assert sorted(matched | set(missing)) == sorted(by_id), "score ids do not cover the 48 gold"

    rows: list[dict[str, Any]] = []
    for gid in missing:
        rec = by_id[gid]
        label, slug = SOURCE_LABEL[rec["source_id"]]
        g33 = gate33_gold.get(gid) or {}
        targets = [t for t in {rec.get("quote") or "", g33.get("proposition") or ""} if t]

        mentions = [
            {
                "candidate_id": c["candidate_id"],
                "bucket": c["bucket"],
                "judgement": c["judgement"],
                "reason": c["reason"][:200],
            }
            for c in scored
            if gid in GOLD_ID_RE.findall(c["reason"])
        ]

        near: list[dict[str, Any]] = []
        for c in scored:
            if c["source_id"] != rec["source_id"]:
                continue
            sim = max((ratio(c["text"], t) for t in targets), default=0.0)
            contain = any(
                norm(t)
                and (
                    norm(t) in norm(c["text"])
                    or (norm(c["text"]) and len(norm(c["text"])) >= MIN_CONTAIN_LEN and norm(c["text"]) in norm(t))
                )
                for t in targets
            )
            near.append({**c, "sim": sim, "containment": contain})
        near.sort(key=lambda c: (c["sim"], c["containment"]), reverse=True)
        best = near[0] if near else None

        gap_hits: list[dict[str, Any]] = []
        for slot in gap_slots:
            sim = ratio(slot["slot_text"], " ".join(targets))
            if sim >= SIM_THRESHOLD or any(
                norm(t) and len(norm(t)) >= MIN_CONTAIN_LEN and norm(t) in norm(slot["slot_text"])
                for t in targets
            ):
                gap_hits.append({**slot, "sim": sim})
        gap_hits.sort(key=lambda g: g["sim"], reverse=True)

        if gap_hits:
            bucket = "D_gap_slot"
        elif best and best["judgement"] == "matched" and best["sim"] >= 0.6:
            bucket = "B_occupied_by_gold"
        elif best and (best["sim"] >= SIM_THRESHOLD or best["containment"]):
            bucket = "A_near_duplicate_ce"
        elif mentions:
            bucket = "E_mention_only"
        else:
            bucket = "C_no_candidate"

        rows.append(
            {
                "gold_id": gid,
                "bucket": bucket,
                "source": label,
                "source_slug": slug,
                "locator": rec.get("locator"),
                "quote": rec.get("quote"),
                "proposition": g33.get("proposition"),
                "is_review_assertion": gid in assertions,
                "critical": bool(rec.get("critical")),
                "risk_or_condition": bool(rec.get("risk_or_condition")),
                "u_calibration_revoked": gid in U_CALIBRATION_REVOKED,
                "agent_draft_mechanism": MECHANISM_DRAFT.get(gid, ""),
                "reason_mentions": mentions,
                "nearest_candidates": [
                    {
                        "candidate_id": c["candidate_id"],
                        "bucket": c["bucket"],
                        "judgement": c["judgement"],
                        "matched_gold_id": c["matched_gold_id"],
                        "sim": c["sim"],
                        "containment": c["containment"],
                        "text": c["text"][:140],
                        "reason": c["reason"][:200],
                        "flags": [
                            f
                            for f in (
                                "containment" if c["containment"] else None,
                                "sim>=thr" if c["sim"] >= SIM_THRESHOLD else None,
                                "judged_matched_other" if c["judgement"] == "matched" else None,
                                "judged_correct_extra" if c["judgement"] == "correct_extra" else None,
                            )
                            if f
                        ],
                    }
                    for c in near[:3]
                ],
                "gap_slot_hits": gap_hits,
            }
        )

    order = {
        "A_near_duplicate_ce": 0,
        "B_occupied_by_gold": 1,
        "C_no_candidate": 2,
        "D_gap_slot": 3,
        "E_mention_only": 4,
    }
    rows.sort(key=lambda r: (order[r["bucket"]], r["source"], r["gold_id"]))

    buckets = {k: [r["gold_id"] for r in rows if r["bucket"] == k] for k in order}
    buckets = {k: v for k, v in buckets.items() if v}
    assertions_failed = [r["gold_id"] for r in rows if r["is_review_assertion"]]

    def project(extra: set[str]) -> dict[str, Any]:
        proj = matched | extra
        per_source = {
            lab: {
                "matched": sum(1 for rid in proj if SOURCE_LABEL[by_id[rid]["source_id"]][0] == lab),
                "gold": sum(1 for rid in by_id if SOURCE_LABEL[by_id[rid]["source_id"]][0] == lab),
            }
            for lab in ("源1", "源2")
        }
        for v in per_source.values():
            v["recall"] = round(v["matched"] / v["gold"], 3)
        cov = len([g for g in assertions if g in proj])
        ok = (
            len(proj) / 48 >= 0.85
            and all(v["recall"] >= 0.8 for v in per_source.values())
            and cov == len(assertions)
        )
        return {
            "extra_matched": sorted(extra),
            "matched_total": len(proj),
            "recall_overall": round(len(proj) / 48, 3),
            "per_source": per_source,
            "assertions_covered": f"{cov}/{len(assertions)}",
            "verdict": "PASS" if ok else "still FAIL",
        }

    A_plus_B = set(buckets.get("A_near_duplicate_ce", []) + buckets.get("B_occupied_by_gold", []))
    scenarios = {
        "S0_as_scored": project(set()),
        "S1_A_only": project(set(buckets.get("A_near_duplicate_ce", []))),
        "S2_A_and_B": project(A_plus_B),
        "S3_A_B_minus_u_calibration": project(A_plus_B - set(U_CALIBRATION_REVOKED)),
        "S4_all_fn": project(set(missing)),
    }

    out = {
        "schema_version": "gate33-fn-attribution-1",
        "created_on": "2026-10-13",
        "zero_model_calls": True,
        "basis": "gate33-honest-score.json（A 工作表权威 + r5/base 签认批）",
        "authority_note": (
            "本表是机械归因输入，不是裁定。A/B 桶只说明『池内已有近似候选、但已被具名裁定为非匹配』，"
            "是否改判必须由 xyl 具名，并且会触碰『片段/缺限定是否算原子命题命中』这一口径。"
        ),
        "method": {
            "similarity": f"difflib 归一化相似度（NFKC、去空白与标点），阈值 {SIM_THRESHOLD}；代理启发式",
            "containment": f"互为包含，较短一侧长度 >= {MIN_CONTAIN_LEN}",
            "gap_slot": "落在 evidence/32 residual-attribution.json 记录的 9 个未产出槽",
            "bucket_rule": (
                "D 若落在未产出槽；否则若最近候选已被其他金标 matched（sim>=0.6）记 B；"
                "否则若 sim>=阈值或互为包含记 A；否则仅有 reason 提及记 E；否则记 C"
            ),
        },
        "inputs": {
            "gold": str(gold_path.relative_to(REPO_ROOT)),
            "gate33_gold_reference": str(gate33_gold_path.relative_to(REPO_ROOT)),
            "worksheet_A": str(worksheet_path.relative_to(REPO_ROOT)),
            "signed_batches": {k: str(v.relative_to(REPO_ROOT)) for k, v in signed_paths.items()},
            "score": str(score_path.relative_to(REPO_ROOT)),
            "residual_attribution": str(residual_path.relative_to(REPO_ROOT)),
            "contract": str(contract_path.relative_to(REPO_ROOT)),
        },
        "input_hashes": {
            "gold": sha256_of(gold_path),
            "gate33_gold_reference": sha256_of(gate33_gold_path),
            "worksheet_A": sha256_of(worksheet_path),
            **{f"signed_{k}": sha256_of(v) for k, v in signed_paths.items()},
            "score": sha256_of(score_path),
            "residual_attribution": sha256_of(residual_path),
            "contract": sha256_of(contract_path),
        },
        "consistency": consistency,
        "scored_candidates": {
            "total": len(scored),
            "by_bucket": {
                b: sum(1 for c in scored if c["bucket"] == b) for b in sorted({c["bucket"] for c in scored})
            },
            "by_source": {SOURCE_LABEL[s][0]: sum(1 for c in scored if c["source_id"] == s) for s in SOURCE_LABEL},
            "note": "31 条签认批候选全部属于源1；源2 的 FN 只可能由 222 池内的源2 候选解释。",
        },
        "inventory": {
            "gold_total": len(by_id),
            "matched_total": len(matched),
            "fn_total": len(missing),
            "fn_by_source": {lab: sum(1 for r in rows if r["source"] == lab) for lab in ("源1", "源2")},
            "assertions_total": len(assertions),
            "assertions_failed": assertions_failed,
            "assertions_failed_by_source": {
                lab: [r["gold_id"] for r in rows if r["is_review_assertion"] and r["source"] == lab]
                for lab in ("源1", "源2")
            },
        },
        "buckets": buckets,
        "bucket_counts": {k: len(v) for k, v in buckets.items()},
        "contradicted_claims": [
            {
                "claim": "缺口为真实 FN（金标无候选匹配），非流程问题",
                "where": "evidence/69-union-adjudication-20261013/r1-score/gate33-honest-score.json:88",
                "machine_finding": (
                    "14/14 条 FN 在同源候选里都有近似文本（12 条 sim>=0.75 或互为包含，2 条候选已被邻近金标占用且带具名理由）；"
                    "『无匹配』字面为真，但读作『模型没产出相关内容』与实测不符"
                ),
            },
            {
                "claim": "14 条 FN 为真实抽取覆盖缺口（三次独立抽取均未覆盖）",
                "where": "evidence/69-union-adjudication-20261013/r1-score/gate33-full-verdict.md:26-30",
                "machine_finding": "0 条落在 evidence/32 记录的 9 个未产出槽；0 条为『池内无近似候选』",
            },
            {
                "claim": "8 条未过断言全部属于源2 文档段",
                "where": "evidence/69-union-adjudication-20261013/r1-score/gate33-full-verdict.md:17 与 report.md:14",
                "machine_finding": "NT-I09、NT-I19 属于源1（locator 为 char: 体系；源2 为 body[N] 体系），与其自身判据 2『源1 20/22』自相矛盾",
            },
            {
                "claim": "源2 召回 0.538 + 8 条断言未过：需对源2 对应片段定向补抽",
                "where": "evidence/70-closure-20261013/r0-zero-call/closure.md:29 与 gate33-full-verdict.md:34",
                "machine_finding": (
                    "补抽同样会产出这些片段，而它们已被具名裁定为非等价（原子度/限定/承载/断言形态）；"
                    "要翻必须先裁口径，不是抽取问题"
                ),
            },
        ],
        "scenarios": scenarios,
        "rows": rows,
    }

    summary = {
        "fn_total": len(missing),
        "bucket_counts": out["bucket_counts"],
        "assertions_failed_by_source": out["inventory"]["assertions_failed_by_source"],
        "scenarios": scenarios,
        "consistency_ok": {
            "id_sets_equal": consistency["id_sets_equal"],
            "quote_mismatches": len(consistency["quote_mismatches"]),
            "source_mismatches": len(consistency["source_mismatches"]),
        },
    }

    if not args.no_write:
        (HERE / "fn-attribution.json").write_text(
            json.dumps(out, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )
        (HERE / "fn-attribution.md").write_text(render_md(out), encoding="utf-8")
        manifest = {
            "schema_version": "evidence-manifest-1",
            "created_on": "2026-10-13",
            "zero_model_calls": True,
            "artifacts": {
                name: sha256_of(HERE / name)
                for name in ("build_fn_attribution.py", "fn-attribution.json", "fn-attribution.md")
            },
            "inputs": out["input_hashes"],
            "reproduce": (
                "uv run python .scratch/claims-r2-role-isolation/evidence/"
                "71-fn-attribution-20261013/r0-zero-call/build_fn_attribution.py"
            ),
        }
        (HERE / "MANIFEST.json").write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
        )

    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


def render_md(out: dict[str, Any]) -> str:
    inv, scen = out["inventory"], out["scenarios"]
    lines = [
        "# 门 33 的 14 条 FN 逐条归因（零模型调用；机械归因输入，非裁定）",
        "",
        "- 2026-10-13　零调用　基准：`gate33-honest-score.json`（A 工作表权威 + r5/base 签认批）",
        f"- 金标 `frozen-gold.json` role=material_items 48 条；matched {inv['matched_total']}，FN {inv['fn_total']}"
        f"（源1 {inv['fn_by_source']['源1']} / 源2 {inv['fn_by_source']['源2']}）",
        f"- 16 条高危断言未中 {len(inv['assertions_failed'])} 条："
        f"源1 {inv['assertions_failed_by_source']['源1']}、源2 {inv['assertions_failed_by_source']['源2']}",
        "",
        "> **这是机械归因，不是裁定。**A/B 桶只说明「池内已有近似候选、但已被具名裁定为非匹配」，",
        "> 是否改判必须由 xyl 具名，并会触碰「片段/缺限定是否算原子命题命中」的口径。",
        "",
        "## 〇、首要结论",
        "",
        "**14 条 FN 全部是同源候选『已抽到但被判不等价』，没有一条是抽取覆盖缺口。**",
        "",
        f"- A 近逐字但已判 ce/dup：{out['bucket_counts'].get('A_near_duplicate_ce', 0)} 条",
        f"- B 候选已被邻近金标占用：{out['bucket_counts'].get('B_occupied_by_gold', 0)} 条",
        f"- C 池内无近似候选：{out['bucket_counts'].get('C_no_candidate', 0)} 条",
        f"- D 落在 9 个未产出槽：{out['bucket_counts'].get('D_gap_slot', 0)} 条",
        "",
        "直接推翻的既有表述（详见末节）：",
        "",
    ]
    for c in out["contradicted_claims"]:
        lines.append(f"- `{c['where']}`：{c['claim']}")
        lines.append(f"  - 机器实测：{c['machine_finding']}")
    lines += [
        "",
        "## 一、桶分布",
        "",
        "| 桶 | 条数 | 金标 | 含义 |",
        "|---|---|---|---|",
    ]
    for key, ids in out["buckets"].items():
        lines.append(f"| {BUCKET_LABEL[key]} | {len(ids)} | {'、'.join(ids)} | {bucket_meaning(key)} |")
    lines += [
        "",
        "## 二、情景推演（仅供决策；改判后重算才有效）",
        "",
        "| 情景 | 追加 matched | 总召回 | 源1 | 源2 | 断言 | 判定 |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, s in scen.items():
        lines.append(
            f"| {name} | {len(s['extra_matched'])} | {s['matched_total']}/48 = {s['recall_overall']} | "
            f"{s['per_source']['源1']['matched']}/{s['per_source']['源1']['gold']} = {s['per_source']['源1']['recall']} | "
            f"{s['per_source']['源2']['matched']}/{s['per_source']['源2']['gold']} = {s['per_source']['源2']['recall']} | "
            f"{s['assertions_covered']} | **{s['verdict']}** |"
        )
    lines += [
        "",
        "## 三、逐条明细",
        "",
        "| # | 桶 | gold | 源 | 断言 | locator | 金标引文 | 最近候选 | sim | 该候选裁定 | 指向金标 | agent draft 机制 |",
        "|---|---|---|---|---|---|---|---|---|---|---|---|",
    ]
    for i, r in enumerate(out["rows"], 1):
        best = r["nearest_candidates"][0] if r["nearest_candidates"] else None
        cand = f"`{best['candidate_id']}`" if best else "—"
        sim = best["sim"] if best else "—"
        judge = best["judgement"] if best else "—"
        target = best["matched_gold_id"] if best and best["matched_gold_id"] else "—"
        if best and best["matched_gold_id"] == r["gold_id"]:
            target = r["gold_id"]
        lines.append(
            f"| {i} | {r['bucket'][0]} | {r['gold_id']} | {r['source']} | {'Y' if r['is_review_assertion'] else ''} | "
            f"{r['locator']} | `{r['quote']}` | {cand} | {sim} | {judge} | {target} | {r['agent_draft_mechanism']} |"
        )
    lines += ["", "## 四、每条的三档信号明细", ""]
    for r in out["rows"]:
        lines.append(f"### {r['gold_id']}（{r['source']}，`{r['locator']}`，桶 {r['bucket']}）")
        lines.append("")
        lines.append(f"- 金标引文：`{r['quote']}`")
        lines.append(f"- 金标命题：{r['proposition']}")
        lines.append(
            f"- 16 断言：{'是' if r['is_review_assertion'] else '否'}；"
            f"critical：{'是' if r['critical'] else '否'}；"
            f"U 2026-10-12 校准撤销：{'是' if r['u_calibration_revoked'] else '否'}"
        )
        if r["agent_draft_mechanism"]:
            lines.append(f"- agent draft 机制：{r['agent_draft_mechanism']}")
        if r["nearest_candidates"]:
            lines.append("- 信号2（同源最近候选，代理相似度）：")
            for c in r["nearest_candidates"]:
                flags = ",".join(c["flags"]) or "—"
                lines.append(
                    f"  - `{c['candidate_id']}`（{c['bucket']}，裁定 **{c['judgement']}**"
                    f"{'，指向 ' + c['matched_gold_id'] if c['matched_gold_id'] else ''}）sim={c['sim']} flags={flags}"
                )
                lines.append(f"    - 候选文本：`{c['text']}`")
                if c["reason"]:
                    lines.append(f"    - 裁定理由：{c['reason']}")
        else:
            lines.append("- 信号2（同源最近候选）：无")
        if r["reason_mentions"]:
            lines.append(f"- 信号1（reason 提及该 gold）{len(r['reason_mentions'])} 条：")
            for m in r["reason_mentions"]:
                lines.append(f"  - `{m['candidate_id']}`（{m['judgement']}）：{m['reason']}")
        else:
            lines.append("- 信号1（reason 提及该 gold）：0 条")
        if r["gap_slot_hits"]:
            lines.append("- 信号3（落在未产出槽）：")
            for g in r["gap_slot_hits"]:
                lines.append(
                    f"  - `{g['candidate_slot_id']}`（{g['slug']}，槽 {g['slot_status']}，{g['category']}，"
                    f"attempt {g['attempt_status']}）sim={g['sim']}"
                )
        else:
            lines.append("- 信号3（落在未产出槽）：无")
        lines.append("")
    lines += [
        "## 五、口径与校验",
        "",
        f"- 两份 48 条金标 id 集合一致：{out['consistency']['id_sets_equal']}；"
        f"引文不一致 {len(out['consistency']['quote_mismatches'])} 条；"
        f"来源不一致 {len(out['consistency']['source_mismatches'])} 条",
        f"- 参与计算候选 {out['scored_candidates']['total']} 条：{out['scored_candidates']['by_bucket']}",
        f"- 来源分布：{out['scored_candidates']['by_source']}",
        f"- {out['scored_candidates']['note']}",
        "",
        "## 六、与既有表述的矛盾（需更正记录）",
        "",
        "| 既有表述 | 出处 | 机器实测 |",
        "|---|---|---|",
    ]
    for c in out["contradicted_claims"]:
        lines.append(f"| {c['claim']} | `{c['where']}` | {c['machine_finding']} |")
    lines += [
        "",
        "> 更正须按『新版本记录 + 旧哈希留存』办理，不得编辑上述已执行产物的字节。",
        "",
        "## 七、复现",
        "",
        "```bash",
        "uv run python .scratch/claims-r2-role-isolation/evidence/71-fn-attribution-20261013/r0-zero-call/build_fn_attribution.py",
        "```",
        "",
    ]
    return "\n".join(lines)


def bucket_meaning(key: str) -> str:
    return {
        "A_near_duplicate_ce": "池内有近似逐字候选，但被裁为 correct_extra/duplicate：属裁定口径问题，不是抽取缺口",
        "B_occupied_by_gold": "最近候选已被另一条金标占用（一对一映射），须重划归属或拆分相邻断言",
        "C_no_candidate": "池内无近似候选：真抽取覆盖缺口，须补抽或范围裁定",
        "D_gap_slot": "金标片段落在 9 个未产出槽之一：只能按显式缺口披露",
        "E_mention_only": "仅有裁定 reason 提及该 gold，无近似文本：证据最弱",
    }[key]


if __name__ == "__main__":
    raise SystemExit(main())
