"""M7 复核 G2 回归：旧 ingest 写入口停用后必须 fail-closed 拒绝。

I4-5 已批准停用旧写入口，但原 ``run_ingest`` 先写旧 ``ingest_runs`` 台账再入库，
入库失败（exit 2）路径也执行 INSERT/UPDATE/COMMIT——停用未落实到入口。
验收口径（M7 复核 G2）：**失败路径也不能写旧表**——拒绝必须发生在任何数据库
连接 / DDL / advisory lock / 台账写入之前（零连接，故零旧表写入）。
"""

from __future__ import annotations

import json
import inspect

import pytest

from plugins.corpus.service import CorpusService, RetiredEvidenceWriteError, RetiredIngestError


@pytest.fixture()
def _forbid_psycopg_connect(monkeypatch: pytest.MonkeyPatch) -> None:
    """任何 ``psycopg.connect`` 调用即失败：证明拒绝发生在连接之前（零连接）。"""
    import psycopg

    def _boom(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("psycopg.connect 被调用——停用入口不得建立任何数据库连接")

    monkeypatch.setattr(psycopg, "connect", _boom)


def test_run_ingest_rejected_without_any_connection(
    _forbid_psycopg_connect: None,
) -> None:
    """编程调用 run_ingest：恒定 RetiredIngestError，且零数据库连接（零旧表写入）。"""
    svc = CorpusService("postgresql://forbidden:forbidden@127.0.0.1:1/nowhere")
    with pytest.raises(RetiredIngestError, match="旧 ingest 写入口已停用"):
        svc.run_ingest("data/corpus")


def test_cli_ingest_subcommand_structured_rejection(
    _forbid_psycopg_connect: None,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """CLI ``ingest`` 子命令：结构化 JSON 拒绝 + exit 2，不构造任何数据库连接。"""
    from plugins.corpus.service import _main

    monkeypatch.setattr("sys.argv", ["corpus-service", "ingest"])
    assert _main() == 2
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is False
    assert payload["status"] == "rejected"
    assert payload["reason"] == "retired_ingest_entry"


def test_evidence_write_rejected_without_any_connection(
    _forbid_psycopg_connect: None,
) -> None:
    """I4-5 登记的旧 evidence 写入口同样不能绕过停用门。"""
    svc = CorpusService("postgresql://forbidden:forbidden@127.0.0.1:1/nowhere")
    with pytest.raises(RetiredEvidenceWriteError, match="旧 evidence 写入口已停用"):
        svc.save_evidence_run(object())  # type: ignore[arg-type]


def test_extract_claims_does_not_request_retired_persistence_by_default() -> None:
    """正常 extraction 默认只返回内存 EvidenceRun，不能隐式写旧表。"""
    assert inspect.signature(CorpusService.extract_claims).parameters["persist"].default is False
