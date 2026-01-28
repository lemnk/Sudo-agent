from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from sudoagent.ledger.canonical import (
    CanonicalizationError,
    canonical_dumps,
    canonical_sha256_hex,
)


def test_canonical_hash_is_stable_across_key_order() -> None:
    payload_one = {
        "b": 1,
        "a": {
            "y": [3, {"z": Decimal("01.2300"), "a": 2}],
            "x": "value",
        },
    }
    payload_two = {
        "a": {
            "x": "value",
            "y": [3, {"a": 2, "z": Decimal("1.230")}],
        },
        "b": 1,
    }

    dump_one = canonical_dumps(payload_one)
    dump_two = canonical_dumps(payload_two)

    assert dump_one == dump_two
    assert '"z":1.23' in dump_one

    hash_one = canonical_sha256_hex(payload_one)
    hash_two = canonical_sha256_hex(payload_two)
    assert hash_one == hash_two


def test_float_inputs_are_rejected() -> None:
    with pytest.raises(CanonicalizationError, match="float values are not permitted"):
        canonical_dumps({"value": 1.1})


def test_datetimes_are_canonicalized_and_non_utc_are_handled() -> None:
    utc_time = datetime(2026, 1, 25, 12, 0, 0, tzinfo=timezone.utc)
    canonical = canonical_dumps({"ts": utc_time})
    assert '"ts":"2026-01-25T12:00:00.000000Z"' in canonical

    offset_time = datetime(2026, 1, 25, 13, 30, 0, tzinfo=timezone(timedelta(hours=1)))
    canonical_offset = canonical_dumps({"ts": offset_time})
    assert '"ts":"2026-01-25T12:30:00.000000Z"' in canonical_offset

    with pytest.raises(CanonicalizationError, match="timezone-aware and UTC"):
        canonical_dumps({"ts": datetime(2026, 1, 25, 12, 0, 0)})
