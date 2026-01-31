from __future__ import annotations

import json
from pathlib import Path

import pytest

from sudoagent.cli import main
from sudoagent.ledger.jcs import canonical_bytes, sha256_hex
from sudoagent.ledger.jsonl import JSONLLedger


def _write_valid_ledger(path: Path) -> JSONLLedger:
    ledger = JSONLLedger(path)
    ledger.append(
        {
            "schema_version": "2.0",
            "ledger_version": "2.0",
            "request_id": "req-1",
            "created_at": "2026-01-25T12:00:00.000000Z",
            "event": "decision",
            "action": "test.action",
            "agent_id": "agent:test",
            "decision": {
                "policy_id": "policy:test",
                "policy_hash": "abc",
                "decision_hash": "xyz",
                "reason": "ok",
                "reason_code": "TEST",
            },
        }
    )
    return ledger


def test_verify_success(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_valid_ledger(ledger_path)

    code = main(["verify", str(ledger_path)])

    captured = capsys.readouterr()
    assert code == 0
    assert "verification ok" in captured.out
    assert captured.err == ""


def test_verify_failure_on_tamper(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_valid_ledger(ledger_path)
    text = ledger_path.read_text(encoding="utf-8")
    ledger_path.write_text(text.replace("policy:test", "policy:tampered"), encoding="utf-8")

    code = main(["verify", str(ledger_path)])

    captured = capsys.readouterr()
    assert code == 1
    assert "verify failed" in captured.err
    assert captured.out == ""


def test_verify_failure_on_version_mismatch(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_valid_ledger(ledger_path)
    line = ledger_path.read_text(encoding="utf-8").splitlines()[0]
    entry = json.loads(line)
    entry["schema_version"] = "1.0"
    entry["entry_hash"] = None
    entry["entry_hash"] = sha256_hex(entry)
    ledger_path.write_text(canonical_bytes(entry).decode("utf-8") + "\n", encoding="utf-8")

    code = main(["verify", str(ledger_path)])

    captured = capsys.readouterr()
    assert code == 1
    assert "verify failed" in captured.err
    assert captured.out == ""


def test_verify_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_valid_ledger(ledger_path)

    code = main(["verify", str(ledger_path), "--json"])

    captured = capsys.readouterr()
    assert code == 0
    assert captured.err == ""
    assert captured.out.strip() == '{"status": "ok"}'


def test_verify_json_failure_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_valid_ledger(ledger_path)
    ledger_path.write_text("corrupt", encoding="utf-8")

    code = main(["verify", str(ledger_path), "--json"])

    captured = capsys.readouterr()
    assert code == 1
    assert captured.err == ""
    assert '{"status": "failed"' in captured.out
