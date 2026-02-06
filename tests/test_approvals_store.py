from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from sudoagent.approvals_store import SQLiteApprovalStore


def test_create_pending_and_resolve_happy_path(tmp_path) -> None:
    db = tmp_path / "approvals.sqlite"
    store = SQLiteApprovalStore(db)

    now = datetime.now(timezone.utc)
    store.create_pending(
        request_id="req-1",
        policy_hash="ph-1",
        decision_hash="dh-1",
        expires_at=now + timedelta(seconds=60),
    )
    store.resolve(request_id="req-1", state="approved", approver_id="alice@example.com")

    record = store.fetch("req-1")
    assert record is not None
    assert record["state"] == "approved"
    assert record["approver_id"] == "alice@example.com"
    assert record["resolved_at"] is not None


def test_resolve_rejects_invalid_state_transition(tmp_path) -> None:
    db = tmp_path / "approvals.sqlite"
    store = SQLiteApprovalStore(db)

    store.create_pending(
        request_id="req-1",
        policy_hash="ph-1",
        decision_hash="dh-1",
        expires_at=None,
    )
    store.resolve(request_id="req-1", state="denied", approver_id="alice@example.com")

    with pytest.raises(ValueError, match="invalid approval state transition"):
        store.resolve(request_id="req-1", state="approved", approver_id="bob@example.com")


def test_resolve_is_idempotent_for_same_state(tmp_path) -> None:
    db = tmp_path / "approvals.sqlite"
    store = SQLiteApprovalStore(db)

    store.create_pending(
        request_id="req-1",
        policy_hash="ph-1",
        decision_hash="dh-1",
        expires_at=None,
    )
    store.resolve(request_id="req-1", state="approved", approver_id="alice@example.com")
    store.resolve(request_id="req-1", state="approved", approver_id="alice@example.com")

    record = store.fetch("req-1")
    assert record is not None
    assert record["state"] == "approved"


def test_resolve_raises_for_unknown_request_id(tmp_path) -> None:
    db = tmp_path / "approvals.sqlite"
    store = SQLiteApprovalStore(db)

    with pytest.raises(ValueError, match="request_id not found"):
        store.resolve(request_id="missing", state="approved", approver_id="alice@example.com")
