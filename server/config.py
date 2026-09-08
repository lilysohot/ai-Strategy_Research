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

from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

REPO_ROOT = Path(__file__).resolve().parents[1]


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

    # — Uploads (T2.10) ——————————————————————————————
    # Per-file and per-run caps for multipart uploads. These bound what one
    # request can write into a run's inputs dir; the agent only ever reads them.
    max_upload_bytes: int = 50 * 1024 * 1024  # 50 MiB per file
    max_upload_files: int = 20                # files per run submission

    # — Paths ————————————————————————————————————————————————
    # Root for all per-run artifacts + trajectory. Must be a persistent volume.
    runs_root: Path = REPO_ROOT / "server" / "runs"
    # Uploaded inputs (e.g. financial PDFs). Sibling to runs_root.
    uploads_root: Path = REPO_ROOT / "uploads"

    # — Database ——————————————————————————————————————————————
    database_url: str = "sqlite+aiosqlite:///./server/dev.db"

    # — Secrets ————————————————————————————————————————————————
    # Master key for Fernet-encrypting user LLM api_keys. MUST be set in prod.
    master_key: str = "dev-only-insecure-master-key-change-me"

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
        self.uploads_root.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_config() -> ServerConfig:
    cfg = ServerConfig()
    cfg.ensure_dirs()
    return cfg


def run_dir_for(run_id: str) -> Path:
    """Per-run directory tree for ``<run_id>``.

    Layout (spike-validated, tech-stack.md §5.1)::
        <runs_root>/<run_id>/
            ws/outputs/   FRONTIER_AGENT_WORKSPACE_DIR + CODING_WORKSPACE_ROOT
            inputs/       FRONTIER_AGENT_INPUTS_DIR (uploads, read-only)
            spill/        APODEX_SPILL_DIR
            run/          _trial_dir (agent/trajectories + engine.log)
    """
    return get_config().runs_root / run_id


def build_run_paths(run_id: str) -> dict[str, Path]:
    """Materialise the per-run directory tree and return the env-target paths."""
    root = run_dir_for(run_id)
    paths = {
        "root": root,
        "workspace": root / "ws",
        "outputs": root / "ws" / "outputs",
        "inputs": root / "inputs",
        "spill": root / "spill",
        "run": root / "run",
    }
    for p in paths.values():
        p.mkdir(parents=True, exist_ok=True)
    return paths
