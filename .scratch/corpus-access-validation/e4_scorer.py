"""E4 分层评分器（L1–L9）核心：逐层判定 + 缺陷分类 + 确定性自检。

遵循 `docs/data_clean_dos/protocol.md` §3 九层判定链路与 §6.4 准入标准
（评分器在开发集上须能发现 漏提取→L2、误清洗→L3、漏检索→L5、截断→L7/L8、
错用结构→L9）。

**本模块是纯函数评分核心**：不读库、不调模型、不写文件、不 import 任何
DB/LLM 依赖（保证 pytest 无需环境即可运行）。判定的输入分两部分：

- ``score_prep(prep)`` —— 准备/检索层（L1–L5）。``prep`` 由验证/消费侧把
  B0 归因结果（``b0.attr_target`` 的 ``primary_code`` + ``flags``）与证据集
  （是否需要先读 reader/clean 两个视图，见 ``e4_validate.py``）装配好。
- ``score_consumption(target, cons)`` —— 消费/答案层（L6–L9）。``cons`` 由
  run 记录侧（``corpus/ledger.json`` + ``trace.jsonl`` 解析）装配好；``target``
  即金标/样本的 target 字段（quote/period/unit/row/col/verbatim_quote）。

每一层输出 ``status ∈ {pass, fail, n/a}`` + ``evidence_ref``。``n/a`` 表示该层
在该上下文没有可判定的观测（如：仅做生成侧评分时消费层无 run 记录）。
``classify_failure`` 把首个 fail 层映射到五类缺陷。

隔离保证：评分侧证据集（``verbatim_quote``/``period``/``unit`` 等）只作评分
输入；执行代理侧不可读取本目录（E5 实跑按 OS 级读边界隐藏）。
"""

from __future__ import annotations

import re
from typing import Any

# ── 九层链路（protocol §3） ─────────────────────────────────────────────
L1 = "L1"
L2 = "L2"
L3 = "L3"
L4 = "L4"
L5 = "L5"
L6 = "L6"
L7 = "L7"
L8 = "L8"
L9 = "L9"

LAYER_NAMES: dict[str, str] = {
    L1: "source_present",
    L2: "extracted",
    L3: "clean_retained",
    L4: "tool_reachable",
    L5: "offered",
    L6: "requested",
    L7: "fetched",
    L8: "delivered",
    L9: "answer_supported",
}

#: 层 → 五类缺陷（protocol §6.4）。L1 前置、L4 诊断用、L6 模型使用 → 无类。
FIVE_CLASSES: dict[str, str] = {
    L2: "漏提取",
    L3: "误清洗",
    L5: "漏检索",
    L7: "截断",
    L8: "截断",
    L9: "错用结构",
}

# —— 命中 / 失败状态 ——
PASS = "pass"
FAIL = "fail"
NA = "n/a"

#: 空白规约（与 B0 ``norm`` 口径一致：去全部空白含换行/全角/零宽）。
_WS = re.compile(r"[\s\u3000\xa0\u200b]+")
#: 数值 token（可有千分位/小数/百分号/负号括号），供 L9 答案结构核对。
_NUM = re.compile(r"\(?(?:-\s?\d|\d)(?:[\d,\.%]*\d)?%?\)?")


def norm(text: str | None) -> str:
    """去全部空白（含换行/全角空格/零宽空格）后比较，抵消排版换行差异。"""
    return _WS.sub("", text or "")


def value_tokens(text: str | None) -> list[str]:
    """抽取文本里的数值 token（含负号括号/百分号），用于 L9 数值核对。"""
    tokens: list[str] = []
    for m in _NUM.finditer(text or ""):
        tok = m.group(0)
        if tok and tok not in tokens:
            tokens.append(tok)
    return tokens


def classify_failure(layer: str) -> str | None:
    """把首个 fail 层归到五类缺陷之一；L1/L4/L6 无对应类别返回 ``None``。"""
    return FIVE_CLASSES.get(layer)


# ── 准备/检索层 L1–L5 ──────────────────────────────────────────────────
def score_prep(prep: dict[str, Any]) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """对一条目标在生成侧做 L1–L5 逐层判定。

    ``prep`` 字段（由装配方提供）：
    - ``source_present``: bool，证据集层面源页/证据核验（E2）；
    - ``in_reader_contiguous``: bool，引文在 **reader（清洗前）** 拼接里连续；
    - ``reader_tokens_present``: bool，引文分词在 reader 拼接里都存在；
    - ``has_reader_tokens``: bool，引文含 ≥1 个可分词 token（空引文不判提取）；
    - ``in_clean_contiguous``: bool，引文在 **clean（清洗后视图）** 拼接里连续；
    - ``clean_tokens_present``: bool，引文分词在 clean 拼接里都存在；
    - ``single_chunk_hit``: bool，引文落在单个 chunk（可离定点取回）；
    - ``offered_contains``: bool，检索 offered 的 locator 含覆盖该引文的块。

    返回 ``({L1:status,...L5:status}, [evidence])``。
    """
    out: dict[str, str] = {}
    ev: list[dict[str, Any]] = []

    # L1 前置：证据集层面已核验则过，否则 n/a（非生成侧可判）。
    if prep.get("source_present") is True:
        out[L1] = PASS
    else:
        out[L1] = NA
    ev.append(_ev(L1, out[L1], "evidence_set:source_page_verified", {}))

    # L2 extracted（reader 层）：引文连续或分词在 reader 拼接里存在即视为已提取。
    l2 = bool(prep.get("in_reader_contiguous") or prep.get("reader_tokens_present"))
    out[L2] = PASS if l2 else FAIL
    ev.append(
        _ev(
            L2,
            out[L2],
            "corpus_units.raw_text（reader 视图）",
            {
                "in_reader_contiguous": prep.get("in_reader_contiguous"),
                "reader_tokens_present": prep.get("reader_tokens_present"),
            },
        )
    )

    # L3 clean_retained：仅当 L2 已提取才判 clean 是否误排除。
    if out[L2] == PASS:
        l3 = bool(prep.get("in_clean_contiguous") or prep.get("clean_tokens_present"))
        out[L3] = PASS if l3 else FAIL
        ev.append(
            _ev(
                L3,
                out[L3],
                "corpus_units.clean_view（clean 视图）",
                {
                    "in_clean_contiguous": prep.get("in_clean_contiguous"),
                    "clean_tokens_present": prep.get("clean_tokens_present"),
                },
            )
        )
    else:
        out[L3] = NA
        ev.append(_ev(L3, NA, "L2 fail，clean 层无从判定", {}))

    # L4 tool_reachable（诊断用，不阻塞成功）：引文落单块即离线定点可取回。
    out[L4] = PASS if (prep.get("single_chunk_hit") or False) else FAIL
    ev.append(
        _ev(
            L4,
            out[L4],
            "single_chunk existence",
            {"single_chunk_hit": prep.get("single_chunk_hit")},
        )
    )

    # L5 offered：正常流程检索提供的块须含目标候选（不得以整篇文档计入）。
    out[L5] = PASS if (prep.get("offered_contains") or False) else FAIL
    ev.append(
        _ev(
            L5,
            out[L5],
            "ledger.offered locators",
            {"offered_contains": prep.get("offered_contains")},
        )
    )

    return out, ev


# ── 消费/答案层 L6–L9 ────────────────────────────────────────────────
def score_consumption(
    target: dict[str, Any],
    cons: dict[str, Any] | None,
) -> tuple[dict[str, str], list[dict[str, Any]]]:
    """对一条目标在消费侧做 L6–L9 逐层判定。

    ``cons``（由 run 记录侧装配；``None`` 表示无 run 记录 → 全 n/a）：
    - ``requested_covers``: bool，账本 requested 含覆盖目标来源/页的 locator；
    - ``fetched_text``: str，取回的权威片段文本；或 ``fetched_includes_quote``；
    - ``final_input_text``: str，最终模型请求文本（L8 逐字核验）；
    - ``answer_text``: str，最终回答（L9 数值/期间/单位核对）。

    返回 ``({L6..L9:status}, [evidence])``。
    """
    out: dict[str, str] = {}
    ev: list[dict[str, Any]] = []
    if cons is None:
        for ln in (L6, L7, L8, L9):
            out[ln] = NA
            ev.append(_ev(ln, NA, "无 run 记录（生成侧评分，消费层 n/a）", {}))
        return out, ev

    quote = norm(target.get("verbatim_quote") or target.get("quote") or "")
    period = str(target.get("period") or "").strip()
    unit = str(target.get("unit") or "").strip()

    # L6 requested：模型显式请求覆盖该范围。
    out[L6] = PASS if bool(cons.get("requested_covers")) else FAIL
    ev.append(
        _ev(L6, out[L6], "ledger.requested", {"requested_covers": cons.get("requested_covers")})
    )

    # L7 fetched：服务实际取回了含引文的片段。
    fetched_ok = bool(cons.get("fetched_includes_quote")) or (
        quote and quote in norm(str(cons.get("fetched_text") or ""))
    )
    out[L7] = PASS if fetched_ok else FAIL
    ev.append(_ev(L7, out[L7], "ledger.fetched", {"quote_len": len(quote)}))

    # L8 delivered：最终模型输入含引文及其必要依赖（期间/单位）。
    final = norm(str(cons.get("final_input_text") or ""))
    dep_ok = True
    if period:
        dep_ok &= norm(period) in final
    if unit:
        dep_ok &= norm(unit) in final
    l8 = bool(quote and quote in final) and dep_ok
    out[L8] = PASS if l8 else FAIL
    ev.append(
        _ev(
            L8,
            out[L8],
            "trace 最终模型请求",
            {"period_req": bool(period), "unit_req": bool(unit), "dep_ok": dep_ok},
        )
    )

    # L9 answer_supported：回答包含证据的数值/主体/期间/单位，指代正确。
    answer = norm(str(cons.get("answer_text") or ""))
    vals = [
        norm(t)
        for t in value_tokens(str(target.get("verbatim_quote") or target.get("quote") or ""))
    ]
    vals_in_answer = bool(vals) and all(v and (v in answer or quote in answer) for v in vals)
    subject_ok = bool(cons.get("subject_value_present", True))
    l9 = bool(answer) and (vals_in_answer or (quote and quote in answer)) and subject_ok
    out[L9] = PASS if l9 else FAIL
    ev.append(
        _ev(L9, out[L9], "最终回答（数值/期间/单位）", {"values": vals, "subject_ok": subject_ok})
    )

    return out, ev


# ── 组合 ──────────────────────────────────────────────────────────────
def score_target(
    target: dict[str, Any],
    prep: dict[str, Any],
    cons: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """整条目标九层判定 + 首败层 + 缺陷分类。

    返回 dict：``layers``（L1..L9 → status）、``first_fail``（首个 fail 层或
    ``None``）、``failure_class``（``classify_failure`` 或 ``None``）、
    ``fail_layers``、``all_pass``。
    """
    prep_layers, _ = score_prep(prep)
    cons_layers, _ = score_consumption(target, cons)
    layers = {**prep_layers, **cons_layers}
    order = [L1, L2, L3, L4, L5, L6, L7, L8, L9]
    fails = [ln for ln in order if layers[ln] == FAIL]
    return {
        "target_id": target.get("target_id"),
        "layers": layers,
        "first_fail": fails[0] if fails else None,
        "fail_layers": fails,
        "failure_class": classify_failure(fails[0]) if fails else None,
        "all_pass": not fails,
    }


def _ev(layer: str, status: str, evidence_ref: str, detail: dict[str, Any]) -> dict[str, Any]:
    return {
        "layer": layer,
        "name": LAYER_NAMES[layer],
        "status": status,
        "evidence_ref": evidence_ref,
        "detail": detail,
    }


def _minimal_target(target_id: str, quote: str, period: str = "", unit: str = "") -> dict[str, Any]:
    return {
        "target_id": target_id,
        "verbatim_quote": quote,
        "quote": quote,
        "period": period,
        "unit": unit,
        "row": None,
        "col": None,
        "cell": None,
    }


# ── 确定性自检（不依赖 DB，纯函数） ─────────────────────────────────────
def self_check() -> list[dict[str, Any]]:
    """用五类假想目标分别命中五类缺陷，返回每例的预期判定与实测结果。

    每例构造 ``prep``/``cons`` 使某一特定层先 fail，断言
    ``score_target(...).first_fail`` 与预期层一致、``failure_class`` 与
    ``classify_failure(预期层)`` 一致 —— 证明评分器能发现这五类缺陷。
    """
    quote_ok = "我们维持26-28年EPS预测值67.74元，维持强推评级。"

    all_content_present = {
        "in_reader_contiguous": True,
        "reader_tokens_present": True,
        "in_clean_contiguous": True,
        "clean_tokens_present": True,
        "single_chunk_hit": True,
        "offered_contains": True,
    }

    consumed_ok = {
        "requested_covers": True,
        "fetched_text": quote_ok,
        "final_input_text": quote_ok,
        "answer_text": quote_ok,
    }

    cases: list[dict[str, Any]] = []
    # 1) 漏提取 → L2：reader 视图连续与分词都不在。
    cases.append(
        {
            "test": "leak_extraction_L2",
            "expect_layer": L2,
            "target": _minimal_target("t_leak_ext", quote_ok),
            "prep": {
                **all_content_present,
                "source_present": True,
                "in_reader_contiguous": False,
                "reader_tokens_present": False,
                "in_clean_contiguous": False,
                "clean_tokens_present": False,
            },
            "cons": None,
        }
    )
    # 2) 误清洗 → L3：reader 已提取，但 clean 视图丢失引文。
    cases.append(
        {
            "test": "over_clean_L3",
            "expect_layer": L3,
            "target": _minimal_target("t_clean_drop", quote_ok),
            "prep": {
                **all_content_present,
                "source_present": True,
                "in_clean_contiguous": False,
                "clean_tokens_present": False,
            },
            "cons": None,
        }
    )
    # 3) 漏检索 → L5：内容在单块，但检索 offered 未含覆盖块。
    cases.append(
        {
            "test": "miss_offer_L5",
            "expect_layer": L5,
            "target": _minimal_target("t_offer_miss", quote_ok),
            "prep": {**all_content_present, "source_present": True, "offered_contains": False},
            "cons": None,
        }
    )
    # 4) 截断 → L7：服务取回片段缺失引文（取回即截断）。
    cases.append(
        {
            "test": "truncate_L7",
            "expect_layer": L7,
            "target": _minimal_target("t_truncate", quote_ok),
            "prep": {**all_content_present, "source_present": True},
            "cons": {**consumed_ok, "fetched_text": quote_ok[:10]},
        }
    )
    # 5) 错用结构 → L9：证据全送达（含期间/单位依赖），但回答未含所需数值。
    cases.append(
        {
            "test": "misuse_structure_L9",
            "expect_layer": L9,
            "target": _minimal_target("t_structure", quote_ok, period="2026E", unit="元"),
            "prep": {**all_content_present, "source_present": True},
            "cons": {
                **consumed_ok,
                # 期间不在正文引文里，须在送达输入中出现，L8 才会通过。
                "final_input_text": f"{quote_ok} 2026E",
                "answer_text": "维持强推评级，但未给出 EPS 数值。",
            },
        }
    )

    results: list[dict[str, Any]] = []
    for case in cases:
        first_fail = score_target(case["target"], case["prep"], case["cons"])["first_fail"]
        expect_class = classify_failure(case["expect_layer"])
        got_class = classify_failure(first_fail) if first_fail else None
        results.append(
            {
                "test": case["test"],
                "expect_layer": case["expect_layer"],
                "expect_class": expect_class,
                "got_first_fail": first_fail,
                "got_class": got_class,
                "ok": first_fail == case["expect_layer"] and got_class == expect_class,
            }
        )
    return results
