#!/usr/bin/env python3
"""Land the signed R2 package (gate v3 + contract v4.3 + 7 re-adjudications) — write-once.

Signing instrument (the only signable sheet):
  ``74-r2-gate-v3-contract-v43-draft-20261013/r0-zero-call/r2-signoff-review.md``

The sheet carries three human decisions; all three are read from it, none is prefilled:
  * 二选一  : NT-I23 or NT-I24 (they share one candidate; exactly one may be kept)
  * 第 7 条 : I36_question_form or one_of_u_calibration_revoked
  * 子选择  : when 选项乙 is chosen, exactly one of NT-I45/NT-I46/NT-I47

Guards (fail closed):
  * the sheet must be actually signed (filled 复核人, checked box); the untouched template is
    rejected by both the blank-hash check and ``artifact_state``
  * signer name and date come from the sheet
  * the three draft sha256 embedded in the sheet must match the drafts on disk
  * each decision must have exactly one (or, for 选项甲, zero) checked box
  * the 11 adjudication stubs collapse to exactly 7 records with pairwise-distinct candidates
  * outputs are written only into this directory via ``write_once``; no input byte changes

Zero model calls. ``--no-write`` performs every check and prints the outcome.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
E75 = HERE.parent
CLAIMS = E75.parent.parent
REPO_ROOT = HERE.parents[4]
sys.path.insert(0, str(REPO_ROOT))

from tools.evidence_guard import artifact_state, write_once  # noqa: E402

EV = CLAIMS / "evidence"
DRAFT_DIR = EV / "74-r2-gate-v3-contract-v43-draft-20261013" / "r0-zero-call"
SHEET = DRAFT_DIR / "r2-signoff-review.md"
DRAFT_GATE = DRAFT_DIR / "gate-v3.proposed.json"
DRAFT_CONTRACT = DRAFT_DIR / "scoring-contract-v4.3.proposed.json"
DRAFT_READJUDICATION = DRAFT_DIR / "re-adjudication-draft.json"

GATE_V2 = EV / "28-items-only-quality-gate-20261010" / "r0-zero-call" / "preregistered-gate-v2.json"
CONTRACT_V42 = EV / "58-contract-v42-signed-20261012" / "r0-zero-call" / "scoring-contract-v4.2.json"

BLANK_SHEET_SHA = "sha256:37b3951b29e34a0d1ee1ee6fbac3c4dbc6749c88e32eac0f5b1d2c984e0b0621"

CHOICE_A = "I36_question_form"
CHOICE_B = "one_of_u_calibration_revoked"
PAIR_IDS = ("NT-I23", "NT-I24")
SUBTREE_IDS = ("NT-I45", "NT-I46", "NT-I47")
# 勾选标记：仓库既有约定是「☑」或结论行的「x」（见 tools/evidence_guard._TEXT_SIGNATURE_PATTERNS），
# 本件两类都接受；裸 x/X 需前置非字母数字字符，避免误吃正文里的字母。
MARKER_REGEX = re.compile(r"(?<![0-9A-Za-z])(?:\u2611|\u2612|\[[xX]\]|\u2713|X|x)")
MARKER_WINDOW = 8

REVIEWER_LINE = re.compile(r"复核人：([^\n]*)")
DATE_LINE = re.compile(r"日期[:：]?\s*([0-9]{4}-[0-9]{2}-[0-9]{2})")


def sha256(path: Path) -> str:
    return "sha256:" + hashlib.sha256(path.read_bytes()).hexdigest()


def dumps(payload: Any) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def sha256_text(text: str) -> str:
    return "sha256:" + hashlib.sha256(text.encode("utf-8")).hexdigest()


_BOX_TOKENS = (
    "`NT-I23`",
    "`NT-I24`",
    "`NT-I45`",
    "`NT-I46`",
    "`NT-I47`",
    "选项甲",
    "选项乙",
    "认可并签认 门 v3",
    "退回修改",
)
_BLANK_REVIEWER_LINE = "- 复核人：　　　　　　日期："


def to_blank_template(text: str) -> str:
    """把已签件按可逆规则还原成原空白模板（用于证明签认只动了签认栏）。"""
    lines: list[str] = []
    for line in text.splitlines():
        if line.startswith("- 复核人："):
            line = _BLANK_REVIEWER_LINE
        for token in _BOX_TOKENS:
            line = re.sub(
                rf"(?:\u2611|\u2612|\u2713|\[[xX]\]|x|X)(\s+)(?={re.escape(token)})",
                r"☐\1",
                line,
            )
        lines.append(line)
    return "\n".join(lines) + ("\n" if text.endswith("\n") else "")


def _marker_before(line: str, index: int) -> bool:
    """True when a check marker sits in the window immediately before ``index`` on ``line``."""
    if index < 0:
        return False
    return bool(MARKER_REGEX.search(line[max(index - MARKER_WINDOW, 0) : index]))


def _box_checked(line: str, label: str) -> bool:
    """True only when the marker sits immediately before ``label`` on the same line."""
    return _marker_before(line, line.find(label))


def _selected_options(line: str, options: tuple[str, ...]) -> list[str]:
    """Per-option box state: only the option's own preceding window counts."""
    return [option for option in options if option in line and _marker_before(line, line.find(option))]


def _line_starting_with(text: str, prefix: str) -> str:
    return next((line for line in text.splitlines() if line.strip().startswith(prefix)), "")


def parse_sheet(text: str) -> dict[str, Any]:
    reviewer_tail = REVIEWER_LINE.search(text)
    reviewer = ""
    date = ""
    if reviewer_tail:
        tail = reviewer_tail.group(1)
        reviewer = re.split(r"日期[:：]?", tail)[0].strip(" \u3000：:\t")
        found = DATE_LINE.search(tail)
        date = found.group(1) if found else ""
    if not date:
        found = DATE_LINE.search(text)
        date = found.group(1) if found else ""

    conclusion_line = _line_starting_with(text, "- 结论：")
    accepted = _box_checked(conclusion_line, "认可并签认")
    reject_return = _box_checked(conclusion_line, "退回修改")

    pair_line = _line_starting_with(text, "- 二选一")
    seventh_line = _line_starting_with(text, "- 第 7 条选择")
    sub_line = _line_starting_with(text, "- 仅当选")

    embedded: dict[str, str] = {}
    for name, key in (
        ("gate-v3.proposed.json", "gate"),
        ("scoring-contract-v4.3.proposed.json", "contract"),
        ("re-adjudication-draft.json", "readjudication"),
    ):
        match = re.search(rf"{re.escape(name)}`? \| `(sha256:[0-9a-f]{{64}})`", text)
        if match:
            embedded[key] = match.group(1)

    return {
        "reviewer": reviewer,
        "date": date,
        "accepted": accepted,
        "reject_return": reject_return,
        "pair_line": pair_line,
        "seventh_line": seventh_line,
        "sub_line": sub_line,
        "pair_selected": _selected_options(pair_line, PAIR_IDS),
        "seventh_selected": _selected_options(seventh_line, (CHOICE_A, CHOICE_B)),
        "sub_selected": _selected_options(sub_line, SUBTREE_IDS),
        "embedded": embedded,
    }


def collect_problems(parsed: dict[str, Any], sheet_sha: str, state: str,
                     draft_hashes: dict[str, str]) -> list[str]:
    problems: list[str] = []
    if sheet_sha == BLANK_SHEET_SHA:
        problems.append("签认件仍是空白版（sha 未变），拒绝落地")
    if state != "signed":
        problems.append(f"签认件未检测到实际签认（artifact_state={state}），拒绝落地")
    if not parsed["reviewer"]:
        problems.append("复核人姓名为空，拒绝落地（不代签、不预填）")
    if not parsed["date"]:
        problems.append("日期为空，拒绝落地")
    if not parsed["accepted"]:
        problems.append("结论行未勾选『认可并签认』，拒绝落地")
    if parsed["reject_return"]:
        problems.append("结论行勾选了『退回修改』，拒绝落地")
    if not parsed["pair_line"] or not parsed["seventh_line"]:
        problems.append("签认件缺少『二选一』或『第 7 条选择』勾选栏，拒绝落地")
    if len(parsed["pair_selected"]) != 1:
        problems.append(f"二选一必须且只能勾一项，当前 {parsed['pair_selected'] or '无'}")
    if len(parsed["seventh_selected"]) != 1:
        problems.append(f"第 7 条必须且只能勾一项，当前 {parsed['seventh_selected'] or '无'}")
    if parsed["seventh_selected"] == [CHOICE_A] and parsed["sub_selected"]:
        problems.append(f"选『选项甲』时三选一栏必须留空，当前 {parsed['sub_selected']}")
    if parsed["seventh_selected"] == [CHOICE_B] and len(parsed["sub_selected"]) != 1:
        problems.append(f"选『选项乙』时三选一必须且只能勾一项，当前 {parsed['sub_selected'] or '无'}")
    for key, value in parsed["embedded"].items():
        if draft_hashes.get(key) != value:
            problems.append(
                f"草案哈希与签认件不符：{key} 件内 {value} / 现盘 {draft_hashes.get(key)}，拒绝落地"
            )
    if len(parsed["embedded"]) != 3:
        problems.append(f"签认件未嵌入全部三份草案哈希（找到 {sorted(parsed['embedded'])}）")
    return problems


def select_adjudications(
    adjudications: list[dict[str, Any]], pair: str, seventh: str, sub: str
) -> list[dict[str, Any]]:
    kept = [r for r in adjudications if r["keep_if"]["rule"] == "always"]
    kept += [
        r
        for r in adjudications
        if r["keep_if"]["rule"] == "pair_choice" and r["proposed_matched_gold_id"] == pair
    ]
    target = "NT-I36" if seventh == CHOICE_A else sub
    kept += [
        r
        for r in adjudications
        if r["keep_if"]["rule"] == "seventh_choice" and r["proposed_matched_gold_id"] == target
    ]
    return kept


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--no-write", action="store_true")
    args = parser.parse_args()

    sheet_text = SHEET.read_text(encoding="utf-8")
    sheet_sha = sha256(SHEET)
    state = artifact_state(SHEET)
    parsed = parse_sheet(sheet_text)

    draft_hashes = {
        "gate": sha256(DRAFT_GATE),
        "contract": sha256(DRAFT_CONTRACT),
        "readjudication": sha256(DRAFT_READJUDICATION),
    }
    problems = collect_problems(parsed, sheet_sha, state, draft_hashes)

    targets = (
        HERE / "gate-v3.json",
        HERE / "scoring-contract-v4.3.json",
        HERE / "re-adjudication.json",
        HERE / "signoff-record.json",
        HERE / "README.md",
        HERE / "MANIFEST.json",
    )
    for target in targets:
        if target.exists():
            problems.append(f"输出目标已存在（write-once）：{target.name}")

    draft_readjudication = json.loads(DRAFT_READJUDICATION.read_text(encoding="utf-8"))
    kept: list[dict[str, Any]] = []
    if not problems:
        pair = parsed["pair_selected"][0]
        seventh = parsed["seventh_selected"][0]
        sub = parsed["sub_selected"][0] if parsed["sub_selected"] else ""
        kept = select_adjudications(draft_readjudication["adjudications"], pair, seventh, sub)
        if len(kept) != 7:
            problems.append(f"收敛后的改判应为 7 条，实际 {len(kept)} 条")
        candidates = [r["candidate_id"] for r in kept]
        if len(set(candidates)) != len(candidates):
            problems.append(f"收敛后候选重复，违反一对一：{candidates}")
        golds = [r["proposed_matched_gold_id"] for r in kept]
        if len(set(golds)) != len(golds):
            problems.append(f"收敛后金标重复：{golds}")

    if problems:
        print(json.dumps({"status": "REFUSED", "problems": problems}, ensure_ascii=False, indent=2))
        return 3

    reviewer = parsed["reviewer"]
    signed_on = parsed["date"]
    pair = parsed["pair_selected"][0]
    seventh = parsed["seventh_selected"][0]
    sub = parsed["sub_selected"][0] if parsed["sub_selected"] else ""

    gate = json.loads(DRAFT_GATE.read_text(encoding="utf-8"))
    gate["status"] = "frozen_before_execution"
    gate["quality_requirements_status"] = "signed"
    gate["countersignature"] = {
        "required": True,
        "status": "signed",
        "reviewer": reviewer,
        "signed_on": signed_on,
    }
    gate["revision_history"][-1]["signed_by"] = reviewer
    gate["revision_history"][-1]["signed_on"] = signed_on
    gate_text = dumps(gate)
    gate_sha = "sha256:" + hashlib.sha256(gate_text.encode("utf-8")).hexdigest()

    contract = json.loads(DRAFT_CONTRACT.read_text(encoding="utf-8"))
    contract["status"] = "frozen_signed"
    contract["revision_history"][-1]["signed_by"] = reviewer
    contract["revision_history"][-1]["status"] = "frozen_signed"
    authority = contract["threshold_source"]["authority_source"]
    authority["sha256"] = gate_sha
    authority.pop("pin_status", None)
    contract["threshold_source"]["effective"]["authority_pin_note"] = (
        f"已回填门 v3 签认版字节哈希 {gate_sha}"
    )
    contract["signoff"] = {
        "signed_by": reviewer,
        "signed_on": signed_on,
        "statement": (
            "核准门 v3 与契约 v4.3 作为 items-only 质量门的已签认度量基准：哨兵清单由 16 项缩为 11 项，"
            "契约 matching.items 增补『上下文唯一可恢复』读法。六项阈值逐字不变，未放宽任何门槛。"
        ),
        "instrument": {"path": str(SHEET.relative_to(REPO_ROOT)), "sha256": sheet_sha},
        "scope_note": "签认只定读路径、口径与度量口径；不代表出分、不代表复验通过、不代表发布或语境完整。",
        "reviewer_remark": "",
        "remark_note": "备注为空 ⇒ 草案按原样接受；不等同逐条确认。",
    }

    for record in kept:
        record["judgement"] = "matched"
        record["matched_gold_id"] = record["proposed_matched_gold_id"]
        record["reviewer"] = reviewer
        record["reason"] = (
            f"{record['proposed_reason']}（理由依据：签认件第四节 {record['proposed_matched_gold_id']} 行，"
            f"由 {reviewer} 于 {signed_on} 具名确认）"
        )
        record["status"] = "named_signed"
        record["proposed_reviewer"] = reviewer
        record["proposed_signed_on"] = signed_on
    landed = {
        "schema_version": "r2-readjudication-1",
        "created_on": signed_on,
        "zero_model_calls": True,
        "status": "named_signed",
        "authority_note": "七条改判由具名裁定人确认；原始候选 11 字段逐字保留，历史裁定见 previous_*/superseded_* 字段。",
        "instrument": {"path": str(SHEET.relative_to(REPO_ROOT)), "sha256": sheet_sha},
        "selection": {
            "pair": pair,
            "seventh": seventh,
            "seventh_sub": sub,
            "signed_by": reviewer,
            "signed_on": signed_on,
        },
        "adjudications": kept,
        "candidate_ids": [r["candidate_id"] for r in kept],
        "matched_gold_ids": [r["proposed_matched_gold_id"] for r in kept],
    }

    record = {
        "schema_version": "r2-signoff-record-1",
        "created_on": signed_on,
        "zero_model_calls": True,
        "signed_by": reviewer,
        "signed_on": signed_on,
        "instrument": {
            "path": str(SHEET.relative_to(REPO_ROOT)),
            "sha256": sheet_sha,
            "superseded_unsigned_sha256": BLANK_SHEET_SHA,
            "covered": ["gate_v3", "contract_v4.3", "seven_re_adjudications"],
            "blank_template_reproduced": BLANK_SHEET_SHA,
            "marker_conventions_accepted": ["\u2611", "\u2612", "[x]", "\u2713", "x/X（仓库既有结论行约定）"],
        },
        "human_decisions_read_from_sheet": {
            "pair": {"selected": pair, "rejected": [i for i in PAIR_IDS if i != pair]},
            "seventh": {
                "selected": seventh,
                "rejected": [c for c in (CHOICE_A, CHOICE_B) if c != seventh],
                "sub_selected": sub,
            },
            "contract_invalid_option": "I23_or_I24_double_assignment（不列入勾选）",
        },
        "outputs": {
            "gate_v3": {"file": "gate-v3.json", "sha256": gate_sha, "status": gate["status"]},
            "contract_v4.3": {"file": "scoring-contract-v4.3.json", "status": contract["status"]},
            "re_adjudication": {
                "file": "re-adjudication.json",
                "status": landed["status"],
                "count": len(kept),
            },
        },
        "thresholds_untouched": {
            "target_recall_overall_min": gate["quality_requirements"]["target_recall_overall_min"],
            "target_recall_per_source_min": gate["quality_requirements"]["target_recall_per_source_min"],
            "candidate_precision_min": gate["quality_requirements"]["candidate_precision_min"],
            "accepted_records_total_min": gate["quality_requirements"]["accepted_records_total_min"],
            "accepted_records_per_source_min": gate["quality_requirements"][
                "accepted_records_per_source_min"
            ],
            "unresolved_candidates_max": gate["quality_requirements"]["unresolved_candidates_max"],
            "threshold_relaxation_after_execution_allowed": gate["scope_constraints"][
                "threshold_relaxation_after_execution_allowed"
            ],
        },
        "bytes_left_untouched": {
            str(GATE_V2.relative_to(REPO_ROOT)): sha256(GATE_V2),
            str(CONTRACT_V42.relative_to(REPO_ROOT)): sha256(CONTRACT_V42),
            **{
                str(p.relative_to(REPO_ROOT)): sha256(p)
                for p in (DRAFT_GATE, DRAFT_CONTRACT, DRAFT_READJUDICATION)
            },
        },
        "in_place_edits": 0,
        "outstanding_after_signoff": [
            "据实重算门 33 出分并形成**新 verdict**；旧 verdict（FAIL）不改写",
            "评分器按契约读阈值（OPEN-1=A 的兑现）——本条独立于本签认",
            "发布路径（O1『显式缺口』）仍待单独裁定与实施",
            "本签认不授权任何模型调用、发布、查询、delivery 或 context_use",
        ],
        "note": "签认只签条款：不等于出分、不等于复验通过、不等于可发布。",
    }

    print(
        json.dumps(
            {
                "status": "READY",
                "reviewer": reviewer,
                "signed_on": signed_on,
                "sheet_sha256": sheet_sha,
                "pair": pair,
                "seventh": seventh,
                "seventh_sub": sub,
                "landed_adjudications": len(kept),
                "gate_v3_sha256": gate_sha,
                "contract_status": contract["status"],
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    if args.no_write:
        return 0

    write_once(HERE / "gate-v3.json", gate_text, reason="门 v3 签认落地")
    write_once(HERE / "scoring-contract-v4.3.json", contract, reason="契约 v4.3 签认落地")
    write_once(HERE / "re-adjudication.json", landed, reason="R2 改判签认落地")
    write_once(HERE / "signoff-record.json", record, reason="R2 签认落地记录")
    write_once(HERE / "README.md", render_readme(record), reason="R2 签认落地说明")
    blank_template = to_blank_template(sheet_text)
    if sha256_text(blank_template) != BLANK_SHEET_SHA:
        raise SystemExit("还原空白模板失败，拒绝落地（签认件可能被改动了签认栏以外的内容）")
    write_once(
        HERE / "blank-sheet-template.md",
        blank_template,
        reason="签认件空白模板（已由空白哈希验证）",
    )
    manifest = {
        "schema_version": "r2-signed-manifest-1",
        "created_on": signed_on,
        "zero_model_calls": True,
        "inputs": {
            str(SHEET.relative_to(REPO_ROOT)): sheet_sha,
            "drafts": draft_hashes,
            str(GATE_V2.relative_to(REPO_ROOT)): sha256(GATE_V2),
            str(CONTRACT_V42.relative_to(REPO_ROOT)): sha256(CONTRACT_V42),
        },
        "outputs": {
            item.name: sha256(item)
            for item in sorted(HERE.iterdir())
            if item.is_file() and item.name != "MANIFEST.json"
        },
        "in_place_edits": 0,
    }
    write_once(HERE / "MANIFEST.json", manifest, reason="R2 签认落地清单")
    return 0


def render_readme(record: dict[str, Any]) -> str:
    decisions = record["human_decisions_read_from_sheet"]
    lines = [
        "# R2 · 已签认版（门 v3 + 契约 v4.3 + 7 条改判）",
        "",
        f"- 签署人：**{record['signed_by']}**　日期：**{record['signed_on']}**",
        f"- 签署工具：`{record['instrument']['path']}` `{record['instrument']['sha256']}`",
        f"- 二选一：**{decisions['pair']['selected']}**（未选：{decisions['pair']['rejected']}）",
        f"- 第 7 条：**{decisions['seventh']['selected']}**"
        f"{'（具体条目 ' + decisions['seventh']['sub_selected'] + '）' if decisions['seventh']['sub_selected'] else ''}",
        f"- 门 v3：`{record['outputs']['gate_v3']['file']}` `{record['outputs']['gate_v3']['sha256']}`",
        f"- 契约 v4.3：`{record['outputs']['contract_v4.3']['file']}`"
        f"（`{record['outputs']['contract_v4.3']['status']}`）",
        f"- 改判：`{record['outputs']['re_adjudication']['file']}`"
        f"（`{record['outputs']['re_adjudication']['status']}`，{record['outputs']['re_adjudication']['count']} 条）",
        "",
        "## 阈值确认（逐字未改）",
        "",
    ]
    for key, value in record["thresholds_untouched"].items():
        lines.append(f"- `{key}` = `{value}`")
    lines += ["", "## 签认之后仍未完成（不得读成已过门）", ""]
    lines += [f"- {item}" for item in record["outstanding_after_signoff"]]
    lines += ["", f"> {record['note']}"]
    return "\n".join(lines) + "\n"


if __name__ == "__main__":
    raise SystemExit(main())
