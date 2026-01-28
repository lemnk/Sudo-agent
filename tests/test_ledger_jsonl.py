from __future__ import annotations

from pathlib import Path

import pytest

from sudoagent.ledger.jsonl import JSONLLedger, LedgerVerificationError


def _entry(request_id: str, kind: str) -> dict[str, object]:
    return {
        "schema_version": "2.0",
        "ledger_version": "2.0",
        "request_id": request_id,
        "created_at": "2026-01-25T12:00:00.000000Z",
        "event": kind,
        "action": "test.action",
        "agent_id": "agent:test",
        "decision": {
            "kind": kind,
            "policy_id": "policy:test",
            "policy_hash": "hash",
            "decision_hash": f"{request_id}-decision",
            "reason": "ok",
            "reason_code": "TEST",
        },
        "outcome": {"status": "ok"},
    }


def _write_sample_ledger(path: Path) -> JSONLLedger:
    ledger = JSONLLedger(path)
    ledger.append(_entry("req-1", "decision"))
    ledger.append(_entry("req-1", "outcome"))
    return ledger


def test_append_and_verify_happy_path(tmp_path: Path) -> None:
    ledger = _write_sample_ledger(tmp_path / "ledger.jsonl")
    ledger.verify()  # should not raise


def test_tamper_detection_on_modified_line(tmp_path: Path) -> None:
    ledger = _write_sample_ledger(tmp_path / "ledger.jsonl")
    ledger_file = ledger.path
    lines = ledger_file.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"ok"', '"tampered"')
    ledger_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerVerificationError):
        ledger.verify()


def test_deletion_breaks_chain(tmp_path: Path) -> None:
    ledger = _write_sample_ledger(tmp_path / "ledger.jsonl")
    ledger_file = ledger.path
    lines = ledger_file.read_text(encoding="utf-8").splitlines()
    # Keep only the second entry; its prev_entry_hash points to the deleted first.
    if len(lines) < 2:
        pytest.skip("ledger did not contain two lines")
    ledger_file.write_text(lines[1] + "\n", encoding="utf-8")

    with pytest.raises(LedgerVerificationError):
        ledger.verify()


def test_reordering_is_rejected(tmp_path: Path) -> None:
    ledger = _write_sample_ledger(tmp_path / "ledger.jsonl")
    ledger_file = ledger.path
    lines = ledger_file.read_text(encoding="utf-8").splitlines()
    if len(lines) >= 2:
        lines[0], lines[1] = lines[1], lines[0]
    ledger_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerVerificationError):
        ledger.verify()


def test_partial_line_fails_verification(tmp_path: Path) -> None:
    ledger = _write_sample_ledger(tmp_path / "ledger.jsonl")
    ledger_file = ledger.path
    text = ledger_file.read_text(encoding="utf-8")
    # Truncate final characters to create a partial JSON line.
    ledger_file.write_text(text[:-5], encoding="utf-8")

    with pytest.raises(LedgerVerificationError):
        ledger.verify()


def test_prev_hash_mismatch_is_detected(tmp_path: Path) -> None:
    ledger = _write_sample_ledger(tmp_path / "ledger.jsonl")
    ledger_file = ledger.path
    lines = ledger_file.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        pytest.skip("ledger did not contain two lines")
    # Flip the prev_entry_hash in second line to break chain
    corrupted = lines[1].replace('"prev_entry_hash":null', '"prev_entry_hash":"bogus"')
    lines[1] = corrupted
    ledger_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerVerificationError):
        ledger.verify()


def test_schema_version_mismatch_is_detected(tmp_path: Path) -> None:
    ledger = _write_sample_ledger(tmp_path / "ledger.jsonl")
    ledger_file = ledger.path
    lines = ledger_file.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"schema_version":"2.0"', '"schema_version":"1.0"')
    ledger_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerVerificationError):
        ledger.verify()


def test_ledger_version_mismatch_is_detected(tmp_path: Path) -> None:
    ledger = _write_sample_ledger(tmp_path / "ledger.jsonl")
    ledger_file = ledger.path
    lines = ledger_file.read_text(encoding="utf-8").splitlines()
    lines[0] = lines[0].replace('"ledger_version":"2.0"', '"ledger_version":"1.0"')
    ledger_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerVerificationError):
        ledger.verify()


def test_outcome_decision_hash_unknown_is_detected(tmp_path: Path) -> None:
    ledger = _write_sample_ledger(tmp_path / "ledger.jsonl")
    ledger_file = ledger.path
    lines = ledger_file.read_text(encoding="utf-8").splitlines()
    if len(lines) < 2:
        pytest.skip("ledger did not contain two lines")
    lines[1] = lines[1].replace('"decision_hash":"req-1-decision"', '"decision_hash":"bogus"')
    ledger_file.write_text("\n".join(lines) + "\n", encoding="utf-8")

    with pytest.raises(LedgerVerificationError):
        ledger.verify()


def test_two_ledger_handles_append_sequentially(tmp_path: Path) -> None:
    path = tmp_path / "ledger.jsonl"
    ledger_a = JSONLLedger(path)
    ledger_b = JSONLLedger(path)

    ledger_a.append(_entry("req-1", "decision"))
    ledger_b.append(_entry("req-2", "decision"))

    # Both entries must verify and be in correct chain order.
    ledger_a.verify()
