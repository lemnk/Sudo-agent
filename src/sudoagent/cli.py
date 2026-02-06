"""Command-line interface for sudoagent."""

from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import datetime
from pathlib import Path
from typing import Iterable, Iterator

from sudoagent.ledger.jsonl import JSONLLedger, LedgerVerificationError
from sudoagent.ledger.signing import generate_keypair, load_public_key

CSV_FIELDS = (
    "created_at",
    "event",
    "action",
    "request_id",
    "agent_id",
    "decision_hash",
    "policy_id",
    "policy_hash",
    "decision_effect",
    "outcome_status",
    "reason",
    "reason_code",
)

def _format_optional_dependency_error(exc: Exception) -> str:
    message = str(exc)
    if isinstance(exc, RuntimeError) and "cryptography" in message:
        return f"{message} (install \"sudoagent[crypto]\")"
    return message


def _iter_entries(path: Path) -> Iterator[dict[str, object]]:
    with path.open("r", encoding="utf-8") as handle:
        for raw_line in handle:
            line = raw_line.strip()
            if not line:
                continue
            yield json.loads(line)


def _parse_timestamp(value: str) -> datetime | None:
    text = value.strip()
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        return datetime.fromisoformat(text)
    except ValueError:
        return None


def _stringify(value: object) -> str:
    if value is None:
        return ""
    return str(value)


def _flatten_entry(entry: dict[str, object]) -> dict[str, str]:
    decision = entry.get("decision")
    if not isinstance(decision, dict):
        decision = {}
    outcome = entry.get("outcome")
    if not isinstance(outcome, dict):
        outcome = {}
    return {
        "created_at": _stringify(entry.get("created_at")),
        "event": _stringify(entry.get("event")),
        "action": _stringify(entry.get("action")),
        "request_id": _stringify(entry.get("request_id")),
        "agent_id": _stringify(entry.get("agent_id")),
        "decision_hash": _stringify(decision.get("decision_hash")),
        "policy_id": _stringify(decision.get("policy_id")),
        "policy_hash": _stringify(decision.get("policy_hash")),
        "decision_effect": _stringify(decision.get("effect")),
        "outcome_status": _stringify(outcome.get("status")),
        "reason": _stringify(decision.get("reason")),
        "reason_code": _stringify(decision.get("reason_code")),
    }


def _write_entries(
    entries: Iterable[dict[str, object]],
    output_format: str,
    output_path: Path | None,
) -> int:
    """Write entries in the specified format. Streams entries to avoid memory issues.

    For JSON format: writes a valid JSON array incrementally without loading all entries.
    For NDJSON/CSV: already streams naturally.
    """
    output = sys.stdout
    close_output = False
    if output_path is not None:
        output = output_path.open("w", encoding="utf-8", newline="")
        close_output = True
    try:
        if output_format == "json":
            # Stream JSON array incrementally: [entry1,entry2,...]
            output.write("[")
            first = True
            for entry in entries:
                if not first:
                    output.write(",")
                first = False
                output.write(json.dumps(entry, ensure_ascii=False))
            output.write("]\n")
        elif output_format == "ndjson":
            for entry in entries:
                output.write(json.dumps(entry, ensure_ascii=False, separators=(",", ":")) + "\n")
        elif output_format == "csv":
            writer = csv.DictWriter(
                output,
                fieldnames=CSV_FIELDS,
                extrasaction="ignore",
                lineterminator="\n",
            )
            writer.writeheader()
            for entry in entries:
                writer.writerow(_flatten_entry(entry))
        else:
            raise ValueError(f"unknown format: {output_format}")
    finally:
        if close_output:
            output.close()
    return 0


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="sudoagent", add_help=True)
    subparsers = parser.add_subparsers(dest="command", required=True)

    verify_parser = subparsers.add_parser("verify", help="Verify a JSONL ledger file")
    verify_parser.add_argument("ledger_path", type=Path, help="Path to ledger JSONL file")
    verify_parser.add_argument("--json", action="store_true", help="Output JSON")
    verify_parser.add_argument("--public-key", type=Path, help="Path to Ed25519 public key PEM")

    export_parser = subparsers.add_parser("export", help="Export ledger entries")
    export_parser.add_argument("ledger_path", type=Path, help="Path to ledger JSONL file")
    export_parser.add_argument(
        "--format",
        choices=("json", "ndjson", "csv"),
        default="ndjson",
        help="Output format",
    )
    export_parser.add_argument("--output", type=Path, help="Output file path")

    filter_parser = subparsers.add_parser("filter", help="Filter ledger entries")
    filter_parser.add_argument("ledger_path", type=Path, help="Path to ledger JSONL file")
    filter_parser.add_argument("--request-id", dest="request_id", help="Filter by request_id")
    filter_parser.add_argument("--action", help="Filter by action")
    filter_parser.add_argument("--agent-id", dest="agent_id", help="Filter by agent_id")
    filter_parser.add_argument("--start", help="Filter entries at or after timestamp (UTC)")
    filter_parser.add_argument("--end", help="Filter entries at or before timestamp (UTC)")
    filter_parser.add_argument(
        "--format",
        choices=("json", "ndjson", "csv"),
        default="ndjson",
        help="Output format",
    )
    filter_parser.add_argument("--output", type=Path, help="Output file path")

    search_parser = subparsers.add_parser("search", help="Search ledger entries")
    search_parser.add_argument("ledger_path", type=Path, help="Path to ledger JSONL file")
    search_parser.add_argument("--query", required=True, help="Search query")
    search_parser.add_argument("--start", help="Filter entries at or after timestamp (UTC)")
    search_parser.add_argument("--end", help="Filter entries at or before timestamp (UTC)")
    search_parser.add_argument(
        "--format",
        choices=("json", "ndjson", "csv"),
        default="ndjson",
        help="Output format",
    )
    search_parser.add_argument("--output", type=Path, help="Output file path")

    keygen_parser = subparsers.add_parser("keygen", help="Generate Ed25519 key pair")
    keygen_parser.add_argument("--private-key", type=Path, required=True, help="Path to private key PEM")
    keygen_parser.add_argument("--public-key", type=Path, required=True, help="Path to public key PEM")
    keygen_parser.add_argument(
        "--overwrite",
        action="store_true",
        help="Overwrite existing key files",
    )

    receipt_parser = subparsers.add_parser("receipt", help="Generate a ledger receipt")
    receipt_parser.add_argument("ledger_path", type=Path, help="Path to ledger JSONL file")
    receipt_parser.add_argument("--request-id", dest="request_id", help="Lookup by request_id")
    receipt_parser.add_argument("--decision-hash", dest="decision_hash", help="Lookup by decision_hash")
    receipt_parser.add_argument("--output", type=Path, help="Output file path")

    return parser.parse_args(argv)


def _cmd_verify(ledger_path: Path, json_output: bool, public_key_path: Path | None) -> int:
    public_key = None
    if public_key_path is not None:
        try:
            public_key = load_public_key(public_key_path.read_bytes())
        except Exception as exc:
            if json_output:
                print(json.dumps({"status": "failed", "error": _format_optional_dependency_error(exc)}))
            else:
                print(f"verify failed: {_format_optional_dependency_error(exc)}", file=sys.stderr)
            return 1
    ledger = JSONLLedger(ledger_path)
    try:
        ledger.verify(public_key=public_key)
    except LedgerVerificationError as exc:
        if json_output:
            print(json.dumps({"status": "failed", "error": _format_optional_dependency_error(exc)}))
        else:
            print(f"verify failed: {_format_optional_dependency_error(exc)}", file=sys.stderr)
        return 1
    except Exception as exc:  # one-line justification: catch-all to fail closed on unexpected issues
        if json_output:
            print(json.dumps({"status": "failed", "error": _format_optional_dependency_error(exc)}))
        else:
            print(f"verify failed: {_format_optional_dependency_error(exc)}", file=sys.stderr)
        return 1
    else:
        if json_output:
            print(json.dumps({"status": "ok"}))
        else:
            print("verification ok")
        return 0


def _cmd_export(ledger_path: Path, output_format: str, output_path: Path | None) -> int:
    if not ledger_path.exists():
        print("ledger file not found", file=sys.stderr)
        return 1
    try:
        entries = _iter_entries(ledger_path)
        return _write_entries(entries, output_format, output_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"export failed: {exc}", file=sys.stderr)
        return 1


def _matches_filters(
    entry: dict[str, object],
    *,
    request_id: str | None,
    action: str | None,
    agent_id: str | None,
    start: datetime | None,
    end: datetime | None,
) -> bool:
    if request_id is not None and entry.get("request_id") != request_id:
        return False
    if action is not None and entry.get("action") != action:
        return False
    if agent_id is not None and entry.get("agent_id") != agent_id:
        return False
    if start is not None or end is not None:
        created_at = entry.get("created_at")
        if not isinstance(created_at, str):
            return False
        parsed = _parse_timestamp(created_at)
        if parsed is None:
            return False
        if start is not None and parsed < start:
            return False
        if end is not None and parsed > end:
            return False
    return True


def _cmd_filter(
    ledger_path: Path,
    *,
    request_id: str | None,
    action: str | None,
    agent_id: str | None,
    start: str | None,
    end: str | None,
    output_format: str,
    output_path: Path | None,
) -> int:
    if not ledger_path.exists():
        print("ledger file not found", file=sys.stderr)
        return 1
    start_ts = _parse_timestamp(start) if start is not None else None
    if start is not None and start_ts is None:
        print("invalid --start timestamp", file=sys.stderr)
        return 2
    end_ts = _parse_timestamp(end) if end is not None else None
    if end is not None and end_ts is None:
        print("invalid --end timestamp", file=sys.stderr)
        return 2
    if start_ts is not None and end_ts is not None and start_ts > end_ts:
        print("--start must be <= --end", file=sys.stderr)
        return 2
    try:
        entries = _iter_entries(ledger_path)
        filtered = (
            entry
            for entry in entries
            if _matches_filters(
                entry,
                request_id=request_id,
                action=action,
                agent_id=agent_id,
                start=start_ts,
                end=end_ts,
            )
        )
        return _write_entries(filtered, output_format, output_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"filter failed: {exc}", file=sys.stderr)
        return 1


def _cmd_search(
    ledger_path: Path,
    *,
    query: str,
    start: str | None,
    end: str | None,
    output_format: str,
    output_path: Path | None,
) -> int:
    if not ledger_path.exists():
        print("ledger file not found", file=sys.stderr)
        return 1
    start_ts = _parse_timestamp(start) if start is not None else None
    if start is not None and start_ts is None:
        print("invalid --start timestamp", file=sys.stderr)
        return 2
    end_ts = _parse_timestamp(end) if end is not None else None
    if end is not None and end_ts is None:
        print("invalid --end timestamp", file=sys.stderr)
        return 2
    if start_ts is not None and end_ts is not None and start_ts > end_ts:
        print("--start must be <= --end", file=sys.stderr)
        return 2
    query_text = query.lower()
    try:
        entries = _iter_entries(ledger_path)

        def _matches_query(entry: dict[str, object]) -> bool:
            for key in ("request_id", "action", "agent_id"):
                value = entry.get(key)
                if isinstance(value, str) and query_text in value.lower():
                    return True
            return False

        matched = (
            entry
            for entry in entries
            if _matches_query(entry)
            and _matches_filters(
                entry,
                request_id=None,
                action=None,
                agent_id=None,
                start=start_ts,
                end=end_ts,
            )
        )
        return _write_entries(matched, output_format, output_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"search failed: {exc}", file=sys.stderr)
        return 1


def _cmd_keygen(
    *,
    private_key_path: Path,
    public_key_path: Path,
    overwrite: bool,
) -> int:
    if not overwrite and (private_key_path.exists() or public_key_path.exists()):
        print("key file already exists", file=sys.stderr)
        return 1
    private_key_path.parent.mkdir(parents=True, exist_ok=True)
    public_key_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        private_key, public_key = generate_keypair()
    except Exception as exc:
        print(_format_optional_dependency_error(exc), file=sys.stderr)
        return 1
    private_key_path.write_bytes(private_key)
    public_key_path.write_bytes(public_key)
    return 0


def _cmd_receipt(
    ledger_path: Path,
    *,
    request_id: str | None,
    decision_hash: str | None,
    output_path: Path | None,
) -> int:
    if not ledger_path.exists():
        print("ledger file not found", file=sys.stderr)
        return 1
    if (request_id is None and decision_hash is None) or (
        request_id is not None and decision_hash is not None
    ):
        print("provide exactly one of --request-id or --decision-hash", file=sys.stderr)
        return 2
    try:
        entries = _iter_entries(ledger_path)
    except (OSError, json.JSONDecodeError) as exc:
        print(f"receipt failed: {exc}", file=sys.stderr)
        return 1
    match = None
    for idx, entry in enumerate(entries, start=1):
        if entry.get("event") != "decision":
            continue
        decision = entry.get("decision")
        if not isinstance(decision, dict):
            continue
        if request_id is not None and entry.get("request_id") == request_id:
            match = (idx, entry, decision)
            break
        if decision_hash is not None and decision.get("decision_hash") == decision_hash:
            match = (idx, entry, decision)
            break
    if match is None:
        print("receipt target not found", file=sys.stderr)
        return 1
    idx, entry, decision = match
    receipt = {
        "ledger_position": idx,
        "schema_version": entry.get("schema_version"),
        "ledger_version": entry.get("ledger_version"),
        "request_id": entry.get("request_id"),
        "created_at": entry.get("created_at"),
        "policy_id": decision.get("policy_id"),
        "policy_hash": decision.get("policy_hash"),
        "decision_hash": decision.get("decision_hash"),
        "entry_hash": entry.get("entry_hash"),
        "entry_signature": entry.get("entry_signature"),
    }
    output = sys.stdout
    if output_path is not None:
        output = output_path.open("w", encoding="utf-8")
    try:
        output.write(json.dumps(receipt, ensure_ascii=False))
        output.write("\n")
    finally:
        if output_path is not None:
            output.close()
    return 0


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    if args.command == "verify":
        return _cmd_verify(args.ledger_path, args.json, args.public_key)
    if args.command == "export":
        return _cmd_export(args.ledger_path, args.format, args.output)
    if args.command == "filter":
        return _cmd_filter(
            args.ledger_path,
            request_id=args.request_id,
            action=args.action,
            agent_id=args.agent_id,
            start=args.start,
            end=args.end,
            output_format=args.format,
            output_path=args.output,
        )
    if args.command == "search":
        return _cmd_search(
            args.ledger_path,
            query=args.query,
            start=args.start,
            end=args.end,
            output_format=args.format,
            output_path=args.output,
        )
    if args.command == "keygen":
        return _cmd_keygen(
            private_key_path=args.private_key,
            public_key_path=args.public_key,
            overwrite=args.overwrite,
        )
    if args.command == "receipt":
        return _cmd_receipt(
            args.ledger_path,
            request_id=args.request_id,
            decision_hash=args.decision_hash,
            output_path=args.output,
        )
    print("unknown command", file=sys.stderr)
    return 1


if __name__ == "__main__":
    sys.exit(main())
