"""Read-only product review for the I3-1 dev-lane round; writes logs only in this audit directory.

与 r33 的 `run_review.py` 同法（不改动其目录内任何绑定件——r33 的 `.txt`/`.json` 会被同一
入口重写，故本轮另建入口并写本目录）：
- 冻结链门（validate_i0c_freeze.py）；
- M5 证据只读复算（verify_matrix.verify，不调用会重写历史矩阵摘要的 main()）；
- I3 守卫下的评分器基线（tests/test_corpus_scoring.py）；
- I3 守卫下的 r33 独立反例探针（**只读原文件**）；
- I3 守卫下的本阶段 dev lane 独立反例探针（新增面）。

用法::

    env -u PYTHONPATH uv run python \
        .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260920-i31-dev-lane/run_review.py
"""

from __future__ import annotations

import json
import runpy
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[4]
PYTHON = ROOT / ".venv/bin/python"
BASE = ROOT / ".scratch/corpus-evidence-pipeline/ingestion-rebuild"
R33_PROBES = BASE / "audits/20260918-i30-review/test_review_probes.py"


def run(name: str, args: list[str], env: dict) -> int:
    result = subprocess.run(args, cwd=ROOT, env=env, text=True,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, check=False)
    (HERE / (name + ".txt")).write_text(
        "$ " + " ".join(map(str, args)) + "\n" + result.stdout +
        f"\nexit={result.returncode}\n", encoding="utf-8")
    print(name, "exit=", result.returncode)
    print(result.stdout[-1500:])
    return result.returncode


def main() -> int:
    clean = {"PATH": "/usr/bin:/bin", "LANG": "C.UTF-8",
             "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1",
             "PYTEST_DISABLE_PLUGIN_AUTOLOAD": "1"}
    codes = [run("freeze-validation",
                 [str(PYTHON), "-B", str(BASE / "freezes/validate_i0c_freeze.py")], clean)]

    verifier = runpy.run_path(str(BASE / "audits/20260918-m5-review/verify_matrix.py"))
    verified = verifier["verify"](BASE / "audits/20260918-m5-review/evidence")
    (HERE / "m5-evidence-recheck.json").write_text(
        json.dumps(verified, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print("M5 read-only evidence recheck:", len(verified["blocks"]), "blocks;",
          "misses=", verified["misses"], "errors=", verified["errors"])

    guarded = {**clean, "CORPUS_GUARD_PHASE": "i3", "CORPUS_GUARD_CONFIG":
               ".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i3.json"}
    prefix = [str(PYTHON), "-B", "-m", "pytest", "--noconftest", "-c", "/dev/null",
              "-p", "no:cacheprovider", "-p", "plugins.corpus.preparation.guard_pytest"]
    codes.append(run("baseline", [*prefix, "tests/test_corpus_scoring.py", "-q", "--tb=short"],
                     guarded))
    codes.append(run("independent-probes-r33", [*prefix, str(R33_PROBES), "-q", "--tb=short"],
                     guarded))
    codes.append(run("independent-probes-dev-lane",
                     [*prefix, str(HERE / "test_dev_lane_probes.py"), "-q", "--tb=short"],
                     guarded))
    return int(any(codes) or bool(verified["errors"]) or bool(verified["misses"]))


if __name__ == "__main__":
    raise SystemExit(main())
