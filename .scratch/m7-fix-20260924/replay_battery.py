"""M7 修复后 PG lane 复放：复用 i37 冻结电池，中和 G1 后 .env 的 CORPUS_TARGET_DB 注入。

背景（M7 复核修复 G1）：.env 新增 ``CORPUS_TARGET_DB=postgres``（默认服务恢复的
交付通道）。任何 import 到 ``frontier_agent.infra.config`` 的进程都会经模块级
``load_dotenv(.env, override=False)`` 把该值灌入 ``os.environ``——含 fullchain 在内
的多个 lane 测试文件 import ``plugins.tools.corpus_fetch``（其依赖链经
``plugins/tools/meta.py`` 触达 config.py），若不中和，沙箱 lane 的
``resolve_target_db()`` 会解析成生产库名并拒绝隔离库连接。

中和方式：lane env 预置 ``CORPUS_TARGET_DB=''``——dotenv ``override=False`` 不覆盖
已存在的键，``resolve_target_db()`` 对空串回落 ``SANDBOX_DB``，与复核时（.env 尚无
该键）的解析态**完全一致**。lane 定义、守卫、顺序、恢复步全部复用冻结电池原样。

用法（仓库根）： python .scratch/m7-fix-20260924/replay_battery.py
产物落本目录（lane-*.txt / i37-tests-results.json），不触碰冻结目录 write-once 产物。
"""
from __future__ import annotations

import importlib.util
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = Path(__file__).resolve().parent
OLD = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260923-i37-final-reverify"

os.chdir(ROOT)
sys.path.insert(0, str(ROOT))


def load(name: str, path: Path) -> object:
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


m = load("m7fix_frozen_battery", OLD / "run_tests.py")
m.HERE = OUT
m.load_i37_rebuild = lambda: load("m7fix_frozen_rebuild", OLD / "i37_rebuild.py")

_orig_lane_env = m.lane_env


def lane_env(*, guard, dsn, also_corpus_dsn: bool = False) -> dict[str, str]:  # noqa: ANN001
    env = _orig_lane_env(guard=guard, dsn=dsn, also_corpus_dsn=also_corpus_dsn)
    env["CORPUS_TARGET_DB"] = ""
    return env


m.lane_env = lane_env

raise SystemExit(m.main())
