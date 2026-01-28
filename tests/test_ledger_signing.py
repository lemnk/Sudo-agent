from __future__ import annotations

from pathlib import Path

import pytest

from sudoagent.ledger.jsonl import JSONLLedger, LedgerVerificationError
from sudoagent.ledger.signing import (
    CRYPTO_AVAILABLE,
    generate_keypair,
    load_private_key,
    load_public_key,
)

pytestmark = pytest.mark.skipif(
    not CRYPTO_AVAILABLE, reason="cryptography not installed"
)


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


def test_signature_verification_round_trip(tmp_path: Path) -> None:
    private_bytes, public_bytes = generate_keypair()
    private_key = load_private_key(private_bytes)
    public_key = load_public_key(public_bytes)

    ledger = JSONLLedger(tmp_path / "ledger.jsonl", signing_key=private_key)
    ledger.append(_entry("req-1", "decision", "dh-1"))
    ledger.append(_entry("req-1", "outcome", "dh-1"))

    ledger.verify(public_key=public_key)


def test_signature_verification_missing_signature_fails(tmp_path: Path) -> None:
    _, public_bytes = generate_keypair()
    public_key = load_public_key(public_bytes)

    ledger = JSONLLedger(tmp_path / "ledger.jsonl")
    ledger.append(_entry("req-1", "decision", "dh-1"))

    with pytest.raises(LedgerVerificationError):
        ledger.verify(public_key=public_key)


def test_signature_verification_rejects_tampered_signature(tmp_path: Path) -> None:
    private_bytes, public_bytes = generate_keypair()
    private_key = load_private_key(private_bytes)
    public_key = load_public_key(public_bytes)

    ledger_path = tmp_path / "ledger.jsonl"
    ledger = JSONLLedger(ledger_path, signing_key=private_key)
    ledger.append(_entry("req-1", "decision", "dh-1"))

    text = ledger_path.read_text(encoding="utf-8")
    text = text.replace('"entry_signature":"', '"entry_signature":"tampered')
    ledger_path.write_text(text, encoding="utf-8")

    with pytest.raises(LedgerVerificationError):
        ledger.verify(public_key=public_key)
