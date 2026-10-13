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

from pydantic import BaseModel, Field, StrictStr, model_validator


class RunRequest(BaseModel):
    goal: str | None = None
    goals: list[str] | None = None
    template_id: str | None = Field(default=None, min_length=1)
    args: dict[str, StrictStr] | None = None
    profile: str | None = None
    expected_output: str | None = None
    enable_outputter: bool | None = None
    # Pro-profile tuning (ignored by the Flash profile): a coarse Checker preset
    # ('off' | 'final' | 'checkpoints' | 'strict') and the Explorer perception
    # version used by the Operator ('flash' | 'pro' | 'ultra').
    verification_level: str | None = None
    explorer_mode: str | None = None
    locked_app_package: str | None = None
    app_path: str | None = None
    device_serial: str | None = None
    ingress: str | None = "frontend"
    session_id: str | None = None
    conversation_id: str | None = None

    @model_validator(mode="after")
    def validate_input_mode(self) -> "RunRequest":
        if self.template_id is not None:
            if not self.template_id.strip():
                raise ValueError("template_id must not be blank")
            if self.goal is not None or self.goals is not None:
                raise ValueError("template_id cannot be combined with goal or goals")
        elif self.args is not None:
            raise ValueError("args requires template_id")
        return self


class ReplayRequest(BaseModel):
    device_id: str
    user_submits: dict
    tool_name: str = "ask_explorer"
    replay_id: str | None = None


class StopRequest(BaseModel):
    session_id: str | None = None
    device_id: str | None = None
    all: bool = False
