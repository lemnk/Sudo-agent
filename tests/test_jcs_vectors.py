from __future__ import annotations

import json
from decimal import Decimal

import pytest

from sudoagent.ledger.jcs import CanonicalizationError, canonical_bytes, sha256_hex


# Golden vectors sourced from SudoAgent's strict canonical JSON rules.
# See docs/v2_spec.md
VECTORS = [
    # simple object ordering
    ({"b": 1, "a": 2}, b'{"a":2,"b":1}', "d3626ac30a87e6f7a6428233b3c68299976865fa5508e4267c5415c76af7a772"),
    # unicode example (Angstrom sign U+212B) NFC-normalizes to U+00C5
    ({"\u212b": 1}, b'{"\xc3\x85":1}', "3511e6515fb12a08ba57db370f587800037cc69c6c255bac9e16fbcba6de497f"),
    # arrays
    ([3, 2, 1], b"[3,2,1]", "30c8681f9b840aceee56b737f3b126ae67ec4eb71d2881db831f86014fba016d"),
    # nested object/array
    ({"z": [1, {"a": "x"}]}, b'{"z":[1,{"a":"x"}]}', "c53c1456bf2048c7d5c42ef8e332d78b0b44f0e0267fd559e14b33539e36832b"),
    # decimals: fixed-point, no exponent, trailing zeros removed
    ({"n": Decimal("1.2300")}, b'{"n":1.23}', "c2f4a8099bdaf483ac3f465590b90ae2156f94d0d32c194bfbb06ca2289ad25f"),
    ({"n": Decimal("1E+2")}, b'{"n":100}', "b39022c4ed96525c42cd0e7ce55308533962a655f1c19d5dac2f03e9dd995b2c"),
]


def test_canonical_vectors() -> None:
    for value, expected_bytes, expected_sha in VECTORS:
        assert canonical_bytes(value) == expected_bytes
        assert sha256_hex(value) == expected_sha
        # canonical bytes must parse back to same value
        assert json.loads(expected_bytes) == json.loads(canonical_bytes(value))


def test_rejects_floats() -> None:
    with pytest.raises(CanonicalizationError, match="floats are rejected"):
        canonical_bytes({"n": 1.5})


def test_rejects_duplicate_keys_after_nfc() -> None:
    # U+212B NFC-normalizes to U+00C5, so these collide.
    with pytest.raises(CanonicalizationError, match="duplicate key"):
        canonical_bytes({"\u212b": 1, "\u00c5": 2})
