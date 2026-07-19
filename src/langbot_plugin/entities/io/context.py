from __future__ import annotations

import pydantic


class ActionContext(pydantic.BaseModel):
    """Trusted Workspace binding carried outside an action's data payload.

    Plugin-provided data must never be used to construct this object at the
    Runtime-to-Host boundary.  Runtime handlers bind it from the trusted
    LangBot control connection and forward that binding unchanged.
    """

    instance_uuid: str
    workspace_uuid: str
    placement_generation: int = 1
    installation_uuid: str | None = None

    model_config = pydantic.ConfigDict(extra="forbid", frozen=True)

    @pydantic.field_validator("instance_uuid", "workspace_uuid")
    @classmethod
    def validate_required_uuid(cls, value: str) -> str:
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @pydantic.field_validator("installation_uuid")
    @classmethod
    def validate_optional_uuid(cls, value: str | None) -> str | None:
        if value is None:
            return None
        value = value.strip()
        if not value:
            raise ValueError("must not be empty")
        return value

    @pydantic.field_validator("placement_generation")
    @classmethod
    def validate_placement_generation(cls, value: int) -> int:
        if value < 1:
            raise ValueError("placement_generation must be greater than or equal to 1")
        return value

    def same_workspace(self, other: ActionContext) -> bool:
        """Return whether both contexts identify the same fenced Workspace."""

        return (
            self.instance_uuid == other.instance_uuid
            and self.workspace_uuid == other.workspace_uuid
            and self.placement_generation == other.placement_generation
        )

    def for_installation(self, installation_uuid: str | None) -> ActionContext:
        """Return the same Workspace binding with an installation capability."""

        return ActionContext(
            instance_uuid=self.instance_uuid,
            workspace_uuid=self.workspace_uuid,
            placement_generation=self.placement_generation,
            installation_uuid=installation_uuid,
        )

    def without_installation(self) -> ActionContext:
        """Return the Runtime-level Workspace binding."""

        if self.installation_uuid is None:
            return self
        return ActionContext(
            instance_uuid=self.instance_uuid,
            workspace_uuid=self.workspace_uuid,
            placement_generation=self.placement_generation,
        )
