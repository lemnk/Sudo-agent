"""Typed models for SudoAgent v0.1."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import json
from typing import Any

from pydantic import BaseModel, Field, field_validator, model_validator


class Decision(str, Enum):
    """Outcome of a guarded action."""

    ALLOW = "allow"
    DENY = "deny"
    REQUIRE_APPROVAL = "require_approval"


class Context(BaseModel):
    """Data captured for a single guarded call."""

    action: str
    args: tuple[Any, ...]
    kwargs: dict[str, Any]
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("action")
    @classmethod
    def _action_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("action must be a non-empty string")
        return value

    @field_validator("metadata", mode="before")
    @classmethod
    def _metadata_not_none(cls, value: Any) -> dict[str, Any]:
        if value is None:
            return {}
        if isinstance(value, dict):
            return value
        raise TypeError("metadata must be a dict")


class ApprovalResult(BaseModel):
    """Result of policy evaluation and potential approval."""

    decision: Decision
    reason: str
    request_id: str | None = None

    @field_validator("reason")
    @classmethod
    def _reason_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("reason must be a non-empty string")
        return value

    @model_validator(mode="after")
    def _require_request_id(self) -> "ApprovalResult":
        if (
            self.decision is Decision.REQUIRE_APPROVAL
            and (self.request_id is None or not str(self.request_id).strip())
        ):
            raise ValueError("request_id is required when decision is REQUIRE_APPROVAL")
        return self


class AuditEntry(BaseModel):
    """Audit log entry for JSONL output."""

    timestamp: datetime
    action: str
    decision: Decision
    reason: str
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _timestamp_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    def to_json_line(self) -> str:
        """Render the entry as a single JSON line."""
        return json.dumps(self.model_dump(mode="json"))
