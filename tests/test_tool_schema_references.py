"""Every advertised tool schema must be pointer-complete.

Pydantic emits document-root-relative references (``#/$defs/Inner``). Embedding
a model's schema under an argument — ``items`` or a property — leaves its
``$defs`` nested inside that sub-schema, so the reference points at
``/<root>/$defs/Inner`` which does not exist. Strict providers reject the whole
chat request with ``Invalid schema for function 'X': Pointer '/$defs/Inner'
does not exist``, and because the schema travels with every call, one such tool
fails the entire run at turn 1. That is not a per-tool degradation, so the
invariant is asserted across the advertised set rather than for one tool.
"""

from pydantic import BaseModel, ConfigDict

from frontier_agent.core.tool import Tool, tool
from plugins.tools import get_builtin_tools
from plugins.tools.assign_task import (
    _AGENT_TEAM_ASSIGN_TASK_PARAMETERS,
    agent_team_assign_task,
)


def _references(node, found: list[str]) -> None:
    if isinstance(node, dict):
        for key, value in node.items():
            if key == "$ref" and isinstance(value, str):
                found.append(value)
            else:
                _references(value, found)
    elif isinstance(node, list):
        for item in node:
            _references(item, found)


def _resolves(document: dict, pointer: str) -> bool:
    current = document
    for part in pointer.lstrip("#/").split("/"):
        if not isinstance(current, dict) or part not in current:
            return False
        current = current[part]
    return True


def dangling_references(document: dict) -> list[str]:
    found: list[str] = []
    _references(document, found)
    return sorted({ref for ref in found if not _resolves(document, ref)})


def test_every_advertised_tool_schema_is_pointer_complete() -> None:
    advertised = {**get_builtin_tools(), "assign_task": agent_team_assign_task}
    broken = {
        name: dangling_references(instance.parameters)
        for name, instance in advertised.items()
        if dangling_references(instance.parameters)
    }
    assert broken == {}


def test_agent_team_assignment_schema_hoists_its_nested_definitions() -> None:
    document = agent_team_assign_task.parameters
    assert sorted(document["$defs"]) == ["VerificationCheck", "VerificationSource"]
    assert "#/$defs/VerificationCheck" in str(document["properties"]["tasks"])
    # The hand-authored constant keeps its embedded shape: the served document
    # is a copy, so assembling the schema never rewrites the module constant.
    assert "$defs" in _AGENT_TEAM_ASSIGN_TASK_PARAMETERS["properties"]["tasks"]["items"]


class Inner(BaseModel):
    model_config = ConfigDict(extra="forbid")
    value: str


class Outer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    items: list[Inner]


_EXPLICIT = {"type": "object", "properties": {"payload": Outer.model_json_schema()}}


@tool(name="explicit_schema_probe", parameters=_EXPLICIT)
async def explicit_schema_probe(payload: dict) -> str:
    """Probe tool with an explicitly supplied nested schema."""
    return "ok"


def test_explicitly_supplied_parameters_are_hoisted() -> None:
    document = explicit_schema_probe.parameters
    assert dangling_references(document) == []
    assert "Inner" in document["$defs"]
    assert "$defs" not in document["properties"]["payload"]
    # Hoisting copies: the caller's dict is a module-level constant.
    assert "$defs" in _EXPLICIT["properties"]["payload"]


def test_tool_still_infers_when_no_parameters_are_supplied() -> None:
    @tool
    async def inferred_probe(count: int) -> str:
        """Probe tool with an inferred schema.

        Args:
            count: How many units to take.

        Returns:
            A marker string.
        """
        return "ok"

    assert isinstance(inferred_probe, Tool)
    assert inferred_probe.parameters["properties"]["count"]["type"] == "integer"
    assert inferred_probe.parameters["properties"]["count"]["description"] == (
        "How many units to take."
    )
