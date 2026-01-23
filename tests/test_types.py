from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from sudoagent.types import ApprovalResult, AuditEntry, Context, Decision


# -----------------------------------------------------------------------------
# Context tests
# -----------------------------------------------------------------------------


def test_context_action_empty_raises() -> None:
    with pytest.raises(ValueError):
        Context(action="  ", args=(), kwargs={})


def test_context_metadata_none_defaults_empty_dict() -> None:
    ctx = Context(action="pkg.mod.func", args=(), kwargs={}, metadata=None)
    assert ctx.metadata == {}


def test_context_metadata_invalid_type_raises() -> None:
    with pytest.raises(TypeError):
        Context(action="pkg.mod.func", args=(), kwargs={}, metadata="x")


# -----------------------------------------------------------------------------
# ApprovalResult tests
# -----------------------------------------------------------------------------


def test_approval_result_require_approval_needs_request_id() -> None:
    with pytest.raises(ValueError):
        ApprovalResult(decision=Decision.REQUIRE_APPROVAL, reason="needs approval")


# -----------------------------------------------------------------------------
# AuditEntry tests - timestamp validation (existing)
# -----------------------------------------------------------------------------


def test_audit_entry_rejects_naive_datetime() -> None:
    naive = datetime.now()
    with pytest.raises(ValueError):
        AuditEntry(
            timestamp=naive,
            request_id="abc-123",
            action="pkg.mod.func",
            decision=Decision.DENY,
            reason="denied",
        )


def test_audit_entry_timezone_aware_to_json_line() -> None:
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc),
        request_id="req-001",
        action="pkg.mod.func",
        decision=Decision.ALLOW,
        reason="ok",
    )
    line = entry.to_json_line()
    payload = json.loads(line)
    assert payload["decision"] == "allow"


# -----------------------------------------------------------------------------
# AuditEntry tests - v0.1.1 new fields
# -----------------------------------------------------------------------------


def test_audit_entry_requires_request_id() -> None:
    """request_id is required and must be non-empty."""
    with pytest.raises(ValueError, match="request_id must be a non-empty string"):
        AuditEntry(
            timestamp=datetime.now(timezone.utc),
            request_id="",
            action="pkg.mod.func",
            decision=Decision.ALLOW,
            reason="ok",
        )


def test_audit_entry_decision_event_includes_request_id_and_event() -> None:
    """Decision event has request_id and event='decision' by default."""
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc),
        request_id="req-abc-123",
        action="pkg.mod.func",
        decision=Decision.ALLOW,
        reason="allowed",
    )
    assert entry.request_id == "req-abc-123"
    assert entry.event == "decision"

    line = entry.to_json_line()
    payload = json.loads(line)
    assert payload["request_id"] == "req-abc-123"
    assert payload["event"] == "decision"
    # outcome fields not present for decision event
    assert "outcome" not in payload


def test_audit_entry_outcome_event_requires_outcome_field() -> None:
    """Outcome event must have outcome field set."""
    with pytest.raises(ValueError, match="outcome is required when event is 'outcome'"):
        AuditEntry(
            timestamp=datetime.now(timezone.utc),
            request_id="req-001",
            event="outcome",
            action="pkg.mod.func",
            decision=Decision.ALLOW,
            reason="allowed",
            # outcome not set
        )


def test_audit_entry_outcome_success_serializes_correctly() -> None:
    """Outcome event with success serializes correctly."""
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc),
        request_id="req-xyz",
        event="outcome",
        action="pkg.mod.func",
        decision=Decision.ALLOW,
        reason="allowed",
        outcome="success",
    )
    line = entry.to_json_line()
    payload = json.loads(line)

    assert payload["event"] == "outcome"
    assert payload["outcome"] == "success"
    # error fields not present on success
    assert "error_type" not in payload
    assert "error" not in payload


def test_audit_entry_outcome_error_serializes_correctly() -> None:
    """Outcome event with error includes error_type and error."""
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc),
        request_id="req-err",
        event="outcome",
        action="pkg.mod.func",
        decision=Decision.ALLOW,
        reason="allowed",
        outcome="error",
        error_type="ValueError",
        error="something went wrong",
    )
    line = entry.to_json_line()
    payload = json.loads(line)

    assert payload["event"] == "outcome"
    assert payload["outcome"] == "error"
    assert payload["error_type"] == "ValueError"
    assert payload["error"] == "something went wrong"


def test_audit_entry_error_truncated_to_200_chars() -> None:
    """Error message is truncated to 200 characters."""
    long_error = "x" * 300
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc),
        request_id="req-trunc",
        event="outcome",
        action="pkg.mod.func",
        decision=Decision.ALLOW,
        reason="allowed",
        outcome="error",
        error_type="RuntimeError",
        error=long_error,
    )
    # Truncated to 197 + "..."
    assert entry.error is not None
    assert len(entry.error) == 200
    assert entry.error.endswith("...")

    line = entry.to_json_line()
    payload = json.loads(line)
    assert len(payload["error"]) == 200
