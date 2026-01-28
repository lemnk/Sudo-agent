# SudoAgent v2 Ledger Specification

This document defines the v2 ledger format, canonicalization rules, and hashing/verification behavior.

For a friendlier overview, see `docs/v2_ledger.md`.

## Canonical JSON rules

The ledger uses a strict canonical JSON encoding to keep hashes stable across runs and environments.

- Encoding: UTF-8.
- Objects:
  - keys must be strings
  - keys are NFC-normalized
  - keys are sorted lexicographically
  - duplicate keys after normalization are rejected
- Arrays preserve element order.
- Serialization has no superfluous whitespace (separators are `,` and `:`).
- Strings are NFC-normalized.
- Numbers:
  - integers are base-10
  - decimals are fixed-point (no exponent)
  - `NaN` / `Infinity` are rejected
  - floats are rejected; use `Decimal` for exact numbers
- Timestamps are UTC with microseconds: `YYYY-MM-DDTHH:MM:SS.ssssssZ`.
- Redaction happens before canonicalization, hashing, and logging.

## Ledger entry format (JSONL)

The ledger is newline-delimited JSON (one canonical JSON object per line).

Every entry includes these fields (some are added by the backend during append):

| Field | Type | Notes |
| --- | --- | --- |
| `schema_version` | string | Entry schema version (currently `"2.0"`). |
| `ledger_version` | string | Ledger format version (currently `"2.0"`). |
| `created_at` | timestamp | Canonical UTC timestamp. |
| `request_id` | string | Correlates decision and outcome for a call. |
| `event` | string | `"decision"` or `"outcome"`. |
| `action` | string | Fully qualified function identity. |
| `agent_id` | string | Identifier for the caller/agent. |
| `decision` | object | Always present; includes `decision_hash`. |
| `metadata` | object | Redacted args/kwargs snapshots (and other safe metadata). |
| `prev_entry_hash` | string\|null | Added during append; `null` only for the first entry. |
| `entry_hash` | string | Added during append; hash of the canonical entry. |
| `entry_signature` | string (optional) | Added when signing is enabled; signature over `entry_hash`. |

### Decision entries (`event == "decision"`)

Decision entries include:
- `decision.effect`: `"allow"` or `"deny"`
- `decision.reason`: human-readable reason
- `decision.reason_code`: stable code when provided
- `decision.policy_id`: stable policy identifier
- `decision.policy_hash`: SHA-256 of the canonical policy identifier
- `decision.decision_hash`: binding anchor for approvals and outcomes

If approval was involved, an `approval` block may be present:
- `approval.binding`: `{request_id, policy_hash, decision_hash}`
- `approval.approved`: boolean
- `approval.approver_id` (optional): approver identity

### Outcome entries (`event == "outcome"`)

Outcome entries include an `outcome` block:
- `outcome.status`: `"success"` or `"error"`
- `outcome.error_type` (optional): exception type name
- `outcome.error` (optional): truncated error message

Outcome entries must reference a known decision via:
- matching `decision.decision_hash`
- matching `request_id`

## Decision hash

`decision_hash` is `SHA-256` over the canonical JSON object below:

```json
{
  "version": "2.0",
  "request_id": "<uuid>",
  "decision_at": "<timestamp>",
  "policy_hash": "<policy_hash>",
  "intent": "<action>",
  "resource": {"type": "function", "name": "<action>"},
  "parameters": {"args": [...], "kwargs": {...}},
  "actor": {"principal": "unknown", "source": "python"}
}
```

Notes:
- The `parameters` object uses redacted args/kwargs.
- Any change to the decision payload changes `decision_hash` and forces re-approval.

## Entry hash and chaining

The backend computes `entry_hash` as:
- Take the full entry object and set:
  - `entry_hash` to `null`
  - `entry_signature` to `null` (if present)
- Canonicalize that object.
- Hash it with SHA-256 hex.

Each entry also stores `prev_entry_hash`, which must equal the prior entry's `entry_hash` (or `null` for the first entry).

## Verification behavior

Verification fails on:
- non-canonical lines
- schema/ledger version mismatches
- hash mismatches
- `prev_entry_hash` chain mismatches (tampering, gaps, or reorderings)
- outcome entries that reference an unknown decision hash
- outcome entries whose `request_id` does not match the referenced decision hash

When a public key is provided, verification also validates `entry_signature` for each entry.
