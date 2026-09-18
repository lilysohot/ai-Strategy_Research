"""pytest 早期装载钩子：测试收集**之前**安装语料准备执行守卫（I0G-1 / I1-8）。

用法（显式选择加入，两个环境变量必须**同时**声明）::

    CORPUS_GUARD_PHASE=i1 \
    CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json \
    uv run pytest -p plugins.corpus.preparation.guard_pytest tests/test_corpus_preparation_*.py

未声明任何变量时本插件保持惰性，不影响普通测试运行；只声明其一视为配置
错误，直接失败（fail-closed，不静默跳过）。环境变量声明与配置文件实际
阶段不一致时同样直接失败。
"""

from __future__ import annotations

import os
from typing import Any

from plugins.corpus.preparation import guard


def pytest_load_initial_conftests(args: list[str], early_config: Any, parser: Any) -> None:
    phase = os.environ.get("CORPUS_GUARD_PHASE")
    config = os.environ.get("CORPUS_GUARD_CONFIG")
    if phase is None and config is None:
        return  # 未声明守卫阶段：本插件保持惰性，不影响普通测试运行
    if phase is None or config is None:
        missing = "CORPUS_GUARD_CONFIG" if phase is not None else "CORPUS_GUARD_PHASE"
        raise guard.GuardError(
            f"corpus preparation guard: 检测到部分声明（{missing} 缺失）；"
            "CORPUS_GUARD_PHASE 与 CORPUS_GUARD_CONFIG 必须同时提供，否则拒绝运行"
        )
    loaded = guard.install(config)
    if loaded.phase != phase:
        raise guard.GuardError(
            f"corpus preparation guard: CORPUS_GUARD_PHASE={phase!r} 与配置阶段 "
            f"{loaded.phase!r} 不一致"
        )
