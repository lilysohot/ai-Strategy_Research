#!/usr/bin/env python3
"""Re-runnable self-test for the R2 sign-off sheet parser (never writes anything).

Verifies that ``apply_r2_signoff.py`` reads the sheet exactly as intended:
  * a blank template counts as NOT signed and selects nothing
  * a properly filled sheet yields reviewer, date, the 二选一 pick, the 第 7 条 pick and
    (only under 选项乙) the 三选一 sub-pick
  * ticking "退回修改" is recognised; ticking both boxes of a group is recognised as
    "not exactly one"; an empty 三选一 under 选项乙 is recognised

Idempotent, read-only, zero model calls.
"""

from __future__ import annotations

import importlib.util
import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

HERE = Path(__file__).resolve().parent
TARGET = HERE / "apply_r2_signoff.py"


def load_module(path: Path) -> Any:
    spec = importlib.util.spec_from_file_location("apply_r2_signoff", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    module = load_module(TARGET)
    live = module.SHEET.read_text(encoding="utf-8")
    # 件签认后"现盘"不再是空白版：把签认痕迹按可逆规则还原为空白模板，
    # 并用记录的空白哈希**证明**还原逐字节等于原空白件（还原失败即报错，不静默继续）。
    blank = module.to_blank_template(live)
    if module.sha256_text(blank) != module.BLANK_SHEET_SHA:
        print(
            "FAIL  无法把现盘签认件还原为原空白模板，自检基线不可信："
            f"{module.sha256_text(blank)} != {module.BLANK_SHEET_SHA}"
        )
        return 1
    print(f"基线：签认件可逆还原为原空白模板（{module.BLANK_SHEET_SHA}）")

    def build(
        *,
        reviewer: str = "　xyl　",
        date: str = "2026-10-13",
        accept: bool = True,
        reject: bool = False,
        pair: str | None = None,
        seventh: str | None = None,
        sub: str | None = None,
        marker: str = "\u2611",
    ) -> str:
        """``marker`` 是勾选态写法：仓库既有约定同时存在「☑」与结论行的「x」，两类都必须认。"""
        text = blank.replace("- 复核人：　　　　　　日期：", f"- 复核人：{reviewer}　日期：{date}")
        if accept:
            text = text.replace("☐ 认可并签认 门 v3", f"{marker} 认可并签认 门 v3")
        if reject:
            text = text.replace("☐ 退回修改", f"{marker} 退回修改")
        if pair:
            text = text.replace(f"☐ `{pair}`", f"{marker} `{pair}`")
        if seventh:
            label = "选项甲" if seventh == module.CHOICE_A else "选项乙"
            text = text.replace(f"☐ {label}", f"{marker} {label}")
        if sub:
            text = text.replace(f"☐ `{sub}`", f"{marker} `{sub}`")
        return text

    cases: tuple[tuple[str, Callable[[], str], dict[str, Any]], ...] = (
        (
            "空白版",
            lambda: blank,
            {"reviewer": "", "accepted": False, "pair_selected": [], "seventh_selected": [],
             "sub_selected": []},
        ),
        (
            "签署（甲）",
            lambda: build(pair="NT-I23", seventh=module.CHOICE_A),
            {"reviewer": "xyl", "date": "2026-10-13", "accepted": True, "reject_return": False,
             "pair_selected": ["NT-I23"], "seventh_selected": [module.CHOICE_A], "sub_selected": []},
        ),
        (
            "签署（乙+I46）",
            lambda: build(pair="NT-I24", seventh=module.CHOICE_B, sub="NT-I46"),
            {"reviewer": "xyl", "pair_selected": ["NT-I24"],
             "seventh_selected": [module.CHOICE_B], "sub_selected": ["NT-I46"]},
        ),
        (
            "乙但三选一空",
            lambda: build(pair="NT-I23", seventh=module.CHOICE_B),
            {"seventh_selected": [module.CHOICE_B], "sub_selected": []},
        ),
        (
            "二选一都勾",
            lambda: build(pair="NT-I23", seventh=module.CHOICE_A).replace(
                "☐ `NT-I24`", "\u2611 `NT-I24`"
            ),
            {"pair_selected": ["NT-I23", "NT-I24"]},
        ),
        (
            "退回修改",
            lambda: build(accept=False, reject=True),
            {"accepted": False, "reject_return": True},
        ),
        (
            "x 约定（乙+I45）",
            lambda: build(pair="NT-I23", seventh=module.CHOICE_B, sub="NT-I45", marker="x"),
            {"reviewer": "xyl", "accepted": True, "reject_return": False,
             "pair_selected": ["NT-I23"], "seventh_selected": [module.CHOICE_B],
             "sub_selected": ["NT-I45"]},
        ),
        (
            "x 约定（甲）",
            lambda: build(pair="NT-I24", seventh=module.CHOICE_A, marker="x"),
            {"accepted": True, "pair_selected": ["NT-I24"],
             "seventh_selected": [module.CHOICE_A], "sub_selected": []},
        ),
        (
            "x 约定下未勾项不得误选",
            lambda: build(pair="NT-I23", seventh=module.CHOICE_A, marker="x"),
            {"pair_selected": ["NT-I23"], "sub_selected": []},
        ),
    )

    failures = 0
    for name, builder, expected in cases:
        text = builder()
        parsed = module.parse_sheet(text)
        bad = {key: (value, parsed.get(key)) for key, value in expected.items() if parsed.get(key) != value}
        shown = {
            k: parsed[k]
            for k in ("reviewer", "date", "accepted", "reject_return",
                      "pair_selected", "seventh_selected", "sub_selected")
        }
        print(f"{'PASS' if not bad else 'FAIL'}  {name:14s} " + json.dumps(shown, ensure_ascii=False))
        if bad:
            failures += 1
            print(f"      期望不符：{bad}")

    # 分支校验逻辑（与落地脚本同源）：乙必须带三选一、甲必须留空
    gateway: tuple[tuple[str, str, str, str], ...] = (
        ("甲+空(合法)", module.CHOICE_A, "", "ok"),
        ("乙+I46(合法)", module.CHOICE_B, "NT-I46", "ok"),
        ("乙+空(非法)", module.CHOICE_B, "", "reject"),
        ("甲+有值(非法)", module.CHOICE_A, "NT-I45", "reject"),
    )
    for label, seventh, sub, expectation in gateway:
        selected = [sub] if sub else []
        invalid = (seventh == module.CHOICE_A and selected) or (
            seventh == module.CHOICE_B and len(selected) != 1
        )
        got = "reject" if invalid else "ok"
        ok = got == expectation
        print(f"{'PASS' if ok else 'FAIL'}  分支-{label:12s} -> {got}")
        failures += 0 if ok else 1

    print(f"失败 {failures} 例")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(main())
