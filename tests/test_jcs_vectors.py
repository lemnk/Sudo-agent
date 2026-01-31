from __future__ import annotations

import json

import rfc8785

from sudoagent.ledger.jcs import canonical_bytes, sha256_hex


# Golden vectors sourced from RFC 8785 examples and basic composites
VECTORS = [
    # simple object ordering
    ({"b": 1, "a": 2}, b'{"a":2,"b":1}', "d3626ac30a87e6f7a6428233b3c68299976865fa5508e4267c5415c76af7a772"),
    # unicode example (Angstrom sign U+212B)
    ({"\u212b": 1}, b'{"\xe2\x84\xab":1}', "7d32e2d6d0a51f7ed91e64d54f3dd98745784113b4dc59dac919767eed6c30be"),
    # arrays
    ([3, 2, 1], b"[3,2,1]", "30c8681f9b840aceee56b737f3b126ae67ec4eb71d2881db831f86014fba016d"),
    # nested object/array
    ({"z": [1, {"a": "x"}]}, b'{"z":[1,{"a":"x"}]}', "c53c1456bf2048c7d5c42ef8e332d78b0b44f0e0267fd559e14b33539e36832b"),
]


def test_rfc8785_vectors() -> None:
    for value, expected_bytes, expected_sha in VECTORS:
        assert canonical_bytes(value) == expected_bytes
        assert sha256_hex(value) == expected_sha
    # sanity: rfc8785.dumps matches our wrapper
        assert rfc8785.dumps(value) == expected_bytes
        # canonical bytes must parse back to same value
        assert json.loads(expected_bytes) == json.loads(canonical_bytes(value))
