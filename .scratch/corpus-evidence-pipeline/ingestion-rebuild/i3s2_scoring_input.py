"""I3-2 正式**评分输入派生件**：把批准投影确定性材料化成评分器可读的独立输入（卡点 1 整改）。

设计要点（对齐 `audits/20260919-i32-diagnosis/diagnosis-and-remediation.md` 卡点 1）：

- **不改** r26 的 `query-gold-frozen.jsonl` / 候选 / 裁决件 / 批准投影（原审批继续有效）；
- 派生件写 `i3-2/query-gold-scoring-v1.jsonl`，只**增** 字段：
  `evidence_targets`（= 投影 `approved_required`）与 `supplementary_evidence_targets`（**非必需**）；
- 派生 manifest 记录 lineage：原 query gold / source gold / 批准投影 / 裁决件 / 本程序 / 产出文件 /
  评分器的**路径 + sha256**；任一上游字节或目标集合变化都使派生校验失败；
- 评分入口必须**显式指定** manifest 路径（``load_scoring_input``），禁止依赖旧默认路径或"取最新文件"；
- 自校验 + **变异反例**（改 quote／删 target／把补充升级为必需／改 locator／篡改上游哈希／
  改原金标既有字段）都必须被判失败。

用法::

    # 构建 + 自校验 + 变异反例（默认）
    env -u PYTHONPATH uv run python i3s2_scoring_input.py
    # 只校验现有派生件与 manifest（不重写）
    env -u PYTHONPATH uv run python i3s2_scoring_input.py --check
"""

from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parent
ROOT = BASE.parents[2]
if str(BASE) not in sys.path:
    sys.path.insert(0, str(BASE))
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

QUERY_GOLD = BASE / "query-gold-frozen.jsonl"
SOURCE_GOLD = BASE / "source-gold-frozen.jsonl"
PROJECTION = BASE / "i3-2/evidence-targets-approved.json"
DECISIONS = BASE / "i3-2/evidence-targets-decisions.json"
OUT_JSONL = BASE / "i3-2/query-gold-scoring-v1.jsonl"
MANIFEST = BASE / "i3-2/scoring-input-manifest.json"
SCORER = ROOT / "plugins/corpus/scoring.py"
P1_DRAFT = (
    BASE
    / "audits/20260918-i32-remaining-inventory/p1/query-gold-with-targets.jsonl"
)
_TARGET_KEYS = ("target_id", "quote", "locator", "source_id")
_VERSION = "scoring-input-v1"


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def digest_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def load_jsonl(path: Path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def dump_jsonl(path: Path, records: Sequence[Mapping]) -> None:
    path.write_text(
        "\n".join(json.dumps(record, ensure_ascii=False) for record in records) + "\n",
        encoding="utf-8",
    )


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader, path
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def to_target(target: Mapping[str, object]) -> dict[str, object]:
    out = {key: target[key] for key in _TARGET_KEYS}
    for key in ("role", "constraints", "basis"):
        if key in target:
            out[key] = target[key]
    return out


def materialize(gold: Sequence[Mapping], projection: Mapping) -> list[dict]:
    """确定性材料化：有答案题补 targets，负例原样保留。"""

    proj_by_id = {str(q["query_id"]): q for q in projection["questions"]}
    records: list[dict] = []
    for record in gold:
        qid = str(record["query_id"])
        question = proj_by_id[qid]
        if str(record.get("answer_existence")) != "answerable":
            records.append(dict(record))
            continue
        new = dict(record)
        new["evidence_targets"] = [to_target(t) for t in question.get("approved_required") or []]
        supplementary = [to_target(t) for t in question.get("supplementary") or []]
        if supplementary:
            new["supplementary_evidence_targets"] = supplementary
        records.append(new)
    return records


# ─────────────────────────────────────────── 校验（自校验与变异反例共用同一套）


def validate(
    records: Sequence[Mapping],
    gold: Sequence[Mapping],
    projection: Mapping,
    slots: Sequence[Mapping],
    manifest: Mapping | None,
    applier,
) -> list[str]:
    errors: list[str] = []
    slot_by_id = {str(slot["gold_id"]): slot for slot in slots}
    proj_by_id = {str(q["query_id"]): q for q in projection["questions"]}
    gold_by_id = {str(r["query_id"]): r for r in gold}
    rec_by_id = {str(r["query_id"]): r for r in records}

    if set(rec_by_id) != set(gold_by_id):
        errors.append("派生件与冻结金标的题号集合不一致")
        return errors

    for qid, original in gold_by_id.items():
        record = rec_by_id[qid]
        # 1) 原字段不变（不允许改既有键值、不允许丢键）
        for key, value in original.items():
            if key not in record:
                errors.append(f"{qid}: 派生件丢失原字段 {key}")
            elif record[key] != value:
                errors.append(f"{qid}: 派生件改动了原字段 {key}")
        # 2) 题内 target_id 唯一
        required = list(record.get("evidence_targets") or [])
        supplementary = list(record.get("supplementary_evidence_targets") or [])
        ids = [str(t["target_id"]) for t in required + supplementary]
        if len(ids) != len(set(ids)):
            errors.append(f"{qid}: 题内 target_id 重复")
        # 3) 有答案题：必需集合必须与批准投影逐条一致（顺序亦一致）
        expected = [to_target(t) for t in proj_by_id[qid].get("approved_required") or []]
        if str(original.get("answer_existence")) == "answerable":
            if not required:
                errors.append(f"{qid}: 有答案题缺 evidence_targets")
            if required != expected:
                errors.append(f"{qid}: 必需目标与批准投影不一致（条数或内容）")
            exp_sup = [to_target(t) for t in proj_by_id[qid].get("supplementary") or []]
            if supplementary != exp_sup:
                errors.append(f"{qid}: 补充目标与批准投影不一致")
            # 4) 补充不得混入必需集合
            required_ids = {str(t["target_id"]) for t in required}
            if required_ids & {str(t["target_id"]) for t in supplementary}:
                errors.append(f"{qid}: 补充目标混入了必需集合")
        else:
            if required or supplementary:
                errors.append(f"{qid}: 负例题不应携带任何目标")
        # 5) 每条 target 可回链 source-gold（quote/source/locator 逐字一致）
        for target in required + supplementary:
            basis = target.get("basis") or {}
            slot = slot_by_id.get(str(basis.get("gold_id")))
            if slot is None:
                errors.append(f"{qid}#{target['target_id']}: basis.gold_id 不在 source-gold")
                continue
            item = dict(applier.split_items(slot)).get(basis.get("item_index"))
            if not isinstance(item, Mapping):
                errors.append(f"{qid}#{target['target_id']}: basis.item_index 不存在")
                continue
            if str(target.get("quote")) != str(item.get("quote")):
                errors.append(f"{qid}#{target['target_id']}: quote 与 source-gold 不一致")
            if str(target.get("source_id") or "") != str(slot.get("source_id") or ""):
                errors.append(f"{qid}#{target['target_id']}: source_id 与槽位不一致")
            if list(target.get("locator") or []) != list(applier._locator_tokens(slot, item) or []):
                errors.append(f"{qid}#{target['target_id']}: locator 与 source-gold 定位不一致")

    # 6) manifest lineage 必须与当前上游一致
    if manifest is not None:
        upstream = {
            "query_gold": QUERY_GOLD,
            "source_gold": SOURCE_GOLD,
            "projection": PROJECTION,
            "decisions": DECISIONS,
            "materializer": Path(__file__).resolve(),
            "scorer": SCORER,
        }
        lineage = manifest.get("lineage") or {}
        for name, path in upstream.items():
            entry = lineage.get(name) or {}
            if str(entry.get("path") or "") != str(path.relative_to(ROOT)):
                errors.append(f"manifest.lineage.{name}.path 不符：{entry.get('path')!r}")
            elif entry.get("sha256") != digest(path):
                errors.append(f"manifest.lineage.{name}.sha256 与当前字节不符（上游已变）")
        output = manifest.get("scoring_input") or {}
        if str(output.get("path") or "") != str(OUT_JSONL.relative_to(ROOT)):
            errors.append("manifest.scoring_input.path 不符")
        elif output.get("sha256") != digest_bytes(
            ("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n").encode("utf-8")
        ):
            errors.append("manifest.scoring_input.sha256 与派生件内容不符")
        counts = manifest.get("counts") or {}
        if counts.get("required") != sum(len(r.get("evidence_targets") or []) for r in records):
            errors.append("manifest.counts.required 与派生件不符")
        if counts.get("supplementary") != sum(
            len(r.get("supplementary_evidence_targets") or []) for r in records
        ):
            errors.append("manifest.counts.supplementary 与派生件不符")
    return errors


def mutation_probes(gold, projection, slots, manifest, applier) -> list[dict]:
    """变异反例：每条都必须让校验**失败**（防止校验形同虚设）。"""

    base = materialize(gold, projection)
    assert not validate(base, gold, projection, slots, manifest, applier), "正向对照应通过"

    probes: list[dict] = []

    def record(name: str, records, manifest_override=None, gold_override=None):
        errors = validate(
            records,
            gold_override if gold_override is not None else gold,
            projection,
            slots,
            manifest if manifest_override is None else manifest_override,
            applier,
        )
        probes.append({"probe": name, "failed_as_expected": bool(errors), "errors": errors[:3]})

    mutated = json.loads(json.dumps(base))  # 深拷贝：避免探针之间互相污染
    target = next(
        t for r in mutated for t in (r.get("evidence_targets") or [])
    )
    target["quote"] = target["quote"] + "（篡改）"
    record("quote 被改", mutated)

    mutated = json.loads(json.dumps(base))  # 深拷贝：避免探针之间互相污染
    for r in mutated:
        if r.get("evidence_targets"):
            r["evidence_targets"] = r["evidence_targets"][1:]
            break
    record("必需 target 被删", mutated)

    mutated = json.loads(json.dumps(base))  # 深拷贝：避免探针之间互相污染
    for r in mutated:
        if r.get("supplementary_evidence_targets"):
            r["evidence_targets"] = list(r["evidence_targets"]) + [r["supplementary_evidence_targets"][0]]
            break
    record("补充被升级为必需", mutated)

    mutated = json.loads(json.dumps(base))  # 深拷贝：避免探针之间互相污染
    locator_target = next(t for r in mutated for t in (r.get("evidence_targets") or []))
    locator_target["locator"] = ["page:999"]
    record("locator 被改", mutated)

    tampered = json.loads(json.dumps(manifest))
    tampered["lineage"]["query_gold"]["sha256"] = "0" * 64
    record("上游哈希被篡改", json.loads(json.dumps(base)), manifest_override=tampered)

    mutated = json.loads(json.dumps(base))  # 深拷贝：避免探针之间互相污染
    mutated[0]["question"] = str(mutated[0].get("question")) + "（篡改）"
    record("原金标既有字段被改", mutated)

    return probes


def build_manifest(records: Sequence[Mapping]) -> dict:
    return {
        "artifact": "i3-2-scoring-input-manifest",
        "version": _VERSION,
        "generated_at": now(),
        "status": "frozen_r28",
        "frozen_in": "i0c-r28",
        "purpose": (
            "把批准投影确定性材料化成**唯一**的正式评分输入；评分入口只允许按本清单指定的路径读取，"
            "禁止依赖旧默认路径或选择『最新文件』"
        ),
        "lineage": {
            name: {"path": str(path.relative_to(ROOT)), "sha256": digest(path)}
            for name, path in (
                ("query_gold", QUERY_GOLD),
                ("source_gold", SOURCE_GOLD),
                ("projection", PROJECTION),
                ("decisions", DECISIONS),
                ("materializer", Path(__file__).resolve()),
                ("scorer", SCORER),
            )
        },
        "scoring_input": {
            "path": str(OUT_JSONL.relative_to(ROOT)),
            "sha256": digest_bytes(
                ("\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n").encode("utf-8")
            ),
        },
        "counts": {
            "questions": len(records),
            "answerable": sum(1 for r in records if r.get("answer_existence") == "answerable"),
            "no_answer": sum(1 for r in records if r.get("answer_existence") == "no_answer"),
            "required": sum(len(r.get("evidence_targets") or []) for r in records),
            "supplementary": sum(len(r.get("supplementary_evidence_targets") or []) for r in records),
        },
        "rules": [
            "只增字段：原 query gold 既有键值逐字段不变（校验会比对每题的每个原字段）",
            "必需集合逐条等于批准投影 approved_required（含顺序）",
            "补充证据放 supplementary_evidence_targets，不计入 EvidencePass",
            "负例题（answer_existence=no_answer）不带任何目标（评分器自动 evidence_required=False）",
            "每条 target 的 quote/source_id/locator 可回链到 source-gold 槽位与条目",
            "任一上游哈希或目标集合变化 ⇒ 派生校验失败（score 入口必须先过本校验）",
        ],
        "approval_provenance": {
            "decisions_reviewer": json.loads(DECISIONS.read_text(encoding="utf-8")).get("reviewer"),
            "approval_untouched": True,
            "note": "派生件不改审批原件；原审批件与 r26 冻结件字节不变",
        },
    }


def load_scoring_input(manifest_path: Path) -> list[dict]:
    """评分入口的**唯一**读法：按 manifest 指定的路径读派生件并校验哈希。"""

    manifest = json.loads(Path(manifest_path).read_text(encoding="utf-8"))
    entry = manifest.get("scoring_input") or {}
    path = ROOT / str(entry.get("path") or "")
    if not path.is_file():
        raise RuntimeError(f"派生评分输入缺失：{path}")
    if digest(path) != entry.get("sha256"):
        raise RuntimeError(f"派生评分输入哈希不符：{path}")
    return load_jsonl(path)


def main() -> int:
    check_only = "--check" in sys.argv
    gold = load_jsonl(QUERY_GOLD)
    projection = json.loads(PROJECTION.read_text(encoding="utf-8"))
    slots = load_jsonl(SOURCE_GOLD)
    applier = load_module(BASE / "i3s2_apply_decisions.py", "i3s2_applier_scoring_input")

    if check_only:
        records = load_jsonl(OUT_JSONL)
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
        errors = validate(records, gold, projection, slots, manifest, applier)
        print(json.dumps({"mode": "check", "errors": errors, "ok": not errors}, ensure_ascii=False, indent=2))
        return 0 if not errors else 2

    records = materialize(gold, projection)
    manifest = build_manifest(records)
    OUT_JSONL.write_text(
        "\n".join(json.dumps(r, ensure_ascii=False) for r in records) + "\n", encoding="utf-8"
    )
    # 确定性对照：与 P1 草稿必须逐字节一致（若 P1 草稿仍在）
    p1_match = None
    if P1_DRAFT.is_file():
        p1_match = digest(P1_DRAFT) == digest(OUT_JSONL)
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")

    errors = validate(records, gold, projection, slots, manifest, applier)
    probes = mutation_probes(gold, projection, slots, manifest, applier)
    all_probes_fail = all(p["failed_as_expected"] for p in probes)

    try:
        __import__("plugins.corpus.scoring", fromlist=["gold_from_records"]).gold_from_records(records)
        scorer_ok = True
    except Exception:  # noqa: BLE001
        scorer_ok = False

    print(
        json.dumps(
            {
                "scoring_input": str(OUT_JSONL.relative_to(ROOT)),
                "scoring_input_sha256": digest(OUT_JSONL),
                "manifest": str(MANIFEST.relative_to(ROOT)),
                "counts": manifest["counts"],
                "self_check_errors": errors,
                "self_check_ok": not errors,
                "deterministic_matches_p1": p1_match,
                "scorer_gold_from_records_ok": scorer_ok,
                "mutation_probes": probes,
                "mutation_probes_all_failed_as_expected": all_probes_fail,
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0 if not errors and all_probes_fail and scorer_ok else 2


if __name__ == "__main__":
    raise SystemExit(main())
