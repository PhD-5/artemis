# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import time
from typing import Any, Literal
from pydantic import BaseModel, Field, field_validator, model_validator


class StreamEventType:
    THOUGHT = "thought"
    ACTION = "action"
    OBSERVATION = "observation"
    STEP_START = "step_start"
    STEP_END = "step_end"
    STATUS = "status"
    ERROR = "error"


class StreamEvent(BaseModel):
    """Real-time intermediate progress event emitted during task execution."""

    event_type: str = Field(
        ..., description="Type of event: thought, action, observation, status, etc."
    )
    step_number: int = Field(default=0, description="1-indexed execution step")
    payload: dict[str, Any] = Field(default_factory=dict, description="Event data dictionary")
    timestamp: float = Field(default_factory=time.time, description="Epoch timestamp")


class Task(BaseModel):
    """Configures a single autonomous mobile automation request."""

    goal: str | None = Field(default=None, description="Raw goal, mutually exclusive with template_id")
    template_id: str | None = Field(default=None, description="Saved task template identifier")
    args: dict[str, str] | None = Field(default=None, description="String template arguments")
    profile: Literal["flash", "pro"] = Field(default="pro", description="Execution profile")
    device_id: str = Field(default="default-device", description="Target device serial")
    device_serial: str | None = Field(
        default=None, description="Target device serial (alias for device_id)"
    )
    concurrency_mode: Literal["global", "per_device"] | None = Field(
        default=None,
        description="Concurrency mode: 'global' (1 across all devices) or 'per_device' (1 per device)",
    )
    locked_package: str | None = Field(default=None, description="Package lock restriction")
    max_turns: int = Field(default=30, description="Turn cutoff limit")

    @field_validator("goal", "template_id", mode="before")
    @classmethod
    def validate_input_strings(cls, value: Any) -> Any:
        if value is not None and not isinstance(value, str):
            raise ValueError("goal and template_id must be strings")
        return value

    @field_validator("args", mode="before")
    @classmethod
    def validate_args(cls, value: Any) -> Any:
        if value is not None and (
            not isinstance(value, dict)
            or any(
                not isinstance(key, str) or not isinstance(arg, str)
                for key, arg in value.items()
            )
        ):
            raise ValueError("args must contain only string names and values")
        return value

    @model_validator(mode="after")
    def validate_input(self) -> "Task":
        if self.goal is not None:
            if not self.goal.strip():
                raise ValueError("goal must not be empty")
            if self.template_id is not None:
                raise ValueError("goal and template_id are mutually exclusive")
            if self.args is not None:
                raise ValueError("args requires template_id")
        elif self.template_id is None or not self.template_id.strip():
            raise ValueError("provide a non-empty goal or template_id")
        return self

    def model_post_init(self, __context: Any) -> None:
        if self.device_serial and self.device_id == "default-device":
            self.device_id = self.device_serial
        elif self.device_id != "default-device" and not self.device_serial:
            self.device_serial = self.device_id


class TaskResult(BaseModel):
    """Final structured outcome of a task execution."""

    trace_id: str
    status: str
    turns: int
    output: Any = None
    error: str | None = None
    device_id: str | None = None
