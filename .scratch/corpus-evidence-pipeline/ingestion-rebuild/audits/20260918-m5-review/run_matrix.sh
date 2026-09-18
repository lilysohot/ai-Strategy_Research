#!/usr/bin/env bash
# M5 独立复核命令矩阵（审计材料，只记录证据，不做判定）。
#
# 用法（仓库根目录；需已导出 CORPUS_I2_DSN 指向 i2_sandbox_corpus）：
#   bash .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/run_matrix.sh
#
# 执行模型：
#   前置门（冻结验证器 / 哈希留痕 / 目标双校验 / 守卫自检）任一失败 → 立即停止（exit 2）；
#   行为/静态块失败 → 继续收集证据；运行后重跑冻结验证器（绑定零漂移门，失败 exit 2）；
#   末尾 verify_matrix.py 按 JUnit XML 精确核对计数，产出 matrix-summary.json。
# 脚本退出码：0 = 矩阵与预期一致；1 = 存在 MISS；2 = 前置门或运行后门失败。
# 退出码只表示「矩阵与预期一致」，不构成 M5 裁决。
# 结果 write-once 落 evidence/（已存在即拒绝）。
# M5_REVIEW_EVIDENCE_DIR 可重定向 evidence 目录（仅供申请方演练；正式复核必须用默认值）。
set -u

AUDIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$AUDIT_DIR/../../../../.." && pwd)"
EV="${M5_REVIEW_EVIDENCE_DIR:-$AUDIT_DIR/evidence}"

cd "$REPO_ROOT" || { echo "无法进入仓库根: $REPO_ROOT"; exit 2; }
if [ -e "$EV" ]; then
  echo "拒绝：evidence 目录已存在（write-once）: $EV"
  exit 2
fi
mkdir -p "$EV"

GUARD_I2=".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json"
GUARD_I1=".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json"
FREEZE=".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
AUD=".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits"

DSN="${CORPUS_I2_DSN:-}"
if [ -z "$DSN" ]; then
  echo "拒绝：未声明 CORPUS_I2_DSN（矩阵只对被测隔离目标运行）"
  exit 2
fi

# 受控最小环境需显式纳入 node（pyright 依赖；本机 node 位于 nvm 路径，不在 /usr/bin）
NODE_DIR="$(dirname "$(command -v node 2>/dev/null)" 2>/dev/null || true)"
CTRL_PATH="/usr/bin:/bin"
[ -n "$NODE_DIR" ] && CTRL_PATH="$CTRL_PATH:$NODE_DIR"

fail() { echo "GATE FAILED: $1（证据: $EV）" >&2; exit 2; }

BLOCK=""
run() { # 行为/静态块：失败继续收集证据，仅留痕
  BLOCK="$1"; shift
  local rc=0
  "$@" > "$EV/$BLOCK.log" 2>&1 || rc=$?
  echo "$BLOCK exit=$rc" | tee -a "$EV/index.txt"
}
gate() { # 前置/后置门：失败立即停止
  BLOCK="$1"; shift
  local rc=0
  "$@" > "$EV/$BLOCK.log" 2>&1 || rc=$?
  echo "$BLOCK exit=$rc" | tee -a "$EV/index.txt"
  [ "$rc" -eq 0 ] || fail "$BLOCK 未通过"
}

# 守卫环境（i2-verify）：env -i 零继承；显式传 DSN；守卫先于测试收集装载；禁插件自动加载与 conftest
i2_guard_pytest() {
  env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$REPO_ROOT" \
    PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    CORPUS_I2_DSN="$DSN" \
    CORPUS_GUARD_PHASE=i2-verify CORPUS_GUARD_CONFIG="$GUARD_I2" \
    .venv/bin/python -B -m pytest --noconftest -c /dev/null \
    -p no:cacheprovider -p plugins.corpus.preparation.guard_pytest \
    --junitxml="$EV/$BLOCK.xml" "$@" -q --tb=short
}
# 守卫环境（i1）：preparation 业务套件（无 PG/无网络）
i1_guard_pytest() {
  env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$REPO_ROOT" \
    PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    CORPUS_GUARD_PHASE=i1 CORPUS_GUARD_CONFIG="$GUARD_I1" \
    .venv/bin/python -B -m pytest --noconftest -c /dev/null \
    -p no:cacheprovider -p plugins.corpus.preparation.guard_pytest \
    --junitxml="$EV/$BLOCK.xml" "$@" -q --tb=short
}
# 受控普通环境：env -i 最小继承（node 显式纳入，供 pyright；HOME 显式声明），
# pytest 同样禁用插件自动加载与 conftest。普通环境 ≠ 允许连接 PG 或模型。
plain() {
  env -i PATH="$CTRL_PATH" LANG=C.UTF-8 PYTHONPATH="$REPO_ROOT" \
    HOME="${HOME:-/root}" PYTHONDONTWRITEBYTECODE=1 \
    PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 "$@"
}
plain_pytest() {
  plain .venv/bin/python -B -m pytest --noconftest -c /dev/null \
    -p no:cacheprovider --junitxml="$EV/$BLOCK.xml" "$@" -q --tb=short
}

BUSINESS_I1=(
  tests/test_corpus_preparation_release_gate.py
  tests/test_corpus_preparation_counterexamples.py
  tests/test_corpus_preparation_remediation.py
  tests/test_corpus_preparation_contract.py
  tests/test_corpus_preparation_engine.py
  tests/test_corpus_preparation_fixtures.py
  tests/test_corpus_preparation_readers.py
  tests/test_corpus_preparation_source.py
  tests/test_corpus_preparation_admission.py
  tests/test_corpus_preparation_chunk.py
  tests/test_corpus_preparation_clean.py
)

I2_CHANGED_FILES=(
  plugins/corpus/preparation/read_pg.py
  plugins/corpus/preparation/search_pg.py
  plugins/corpus/preparation/engine.py
  plugins/corpus/preparation/clean.py
  plugins/corpus/preparation/gaps.py
  plugins/corpus/service.py
  plugins/corpus/cli.py
  plugins/corpus/audit.py
  plugins/tools/corpus_search.py
  plugins/tools/corpus_fetch.py
  plugins/tools/data_coverage.py
  tests/test_corpus_authority_pg.py
  tests/test_corpus_cli_isolation.py
  tests/test_corpus_consumers_pg.py
  tests/test_corpus_cli_pg.py
  tests/test_corpus_coverage.py
  tests/test_corpus_gap_dispositions.py
  tests/test_data_coverage.py
)

: > "$EV/index.txt"
{
  echo "uname: $(uname -a)"
  echo "git HEAD: $(git rev-parse HEAD 2>/dev/null || echo n/a)"
  echo "python: $(.venv/bin/python -V 2>&1)"
  echo "node: $(node -v 2>/dev/null || echo missing)"
  echo "repo: $REPO_ROOT"
  echo "target dsn host/port/db: $(printf '%s' "$DSN" | sed -E 's#.*@([^/]+)/(.*)#\1/\2#')"
  sha256sum "$AUDIT_DIR/README.md" "$AUDIT_DIR/run_matrix.sh" "$AUDIT_DIR/verify_matrix.py" \
    "$AUDIT_DIR/cross-check.md"
} > "$EV/environment.txt" 2>&1

echo "== 前置门（任一失败立即停止，exit 2）"
gate freeze-validator .venv/bin/python "$FREEZE/validate_i0c_freeze.py"
gate freeze-hashes sha256sum \
  "$FREEZE/i0c-r15.json" "$FREEZE/i0c-r14.json" "$FREEZE/i0c-r13.json" \
  "$FREEZE/i0c-r12.json" "$FREEZE/i0c-r11.json" \
  "$FREEZE/freeze-manifest.json" "$FREEZE/validate_i0c_freeze.py" \
  "$GUARD_I2" ".scratch/corpus-evidence-pipeline/ingestion-rebuild/i2-verify-guard-report.json"
gate target-guard env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$REPO_ROOT" \
  CORPUS_I2_DSN="$DSN" .venv/bin/python -c "
import os, psycopg
expected = 'i2_sandbox_corpus'
with psycopg.connect(os.environ['CORPUS_I2_DSN'], autocommit=True) as conn:
    cur = conn.execute('SELECT current_database()')
    db = cur.fetchone()[0]
    dbs = {r[0] for r in conn.execute('SELECT datname FROM pg_database WHERE datallowconn').fetchall()}
if db != expected:
    raise SystemExit(f'REFUSED: current_database={db!r} != {expected!r}')
if 'apodex' in dbs:
    raise SystemExit('REFUSED: 目标实例含 apodex 库（判定为生产实例）')
print('TARGET_OK', db)
"
gate guard-selfcheck plain .venv/bin/python -m plugins.corpus.preparation.guard \
  --config "$GUARD_I2" --selfcheck --out "$EV/guard-selfcheck.json"

echo "== 行为矩阵（守卫 env / 受控普通 env；失败继续收集证据）"
run publication-pg i2_guard_pytest tests/test_corpus_preparation_publication_pg.py
run repository-pg i2_guard_pytest tests/test_corpus_preparation_repository_pg.py
run authority-pg i2_guard_pytest tests/test_corpus_authority_pg.py
run cli-isolation i2_guard_pytest tests/test_corpus_cli_isolation.py
run consumers-pg i2_guard_pytest tests/test_corpus_consumers_pg.py
run cli-pg i2_guard_pytest tests/test_corpus_cli_pg.py
run i28-i24-probes i2_guard_pytest "$AUD/20260918-i2-8-i2-4-review/test_review_probes.py"
# i0c-r15 起纳管（RM-FC-8）：全链路回路（9 链不变量 + check/status 缺口契约，write-once 不修改）
# 与缺口裁决回归；六族只做 store/service 级操作，链级契约只有这两个文件守得住。
run i2-fullchain-probes i2_guard_pytest "$AUD/20260918-i2-fullchain-review/test_fullchain_probes.py"
run i2-gap-dispositions i2_guard_pytest tests/test_corpus_gap_dispositions.py
run i1-business-guard-env i1_guard_pytest "${BUSINESS_I1[@]}"
run guard-tests-normal-env plain_pytest tests/test_corpus_preparation_guard.py

echo "== 静态检查（受控最小环境；失败继续收集证据）"
run ruff-check plain .venv/bin/python -m ruff check plugins apodex benchmarks workflows deploy tools scripts
run ruff-format-check plain .venv/bin/python -m ruff format --check "${I2_CHANGED_FILES[@]}"
run pyright-i2-scope plain .venv/bin/python -m pyright plugins/corpus plugins/tools
run import-smoke-stage1 plain .venv/bin/python -B tools/import_smoke.py --stage 1

echo "== 运行后复核（绑定零漂移门失败即停；哈希留痕）"
gate postflight-freeze-revalidate .venv/bin/python "$FREEZE/validate_i0c_freeze.py"
sha256sum \
  "$FREEZE/validate_i0c_freeze.py" "$AUDIT_DIR/run_matrix.sh" "$AUDIT_DIR/verify_matrix.py" \
  "$FREEZE/i0c-r15.json" "$FREEZE/i0c-r13.json" \
  "$AUD/20260918-i2-8-i2-4-review/test_review_probes.py" \
  "$AUD/20260918-i2-fullchain-review/test_fullchain_probes.py" \
  tests/test_corpus_gap_dispositions.py \
  tests/test_corpus_authority_pg.py tests/test_corpus_cli_isolation.py \
  uv.lock > "$EV/postflight-hashes.txt" 2>&1 || fail "运行后哈希留痕失败"

echo "== 汇总核对（JUnit XML 精确计数 + 日志内容；退出码 = 矩阵与预期一致性）"
plain .venv/bin/python "$AUDIT_DIR/verify_matrix.py" "$EV"
