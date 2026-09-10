"""M0 capability 自检：探测同花顺 fuyao 五个 capability 是否已开通。

用法（凭据只从环境读取，脚本不打印 key）：
    set -a && . ./.env && set +a && python3 .scratch/ths-market-data/probe_capability.py

判定：
    code=0      -> 已开通且调用成功
    code=2001   -> 未认证（key 无效）
    code=2003   -> 无该 capability 权限
    code=1001.. -> 参数缺失/格式错（说明权限已开通，只是本次探测参数不全）
    HTTP 429    -> 限流（重试即可，非权限问题）
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.parse
import urllib.request

BASE = os.environ.get("THS_API_BASE_URL", "https://fuyao.aicubes.cn")
KEY = os.environ.get("THS_API_KEY", "")

PROBES: list[tuple[str, str, dict[str, str]]] = [
    ("meta", "/api/meta/tickers/search", {"q": "茅台"}),
    ("prices", "/api/a-share/prices/snapshot", {"thscode": "600519.SH"}),
    ("valuations", "/api/a-share/valuations/snapshot", {"thscode": "600519.SH"}),
    ("financials", "/api/a-share/financials/income-statements", {"thscode": "600519.SH"}),
    (
        "corporate-actions",
        "/api/a-share/corporate-actions/adjustment-factors",
        {"thscode": "600519.SH"},
    ),
]


def summarize(data: object) -> str:
    if not isinstance(data, dict):
        return str(data)[:160]
    item = data.get("item")
    head = f"data_keys={list(data.keys())} timestamp={data.get('timestamp')}"
    if isinstance(item, list):
        first = json.dumps(item[0], ensure_ascii=False)[:180] if item else "[]"
        return f"{head} items={len(item)} first={first}"
    if isinstance(item, dict):
        return f"{head} item={json.dumps(item, ensure_ascii=False)[:220]}"
    return head


def main() -> None:
    if not KEY:
        print("FAIL: THS_API_KEY 未设置（请在 .env 中配置）")
        return
    print(f"base={BASE} key_len={len(KEY)}\n")

    for name, path, params in PROBES:
        url = f"{BASE}{path}?{urllib.parse.urlencode(params)}"
        req = urllib.request.Request(
            url, headers={"X-api-key": KEY, "Accept": "application/json"}
        )
        try:
            with urllib.request.urlopen(req, timeout=15) as resp:
                status, body = resp.status, resp.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            status, body = exc.code, exc.read().decode("utf-8", "replace")
        except Exception as exc:  # noqa: BLE001
            print(f"[{name}] EXC {type(exc).__name__}: {exc}")
            continue

        print(f"[{name}] HTTP {status}  {path}")
        try:
            payload = json.loads(body)
        except json.JSONDecodeError:
            print(f"    non-json: {body[:200]}")
            continue

        code = payload.get("code")
        print(
            f"    code={code} message={payload.get('message')!r} "
            f"request_id={payload.get('request_id')}"
        )
        if code == 0:
            print(f"    OK  {summarize(payload.get('data'))}")
        print()


if __name__ == "__main__":
    main()
