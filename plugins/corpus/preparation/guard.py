"""语料准备链路阶段化执行守卫（任务清单 I0G-1）。

架构 v1.1 §2.1 的零模型执行契约要求：基础链路的解析/切块/入库全程 0 模型调用，
CLI 子进程启动与测试收集**之前**装载拒绝守卫；模型客户端构造/调用注入陷阱，
触发即失败；网络仅允许阶段显式授权目标；来源读取与写入按阶段配置限制。

保护范围（如实声明）——本守卫由 CPython audit/import 钩子构成：

- ``open``：forbidden_roots 读写全拒；protected_roots 拒绝写入，且其读取仅当
  路径同时被 read_roots 声明并命中 allowed_source_paths 时放行；read_roots 内
  读取必须命中 allowed_source_paths（空清单即全部拒绝，fail-closed）；read_roots
  为空的阶段仅放行运行时路径（解释器前缀与仓库根，供模块导入与测试夹具使用），
  其余读取一律拒绝。相对路径按当前工作目录归一化后判定。
- ``socket.connect``：deny_all 全拒（含 Unix 域套接字）；allowlist 未命中亦拒。
- ``os.remove``/``os.rmdir``/``os.rename``：触及 forbidden/protected 路径即拒。
- ``os.exec``/``os.system``/未注入引导的 ``subprocess.Popen``：一律拒绝。
- 子进程传播：受守卫进程派生的 Python 解释器命令，其命令行被重写为
  “先 install 守卫再执行原载荷”的引导形式（marker 防止二次重写）；非 Python
  命令、shell=True、字符串命令与 ``executable=`` 覆盖一律拒绝派生（fail-closed）。
- 模型客户端/智能解析模块导入陷阱与环境变量/DSN 投毒。

不在承诺范围：C 扩展绕过 audit 机制的原生 syscall；操作系统级隔离由沙箱后端
负责。阶段配置是数据文件（``.scratch/corpus-evidence-pipeline/ingestion-rebuild/
guards/``），本模块只实现引擎；配置变化必须重新核验并绑定当前阶段版本。

接口（刻意收窄）：
- :func:`install` —— 在当前进程装载守卫；幂等；任何违规立即失败（fail-closed）。
- 命令行 ``python -m plugins.corpus.preparation.guard --config <cfg> -- <cmd>``
  在装载守卫后执行目标命令；仅允许 Python 解释器命令（守卫经命令行重写注入
  目标进程），其余命令拒绝派生。
- ``--selfcheck`` 用合成反例在全新子进程中验证拒绝行为（不触真实来源、公网
  DNS 或 PG；网络用例仅重放 audit 事件信号）。
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

GUARD_ENV_SENTINEL = "CORPUS_GUARD_DISABLED"
GUARD_DSN_SENTINEL = (
    "postgresql://corpus-guard:corpus-guard@127.0.0.1:1/corpus_guard_forbidden?connect_timeout=1"
)
CONFIG_VERSION = 1

_REPO_ROOT = Path(__file__).resolve().parents[3]

_ALLOWED_NETWORK_MODES = ("deny_all", "allowlist")
_WRITE_FLAGS = os.O_WRONLY | os.O_RDWR | os.O_CREAT | os.O_APPEND | os.O_TRUNC

# 子进程引导 marker：命令行含此串视为已注入守卫，跳过重写。
_CHILD_BOOTSTRAP_MARKER = "corpus-guard-child-bootstrap-v1"


class GuardError(RuntimeError):
    """守卫拒绝或配置非法。所有拒绝路径都必须呈现为可识别的失败。"""


@dataclass(frozen=True)
class PhaseConfig:
    """已校验的阶段配置；未知字段/版本一律拒绝。"""

    path: Path
    phase: str
    network_mode: str
    allowed_targets: tuple[tuple[str, int], ...]
    blocked_modules: tuple[str, ...]
    blocked_module_prefixes: tuple[str, ...]
    poisoned_env: tuple[str, ...]
    poisoned_dsn: tuple[str, ...]
    read_roots: tuple[Path, ...]
    allowed_source_paths: tuple[Path, ...]
    forbidden_roots: tuple[Path, ...]
    protected_roots: tuple[Path, ...]
    raw_sha256: str


@dataclass
class GuardState:
    """已安装守卫的运行时状态（审计计数与配置引用）。"""

    config: PhaseConfig
    runtime_roots: tuple[Path, ...] = ()
    blocked_socket_connects: int = 0
    blocked_file_ops: int = 0
    blocked_imports: int = 0
    blocked_child_procs: int = 0
    notes: list[str] = field(default_factory=list)


@dataclass(frozen=True)
class SnippetResult:
    """selfcheck 子进程执行结果。"""

    exit_code: int
    stdout: str
    stderr: str


_STATE: GuardState | None = None


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _resolve_root(raw: str) -> Path:
    path = Path(raw)
    if not path.is_absolute():
        path = _REPO_ROOT / path
    return path.resolve()


def _require_str_list(data: dict[str, Any], key: str) -> tuple[str, ...]:
    value = data.get(key, [])
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        raise GuardError(f"guard config: {key} 必须是字符串列表")
    return tuple(value)


def load_phase_config(path: str | Path) -> PhaseConfig:
    """加载并校验阶段配置；未知字段、错误版本、非法枚举一律拒绝。"""

    config_path = Path(path).resolve()
    try:
        raw = config_path.read_text(encoding="utf-8")
    except OSError as exc:
        raise GuardError(f"guard config 无法读取: {config_path} ({exc})") from exc
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise GuardError(f"guard config 不是合法 JSON: {config_path}") from exc
    if not isinstance(data, dict):
        raise GuardError("guard config 顶层必须是对象")

    known = {"config_version", "phase", "network", "model", "sources", "note"}
    unknown = set(data) - known
    if unknown:
        raise GuardError(f"guard config 存在未知字段: {sorted(unknown)}")
    if data.get("config_version") != CONFIG_VERSION:
        raise GuardError(f"guard config_version 不受支持: {data.get('config_version')!r}")
    phase = data.get("phase")
    if not isinstance(phase, str) or not phase:
        raise GuardError("guard config 缺少 phase")

    network = data.get("network")
    if not isinstance(network, dict):
        raise GuardError("guard config 缺少 network 对象")
    unknown = set(network) - {"mode", "allowed_targets"}
    if unknown:
        raise GuardError(f"guard config.network 存在未知字段: {sorted(unknown)}")
    mode = network.get("mode")
    if mode not in _ALLOWED_NETWORK_MODES:
        raise GuardError(f"guard config.network.mode 非法: {mode!r}")
    targets_raw = network.get("allowed_targets", [])
    targets: list[tuple[str, int]] = []
    if not isinstance(targets_raw, list):
        raise GuardError("guard config.network.allowed_targets 必须是列表")
    for entry in targets_raw:
        if not isinstance(entry, dict) or set(entry) != {"host", "port", "reason"}:
            raise GuardError("guard config.network.allowed_targets 条目必须恰为 host/port/reason")
        host, port = entry["host"], entry["port"]
        if not isinstance(host, str) or not host:
            raise GuardError("guard config allowed target host 非法")
        if not isinstance(port, int) or isinstance(port, bool) or not 0 < port < 65536:
            raise GuardError(f"guard config allowed target port 非法: {port!r}")
        targets.append((host.lower(), port))
    if mode == "allowlist" and not targets:
        raise GuardError("allowlist 模式必须给出至少一个 allowed_target")

    model = data.get("model")
    if not isinstance(model, dict):
        raise GuardError("guard config 缺少 model 对象")
    unknown = set(model) - {
        "blocked_modules",
        "blocked_module_prefixes",
        "poisoned_env",
        "poisoned_dsn",
    }
    if unknown:
        raise GuardError(f"guard config.model 存在未知字段: {sorted(unknown)}")

    sources = data.get("sources")
    if not isinstance(sources, dict):
        raise GuardError("guard config 缺少 sources 对象")
    unknown = set(sources) - {
        "read_roots",
        "allowed_source_paths",
        "forbidden_roots",
        "protected_roots",
    }
    if unknown:
        raise GuardError(f"guard config.sources 存在未知字段: {sorted(unknown)}")

    return PhaseConfig(
        path=config_path,
        phase=phase,
        network_mode=mode,
        allowed_targets=tuple(targets),
        blocked_modules=_require_str_list(model, "blocked_modules"),
        blocked_module_prefixes=_require_str_list(model, "blocked_module_prefixes"),
        poisoned_env=_require_str_list(model, "poisoned_env"),
        poisoned_dsn=_require_str_list(model, "poisoned_dsn"),
        read_roots=tuple(_resolve_root(p) for p in _require_str_list(sources, "read_roots")),
        allowed_source_paths=tuple(
            _resolve_root(p) for p in _require_str_list(sources, "allowed_source_paths")
        ),
        forbidden_roots=tuple(
            _resolve_root(p) for p in _require_str_list(sources, "forbidden_roots")
        ),
        protected_roots=tuple(
            _resolve_root(p) for p in _require_str_list(sources, "protected_roots")
        ),
        raw_sha256=_sha256_file(config_path),
    )


class _ModelImportTrap:
    """模型客户端/智能解析模块导入陷阱：命中即 ImportError。"""

    def __init__(self, config: PhaseConfig) -> None:
        self._config = config

    def find_spec(self, fullname: str, path: Any = None, target: Any = None) -> Any:
        blocked = fullname in self._config.blocked_modules or any(
            fullname.startswith(prefix) for prefix in self._config.blocked_module_prefixes
        )
        if not blocked:
            return None
        if _STATE is not None:
            _STATE.blocked_imports += 1
        raise ImportError(
            f"corpus preparation guard: 模块 {fullname!r} 在阶段 "
            f"{self._config.phase!r} 被零模型守卫禁止导入"
        )


def _is_within(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
    except ValueError:
        return False
    return True


def _writes_intent(mode: Any, flags: Any) -> bool:
    if isinstance(mode, str):
        return any(ch in mode for ch in ("w", "a", "x", "+"))
    if isinstance(flags, int):
        return bool(flags & _WRITE_FLAGS)
    return False


def _resolve_audit_path(target: Any) -> Path | None:
    """把 audit 事件里的路径目标归一化为绝对已解析路径；不可判定返回 None。

    相对路径按当前工作目录展开（反例 C02/C03：仅看字面绝对性会漏判）。
    """

    if not isinstance(target, (str, bytes, os.PathLike)):
        return None
    path = Path(os.fsdecode(target))
    if not path.is_absolute():
        path = Path.cwd() / path
    return path.resolve()


def _compute_runtime_roots() -> tuple[Path, ...]:
    """read_roots 为空阶段允许读取的运行时路径：解释器前缀 + 仓库根。

    仅为保持模块导入、解释器数据和仓库内夹具可用；不构成对任何来源的授权。
    """

    roots = {
        Path(sys.base_prefix).resolve(),
        Path(sys.prefix).resolve(),
        Path(sys.exec_prefix).resolve(),
        _REPO_ROOT,
    }
    return tuple(sorted(roots))


def _audit(event: str, args: tuple[Any, ...]) -> None:
    state = _STATE
    if state is None:  # pragma: no cover - 钩子与状态同生命周期
        return
    config = state.config

    if event == "socket.connect":
        address = args[1] if len(args) > 1 else None
        if config.network_mode == "allowlist" and isinstance(address, tuple) and len(address) >= 2:
            host, port = str(address[0]).lower(), address[1]
            if (host, port) in config.allowed_targets:
                return
        # deny_all 一律拒绝（含 Unix 域套接字）；allowlist 未命中同样拒绝。
        state.blocked_socket_connects += 1
        raise OSError(
            f"corpus preparation guard: 阶段 {config.phase!r} 禁止 socket 连接 {address!r}"
        )

    if event == "open":
        target, mode, flags = args[0], args[1], args[2]
        resolved = _resolve_audit_path(target)
        if resolved is None:
            return  # 非路径目标（如 fd）无法按路径判定
        if any(_is_within(resolved, root) for root in config.forbidden_roots):
            state.blocked_file_ops += 1
            raise OSError(
                f"corpus preparation guard: 阶段 {config.phase!r} 禁止访问隔离路径 {resolved}"
            )
        if _writes_intent(mode, flags):
            if any(_is_within(resolved, root) for root in config.protected_roots):
                state.blocked_file_ops += 1
                raise OSError(
                    f"corpus preparation guard: 阶段 {config.phase!r} 禁止写入受保护路径 {resolved}"
                )
            return
        # 读取策略（fail-closed）：
        if any(_is_within(resolved, root) for root in config.read_roots):
            # read_roots 内必须命中允许清单；空清单即全部拒绝（反例 C05）。
            if not config.allowed_source_paths or not any(
                _is_within(resolved, p) for p in config.allowed_source_paths
            ):
                state.blocked_file_ops += 1
                raise OSError(
                    f"corpus preparation guard: 路径 {resolved} 不在阶段 "
                    f"{config.phase!r} 的开发来源允许清单内"
                )
            return
        if any(_is_within(resolved, root) for root in config.protected_roots):
            # 受保护路径的读取必须经 read_roots 显式绑定（反例 C06 的强约束面）。
            state.blocked_file_ops += 1
            raise OSError(
                f"corpus preparation guard: 阶段 {config.phase!r} 禁止读取未绑定来源的"
                f"受保护路径 {resolved}"
            )
        if any(_is_within(resolved, root) for root in state.runtime_roots):
            return  # 解释器前缀/仓库根：模块导入与仓库内夹具所需
        if not config.read_roots:
            state.blocked_file_ops += 1
            raise OSError(
                f"corpus preparation guard: 阶段 {config.phase!r} 未绑定 read_roots，"
                f"拒绝读取 {resolved}"
            )
        # read_roots 非空：区域外读取不受本守卫限制（如实声明，不由钩子放大）。
        return

    if event in ("os.remove", "os.rmdir"):
        resolved = _resolve_audit_path(args[0] if args else None)
        if resolved is None:
            return
        if any(
            _is_within(resolved, root) for root in config.forbidden_roots + config.protected_roots
        ):
            state.blocked_file_ops += 1
            raise OSError(
                f"corpus preparation guard: 阶段 {config.phase!r} 禁止删除受保护或隔离路径 "
                f"{resolved}"
            )
        return

    if event == "os.rename":
        for target in args[:2]:
            resolved = _resolve_audit_path(target)
            if resolved is None:
                continue
            if any(
                _is_within(resolved, root)
                for root in config.forbidden_roots + config.protected_roots
            ):
                state.blocked_file_ops += 1
                raise OSError(
                    f"corpus preparation guard: 阶段 {config.phase!r} 禁止重命名受保护或"
                    f"隔离路径 {resolved}"
                )
        return

    if event in ("os.exec", "os.system"):
        # exec 替换进程镜像后守卫无法延续；system 命令串无法核验。
        state.blocked_child_procs += 1
        raise OSError(
            f"corpus preparation guard: 阶段 {config.phase!r} 禁止 exec/system 派生"
            f"不受守卫约束的进程"
        )

    if event in ("subprocess.Popen", "os.posix_spawn", "os.posix_spawnp"):
        # subprocess.Popen 事件参数为 (args, executable, cwd, env)；posix_spawn 为
        # (path, argv, env)。扫描前两个参数，只有注入引导的 Python 子进程放行。
        parts: list[str] = []
        for item in args[:2]:
            if isinstance(item, (list, tuple)):
                parts.extend(os.fsdecode(element) for element in item)
            elif isinstance(item, (str, bytes, os.PathLike)):
                parts.append(os.fsdecode(item))
        text = " ".join(parts)
        if _CHILD_BOOTSTRAP_MARKER in text:
            return  # 已注入引导的 Python 子进程
        state.blocked_child_procs += 1
        raise OSError(
            f"corpus preparation guard: 阶段 {config.phase!r} 拒绝未受控子进程派生 {text!r}"
        )


def _is_python_executable(exe: Any) -> bool:
    if not isinstance(exe, str) or not exe:
        return False
    if exe == sys.executable:
        return True
    return Path(exe).name.startswith("python")


def _child_bootstrap_source(config_path: Path, dispatch: str) -> str:
    return (
        f"# {_CHILD_BOOTSTRAP_MARKER}\n"
        "import sys\n"
        f"sys.path.insert(0, {str(_REPO_ROOT)!r})\n"
        "from plugins.corpus.preparation import guard\n"
        f"guard.install({str(config_path)!r})\n"
        f"{dispatch}"
    )


def _rewrite_python_child(args: list[str], config_path: Path) -> list[str]:
    """把 Python 解释器子进程命令改写为“先装守卫再执行原载荷”。"""

    flags: list[str] = []
    rest = args[1:]
    index = 0
    while index < len(rest):
        item = rest[index]
        if item == "-c":
            if index + 1 >= len(rest):
                raise GuardError(f"corpus preparation guard: -c 缺少载荷 {args!r}")
            payload, extra = rest[index + 1], rest[index + 2 :]
            dispatch = (
                f"sys.argv = {(['-c', *extra])!r}\n"
                f"exec(compile({payload!r}, '<corpus-guard-child>', 'exec'))\n"
            )
            return [args[0], *flags, "-c", _child_bootstrap_source(config_path, dispatch)]
        if item == "-m":
            if index + 1 >= len(rest):
                raise GuardError(f"corpus preparation guard: -m 缺少模块名 {args!r}")
            module, extra = rest[index + 1], rest[index + 2 :]
            dispatch = (
                "import runpy\n"
                f"sys.argv[1:] = {extra!r}\n"
                f"runpy.run_module({module!r}, run_name='__main__', alter_sys=True)\n"
            )
            return [args[0], *flags, "-c", _child_bootstrap_source(config_path, dispatch)]
        if item in ("-X", "-W", "--check-hash-based-pycs"):
            if index + 1 >= len(rest):
                raise GuardError(f"corpus preparation guard: 选项 {item} 缺少参数 {args!r}")
            flags += [item, rest[index + 1]]
            index += 2
            continue
        if item.startswith("-"):
            flags.append(item)
            index += 1
            continue
        if item.endswith(".py"):
            extra = rest[index + 1 :]
            dispatch = (
                "import runpy\n"
                f"sys.argv = {[item, *extra]!r}\n"
                f"runpy.run_path({item!r}, run_name='__main__')\n"
            )
            return [args[0], *flags, "-c", _child_bootstrap_source(config_path, dispatch)]
        raise GuardError(f"corpus preparation guard: 阶段子进程命令无法注入守卫，拒绝派生 {args!r}")
    raise GuardError(f"corpus preparation guard: Python 子进程缺少 -c/-m/脚本参数 {args!r}")


def _prepare_child_args(args: Any, kwargs: dict[str, Any]) -> list[str]:
    """核验并按需重写子进程命令；不可保护的派生一律拒绝（fail-closed）。"""

    if isinstance(args, (str, bytes, os.PathLike)):
        raise GuardError(
            "corpus preparation guard: 拒绝字符串形式的子进程命令（无法注入守卫）；请使用列表形式"
        )
    if not isinstance(args, (list, tuple)) or not args:
        raise GuardError(f"corpus preparation guard: 子进程命令形式不可核验 {args!r}")
    items = [item if isinstance(item, str) else os.fsdecode(item) for item in args]
    if any(_CHILD_BOOTSTRAP_MARKER in item for item in items):
        return items
    if kwargs.get("shell"):
        raise GuardError("corpus preparation guard: 拒绝 shell=True 子进程（命令串不可核验）")
    executable = kwargs.get("executable")
    if executable is not None and executable != items[0]:
        raise GuardError(f"corpus preparation guard: 拒绝 executable= 覆盖 {executable!r}")
    if not _is_python_executable(items[0]):
        raise GuardError(
            "corpus preparation guard: 拒绝派生非 Python 子进程（纯 Python 守卫无法保护其"
            f"行为）: {items!r}"
        )
    return _rewrite_python_child(items, _STATE.config.path if _STATE else _REPO_ROOT / "guard.json")


def _install_popen_patch() -> None:
    """包装 subprocess.Popen：Python 子进程注入守卫引导，其余拒绝派生。"""

    original_init = subprocess.Popen.__init__

    def patched_init(self: Any, args: Any, *pargs: Any, **kwargs: Any) -> None:
        prepared = _prepare_child_args(args, kwargs)
        original_init(self, prepared, *pargs, **kwargs)  # type: ignore[arg-type]

    subprocess.Popen.__init__ = patched_init  # type: ignore[method-assign]


def install(config_path: str | Path) -> PhaseConfig:
    """在当前进程装载守卫。幂等；换配置重装视为错误。

    任何被禁模块已在本进程加载时拒绝安装（fail-closed），不允许“先污染再守卫”。
    """

    global _STATE
    if _STATE is not None:
        requested = Path(config_path).resolve()
        if requested != _STATE.config.path:
            raise GuardError(
                f"corpus preparation guard: 守卫已安装为 {_STATE.config.path}，"
                f"拒绝换配置重装 {requested}"
            )
        return _STATE.config

    config = load_phase_config(config_path)

    already_loaded = {name for name in config.blocked_modules if name in sys.modules}
    already_loaded |= {
        name
        for name in sys.modules
        if any(name.startswith(prefix) for prefix in config.blocked_module_prefixes)
    }
    if already_loaded:
        raise GuardError(
            f"corpus preparation guard: 被禁模块已先于守卫加载: {sorted(already_loaded)}"
        )

    for key in config.poisoned_env:
        os.environ[key] = GUARD_ENV_SENTINEL
    for key in config.poisoned_dsn:
        os.environ[key] = GUARD_DSN_SENTINEL

    sys.meta_path.insert(0, _ModelImportTrap(config))
    _install_popen_patch()
    sys.addaudithook(_audit)

    _STATE = GuardState(config=config, runtime_roots=_compute_runtime_roots())
    return config


def state() -> GuardState | None:
    """当前守卫状态；未安装时为 None。"""

    return _STATE


_REFUSE_SNIPPET_TEMPLATE = """import sys
import os
import socket
sys.path.insert(0, {root!r})
from plugins.corpus.preparation import guard
guard.install({config!r})
try:
{body}
except Exception as exc:
    print('REFUSED', type(exc).__name__, exc)
    raise SystemExit(3)
print('NOT_REFUSED')
raise SystemExit(0)
"""

# 合成反例：网络用例只重放 audit 事件信号，不发起真实连接或 DNS。
_SELF_CHECK_NEGATIVE_BODIES: tuple[str, ...] = (
    "    import openai",
    "    from openai import OpenAI\n    OpenAI()",
    "    import anthropic",
    "    import plugins.corpus.material_semantics",
    "    import plugins.corpus._r2_runtime",
    "    class _S:\n"
    "        family = socket.AF_INET\n"
    "    sys.audit('socket.connect', _S(), ('203.0.113.1', 443))",
    "    class _U:\n"
    "        family = socket.AF_UNIX\n"
    "    sys.audit('socket.connect', _U(), '/synthetic-guard.sock')",
)

_CONFIG_FOR_SELFCHECK: str = ""

_SELFCHECK_FINGERPRINT_PATHS: tuple[str, ...] = (
    "plugins/corpus/preparation/guard.py",
    "plugins/corpus/preparation/guard_pytest.py",
    "plugins/corpus/preparation/__init__.py",
    "tests/test_corpus_preparation_guard.py",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i0-inventory.json",
    ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json",
)


def _run_snippet(
    snippet: str, config: str | None = None, extra_args: list[str] | None = None
) -> SnippetResult:
    if config is None:
        config = _CONFIG_FOR_SELFCHECK
    env = dict(os.environ)
    env.pop("CORPUS_GUARD_PHASE", None)
    proc = subprocess.run(
        [sys.executable, "-c", snippet, *(extra_args or [])],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
        check=False,
    )
    return SnippetResult(exit_code=proc.returncode, stdout=proc.stdout, stderr=proc.stderr)


def _refusal_case(body: str, expected: str, config_path: str) -> dict[str, Any]:
    snippet = _REFUSE_SNIPPET_TEMPLATE.format(root=str(_REPO_ROOT), body=body, config=config_path)
    outcome = _run_snippet(snippet, config=config_path)
    output = outcome.stdout
    passed = outcome.exit_code == 3 and "guard" in output
    lines = [ln for ln in output.splitlines() if ln.startswith("REFUSED")]
    return {
        "case": body.strip().replace("\n", "; "),
        "expected": expected,
        "passed": passed,
        "detail": lines[-1] if lines else "",
    }


def _positive_case(
    body: str, marker: str, config_path: str, extra_args: list[str] | None = None
) -> dict[str, Any]:
    indented = "\n".join(f"    {line}" if line else line for line in body.splitlines())
    snippet = _REFUSE_SNIPPET_TEMPLATE.format(
        root=str(_REPO_ROOT), body=indented, config=config_path
    )
    outcome = _run_snippet(snippet, config=config_path, extra_args=extra_args)
    if outcome.exit_code == 0 and marker in outcome.stdout:
        detail = ""
    else:
        combined = (outcome.stdout + outcome.stderr).strip().splitlines()
        detail = combined[-1] if combined else ""
    return {
        "case": body.strip().replace("\n", "; "),
        "expected": marker,
        "passed": outcome.exit_code == 0 and marker in outcome.stdout,
        "detail": detail,
    }


def run_selfcheck(config_path: str | Path) -> dict[str, Any]:
    """用合成反例验证拒绝行为（架构 §2.1：仅“日志 0 次”不足以过门）。

    全部用例在全新子进程执行，不触真实 PG、不读来源正文、不发起公网连接或
    DNS；网络用例仅重放 ``socket.connect`` audit 事件信号。同时验证
    fail-closed 装载、子进程守卫传播与只读正例。返回可被守卫报告引用的
    结构化结果（含 report_version 与实现/配置/测试哈希绑定）。
    """

    global _CONFIG_FOR_SELFCHECK
    config = load_phase_config(config_path)
    _CONFIG_FOR_SELFCHECK = str(config.path)
    real_config = str(config.path)
    results: list[dict[str, Any]] = [
        _refusal_case(body, "refused", real_config) for body in _SELF_CHECK_NEGATIVE_BODIES
    ]

    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        tmp_root = Path(tmp)
        secret = tmp_root / "holdout" / "secret.md"
        secret.parent.mkdir()
        secret.write_text("synthetic", encoding="utf-8")
        src_dir = tmp_root / "sources"
        src_dir.mkdir()
        sample = src_dir / "sample.md"
        sample.write_text("ok", encoding="utf-8")
        (src_dir / "other.md").write_text("x", encoding="utf-8")
        protected_dir = tmp_root / "data"
        protected_dir.mkdir()
        keep = protected_dir / "keep.md"
        keep.write_text("keep", encoding="utf-8")

        synthetic = {
            "config_version": 1,
            "phase": "synthetic-selfcheck",
            "network": {"mode": "deny_all", "allowed_targets": []},
            "model": {
                "blocked_modules": ["openai", "anthropic"],
                "blocked_module_prefixes": [],
                "poisoned_env": ["OPENAI_API_KEY"],
                "poisoned_dsn": ["CORPUS_DSN"],
            },
            "sources": {
                "read_roots": [str(src_dir)],
                "allowed_source_paths": [str(sample)],
                "forbidden_roots": [str(secret.parent)],
                "protected_roots": [str(protected_dir)],
            },
        }
        synthetic_path = tmp_root / "synthetic-guard.json"
        synthetic_path.write_text(json.dumps(synthetic), encoding="utf-8")

        results.append(
            _refusal_case(f"    open({str(secret)!r}).read()", "refused", str(synthetic_path))
        )
        # 相对路径按 cwd 归一化后判定（反例 C02/C03 镜像）。
        results.append(
            _refusal_case(
                f"    os.chdir({str(tmp_root)!r})\n    open('holdout/secret.md').read()",
                "refused",
                str(synthetic_path),
            )
        )
        results.append(
            _refusal_case(
                f"    os.chdir({str(tmp_root)!r})\n    open('data/keep.md', 'w').write('x')",
                "refused",
                str(synthetic_path),
            )
        )
        # 删除/重命名保护（反例 C04 镜像）。
        results.append(
            _refusal_case(f"    os.unlink({str(keep)!r})", "refused", str(synthetic_path))
        )
        results.append(
            _refusal_case(
                f"    os.rename({str(keep)!r}, {str(tmp_root / 'moved.md')!r})",
                "refused",
                str(synthetic_path),
            )
        )
        # 允许清单文件级反例：read_roots 内但未命中 allowed_source_paths（C05 镜像）。
        results.append(
            _refusal_case(
                f"    open({str(src_dir / 'other.md')!r}).read()",
                "refused",
                str(synthetic_path),
            )
        )
        # 空 read_roots：未绑定来源根即拒绝全部非运行时读取（C06 镜像）。
        empty_roots = dict(synthetic)
        empty_roots["sources"] = {
            "read_roots": [],
            "allowed_source_paths": [],
            "forbidden_roots": [],
            "protected_roots": [],
        }
        empty_path = tmp_root / "empty-roots-guard.json"
        empty_path.write_text(json.dumps(empty_roots), encoding="utf-8")
        results.append(
            _refusal_case(f"    open({str(sample)!r}).read()", "refused", str(empty_path))
        )

        # 正例：允许清单内只读哈希（仅哈希，不读入正文）。
        results.append(
            _positive_case(
                "import hashlib\n"
                f"h = hashlib.sha256(open({str(sample)!r}, 'rb').read()).hexdigest()\n"
                "assert len(h) == 64\n"
                "print('HASH_OK')",
                "HASH_OK",
                str(synthetic_path),
            )
        )

        # CLI 包装把守卫传播进 exec 目标（C07 镜像）。
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
        results.append(
            _positive_case(
                "raise SystemExit(guard.main(sys.argv[1:]))",
                "GUARD_REFUSED",
                str(synthetic_path),
                extra_args=[
                    "--config",
                    str(synthetic_path),
                    "--",
                    sys.executable,
                    "-I",
                    "-B",
                    "-c",
                    target_code,
                ],
            )
        )
        # 非 Python 目标拒绝派生（fail-closed 声明）。
        results.append(
            _refusal_case(
                "    import subprocess\n    subprocess.run(['/bin/true'])",
                "refused",
                str(synthetic_path),
            )
        )

        # 普通子进程经命令行重写继承守卫（C08 镜像）。
        results.append(
            _positive_case(
                "import subprocess\n"
                "child = subprocess.run([sys.executable, '-I', '-B', '-c', "
                f"{target_code!r}], capture_output=True, text=True)\n"
                "assert child.returncode == 0 and 'GUARD_REFUSED' in child.stdout, "
                "child.stderr\n"
                "print('CHILD_INHERITED')",
                "CHILD_INHERITED",
                str(synthetic_path),
            )
        )

        # pytest 部分声明 fail-closed（C09 镜像）。
        results.append(
            _refusal_case(
                "    os.environ['CORPUS_GUARD_PHASE'] = 'synthetic-selfcheck'\n"
                "    os.environ.pop('CORPUS_GUARD_CONFIG', None)\n"
                "    from plugins.corpus.preparation import guard_pytest\n"
                "    guard_pytest.pytest_load_initial_conftests([], None, None)",
                "refused",
                str(synthetic_path),
            )
        )

        # exec/system/posix_spawn 派生一律拒绝。
        results.append(
            _refusal_case(
                f"    os.execvp({sys.executable!r}, [{sys.executable!r}, '-c', 'pass'])",
                "refused",
                str(synthetic_path),
            )
        )
        results.append(_refusal_case("    os.system('true')", "refused", str(synthetic_path)))
        results.append(
            _refusal_case(
                f"    os.posix_spawn({sys.executable!r}, [{sys.executable!r}, '-c', 'pass'], {{}})",
                "refused",
                str(synthetic_path),
            )
        )

        # fail-closed：被禁模块先于守卫加载时，安装必须失败。
        preloaded_config = dict(synthetic)
        preloaded_config["model"] = {
            "blocked_modules": ["json"],
            "blocked_module_prefixes": [],
            "poisoned_env": [],
            "poisoned_dsn": [],
        }
        preloaded_path = tmp_root / "preloaded-guard.json"
        preloaded_path.write_text(json.dumps(preloaded_config), encoding="utf-8")
        results.append(
            _install_case(
                str(preloaded_path),
                "install fails when blocked module already loaded",
                prelude="import json\n",
            )
        )

        # 非法配置 fail-closed：未知字段拒绝。
        bad_config = dict(synthetic)
        bad_config["unexpected_field"] = True
        bad_path = tmp_root / "bad-guard.json"
        bad_path.write_text(json.dumps(bad_config), encoding="utf-8")
        results.append(
            _install_case(
                str(bad_path), "unknown config field rejected", expect_fragment="未知字段"
            )
        )

    _CONFIG_FOR_SELFCHECK = real_config
    passed = all(item["passed"] for item in results)
    return {
        "report_version": 2,
        "phase": config.phase,
        "config": str(config.path),
        "config_sha256": config.raw_sha256,
        "passed": passed,
        "cases": results,
        "fingerprints": {
            rel: _sha256_file(_REPO_ROOT / rel) for rel in _SELFCHECK_FINGERPRINT_PATHS
        },
    }


def _install_case(
    config_path: str, case: str, prelude: str = "", expect_fragment: str = "guard"
) -> dict[str, Any]:
    snippet = (
        "import sys\n"
        f"sys.path.insert(0, {str(_REPO_ROOT)!r})\n"
        f"{prelude}"
        "from plugins.corpus.preparation import guard\n"
        "try:\n"
        f"    guard.install({config_path!r})\n"
        "    print('INSTALLED')\n"
        "    raise SystemExit(0)\n"
        "except Exception as exc:\n"
        "    print('REFUSED', type(exc).__name__, exc)\n"
        "    raise SystemExit(3)\n"
    )
    outcome = _run_snippet(snippet, config=config_path)
    output = outcome.stdout
    lines = [ln for ln in output.splitlines() if ln.startswith("REFUSED")]
    detail = lines[-1] if lines else ""
    return {
        "case": case,
        "expected": "refused",
        "passed": outcome.exit_code == 3 and expect_fragment in output,
        "detail": detail,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="语料准备阶段化执行守卫")
    parser.add_argument("--config", required=True, help="阶段守卫配置 JSON 路径")
    parser.add_argument("--selfcheck", action="store_true", help="运行合成反例自检")
    parser.add_argument("--out", type=Path, help="自检报告输出路径（write-once）")
    parser.add_argument(
        "command",
        nargs=argparse.REMAINDER,
        help="-- 之后在守卫生效下执行（仅 Python 解释器命令可派生；其余拒绝）",
    )
    args = parser.parse_args(argv)

    if args.selfcheck:
        report = run_selfcheck(args.config)
        text = json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
        if args.out is not None:
            out_path = args.out if args.out.is_absolute() else _REPO_ROOT / args.out
            if out_path.exists():
                raise GuardError(f"自检报告输出路径已存在（write-once）: {out_path}")
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(text + "\n", encoding="utf-8")
        print(text)
        return 0 if report["passed"] else 1

    install(args.config)
    command = list(args.command)
    if command and command[0] == "--":
        command = command[1:]
    if not command:
        parser.error("需要 --selfcheck 或 -- <命令>")
    if os.name != "posix":  # pragma: no cover - 本仓库目标环境为 Linux
        raise GuardError("守卫包装仅支持 POSIX")
    # 守卫经命令行重写注入 Python 子进程；exec 替换镜像会丢失守卫，故不使用。
    proc = subprocess.run(command, check=False)
    exit_code = proc.returncode
    if exit_code < 0:  # 被信号终止：按 shell 惯例 128+signum
        exit_code = 128 - exit_code
    raise SystemExit(exit_code)


if __name__ == "__main__":
    raise SystemExit(main())
