from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from sudoagent.ledger.sqlite import SQLiteLedger, LedgerVerificationError


def _entry(request_id: str, event: str, decision_hash: str) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "ledger_version": "2.0",
        "request_id": request_id,
        "created_at": "2026-01-25T12:00:00.000000Z",
        "event": event,
        "action": "test.action",
        "agent_id": "agent:test",
        "decision": {
            "policy_id": "policy:test",
            "policy_hash": "hash",
            "decision_hash": decision_hash,
            "reason": "ok",
            "reason_code": "TEST",
            "effect": "allow",
        },
        "outcome": {"status": "ok"},
    }


def test_append_and_verify_happy_path(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    ledger.append(_entry("req-1", "decision", "dh-1"))
    ledger.append(_entry("req-1", "outcome", "dh-1"))

    ledger.verify()


def test_tamper_detection_on_modified_entry(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    ledger.append(_entry("req-1", "decision", "dh-1"))
    ledger.append(_entry("req-1", "outcome", "dh-1"))

    conn = sqlite3.connect(tmp_path / "ledger.db")
    row = conn.execute("SELECT id, entry_json FROM ledger ORDER BY id ASC LIMIT 1").fetchone()
    assert row is not None
    entry_id, entry_json = row
    conn.execute(
        "UPDATE ledger SET entry_json = ? WHERE id = ?",
        (entry_json.replace("ok", "tampered"), entry_id),
    )
    conn.commit()
    conn.close()

    with pytest.raises(LedgerVerificationError):
        ledger.verify()


def test_tamper_detection_on_hash_columns(tmp_path: Path) -> None:
    ledger = SQLiteLedger(tmp_path / "ledger.db")
    ledger.append(_entry("req-1", "decision", "dh-1"))
    ledger.append(_entry("req-1", "outcome", "dh-1"))

    conn = sqlite3.connect(tmp_path / "ledger.db")
    conn.execute("UPDATE ledger SET entry_hash = ? WHERE id = 1", ("bogus",))
    conn.commit()
    conn.close()

    with pytest.raises(LedgerVerificationError):
        ledger.verify()
