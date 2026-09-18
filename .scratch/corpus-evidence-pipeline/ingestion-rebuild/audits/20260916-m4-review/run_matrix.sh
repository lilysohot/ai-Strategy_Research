#!/usr/bin/env bash
# M4 独立复核命令矩阵（审计材料，只记录证据，不做判定）。
#
# 用法（仓库根目录）：
#   bash .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-m4-review/run_matrix.sh
#
# 执行模型：
#   前置门（冻结验证器 / 快照哈希 / r1 可信副本 / 守卫自检）任一失败 → 立即停止（exit 2）；
#   行为/静态块失败 → 继续收集证据；运行后重跑冻结验证器（绑定零漂移门，失败 exit 2）；
#   末尾 verify_matrix.py 按 JUnit XML 精确核对计数与失败节点，产出 matrix-summary.json。
# 脚本退出码：0 = 矩阵与预期一致；1 = 存在 MISS；2 = 前置门或运行后门失败。
# 退出码只表示「矩阵与预期一致」，不构成 M4 裁决。
# 结果 write-once 落 evidence/（已存在即拒绝）。
# M4_REVIEW_EVIDENCE_DIR 可重定向 evidence 目录（仅供申请方演练；正式复核必须用默认值）。
set -u

AUDIT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "$AUDIT_DIR/../../../../.." && pwd)"
EV="${M4_REVIEW_EVIDENCE_DIR:-$AUDIT_DIR/evidence}"

cd "$REPO_ROOT" || { echo "无法进入仓库根: $REPO_ROOT"; exit 2; }
if [ -e "$EV" ]; then
  echo "拒绝：evidence 目录已存在（write-once）: $EV"
  exit 2
fi
mkdir -p "$EV"

GUARD=".scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i1.json"
AUD=".scratch/corpus-evidence-pipeline/ingestion-rebuild/audits"
FREEZE=".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes"
TRUSTED="$AUD/20260916-i1-remediation/i1-r1-original.json"

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

# 守卫环境：env -i 零继承；守卫先于测试收集装载；禁用插件自动加载与 conftest
guard_pytest() {
  env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$REPO_ROOT" \
    PYTHONDONTWRITEBYTECODE=1 PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 \
    CORPUS_GUARD_PHASE=i1 CORPUS_GUARD_CONFIG="$GUARD" \
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

BUSINESS=(
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

: > "$EV/index.txt"
{
  echo "uname: $(uname -a)"
  echo "git HEAD: $(git rev-parse HEAD 2>/dev/null || echo n/a)"
  echo "python: $(.venv/bin/python -V 2>&1)"
  echo "node: $(node -v 2>/dev/null || echo missing)"
  echo "repo: $REPO_ROOT"
  sha256sum "$AUDIT_DIR/README.md" "$AUDIT_DIR/run_matrix.sh" "$AUDIT_DIR/verify_matrix.py"
} > "$EV/environment.txt" 2>&1

echo "== 前置门（任一失败立即停止，exit 2）"
gate freeze-validator .venv/bin/python "$FREEZE/validate_i1_freeze.py"
gate freeze-hashes sha256sum \
  "$FREEZE/i1-r1.json" "$FREEZE/i1-r2.json" "$FREEZE/i1-r3.json" \
  "$FREEZE/freeze-manifest.json" "$TRUSTED"
gate freeze-r1-trusted-cmp bash -c "cmp '$FREEZE/i1-r1.json' '$TRUSTED' && echo byte-identical"
gate guard-selfcheck plain .venv/bin/python -m plugins.corpus.preparation.guard \
  --config "$GUARD" --selfcheck --out "$EV/guard-selfcheck.json"

echo "== 行为矩阵（守卫 env / 受控普通 env；失败继续收集证据）"
run chain-contracts-full-review guard_pytest \
  "$AUD/20260916-i1-full-review/test_chain_contracts.py"
# 历史口径探针：test_acceptance_freeze_does_not_omit_latest_known_chain_tests
# 断言「r1 含最新 11 项链路测试」——该历史断言不适用于当前候选；r1 字节完整性由
# 上方 freeze-hashes + freeze-r1-trusted-cmp 门以精确哈希与逐字节比较证明，
# 本探针失败本身不证明完整性。预期恰失败该固定节点 1 次（1 failed）；若通过，
# 反而说明 r1 字节又被动过。当前候选完整性由 validate_i1_freeze.py 承担。
run i19-acceptance-historical guard_pytest \
  "$AUD/20260916-i1-9-retest/test_i1_9_acceptance.py"
run legacy-probes guard_pytest \
  "$AUD/20260916-i1/test_acceptance_probes.py" \
  "$AUD/20260916-i1-retest/test_remaining_boundaries.py"
run boundary-contracts-r1-r5 guard_pytest \
  "$AUD/20260916-i1-remediation-retest/test_remaining_contracts.py"
run business-11-files-guard-env guard_pytest "${BUSINESS[@]}"
run guard-tests-normal-env plain_pytest tests/test_corpus_preparation_guard.py

echo "== 静态检查（受控最小环境；失败继续收集证据）"
run pyright-i1-scope plain .venv/bin/python -m pyright plugins/corpus/preparation \
  tests/test_corpus_preparation_engine.py \
  tests/test_corpus_preparation_contract.py \
  tests/test_corpus_preparation_remediation.py \
  tests/test_corpus_preparation_counterexamples.py \
  tests/test_corpus_preparation_release_gate.py
run ruff-check plain .venv/bin/python -m ruff check plugins/corpus/preparation tests/test_corpus_preparation_*.py
run ruff-format-check plain .venv/bin/python -m ruff format --check plugins/corpus/preparation
run import-smoke-stage1 plain .venv/bin/python -B tools/import_smoke.py --stage 1

echo "== 运行后复核（绑定零漂移门失败即停；版本留痕）"
gate postflight-freeze-revalidate .venv/bin/python "$FREEZE/validate_i1_freeze.py"
sha256sum \
  "$FREEZE/validate_i1_freeze.py" "$AUDIT_DIR/run_matrix.sh" "$AUDIT_DIR/verify_matrix.py" \
  "$AUD/20260916-i1-full-review/test_chain_contracts.py" \
  "$AUD/20260916-i1-9-retest/test_i1_9_acceptance.py" \
  "$AUD/20260916-i1/test_acceptance_probes.py" \
  "$AUD/20260916-i1-retest/test_remaining_boundaries.py" \
  "$AUD/20260916-i1-remediation-retest/test_remaining_contracts.py" \
  uv.lock > "$EV/postflight-hashes.txt" 2>&1 || fail "运行后哈希留痕失败"
run postflight-lib-versions plain .venv/bin/python -c \
  "import importlib.metadata as m; [print(p, m.version(p)) for p in ('pymupdf', 'python-docx')]"

echo "== 汇总核对（JUnit XML 精确计数 + 日志内容；退出码 = 矩阵与预期一致性）"
plain .venv/bin/python "$AUDIT_DIR/verify_matrix.py" "$EV"
