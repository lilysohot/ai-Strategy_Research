# M5 交叉核验清单（reviewer 独立复算，不采信申请方数字）

执行前提：仓库根目录；`export CORPUS_I2_DSN=...`；**只读**，不改任何文件（除 reviewer 自己的报告与
`evidence/` 内产物）。每条记录「命令 + 实际输出 + 判定」。发现问题按 README §8 模板登记。

## X1 快照哈希与血缘逐级复算

```bash
sha256sum .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i0c-r1{1,2,3,4,5}.json
python .scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/validate_i0c_freeze.py
```
预期：r15/r14/r13/r12/r11 与 README §2 及 `evidence/freeze-hashes.log` 一致；
验证器打印 `i0c freeze chain verified … lineage i0c-r15->…->i0a5(M1) ok` 且 exit 0。
若哈希不一致 → 立即停止（快照被改动），按 P1 记录。

## X2 绑定面逐文件复算 + 漏绑核查

```bash
python - <<'PY'
import hashlib, json
from pathlib import Path
root = Path(".")
snap = json.loads(Path(".scratch/corpus-evidence-pipeline/ingestion-rebuild/freezes/i0c-r15.json").read_text())
bad = []
for group, items in snap["binding"].items():
    for rel, expected in items.items():
        actual = hashlib.sha256((root / rel).read_bytes()).hexdigest()
        if actual != expected:
            bad.append((group, rel, expected[:12], actual[:12]))
print("bindings:", {g: len(v) for g, v in snap["binding"].items()})
print("MISMATCH:", bad or "none")
PY
```
预期：`implementation=5, tests=1, docs=3, review_evidence=3, freeze_validator=1, freeze_generator=1`，
`MISMATCH: none`。
**漏绑核查（人工）**：r15 的改动面为 `gaps.py`（新增）、`clean.py`、`engine.py`、`read_pg.py`、
`cli.py`（实现）、`tests/test_corpus_gap_dispositions.py`（新增回归）、三份计划文档与复核证据三件；
reviewer 应把 r15 绑定清单与 `git status`/文件 mtime 对照，若发现还动过别的实现/测试而未被
更早修订（r11—r14）绑定，记为漏绑并追查。**特别注意**：r15 未绑定 `plugins/tools/*` 与
`service.py`——若这两处在本轮实际被改动，即为漏绑。

## X3 用例数与 JUnit 计数一致（防"少收集掩盖失败"）

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" CORPUS_I2_DSN="$CORPUS_I2_DSN" \
  .venv/bin/python -B -m pytest --noconftest -c /dev/null -p no:cacheprovider \
  --collect-only -q tests/test_corpus_preparation_publication_pg.py tests/test_corpus_preparation_repository_pg.py \
  tests/test_corpus_authority_pg.py tests/test_corpus_cli_isolation.py tests/test_corpus_consumers_pg.py \
  tests/test_corpus_cli_pg.py .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-8-i2-4-review/test_review_probes.py \
  .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-i2-fullchain-review/test_fullchain_probes.py \
  tests/test_corpus_gap_dispositions.py \
  | tail -3
```
预期：收集数 = 17+18+8+5+19+4+6+12+13 = **102**，与 `evidence/*.xml` 的 tests 之和一致。
`i1-business-guard-env` 块预期 188、`guard-tests-normal-env` 预期 19（各自 `--collect-only` 复核）。

## X4 守卫对抗探针（否决面）

```bash
# 留出读取 / 未清单来源 / 受保护写入 / 模型 import / 非允许网络 / 非 Python 子进程
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" \
  CORPUS_GUARD_PHASE=i2-verify CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json \
  .venv/bin/python -c "
from plugins.corpus.preparation import guard
guard.install('.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json')
import pathlib
for target in ['data/corpus/2026-08-12_2026.08.12-国泰海通-国内研报-国泰海通证券-ipo专题-新股精要-国内领先的电子材料和化工新材料生产企业贝特利-2594e01d.pdf']:
    try:
        pathlib.Path(target).read_bytes(); print('NOT_REFUSED', target)
    except Exception as exc:
        print('REFUSED', type(exc).__name__, str(exc)[:60])
"
```
预期：`REFUSED`（3 份留出在 `forbidden_roots`，读取被拒）。
另跑守卫自检（`guard --config … --selfcheck`）覆盖模型 import/网络/非 Python 子进程：24/24。
`guard-selfcheck.json` 的 `cases` 须逐项 `passed=true`（reviewer 抽查其中至少 3 项）。

## X5 write-once 拒绝路径（装置不可被覆盖）

```bash
# ① 重跑冻结生成器（i0c-r15 已存在）→ 必须拒绝且非零退出
.venv/bin/python .scratch/corpus-evidence-pipeline/ingestion-rebuild/i2_fullchain_remediation_freeze.py; echo "exit=$?"
# ② 矩阵 evidence 已存在时重跑 run_matrix.sh → exit 2
bash .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/run_matrix.sh; echo "exit=$?"
```
预期：① `I0C-R15 FREEZE FAILED: i0c-r15 已存在（write-once）`，exit 1；② 第二次运行 `拒绝：evidence 目录已存在`，exit 2。
（② 须在正式矩阵落盘后执行；不得用 `M5_REVIEW_EVIDENCE_DIR` 覆盖默认 evidence 目录来"重跑"。）

## X6 legacy / 无 schema 双向 fail-closed（"旧来源路径不能兜底"）

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" CORPUS_I2_DSN="$CORPUS_I2_DSN" \
  CORPUS_READ_CHAIN=legacy .venv/bin/python -c "
from plugins.corpus.service import CorpusService
import os
try:
    CorpusService(os.environ['CORPUS_I2_DSN']).read_chain(); print('NOT_REFUSED')
except Exception as exc:
    print('REFUSED', type(exc).__name__, str(exc)[:70])
"
```
预期：`REFUSED StoreError 拒绝：目标库已承载新链（corpus schema），legacy 读路径不可达…`。
反向（无 schema 库请求 `new`）：把 DSN 换成同一容器的 `postgres` 库（无 corpus schema）→ 同样 `REFUSED`。
对应正式用例：`tests/test_corpus_consumers_pg.py::test_read_chain_legacy_refused_on_migrated_target`、
`::test_read_chain_new_refused_without_corpus_schema`。

## X7 同快照不变量（并发发布下 coverage 与命中不拼接）

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" CORPUS_I2_DSN="$CORPUS_I2_DSN" \
  .venv/bin/python -B -m pytest --noconftest -c /dev/null -p no:cacheprovider \
  tests/test_corpus_consumers_pg.py::test_search_and_coverage_share_one_snapshot_under_concurrent_publish -q
```
预期：`1 passed`。该用例在另一线程反复 publish/retire 的同时循环 40 次
`search_with_coverage`，断言 `hits 非空 ⇒ coverage.counts.published ≥ 1`（若命中与覆盖来自不同时刻必偶发失败）。

## X8 零模型（子进程真实验证，非声明）

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" \
  CORPUS_GUARD_PHASE=i2-verify CORPUS_GUARD_CONFIG=.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json \
  .venv/bin/python -c "
from plugins.corpus.preparation import guard
guard.install('.scratch/corpus-evidence-pipeline/ingestion-rebuild/guards/i2-verify.json')
import subprocess, sys
r = subprocess.run([sys.executable, '-c', 'import openai'], capture_output=True, text=True)
print('child rc=', r.returncode)
print('contains openai:', 'openai' in (r.stdout + r.stderr))
"
```
预期：`child rc= 1`（非零）且 `contains openai: True`——**父进程已装守卫时子进程同样被拒**。
等价正式用例：`tests/test_corpus_cli_isolation.py::test_subprocess_model_client_import_refused`。

## X9 目标 fail-closed（拒绝非演练库）

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" \
  .venv/bin/python -c "
from plugins.corpus.cli import main
print('exit=', main(['status', '--build', '0'*64, '--dsn', 'postgresql://postgres:***@127.0.0.1:543/postgres']))
"
```
预期：输出 JSON 含 `"error": "拒绝：current_database='postgres' ≠ 'i2_sandbox_corpus'"`，`exit= 3`。
注意：**不得**把 DSN 指向 `127.0.0.1:5432`（生产库）；本项仅用同一隔离容器的非演练库构造反证。

## X10 装置自证（核对脚本有区分力）

```bash
python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/verify_matrix.py \
  --self-test <evidence-dir>
```
预期：`SELFTEST_OK`（篡改副本被判 ≥2 项 MISS）。若打印 `SELFTEST FAILED`，说明核对脚本无区分力，
本次矩阵结论不可用（P1）。

## X11 缺口裁决不可绕过（"未知/畸形缺口不得被放行"）

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" .venv/bin/python -c "
from plugins.corpus.preparation.gaps import gap_records, blocking_gaps, parse_gap_key
for key in ('issue:empty_page', 'issue:empty_page:page:4:extra', 'issue:not_in_vocabulary:page:1', 'issue::page:1'):
    recs = gap_records([key])
    print(repr(key), '->', recs[0].code, recs[0].disposition.value, 'blocking=', bool(blocking_gaps(recs)))
print('parse issue:empty_page ->', parse_gap_key('issue:empty_page'))
"
```
预期：四行中只有 `issue:empty_page:page:4:extra`（location 合法）为 `empty_page / acknowledged`；
其余（缺 location / 词表外码 / 空码）必须 `blocking=True`。
若任一畸形键被放行 → P1（缺口"看不见"比误阻断更危险）。

## X12 无 scope 时缺口不得被判 `out_of_scope`

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" .venv/bin/python -c "
from plugins.corpus.preparation.gaps import gap_key, gap_records, evaluate_against_scope
keys = [gap_key('image_only_page', 'page:3'), gap_key('unreadable_element', 'body[5]:tbl[0]/row[0]/cell[1]')]
print('no-scope:', [r.lifecycle.value for r in evaluate_against_scope(gap_records(keys), ())])
print('scoped-pdf:', [r.lifecycle.value for r in evaluate_against_scope(gap_records(keys), ((0, 200),))])
print('char-outside:', [r.lifecycle.value for r in evaluate_against_scope(gap_records([gap_key('unterminated_code_fence', 'char:600-')]), ((0, 200),))])
"
```
预期：`no-scope` 与 `scoped-pdf` 两行均为 `['blocking','blocking']`（页/元素坐标不构成 `char:` 区间，
不得因 scope 存在而被判范围外）；`char-outside` 行为 `['out_of_scope']`。
若页/元素坐标在 scope 下被判范围外 → P1（等于用 scope 绕过 blocking 缺口）。

## X13 活动 build 有缺口 ⇒ coverage 必为 `scoped`

在演练库上发布一份含 `empty_page` 的 PDF 后：
```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" CORPUS_I2_DSN="$CORPUS_I2_DSN" .venv/bin/python -c "
from plugins.corpus.preparation import read_pg
import os
cov = read_pg.coverage_snapshot(os.environ['CORPUS_I2_DSN'], sandbox_db='i2_sandbox_corpus', query_status='matched')
print(cov['processing'], cov['reason_codes'], cov['counts']['published_with_gaps'])
"
```
预期：`scoped ('gap_regions_present',) 1`（缺口即"剩余范围"的机读形式，由 `check`/`status` 的 `gaps` 返回）。
反向：缺口台账为空的活动 build 不得因缺口因素降级（正式用例 `test_chain_hits_and_coverage_share_one_snapshot`）。
最省事的复现方式：直接跑 `tests/test_corpus_gap_dispositions.py::TestI2GapCli::test_acknowledged_gap_publishes_and_coverage_is_scoped`。

## X14 `check` 的缺口计数与发布门判决同源

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" CORPUS_I2_DSN="$CORPUS_I2_DSN" \
  .venv/bin/python -m pytest --noconftest -c /dev/null -p no:cacheprovider -q \
  tests/test_corpus_gap_dispositions.py::TestI2GapCli::test_check_and_status_expose_structured_gaps \
  tests/test_corpus_gap_dispositions.py::TestI2GapCli::test_plan_precheck_shares_the_same_verdict
```
预期：`2 passed`。判据：`check` 被拒 ⇔ `gap_summary.blocking ≥ 1`；`plan` 预检的阻断键集合与
`check` 的 `gaps` 键集合逐项相等（同一实现 `engine.gap_records_of`，不得各算一套）。
若预检比 `check` 更宽（预检说可发布、check 拒绝）→ P1。

## X15 文档级拼接语义（单元级逐字 ≠ 字节还原）

```bash
env -i PATH=/usr/bin:/bin LANG=C.UTF-8 PYTHONPATH="$PWD" CORPUS_I2_DSN="$CORPUS_I2_DSN" \
  .venv/bin/python -m pytest --noconftest -c /dev/null -p no:cacheprovider -q \
  tests/test_corpus_gap_dispositions.py::TestI2GapCli::test_document_text_is_unit_join_not_byte_restore
```
预期：`1 passed`。`fetch_document().text` 不等于源文件字节、不含源文件的空行分隔，
但每一非空行都逐字出自源文件——即架构 §7.2（RM-FC-5）声明的语义。

## 记录要求

每条填写：命令（原样）、实际输出关键行、判定（符合预期 / 偏离）。偏离项一律进入
`review.md` 的发现表（README §8），并给出最小复现；**不得修改预期或 evidence 原始输出**。
