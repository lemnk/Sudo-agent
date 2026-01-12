from __future__ import annotations

from datetime import datetime, timezone
import json

import pytest

from sudoagent.types import ApprovalResult, AuditEntry, Context, Decision


def test_context_action_empty_raises() -> None:
    with pytest.raises(ValueError):
        Context(action="  ", args=(), kwargs={})


def test_context_metadata_none_defaults_empty_dict() -> None:
    ctx = Context(action="pkg.mod.func", args=(), kwargs={}, metadata=None)
    assert ctx.metadata == {}


def test_context_metadata_invalid_type_raises() -> None:
    with pytest.raises(TypeError):
        Context(action="pkg.mod.func", args=(), kwargs={}, metadata="x")


def test_approval_result_require_approval_needs_request_id() -> None:
    with pytest.raises(ValueError):
        ApprovalResult(decision=Decision.REQUIRE_APPROVAL, reason="needs approval")


def test_audit_entry_rejects_naive_datetime() -> None:
    naive = datetime.now()
    with pytest.raises(ValueError):
        AuditEntry(
            timestamp=naive,
            action="pkg.mod.func",
            decision=Decision.DENY,
            reason="denied",
        )


def test_audit_entry_timezone_aware_to_json_line() -> None:
    entry = AuditEntry(
        timestamp=datetime.now(timezone.utc),
        action="pkg.mod.func",
        decision=Decision.ALLOW,
        reason="ok",
    )
    line = entry.to_json_line()
    payload = json.loads(line)
    assert payload["decision"] == "allow"
