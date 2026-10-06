"""Server configuration for the投研 Agent web platform.

Single source of truth for paths, concurrency, and the per-run environment that
the worker subprocess inherits. Values come from environment variables (so the
same image can be deployed with different Postgres / model defaults) with
sensible local defaults for development.

The sandbox backend is pinned to ``native`` — see ``tech-stack.md §7.2``: only
the ``native``/``container`` branches of the react node honour the
``FRONTIER_AGENT_*_DIR`` env vars, and ``native`` is the only one that needs no
CAP_SYS_ADMIN inside the container.
"""

from __future__ import annotations

import os
import uuid
from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]


def _default_web_data_dir() -> Path:
    """Source-tree-external default for Web run data (F01).

    The runtime must never write user data into the source tree: a build context
    and image layer would then carry it (F02), and a checkout wipe would lose it.
    Defaults follow the platform's per-user data convention; a service account or
    containerised deploy must set ``SERVER_RUNS_ROOT`` explicitly instead of
    inheriting a HOME/LOCALAPPDATA that may drift.
    """
    if os.name == "nt":
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / "AppData" / "Local")
        return Path(base) / "frontier-agent" / "web"
    base = os.environ.get("XDG_DATA_HOME") or str(Path.home() / ".local" / "share")
    return Path(base) / "frontier-agent" / "web"


_DEFAULT_WEB_DATA_DIR = _default_web_data_dir()

#: Placeholder the server refuses to run with outside of ``SERVER_DEBUG``. It is
#: a constant (rather than an inline literal) so the startup check and the
#: default value cannot drift apart.
INSECURE_DEFAULT_MASTER_KEY = "dev-only-insecure-master-key-change-me"


class ServerConfig(BaseSettings):
    """Runtime configuration, all overridable via environment variables.

    ``model_config`` reads ``.env`` at the repo root, so ``MASTER_KEY`` and
    ``DATABASE_URL`` can live there without being committed.
    """

    model_config = SettingsConfigDict(
        env_prefix="SERVER_",
        env_file=str(REPO_ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # — HTTP ————————————————————————————————————————————————
    host: str = "0.0.0.0"
    port: int = 8000

    # — Concurrency / timeouts ————————————————————————————————
    # Worker subprocess pool size. Runs in the *same* session are serialised by
    # the orchestrator; this is the cross-session parallelism ceiling.
    worker_pool_size: int = 2
    # Hard wall-clock budget per run, applied by the orchestrator (SIGKILL
    # fallback) and also handed to the worker via FRONTIER_AGENT_TASK_WALL_TIME_S.
    wall_timeout_s: int = 900
    # Max agent turns before the worker stops the loop on its own.
    max_turns: int = 60
    # Grace period the orchestrator waits for a worker to exit before SIGKILL.
    stop_grace_period_s: int = 30

    # — Dispatch outbox (DATA-06) ————————————————————————————
    # Business runs are dispatched through a persistent outbox with leases, so a
    # committed submit survives an API crash. The dispatcher runs as a task
    # inside the API process; multi-process deployments share the work via
    # SKIP LOCKED claiming, not via a separate singleton.
    dispatch_enabled: bool = True
    dispatch_poll_seconds: float = 1.0
    # Lease length: how long a claim may go unreported before another process
    # may re-examine the run. Generous on purpose — re-claim first verifies the
    # run never started, so a slow (but alive) claimer is not raced.
    dispatch_lease_seconds: int = 120
    dispatch_max_attempts: int = 5
    # When the research already has an active run, back off instead of failing.
    dispatch_busy_delay_seconds: int = 5
    # Per-research cap on un-finished dispatch intents (pending/claimed/dispatched).
    # Without it a client can pile up unbounded queued runs behind a slow worker;
    # submission past the cap is rejected with 429 quota_exceeded instead.
    dispatch_research_queue_limit: int = 20
    # How long a rerun waits for the superseded worker to be confirmed stopped
    # before giving up. Native runs write into the run tree directly, so a new
    # execution must not overlap an old one that is still alive.
    dispatch_stop_timeout_seconds: float = 30.0

    # — Monitor (DATA-10) ————————————————————————————————
    # 监控常驻轮询默认关闭：部署时显式开启（DATA-00 §5 后台进程登记）。监控链不调用 LLM。
    monitor_enabled: bool = False
    monitor_poll_seconds: float = 60.0
    # 相邻观测间隔超过该值视为断线缺口：恢复后首个报价按 disconnect_recovery 处理。
    monitor_max_gap_seconds: float = 300.0
    # 每轮最多判定的规则数与去重后标的数（轮询容量上限，防止拖垮行情额度）。
    monitor_batch_rules: int = 50
    monitor_max_symbols: int = 20

    # — Uploads (T2.10) ——————————————————————————————
    # Per-file and per-run caps for multipart uploads. These bound what one
    # request can write into a run's inputs dir; the agent only ever reads them.
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MiB per file
    max_upload_files: int = 20  # files per run submission

    # — Paths ————————————————————————————————————————————————
    # Root for all per-run artifacts + trajectory. Source-tree-external by
    # default (F01); set SERVER_RUNS_ROOT to pin a stable service path.
    runs_root: Path = _DEFAULT_WEB_DATA_DIR / "runs"

    # — Database ——————————————————————————————————————————————
    database_url: str = "sqlite+aiosqlite:///./server/dev.db"

    # — Secrets ————————————————————————————————————————————————
    # Master key for Fernet-encrypting user LLM api_keys. MUST be set in prod.
    # Rotating it makes every stored api_key_cipher undecryptable — users have
    # to re-enter their keys. See deploy/README.md.
    master_key: str = INSECURE_DEFAULT_MASTER_KEY

    # Signing key for JWTs. Kept separate from master_key on purpose: sharing
    # one value means a single leak gives away both the encrypted LLM
    # credentials and every live session token.
    jwt_secret: str = ""

    # Local-development escape hatch: skips the startup secret checks
    # (see security.check_startup_secrets). Never set this in a deployment.
    debug: bool = False

    # — Model / sandbox ——————————————————————————————————————
    sandbox_backend: str = "native"
    # Default system model (used only when a user has no LLM config). The actual
    # credentials come from the repo .env (OPENAI_*), which load_dotenv loads at
    # import time in infra.config — see tech-stack.md §5.3.
    default_model: str = "glm-5.3-flash"
    default_base_url: str = "https://open.bigmodel.cn/api/paas/v4"

    # — Pipeline ——————————————————————————————————————————————
    pipeline_id: str = "stateful-react-agent"

    @property
    def fernet_key(self) -> bytes:
        """Derive a 32-byte url-safe key from ``master_key``.

        ``cryptography.Fernet`` requires a 32-byte base64-encoded key; we stretch
        whatever the operator supplies so they never have to pre-encode it.
        """
        import base64
        import hashlib

        digest = hashlib.sha256(self.master_key.encode("utf-8")).digest()
        return base64.urlsafe_b64encode(digest)

    def ensure_dirs(self) -> None:
        self.runs_root.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_config() -> ServerConfig:
    cfg = ServerConfig()
    cfg.ensure_dirs()
    return cfg


def canonical_run_id(run_id: str) -> str:
    """The one canonical spelling of a run id: 32 lowercase hex characters.

    Run ids reach us in two legal forms — ``submit`` returns the compact hex
    form while the session/run read models return the hyphenated UUID — and both
    are valid inputs to every run route. Because the per-run directory is built
    by *concatenating* the string, the two spellings addressed DIFFERENT
    directories, so a hyphenated id produced an empty trace that looked like
    "no trajectory was ever recorded" (F01). Normalising here means every
    spelling of an id resolves to the same run.

    A value that is not a UUID is returned unchanged: the caller's ownership
    lookup then rejects it as "not found", and no path is ever built from an
    unparsed string in a way the parse would have made safe.
    """
    try:
        return uuid.UUID(run_id).hex
    except (ValueError, AttributeError, TypeError):
        return run_id


def run_dir_for(run_id: str) -> Path:
    """Per-run directory tree for ``<run_id>``.

    Layout (spike-validated, tech-stack.md §5.1)::
        <runs_root>/<run_id>/
            ws/outputs/   FRONTIER_AGENT_WORKSPACE_DIR + CODING_WORKSPACE_ROOT
            inputs/       FRONTIER_AGENT_INPUTS_DIR (uploads, read-only)
            spill/        APODEX_SPILL_DIR
            run/          _trial_dir (agent/trajectories + engine.log)

    ``run_id`` is canonicalised first (see :func:`canonical_run_id`) so the
    hyphenated and compact spellings of the same id land on the same directory.
    """
    return get_config().runs_root / canonical_run_id(run_id)


def build_run_paths(run_id: str) -> dict[str, Path]:
    """Materialise the per-run directory tree and return the env-target paths."""
    root = run_dir_for(run_id)
    paths = {
        "root": root,
        "workspace": root / "ws",
        "outputs": root / "ws" / "outputs",
        # Uploads land here first (DATA-06 受控暂存区) so a partially written
        # attachment never appears in the read-only ``inputs`` a worker may read.
        "staging": root / "staging",
        "inputs": root / "inputs",
        "spill": root / "spill",
        "run": root / "run",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths
