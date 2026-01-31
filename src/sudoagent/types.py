"""Typed models for SudoAgent."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
import json
from typing import Any, Literal, NotRequired, TypedDict, Union

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
    """Audit log entry for JSONL output.

    Two event types:
    - "decision": records the policy decision (allow/deny/require_approval)
    - "outcome": records the execution result (success/error)
    """

    timestamp: datetime
    request_id: str
    event: Literal["decision", "outcome"] = "decision"
    action: str
    decision: Decision
    reason: str
    outcome: Literal["success", "error"] | None = None
    error_type: str | None = None
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("timestamp")
    @classmethod
    def _timestamp_timezone_aware(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.tzinfo.utcoffset(value) is None:
            raise ValueError("timestamp must be timezone-aware")
        return value

    @field_validator("request_id")
    @classmethod
    def _request_id_non_empty(cls, value: str) -> str:
        if not value or not value.strip():
            raise ValueError("request_id must be a non-empty string")
        return value

    @field_validator("error", mode="before")
    @classmethod
    def _truncate_error(cls, value: str | None) -> str | None:
        if value is None:
            return None
        if len(value) > 200:
            return value[:197] + "..."
        return value

    @model_validator(mode="after")
    def _validate_outcome_event(self) -> "AuditEntry":
        if self.event == "outcome" and self.outcome is None:
            raise ValueError("outcome is required when event is 'outcome'")
        return self

    def to_json_line(self) -> str:
        """Render the entry as a single JSON line."""
        return json.dumps(self.model_dump(mode="json", exclude_none=True))


# -------- Ledger and receipt typed structures --------


class DecisionRecord(TypedDict):
    effect: str
    reason: str
    reason_code: str | None
    policy_id: str
    policy_hash: str
    decision_hash: str


class ApprovalRecord(TypedDict, total=False):
    binding: dict[str, str] | None
    approved: bool
    approver_id: str | None
    policy_decision: str | None


class BudgetRecord(TypedDict, total=False):
    budget_key: str | None
    cost: int | None


class LedgerDecisionEntry(TypedDict):
    schema_version: str
    ledger_version: str
    prev_entry_hash: str | None
    entry_hash: str | None
    entry_signature: NotRequired[str | None]
    key_id: NotRequired[str | None]
    request_id: str
    created_at: str
    event: Literal["decision"]
    action: str
    agent_id: str
    decision: DecisionRecord
    approval: ApprovalRecord | None
    metadata: dict[str, Any]
    budget: NotRequired[BudgetRecord | None]


class OutcomeRecord(TypedDict, total=False):
    outcome: Literal["success", "error"]
    reason: str
    reason_code: str | None
    error_type: str | None
    error: str | None


class LedgerOutcomeEntry(TypedDict):
    schema_version: str
    ledger_version: str
    prev_entry_hash: str | None
    entry_hash: str | None
    entry_signature: NotRequired[str | None]
    key_id: NotRequired[str | None]
    request_id: str
    created_at: str
    event: Literal["outcome"]
    action: str
    agent_id: str
    decision: dict[str, str | None]
    result: OutcomeRecord
    parameters: dict[str, Any]
    metadata: NotRequired[dict[str, Any]]


class LedgerCheckpointEntry(TypedDict, total=False):
    schema_version: str
    ledger_version: str
    prev_entry_hash: str | None
    entry_hash: str | None
    event: Literal["checkpoint"]
    log_id: str
    entry_index: int
    created_at: str
    signature: str | None
    key_id: str | None


LedgerEntry = Union[LedgerDecisionEntry, LedgerOutcomeEntry, LedgerCheckpointEntry]
