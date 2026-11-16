"""07 候选：``collect_reports`` 回放里的检查清单压缩。

同一份未核验清单在一次运行中被追加四次，每次约 1,340 字符，其中大半是
模型无法使用的内部句柄（``binding_id``、``subject.sha256``）。开关默认关闭，
发布形态保持不变，直到对照实验决定。
"""

from __future__ import annotations

import copy
import json

import pytest

import plugins.tools._verification as verification
from plugins.tools._verification import render_verification_status


class _Bus:
    def list_task_jobs(self, _task_id: str) -> list[object]:
        return []


def _summary() -> dict[str, object]:
    long_criterion = "最终答案中引用的每个关键数字（GW 规模、年份、功率/质量/成本/单价/IRR 等）与绑定 evidence 的原文在数值、单位、口径、归属主体上一致，无夸大或跨版本外推"
    return {
        "status": "unchecked",
        "checks": [
            {
                "check_id": "figures_fidelity",
                "work_item_id": "t3",
                "criterion": long_criterion,
                "binding_id": "85e2cdec" + "0" * 56,
                "required": True,
                "factual_scope": True,
                "publication_excerpt": True,
                "verdict": "unchecked",
                "job_id": "39e1aec6c0fb.job.3",
                "verdict_job_id": "",
                "subject": {
                    "sha256": "e" * 64,
                    "key": "inline:" + "e" * 64,
                    "job_id": "39e1aec6c0fb.job.3",
                },
                "evidence": [{"key": "39e1aec6c0fb.job.1"}],
            }
        ],
        "basis": "version_bound_member_verdicts",
    }


@pytest.fixture()
def patched(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("VERIFICATION_STATUS_COMPACT", raising=False)
    monkeypatch.setattr(
        verification,
        "project_bus_checks",
        lambda bus, task_id: copy.deepcopy(_summary()),
    )


def test_default_shape_keeps_the_published_fields(patched: None) -> None:
    out = render_verification_status(_Bus(), "run", compact=False)

    assert "binding_id" in out
    assert "sha256" in out


def test_compact_drops_handles_but_keeps_state(patched: None) -> None:
    out = render_verification_status(_Bus(), "run", compact=True)

    assert "binding_id" not in out
    assert "sha256" not in out
    assert "figures_fidelity" in out
    assert "unchecked" in out
    assert "39e1aec6c0fb.job.1" in out


def test_compact_costs_materially_less(patched: None) -> None:
    full = render_verification_status(_Bus(), "run", compact=False)
    compact = render_verification_status(_Bus(), "run", compact=True)

    assert len(compact) < len(full) * 0.6


def test_compact_truncates_the_criterion(patched: None) -> None:
    out = render_verification_status(_Bus(), "run", compact=True)
    payload = json.loads(out.split("[version-bound checks]\n", 1)[1])

    criterion = payload["checks"][0]["criterion"]
    assert 0 < len(criterion) <= verification._CRITERION_PREVIEW_CHARS


def test_env_switch_turns_compaction_on(
    patched: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("VERIFICATION_STATUS_COMPACT", "1")

    out = render_verification_status(_Bus(), "run")

    assert "binding_id" not in out
