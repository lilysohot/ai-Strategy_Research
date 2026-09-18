"""M5 复核矩阵汇总核对（按 JUnit XML 精确计数 + 日志内容 + 退出码逐块自动判定）。

用法::

    python .scratch/corpus-evidence-pipeline/ingestion-rebuild/audits/20260918-m5-review/verify_matrix.py <evidence-dir>
    python .../verify_matrix.py --self-test <evidence-dir>   # 篡改副本必须被判 MISS（装置自证）

语义：退出码 0 = 矩阵与预期一致；1 = 存在 MISS；2 = 装置/证据不可读。
**退出码只表示「矩阵与预期一致」，不构成 M5 裁决**（见 README §9）。
不使用 assert（不依赖可被 -O 剥离的断言）。
"""

from __future__ import annotations

import json
import re
import shutil
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

#: 块 → 预期：exit 码；junit=(tests, failures, errors, skipped)；log=必须命中的子串；
#: log_regex=必须命中的正则（对模块计数等「随新增模块增长」的量，判据是闭合性而非固定数字）；
#: selfcheck=（JSON 文件, 最少 case 数, 期望 passed 值）
EXPECT: dict[str, dict[str, object]] = {
    "freeze-validator": {"exit": 0, "log": ("i0c freeze chain verified",)},
    "freeze-hashes": {"exit": 0, "log": ("i0c-r15.json", "i0c-r13.json", "i2-verify.json")},
    "target-guard": {"exit": 0, "log": ("TARGET_OK i2_sandbox_corpus",)},
    "guard-selfcheck": {"exit": 0, "selfcheck": ("guard-selfcheck.json", 24, True)},
    "publication-pg": {"exit": 0, "junit": (17, 0, 0, 0)},
    "repository-pg": {"exit": 0, "junit": (18, 0, 0, 0)},
    "authority-pg": {"exit": 0, "junit": (8, 0, 0, 0)},
    "cli-isolation": {"exit": 0, "junit": (5, 0, 0, 0)},
    "consumers-pg": {"exit": 0, "junit": (19, 0, 0, 0)},
    "cli-pg": {"exit": 0, "junit": (4, 0, 0, 0)},
    "i28-i24-probes": {"exit": 0, "junit": (6, 0, 0, 0)},
    "i2-fullchain-probes": {"exit": 0, "junit": (12, 0, 0, 0)},
    "i2-gap-dispositions": {"exit": 0, "junit": (13, 0, 0, 0)},
    "i1-business-guard-env": {"exit": 0, "junit": (188, 0, 0, 0)},
    "guard-tests-normal-env": {"exit": 0, "junit": (19, 0, 0, 0)},
    "ruff-check": {"exit": 0, "log": ("All checks passed",)},
    "ruff-format-check": {"exit": 0, "log": ("already formatted",)},
    "pyright-i2-scope": {"exit": 0, "log": ("0 errors",)},
    # 判据是「导入闭合」（分子=分母），不是固定数字：新增模块（gaps.py 等）会使 N 增长，
    # 那不是回归；固定数字只会逼迫复核人改预期凑结果。i0c-r15 时点为 359/359。
    "import-smoke-stage1": {"exit": 0, "log_regex": (r"\b([0-9]+)/\1 modules imported\b",)},
    "postflight-freeze-revalidate": {"exit": 0, "log": ("i0c freeze chain verified",)},
}

errors: list[str] = []
misses: list[str] = []


def check(condition: bool, message: str) -> None:
    if not condition:
        errors.append(message)


def load_index(evidence: Path) -> dict[str, int]:
    index = evidence / "index.txt"
    if not index.is_file():
        check(False, f"缺少 index.txt: {index}")
        return {}
    codes: dict[str, int] = {}
    for line in index.read_text(encoding="utf-8").splitlines():
        parts = line.rsplit(" exit=", 1)
        if len(parts) != 2:
            continue
        block, raw = parts[0].strip(), parts[1].strip()
        try:
            codes[block] = int(raw)
        except ValueError:
            check(False, f"index.txt 退出码不可解析: {line!r}")
    return codes


def junit_counts(path: Path) -> tuple[int, int, int, int] | None:
    if not path.is_file():
        return None
    try:
        root = ET.parse(path).getroot()
    except ET.ParseError as exc:
        check(False, f"JUnit XML 不可解析 {path.name}: {exc}")
        return None
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        check(False, f"JUnit XML 无 testsuite: {path.name}")
        return None
    return (
        int(suite.get("tests", 0)),
        int(suite.get("failures", 0)),
        int(suite.get("errors", 0)),
        int(suite.get("skipped", 0)),
    )


def verify(evidence: Path, *, strict_index: bool = True) -> dict[str, object]:
    codes = load_index(evidence)
    results: dict[str, dict[str, object]] = {}
    for block, spec in EXPECT.items():
        entry: dict[str, object] = {}
        if block not in codes:
            check(False, f"{block}: index.txt 缺该块（未执行或提前中断）")
            misses.append(block)
            continue
        if codes[block] != spec["exit"]:
            misses.append(f"{block}: exit={codes[block]} 期望 {spec['exit']}")
        entry["exit"] = codes[block]

        if "junit" in spec:
            counts = junit_counts(evidence / f"{block}.xml")
            entry["junit"] = counts
            if counts is None:
                misses.append(f"{block}: 缺 JUnit XML")
            elif counts != spec["junit"]:
                misses.append(f"{block}: junit={counts} 期望 {spec['junit']}")
        if "log" in spec:
            log = evidence / f"{block}.log"
            text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
            for needle in spec["log"]:  # type: ignore[union-attr]
                if needle not in text:
                    misses.append(f"{block}: 日志未命中 {needle!r}")
        if "log_regex" in spec:
            log = evidence / f"{block}.log"
            text = log.read_text(encoding="utf-8", errors="replace") if log.is_file() else ""
            for pattern in spec["log_regex"]:  # type: ignore[union-attr]
                if re.search(pattern, text) is None:
                    misses.append(f"{block}: 日志未命中正则 {pattern!r}")
        if "selfcheck" in spec:
            name, min_cases, want_passed = spec["selfcheck"]  # type: ignore[misc]
            report_path = evidence / name
            if not report_path.is_file():
                misses.append(f"{block}: 缺 {name}")
            else:
                report = json.loads(report_path.read_text(encoding="utf-8"))
                cases = report.get("cases") or []
                entry["selfcheck"] = {"passed": report.get("passed"), "cases": len(cases)}
                if report.get("passed") is not want_passed:
                    misses.append(f"{block}: passed={report.get('passed')} 期望 {want_passed}")
                if len(cases) < min_cases:
                    misses.append(f"{block}: cases={len(cases)} < {min_cases}")
        results[block] = entry

    if strict_index:
        extra = sorted(set(codes) - set(EXPECT))
        if extra:
            misses.append(f"index.txt 含未登记块: {extra}")
    return {"blocks": results, "misses": misses, "errors": errors}


def _write_summary(evidence: Path, payload: dict[str, object]) -> None:
    target = evidence / "matrix-summary.json"
    target.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def self_test(evidence: Path) -> int:
    """装置自证：篡改副本必须被判 MISS（否则核对脚本没有区分力）。"""
    with tempfile.TemporaryDirectory() as tmp:
        copy = Path(tmp) / "evidence"
        shutil.copytree(evidence, copy)
        # 篡改 1：把 cli-isolation 的 JUnit 计数改错
        xml_path = copy / "cli-isolation.xml"
        if xml_path.is_file():
            text = xml_path.read_text(encoding="utf-8")
            xml_path.write_text(text.replace('tests="5"', 'tests="4"', 1), encoding="utf-8")
        # 篡改 2：伪造一个退出码（authority-pg 标成 1）
        index = copy / "index.txt"
        text = index.read_text(encoding="utf-8").replace("authority-pg exit=0", "authority-pg exit=1")
        index.write_text(text, encoding="utf-8")
        result = verify(copy)
    if not result["misses"]:
        print("SELFTEST FAILED: 篡改副本未被判 MISS（核对脚本无区分力）")
        return 2
    print(f"SELFTEST_OK: 篡改副本被判 {len(result['misses'])} 项 MISS")
    for item in result["misses"]:
        print(f"  - {item}")
    return 0


def main(argv: list[str]) -> int:
    if len(argv) < 2:
        print(__doc__)
        return 2
    if argv[1] == "--self-test":
        if len(argv) < 3:
            print("--self-test 需要 evidence 目录")
            return 2
        return self_test(Path(argv[2]))
    evidence = Path(argv[1])
    if not evidence.is_dir():
        print(f"证据目录不存在: {evidence}")
        return 2
    result = verify(evidence)
    _write_summary(evidence, result)
    for block, entry in result["blocks"].items():
        print(f"{block}: {json.dumps(entry, ensure_ascii=False)}")
    if result["errors"]:
        print("ERRORS:")
        for message in result["errors"]:
            print(f"  - {message}")
        return 2
    if result["misses"]:
        print(f"MISS {len(result['misses'])} 项（矩阵与预期不一致；不得改预期凑结果）:")
        for message in result["misses"]:
            print(f"  - {message}")
        return 1
    print(f"MATRIX OK: {len(result['blocks'])} 块全部与预期一致（不构成 M5 裁决）")
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
