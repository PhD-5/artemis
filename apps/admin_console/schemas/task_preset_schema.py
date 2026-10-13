"""Validated API and storage representation of recommended tasks."""

from pydantic import BaseModel, Field, StrictBool, StrictStr, model_validator
from typing import Literal

try:
    from admin_console.services.task_template import validate_task_template
except ImportError:
    from apps.admin_console.services.task_template import validate_task_template


class AppInfo(BaseModel):
    name: str
    icon: str
    pkg: str
    category: str = "general"


class TaskPresetInput(BaseModel):
    title: str = Field(min_length=1)
    description: str = Field(min_length=1)
    goal: str = Field(min_length=1)
    parameters: list[StrictStr] = Field(default_factory=list)
    profile: Literal["flash", "pro"]
    expected_output: str | None = None
    category: Literal["flash", "pro", "cross_app", "monitor"]
    tag: str = Field(min_length=1)
    apps: list[AppInfo]
    required_packages: list[str] = Field(default_factory=list)
    match_mode: Literal["any", "all"] = "any"
    priority: int = 50

    @model_validator(mode="after")
    def validate_prompt(self) -> "TaskPresetInput":
        validate_task_template(self.goal, self.parameters)
        return self


class TaskPresetArchiveInput(BaseModel):
    archived: StrictBool


class TaskPreset(TaskPresetInput):
    id: str
    archived: bool = False
