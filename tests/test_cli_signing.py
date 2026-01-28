from __future__ import annotations

import json
from pathlib import Path

import pytest

from sudoagent.cli import main
from sudoagent.ledger.jsonl import JSONLLedger
from sudoagent.ledger.signing import CRYPTO_AVAILABLE, generate_keypair, load_private_key

pytestmark = pytest.mark.skipif(
    not CRYPTO_AVAILABLE, reason="cryptography not installed"
)


def _write_signed_ledger(path: Path, private_key) -> None:
    ledger = JSONLLedger(path, signing_key=private_key)
    ledger.append(
        {
            "schema_version": "2.0",
            "ledger_version": "2.0",
            "request_id": "req-1",
            "created_at": "2026-01-25T12:00:00.000000Z",
            "event": "decision",
            "action": "tool.one",
            "agent_id": "agent-1",
            "decision": {
                "policy_id": "policy:test",
                "policy_hash": "hash",
                "decision_hash": "dh-1",
                "reason": "ok",
                "reason_code": "TEST",
                "effect": "allow",
            },
            "outcome": {"status": "success"},
        }
    )


def test_keygen_creates_key_files(tmp_path: Path) -> None:
    private_path = tmp_path / "private.pem"
    public_path = tmp_path / "public.pem"

    code = main(
        ["keygen", "--private-key", str(private_path), "--public-key", str(public_path)]
    )

    assert code == 0
    assert private_path.exists()
    assert public_path.exists()


def test_verify_with_public_key_succeeds(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    private_bytes, public_bytes = generate_keypair()
    private_key = load_private_key(private_bytes)

    ledger_path = tmp_path / "ledger.jsonl"
    _write_signed_ledger(ledger_path, private_key)

    public_path = tmp_path / "public.pem"
    public_path.write_bytes(public_bytes)

    code = main(["verify", str(ledger_path), "--public-key", str(public_path)])

    captured = capsys.readouterr()
    assert code == 0
    assert "verification ok" in captured.out


def test_receipt_by_request_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    private_bytes, _ = generate_keypair()
    private_key = load_private_key(private_bytes)

    ledger_path = tmp_path / "ledger.jsonl"
    _write_signed_ledger(ledger_path, private_key)

    code = main(["receipt", str(ledger_path), "--request-id", "req-1"])

    captured = capsys.readouterr()
    assert code == 0
    receipt = json.loads(captured.out)
    assert receipt["request_id"] == "req-1"
    assert receipt["decision_hash"] == "dh-1"
