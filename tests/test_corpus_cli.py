"""I2-4 语料 CLI 参数与退出码（不需要 PG）。

覆盖：恰好退出码（0/2/3）、``publish`` 必须给操作者（argparse 拒绝即 exit 2）、
未声明目标库时 fail-closed 拒绝（exit 3）。真库往返见 ``test_corpus_cli_pg.py``。
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from plugins.corpus import cli

FIXTURE = (
    Path(__file__).resolve().parent / "fixtures/corpus_preparation/synthetic-company-report.md"
)


def _write_manifest(tmp_path: Path, payload: object) -> Path:
    path = tmp_path / "plan.json"
    path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    return path


def test_plan_valid_manifest_exit_0(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    manifest = _write_manifest(
        tmp_path,
        {
            "sources": [
                {
                    "path": str(FIXTURE),
                    "domain_hint": "company",
                    "review_decision_ids": ["r1"],
                }
            ]
        },
    )
    assert cli.main(["plan", "--manifest", str(manifest)]) == cli.EXIT_OK
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["count"] == 1
    assert payload["entries"][0]["format"] == "markdown"
    assert payload["entries"][0]["review_decision_ids"] == ["r1"]


def test_plan_missing_source_exit_2(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, {"sources": [{"path": str(tmp_path / "absent.md")}]})
    assert cli.main(["plan", "--manifest", str(manifest)]) == cli.EXIT_INPUT


def test_plan_empty_manifest_exit_2(tmp_path: Path) -> None:
    manifest = _write_manifest(tmp_path, {"sources": []})
    assert cli.main(["plan", "--manifest", str(manifest)]) == cli.EXIT_INPUT


def test_plan_bad_domain_exit_2(tmp_path: Path) -> None:
    manifest = _write_manifest(
        tmp_path, {"sources": [{"path": str(FIXTURE), "domain_hint": "not-a-domain"}]}
    )
    assert cli.main(["plan", "--manifest", str(manifest)]) == cli.EXIT_INPUT


def test_plan_malformed_json_exit_2(tmp_path: Path) -> None:
    path = tmp_path / "broken.json"
    path.write_text("{not json", encoding="utf-8")
    assert cli.main(["plan", "--manifest", str(path)]) == cli.EXIT_INPUT


def test_publish_requires_operator_returns_exit_2() -> None:
    """RM-I28-11：argparse 缺必填参数由 main 归一为返回码 2（不再抛 SystemExit）。"""
    assert cli.main(["publish", "--build", "x"]) == cli.EXIT_INPUT


def test_unknown_argument_value_returns_exit_2() -> None:
    assert cli.main(["plan", "--manifest", "/nonexistent/manifest.json"]) == cli.EXIT_INPUT
    assert cli.main(["plan"]) == cli.EXIT_INPUT  # 缺 --manifest


@pytest.mark.parametrize("command", [["check", "--build", "x"], ["status", "--build", "x"]])
def test_no_target_declared_refused_exit_3(
    command: list[str], monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("CORPUS_I2_DSN", raising=False)
    assert cli.main(command) == cli.EXIT_TARGET


def test_rebuild_plan_missing_build_requires_target(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv("CORPUS_I2_DSN", raising=False)
    assert cli.main(["rebuild-plan", "--build", "x"]) == cli.EXIT_TARGET
