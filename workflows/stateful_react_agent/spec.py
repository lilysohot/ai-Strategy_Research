"""Pipeline spec: ``stateful-react-agent``."""

from __future__ import annotations

from frontier_agent.models.pipeline_spec import (
    CompressionConfig,
    ContextPolicy,
    NodeDefinition,
    PipelineSpec,
    TransitionSpec,
)

REACT_SPEC = PipelineSpec(
    pipeline_id="stateful-react-agent",
    name="Stateful ReAct Agent",
    description=(
        "A single stateful ReAct agent in a per-task workspace. A no-tool "
        "assistant response is the final answer."
    ),
    entry_point="react_agent",
    terminal_nodes=["react_agent"],
    nodes=[
        NodeDefinition(
            node_id="react_agent",
            role_id="stateful_react",
            node_function=(
                "workflows.stateful_react_agent.nodes.main_agent.react_agent_node"
            ),
            context_policy=ContextPolicy(
                include_fields=[
                    "original_question", "current_query", "language",
                    "task_id", "metadata",
                    # Opaque previous-run dump transported by the server; the
                    # node validates it before replaying (issue 01 §9.4).
                    "replay_payload",
                    # Read/write are separate for watch runs (issue 01 §13):
                    # replay the human conversation, never persist raw monitor
                    # messages over it. ``continuity_enabled`` remains as a
                    # compatibility input for older direct workflow callers.
                    "continuity_read_enabled",
                    "continuity_write_enabled",
                    "continuity_enabled",
                ],
            ),
            compression=CompressionConfig(enabled=False),
            output_fields=[
                "final_answer", "final_content", "react_steps", "language",
                "session_turn",
                "answer_status", "answer_sentinel",
                "final_answer_rescued", "final_answer_rescue_mode",
                "final_answer_source", "stopped_by",
                # Whether the cross-turn dump was replayed, and why not.
                "replay_decision",
                # The write-time summary call's own tokens (issue 01 §12.11 待办 2).
                "summary_usage",
            ],
        ),
    ],
    transitions=[
        TransitionSpec(from_phase="react_agent", to_phase="__END__"),
    ],
)
