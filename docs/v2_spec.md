# SudoAgent v2 Specification

Concise specification for v2 ledger semantics. Scope is documentation only; no code changes.

## Canonical JSON Rules
- UTF-8, LF line endings, no BOM, no trailing whitespace.
- Objects use lexicographic key order; arrays preserve author order.
- Serialization: no superfluous whitespace; separators are `:` and `,` only.
- Numbers: use decimal form, no exponent, no `NaN`/`Infinity`; strip leading `+` and leading zeros; keep a single `0` before the decimal point when needed; trim trailing fractional zeros and trailing decimal point.
- Strings are normalized to NFC; do not escape `/`; escape only when required by JSON.
- Timestamps are ISO 8601 UTC with `Z`, six microsecond digits: `YYYY-MM-DDTHH:MM:SS.ssssssZ`.
- `null` means "intentionally recorded unknown"; omit keys to mean "not provided".
- Redact sensitive fields before canonicalization, hashing, and logging.

## Ledger Entry Schema
Canonical object stored per request. All fields are required unless noted.

| Field | Type | Notes |
| --- | --- | --- |
| `version` | string | Literal `"2.0"`. |
| `request_id` | string | Unique per requested action. |
| `created_at` | timestamp | Canonical timestamp. |
| `prev_entry_hash` | string\|null | SHA-256 of prior canonical entry; `null` only for the first entry. |
| `entry_hash` | string | SHA-256 of this entry’s canonical JSON with `entry_hash` set to `null` during computation. |
| `decision` | object | See Decision block. |
| `outcome` | object | See Outcome block. |

### Decision Block (`decision`)
| Field | Type | Notes |
| --- | --- | --- |
| `policy_hash` | string | SHA-256 over canonicalized policy used. |
| `decision_hash` | string | SHA-256 defined in Decision Hash section. |
| `decision_at` | timestamp | When the policy decision was made. |
| `actor` | object | Identity of requester (e.g., `{"principal":"alice","source":"cli"}`). |
| `intent` | string | High-level action (e.g., `"deploy"`). |
| `resource` | object | Target description (e.g., `{"type":"service","name":"payments"}`). |
| `parameters` | object | Redacted parameters relevant to the decision. |
| `budget_check` | object | Budget preview result; see Budget Model. |

### Outcome Block (`outcome`)
| Field | Type | Notes |
| --- | --- | --- |
| `approved` | boolean | `false` on any error (fail-closed). |
| `approval` | object\|null | Details when `approved` is true; see Approval Binding. |
| `decision_effect` | string | `"allow"` or `"deny"` derived from policy. |
| `result` | object | Action outcome payload or error envelope (redacted as needed). |
| `budget_commit` | object\|null | Commit record when approval succeeded; see Budget Model. |

## Decision Hash
`decision_hash` is `SHA-256` over the canonical JSON of the object below, using the canonical rules above:

```json
{"actor":{...},"decision_at":"<ts>","intent":"<intent>","parameters":{...},"policy_hash":"<policy_hash>","request_id":"<request_id>","resource":{...},"version":"2.0"}
```

Notes:
- Exclude `decision_hash`, `prev_entry_hash`, `entry_hash`, outcome fields, and budgets except `budget_check` values included inside `parameters` if policy needs them.
- Redact before hashing.
- Any change to these fields changes `decision_hash`, forcing re-approval.

## Approval Binding
- Approval is valid only when `approval.binding == {"request_id":..., "policy_hash":..., "decision_hash":...}`.
- Store approver identity, mode, and `approved_at` timestamp inside `approval`.
- If the binding does not match the ledger entry, the entry is rejected and logged as denied.
- Approvals are single-use; reuse with a new `decision_hash` is invalid (fail-closed).

## Budget Model (Check → Commit)
- Check stage: `budget_check` records `{"check_id":..., "request_id":..., "limit":..., "projected_cost":..., "currency":"USD", "succeeded":bool, "checked_at":<ts>}`. It is idempotent by `request_id`.
- Commit stage: after approval and successful action, write `budget_commit` as `{"check_id":..., "request_id":..., "commit_id":..., "actual_cost":..., "currency":"USD", "committed_at":<ts>}`. Idempotent by `request_id` and `commit_id`; replay with same ids is a no-op, mismatched ids fail.
- If check fails or approval denies, commit is omitted and the entry remains deny/closed.

## Threat Model and Failure Modes
- Ledger tampering (edit, reorder, truncate): detected via `prev_entry_hash` chain and recomputation of `entry_hash`.
- Replay or drifted approvals: blocked by `decision_hash` binding and idempotent budget ids.
- Canonicalization ambiguity (float, timestamp, null): avoided by strict rules; reject non-conforming inputs.
- Redaction gaps: reject if sensitive fields are not redacted before hashing/logging.
- Time skew: use UTC and monotonic ordering; deny when timestamps are missing or malformed.
- Partial writes or I/O errors: treat as denial; do not emit incomplete entries.

## Example Canonical Ledger Entry
```json
{"created_at":"2026-01-25T12:00:00.000000Z","decision":{"actor":{"principal":"alice","source":"cli"},"budget_check":{"check_id":"chk-123","checked_at":"2026-01-25T11:59:59.500000Z","currency":"USD","limit":1000,"projected_cost":200,"request_id":"req-001","succeeded":true},"decision_at":"2026-01-25T12:00:00.000000Z","intent":"deploy","parameters":{"service":"payments"},"policy_hash":"c2f6...","request_id":"req-001","resource":{"type":"service","name":"payments"},"version":"2.0","decision_hash":"5b8c..."},"entry_hash":"9f44...","outcome":{"approved":true,"approval":{"approved_at":"2026-01-25T12:00:05.000000Z","approver":"bob","binding":{"decision_hash":"5b8c...","policy_hash":"c2f6...","request_id":"req-001"},"mode":"interactive"},"budget_commit":{"actual_cost":180,"check_id":"chk-123","commit_id":"cmt-123","committed_at":"2026-01-25T12:00:06.000000Z","currency":"USD","request_id":"req-001"},"decision_effect":"allow","result":{"status":"success"}},"prev_entry_hash":null,"request_id":"req-001","version":"2.0"}
```
