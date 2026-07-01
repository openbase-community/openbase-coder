"""Pydantic models for Codex app-server thread and turn state."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, computed_field


class ThreadStatus(str, Enum):
    """Status of a Codex coding thread."""

    idle = "idle"
    waiting = "waiting"
    running = "running"
    completed = "completed"
    error = "error"


class TurnInfo(BaseModel):
    """Information about a single turn within a thread."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    run_id: str = Field(serialization_alias="turn_id")
    started_at: datetime
    completed_at: datetime | None = None
    status: ThreadStatus = ThreadStatus.running
    accumulated_output: str = ""
    accumulated_stderr: str = ""
    return_code: int | None = None
    message: str = Field(default="", serialization_alias="prompt")
    reasoning_effort: str | None = None


class ThreadInfo(BaseModel):
    """Information about a Codex coding thread."""

    model_config = ConfigDict(populate_by_name=True, serialize_by_alias=True)

    session_id: str = Field(serialization_alias="thread_id")
    directory: str
    name: str | None = None
    agent_name: str | None = Field(default=None, serialization_alias="agent_name")
    title: str | None = None
    preview: str | None = None
    is_likely_stale: bool = False
    status_warning: str | None = None
    session_type: Literal["codex"] = Field(default="codex", exclude=True)
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
    raw_status: ThreadStatus | None = Field(default=None, exclude=True)
    status_override: ThreadStatus | None = Field(default=None, exclude=True)
    current_run: TurnInfo | None = Field(
        default=None,
        serialization_alias="current_turn",
    )
    run_history: list[TurnInfo] = Field(
        default_factory=list,
        serialization_alias="turn_history",
    )

    @computed_field
    @property
    def status(self) -> ThreadStatus:
        """Get the current status of the thread."""
        if self.current_run is not None:
            return self.current_run.status
        if self.status_override is not None:
            return self.status_override
        if self.run_history:
            return self.run_history[-1].status
        if self.raw_status is not None:
            return self.raw_status
        return ThreadStatus.idle
