"""verify_matrix v2：在 v1 基础上把 index.txt 退出码纳入自动判定（review.md N-4）。

出处与边界（2026-09-17 追加，append-only）：本文件是 20260916-m4-review 复核关闭后的
补充实现，**不属于本轮 run_matrix.sh 的被复核产物**（v1 脚本与 evidence 运行输出保持
复核时点冻结哈希，见 review.md §6 / 发现 N-4）。供后续里程碑复核矩阵直接采用；
届时按当轮块清单修订下方三个期望字典即可。

相对 v1（verify_matrix.py）新增：
- 解析 ``<EV>/index.txt`` 中由 run_matrix.sh `run()`/`gate()` 留痕的 ``<块> exit=<n>`` 行；
- 每块退出码必须与 EXPECTED_EXITS 精确一致（含设计内失败块 i19-acceptance-historical=1）；
- index.txt 不得出现期望之外的块，期望块不得缺失——「日志命中但进程异常退出」「块被
  静默增删」均判 MISS；
- 其余核对（JUnit XML 计数、失败节点白名单、日志内容命中、守卫自检 JSON 结构）与 v1 一致。

退出码语义：0 = 计数/内容/自检/退出码全部与预期一致；1 = 存在 MISS。
**退出码不构成 M4 裁决**，仅表示「矩阵与预期一致」。

运行（仓库根目录）::

    .venv/bin/python -B .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260916-m4-review/verify_matrix_v2.py [evidence_dir]

产出：``<EV>/matrix-summary-v2.json``（机器可读；文件名区别于 v1 的 matrix-summary.json，不覆盖）。
"""
from __future__ import annotations

import json
import re
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

AUDIT = Path(__file__).resolve().parent
EV = Path(sys.argv[1]) if len(sys.argv) > 1 else AUDIT / "evidence"
OUT = EV / "matrix-summary-v2.json"

HASH_R1 = "d474bd6d566e8cf5d72d0531de55fe918833ec49185f0b31322f97d603f85957"
HASH_R2 = "3d27a690519cb006b319da6fbc59dac2e81199b77b2b650983f700ea2f1f71e2"
HASH_R3 = "f22525c3957f8d09890600eb1df7e3cab3a6fce61f79b196c6067cbd9f39dd59"
HISTORICAL_FAILING = "test_acceptance_freeze_does_not_omit_latest_known_chain_tests"

# 每块预期退出码（run_matrix.sh index.txt 留痕；i19 历史探针设计内 exit=1）。
EXPECTED_EXITS: dict[str, int] = {
    "freeze-validator": 0,
    "freeze-hashes": 0,
    "freeze-r1-trusted-cmp": 0,
    "guard-selfcheck": 0,
    "chain-contracts-full-review": 0,
    "i19-acceptance-historical": 1,
    "legacy-probes": 0,
    "boundary-contracts-r1-r5": 0,
    "business-11-files-guard-env": 0,
    "guard-tests-normal-env": 0,
    "pyright-i1-scope": 0,
    "ruff-check": 0,
    "ruff-format-check": 0,
    "import-smoke-stage1": 0,
    "postflight-freeze-revalidate": 0,
    "postflight-lib-versions": 0,
}

# pytest 块：JUnit XML 计数精确核对（errors/skipped 一律必须为 0）
PYTEST_EXPECT: dict[str, dict] = {
    "chain-contracts-full-review": {"tests": 11, "failures": 0},
    "i19-acceptance-historical": {
        "tests": 3, "failures": 1, "failing": [HISTORICAL_FAILING],
    },
    "legacy-probes": {"tests": 31, "failures": 0},
    "boundary-contracts-r1-r5": {"tests": 9, "failures": 0},
    "business-11-files-guard-env": {"tests": 186, "failures": 0},
    "guard-tests-normal-env": {"tests": 19, "failures": 0},
}
# 日志块：内容全部命中（退出码由 EXPECTED_EXITS 单独核对）
LOG_EXPECT: dict[str, list[str]] = {
    "freeze-validator": ["freeze chain verified"],
    "freeze-hashes": [HASH_R1, HASH_R2, HASH_R3],
    "freeze-r1-trusted-cmp": ["byte-identical"],
    "pyright-i1-scope": ["0 errors"],
    "ruff-check": ["All checks passed"],
    "ruff-format-check": ["already formatted"],
    "import-smoke-stage1": ["354/354"],
    "postflight-freeze-revalidate": ["freeze chain verified"],
    "postflight-lib-versions": ["pymupdf", "python-docx"],
}

results: dict[str, dict] = {}


def record(name: str, ok: bool, detail: str) -> None:
    results[name] = {"ok": ok, "detail": detail}
    print(f"  [{'ok' if ok else 'MISS'}] {name}: {detail}")


# ---- N-4 新增：index.txt 退出码自动核对 ------------------------------------
index_path = EV / "index.txt"
recorded: dict[str, int] = {}
if index_path.is_file():
    for line in index_path.read_text(encoding="utf-8", errors="replace").splitlines():
        matched = re.fullmatch(r"(\S+) exit=(\d+)", line.strip())
        if matched:
            recorded[matched.group(1)] = int(matched.group(2))
else:
    record("index-exit-codes", False, "缺少 index.txt（无法核对退出码）")

for name, expected in EXPECTED_EXITS.items():
    actual = recorded.get(name)
    record(
        f"exit:{name}",
        actual == expected,
        f"expected={expected} actual={actual}" if actual is not None else "index.txt 缺该块",
    )
unexpected = sorted(set(recorded) - set(EXPECTED_EXITS))
record(
    "index-unexpected-blocks",
    not unexpected,
    "无未预期块" if not unexpected else f"index.txt 出现期望之外的块: {unexpected}",
)
# ---------------------------------------------------------------------------

for name, exp in PYTEST_EXPECT.items():
    xml_path = EV / f"{name}.xml"
    if not xml_path.is_file():
        record(name, False, "缺少 JUnit XML（块未运行或崩溃）")
        continue
    try:
        root = ET.parse(xml_path).getroot()
    except ET.ParseError as exc:
        record(name, False, f"XML 解析失败: {exc}")
        continue
    suite = root if root.tag == "testsuite" else root.find(".//testsuite")
    if suite is None:
        record(name, False, "XML 无 testsuite 节点")
        continue
    actual = {key: int(suite.get(key, "0")) for key in ("tests", "errors", "failures", "skipped")}
    failed_ids = [tc.get("name") for tc in suite.iter("testcase") if tc.find("failure") is not None]
    detail = (
        f"tests={actual['tests']} failures={actual['failures']} "
        f"errors={actual['errors']} skipped={actual['skipped']}"
    )
    ok = (
        actual["tests"] == exp["tests"]
        and actual["failures"] == exp["failures"]
        and actual["errors"] == 0
        and actual["skipped"] == 0
    )
    if "failing" in exp:
        ok = ok and failed_ids == exp["failing"]
        detail += f" failing={failed_ids}"
    record(name, ok, detail)

for name, needles in LOG_EXPECT.items():
    log_path = EV / f"{name}.log"
    if not log_path.is_file():
        record(name, False, "缺少日志")
        continue
    text = log_path.read_text(encoding="utf-8", errors="replace")
    missing = [needle for needle in needles if needle not in text]
    record(name, not missing, "内容全部命中" if not missing else f"缺失: {missing}")

sc_path = EV / "guard-selfcheck.json"
try:
    report = json.loads(sc_path.read_text(encoding="utf-8"))
    cases = report.get("cases", [])
    case_ok = [bool(case.get("passed")) for case in cases]
    ok = report.get("passed") is True and len(cases) == 24 and all(case_ok)
    record("guard-selfcheck", ok,
           f"passed={report.get('passed')} cases={len(cases)} case_passed={sum(case_ok)}")
except (OSError, ValueError) as exc:
    record("guard-selfcheck", False, f"自检 JSON 不可读: {exc}")

all_ok = all(item["ok"] for item in results.values())
summary = {
    "expectation": "matrix matches expected results incl. per-block exit codes; NOT an M4 verdict",
    "version": 2,
    "all_ok": all_ok,
    "blocks": results,
}
OUT.write_text(
    json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"汇总: {'全部预期命中（含退出码）' if all_ok else '存在 MISS（发现候选，人工核对原始证据）'}")
print("脚本退出码仅表示矩阵与预期一致，不构成 M4 裁决。")
sys.exit(0 if all_ok else 1)
