"""Run-bound market receipts and arithmetic; no server/database dependencies."""

from __future__ import annotations

import contextvars
import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any
from uuid import uuid4


@dataclass
class MarketEvidence:
    context: dict[str, Any]
    directory: Path | None
    records: dict[str, dict[str, Any]] = field(default_factory=dict)
    targets: list[dict[str, Any]] = field(default_factory=list)


_EVIDENCE: contextvars.ContextVar[MarketEvidence | None] = contextvars.ContextVar(
    "market_evidence", default=None
)


def bind_market_evidence(
    context: dict[str, Any] | None,
    directory: Path | None,
) -> contextvars.Token:
    return _EVIDENCE.set(MarketEvidence(deepcopy(context or {}), directory))


def reset_market_evidence(token: contextvars.Token) -> None:
    _EVIDENCE.reset(token)


def _decimal(value: Any) -> Decimal | None:
    try:
        number = Decimal(str(value))
        return number if number.is_finite() else None
    except (InvalidOperation, ValueError):
        return None


def _text(number: Decimal) -> str:
    return format(number, "f").rstrip("0").rstrip(".") if number % 1 else str(int(number))


def _pct(numerator: Decimal, denominator: Decimal) -> str:
    return _text(((numerator / denominator - 1) * 100).quantize(Decimal("0.000001")))


def _record(book: MarketEvidence, tool: str, payload: dict[str, Any]) -> str:
    ref = ("wref:" if tool == "get_watch_targets" else "mref:") + uuid4().hex
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True)
    rows = [
        *(payload.get("items") or payload.get("targets") or []),
        *payload.get("provisional_items", []),
    ]
    symbols = {
        str(r.get("thscode") or r.get("symbol"))
        for r in rows
        if r.get("thscode") or r.get("symbol")
    }
    if tool == "market_history" and rows and payload.get("thscode"):
        symbols.add(str(payload["thscode"]))
    receipt = {
        "ref": ref,
        "tool": tool,
        "symbols": sorted(symbols),
        "as_of": payload.get("retrieved_at")
        or next((r.get("as_of") for r in rows if r.get("as_of")), None),
        "sha256": hashlib.sha256(raw.encode()).hexdigest(),
    }
    if book.directory is not None:
        folder = book.directory / "market"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / f"{ref.split(':')[1]}.json").write_text(
            json.dumps({"receipt": receipt, "result": payload}, ensure_ascii=False),
            encoding="utf-8",
        )
    book.records[ref] = receipt
    return ref


def _recorded_buys(book: MarketEvidence, symbol: str, last: Decimal) -> dict[str, Any]:
    values = book.context.get("values") or {}

    def value(key: str) -> Any:
        entry = values.get(key) or {}
        return (
            entry.get("value")
            if entry.get("status") in {"user_provided", "resolved", "derived"}
            else None
        )

    count = _decimal(value("buy_sell.count"))
    if count is None or count != int(count) or not 0 < count <= 100:
        return {"available": False, "reason": "missing_trade_records"}
    if (
        str(value("buy_sell.truncated")).lower() != "false"
        or _decimal(value("buy_sell.total_count")) != count
    ):
        return {"available": False, "reason": "incomplete_trade_records"}
    cost, quantity = Decimal(0), Decimal(0)
    for i in range(1, int(count) + 1):
        prefix = f"buy_sell.{i}."
        recorded_symbol = str(value(prefix + "symbol") or "").upper()
        if recorded_symbol not in {symbol, symbol.split(".")[0]}:
            continue
        if (
            value(prefix + "side") != "buy"
            or value(prefix + "currency") != "CNY"
            or value(prefix + "market") != "CN"
        ):
            return {"available": False, "reason": "mixed_trades_require_position_reconciliation"}
        price, qty = _decimal(value(prefix + "price")), _decimal(value(prefix + "quantity"))
        if price is None or qty is None or price <= 0 or qty <= 0:
            return {"available": False, "reason": "missing_trade_price_or_quantity"}
        cost += price * qty
        quantity += qty
    if quantity <= 0:
        return {"available": False, "reason": "no_matching_buys"}
    return {
        "available": True,
        "basis": "登记买入合计，不保证涵盖全部实际持仓；未计费用",
        "snapshot_id": book.context.get("snapshot_id"),
        "quantity": _text(quantity),
        "cost_cny": _text(cost),
        "average_cost": _text(cost / quantity),
        "market_value_cny": _text(last * quantity),
        "pnl_cny": _text(last * quantity - cost),
        "pnl_vs_cost_pct": _pct(last * quantity, cost),
    }


def _metrics(book: MarketEvidence, symbol: str, last: Decimal) -> dict[str, Any]:
    targets = []
    for target in book.targets:
        if target.get("symbol") != symbol:
            continue
        threshold = target.get("threshold")
        thresholds = threshold if isinstance(threshold, dict) else {"threshold": threshold}
        for edge, price in thresholds.items():
            level = _decimal(price)
            if level is not None and level > 0:
                targets.append(
                    {
                        "rule_id": target["id"],
                        "edge": edge,
                        "threshold": _text(level),
                        "target_vs_last_pct": _pct(level, last),
                        "last_vs_target_pct": _pct(last, level),
                    }
                )
    return {
        "last_price": _text(last),
        "targets": targets,
        "denominators": {
            "target_vs_last_pct": "(目标价/最新价-1)*100",
            "last_vs_target_pct": "(最新价/目标价-1)*100",
        },
        "recorded_buys": _recorded_buys(book, symbol, last),
    }


def record_market_result(tool: str, result: dict[str, Any]) -> dict[str, Any]:
    book = _EVIDENCE.get()
    if book is None or result.get("ok") is not True:
        return result
    payload = deepcopy(result)
    for row in [*payload.get("items", []), *payload.get("provisional_items", [])]:
        display = {}
        for key, label in (("turnover", "turnover_yi_cny"), ("volume", "volume_yi_shares")):
            number = _decimal(row.get(key))
            if number is not None:
                display[label] = _text(number / Decimal(100000000))
        row["display_numbers"] = display
        last = _decimal(row.get("last_price"))
        if tool == "market_quote" and last is not None and last > 0:
            row["monitoring_metrics"] = _metrics(book, str(row.get("thscode")), last)
    payload["evidence_ref"] = _record(book, tool, payload)
    return payload


def record_watch_state(result: dict[str, Any]) -> dict[str, Any]:
    book = _EVIDENCE.get()
    if book is None or result.get("ok") is not True:
        return result
    payload = deepcopy(result)
    book.targets = deepcopy(payload.get("targets") or [])
    payload["evidence_ref"] = _record(book, "get_watch_targets", payload)
    return payload


def bind_intent_evidence(intents: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Resolve only receipts actually returned in this Run, before any writes."""
    book = _EVIDENCE.get()
    if book is None:
        raise ValueError("当前运行没有行情证据上下文")
    if not intents or not all(isinstance(item, dict) for item in intents):
        raise ValueError("需要非空监控操作列表")
    bound = deepcopy(intents)
    for item in bound:
        refs = item.get("evidence_refs")
        if (
            not isinstance(refs, list)
            or not refs
            or not all(isinstance(ref, str) and ref in book.records for ref in refs)
        ):
            raise ValueError(
                "evidence_refs 必须引用本轮 market_quote/market_history/get_watch_targets 返回的 evidence_ref"
            )
        receipts = [book.records[ref] for ref in dict.fromkeys(refs)]
        spec = item.get("spec") or {}
        if not isinstance(spec, dict):
            raise ValueError("spec 必须是对象")
        target = next((t for t in book.targets if t["id"] == item.get("rule_id")), {})
        symbol = spec.get("symbol") or target.get("symbol")
        if symbol and not any(symbol in receipt["symbols"] for receipt in receipts):
            raise ValueError("引用的行情或目标回执不包含本次监控标的")
        price_write = item.get("operation") == "create" or any(
            key in spec for key in ("threshold", "direction", "symbol")
        )
        if price_write and not any(
            r["tool"] in {"market_quote", "market_history"} and symbol in r["symbols"]
            for r in receipts
        ):
            raise ValueError("新增或重新提交价格条件必须引用本轮该标的的行情回执")
        item["evidence_receipts"] = deepcopy(receipts)
    return bound
