#!/usr/bin/env python3
"""错峰抓取执行器：自动续跑 claim 抽取直到全量完成。

设计要点（都是被实测逼出来的，不是凭空定的）：
- 断点续跑：service 层 ``extract_claims(skip_existing=True)`` 会跳过 claims 表
  已存在的 (doc_id, seq)，所以进程挂了 / 429 风暴中断，重跑自动续接，不重复花钱。
- 批次控制：每轮只抽 ``--limit`` 块，避免单进程跑太久被供应商踢；
  一轮跑完再 dry-run 看剩余，归零即全量完成。
- 适配错峰：在访问低谷时段（如深夜）后台跑，命中率高、429 少。
- 致命错误（缺 key 等 returncode==2）立即停，不空转。

用法：
    uv run python scripts/extract_claims_offpeak.py
环境变量：
    CLAIM_BATCH  每轮块数（默认 100）
    CLAIM_SLEEP  块间限速秒数（默认 1.5）
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time

LIMIT = int(os.environ.get("CLAIM_BATCH", "100"))
SLEEP = float(os.environ.get("CLAIM_SLEEP", "1.5"))
ENV = dict(os.environ)


def _run(args: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "plugins.corpus.service", *args],
        env=ENV,
        capture_output=True,
        text=True,
    )


def _dry_run() -> dict:
    proc = _run(["extract-claims", "--dry-run", "--sleep", str(SLEEP)])
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {}


def main() -> int:
    round_no = 0
    while True:
        round_no += 1
        info = _dry_run()
        remaining = info.get("candidates", 0)
        print(
            f"[offpeak] 第 {round_no} 轮 | 剩余候选块: {remaining} "
            f"| 已抽文档: {info.get('documents', '?')}",
            flush=True,
        )
        if remaining == 0:
            print("[offpeak] 全量抽取完成", flush=True)
            break

        proc = _run(
            ["extract-claims", "--limit", str(LIMIT), "--sleep", str(SLEEP)]
        )
        tail = (proc.stdout or proc.stderr)[-1500:]
        print(tail, flush=True)
        if proc.returncode == 2:  # 缺 key 等致命错误，别空转
            print("[offpeak] 致命错误，停止（检查 .env 的 OPENAI_API_KEY）", flush=True)
            return 2
        time.sleep(2)  # 轮间稍歇，给供应商喘息

    print("=== 最终统计 ===")
    print(json.dumps(_dry_run(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
