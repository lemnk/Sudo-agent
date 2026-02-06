# Threat Test Matrix

This matrix maps the SudoAgent threat model to automated checks in the repo.
It is intended to be used as a release gate for security-sensitive changes.

## Integrity and Tamper Detection

| Threat | Expected behavior | Tests |
|---|---|---|
| Entry payload tampering | Verification fails on hash mismatch | `tests/test_ledger_jsonl.py::test_tamper_detection_on_modified_line`, `tests/test_ledger_sqlite.py::test_tamper_detection_on_modified_entry` |
| Hash-column tampering | Verification fails on stored hash mismatch | `tests/test_ledger_sqlite.py::test_tamper_detection_on_hash_columns` |
| Chain reorder/deletion | Verification fails on `prev_entry_hash` mismatch | `tests/test_ledger_jsonl.py::test_deletion_breaks_chain`, `tests/test_ledger_jsonl.py::test_reordering_is_rejected` |
| Signature tampering | Verification fails with public key | `tests/test_ledger_signing.py::test_signature_verification_rejects_tampered_signature`, `tests/test_cli_signing.py::test_verify_with_public_key_rejects_tamper` |

## Replay and Binding Guarantees

| Threat | Expected behavior | Tests |
|---|---|---|
| Approval replay (wrong decision hash) | Fail-closed deny | `tests/test_engine.py::test_approval_binding_mismatch_decision_hash_fails_closed` |
| Approval replay (wrong policy hash) | Fail-closed deny | `tests/test_engine.py::test_approval_binding_mismatch_policy_hash_fails_closed` |
| Outcome replay/rewire | Unknown or mismatched decision reference is rejected | `tests/test_ledger_jsonl.py::test_outcome_decision_hash_unknown` |

## Redaction and Evidence Safety

| Threat | Expected behavior | Tests |
|---|---|---|
| Sensitive values leak into policy/evidence paths | Deterministic redaction before policy and logging | `tests/test_redaction.py`, `tests/test_engine.py` redaction-focused cases |
| Canonicalization drift | Hash input remains stable | `tests/test_jcs_vectors.py` |

## Async and Concurrency Safety

| Threat | Expected behavior | Tests |
|---|---|---|
| Sync engine called in active event loop | Explicit runtime error | `tests/test_engine.py` async-loop guard case |
| Async wrapper correctness | Async entry points execute successfully | `tests/test_async_utils.py`, `tests/test_async_approvers.py` |
| Budget idempotency under retries | No double charge on duplicate `request_id` | `tests/test_budgets.py::test_sqlite_budget_idempotent_commit` |

## Operational Controls

| Threat | Expected behavior | Tests |
|---|---|---|
| CLI exports fail on malformed or missing files | Non-zero exit with clear error path | `tests/test_cli_export.py`, `tests/test_cli_verify.py` |
| Key generation and receipt path regressions | Deterministic CLI behavior | `tests/test_cli_signing.py` |

## Release Gate

Use this minimum release gate before publish:

1. `python -m ruff check .`
2. `python -m mypy src`
3. `python -m pytest -q`
4. Verify CI matrix is green on Linux/macOS/Windows and Python 3.10/3.11/3.12.
