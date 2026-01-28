from __future__ import annotations

import json
from pathlib import Path

import pytest

from sudoagent.cli import main
from sudoagent.ledger.jsonl import JSONLLedger


def _write_sample_ledger(path: Path) -> None:
    ledger = JSONLLedger(path)
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
    ledger.append(
        {
            "schema_version": "2.0",
            "ledger_version": "2.0",
            "request_id": "req-2",
            "created_at": "2026-01-25T12:05:00.000000Z",
            "event": "decision",
            "action": "tool.two",
            "agent_id": "agent-2",
            "decision": {
                "policy_id": "policy:test",
                "policy_hash": "hash",
                "decision_hash": "dh-2",
                "reason": "ok",
                "reason_code": "TEST",
                "effect": "deny",
            },
            "outcome": {"status": "error"},
        }
    )


def test_export_json_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_sample_ledger(ledger_path)

    code = main(["export", str(ledger_path), "--format", "json"])

    captured = capsys.readouterr()
    assert code == 0
    payload = json.loads(captured.out)
    assert len(payload) == 2
    assert payload[0]["request_id"] == "req-1"


def test_export_csv_output(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_sample_ledger(ledger_path)

    code = main(["export", str(ledger_path), "--format", "csv"])

    captured = capsys.readouterr()
    assert code == 0
    header = captured.out.splitlines()[0]
    assert "created_at" in header
    assert "request_id" in header


def test_filter_by_request_id(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_sample_ledger(ledger_path)

    code = main(["filter", str(ledger_path), "--request-id", "req-1"])

    captured = capsys.readouterr()
    assert code == 0
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["request_id"] == "req-1"


def test_filter_by_action(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_sample_ledger(ledger_path)

    code = main(["filter", str(ledger_path), "--action", "tool.two"])

    captured = capsys.readouterr()
    assert code == 0
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["action"] == "tool.two"


def test_filter_by_time_range(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_sample_ledger(ledger_path)

    code = main(
        [
            "filter",
            str(ledger_path),
            "--start",
            "2026-01-25T12:02:00Z",
            "--end",
            "2026-01-25T12:06:00Z",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["request_id"] == "req-2"


def test_search_by_time_range(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_sample_ledger(ledger_path)

    code = main(
        [
            "search",
            str(ledger_path),
            "--query",
            "tool",
            "--start",
            "2026-01-25T12:02:00Z",
            "--end",
            "2026-01-25T12:06:00Z",
        ]
    )

    captured = capsys.readouterr()
    assert code == 0
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["request_id"] == "req-2"


def test_search_query_matches_action(tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    ledger_path = tmp_path / "ledger.jsonl"
    _write_sample_ledger(ledger_path)

    code = main(["search", str(ledger_path), "--query", "tool.two"])

    captured = capsys.readouterr()
    assert code == 0
    lines = [line for line in captured.out.splitlines() if line.strip()]
    assert len(lines) == 1
    entry = json.loads(lines[0])
    assert entry["action"] == "tool.two"
