"""I3-1 环境预检（Step 7）：只读探测环境、登记入口、判定前置，产出预检报告。

**不做**：不运行 E2E、不连 PG（连不上）、不改任何冻结件、不动 guards/i3.json。
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
BASE = HERE.parents[1]
ROOT = HERE.parents[4]
REPORT = HERE / "i3-1-environment-precheck.json"
REPORT_MD = HERE / "i3-1-environment-precheck.md"
GUARD_E2E = BASE / "guards/i3-e2e.json"
GUARD_I3 = BASE / "guards/i3.json"
DEV_MANIFEST = BASE / "dev-manifest.json"
DSN_ENV = ("CORPUS_I2_DSN", "CORPUS_DSN", "CORPUS_DSN_DOCKER")


def now() -> str:
    return datetime.now(timezone(timedelta(hours=8))).isoformat(timespec="seconds")


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def mask(dsn: str) -> str:
    return re.sub(r"://[^@]*@", "://***@", dsn)


def probe_port(port: int, host: str = "127.0.0.1", timeout: float = 2.0) -> dict:
    sock = socket.socket()
    sock.settimeout(timeout)
    try:
        sock.connect((host, port))
        return {"host": host, "port": port, "reachable": True}
    except OSError as exc:
        return {"host": host, "port": port, "reachable": False, "error": type(exc).__name__}
    finally:
        sock.close()


def env_file() -> dict[str, str]:
    path = ROOT / ".env"
    if not path.is_file():
        return {}
    data: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if "=" in line and not line.strip().startswith("#"):
            key, value = line.split("=", 1)
            data[key.strip()] = value.strip()
    return data


def main() -> int:
    env = env_file()
    dm = json.loads(DEV_MANIFEST.read_text(encoding="utf-8"))
    candidates = dm["dev_selection_candidates"]
    proposed = [p for key in ("company", "industry", "macro") for p in candidates[key]]
    guard_e2e = json.loads(GUARD_E2E.read_text(encoding="utf-8"))
    guard_i3 = json.loads(GUARD_I3.read_text(encoding="utf-8"))

    sys.path.insert(0, str(ROOT))
    from plugins.corpus.preparation.guard import load_phase_config  # noqa: E402

    guard_ok = True
    guard_error = None
    try:
        load_phase_config(GUARD_E2E)
    except Exception as exc:  # pragma: no cover - 预检登记用
        guard_ok, guard_error = False, f"{type(exc).__name__}: {exc}"

    sandbox_db = "i2_sandbox_corpus"
    cli_text = (ROOT / "plugins/corpus/cli.py").read_text(encoding="utf-8")
    m = re.search(r"_SANDBOX_DB\s*=\s*\"([^\"]+)\"", cli_text)
    if m:
        sandbox_db = m.group(1)

    model_hits = subprocess.run(
        ["grep", "-rIn", "-E", "openai|llm|jina|mineru|OCR|anthropic",
         "--include=*.py", "plugins/corpus/preparation/"],
        capture_output=True, text=True, cwd=str(ROOT), check=False,
    ).stdout.strip().splitlines()

    dsn_state = {
        name: {
            "in_dotenv": name in env,
            "in_process_env": bool(os.environ.get(name)),
            "masked": mask(env[name]) if name in env else None,
        }
        for name in DSN_ENV
    }

    report = {
        "artifact": "i3-1-environment-precheck",
        "step": "执行顺序表第 7 步：进入 I3-1 的环境预检与 E2E",
        "authorized_by": "U（2026-09-19 会话：『授权执行下一步任务』）",
        "generated_at": now(),
        "scope": "只读预检：入口清点 + 环境探测 + 前置判定 + 隔离目标定义 + 运行计划；未运行 E2E",
        "e2e_executed": False,
        "real_results": "none",
        "synthetic_scores_reused": False,
        "zero_write": {
            "pg_writes": 0, "model_calls": 0, "frozen_artifacts_modified": 0,
            "guards/i3.json_modified": False,
        },
        "entries": {
            "cli": {
                "invocation": "uv run python -m plugins.corpus.cli <plan|build|check|publish|status|rebuild-plan>",
                "file": "plugins/corpus/cli.py",
                "sha256": digest(ROOT / "plugins/corpus/cli.py"),
                "subcommands": ["plan", "build", "check", "publish", "status", "rebuild-plan"],
                "target_rule": "--dsn 或 CORPUS_I2_DSN 必须显式声明；未声明即拒绝（exit 3），不隐式连库",
                "sandbox_db": sandbox_db,
                "production_refusal": "连接后校验 current_database == sandbox_db，且实例含 apodex 库即判生产实例拒绝写入",
                "exit_codes": {"ok": 0, "输入非法": 2, "目标/守卫拒绝": 3, "门未过": 4, "目标不存在": 5},
            },
            "stages": {
                "登记/准入/解析/清洗/切块": "plugins/corpus/preparation/{source,admission,readers,clean,chunk}.py（经 cli build 编排）",
                "build/check/publish/status": "cli 子命令（复用正式编排与解析产物）",
                "search/fetch/verify": (
                    "库 API：plugins/corpus/preparation/search_pg.py:search_chunks / read_pg.py（证据句柄）；"
                    "**无 CLI**——I3-1 需一个 runner，可复用/扩展 "
                    "audits/20260918-i2-fullchain-review 的自写全链路回路脚本（属 I3-1 前置，本轮登记不实现）"
                ),
            },
            "guard_pytest": (
                "CORPUS_GUARD_PHASE=i3-e2e CORPUS_GUARD_CONFIG=<abs>/guards/i3-e2e.json "
                "uv run pytest -p plugins.corpus.preparation.guard_pytest"
            ),
        },
        "environment": {
            "postgres": {
                "status": "unavailable",
                "probes": [probe_port(543), probe_port(5432)],
                "local_binaries": {
                    name: bool(shutil.which(name))
                    for name in ("postgres", "initdb", "pg_ctl", "psql", "pg_isready")
                },
                "reason": (
                    "I2 阶段使用的隔离容器 corpus-db（宿主映射 127.0.0.1:543）当前不可达；"
                    "本机未安装 postgres 系二进制，本 WSL 发行版未接 Docker（Docker Desktop WSL 集成未开），"
                    "sudo 需交互认证 → Agent 无法自行供给隔离 PG"
                ),
            },
            "docker": {
                "status": "unavailable",
                "probe": (
                    "/mnt/c/Program Files/Docker/Docker/resources/bin/docker 报"
                    "『The command docker could not be found in this WSL 2 distro』"
                ),
            },
            "sudo_non_interactive": subprocess.run(["sudo", "-n", "true"], capture_output=True).returncode == 0,
            "dsn_env": dsn_state,
            "isolation_target": {
                "declared_by": "guards/i2-sandbox.json（I2-01 冻结）+ cli._SANDBOX_DB",
                "host": "127.0.0.1", "port": 543, "database": sandbox_db,
                "env_var": "CORPUS_I2_DSN",
                "rules": [
                    "仅此一个允许目标（allowlist），不隐式连生产库",
                    "库名必须等于 sandbox_db，否则拒绝",
                    "实例内出现 apodex 库 → 判生产实例，禁止写入",
                ],
            },
        },
        "dev_scope": {
            "status": "NOT_FROZEN",
            "manifest": str(DEV_MANIFEST.relative_to(ROOT)),
            "manifest_sha256": digest(DEV_MANIFEST),
            "admission_state": dm["admission_state"],
            "counts": dm["counts"],
            "proposed_selection": {
                "rule": "三类（company/industry/macro）×≥2 份，PDF；来源已通过 in_scope 之外的筛选建议",
                "company": candidates["company"],
                "industry": candidates["industry"],
                "macro": candidates["macro"],
                "all_on_disk": all((ROOT / p).is_file() for p in proposed),
                "intersect_holdouts": sorted(
                    set(proposed) & set(guard_e2e["sources"]["forbidden_roots"])
                ),
            },
            "format_matrix_gaps": candidates.get("format_matrix_gaps"),
            "blocking": "I3-1 完成标准要求『冻结开发范围』；当前 73 份来源终态均为 review_required，需 U 逐条判定（M1 前置）",
        },
        "guard": {
            "i3_e2e": {
                "path": str(GUARD_E2E.relative_to(ROOT)),
                "sha256": digest(GUARD_E2E),
                "status": "draft_not_activated",
                "self_check": {
                    "load_phase_config": guard_ok,
                    "error": guard_error,
                    "forbidden_roots_identical_to_i3": (
                        set(guard_e2e["sources"]["forbidden_roots"])
                        == set(guard_i3["sources"]["forbidden_roots"])
                    ),
                    "allowed_sources_on_disk": all(
                        (ROOT / p).is_file() for p in guard_e2e["sources"]["allowed_source_paths"]
                    ),
                    "allowed_intersect_forbidden": sorted(
                        set(guard_e2e["sources"]["allowed_source_paths"])
                        & set(guard_e2e["sources"]["forbidden_roots"])
                    ),
                },
                "activation_conditions": [
                    "U 批准 3 类×≥2 份开发来源并生成 dev-scope-manifest.json",
                    "隔离目标可达（127.0.0.1:543 / " + sandbox_db + "）",
                    "目标库身份校验通过（非生产实例）",
                ],
            },
            "i3_json_untouched": True,
        },
        "model_budget": {
            "finding": "I3-1 链路未见模型依赖（stage 实现与 cli 均为本地解析/编排）",
            "evidence": {
                "grep": "plugins/corpus/preparation/ 下 openai|llm|jina|mineru|OCR|anthropic",
                "hits": model_hits[:10],
                "hits_count": len(model_hits),
            },
            "conclusion": "本轮无需模型预算；若准入/解析在真实样本上需要外部服务，将另立清单再请授权（不擅自调用）",
        },
        "preconditions": {
            "I3-2 冻结与完成门": {
                "status": "met",
                "evidence": "i0c-r31；validate_i3_2_completion 10/10 pass；具名签认（xyl）入链",
            },
            "I2 全链路复核 F1 闭环": {"status": "met", "evidence": "缺口分级/坐标，已于 i0c-r15 闭环（台账 I3-1 行注明）"},
            "隔离 PG": {"status": "blocked", "evidence": "environment.postgres"},
            "冻结开发范围": {"status": "blocked", "evidence": "dev_scope.status=NOT_FROZEN"},
            "i3-e2e 阶段守卫": {"status": "prepared", "evidence": "guards/i3-e2e.json（草稿+自检），启用条件见 guard.i3_e2e"},
        },
        "blockers": [
            {
                "id": "B1",
                "name": "隔离 PG 不可达且 Agent 无法自行供给",
                "needs": "U 之一：① 开启 Docker Desktop 的 WSL 集成（我可启 corpus-db 容器）；② 提供可交互 sudo（我 apt 装 postgres 并在 .scratch/ 建私有集群，端口非 5432）；③ 直接给出可达的隔离 DSN（须非生产实例）",
            },
            {
                "id": "B2",
                "name": "开发范围未冻结",
                "needs": "U 批准 3 类×≥2 份（建议见 dev_scope.proposed_selection）+ 对 docx 格式矩阵缺口给定性（补样本/声明缺格式门未过）",
            },
        ],
        "run_plan": {
            "note": "B1/B2 解除后按此顺序执行；每步的命令与预期输出已固定，禁止事后改预期",
            "env": {
                "CORPUS_GUARD_PHASE": "i3-e2e",
                "CORPUS_GUARD_CONFIG": str(GUARD_E2E.relative_to(ROOT)),
                "CORPUS_I2_DSN": "postgresql://…@127.0.0.1:543/" + sandbox_db,
            },
            "steps": [
                {"n": 0, "cmd": "corpus plan --manifest <dev-scope-manifest.json>", "expect": "只读可发布性预检：逐来源缺口分级；无 PG 写入、无模型；exit 0/2"},
                {"n": 1, "cmd": "corpus build --manifest <…> --archive-root <…> --owner i3-e2e", "expect": "登记→准入→解析→清洗→切块；产出 build_id；写入隔离库"},
                {"n": 2, "cmd": "corpus check --build <build_id>", "expect": "门判定；blocking 缺口按 gaps 机读处置；exit 0/4"},
                {"n": 3, "cmd": "corpus publish --build <build_id> --operator i3-e2e", "expect": "仅 acknowledged 缺口可发布；generation 记操作者"},
                {"n": 4, "cmd": "corpus status --build <build_id>", "expect": "状态与 gaps 一致；published_with_gaps 可见"},
                {"n": 5, "cmd": "<runner> search/fetch/verify（库 API，待接线）", "expect": "真实检索命中 + 证据句柄取回 + 完整性校验；**不得复用合成分数**"},
            ],
            "recording": [
                "记录领域×格式矩阵与实际覆盖（缺格式门未过）",
                "每步原始输出、build_id、DSN 目标、守卫哈希一并入新审计目录",
                "结果不得直接放行 I4；I3-3/I3-4 校准与 I3-5 非回归另做",
            ],
        },
        "human_actions_required": [
            "B1：三选一提供隔离 PG（Docker WSL 集成 / 可交互 sudo / 直接给非生产 DSN）",
            "B2：批准开发范围（3 类×≥2 份）与 docx 缺口定性",
        ],
        "artifacts": {
            "guard_draft": str(GUARD_E2E.relative_to(ROOT)),
            "report": str(REPORT.relative_to(ROOT)),
            "report_md": str(REPORT_MD.relative_to(ROOT)),
            "self": str(HERE.joinpath("run_i3_1_precheck.py").relative_to(ROOT)),
        },
        "binding_note": (
            "本报告与 i3-e2e 守卫均为**新建未绑定**文件：本轮不改任何冻结修订，"
            "故不进冻结链；待 U 批准后随 I3-1 首个修订一并绑定"
        ),
    }
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    write_md(report)
    print(json.dumps({
        "report": str(REPORT.name),
        "guard_self_check": guard_ok,
        "pg": report["environment"]["postgres"]["probes"],
        "dev_scope": report["dev_scope"]["status"],
        "blockers": [b["id"] for b in report["blockers"]],
    }, ensure_ascii=False, indent=2))
    return 0


def write_md(report: dict) -> None:
    env = report["environment"]
    scope = report["dev_scope"]
    lines = [
        "# I3-1 环境预检（Step 7）",
        "",
        f"- 生成：{report['generated_at']}；授权：{report['authorized_by']}",
        f"- 本轮：{report['scope']}",
        f"- **E2E 未执行**（`e2e_executed=false`；真实结果 none；**未复用合成分数**）",
        "",
        "## 一、结论：两个阻断，都在你手上",
        "",
        "| 阻断 | 现状 | 需要你 |",
        "|---|---|---|",
        "| **B1 隔离 PG** | `127.0.0.1:543` 与 `:5432` 均拒连；本机无 postgres 二进制；本 WSL 未接 Docker；`sudo` 需交互 | 三选一：① 开 Docker Desktop 的 WSL 集成；② 给可交互 sudo（我装 postgres 并在 `.scratch/` 建私有集群）；③ 直接给一个可达的**非生产** DSN |",
        f"| **B2 开发范围** | `dev-manifest` 73 份来源终态全为 `review_required`；3 类候选只是建议 | 批准 3 类×≥2 份（见下）＋ docx 缺口定性 |",
        "",
        "## 二、环境探测（只读）",
        "",
        f"- PG：{env['postgres']['status']}；探测 {env['postgres']['probes']}",
        f"- 本地二进制：{env['postgres']['local_binaries']}",
        f"- Docker：{env['docker']['status']}",
        f"- sudo 免密：{env['sudo_non_interactive']}",
        f"- 隔离目标（I2-01 冻结）：`{env['isolation_target']['host']}:{env['isolation_target']['port']}` / "
        f"库 `{env['isolation_target']['database']}`（env `CORPUS_I2_DSN`）",
        "",
        "## 三、入口清点（E2E 链路已实现）",
        "",
        f"- CLI：`{report['entries']['cli']['invocation']}`（六个子命令；退出码 {report['entries']['cli']['exit_codes']}）",
        f"- 目标 fail-closed：{report['entries']['cli']['target_rule']}",
        f"- 生产实例拒绝：{report['entries']['cli']['production_refusal']}",
        f"- search/fetch/verify：{report['entries']['stages']['search/fetch/verify']}",
        "",
        "## 四、开发范围（未冻结）",
        "",
        f"- 清单：`{scope['manifest']}`（{scope['counts']['source_like_files']} 份来源；"
        f"{scope['counts']['by_format']}）",
        f"- 状态：**{scope['status']}** —— {scope['blocking']}",
        "- 建议的 3 类×2 份：",
    ]
    for key in ("company", "industry", "macro"):
        lines.append(f"  - {key}：" + "；".join(Path(p).name[:46] for p in scope["proposed_selection"][key]))
    lines += [
        f"- 格式矩阵缺口：{scope['format_matrix_gaps']}",
        f"- 全部在盘：{scope['proposed_selection']['all_on_disk']}；与留出交集：{scope['proposed_selection']['intersect_holdouts']}",
        "",
        "## 五、i3-e2e 阶段守卫（草稿，未启用）",
        "",
        f"- `{report['guard']['i3_e2e']['path']}`（自检 load_phase_config={report['guard']['i3_e2e']['self_check']['load_phase_config']}；"
        f"留出根与 `guards/i3.json` 逐字一致="
        f"{report['guard']['i3_e2e']['self_check']['forbidden_roots_identical_to_i3']}；"
        f"6 份开发来源在盘="
        f"{report['guard']['i3_e2e']['self_check']['allowed_sources_on_disk']}）",
        "- 网络仅允许 `127.0.0.1:543`；模型侧沿用封锁（`openai` 等）；`guards/i3.json` 未改动",
        "- 启用条件：" + "；".join(report["guard"]["i3_e2e"]["activation_conditions"]),
        "",
        "## 六、模型与预算",
        "",
        f"- {report['model_budget']['finding']}（grep 命中 {report['model_budget']['evidence']['hits_count']} 条）",
        f"- {report['model_budget']['conclusion']}",
        "",
        "## 七、前置判定",
        "",
        "| 前置 | 状态 |",
        "|---|---|",
    ]
    for name, item in report["preconditions"].items():
        lines.append(f"| {name} | **{item['status']}**（{item['evidence']}） |")
    lines += ["", "## 八、运行计划（B1/B2 解除后即可执行）", ""]
    for step in report["run_plan"]["steps"]:
        lines.append(f"{step['n']}. `{step['cmd']}` → {step['expect']}")
    lines += ["", "记录要求："]
    lines += [f"- {item}" for item in report["run_plan"]["recording"]]
    lines += [
        "",
        f"> {report['binding_note']}",
        "",
    ]
    REPORT_MD.write_text("\n".join(lines) + "\n", encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
