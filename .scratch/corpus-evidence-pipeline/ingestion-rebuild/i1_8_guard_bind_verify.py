"""I1-8 拒绝路径验证（守卫绑定与实际来源清单回填）。

M1 达成后 I1 首项：把 I0G-1 守卫绑定为 I1 无网络/无 PG 配置，并按 I0A-2
终态（dev_selection_approved 6 份 + holdout_protected 3 份）回填实际来源
清单。本脚本是"拒绝路径验证成功才启动 I1 测试"的确定性验证门，全程：
零模型、零网络（harness 自身只 stat/config 加载/派生受守卫子进程）、零
对真实来源的直接读取（正例仅在被守卫子进程内 hash 6 份开发材料，不读入
正文到 harness 进程）。

验证面（对被守卫子进程逐一断言）：
- 模型客户端构造/调用陷阱：openai/anthropic 及智能解析模块导入即拒。
- 子进程继承：受守卫进程派生的 Python 子进程仍拒绝留出读取。
- 守卫先于模块测试收集：guard_pytest 插件在收集前装载守卫并拒绝 openai。
- 来源清单：6 份开发材料只读 hash 放行；3 份留出（forbidden_roots）与
  非开发 admit 文件拒绝；无 PG（deny_all socket 拒绝）。
- 投毒：OPENAI_* 与 CORPUS_DSN 环境可见为哨兵值。

输出为 write-once（open('x') 独占创建）；报告绑定 i1.json 与实现文件哈希。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from plugins.corpus.preparation import guard  # noqa: E402

REPO = Path(__file__).resolve().parents[3]
GUARDS_DIR = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards"
CONFIG_PATH = GUARDS_DIR / "i1.json"

# I0A-2 终态：开发材料 6 份（company/industry/macro 各 2）。
DEV_PATHS: tuple[str, ...] = (
    "data/corpus/2026-08-16_2026.08.16-华创证券-欧阳予-田晨曦-张慧-公司研究-业绩点评-贵州茅台"
    "-600519-报表实质扎实-经营底部已过-贵州茅台-600519-2026年中报点评-e034bdac.pdf",
    "data/corpus/2026-09-06_2026.09.06-国信证券-光力科技-300480-2026年中报点评-半导体划片机国内"
    "龙头-经营拐点向上-b6beb6ee.pdf",
    "data/corpus/2026-08-13_2026.08.13-长江证券-国内研报-长江证券-化工专题-景气投资-十问十答"
    "-7463f4d0.pdf",
    "data/corpus/2026-09-06_2026.09.06-华福证券-华福证券-基础化工行业新材料周报-英伟达带火-新材"
    "料-电子特气涨幅超240-aa8e026a.pdf",
    "data/corpus/2026-09-06_2026.09.06-华创证券-宏观专题-从分化到收敛-可能的路径与挑战-投石问-k"
    "-系列八-81e10069.pdf",
    "data/corpus/2026-09-06_2026.09.06-光大证券-2026年8月美国非农数据点评-强非农降低了年内加息"
    "的门槛-6fc25e24.pdf",
)

# I0A-2 终态：留出 3 份（不得进入 I1 访问）。
HOLDOUT_PATHS: tuple[str, ...] = (
    "data/corpus/2026-08-12_2026.08.12-国泰海通-国内研报-国泰海通证券-ipo专题-新股精要-国内领先"
    "的电子材料和化工新材料生产企业贝特利-2594e01d.pdf",
    "data/corpus/2026-09-06_2026.09.06-中银国际-中银证券-高频数据扫描-美国非农超预期-特朗普发新"
    "威胁-65b4b040.pdf",
    "data/corpus/2026-09-06_2026.09.06-华泰证券-宏观海外周报-联储加息悬念白热化-d571f138.pdf",
)

# 非开发、非留出的 admit 文件：证明整份 corpus 目录 fail-closed（未命中允许清单即拒）。
NONDEV_PROBE = (
    "data/corpus/2026-08-16_2026.08.16-jpmorgan-摩根大通-中国人工智能-glm-5-3和deepseek的重新"
    "定价改变了能力成本前沿-raise-智谱minimax目标价-维持增持评级中性-b4d3b59b.pdf"
)

_PRELUDE = (
    "import sys\n"
    f"sys.path.insert(0, {str(REPO)!r})\n"
    "from plugins.corpus.preparation import guard\n"
    f"guard.install({str(CONFIG_PATH)!r})\n"
)


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _guarded(code: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _PRELUDE + code],
        capture_output=True,
        text=True,
        timeout=120,
        cwd=str(REPO),
        check=False,
    )


def _refusal(body: str, expected_fragment: str = "corpus preparation guard") -> dict[str, Any]:
    proc = _guarded(body + "\n")
    stderr = proc.stderr
    passed = proc.returncode != 0 and expected_fragment in stderr
    return {
        "case": body.strip().replace("\n", "; "),
        "kind": "refusal",
        "passed": passed,
        "detail": (stderr.strip().splitlines() or [""])[-1],
    }


def _positive(body: str, marker: str) -> dict[str, Any]:
    proc = _guarded(body + "\n")
    passed = proc.returncode == 0 and marker in proc.stdout
    detail = ""
    if not passed:
        detail = (proc.stdout + proc.stderr).strip().splitlines()
        detail = detail[-1] if detail else ""
    return {
        "case": body.strip().replace("\n", "; "),
        "kind": "positive",
        "passed": passed,
        "detail": detail,
    }


def _check_config(config: guard.PhaseConfig) -> tuple[list[dict[str, Any]], bool]:
    """核对已加载 i1.json 与 I0A-2 终态一致；返回 (checks, all_ok)。"""

    dev_roots = tuple(sorted((REPO / p).resolve() for p in DEV_PATHS))
    hold_roots = tuple(sorted((REPO / p).resolve() for p in HOLDOUT_PATHS))
    checks: list[dict[str, Any]] = []
    seen: list[tuple[str, bool, str]] = []
    table = [
        ("phase == i1", config.phase == "i1", config.phase),
        ("network deny_all", config.network_mode == "deny_all", config.network_mode),
        ("no allowed_targets", config.allowed_targets == (), str(config.allowed_targets)),
        ("read_roots == data/corpus", config.read_roots == ((REPO / "data/corpus").resolve(),), ""),
        (
            "allowed == 6 dev files",
            tuple(sorted(config.allowed_source_paths)) == dev_roots,
            f"{len(config.allowed_source_paths)} allowed",
        ),
        (
            "forbidden == 3 holdout files",
            tuple(sorted(config.forbidden_roots)) == hold_roots,
            f"{len(config.forbidden_roots)} forbidden",
        ),
        ("protected == data", config.protected_roots == ((REPO / "data").resolve(),), ""),
        ("openai blocked", "openai" in config.blocked_modules, ""),
        ("anthropic blocked", "anthropic" in config.blocked_modules, ""),
        (
            "semantic parser blocked",
            "plugins.corpus.material_semantics" in config.blocked_modules,
            "",
        ),
        ("_r2_runtime blocked", "plugins.corpus._r2_runtime" in config.blocked_modules, ""),
        ("CORPUS_DSN poisoned", "CORPUS_DSN" in config.poisoned_dsn, ""),
    ]
    for name, ok, extra in table:
        checks.append({"check": name, "passed": ok, "detail": extra})
        seen.append((name, ok, extra))

    for rel in DEV_PATHS:
        ok = (REPO / rel).is_file()
        checks.append({"check": f"dev exists: {rel}", "passed": ok, "detail": ""})
    for rel in HOLDOUT_PATHS:
        ok = (REPO / rel).is_file()
        checks.append({"check": f"holdout exists: {rel}", "passed": ok, "detail": ""})
    ok = (REPO / NONDEV_PROBE).is_file()
    checks.append({"check": "non-dev probe exists", "passed": ok, "detail": ""})

    return checks, all(c["passed"] for c in checks)


def _child_inherits_guard() -> dict[str, Any]:
    hold = str((REPO / HOLDOUT_PATHS[0]).resolve())
    child_code = f"open({hold!r}, 'rb').read()"
    body = (
        "import subprocess\n"
        "child = subprocess.run([sys.executable, '-I', '-B', '-c', "
        f"{child_code!r}], capture_output=True, text=True)\n"
        "assert child.returncode != 0 and 'corpus preparation guard' in child.stderr, "
        "child.stderr\n"
        "print('CHILD_INHERITED')\n"
    )
    return _positive(body, "CHILD_INHERITED")


def _pytest_guard_before_collection() -> dict[str, Any]:
    with tempfile.TemporaryDirectory() as tmp:
        probe = Path(tmp) / "test_i1_guard_probe.py"
        probe.write_text(
            "def test_guard_active_before_collection() -> None:\n"
            "    from plugins.corpus.preparation import guard\n"
            "    st = guard.state()\n"
            "    assert st is not None and st.config.phase == 'i1'\n"
            "    try:\n"
            "        import openai  # noqa: F401\n"
            "    except ImportError as exc:\n"
            "        assert 'corpus preparation guard' in str(exc)\n"
            "    else:\n"
            "        raise AssertionError('openai import must be refused')\n",
            encoding="utf-8",
        )
        env = dict(os.environ)
        env["CORPUS_GUARD_PHASE"] = "i1"
        env["CORPUS_GUARD_CONFIG"] = str(CONFIG_PATH)
        proc = subprocess.run(
            [
                sys.executable,
                "-m",
                "pytest",
                "-p",
                "plugins.corpus.preparation.guard_pytest",
                "-q",
                str(probe),
            ],
            capture_output=True,
            text=True,
            timeout=180,
            cwd=str(REPO),
            env=env,
            check=False,
        )
        passed = proc.returncode == 0 and "1 passed" in proc.stdout
        detail = ""
        if not passed:
            detail = (proc.stdout + proc.stderr).strip().splitlines()
            detail = detail[-1] if detail else ""
        return {
            "case": "pytest guard installs before collection (openai refused)",
            "kind": "refusal",
            "passed": passed,
            "detail": detail,
        }


def run_verify() -> dict[str, Any]:
    config = guard.load_phase_config(CONFIG_PATH)
    checks, config_ok = _check_config(config)

    cases: list[dict[str, Any]] = []
    # 模型客户端构造/调用陷阱。
    for body in (
        "import openai",
        "from openai import OpenAI\nOpenAI()",
        "import anthropic",
        "import plugins.corpus.material_semantics",
        "import plugins.corpus._r2_runtime",
    ):
        cases.append(_refusal(body))

    # 3 份留出显式隔离 + 1 份非开发 admit 文件 fail-closed。
    for rel in HOLDOUT_PATHS:
        full = str((REPO / rel).resolve())
        cases.append(_refusal(f"open({full!r}, 'rb').read()", "禁止访问隔离路径"))
    cases.append(
        _refusal(
            f"open({str((REPO / NONDEV_PROBE).resolve())!r}, 'rb').read()",
            "开发来源允许清单",
        )
    )

    # 无 PG：deny_all 拒绝 socket 连接（合成 audit 事件 + 真实直连不触网）。
    cases.append(
        _refusal(
            "import socket\n"
            "class _S:\n    family = socket.AF_INET\n"
            "sys.audit('socket.connect', _S(), ('127.0.0.1', 5432))"
        )
    )

    # 6 份开发材料只读 hash 放行（正例不读入 harness），并核验投毒哨兵。
    for rel in DEV_PATHS:
        full = str((REPO / rel).resolve())
        cases.append(
            _positive(
                "import hashlib\n"
                f"h = hashlib.sha256(open({full!r}, 'rb').read()).hexdigest()\n"
                "assert len(h) == 64\n"
                "print('DEV_HASH_OK')",
                "DEV_HASH_OK",
            )
        )
    cases.append(
        _positive(
            "import os\n"
            "assert os.environ['OPENAI_API_KEY'] == 'CORPUS_GUARD_DISABLED'\n"
            "assert 'corpus_guard_forbidden' in os.environ['CORPUS_DSN']\n"
            "print('POISON_OK')",
            "POISON_OK",
        )
    )

    # 子进程继承 + 守卫先于测试收集。
    cases.append(_child_inherits_guard())
    cases.append(_pytest_guard_before_collection())

    selfcheck = guard.run_selfcheck(CONFIG_PATH)

    all_ok = config_ok and all(c["passed"] for c in cases) and selfcheck["passed"]
    fingerprints = {
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json": _sha256(CONFIG_PATH),
        ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i1_8_guard_bind_verify.py": _sha256(
            Path(__file__).resolve()
        ),
        "plugins/corpus/preparation/guard.py": _sha256(REPO / "plugins/corpus/preparation/guard.py"),
        "plugins/corpus/preparation/guard_pytest.py": _sha256(
            REPO / "plugins/corpus/preparation/guard_pytest.py"
        ),
        "plugins/corpus/preparation/__init__.py": _sha256(
            REPO / "plugins/corpus/preparation/__init__.py"
        ),
        "tests/test_corpus_preparation_guard.py": _sha256(
            REPO / "tests/test_corpus_preparation_guard.py"
        ),
    }

    return {
        "report_version": 1,
        "task": "I1-8",
        "phase": config.phase,
        "config": str(config.path),
        "config_sha256": config.raw_sha256,
        "config_consistency": {"passed": config_ok, "checks": checks},
        "model_calls": 0,
        "network_attempts": 0,
        "cases": cases,
        "selfcheck": selfcheck,
        "dev_materials": len(DEV_PATHS),
        "holdout_isolation": len(HOLDOUT_PATHS),
        "passed": all_ok,
        "fingerprints": fingerprints,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="I1-8 拒绝路径验证")
    parser.add_argument("--out", type=Path, help="验证报告输出路径（write-once）")
    args = parser.parse_args(argv)

    report = run_verify()
    text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
    if args.out is not None:
        out_path = args.out if args.out.is_absolute() else REPO / args.out
        if out_path.exists():
            raise guard.GuardError(f"验证报告输出路径已存在（write-once）: {out_path}")
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text + "\n", encoding="utf-8")
    print(text)
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())