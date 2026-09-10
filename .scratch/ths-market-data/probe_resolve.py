"""M1 前置探测：`meta/tickers/search` 对各类输入的行为。

决定消歧逻辑能否满足验收「茅台 / 600519 / 600519.SH 得到同一结果」：
- 名称子串（茅台）
- 纯代码（600519）
- 带后缀代码（600519.SH）
- 全称（贵州茅台）
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request

BASE = os.environ.get("THS_API_BASE_URL", "https://fuyao.aicubes.cn")
KEY = os.environ.get("THS_API_KEY", "")

QUERIES = ["茅台", "600519", "600519.SH", "贵州茅台", "平安银行", "000001"]


def main() -> None:
    if not KEY:
        print("FAIL: THS_API_KEY 未设置")
        return
    for query in QUERIES:
        url = f"{BASE}/api/meta/tickers/search?{urllib.parse.urlencode({'q': query})}"
        request = urllib.request.Request(url, headers={"X-api-key": KEY})
        try:
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read().decode())
        except Exception as exc:  # noqa: BLE001
            print(f"q={query!r} EXC {type(exc).__name__}: {exc}")
            continue
        data = payload.get("data") or {}
        items = data.get("item") or []
        print(f"q={query!r} code={payload.get('code')} items={len(items)}")
        for row in items[:3]:
            print(
                "    ",
                row.get("thscode"),
                row.get("ticker"),
                row.get("name"),
                row.get("asset_type"),
            )
        print()


if __name__ == "__main__":
    main()
