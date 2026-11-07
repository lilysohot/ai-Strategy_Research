"""Reproducible arithmetic for explicitly calculated numeric passages.

This is not a semantic truth judge: date/entity/unit applicability still requires
the factual reviewer. It prevents a calculation label from waiving missing inputs.
"""

from __future__ import annotations

import ast
import re
from decimal import Decimal, InvalidOperation, localcontext
from typing import Any

from pydantic import BaseModel, ConfigDict, Field, StrictStr

_CALCULATED = re.compile(
    r"\[计算\]|【计算】|推算值|反推|\b(?:calculated|computed)\b|"
    r"\bderived\s+(?:value|return|price|close|amount)\b",
    re.I,
)
_NUMBER = re.compile(r"(?<![A-Za-z0-9_.])[+-]?\d+(?:,\d{3})*(?:\.\d+)?(?:[%％])?")


def numeric_values(text: str) -> set[str]:
    """Exclude locators/calendar dates; preserve number boundaries and percent scale."""
    text = re.sub(r"https?://\S+|\b\d{4}[-/]\d{1,2}(?:[-/]\d{1,2})?\b", " ", text)
    text = re.sub(r"\d{1,2}月\d{1,2}日|\b\d{1,2}:\d{2}(?::\d{2})?\b", " ", text)
    return {normalize_number(m.group()) for m in _NUMBER.finditer(text)}


def normalize_number(value: str) -> str:
    value = value.replace(",", "").replace("％", "%").lstrip("+")
    percent = value.endswith("%")
    number = Decimal(value.rstrip("%"))
    if not number.is_finite() or len(value) > 60:
        raise ValueError("calculation value must be a finite bounded decimal")
    return format(number.normalize(), "f") + ("%" if percent else "")


def calculation_targets(text: str) -> list[str]:
    """A marker applies to its sentence, including preceding percentages.

    Quoted/negated markers are deliberately not granted exemptions: a numerical
    passage can be removed/rebound or returned unchecked, never certified by label.
    """
    quantities = set()
    sentences = re.split(r"[。！？\n]+|(?<=[.!?])\s+(?=[A-Z])", text)
    for index, paragraph in enumerate(sentences):
        if not _CALCULATED.search(paragraph):
            continue
        if index and re.match(r"\s*(?:以上|上述|These|All of these)", paragraph, re.I):
            paragraph = sentences[index - 1] + "；" + paragraph
        paragraph = re.sub(r"https?://\S+|\b(?:\d{4}[-/])?\d{1,2}[-/]\d{1,2}\b", " ", paragraph)
        paragraph = re.sub(r"\d{4}年|\d{1,2}月\d{1,2}日", " ", paragraph)
        for match in _NUMBER.finditer(paragraph):
            value = match.group()
            tail = paragraph[match.end() :]
            # Bare calendar years, index names (沪深300), section numbers and
            # historical windows are not arithmetic outputs. Decimal/percent
            # values and explicit quantities remain conservative obligations.
            if (
                any(c in value for c in ".,%％")
                or re.match(r"\s*(?:点|元|倍|席|万|亿|units?\b|points?\b|seats?\b)", tail)
                or re.match(r"\s*(?:$|[。；;!])", tail)
            ):
                quantities.add(normalize_number(value))
    return sorted(quantities)


class CalculationInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: StrictStr = Field(min_length=1, max_length=60)
    source_key: StrictStr = Field(min_length=1, max_length=1000)
    source: StrictStr = Field(
        min_length=1,
        max_length=2000,
        description="Copy the exact URL or corpus locator from the attached source pointer. "
        "No annotations, hash suffixes or parentheses.",
    )
    quote: StrictStr = Field(min_length=1, max_length=3000)
    as_of: StrictStr = Field(
        default="",
        max_length=80,
        description="Source date when relevant; must occur verbatim in quote.",
    )


class CalculationCheck(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: StrictStr = Field(
        min_length=1,
        max_length=60,
        description="Exact numerical output, including % when applicable.",
    )
    expression: StrictStr = Field(
        min_length=1,
        max_length=400,
        description="Arithmetic using input names and + - * / parentheses. Percent outputs "
        "use percentage points, e.g. (current / previous - 1) * 100. Constants: 0, 1, 100.",
    )
    inputs: dict[str, CalculationInput] = Field(
        min_length=1,
        max_length=16,
        description="Every operand must quote captured tool evidence, not a researcher report. "
        "For directly sourced numbers use one input and expression equal to its name.",
    )


def _evaluate(expression: str, values: dict[str, Decimal]) -> Decimal:
    tree = ast.parse(expression, mode="eval")
    if len(list(ast.walk(tree))) > 64:
        raise ValueError("calculation expression too complex")
    used = set()

    def evaluate(node: ast.AST) -> Decimal:
        if isinstance(node, ast.Name) and node.id in values:
            used.add(node.id)
            return values[node.id]
        if isinstance(node, ast.Constant) and type(node.value) is int and node.value in (0, 1, 100):
            return Decimal(node.value)
        if isinstance(node, ast.UnaryOp) and isinstance(node.op, (ast.USub, ast.UAdd)):
            result = evaluate(node.operand)
            return -result if isinstance(node.op, ast.USub) else result
        if isinstance(node, ast.BinOp) and isinstance(
            node.op, (ast.Add, ast.Sub, ast.Mult, ast.Div)
        ):
            left, right = evaluate(node.left), evaluate(node.right)
            if isinstance(node.op, ast.Add):
                return left + right
            if isinstance(node.op, ast.Sub):
                return left - right
            if isinstance(node.op, ast.Mult):
                return left * right
            return left / right
        raise ValueError("calculation expression permits only named inputs and arithmetic")

    with localcontext() as context:
        context.prec = 50
        result = evaluate(tree.body)
    if used != set(values):
        raise ValueError("calculation inputs must all participate in the expression")
    return result


def validate_calculations(
    check: dict[str, Any],
    calculations: list[CalculationCheck],
) -> None:
    targets = set(check.get("calculation_targets", []))
    if not targets:
        return
    sources = check.get("calculation_sources", [])
    covered = set()
    try:
        for calculation in calculations:
            target = normalize_number(calculation.value)
            if target not in targets or target in covered:
                raise ValueError("calculation output must uniquely match a bound numeric target")
            values = {}
            for name, operand in calculation.inputs.items():
                if not name.isidentifier():
                    raise ValueError("calculation input name must be an identifier")
                value = normalize_number(operand.value)
                if value not in numeric_values(operand.quote):
                    raise ValueError("calculation input value is absent from its quote")
                if operand.as_of and operand.as_of not in operand.quote:
                    raise ValueError("calculation input date is absent from its quote")
                if not any(
                    source["source_key"] == operand.source_key
                    and source["source"] == operand.source
                    and operand.quote in source["text"]
                    for source in sources
                ):
                    locators = [
                        s["source"] for s in sources if s["source_key"] == operand.source_key
                    ]
                    raise ValueError(
                        f"calculation input {name!r}: quote/source is not bound tool evidence. "
                        f"Copy an exact source locator (no annotations): {locators[:8]}. "
                        "Quote source bytes verbatim; use a numeric value and a pure expression "
                        "such as price * quantity, without explanatory prose."
                    )
                values[name] = Decimal(value.rstrip("%"))
            actual = _evaluate(calculation.expression, values)
            expected = Decimal(calculation.value.replace(",", "").rstrip("%％"))
            exponent = expected.as_tuple().exponent
            if not isinstance(exponent, int):
                raise ValueError("calculation output must be finite")
            tolerance = Decimal(5).scaleb(exponent - 1)
            if not actual.is_finite() or abs(actual - expected) > tolerance:
                raise ValueError("calculation output disagrees with recomputed inputs")
            covered.add(target)
    except (SyntaxError, ArithmeticError, InvalidOperation) as exc:
        raise ValueError("invalid calculation arithmetic") from exc
    if targets != covered:
        raise ValueError(
            f"calculation basis missing for {sorted(targets - covered)}; "
            "supply calculation_checks with quoted inputs and expressions, or return unchecked. "
            "A calculation/estimate label does not waive numerical verification."
        )
