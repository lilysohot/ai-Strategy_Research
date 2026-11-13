"""Model-facing board inputs; unknown fields must never look like successful writes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator

from frontier_agent.components.task_board_types import VALID_RESOLUTION

#: Resolution values accepted by the board, as a ``Literal`` for the schema.
#: Built from the shared tuple so the board write path, the delivery path and the
#: error text can never drift apart (a cancelled item used to be unsayable at
#: delivery and had to be re-declared blocked, which downgraded the whole answer).
ResolutionLiteral = Literal["open", "in_progress", "resolved", "cancelled", "blocked"]

if tuple(ResolutionLiteral.__args__) != VALID_RESOLUTION:  # pragma: no cover - import guard
    raise RuntimeError(
        "board resolution schema drifted from task_board_types.VALID_RESOLUTION: "
        f"{ResolutionLiteral.__args__} != {VALID_RESOLUTION}"
    )

_REQUIRED_FOR_COMPLETION_HELP = (
    "True (default) when the user's requested result or its necessary support depends on this "
    "item. Set false ONLY for self-added enrichment the user did not ask for. An optional item "
    "may stay cancelled/blocked without downgrading the answer; it is frozen once work is "
    "dispatched, so it can never be re-labelled to dodge a gap."
)


class PlannedCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    check_id: StrictStr = Field(pattern=r"^[A-Za-z0-9_.:-]{1,80}$")
    criterion: StrictStr = Field(min_length=1, max_length=2000)


class BoardProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    notes: StrictStr | None = None
    gap: StrictStr | None = Field(
        default=None,
        description="Unmet user requirement or evidence necessary to support the requested result. "
        "Optional exploration belongs in limitations; never move a failed required check there.",
    )
    limitations: StrictStr | None = Field(
        default=None, max_length=2000,
        description="Nonblocking scope boundaries or optional work not performed. "
        "Does not waive required evidence, execution or verification gates.",
    )
    done_when: StrictStr | None = Field(
        default=None,
        description="Acceptance criterion for the original user requirement. Do not replace a "
        "requested result with 'produce it or explain why unavailable'; missing necessary inputs "
        "still block that result even when the investigation and explanation are complete.",
    )
    kind: Literal["research", "verification", "delivery"] | None = None
    evidence_refs: list[StrictStr] | None = None
    owner: StrictStr | list[StrictStr] | None = None
    owners: StrictStr | list[StrictStr] | None = None
    required_for_completion: StrictBool | None = Field(
        default=None, description=_REQUIRED_FOR_COMPLETION_HELP,
    )
    verification_requirements: list[PlannedCheck] | None = Field(
        default=None, min_length=1,
        description="Planned check IDs and criteria. Register before dispatch; immutable after dispatch.",
    )

    @field_validator("verification_requirements")
    @classmethod
    def unique_checks(cls, value: list[PlannedCheck] | None) -> list[PlannedCheck] | None:
        if value and len({check.check_id for check in value}) != len(value):
            raise ValueError("check_id must be unique")
        return value


class BoardAdd(BoardProgress):
    description: StrictStr = Field(min_length=1)
    group: StrictStr | None = None
    verification_required: StrictBool | None = None


class BoardUpdate(BoardProgress):
    id: StrictStr = Field(min_length=1)
    resolution: ResolutionLiteral | None = Field(
        default=None,
        description="blocked requires notes and gap; cancelled retracts the item (notes required). "
        "Neither claims the work succeeded.",
    )
    replace_owners: StrictBool | None = None
    reason: StrictStr | None = None
