"""Manual semantic smoke against the configured provider; no research tools."""
import asyncio
import logging
import sys
from pathlib import Path

from frontier_agent.core.messages import assistant_msg, system_msg, user_msg
from workflows._shared.research_intake import maybe_clarify_research
from workflows.stateful_react_agent.profile import (
    build_react_model_profile, create_react_llm, load_react_profile,
)


async def main():
    logging.disable(logging.CRITICAL)
    profile = load_react_profile("tui")
    cases = [
        ("empty-template", 'ST/*ST个股的涨跌幅与“披星戴帽”触发条件\n请进行深度研究：\n- 研究对象：\n- 时间范围：\n- 需要验证的假设：\n- 输出：结构化报告，包含风险与反方证据。', [], True),
        ("no-subject", "请帮我做个深入研究报告", [], True),
        ("clear-stock", "研究贵州茅台最近的经营状况", [], False),
        ("general-rules", "研究ST/*ST通用交易规则及披星戴帽条件，不针对个股", [], False),
        ("industry", "研究中国半导体行业的竞争格局", [], False),
        ("greeting", "你好", [], False),
        ("follow-up", "继续分析它的风险", [user_msg("研究贵州茅台"), assistant_msg("我们将研究贵州茅台。")], False),
        ("subject-in-title", "研究贵州茅台\n请进行深度研究：\n- 研究对象：\n- 时间范围：", [], False),
        ("attachment", "总结我上传的这份研报，文件在 /inputs/report.pdf", [], False),
    ]
    failures = []
    if True:
        root = ".scratch/research-intake-live"
        for name, question, history, expected in cases:
            if len(sys.argv) > 1 and name not in sys.argv[1:]:
                continue
            try:
                result = await maybe_clarify_research(
                    metadata={"research_intake": True}, llm=create_react_llm(profile),
                    model_profile=build_react_model_profile(profile), task_id=name,
                    system_prompt="Research assistant", user_message=question,
                    initial_messages=[system_msg("Research assistant"), *history],
                    trajectory_dir=Path(root) / name, observers=[],
                )
                passed = (result is not None) == expected
                print(f"{name}: {'PASS' if passed else 'FAIL'}; {'clarify' if result else 'ready'}", flush=True)
                if result:
                    print(result["final_answer"], flush=True)
                if not passed:
                    failures.append(name)
            except Exception as exc:
                print(f"{name}: ERROR {type(exc).__name__}: {exc}", flush=True)
                failures.append(name)
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
