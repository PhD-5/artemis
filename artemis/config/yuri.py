"""Permission settings for the task-opt-in Yuri RPC plugin."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class YuriConfig(BaseModel):
    """Permission is not activation: the user's task must also request Yuri."""

    model_config = ConfigDict(extra="forbid")

    enabled: bool = False
    allowed_tools: list[str] | None = None
    """None uses the catalogue's query/OCR whitelist; [] permits no tools."""
    rpc_timeout_ms: int = Field(default=30000, ge=100, le=300000)
    job_timeout_s: float = Field(default=120.0, gt=0, le=3600)
    poll_interval_s: float = Field(default=1.0, gt=0, le=30)
    identity: Literal["shell", "su_brt", "su"] = "shell"
    compatible_versions: list[str] = Field(default_factory=lambda: ["1.8.6"], min_length=1)
