"""Append-only JSONL ledger with canonical hashing and locking."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Iterator, TextIO, cast

from sudoagent.ledger.filelock import locked_file
from sudoagent.ledger.jcs import canonical_bytes
from sudoagent.ledger.signing import sign_entry_hash
from sudoagent.ledger.errors import (
    LedgerError,
    LedgerWriteError,
    LedgerVerificationError,
    sanitize_exception,
)
from sudoagent.ledger.types import JSONValue, SigningKey, VerifyKey
from sudoagent.ledger.common import prepare_entry
from sudoagent.ledger.validation import ParsedEntry, validate_parsed_entries
from sudoagent.types import LedgerEntry


TAIL_READ_CHUNK_SIZE = 4096


@dataclass(frozen=True)
class JSONLLedger:
    path: Path
    signing_key: SigningKey | None = None

    def append(self, entry: LedgerEntry) -> str:
        """Append an entry, computing chain hashes atomically."""
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with locked_file(self.path) as handle:
                last_hash = _read_last_entry_hash(handle)
                prepared = prepare_entry(cast(dict[str, JSONValue], entry), last_hash)
                entry_hash = prepared.get("entry_hash")
                if not isinstance(entry_hash, str):
                    raise LedgerWriteError("entry_hash missing after preparation")
                if self.signing_key is not None:
                    prepared["entry_signature"] = sign_entry_hash(self.signing_key, entry_hash)
                line = canonical_bytes(prepared).decode("utf-8")
                handle.seek(0, os.SEEK_END)
                handle.write(line + "\n")
                handle.flush()
                os.fsync(handle.fileno())
                return entry_hash
        except (OSError, LedgerError) as exc:
            raise LedgerWriteError(sanitize_exception(exc)) from exc

    def verify(self, *, public_key: VerifyKey | None = None) -> None:
        """Verify the entire ledger, failing on any tamper, gap, or reordering."""
        try:
            if not self.path.exists():
                return
            with locked_file(self.path) as handle:
                handle.seek(0)
                _verify_stream(handle, public_key=public_key)
        except (OSError, LedgerError, json.JSONDecodeError) as exc:
            raise LedgerVerificationError(sanitize_exception(exc)) from exc

def _read_last_entry_hash(handle: TextIO) -> str | None:
    """Return the entry_hash from the last non-empty line without scanning the whole file."""
    # Use the underlying buffered file to seek from the end (faster for large files).
    fb = handle.buffer  # type: ignore[attr-defined]
    fb.seek(0, os.SEEK_END)
    size = fb.tell()
    if size == 0:
        return None

    data = b""
    pos = size
    while pos > 0:
        read_size = TAIL_READ_CHUNK_SIZE if pos >= TAIL_READ_CHUNK_SIZE else pos
        pos -= read_size
        fb.seek(pos)
        chunk = fb.read(read_size)
        data = chunk + data
        # Stop once we have at least one newline before the end or we've reached the start.
        if b"\n" in data[:-1] or pos == 0:
            break

    lines = data.rstrip(b"\n").split(b"\n")
    if not lines:
        return None
    last_line = lines[-1].strip()
    if not last_line:
        return None

    try:
        last_entry = json.loads(last_line.decode("utf-8"), parse_float=Decimal, parse_int=int)
    except json.JSONDecodeError as exc:
        raise LedgerVerificationError("invalid JSON at tail") from exc
    if not isinstance(last_entry, dict):
        raise LedgerVerificationError("ledger line is not an object")
    entry_hash = last_entry.get("entry_hash")
    if not isinstance(entry_hash, str):
        raise LedgerVerificationError("entry_hash missing or invalid")
    return entry_hash


def _verify_stream(handle: TextIO, *, public_key: VerifyKey | None = None) -> None:
    def _iter_parsed() -> Iterator[ParsedEntry]:
        line_number = 0
        for raw_line in handle:
            line_number += 1
            line = raw_line.rstrip("\n")
            if not line:
                raise LedgerVerificationError(f"empty line at {line_number}")
            entry = json.loads(line, parse_float=Decimal, parse_int=int)
            if not isinstance(entry, dict):
                raise LedgerVerificationError(f"line {line_number} is not an object")
            if canonical_bytes(entry).decode("utf-8") != line:
                raise LedgerVerificationError(f"line {line_number} is not canonical")
            yield ParsedEntry(entry=cast(dict[str, JSONValue], entry), raw=line, index=line_number)

    validate_parsed_entries(_iter_parsed(), public_key=public_key)
