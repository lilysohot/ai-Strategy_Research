"""Model-facing board inputs; unknown fields must never look like successful writes."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictStr, field_validator


class PlannedCheck(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    check_id: StrictStr = Field(pattern=r"^[A-Za-z0-9_.:-]{1,80}$")
    criterion: StrictStr = Field(min_length=1, max_length=2000)


class BoardProgress(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)
    notes: StrictStr | None = None
    gap: StrictStr | None = None
    done_when: StrictStr | None = None
    kind: Literal["research", "verification", "delivery"] | None = None
    evidence_refs: list[StrictStr] | None = None
    owner: StrictStr | list[StrictStr] | None = None
    owners: StrictStr | list[StrictStr] | None = None
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
    resolution: Literal["open", "in_progress", "resolved", "cancelled", "blocked"] | None = Field(
        default=None,
        description="blocked requires notes and gap; permits partial delivery without claiming success.",
    )
    replace_owners: StrictBool | None = None
    reason: StrictStr | None = None
