from __future__ import annotations

import os
import shutil
import uuid
from pathlib import Path
from typing import Iterator

import pytest


@pytest.fixture(scope="session", autouse=True)
def _default_ledger_path() -> Iterator[None]:
    """Provide a safe default ledger path for tests that don't pass one explicitly."""
    temp_root = Path(os.environ.get("TEMP", Path.cwd()))
    root = temp_root / "sudoagent_test_runs"
    root.mkdir(parents=True, exist_ok=True)
    ledger_path = root / "default_ledger.jsonl"
    os.environ.setdefault("SUDOAGENT_LEDGER_PATH", str(ledger_path))
    try:
        yield
    finally:
        try:
            ledger_path.unlink(missing_ok=True)
        except OSError:
            pass


@pytest.fixture
def tmp_path() -> Path:
    """Return a writable temp dir under %TEMP% without tempfile.mkdtemp ACL quirks."""
    temp_root = Path(os.environ.get("TEMP", Path.cwd()))
    root = temp_root / "sudoagent_test_runs"
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"run_{uuid.uuid4().hex}"
    path.mkdir(parents=True, exist_ok=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
