"""Precisely verify run_matrix.sh evidence: JUnit XML counts, log contents, selfcheck JSON.

退出码语义：0 = 矩阵与预期一致；1 = 存在 MISS。
**退出码不构成 M4 裁决**，仅表示「矩阵与预期一致」；M4 裁决由独立复核人 + U 作出。

产出：``<evidence>/matrix-summary.json``（机器可读，含每块 expected/actual/ok）。

pytest 块按 JUnit XML 精确核对 tests/failures/errors/skipped 计数，
i19 历史探针块额外要求失败节点白名单精确匹配；日志块要求内容全部命中；
守卫自检按 JSON 结构核对（passed=true 且 24 项 case 全部通过）。
"""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

AUDIT = Path(__file__).resolve().parent
EV = Path(sys.argv[1]) if len(sys.argv) > 1 else AUDIT / "evidence"

HASH_R1 = "d474bd6d566e8cf5d72d0531de55fe918833ec49185f0b31322f97d603f85957"
HASH_R2 = "3d27a690519cb006b319da6fbc59dac2e81199b77b2b650983f700ea2f1f71e2"
HASH_R3 = "f22525c3957f8d09890600eb1df7e3cab3a6fce61f79b196c6067cbd9f39dd59"
HISTORICAL_FAILING = "test_acceptance_freeze_does_not_omit_latest_known_chain_tests"

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
# 日志块：exit 码由 index.txt 留痕，此处核对内容全部命中
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
    "expectation": "matrix matches expected results; NOT an M4 verdict",
    "all_ok": all_ok,
    "blocks": results,
}
(EV / "matrix-summary.json").write_text(
    json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
    encoding="utf-8",
)
print(f"汇总: {'全部预期命中' if all_ok else '存在 MISS（发现候选，人工核对原始证据）'}")
print("脚本退出码仅表示矩阵与预期一致，不构成 M4 裁决。")
sys.exit(0 if all_ok else 1)
