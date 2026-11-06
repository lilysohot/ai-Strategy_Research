import json
from datetime import UTC, datetime

import pytest

from server.monitor_prompt import build_monitor_prompt


@pytest.mark.parametrize(
    "reason,crossed",
    [
        ("initial_condition_met", False),
        ("round_condition_met", False),
        ("up_cross", True),
        ("down_cross", True),
        ("enter_range", True),
    ],
)
def test_trigger_explanation_distinguishes_observed_crossing(reason, crossed):
    prompt = build_monitor_prompt(
        sequence=182,
        received_at_ms=0,
        now=datetime.now(UTC),
        prior_analyses=17,
        hits=[
            {
                "trigger_reason": reason,
                "price": "44.88",
                "previous_price": "44.34",
                "previous_observed_at_ms": 1,
                "observed_at_ms": 2,
            }
        ],
    )
    target = json.loads(prompt.splitlines()[-1])["triggered_targets"][0]
    assert target["sampled_crossing"] is crossed
    assert target["previous_price"] == "44.34"
    assert target["previous_observed_at_ms"] == 1
    assert "不能把触发次数当作支撑验证次数" in prompt
