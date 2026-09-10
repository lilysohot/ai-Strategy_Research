"""M0 契约探测（第三轮）：financials period 字面量 + historical 时间参数格式。

第二轮结论（已确认）：
- prices/snapshot 与 valuations 参数名为 `thscodes`（复数，逗号分隔多只），data 含 timestamp/total/item
- corporate-actions 的 data 信封为 {thscode, ticker, item}，**无 timestamp**
- financials 报错 "period (annual / quarterly)" => period 是字面量，不是日期
- historical 报错 "Missing required parameter: start" => 需探 start/end 格式

本轮目标：
1. 验证 period=annual / quarterly 是否可用，以及是否还需 start/end
2. 验证 historical 的 start/end 格式（毫秒时间戳 vs yyyyMMdd）

用法：
    set -a && . ./.env && set +a && python3 .scratch/ths-market-data/probe_contract.py
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("THS_API_BASE_URL", "https://fuyao.aicubes.cn")
KEY = os.environ.get("THS_API_KEY", "")

FIN = "/api/a-share/financials/income-statements"
HIST = "/api/a-share/prices/historical"


def get(path: str, params: dict[str, str]) -> tuple[int, dict | None, str]:
    url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
    req = urllib.request.Request(url, headers={"X-api-key": KEY, "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=20) as resp:
            status, raw = resp.status, resp.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as exc:
        status, raw = exc.code, exc.read().decode("utf-8", "replace")
    except Exception as exc:  # noqa: BLE001
        return -1, None, f"{type(exc).__name__}: {exc}"
    try:
        return status, json.loads(raw), raw
    except json.JSONDecodeError:
        return status, None, raw


def show(label: str, path: str, params: dict[str, str], *, peek: int = 2) -> None:
    status, payload, raw = get(path, params)
    print(f"--- {label}\n    GET {path}?{urllib.parse.urlencode(params)}")
    if payload is None:
        print(f"    HTTP {status} non-json: {raw[:200]}")
        return
    code = payload.get("code")
    print(f"    HTTP {status} code={code} message={payload.get('message')!r}")
    data = payload.get("data")
    if code != 0 or not isinstance(data, dict):
        return
    print(f"    data_keys={list(data.keys())}")
    item = data.get("item")
    if isinstance(item, list):
        print(f"    items={len(item)}")
        for row in item[:peek]:
            print(f"      {json.dumps(row, ensure_ascii=False)[:280]}")
    elif isinstance(item, dict):
        print(f"    item={json.dumps(item, ensure_ascii=False)[:300]}")
    print()


def main() -> None:
    if not KEY:
        print("FAIL: THS_API_KEY 未设置")
        return

    # 1) financials: period 字面量
    for period in ("annual", "quarterly"):
        show(f"financials period={period}", FIN, {"thscode": "600519.SH", "period": period}, peek=1)

    # 2) historical: start/end 格式（毫秒 vs yyyyMMdd）
    ms = {"start": "1735660800000", "end": "1767196800000"}  # 2025-01-01 ~ 2025-12-31
    ymd = {"start": "20250101", "end": "20251231"}
    for tag, window in (("ms", ms), ("yyyymmdd", ymd)):
        show(
            f"historical start/end={tag}",
            HIST,
            {"thscode": "600519.SH", "interval": "1d", **window},
            peek=2,
        )

    # 3) historical: 不带 interval 是否被接受
    show("historical 无 interval（ms）", HIST, {"thscode": "600519.SH", **ms}, peek=1)


if __name__ == "__main__":
    main()
