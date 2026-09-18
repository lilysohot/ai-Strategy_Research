"""I0G-1 执行守卫测试。

守卫的审计钩子不可卸载，因此**不在 pytest 进程内安装**；每个用例通过
子进程（先 install，再执行目标代码）验证拒绝行为，与 I1-8/CLI 的
子进程继承路径一致。
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
GUARD_DIR = REPO / ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards"
I0_CONFIG = GUARD_DIR / "i0-inventory.json"
I1_CONFIG = GUARD_DIR / "i1.json"

_PRELUDE = (
    "import sys\n"
    f"sys.path.insert(0, {str(REPO)!r})\n"
    "from plugins.corpus.preparation import guard\n"
    "guard.install({config!r})\n"
)


def _guarded(code: str, config: Path = I0_CONFIG) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _PRELUDE.format(config=str(config)) + code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO),
        check=False,
    )


def _guarded_in(cwd: Path, code: str, config: Path = I0_CONFIG) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-c", _PRELUDE.format(config=str(config)) + code],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(cwd),
        check=False,
    )


def _synthetic_env(tmp_root: Path, *, allowed: list[str]) -> tuple[Path, Path, Path, Path]:
    """构造与审计反例同构的合成环境，返回 (config, sources, holdout, protected)。"""

    sources = tmp_root / "sources"
    holdout = tmp_root / "holdout"
    protected = tmp_root / "protected"
    for folder in (sources, holdout, protected):
        folder.mkdir()
    (sources / "sample.md").write_text("synthetic-only", encoding="utf-8")
    secret = holdout / "secret.md"
    secret.write_text("synthetic-only", encoding="utf-8")
    keep = protected / "keep.md"
    keep.write_text("synthetic-only", encoding="utf-8")
    config = {
        "config_version": 1,
        "phase": "synthetic-test",
        "network": {"mode": "deny_all", "allowed_targets": []},
        "model": {
            "blocked_modules": ["fractions"],
            "blocked_module_prefixes": [],
            "poisoned_env": [],
            "poisoned_dsn": [],
        },
        "sources": {
            "read_roots": [str(sources)],
            "allowed_source_paths": allowed,
            "forbidden_roots": [str(holdout)],
            "protected_roots": [str(protected)],
        },
    }
    config_path = tmp_root / "guard.json"
    config_path.write_text(json.dumps(config), encoding="utf-8")
    return config_path, secret, keep, sources / "sample.md"


def test_selfcheck_synthetic_negatives_all_pass() -> None:
    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "plugins.corpus.preparation.guard",
            "--config",
            str(I0_CONFIG),
            "--selfcheck",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        cwd=str(REPO),
        check=False,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads(proc.stdout)
    assert report["phase"] == "i0-inventory"
    assert report["passed"] is True
    assert len(report["cases"]) >= 8


def test_model_client_import_and_construction_refused() -> None:
    proc = _guarded("import openai\n")
    assert proc.returncode != 0
    assert "corpus preparation guard" in proc.stderr

    proc = _guarded("from openai import OpenAI\nOpenAI()\n")
    assert proc.returncode != 0
    assert "corpus preparation guard" in proc.stderr


def test_semantic_parsing_modules_refused() -> None:
    for module in (
        "plugins.corpus.material_semantics",
        "plugins.corpus._r2_runtime",
    ):
        proc = _guarded(f"import {module}\n")
        assert proc.returncode != 0, module
        assert "corpus preparation guard" in proc.stderr


def test_external_socket_connect_refused() -> None:
    proc = _guarded("import socket\nsocket.create_connection(('example.com', 443), timeout=1)\n")
    assert proc.returncode != 0
    assert "corpus preparation guard" in proc.stderr


def test_source_write_refused_but_hash_read_allowed() -> None:
    target = REPO / "data" / "corpus" / "index.db"
    assert target.is_file()
    proc = _guarded(f"open({str(target)!r}, 'w')\n")
    assert proc.returncode != 0
    assert "禁止写入受保护路径" in proc.stderr

    proc = _guarded(
        "import hashlib\n"
        f"h = hashlib.sha256(open({str(target)!r}, 'rb').read()).hexdigest()\n"
        "assert len(h) == 64\n"
    )
    assert proc.returncode == 0, proc.stderr


def test_forbidden_root_read_refused() -> None:
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        secret = Path(tmp) / "holdout" / "secret.md"
        secret.parent.mkdir()
        secret.write_text("synthetic", encoding="utf-8")
        config = {
            "config_version": 1,
            "phase": "synthetic-test",
            "network": {"mode": "deny_all", "allowed_targets": []},
            "model": {
                "blocked_modules": ["openai"],
                "blocked_module_prefixes": [],
                "poisoned_env": [],
                "poisoned_dsn": [],
            },
            "sources": {
                "read_roots": [],
                "allowed_source_paths": [],
                "forbidden_roots": [str(secret.parent)],
                "protected_roots": [],
            },
        }
        cfg_path = Path(tmp) / "cfg.json"
        cfg_path.write_text(json.dumps(config), encoding="utf-8")
        proc = _guarded(f"open({str(secret)!r}, encoding='utf-8').read()\n", config=cfg_path)
        assert proc.returncode != 0
        assert "禁止访问隔离路径" in proc.stderr


def test_install_rejects_blocked_module_loaded_first_and_config_swap() -> None:
    # 缺失配置：安装即失败（fail-closed，不允许降级运行）。
    proc = subprocess.run(
        [
            sys.executable,
            "-c",
            f"import sys\nsys.path.insert(0, {str(REPO)!r})\n"
            "from plugins.corpus.preparation import guard\n"
            "guard.install('no-such-guard.json')\n",
        ],
        capture_output=True,
        text=True,
        timeout=60,
        cwd=str(REPO),
        check=False,
    )
    assert proc.returncode != 0
    assert "guard config 无法读取" in proc.stderr

    # 幂等：同配置二次安装成功；换配置安装拒绝。
    code = (
        "from plugins.corpus.preparation import guard\n"
        f"guard.install({str(I0_CONFIG)!r})\n"
        f"again = guard.install({str(I0_CONFIG)!r})\n"
        "assert again.phase == 'i0-inventory'\n"
        "try:\n"
        f"    guard.install({str(I1_CONFIG)!r})\n"
        "except guard.GuardError:\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )
    proc = _guarded(code)
    assert proc.returncode == 0, proc.stderr


def test_poisoned_env_and_dsn_visible_to_chain() -> None:
    code = (
        "import os\n"
        "assert os.environ['OPENAI_API_KEY'] == 'CORPUS_GUARD_DISABLED'\n"
        "assert 'corpus_guard_forbidden' in os.environ['CORPUS_DSN']\n"
    )
    proc = _guarded(code)
    assert proc.returncode == 0, proc.stderr


def test_pytest_plugin_installs_guard_before_collection(tmp_path: Path) -> None:
    probe = tmp_path / "test_guard_probe.py"
    probe.write_text(
        "def test_guard_active_before_collection() -> None:\n"
        "    from plugins.corpus.preparation import guard\n"
        "    st = guard.state()\n"
        "    assert st is not None and st.config.phase == 'i0-inventory'\n"
        "    try:\n"
        "        import openai  # noqa: F401\n"
        "    except ImportError as exc:\n"
        "        assert 'corpus preparation guard' in str(exc)\n"
        "    else:\n"
        "        raise AssertionError('openai import must be refused')\n",
        encoding="utf-8",
    )
    env = dict(os.environ)
    env["CORPUS_GUARD_PHASE"] = "i0-inventory"
    env["CORPUS_GUARD_CONFIG"] = str(I0_CONFIG)
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
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "1 passed" in proc.stdout

    # 阶段声明与配置不一致时 fail-closed。
    env["CORPUS_GUARD_PHASE"] = "i1"
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
    assert proc.returncode != 0
    assert "不一致" in proc.stdout + proc.stderr


def test_i1_config_declares_no_network_and_actual_sources() -> None:
    from plugins.corpus.preparation.guard import load_phase_config

    config = load_phase_config(I1_CONFIG)
    assert config.phase == "i1"
    assert config.network_mode == "deny_all"
    assert config.allowed_targets == ()
    # I1-8 已按 I0A-2 终态回填：read_roots 绑定 data/corpus，仅 6 份开发材料放行、
    # 3 份留出隔离。
    assert config.read_roots == ((REPO / "data" / "corpus").resolve(),)
    assert len(config.allowed_source_paths) == 6
    assert len(config.forbidden_roots) == 3
    assert all(p.is_relative_to(REPO / "data" / "corpus") for p in config.allowed_source_paths)
    assert all(p.is_relative_to(REPO / "data" / "corpus") for p in config.forbidden_roots)
    assert "openai" in config.blocked_modules
    assert "anthropic" in config.blocked_modules
    assert "CORPUS_DSN" in config.poisoned_dsn


def test_relative_paths_normalized_before_checks() -> None:
    # 审计反例 C02/C03 镜像：相对路径必须按 cwd 归一化后再判定。
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        config, secret, _keep, _ = _synthetic_env(tmp_root, allowed=[])
        proc = _guarded_in(tmp_root, "open('holdout/secret.md').read()\n", config=config)
        assert proc.returncode != 0
        assert "禁止访问隔离路径" in proc.stderr

        proc = _guarded_in(tmp_root, "open('protected/keep.md', 'w').write('x')\n", config=config)
        assert proc.returncode != 0
        assert "禁止写入受保护路径" in proc.stderr

        # 正例：绝对路径下的同一判定仍然成立（不因归一化放宽）。
        proc = _guarded_in(tmp_root, f"open({str(secret)!r}).read()\n", config=config)
        assert proc.returncode != 0
        assert "禁止访问隔离路径" in proc.stderr


def test_protected_delete_and_rename_refused() -> None:
    # 审计反例 C04 镜像：删除/重命名受保护路径必须被拒绝。
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        config, secret, keep, sample = _synthetic_env(tmp_root, allowed=[])
        proc = _guarded(f"import os\nos.unlink({str(keep)!r})\n", config=config)
        assert proc.returncode != 0
        assert "禁止删除" in proc.stderr

        proc = _guarded(f"import os\nos.rmdir({str(keep.parent)!r})\n", config=config)
        assert proc.returncode != 0
        assert "禁止删除" in proc.stderr

        proc = _guarded(
            f"import os\nos.rename({str(keep)!r}, {str(tmp_root / 'moved.md')!r})\n",
            config=config,
        )
        assert proc.returncode != 0
        assert "禁止重命名" in proc.stderr

        proc = _guarded(f"import os\nos.rename({str(sample)!r}, {str(keep)!r})\n", config=config)
        assert proc.returncode != 0
        assert "禁止重命名" in proc.stderr

        # 隔离路径同样受删除保护。
        proc = _guarded(f"import os\nos.unlink({str(secret)!r})\n", config=config)
        assert proc.returncode != 0
        assert "禁止删除" in proc.stderr


def test_empty_allowlist_and_empty_read_roots_fail_closed() -> None:
    # 审计反例 C05：read_roots 内读取必须命中 allowed_source_paths，空清单即拒绝。
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        config, _secret, _keep, sample = _synthetic_env(tmp_root, allowed=[])
        proc = _guarded(f"open({str(sample)!r}).read()\n", config=config)
        assert proc.returncode != 0
        assert "开发来源允许清单" in proc.stderr

        # 审计反例 C06 镜像：read_roots 为空即拒绝全部非运行时读取。
        empty = {
            "config_version": 1,
            "phase": "synthetic-empty-roots",
            "network": {"mode": "deny_all", "allowed_targets": []},
            "model": {
                "blocked_modules": [],
                "blocked_module_prefixes": [],
                "poisoned_env": [],
                "poisoned_dsn": [],
            },
            "sources": {
                "read_roots": [],
                "allowed_source_paths": [],
                "forbidden_roots": [],
                "protected_roots": [],
            },
        }
        empty_path = tmp_root / "empty-guard.json"
        empty_path.write_text(json.dumps(empty), encoding="utf-8")
        proc = _guarded(f"open({str(sample)!r}).read()\n", config=empty_path)
        assert proc.returncode != 0
        assert "未绑定 read_roots" in proc.stderr

        # 绑定允许清单后同一文件可读（哈希正例）。
        bound = json.loads(config.read_text(encoding="utf-8"))
        bound["phase"] = "synthetic-bound"
        bound["sources"] = {
            "read_roots": [str(tmp_root / "sources")],
            "allowed_source_paths": [str(sample)],
            "forbidden_roots": [str(tmp_root / "holdout")],
            "protected_roots": [str(tmp_root / "protected")],
        }
        bound_path = tmp_root / "bound-guard.json"
        bound_path.write_text(json.dumps(bound), encoding="utf-8")
        proc = _guarded(
            "import hashlib\n"
            f"h = hashlib.sha256(open({str(sample)!r}, 'rb').read()).hexdigest()\n"
            "assert len(h) == 64\n",
            config=bound_path,
        )
        assert proc.returncode == 0, proc.stderr


def test_cli_wrapper_preserves_guard() -> None:
    # 审计反例 C07 镜像：包装命令的 exec 目标必须仍受守卫约束。
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        config, secret, _keep, _sample = _synthetic_env(tmp_root, allowed=[])
        wrapper_code = (
            "import sys\n"
            f"sys.path.insert(0, {str(REPO)!r})\n"
            "from plugins.corpus.preparation import guard\n"
            "raise SystemExit(guard.main(sys.argv[1:]))\n"
        )
        target_code = (
            "try:\n"
            f"    open({str(secret)!r}).read()\n"
            "except OSError as exc:\n"
            "    if 'corpus preparation guard' not in str(exc):\n"
            "        raise\n"
            "    print('GUARD_REFUSED')\n"
            "    raise SystemExit(0)\n"
            "print('POLICY_BYPASS')\n"
            "raise SystemExit(1)\n"
        )
        proc = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                wrapper_code,
                "--config",
                str(config),
                "--",
                sys.executable,
                "-I",
                "-B",
                "-c",
                target_code,
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(tmp_root),
            check=False,
        )
        assert proc.returncode == 0, proc.stdout + proc.stderr
        assert "GUARD_REFUSED" in proc.stdout
        assert "POLICY_BYPASS" not in proc.stdout

        # 非 Python 目标拒绝派生（保护范围如实声明的 fail-closed 面）。
        proc = subprocess.run(
            [
                sys.executable,
                "-I",
                "-B",
                "-c",
                wrapper_code,
                "--config",
                str(config),
                "--",
                "/bin/true",
            ],
            capture_output=True,
            text=True,
            timeout=60,
            cwd=str(tmp_root),
            check=False,
        )
        assert proc.returncode != 0
        assert "corpus preparation guard" in proc.stderr


def test_ordinary_child_inherits_guard() -> None:
    # 审计反例 C08 镜像：受守卫进程派生的普通 Python 子进程自动获得约束。
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        config, secret, _keep, _sample = _synthetic_env(tmp_root, allowed=[])
        child_code = f"open({str(secret)!r}).read()"
        code = (
            "import subprocess\n"
            "child = subprocess.run([sys.executable, '-I', '-B', '-c', "
            f"{child_code!r}], capture_output=True, text=True)\n"
            "assert child.returncode != 0 and 'corpus preparation guard' in child.stderr, "
            "child.stderr\n"
        )
        proc = _guarded_in(tmp_root, code, config=config)
        assert proc.returncode == 0, proc.stderr


def test_pytest_partial_declaration_fails_closed() -> None:
    # 审计反例 C09 镜像：只声明 phase 不声明 config 必须报错，不允许静默跳过。
    code = (
        "import os\n"
        "os.environ['CORPUS_GUARD_PHASE'] = 'i1'\n"
        "os.environ.pop('CORPUS_GUARD_CONFIG', None)\n"
        "from plugins.corpus.preparation import guard_pytest\n"
        "try:\n"
        "    guard_pytest.pytest_load_initial_conftests([], None, None)\n"
        "except guard.GuardError as exc:\n"
        "    assert 'corpus preparation guard' in str(exc)\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )
    proc = _guarded(code)
    assert proc.returncode == 0, proc.stderr


def test_unix_socket_audit_event_refused() -> None:
    # 审计反例 C11 镜像：deny_all（含 I1）必须拒绝 Unix 域套接字连接事件。
    code = (
        "import socket\n"
        "class _Fake:\n"
        "    family = socket.AF_UNIX\n"
        "try:\n"
        "    sys.audit('socket.connect', _Fake(), '/synthetic-pg.sock')\n"
        "except OSError as exc:\n"
        "    assert 'corpus preparation guard' in str(exc)\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )
    proc = _guarded(code, config=I1_CONFIG)
    assert proc.returncode == 0, proc.stderr


def test_exec_system_and_uncontrolled_spawn_refused() -> None:
    # exec/system 替换或派生不受守卫约束的进程一律拒绝；posix_spawn 事件同理。
    code = (
        "import os\n"
        "for call in (\n"
        f"    lambda: os.execvp({sys.executable!r}, [{sys.executable!r}, '-c', 'pass']),\n"
        "    lambda: os.system('true'),\n"
        f"    lambda: os.posix_spawn({sys.executable!r}, [{sys.executable!r}, '-c', 'pass'], "
        "{}),\n"
        "):\n"
        "    try:\n"
        "        call()\n"
        "    except OSError as exc:\n"
        "        assert 'corpus preparation guard' in str(exc)\n"
        "    else:\n"
        "        raise AssertionError('must be refused')\n"
        "raise SystemExit(0)\n"
    )
    proc = _guarded(code)
    assert proc.returncode == 0, proc.stderr


def test_non_python_child_spawn_refused() -> None:
    # 非 Python 子进程无法注入守卫：拒绝派生（/bin/true 真实存在，证明是守卫拒绝）。
    code = (
        "import subprocess\n"
        "try:\n"
        "    subprocess.run(['/bin/true'])\n"
        "except guard.GuardError as exc:\n"
        "    assert 'corpus preparation guard' in str(exc)\n"
        "    raise SystemExit(0)\n"
        "raise SystemExit(1)\n"
    )
    proc = _guarded(code)
    assert proc.returncode == 0, proc.stderr
