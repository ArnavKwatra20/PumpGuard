"""Bounded conversational diagnostic contracts."""
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class DiagnosticChatMessage(BaseModel):
    model_config = ConfigDict(extra="forbid")
    role: Literal["user", "assistant"]
    content: str = Field(min_length=1, max_length=2000)


class DiagnosticChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    pump_id: str = Field(min_length=1, max_length=64, pattern=r"^[A-Za-z0-9][A-Za-z0-9_.-]*$")
    question: str = Field(min_length=1, max_length=2000)
    history: list[DiagnosticChatMessage] = Field(default_factory=list, max_length=8)

    @model_validator(mode="after")
    def bounded_history(self) -> "DiagnosticChatRequest":
        if sum(len(item.content) for item in self.history) > 8000:
            raise ValueError("conversation history is too long")
        return self


class DiagnosticChatResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")
    assistant_message: str = Field(min_length=1, max_length=6000)
    provider: Literal["mock", "amd", "amd_unavailable"]
    is_mock: bool
    latency_ms: float = Field(ge=0, le=120000)

