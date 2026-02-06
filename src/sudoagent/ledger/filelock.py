"""Cross-platform file locking for append-only ledgers.

Provides exclusive file locking that works on both Windows (msvcrt) and
Unix-like systems (fcntl). Designed for ledger append operations.

Design notes:
- LOCK_LENGTH_BYTES: On Windows, msvcrt.locking() requires a byte count.
  We use 1 byte because we're locking for exclusive access, not range locking.
- Advisory locking on Unix: flock() is advisory - cooperating processes must
  also use flock(). This is standard for append-only logs.
"""

from __future__ import annotations

import os
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Protocol, TextIO, cast

# Windows msvcrt.locking() requires byte count. We use 1 for exclusive access.
# This is not a range lock - it signals "I want exclusive access to this file."
LOCK_LENGTH_BYTES: int = 1


class _LockStrategy(Protocol):
    """Platform-specific file lock strategy."""

    def acquire(self, file_handle: TextIO) -> None:
        """Acquire exclusive lock on file. Blocks until acquired."""
        ...

    def release(self, file_handle: TextIO) -> None:
        """Release exclusive lock on file."""
        ...


class _MsvcrtModule(Protocol):
    LK_LOCK: int
    LK_UNLCK: int

    def locking(self, fd: int, mode: int, nbytes: int) -> None:
        ...


class _FcntlModule(Protocol):
    LOCK_EX: int
    LOCK_UN: int

    def flock(self, fd: int, operation: int) -> None:
        ...


class _WindowsLockStrategy:
    """Windows file lock strategy using msvcrt.locking."""

    def __init__(self) -> None:
        import msvcrt
        self._msvcrt: _MsvcrtModule = cast(_MsvcrtModule, msvcrt)

    def acquire(self, file_handle: TextIO) -> None:
        self._msvcrt.locking(file_handle.fileno(), self._msvcrt.LK_LOCK, LOCK_LENGTH_BYTES)

    def release(self, file_handle: TextIO) -> None:
        self._msvcrt.locking(file_handle.fileno(), self._msvcrt.LK_UNLCK, LOCK_LENGTH_BYTES)


class _UnixLockStrategy:
    """Unix file lock strategy using fcntl.flock."""

    def __init__(self) -> None:
        import fcntl
        self._fcntl: _FcntlModule = cast(_FcntlModule, fcntl)

    def acquire(self, file_handle: TextIO) -> None:
        self._fcntl.flock(file_handle.fileno(), self._fcntl.LOCK_EX)

    def release(self, file_handle: TextIO) -> None:
        self._fcntl.flock(file_handle.fileno(), self._fcntl.LOCK_UN)


_LOCK_STRATEGY: _LockStrategy
if os.name == "nt":
    _LOCK_STRATEGY = _WindowsLockStrategy()
else:
    _LOCK_STRATEGY = _UnixLockStrategy()


@contextmanager
def locked_file(path: Path) -> Iterator[TextIO]:
    """Open file with exclusive lock for atomic append operations.
    
    Usage:
        with locked_file(Path("ledger.jsonl")) as handle:
            handle.write(line + "\\n")
            handle.flush()
            os.fsync(handle.fileno())
    
    The lock is held for the duration of the context manager.
    File is opened in append+ mode (read and append).
    The handle is positioned at end of file after the lock is acquired.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    file_handle = path.open("a+", encoding="utf-8", newline="")
    try:
        file_handle.seek(0)
        _LOCK_STRATEGY.acquire(file_handle)
        file_handle.seek(0, os.SEEK_END)
        yield file_handle
    finally:
        try:
            file_handle.seek(0)
            _LOCK_STRATEGY.release(file_handle)
        finally:
            file_handle.close()
